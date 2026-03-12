import contextlib
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import exiftool
import pytz
from exiftool.exceptions import ExifToolExecuteError
from timezonefinder import TimezoneFinder

from brybox.core.models.videos import VideoMetadata
from brybox.exceptions.videos import (
    VideoSithFilenameParseError,
    VideoSithMetadataParseError,
    VideoSithMetadataReadError,
    VideoSithTimezoneError,
    VideoSithToolNotFoundError,
    VideoSithVideoNotFoundError,
)
from brybox.utils.logging import get_configured_logger

logger = get_configured_logger('VideoMetadata')


class MetadataReader:
    """
    Reads and interprets video metadata from EXIF data.

    Handles:
    - EXIF parsing via exiftool
    - GPS coordinate extraction
    - Timezone calculation from GPS
    - Time offset determination
    - Filename date parsing

    The reader implements graceful degradation - if non-critical metadata
    parsing fails, it logs a warning and continues with partial data.
    """

    def __init__(self, exiftool_path: str | None = None):
        """
        Initialize metadata reader.

        Args:
            exiftool_path: Path to exiftool binary. If None, attempts to find it.

        Raises:
            VideoSithToolNotFoundError: If exiftool not found
        """
        self.exiftool_path = exiftool_path or self._find_exiftool()
        self.timezone_finder = TimezoneFinder()

    def extract_metadata(self, file_path: Path) -> VideoMetadata:
        """
        Extract all metadata from a video file.

        Returns:
            VideoMetadata (may be partial - None fields indicate missing data)

        Raises:
            VideoSithVideoNotFoundError: If file doesn't exist
            VideoSithMetadataReadError: If EXIF cannot be read
            VideoSithMetadataParseError: If critical metadata parsing fails
        """
        if not file_path.exists():
            raise VideoSithVideoNotFoundError(f'Video not found: {file_path}', video_path=file_path)

        # Read raw EXIF - fatal if this fails
        raw_exif = self._read_exif(file_path)

        # Extract each piece - let parse errors bubble up
        # The orchestrator (videosith.py) will decide what's fatal vs partial
        creation_date = self._extract_creation_date(raw_exif, file_path)
        gps_lat, gps_lon, gps_alt = self._extract_gps_coordinates(raw_exif)
        timezone = self._calculate_timezone(gps_lat, gps_lon, gps_alt, file_path)
        parsed_filename_date = self._parse_date_from_filename(file_path)
        time_offset = self._determine_time_offset(timezone, creation_date, parsed_filename_date, file_path)

        return VideoMetadata(
            creation_date=creation_date,
            gps_latitude=gps_lat,
            gps_longitude=gps_lon,
            gps_altitude=gps_alt,
            timezone=timezone,
            time_offset=time_offset,
            parsed_filename_date=parsed_filename_date,
            raw_exif=raw_exif,
        )

    @staticmethod
    def _read_exif(file_path: Path) -> dict:
        """Read raw EXIF data. Raises VideoSithMetadataReadError on failure."""
        try:
            with exiftool.ExifToolHelper() as et:
                return et.get_metadata(str(file_path))[0]
        except ExifToolExecuteError as e:
            raise VideoSithMetadataReadError(
                f'Failed to read EXIF from {file_path.name}: {e}', video_path=file_path, stderr=str(e)
            ) from e
        except IndexError as e:
            raise VideoSithMetadataReadError(
                f'Exiftool returned empty result for {file_path.name}', video_path=file_path
            ) from e

    @staticmethod
    def _extract_creation_date(raw_exif: dict, file_path: Path) -> datetime | None:
        """Extract creation date. Returns None if not found."""
        # Extract duration
        duration = timedelta()
        if 'QuickTime:MediaDuration' in raw_exif:
            with contextlib.suppress(TypeError, ValueError):
                duration = timedelta(seconds=raw_exif['QuickTime:MediaDuration'])

        # Try date keys in priority order
        date_keys = [
            'QuickTime:CreateDate',
            'QuickTime:MediaCreateDate',
            'QuickTime:TrackCreateDate',
            'QuickTime:FileModifyDate',
        ]

        for key in date_keys:
            if key in raw_exif:
                date_str = raw_exif[key]
                try:
                    creation_date = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
                    return creation_date - duration
                except ValueError:
                    # Bad format - try next key
                    continue
                except Exception as e:
                    raise VideoSithMetadataParseError(
                        f'Unexpected error parsing {key}: {e}', video_path=file_path, field=key
                    ) from e

        return None

    @staticmethod
    def _extract_gps_coordinates(raw_exif: dict) -> tuple[float, float, float]:
        """
        Extract GPS coordinates from EXIF data.

        Args:
            raw_exif: Raw EXIF dictionary

        Returns:
            Tuple of (latitude, longitude, altitude). Returns (0, 0, 0) if not found.
        """
        try:
            return (
                float(raw_exif.get('Composite:GPSLatitude', 0)),
                float(raw_exif.get('Composite:GPSLongitude', 0)),
                float(raw_exif.get('Composite:GPSAltitude', 0)),
            )
        except (TypeError, ValueError):
            return 0.0, 0.0, 0.0

    def _calculate_timezone(self, latitude: float, longitude: float, altitude: float, file_path: Path) -> str | None:
        """Calculate timezone from GPS coordinates."""
        if latitude == 0 and longitude == 0 and altitude == 0:
            return None

        try:
            return self.timezone_finder.timezone_at(lng=longitude, lat=latitude)
        except Exception as e:
            raise VideoSithTimezoneError(
                f'Failed to calculate timezone for {file_path.name}: {e}',
                video_path=file_path,
                coordinates=(latitude, longitude, altitude),
            ) from e

    @staticmethod
    def _parse_date_from_filename(file_path: Path) -> datetime | None:
        """Parse date from filename if present."""
        filename = file_path.stem
        date_match = re.search(r'\d{8}_\d{6}', filename)

        if not date_match:
            return None

        try:
            return datetime.strptime(date_match.group(), '%Y%m%d_%H%M%S')
        except ValueError as e:
            raise VideoSithFilenameParseError(
                f'Failed to parse date from filename: {filename}', video_path=file_path, filename=filename
            ) from e

    @staticmethod
    def _determine_time_offset(
        timezone: str | None, creation_date: datetime | None, parsed_filename_date: datetime | None, file_path: Path
    ) -> int | None:
        """
        Determine timezone offset in hours.

        Priority order:
        1. Calculate from timezone and creation_date
        2. If that fails and we have a filename date, calculate offset from difference

        Args:
            timezone: Timezone string from GPS
            creation_date: When video was taken (from EXIF)
            parsed_filename_date: Date parsed from filename (local time)

        Returns:
            Offset in hours from UTC, or None if cannot be determined
        """
        # Try calculating from timezone first
        if timezone and creation_date:
            try:
                tz = pytz.timezone(timezone)
                local_dt = tz.localize(creation_date, is_dst=None)
                delta = local_dt.utcoffset()
                if delta:
                    return int(delta.total_seconds() / 3600)
            except (pytz.UnknownTimeZoneError, pytz.NonExistentTimeError, pytz.AmbiguousTimeError):
                # Invalid timezone - try filename fallback
                pass
            except Exception as e:
                raise VideoSithMetadataParseError(
                    f'Unexpected error calculating timezone offset: {e}', video_path=file_path, field='timezone_offset'
                ) from e

        # Fallback: calculate from filename date
        if parsed_filename_date and creation_date:
            try:
                time_diff = parsed_filename_date - creation_date
                return int(time_diff.total_seconds() / 3600)
            except OverflowError:
                pass
            except TypeError:
                pass

        return None

    @staticmethod
    def _find_exiftool() -> str:
        """
        Locate exiftool binary.

        Returns:
            Path to exiftool

        Raises:
            RuntimeError: If exiftool not found
        """
        if shutil.which('exiftool'):
            return 'exiftool'

        raise VideoSithToolNotFoundError('exiftool not found. Install exiftool and add to PATH.', tool_name='exiftool')
