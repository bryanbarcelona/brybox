from dataclasses import dataclass, field
from datetime import datetime


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
