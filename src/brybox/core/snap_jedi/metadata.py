from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from pathlib import Path
import shutil

import exiftool
from exiftool.exceptions import ExifToolExecuteError
import pytz
from timezonefinder import TimezoneFinder

from ...utils.logging import log_and_display

@dataclass
class ImageMetadata:
    """
    Structured metadata extracted from an image.
    
    All fields are Optional since images may lack metadata.
    """
    creation_date: Optional[datetime] = None
    gps_latitude: float = 0.0
    gps_longitude: float = 0.0
    gps_altitude: float = 0.0
    timezone: Optional[str] = None
    time_offset: Optional[int] = None  # Hours from UTC
    raw_exif: dict = field(default_factory=dict)


class MetadataReader:
    """
    Reads and interprets image metadata from EXIF data.
    
    Handles:
    - EXIF parsing via exiftool
    - GPS coordinate extraction
    - Timezone calculation from GPS
    - Time offset determination
    """
    
    def __init__(self, exiftool_path: Optional[str] = None):
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
        """
        # 1. Read raw EXIF
        raw_exif = self._read_exif(file_path)
        
        # 2. Extract structured data
        creation_date = self._extract_creation_date(raw_exif)
        gps_lat, gps_lon, gps_alt = self._extract_gps_coordinates(raw_exif)
        timezone = self._calculate_timezone(gps_lat, gps_lon, gps_alt)
        time_offset = self._determine_time_offset(raw_exif, timezone, creation_date)
        
        return ImageMetadata(
            creation_date=creation_date,
            gps_latitude=gps_lat,
            gps_longitude=gps_lon,
            gps_altitude=gps_alt,
            timezone=timezone,
            time_offset=time_offset,
            raw_exif=raw_exif
        )
    
    def _read_exif(self, file_path: Path) -> dict:
        """
        Read raw EXIF data using exiftool.
        
        Args:
            file_path: Path to image file
            
        Returns:
            Dictionary of EXIF tags and values
        """
        try:
            with exiftool.ExifToolHelper() as et:
                metadata = et.get_metadata(str(file_path))[0]
                return metadata
        except ExifToolExecuteError as e:
            log_and_display(f"Failed to read EXIF from {file_path.name}: {e}", level="error")
            return {}
    
    def _extract_creation_date(self, raw_exif: dict) -> Optional[datetime]:
        """
        Extract creation date from EXIF data.
        
        Priority order:
        1. EXIF:DateTimeOriginal (when photo was taken)
        2. EXIF:CreateDate (fallback)
        
        Args:
            raw_exif: Raw EXIF dictionary
            
        Returns:
            Parsed datetime or None if not found/invalid
        """
        # Try DateTimeOriginal first (preferred)
        if "EXIF:DateTimeOriginal" in raw_exif:
            date_str = raw_exif["EXIF:DateTimeOriginal"]
            try:
                return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                log_and_display(f"Failed to parse DateTimeOriginal: {date_str}", level="warning")
                pass
        
        # Fall back to CreateDate
        if "EXIF:CreateDate" in raw_exif:
            date_str = raw_exif["EXIF:CreateDate"]
            try:
                return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                log_and_display(f"Failed to parse CreateDate: {date_str}", level="warning")
                pass
            
        return None
    
    def _extract_gps_coordinates(self, raw_exif: dict) -> tuple[float, float, float]:
        """
        Extract GPS coordinates from EXIF data.
        
        Args:
            raw_exif: Raw EXIF dictionary
            
        Returns:
            Tuple of (latitude, longitude, altitude). Returns (0, 0, 0) if not found.
        """
        latitude = float(raw_exif.get("Composite:GPSLatitude", 0))
        longitude = float(raw_exif.get("Composite:GPSLongitude", 0))
        altitude = float(raw_exif.get("Composite:GPSAltitude", 0))
        
        return latitude, longitude, altitude
    
    def _calculate_timezone(
        self, 
        latitude: float, 
        longitude: float, 
        altitude: float
    ) -> Optional[str]:
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
    
    def _determine_time_offset(
        self,
        raw_exif: dict,
        timezone: Optional[str],
        creation_date: Optional[datetime]
    ) -> Optional[int]:
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
        offset_keys = [
            "EXIF:OffsetTime",
            "EXIF:OffsetTimeOriginal", 
            "EXIF:OffsetTimeDigitized"
        ]
        
        for key in offset_keys:
            if key in raw_exif:
                offset_str = raw_exif[key]
                try:
                    # Format is typically "+05:00" or "-05:00"
                    hours = int(offset_str.split(":")[0])
                    return hours
                except (ValueError, IndexError):
                    log_and_display(f"Failed to parse offset from {key}: {offset_str}", level="warning")
                    continue
        
        # Fall back to calculating from timezone
        if timezone and creation_date:
            try:
                tz = pytz.timezone(timezone)
                local_dt = tz.localize(creation_date, is_dst=None)
                delta = local_dt.utcoffset()
                if delta is None:          # <-- guard
                    return None
                return int(delta.total_seconds() / 3600)
            except Exception as e:
                log_and_display(f"Failed to calculate offset from timezone: {e}", level="warning")
                pass
        
        return None
    
    def _find_exiftool(self) -> str:
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
        bundled = Path(__file__).parent.parent.parent / "assets" / "bin" / "exiftool"
        if bundled.exists():
            return str(bundled)
        
        # Check if available in PATH
        if shutil.which("exiftool"):
            return "exiftool"
        
        raise RuntimeError(
            "exiftool not found. Install exiftool or place in assets/bin/"
        )