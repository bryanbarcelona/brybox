import filecmp
from pathlib import Path

from brybox.core.models import ProcessResult
from brybox.core.snap_jedi.converter import ImageMagickConverter
from brybox.core.snap_jedi.metadata import ImageMetadata, MetadataReader
from brybox.core.snap_jedi.naming import PathStrategy
from brybox.events.bus import publish_file_deleted, publish_file_renamed
from brybox.exceptions.images import (
    SnapJediConversionError,
    SnapJediConversionFailedError,
    SnapJediConversionTimeoutError,
    SnapJediError,
    SnapJediFileOperationError,
    SnapJediImageNotFoundError,
    SnapJediMetadataError,
    SnapJediMetadataParseError,
    SnapJediMetadataReadError,
    SnapJediToolNotFoundError,
)
from brybox.utils.apple_files import AppleSidecarManager
from brybox.utils.health_check import is_image_healthy
from brybox.utils.logging import get_configured_logger, log_and_display

logger = get_configured_logger('SnapJedi')


class SnapJedi:
    """
    Image processor that normalizes photos to timestamped JPGs.

    Implements FileProcessor protocol for use with Pixelporter.
    """

    def __init__(
        self,
        metadata_reader: MetadataReader | None = None,
        converter: ImageMagickConverter | None = None,
        sidecar_manager: AppleSidecarManager | None = None,
    ):
        """
        Initialize processor with optional dependencies.

        Args:
            metadata_reader: Metadata extraction component (DI)
            converter: Image format converter (DI)
            sidecar_manager: Apple sidecar file handler (DI)

        Raises:
            SnapJediToolNotFoundError: If required tools (exiftool/ImageMagick) are missing
        """
        try:
            self._metadata_reader = metadata_reader or MetadataReader()
            self._converter = converter or ImageMagickConverter()
        except SnapJediToolNotFoundError as e:
            log_and_display(f'🔧 Missing required tool: {e}', level='error')
            raise  # Fatal error - can't proceed

        self._sidecar_manager = sidecar_manager or AppleSidecarManager

        self._file_path: Path | None = None
        self._metadata: ImageMetadata | None = None
        self._is_healthy: bool = False

    def open(self, file_path: Path) -> None:
        """
        Open file for processing.

        Performs basic validation but does not read metadata yet.

        Args:
            file_path: Path to image file to process

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If path is not a file
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise SnapJediImageNotFoundError(f'File not found: {file_path}', image_path=file_path)

        if not file_path.is_file():
            raise SnapJediFileOperationError(f'Not a file: {file_path}', source_path=file_path)

        self._file_path = file_path
        log_and_display(f'Opened file: {file_path.name}', log=False)

    def process(self) -> ProcessResult:
        """Execute full processing pipeline."""
        if self._file_path is None:
            return ProcessResult(
                success=False, target_path=Path(), is_healthy=False, error_message='Must call open() before process()'
            )

        # Step 1: Delete Apple sidecars before conversion
        self._sidecar_manager.delete_sidecars(self._file_path)

        # Step 2: Read metadata
        metadata_result = self._extract_metadata()
        if metadata_result:
            return metadata_result

        # Step 3 & 4: Convert HEIC → JPG if needed
        conversion_result = self._handle_conversion_if_needed()
        if conversion_result and not conversion_result.success:
            return conversion_result

        # Validate format
        if self._file_path.suffix.lower() not in {'.jpg', '.jpeg'}:
            return ProcessResult(
                success=False,
                target_path=self._file_path,
                is_healthy=False,
                error_message=f'Unsupported format: {self._file_path.suffix}',
            )

        # Steps 5-10: Generate target, handle duplicates, rename, cleanup
        try:
            return self._execute_post_conversion_steps()
        except Exception as e:  # noqa
            if isinstance(e, SnapJediError):
                log_and_display(f'❌ SnapJedi error: {e}', level='error')
            else:
                log_and_display(
                    f'💥 Unexpected error processing {self._file_path.name if self._file_path else "file"}: {e}',
                    level='error',
                )
            return ProcessResult(success=False, target_path=self._file_path, is_healthy=False, error_message=str(e))

    def _execute_post_conversion_steps(self) -> ProcessResult:
        """Execute steps after conversion: duplicate handling, rename, cleanup."""
        # Step 5 & 6: Generate target path and handle duplicates
        duplicate_result = self._generate_and_check_duplicate()
        if duplicate_result:
            return duplicate_result

        # Steps 7-10: Rename, verify health, publish event, delete sidecars
        return self._finalize_processing()

    def _extract_metadata(self) -> ProcessResult | None:
        """Extract metadata, returning ProcessResult on failure or None on success."""
        try:
            self._metadata = self._metadata_reader.extract_metadata(self._file_path)
        except SnapJediImageNotFoundError:
            return ProcessResult(
                success=False,
                target_path=self._file_path,
                is_healthy=False,
                error_message=f'Image file disappeared: {self._file_path.name}',
            )
        except SnapJediMetadataReadError as e:
            log_and_display(f'📄 Failed to read metadata from {self._file_path.name}', level='warning')
            return ProcessResult(
                success=False,
                target_path=self._file_path,
                is_healthy=False,
                error_message=f'Metadata read failed: {e}',
            )
        except SnapJediMetadataParseError as e:
            log_and_display(f'⚠️  Could not parse {e.field} from {self._file_path.name}', level='warning')
            return None  # Continue with partial metadata
        except SnapJediMetadataError as e:
            log_and_display(f'📄 Metadata error for {self._file_path.name}: {e}', level='warning')
            return ProcessResult(success=False, target_path=self._file_path, is_healthy=False, error_message=str(e))
        else:  # This runs only if no exception occurred
            log_and_display(f'📷 Read metadata from {self._file_path.name}', log=False)
            return None

    def _handle_conversion_if_needed(self) -> ProcessResult | None:
        """Handle HEIC to JPG conversion if needed."""
        if self._file_path.suffix.lower() not in {'.heic', '.heif'}:
            return None

        jpg_path = self._file_path.with_suffix('.jpg')
        return self._handle_conversion(self._file_path, jpg_path)

    def _generate_and_check_duplicate(self) -> ProcessResult | None:
        """Generate target path and handle duplicates."""
        target_path = PathStrategy.generate_target_path(
            self._file_path,
            self._metadata.creation_date if self._metadata else None,
            self._metadata.time_offset if self._metadata else None,
        )

        self._target_path = target_path

        if (
            target_path.exists()
            and target_path != self._file_path
            and self._are_files_identical(self._file_path, target_path)
        ):
            return self._handle_duplicate(self._file_path, target_path)

        return None

    def _finalize_processing(self) -> ProcessResult:
        """Rename file, verify health, publish event, and clean up sidecars."""
        target_path = self._target_path

        if self._file_path != target_path:
            try:
                self._file_path.rename(target_path)
                log_and_display(f'📁 Renamed to {target_path.name}')

                self._is_healthy = is_image_healthy(target_path)

                publish_file_renamed(
                    old_path=str(self._file_path),
                    new_path=str(target_path),
                    file_size=target_path.stat().st_size,
                    is_healthy=self._is_healthy,
                )

                self._file_path = target_path

            except (PermissionError, OSError) as e:
                log_and_display(f'💾 Failed to rename {self._file_path.name}: {e}', level='error')
                return ProcessResult(
                    success=False,
                    target_path=self._file_path,
                    is_healthy=False,
                    error_message=f'Rename failed: {e}',
                )
        else:
            self._is_healthy = is_image_healthy(self._file_path)
            log_and_display(f'✅ No rename needed for {self._file_path.name}')

        # Delete sidecars after rename
        self._sidecar_manager.delete_sidecars(self._file_path)

        return ProcessResult(success=True, target_path=target_path, is_healthy=self._is_healthy, error_message='')

    def _handle_conversion(self, source: Path, target: Path) -> ProcessResult:
        """Handle HEIC to JPG conversion with proper error handling."""
        try:
            self._converter.convert_to_jpg(source, target)
            log_and_display(f'🎨 Converted {source.name} to {target.name}')

            # Health check before deleting original
            if is_image_healthy(target):
                original_heic = source
                self._file_path = target
                original_heic_size = original_heic.stat().st_size
                original_heic.unlink()
                publish_file_deleted(str(original_heic), original_heic_size)
                log_and_display(f'🗑️ Deleted original HEIC: {original_heic.name}')
                return ProcessResult(success=True, target_path=target, is_healthy=True, error_message='')
            else:
                return ProcessResult(
                    success=False,
                    target_path=source,
                    is_healthy=False,
                    error_message='Converted JPG failed health check',
                )

        except SnapJediConversionTimeoutError as e:
            log_and_display(f'⏱️ Conversion timed out for {source.name}', level='warning')
            return ProcessResult(
                success=False,
                target_path=source,
                is_healthy=False,
                error_message=f'Conversion timeout after {e.timeout_seconds}s',
            )
        except SnapJediConversionFailedError as e:
            log_and_display(f'❌ Conversion failed for {source.name}', level='warning')
            if e.stderr:
                log_and_display(f'Converter stderr: {e.stderr}')
            return ProcessResult(success=False, target_path=source, is_healthy=False, error_message=str(e))
        except SnapJediConversionError as e:
            log_and_display(f'❌ Conversion error for {source.name}: {e}', level='warning')
            return ProcessResult(success=False, target_path=source, is_healthy=False, error_message=str(e))
        except SnapJediFileOperationError as e:
            log_and_display(f'💾 File operation failed during conversion: {e}', level='error')
            return ProcessResult(success=False, target_path=source, is_healthy=False, error_message=str(e))

    def _handle_duplicate(self, source: Path, existing_target: Path) -> ProcessResult:
        """Handle duplicate file detection."""
        try:
            source_size = source.stat().st_size
            source.unlink()
            publish_file_deleted(str(source), source_size)
            log_and_display(f'🔄 Duplicate detected, deleted source: {source.name}')

            self._is_healthy = is_image_healthy(existing_target)
            self._file_path = existing_target

            return ProcessResult(
                success=True, target_path=existing_target, is_healthy=self._is_healthy, error_message=''
            )
        except (PermissionError, OSError) as e:
            log_and_display(f'💾 Failed to delete duplicate {source.name}: {e}', level='error')
            return ProcessResult(
                success=False, target_path=source, is_healthy=False, error_message=f'Failed to delete duplicate: {e}'
            )

    @staticmethod
    def _are_files_identical(file1: Path, file2: Path) -> bool:
        """
        Check if two files have identical content.

        Args:
            file1: First file path
            file2: Second file path

        Returns:
            True if files are identical
        """
        return filecmp.cmp(str(file1), str(file2), shallow=False)
