from pathlib import Path
from typing import Optional

from .naming import PathStrategy
from .metadata import MetadataReader, VideoMetadata
from .metadata_writer import MetadataWriter
from ..models import ProcessResult
from .converter import FFmpegConverter, ConversionError
from ...utils.apple_files import AppleSidecarManager
from ...utils.logging import get_configured_logger

logger = get_configured_logger("VideoSith")


class VideoSith:
    """
    Video processor that normalizes videos to timestamped MP4s.
    
    Handles:
    - MOV to MP4 conversion
    - MP4 renaming based on metadata
    - Metadata preservation and writing
    - Apple sidecar cleanup
    """
    
    def __init__(
        self,
        metadata_reader: Optional[MetadataReader] = None,
        metadata_writer: Optional[MetadataWriter] = None,
        converter: Optional[FFmpegConverter] = None,
        sidecar_manager: Optional[AppleSidecarManager] = None
    ):
        """
        Initialize processor with optional dependencies.
        
        Args:
            metadata_reader: Metadata extraction component (DI)
            metadata_writer: Metadata writing component (DI)
            converter: Video format converter (DI)
            sidecar_manager: Apple sidecar file handler (DI)
        """
        self._metadata_reader = metadata_reader or MetadataReader()
        self._metadata_writer = metadata_writer or MetadataWriter()
        self._converter = converter or FFmpegConverter()
        self._sidecar_manager = sidecar_manager or AppleSidecarManager
        
        self._file_path: Optional[Path] = None
        self._metadata: Optional[VideoMetadata] = None
    
    def process(self) -> ProcessResult:
        """Process video and return result."""
        if not self._file_path:
            return ProcessResult(
                success=False,
                target_path=Path(),  # Empty Path instead of None
                is_healthy=False,
                error_message="No file path"  # String instead of None
            )
        
        if self._file_path.suffix.lower() == '.mov':
            success = self.convert_to_mp4()
        else:
            self.rename_mp4()
            success = True
        
        return ProcessResult(
            success=success,
            target_path=self._file_path,
            is_healthy=True,
            error_message="Conversion failed" if not success else ""  # Empty string instead of None
        )

    def convert_to_mp4(self) -> bool:
        """
        Convert MOV file to MP4 and delete the original.
        
        Pipeline:
        1. Skip if already MP4
        2. Extract metadata from source
        3. Generate target path
        4. Convert MOV â†' MP4
        5. Write metadata to MP4
        6. Delete original MOV
        7. Clean up Apple sidecars
        
        Returns:
            True if conversion successful, False otherwise
        """
        if self._file_path is None:
            logger.error("Must call open() or set file path before conversion")
            return False
        
        # Skip if already MP4
        if self._file_path.suffix.lower() == ".mp4":
            logger.debug(f"{self._file_path.name} is already MP4, skipping conversion")
            return True
        
        try:
            # Step 1: Extract metadata from source
            self._metadata = self._metadata_reader.extract_metadata(self._file_path)
            logger.debug(f"Extracted metadata from {self._file_path.name}")
            
            # Step 2: Generate target path
            target_path = PathStrategy.generate_target_path(
                self._file_path,
                self._metadata.creation_date,
                self._metadata.time_offset
            )
            
            # Step 3: Convert to MP4
            self._converter.convert_to_mp4(self._file_path, target_path)
            logger.info(f"Converted {self._file_path.name} to {target_path.name}")
            
            # Step 4: Write metadata to new MP4
            self._write_metadata_to_file(target_path)
            
            # Step 5: Delete original MOV
            if self._file_path.exists():
                self._file_path.unlink()
                logger.info(f"Deleted original: {self._file_path.name}")
            
            # Step 6: Clean up Apple sidecars
            self._sidecar_manager.delete_sidecars(self._file_path)
            
            # Update internal path reference
            self._file_path = target_path
            
            return True
            
        except ConversionError as e:
            logger.error(f"Conversion failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during conversion: {e}", exc_info=True)
            return False
    
    def rename_mp4(self) -> None:
        """
        Rename MP4 file based on metadata.
        
        Pipeline:
        1. Skip if not MP4
        2. Extract metadata
        3. Generate target path
        4. Rename file
        5. Write metadata
        6. Clean up Apple sidecars
        """
        if self._file_path is None:
            logger.error("Must call open() or set file path before renaming")
            return
        
        # Skip if not MP4
        if self._file_path.suffix.lower() != ".mp4":
            logger.debug(f"{self._file_path.name} is not MP4, skipping rename")
            return
        
        try:
            # Step 1: Extract metadata
            self._metadata = self._metadata_reader.extract_metadata(self._file_path)
            logger.debug(f"Extracted metadata from {self._file_path.name}")
            
            # Step 2: Generate target path
            target_path = PathStrategy.generate_target_path(
                self._file_path,
                self._metadata.creation_date,
                self._metadata.time_offset
            )
            
            # Step 3: Rename if different
            if self._file_path != target_path:
                self._file_path.rename(target_path)
                logger.info(f"Renamed {self._file_path.name} to {target_path.name}")
                self._file_path = target_path
            else:
                logger.debug(f"No rename needed for {self._file_path.name}")
            
            # Step 4: Write metadata
            self._write_metadata_to_file(self._file_path)
            
            # Step 5: Clean up Apple sidecars
            self._sidecar_manager.delete_sidecars(self._file_path)
            
        except Exception as e:
            logger.error(f"Rename failed: {e}", exc_info=True)
    
    def _write_metadata_to_file(self, file_path: Path) -> None:
        """
        Write metadata to video file.
        
        Args:
            file_path: Path to video file
        """
        if self._metadata is None:
            logger.warning("No metadata to write")
            return
        
        # Write GPS coordinates if available
        if not (
            self._metadata.gps_latitude == 0 and 
            self._metadata.gps_longitude == 0 and 
            self._metadata.gps_altitude == 0
        ):
            try:
                self._metadata_writer.set_gps_coordinates(
                    file_path,
                    self._metadata.gps_latitude,
                    self._metadata.gps_longitude,
                    self._metadata.gps_altitude
                )
            except Exception as e:
                logger.warning(f"Failed to write GPS coordinates: {e}")
        
        # Write creation date if available
        if self._metadata.creation_date is not None:
            try:
                self._metadata_writer.set_creation_date(
                    file_path,
                    self._metadata.creation_date,
                    self._metadata.time_offset
                )
            except Exception as e:
                logger.warning(f"Failed to write creation date: {e}")
    
    @property
    def file_path(self) -> Optional[Path]:
        """Get current file path."""
        return self._file_path
    
    @file_path.setter
    def file_path(self, path: Path) -> None:
        """Set file path for processing."""
        self._file_path = Path(path)
    
    def open(self, file_path: Path) -> None:
        """
        Open file for processing.
        
        Args:
            file_path: Path to video file to process
            
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


def main():
    """Example usage."""
    # Create processor with default dependencies
    processor = VideoSith()
    
    # Process a MOV file
    mov_path = Path(r"D:\BryBoxTesting\VideoSithTest\IMG_4805.MOV")
    
    if mov_path.exists():
        processor.file_path = mov_path
        processor.convert_to_mp4()
    
    # Process an MP4 file
    mp4_path = Path(r"D:\Tester\video_1_782a1bb28883426098879924e05bd747.mp4")
    
    if mp4_path.exists():
        processor.file_path = mp4_path
        processor.rename_mp4()


if __name__ == "__main__":
    main()