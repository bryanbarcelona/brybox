from datetime import datetime
from pathlib import Path
from typing import Optional
import subprocess
import shutil

from ...utils.logging import get_configured_logger

logger = get_configured_logger("VideoMetadataWriter")


class MetadataWriteError(Exception):
    """Raised when metadata writing fails."""
    pass


class MetadataWriter:
    """
    Writes metadata to video files using ExifTool.
    
    Handles:
    - Setting creation date with timezone offset
    - Setting GPS coordinates
    """
    
    def __init__(self, exiftool_path: Optional[str] = None):
        """
        Initialize metadata writer.
        
        Args:
            exiftool_path: Path to exiftool binary. If None, attempts to find it.
        """
        self.exiftool_path = exiftool_path or self._find_exiftool()
    
    def set_creation_date(
        self,
        file_path: Path,
        creation_date: datetime,
        time_offset: Optional[int] = None
    ) -> None:
        """
        Set creation date with timezone offset on video file.
        
        Args:
            file_path: Path to video file
            creation_date: Creation datetime (naive)
            time_offset: Timezone offset in hours (e.g., -5 for EST)
            
        Raises:
            MetadataWriteError: If writing fails
        """
        # Format time offset string
        if time_offset is not None:
            if time_offset < 0:
                offset_str = f'-{abs(time_offset):02d}:00"'
            else:
                offset_str = f'+{time_offset:02d}:00"'
        else:
            offset_str = '"'
        
        # Build date parameter
        date_str = creation_date.strftime("%Y:%m:%d %H:%M:%S")
        date_param = f'-QuickTime:CreationDate="{date_str}' + offset_str
        
        # Build command
        command = [
            self.exiftool_path,
            '-m',  # Ignore minor errors
            '-P',  # Preserve file modification date
            '-overwrite_original_in_place',
            date_param,
            f'"{file_path}"'
        ]
        
        # Join command (ExifTool quirk - needs shell parsing for complex params)
        command_str = " ".join(command)
        
        try:
            result = subprocess.run(
                command_str,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info(f"Set creation date on {file_path.name}")
            else:
                raise MetadataWriteError(
                    f"ExifTool returned error code: {result.returncode}"
                )
                
        except subprocess.TimeoutExpired:
            raise MetadataWriteError("Setting creation date timed out")
        except Exception as e:
            raise MetadataWriteError(f"Failed to set creation date: {str(e)}")
    
    def set_gps_coordinates(
        self,
        file_path: Path,
        latitude: float,
        longitude: float,
        altitude: float
    ) -> None:
        """
        Set GPS coordinates on video file.
        
        Args:
            file_path: Path to video file
            latitude: GPS latitude
            longitude: GPS longitude
            altitude: GPS altitude
            
        Raises:
            MetadataWriteError: If writing fails
        """
        # Skip if coordinates are all zeros (invalid)
        if latitude == 0 and longitude == 0 and altitude == 0:
            logger.debug(f"Skipping GPS write for {file_path.name} (no valid coords)")
            return
        
        # Build GPS parameter
        gps_param = f'-QuickTime:GPSCoordinates="{latitude}, {longitude}, {altitude}"'
        
        # Build command
        command = [
            self.exiftool_path,
            '-m',
            '-P',
            '-overwrite_original_in_place',
            gps_param,
            str(file_path)
        ]
        
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info(f"Set GPS coordinates on {file_path.name}")
            else:
                raise MetadataWriteError(
                    f"ExifTool returned error code: {result.returncode}"
                )
                
        except subprocess.TimeoutExpired:
            raise MetadataWriteError("Setting GPS coordinates timed out")
        except Exception as e:
            raise MetadataWriteError(f"Failed to set GPS coordinates: {str(e)}")
    
    def _find_exiftool(self) -> str:
        """
        Locate exiftool binary.
        
        Returns:
            Path to exiftool
            
        Raises:
            RuntimeError: If exiftool not found
        """
        if shutil.which("exiftool"):
            return "exiftool"
        
        raise RuntimeError(
            "exiftool not found. Install exiftool and add to PATH."
        )
