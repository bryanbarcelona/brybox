import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from brybox.exceptions.videos import (
    VideoSithFileOperationError,
    VideoSithMetadataWriteError,
    VideoSithToolNotFoundError,
)
from brybox.utils.logging import get_configured_logger

logger = get_configured_logger('VideoMetadataWriter')


class MetadataWriteError(Exception):
    """Raised when metadata writing fails."""


class MetadataWriter:
    """
    Writes metadata to video files using ExifTool.

    Handles:
    - Setting creation date with timezone offset
    - Setting GPS coordinates
    """

    def __init__(self, exiftool_path: str | None = None):
        """
        Initialize metadata writer.

        Args:
            exiftool_path: Path to exiftool binary. If None, attempts to find it.
        """
        self.exiftool_path = exiftool_path or self._find_exiftool()

    def set_creation_date(self, file_path: Path, creation_date: datetime, time_offset: int | None = None) -> None:
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
        offset_str = (
            f'-{abs(time_offset):02d}:00"'
            if time_offset is not None and time_offset < 0
            else f'+{time_offset:02d}:00"'
            if time_offset is not None and time_offset >= 0
            else '"'
        )

        # Build date parameter - ExifTool expects specific format
        date_str = creation_date.strftime('%Y:%m:%d %H:%M:%S')
        date_param = f'-QuickTime:CreationDate={date_str}{offset_str}'

        # Build command
        cmd = [
            self.exiftool_path,
            '-m',  # Ignore minor errors
            '-P',  # Preserve file modification date
            '-overwrite_original_in_place',
            date_param,
            str(file_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                check=False,  # We'll check return code manually
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                raise VideoSithMetadataWriteError(
                    f'Failed to set creation date on {file_path.name}: ExifTool returned {result.returncode}',
                    video_path=file_path,
                    stderr=result.stderr,
                )

        except subprocess.TimeoutExpired as e:
            raise VideoSithMetadataWriteError(
                f'Setting creation date timed out after 30s for {file_path.name}',
                video_path=file_path,
                timeout_seconds=30,
            ) from e
        except (OSError, PermissionError) as e:
            raise VideoSithFileOperationError(
                f'File operation failed while setting creation date: {e}', source_path=file_path
            ) from e

    def set_gps_coordinates(self, file_path: Path, latitude: float, longitude: float, altitude: float) -> None:
        """
        Set GPS coordinates on video file.

        Args:
            file_path: Path to video file
            latitude: GPS latitude
            longitude: GPS longitude
            altitude: GPS altitude

        Raises:
            VideoSithMetadataWriteError: If writing fails
            VideoSithFileOperationError: If file operations fail
        """
        # Skip if coordinates are all zeros (invalid)
        if latitude == 0 and longitude == 0 and altitude == 0:
            return  # Not an error, just nothing to write

        # Build GPS parameter
        gps_param = f'-QuickTime:GPSCoordinates="{latitude}, {longitude}, {altitude}"'

        cmd = [
            self.exiftool_path,
            '-m',
            '-P',
            '-overwrite_original_in_place',
            gps_param,
            str(file_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                raise VideoSithMetadataWriteError(
                    f'Failed to set GPS coordinates on {file_path.name}: ExifTool returned {result.returncode}',
                    video_path=file_path,
                    stderr=result.stderr,
                )

        except subprocess.TimeoutExpired as e:
            raise VideoSithMetadataWriteError(
                f'Setting GPS coordinates timed out after 30s for {file_path.name}',
                video_path=file_path,
                timeout_seconds=30,
            ) from e
        except (OSError, PermissionError) as e:
            raise VideoSithFileOperationError(
                f'File operation failed while setting GPS coordinates: {e}', source_path=file_path
            ) from e

    @staticmethod
    def _find_exiftool() -> str:
        """
        Locate exiftool binary.

        Returns:
            Path to exiftool

        Raises:
            VideoSithToolNotFoundError: If exiftool not found
        """
        if shutil.which('exiftool'):
            return 'exiftool'

        raise VideoSithToolNotFoundError('exiftool not found. Install exiftool and add to PATH.', tool_name='exiftool')
