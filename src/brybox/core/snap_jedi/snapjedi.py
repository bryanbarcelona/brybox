from pathlib import Path
from typing import Optional
import filecmp

from .naming import PathStrategy
from .metadata import MetadataReader, ImageMetadata
from .converter import ImageMagickConverter, ConversionError
from ..models import ProcessResult
from ...utils.apple_files import AppleSidecarManager
from ...utils.health_check import is_image_healthy
from ...utils.logging import log_and_display, get_configured_logger
from ...events.bus import publish_file_renamed, publish_file_deleted

logger = get_configured_logger("SnapJedi")


class SnapJedi:
    """
    Image processor that normalizes photos to timestamped JPGs.
    
    Implements FileProcessor protocol for use with Pixelporter.
    """
    
    def __init__(
        self,
        metadata_reader: Optional[MetadataReader] = None,
        converter: Optional[ImageMagickConverter] = None,
        sidecar_manager: Optional[AppleSidecarManager] = None
    ):
        """
        Initialize processor with optional dependencies.
        
        Args:
            metadata_reader: Metadata extraction component (DI)
            converter: Image format converter (DI)
            sidecar_manager: Apple sidecar file handler (DI)
        """
        self._metadata_reader = metadata_reader or MetadataReader()
        self._converter = converter or ImageMagickConverter()
        self._sidecar_manager = sidecar_manager or AppleSidecarManager
        
        self._file_path: Optional[Path] = None
        self._metadata: Optional[ImageMetadata] = None
        self._is_healthy: bool = False
    
    def open(self, file_path: Path) -> None:
        """
        Open file for processing.
        
        Performs basic validation but does not read metadata yet.
        
        Args:
            file_path: Path to image file to process
            
        Raises:
            FileNotFoundError: If file doesn't exist
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not file_path.is_file():
            raise ValueError(f"Not a file: {file_path}")
        
        self._file_path = file_path
        logger.debug(f"Opened file: {file_path.name}")
    
    def process(self) -> ProcessResult:
        """
        Execute full processing pipeline.
        
        Pipeline:
        1. Delete Apple sidecars (pre-conversion cleanup)
        2. Read metadata (EXIF, GPS, timestamps)
        3. Convert HEIC → JPG (if needed)
        4. Delete original HEIC (after successful conversion + health check)
        5. Generate target path based on metadata
        6. Handle duplicates (delete if identical)
        7. Rename to target path
        8. Verify health of result
        9. Publish rename event
        10. Delete sidecars (post-rename cleanup)
        
        Returns:
            ProcessResult with outcome
        """
        if self._file_path is None:
            return ProcessResult(
                success=False,
                target_path=Path(),
                is_healthy=False,
                error_message="Must call open() before process()"
            )
        
        try:
            # Step 1: Delete Apple sidecars before conversion
            self._sidecar_manager.delete_sidecars(self._file_path)
            
            # Step 2: Read metadata (expensive - only do when processing)
            self._metadata = self._metadata_reader.extract_metadata(self._file_path)
            log_and_display(f"Read metadata from {self._file_path.name}", log=False)
            
            # Step 3 & 4: Convert HEIC → JPG if needed
            needs_conversion = self._file_path.suffix.lower() in ['.heic', '.heif']
            
            if needs_conversion:
                jpg_path = self._file_path.with_suffix('.jpg')
                
                try:
                    self._converter.convert_to_jpg(self._file_path, jpg_path)
                    log_and_display(f"Converted {self._file_path.name} to {jpg_path}")
                    
                    # Health check before deleting original
                    if is_image_healthy(jpg_path):
                        original_heic = self._file_path
                        self._file_path = jpg_path
                        original_heic_size = original_heic.stat().st_size
                        original_heic.unlink()
                        publish_file_deleted(str(original_heic), original_heic_size)
                        log_and_display(f"Deleted original HEIC: {original_heic.name}")
                    else:
                        return ProcessResult(
                            success=False,
                            target_path=self._file_path,
                            is_healthy=False,
                            error_message="Converted JPG failed health check"
                        )
                        
                except ConversionError as e:
                    return ProcessResult(
                        success=False,
                        target_path=self._file_path,
                        is_healthy=False,
                        error_message=f"Conversion failed: {e}"
                    )
            
            # At this point, we have a JPG (either converted or already was)
            if self._file_path.suffix.lower() not in ['.jpg', '.jpeg']:
                return ProcessResult(
                    success=False,
                    target_path=self._file_path,
                    is_healthy=False,
                    error_message=f"Unsupported format: {self._file_path.suffix}"
                )
            
            # Step 5: Generate target path based on metadata
            target_path = PathStrategy.generate_target_path(
                self._file_path,
                self._metadata.creation_date,
                self._metadata.time_offset
            )
            
            # Step 6: Handle duplicates
            if target_path.exists() and target_path != self._file_path:
                if self._are_files_identical(self._file_path, target_path):
                    # Duplicate detected - delete source, keep existing
                    source_size = self._file_path.stat().st_size
                    self._file_path.unlink()
                    publish_file_deleted(str(self._file_path), source_size)
                    log_and_display(f"Duplicate detected, deleted source: {self._file_path.name}")
                    
                    self._is_healthy = is_image_healthy(target_path)
                    
                    return ProcessResult(
                        success=True,
                        target_path=target_path,
                        is_healthy=self._is_healthy,
                        error_message=""
                    )
            
            # Step 7: Rename to target path (if different)
            if self._file_path != target_path:
                self._file_path.rename(target_path)
                log_and_display(f"Renamed to {target_path.name}")
                
                # Step 8: Verify health
                self._is_healthy = is_image_healthy(target_path)
                
                # Step 9: Publish rename event
                publish_file_renamed(
                    old_path=str(self._file_path),
                    new_path=str(target_path),
                    file_size=target_path.stat().st_size,
                    is_healthy=self._is_healthy
                )
                
                self._file_path = target_path
            
            else:
                self._is_healthy = is_image_healthy(self._file_path)
                log_and_display(f"No rename needed for {self._file_path.name}")
            # Step 10: Delete sidecars after rename
            self._sidecar_manager.delete_sidecars(self._file_path)
            
            return ProcessResult(
                success=True,
                target_path=target_path,
                is_healthy=self._is_healthy,
                error_message=""
            )
            
        except Exception as e:
            logger.error(f"Processing failed: {e}", exc_info=True)
            return ProcessResult(
                success=False,
                target_path=self._file_path,
                is_healthy=False,
                error_message=str(e)
            )
    
    def _are_files_identical(self, file1: Path, file2: Path) -> bool:
        """
        Check if two files have identical content.
        
        Args:
            file1: First file path
            file2: Second file path
            
        Returns:
            True if files are identical
        """
        return filecmp.cmp(str(file1), str(file2), shallow=False)