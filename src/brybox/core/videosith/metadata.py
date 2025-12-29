import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import exiftool
import pytz
from exiftool.exceptions import ExifToolExecuteError
from timezonefinder import TimezoneFinder

from ...utils.logging import get_configured_logger

logger = get_configured_logger('VideoMetadata')


@dataclass
class VideoMetadata:
    """
    Structured metadata extracted from a video.

    All fields are Optional since videos may lack metadata.
    """

    creation_date: datetime | None = None
    gps_latitude: float = 0.0
    gps_longitude: float = 0.0
    gps_altitude: float = 0.0
    timezone: str | None = None
    time_offset: int | None = None  # Hours from UTC
    parsed_filename_date: datetime | None = None  # Date from filename if present
    raw_exif: dict = field(default_factory=dict)


class MetadataReader:
    """
    Reads and interprets video metadata from EXIF data.

    Handles:
    - EXIF parsing via exiftool
    - GPS coordinate extraction
    - Timezone calculation from GPS
    - Time offset determination
    - Filename date parsing
    """

    def __init__(self, exiftool_path: str | None = None):
        """
        Initialize metadata reader.

        Args:
            exiftool_path: Path to exiftool binary. If None, attempts to find it.
        """
        self.exiftool_path = exiftool_path or self._find_exiftool()
        self.timezone_finder = TimezoneFinder()

    def extract_metadata(self, file_path: Path) -> VideoMetadata:
        """
        Extract all metadata from a video file.

        Args:
            file_path: Path to video file

        Returns:
            VideoMetadata with extracted information
        """
        # 1. Read raw EXIF
        raw_exif = self._read_exif(file_path)

        # 2. Extract structured data
        creation_date = self._extract_creation_date(raw_exif)
        gps_lat, gps_lon, gps_alt = self._extract_gps_coordinates(raw_exif)
        timezone = self._calculate_timezone(gps_lat, gps_lon, gps_alt)

        # 3. Parse date from filename
        parsed_filename_date = self._parse_date_from_filename(file_path)

        # 4. Determine time offset (with filename fallback)
        time_offset = self._determine_time_offset(timezone, creation_date, parsed_filename_date)

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

    def _read_exif(self, file_path: Path) -> dict:
        """
        Read raw EXIF data using exiftool.

        Args:
            file_path: Path to video file

        Returns:
            Dictionary of EXIF tags and values
        """
        try:
            with exiftool.ExifToolHelper() as et:
                metadata = et.get_metadata(str(file_path))[0]
                return metadata
        except ExifToolExecuteError as e:
            logger.error(f'Failed to read EXIF from {file_path.name}: {e}')
            return {}

    def _extract_creation_date(self, raw_exif: dict) -> datetime | None:
        """
        Extract creation date from EXIF data.

        For video files, we need to subtract the duration to get the actual
        recording start time (QuickTime stores end time).

        Priority order:
        1. QuickTime:CreateDate - duration
        2. QuickTime:MediaCreateDate - duration
        3. QuickTime:TrackCreateDate - duration
        4. QuickTime:FileModifyDate - duration

        Args:
            raw_exif: Raw EXIF dictionary

        Returns:
            Parsed datetime or None if not found/invalid
        """
        # Extract duration offset if available
        duration = timedelta()
        if 'QuickTime:MediaDuration' in raw_exif:
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
                    # Subtract duration to get actual start time
                    return creation_date - duration
                except ValueError:
                    logger.warning('Failed to parse %s: %s', key, date_str)
                    continue

        return None

    def _extract_gps_coordinates(self, raw_exif: dict) -> tuple[float, float, float]:
        """
        Extract GPS coordinates from EXIF data.

        Args:
            raw_exif: Raw EXIF dictionary

        Returns:
            Tuple of (latitude, longitude, altitude). Returns (0, 0, 0) if not found.
        """
        latitude = float(raw_exif.get('Composite:GPSLatitude', 0))
        longitude = float(raw_exif.get('Composite:GPSLongitude', 0))
        altitude = float(raw_exif.get('Composite:GPSAltitude', 0))

        return latitude, longitude, altitude

    def _calculate_timezone(self, latitude: float, longitude: float, altitude: float) -> str | None:
        """
        Calculate timezone from GPS coordinates.

        Args:
            latitude: GPS latitude
            longitude: GPS longitude
            altitude: GPS altitude (unused, but kept for signature consistency)

        Returns:
            Timezone string (e.g., "America/New_York") or None if coordinates invalid
        """
        # Check if we have valid coordinates (not all zeros)
        if latitude == 0 and longitude == 0 and altitude == 0:
            return None

        return self.timezone_finder.timezone_at(lng=longitude, lat=latitude)

    def _parse_date_from_filename(self, file_path: Path) -> datetime | None:
        """
        Parse date from filename if present.

        Looks for pattern: YYYYMMDD_HHMMSS

        Args:
            file_path: Path to video file

        Returns:
            Parsed datetime or None if pattern not found
        """
        filename = file_path.stem
        date_match = re.search(r'\d{8}_\d{6}', filename)

        if date_match:
            try:
                return datetime.strptime(date_match.group(), '%Y%m%d_%H%M%S')
            except ValueError:
                logger.warning('Failed to parse date from filename: %s', filename)
                return None

        return None

    def _determine_time_offset(
        self, timezone: str | None, creation_date: datetime | None, parsed_filename_date: datetime | None
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
                if delta is not None:
                    return int(delta.total_seconds() / 3600)
            except Exception as e:
                logger.warning('Failed to calculate offset from timezone: %s', e)

        # Fallback: calculate from filename date vs EXIF date
        if parsed_filename_date and creation_date:
            time_diff = parsed_filename_date - creation_date
            offset_hours = int(time_diff.total_seconds() / 3600)
            logger.info('Calculated offset from filename: %s hours', offset_hours)
            return offset_hours

        return None

    def _find_exiftool(self) -> str:
        """
        Locate exiftool binary.

        Returns:
            Path to exiftool

        Raises:
            RuntimeError: If exiftool not found
        """
        if shutil.which('exiftool'):
            return 'exiftool'

        raise RuntimeError('exiftool not found. Install exiftool and add to PATH.')
