import traceback
from pathlib import Path

from brybox.core.models import ProcessResult
from brybox.core.videosith.converter import FFmpegConverter
from brybox.core.videosith.metadata import MetadataReader, VideoMetadata
from brybox.core.videosith.metadata_writer import MetadataWriter
from brybox.core.videosith.naming import PathStrategy
from brybox.events.bus import publish_file_deleted, publish_file_renamed
from brybox.exceptions.videos import (
    VideoSithConversionError,
    VideoSithError,
    VideoSithFileOperationError,
    VideoSithMetadataParseError,
    VideoSithMetadataReadError,
    VideoSithMetadataWriteError,
    VideoSithToolNotFoundError,
    VideoSithVideoNotFoundError,
)
from brybox.utils.apple_files import AppleSidecarManager
from brybox.utils.logging import get_configured_logger, log_and_display

logger = get_configured_logger('VideoSith')


class VideoSith:
    """
    Video processor that normalizes videos to timestamped MP4s.

    This is an ORCHESTRATOR component - it catches worker exceptions,
    logs them ONCE, and returns ProcessResult.
    """

    def __init__(
        self,
        metadata_reader: MetadataReader | None = None,
        metadata_writer: MetadataWriter | None = None,
        converter: FFmpegConverter | None = None,
        sidecar_manager: AppleSidecarManager | None = None,
    ) -> None:
        """
        Initialize processor with optional dependencies.

        Args:
            metadata_reader: Metadata extraction component (DI)
            metadata_writer: Metadata writing component (DI)
            converter: Video format converter (DI)
            sidecar_manager: Apple sidecar file handler (DI)

        Raises:
            VideoSithToolNotFoundError: If required tools are missing (fatal)
        """
        print('NEW VIDEOSITH HERE')
        try:
            self._metadata_reader = metadata_reader or MetadataReader()
            self._metadata_writer = metadata_writer or MetadataWriter()
            self._converter = converter or FFmpegConverter()
        except VideoSithToolNotFoundError as e:
            log_and_display(f'🔧 Missing required tool: {e}', level='error')
            raise  # Fatal - can't proceed

        self._sidecar_manager = sidecar_manager or AppleSidecarManager

        self._file_path: Path | None = None
        self._metadata: VideoMetadata | None = None
        self._is_healthy: bool = False

    def open(self, file_path: Path) -> None:
        """
        Open file for processing.

        Args:
            file_path: Path to video file to process

        Raises:
            VideoSithVideoNotFoundError: If file doesn't exist
            VideoSithFileOperationError: If path is not a file
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise VideoSithVideoNotFoundError(f'File not found: {file_path}', video_path=file_path)

        if not file_path.is_file():
            raise VideoSithFileOperationError(f'Not a file: {file_path}', source_path=file_path)

        self._file_path = file_path
        log_and_display(f'Opened file: {file_path.name}', log=False)

    def process(self) -> ProcessResult:
        """Execute full processing pipeline."""
        if self._file_path is None:
            return ProcessResult(
                success=False, target_path=Path(), is_healthy=False, error_message='Must call open() before process()'
            )

        # Delete Apple sidecars before processing
        try:
            self._sidecar_manager.delete_sidecars(self._file_path)
        except (OSError, PermissionError, FileNotFoundError) as e:
            log_and_display(f'⚠️ Failed to delete sidecars: {e}', level='warning', log=True)
            # Non-fatal - continue

        # Route based on file type - clean separation
        if self._file_path.suffix.lower() == '.mov':
            return self._process_mov()
        else:
            return self._process_mp4()

    def _process_mov(self) -> ProcessResult:
        """Process MOV file: convert to MP4 and rename."""
        original_path = self._file_path
        original_size = original_path.stat().st_size if original_path.exists() else 0

        try:
            # Step 1: Extract metadata from source
            try:
                self._metadata = self._metadata_reader.extract_metadata(original_path)
                log_and_display(f'📷 Extracted metadata from {original_path.name}', log=False)
            except VideoSithMetadataReadError as e:
                log_and_display(f'❌ Failed to read metadata from {original_path.name}: {e}', level='error')
                return ProcessResult(success=False, target_path=original_path, is_healthy=False, error_message=str(e))
            except VideoSithMetadataParseError as e:
                log_and_display(f'⚠️ Partial metadata for {original_path.name}: {e}', level='warning')
                self._metadata = VideoMetadata()  # Empty metadata

            # Step 2: Generate target path
            target_path = PathStrategy.generate_target_path(
                original_path,
                self._metadata.creation_date if self._metadata else None,
                self._metadata.time_offset if self._metadata else None,
            )

            # Step 3: Convert to MP4
            try:
                self._converter.convert_to_mp4(original_path, target_path)
                log_and_display(f'🎬 Converted {original_path.name} to {target_path.name}')
            except VideoSithConversionError as e:
                log_and_display(f'❌ Conversion failed: {e}', level='error')
                return ProcessResult(success=False, target_path=original_path, is_healthy=False, error_message=str(e))

            # Step 4: Write metadata to new MP4
            self._write_metadata_to_file(target_path)

            # Step 5: Health check - using image checker temporarily (always True)
            # TODO: Implement proper video health check
            self._is_healthy = True  # Match old behavior until video health check exists

            # Step 6: Delete original MOV
            try:
                original_path.unlink()
                log_and_display(f'🗑️ Deleted original: {original_path.name}')
                publish_file_deleted(str(original_path), original_size)
            except (OSError, PermissionError) as e:
                log_and_display(f'⚠️ Failed to delete original: {e}', level='warning')
                # Non-fatal - continue

            # Step 7: Clean up Apple sidecars
            try:
                self._sidecar_manager.delete_sidecars(original_path)
            except (OSError, PermissionError, FileNotFoundError) as e:
                log_and_display(f'⚠️ Failed to delete sidecars: {e}', level='warning', log=True)
                # Non-fatal - continue

            # Step 8: Publish rename event (original → target)
            publish_file_renamed(
                old_path=str(original_path),
                new_path=str(target_path),
                file_size=target_path.stat().st_size,
                is_healthy=self._is_healthy,
            )

            self._file_path = target_path
            return ProcessResult(success=True, target_path=target_path, is_healthy=self._is_healthy, error_message='')

        except VideoSithError as e:
            # Expected domain errors - already logged at point of occurrence
            return ProcessResult(success=False, target_path=original_path, is_healthy=False, error_message=str(e))
        except Exception as e:  # noqa: BLE001
            # Unexpected errors - log with traceback
            log_and_display(f'💥 Unexpected error processing {original_path.name}: {e}', level='error')

            traceback.print_exc()
            return ProcessResult(
                success=False, target_path=original_path, is_healthy=False, error_message=f'Unexpected error: {e}'
            )

    def _process_mp4(self) -> ProcessResult:
        """Process MP4 file: rename based on metadata."""
        original_path = self._file_path

        try:
            # Step 1: Extract metadata
            try:
                self._metadata = self._metadata_reader.extract_metadata(original_path)
                log_and_display(f'📷 Extracted metadata from {original_path.name}', log=False)
            except VideoSithMetadataReadError as e:
                log_and_display(f'❌ Failed to read metadata from {original_path.name}: {e}', level='error')
                return ProcessResult(success=False, target_path=original_path, is_healthy=False, error_message=str(e))
            except VideoSithMetadataParseError as e:
                log_and_display(f'⚠️ Partial metadata for {original_path.name}: {e}', level='warning')
                self._metadata = VideoMetadata()  # Empty metadata

            # Step 2: Generate target path
            target_path = PathStrategy.generate_target_path(
                original_path,
                self._metadata.creation_date if self._metadata else None,
                self._metadata.time_offset if self._metadata else None,
            )

            # Step 3: Health check - using image checker temporarily (always True)
            # TODO: Implement proper video health check
            self._is_healthy = True  # Match old behavior until video health check exists

            # Step 4: Rename if different
            if original_path != target_path:
                try:
                    original_path.rename(target_path)
                    log_and_display(f'📁 Renamed to {target_path.name}')

                    publish_file_renamed(
                        old_path=str(original_path),
                        new_path=str(target_path),
                        file_size=target_path.stat().st_size,
                        is_healthy=self._is_healthy,
                    )

                    self._file_path = target_path
                except (OSError, PermissionError) as e:
                    log_and_display(f'❌ Failed to rename: {e}', level='error')
                    return ProcessResult(
                        success=False, target_path=original_path, is_healthy=False, error_message=f'Rename failed: {e}'
                    )
            else:
                log_and_display(f'No rename needed for {original_path.name}', log=False)
                self._file_path = original_path

            # Step 5: Write metadata
            self._write_metadata_to_file(self._file_path)

            # Step 6: Clean up Apple sidecars
            try:
                self._sidecar_manager.delete_sidecars(self._file_path)
            except (OSError, PermissionError, FileNotFoundError) as e:
                log_and_display(f'⚠️ Failed to delete sidecars: {e}', level='warning', log=True)
                # Non-fatal - continue

            return ProcessResult(
                success=True, target_path=self._file_path, is_healthy=self._is_healthy, error_message=''
            )

        except VideoSithError as e:
            # Expected domain errors - already logged
            return ProcessResult(success=False, target_path=original_path, is_healthy=False, error_message=str(e))
        except Exception as e:  # noqa: BLE001
            # Unexpected errors - log with traceback
            log_and_display(f'💥 Unexpected error processing {original_path.name}: {e}', level='error')

            traceback.print_exc()
            return ProcessResult(
                success=False, target_path=original_path, is_healthy=False, error_message=f'Unexpected error: {e}'
            )

    def _write_metadata_to_file(self, file_path: Path) -> None:
        """Write metadata to video file (best effort)."""
        if self._metadata is None:
            return

        # Write GPS coordinates if available
        if not (
            self._metadata.gps_latitude == 0 and self._metadata.gps_longitude == 0 and self._metadata.gps_altitude == 0
        ):
            try:
                self._metadata_writer.set_gps_coordinates(
                    file_path, self._metadata.gps_latitude, self._metadata.gps_longitude, self._metadata.gps_altitude
                )
                log_and_display(f'📍 Wrote GPS coordinates to {file_path.name}', log=False)
            except VideoSithMetadataWriteError as e:
                log_and_display(f'⚠️ Failed to write GPS coordinates: {e}', level='warning')
            except VideoSithFileOperationError as e:
                log_and_display(f'⚠️ File error writing GPS: {e}', level='warning')

        # Write creation date if available
        if self._metadata.creation_date is not None:
            try:
                self._metadata_writer.set_creation_date(
                    file_path, self._metadata.creation_date, self._metadata.time_offset
                )
                log_and_display(f'📅 Wrote creation date to {file_path.name}', log=False)
            except VideoSithMetadataWriteError as e:
                log_and_display(f'⚠️ Failed to write creation date: {e}', level='warning')
            except VideoSithFileOperationError as e:
                log_and_display(f'⚠️ File error writing date: {e}', level='warning')

    @property
    def file_path(self) -> Path | None:
        """Get current file path."""
        return self._file_path

    @file_path.setter
    def file_path(self, path: Path) -> None:
        """Set file path for processing."""
        self._file_path = Path(path)
