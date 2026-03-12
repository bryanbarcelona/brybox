import shutil
from datetime import datetime
from pathlib import Path

import exiftool
import pytz
from exiftool.exceptions import ExifToolExecuteError
from timezonefinder import TimezoneFinder

from brybox.core.models.image import ImageMetadata
from brybox.exceptions.images import (
    SnapJediImageNotFoundError,
    SnapJediMetadataError,
    SnapJediMetadataParseError,
    SnapJediMetadataReadError,
    SnapJediToolNotFoundError,
)


class MetadataReader:
    """
    Reads and interprets image metadata from EXIF data.

    Handles:
    - EXIF parsing via exiftool
    - GPS coordinate extraction
    - Timezone calculation from GPS
    - Time offset determination
    """

    def __init__(self, exiftool_path: str | None = None):
        """
        Initialize metadata reader.

        Args:
            exiftool_path: Path to exiftool binary. If None, attempts to find it.
        """
        self.exiftool_path = exiftool_path or self._find_exiftool()
        self.timezone_finder = TimezoneFinder()

    def extract_metadata(self, file_path: Path) -> ImageMetadata:
        """
        Extract all metadata from an image file.

        Args:
            file_path: Path to image file

        Returns:
            ImageMetadata with extracted information

        Raises:
            SnapJediImageNotFoundError: If image file doesn't exist
            SnapJediMetadataReadError: If metadata cannot be read
            SnapJediMetadataParseError: If metadata parsing fails
        """
        if not file_path.exists():
            raise SnapJediImageNotFoundError(f'Image not found: {file_path}', image_path=file_path)

        raw_exif = self._read_exif(file_path)

        try:
            creation_date = self._extract_creation_date(raw_exif, file_path)
            gps_lat, gps_lon, gps_alt = self._extract_gps_coordinates(raw_exif)
            timezone = self._calculate_timezone(gps_lat, gps_lon, gps_alt)
            time_offset = self._determine_time_offset(raw_exif, timezone, creation_date, file_path)
        except SnapJediMetadataError:
            raise
        except Exception as e:
            raise SnapJediMetadataError(
                f'Unexpected error extracting metadata from {file_path.name}: {e}', image_path=file_path
            ) from e

        return ImageMetadata(
            creation_date=creation_date,
            gps_latitude=gps_lat,
            gps_longitude=gps_lon,
            gps_altitude=gps_alt,
            timezone=timezone,
            time_offset=time_offset,
            raw_exif=raw_exif,
        )

    @staticmethod
    def _read_exif(file_path: Path) -> dict:
        """
        Read raw EXIF data using exiftool.

        Args:
            file_path: Path to image file

        Returns:
            Dictionary of EXIF tags and values

        Raises:
            SnapJediMetadataReadError: If exiftool fails
        """
        try:
            with exiftool.ExifToolHelper() as et:
                metadata = et.get_metadata(str(file_path))[0]
                return metadata
        except ExifToolExecuteError as e:
            raise SnapJediMetadataReadError(
                f'Failed to read EXIF from {file_path.name}: {e}', image_path=file_path, stderr=str(e)
            ) from e
        except IndexError as e:
            raise SnapJediMetadataReadError(
                f'Exiftool returned empty result for {file_path.name}', image_path=file_path
            ) from e

    @staticmethod
    def _extract_creation_date(raw_exif: dict, file_path: Path) -> datetime | None:
        """
        Extract creation date from EXIF data.

        Priority order:
        1. EXIF:DateTimeOriginal (when photo was taken)
        2. EXIF:CreateDate (fallback)

        Args:
            raw_exif: Raw EXIF dictionary
            file_path: Path to image (for error context)

        Returns:
            Parsed datetime or None if not found

        Raises:
            SnapJediMetadataParseError: If date string exists but cannot be parsed
        """
        # Try DateTimeOriginal first (preferred)
        if 'EXIF:DateTimeOriginal' in raw_exif:
            date_str = raw_exif['EXIF:DateTimeOriginal']
            try:
                return datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
            except ValueError as e:
                raise SnapJediMetadataParseError(
                    f'Failed to parse DateTimeOriginal: {date_str}', image_path=file_path, field='DateTimeOriginal'
                ) from e

        # Fall back to CreateDate
        if 'EXIF:CreateDate' in raw_exif:
            date_str = raw_exif['EXIF:CreateDate']
            try:
                return datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
            except ValueError as e:
                raise SnapJediMetadataParseError(
                    f'Failed to parse CreateDate: {date_str}', image_path=file_path, field='CreateDate'
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

    @staticmethod
    def _determine_time_offset(
        raw_exif: dict, timezone: str | None, creation_date: datetime | None, file_path: Path
    ) -> int | None:
        """
        Determine timezone offset in hours.

        Priority order:
        1. EXIF offset tags (OffsetTime, OffsetTimeOriginal, OffsetTimeDigitized)
        2. Calculate from timezone and creation_date

        Args:
            raw_exif: Raw EXIF dictionary
            timezone: Timezone string from GPS
            creation_date: When photo was taken

        Returns:
            Offset in hours from UTC, or None if cannot be determined
        """
        # Try EXIF offset tags first
        offset_keys = ['EXIF:OffsetTime', 'EXIF:OffsetTimeOriginal', 'EXIF:OffsetTimeDigitized']

        for key in offset_keys:
            if key in raw_exif:
                offset_str = raw_exif[key]
                try:
                    # Format is typically "+05:00" or "-05:00"
                    hours = int(offset_str.split(':')[0])
                except (ValueError, IndexError) as e:
                    raise SnapJediMetadataParseError(
                        f'Failed to parse offset from {key}: {offset_str}', image_path=file_path, field=key
                    ) from e
                else:
                    return hours

        # Fall back to calculating from timezone
        if timezone and creation_date:
            try:
                tz = pytz.timezone(timezone)
                local_dt = tz.localize(creation_date, is_dst=None)
                delta = local_dt.utcoffset()
                if delta is None:  # <-- guard
                    return None
                return int(delta.total_seconds() / 3600)
            except (pytz.UnknownTimeZoneError, pytz.NonExistentTimeError, pytz.AmbiguousTimeError):
                return None
            except Exception as e:
                raise SnapJediMetadataParseError(
                    f'Unexpected error calculating timezone offset: {e}', image_path=file_path, field='timezone_offset'
                ) from e

    @staticmethod
    def _find_exiftool() -> str:
        """
        Locate exiftool binary.

        Search order:
        1. Bundled in assets/bin/
        2. System PATH

        Returns:
            Path to exiftool

        Raises:
            RuntimeError: If exiftool not found
        """
        # Check bundled location first
        bundled = Path(__file__).parent.parent.parent / 'assets' / 'bin' / 'exiftool'
        if bundled.exists():
            return str(bundled)

        # Check if available in PATH
        if shutil.which('exiftool'):
            return 'exiftool'

        raise SnapJediToolNotFoundError(
            'exiftool not found. Install exiftool or place in assets/bin/', tool_name='exiftool'
        )
