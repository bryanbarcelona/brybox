"""
Audio metadata extraction using exiftool.
"""

import re
from datetime import datetime
from pathlib import Path

import exiftool
from exiftool.exceptions import ExifToolExecuteError

from brybox.utils.logging import log_and_display


class _AudioMetadataExtractor:
    """Extracts metadata from audio files using exiftool."""

    def __init__(self):
        pass

    def extract_media_created_date(self, file_path: str) -> str | None:
        """
        Extract Media Created date from audio file metadata.

        Args:
            file_path: Path to audio file

        Returns:
            Date string in YYYYMMDD format, or None if not found
        """
        try:
            with exiftool.ExifToolHelper() as et:
                metadata = et.get_metadata(str(file_path))[0]

                # Try different date fields in order of preference
                date_fields = [
                    'QuickTime:MediaCreateDate',
                    'QuickTime:CreateDate',
                    'QuickTime:TrackCreateDate',
                ]

                for field in date_fields:
                    if field in metadata:
                        date_str = metadata[field]
                        parsed_date = self._parse_quicktime_date(date_str)
                        if parsed_date:
                            return parsed_date.strftime('%Y%m%d')

                log_and_display(f'No media created date found in {Path(file_path).name}', level='warning')
                return None

        except ExifToolExecuteError as e:
            log_and_display(f'Failed to read metadata from {Path(file_path).name}: {e}', level='error')
            return None

    def _parse_quicktime_date(self, date_str: str) -> datetime | None:
        """
        Parse QuickTime date string to datetime object.

        QuickTime dates are typically in format: "2025:04:13 19:10:45"

        Args:
            date_str: Date string from QuickTime metadata

        Returns:
            datetime object or None if parsing fails
        """
        try:
            # QuickTime format: "YYYY:MM:DD HH:MM:SS"
            return datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
        except (ValueError, TypeError):
            log_and_display(f'Failed to parse date: {date_str}', level='warning')
            return None

    def extract_filename_date(self, filename: str) -> str | None:
        """
        Extract date from filename if present.

        Looks for date patterns like:
        - MM-DD-YYYY (e.g., "04-13-2025")
        - YYYY-MM-DD (e.g., "2025-04-13")

        Args:
            filename: Filename to extract date from

        Returns:
            Date string in YYYYMMDD format, or None if not found
        """
        # Pattern: MM-DD-YYYY or DD-MM-YYYY
        pattern1 = r'^(\d{2})-(\d{2})-(\d{4})'
        match = re.search(pattern1, filename)
        if match:
            # Assume MM-DD-YYYY format (US style)
            month, day, year = match.groups()
            try:
                date = datetime(int(year), int(month), int(day))
                return date.strftime('%Y%m%d')
            except ValueError:
                pass

        # Pattern: YYYY-MM-DD
        pattern2 = r'^(\d{4})-(\d{2})-(\d{2})'
        match = re.search(pattern2, filename)
        if match:
            year, month, day = match.groups()
            try:
                date = datetime(int(year), int(month), int(day))
                return date.strftime('%Y%m%d')
            except ValueError:
                pass

        return None

    def validate_dates(self, metadata_date: str | None, filename_date: str | None, filename: str) -> str | None:
        """
        Validate metadata date against filename date.

        Args:
            metadata_date: Date from audio metadata (YYYYMMDD)
            filename_date: Date from filename (YYYYMMDD)
            filename: Original filename for logging

        Returns:
            The validated date (prefers metadata), or None if neither exists
        """
        if not metadata_date and not filename_date:
            log_and_display(f'No date found in metadata or filename: {filename}', level='warning')
            return None

        if metadata_date and filename_date:
            if metadata_date != filename_date:
                log_and_display(
                    f'Date mismatch for {filename}: '
                    f'metadata={metadata_date}, filename={filename_date}. '
                    f'Using metadata date.',
                    level='warning',
                )

        # Prefer metadata date over filename date
        return metadata_date or filename_date
