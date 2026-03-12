import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from brybox.exceptions.transfers import (
    PorterMetadataError,
    PorterOperationFailedError,
    PorterResourceNotFoundError,
)


class ExifTimestampFixer:
    """Fixes overlapping EXIF timestamps in image files."""

    @staticmethod
    def _get_exiftool_command() -> list[str]:
        """Get full command to run exiftool (works with .exe or .bat)."""
        exiftool_path = shutil.which('exiftool')
        if not exiftool_path:
            raise PorterOperationFailedError(
                'exiftool not found in PATH',
                operation='dependency_check',
                error_detail='exiftool must be installed for metadata operations',
            )

        # On Windows, use cmd /c to handle both .exe and .bat
        return ['cmd', '/c', exiftool_path]

    @staticmethod
    def _read_timestamp(image_path: Path) -> datetime | None:
        """
        Read DateTimeOriginal from image EXIF.

        Returns:
            datetime object if timestamp found, None otherwise

        Raises:
            PorterResourceNotFoundError: If image file doesn't exist
            PorterOperationFailedError: If exiftool fails or times out
            PorterMetadataError: If date format is invalid
        """
        if not image_path.exists():
            raise PorterResourceNotFoundError(
                f'Image file not found: {image_path}',
                resource_path=image_path,
            )

        cmd = [*ExifTimestampFixer._get_exiftool_command(), '-DateTimeOriginal', '-s', '-s', '-s', str(image_path)]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=50,
            )
        except subprocess.TimeoutExpired as e:
            raise PorterOperationFailedError(
                f'Timeout reading EXIF from {image_path.name}',
                resource_path=image_path,
                operation='exif_read',
                error_detail=str(e),
            ) from e
        except subprocess.CalledProcessError as e:
            raise PorterOperationFailedError(
                f'Failed to read EXIF from {image_path.name}',
                resource_path=image_path,
                operation='exif_read',
                error_detail=e.stderr,
            ) from e

        date_str = result.stdout.strip()
        if not date_str:
            return None

        try:
            return datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
        except ValueError as e:
            raise PorterMetadataError(
                f'Invalid date format in {image_path.name}: {date_str}',
                resource_path=image_path,
                metadata_field='DateTimeOriginal',
            ) from e

    @staticmethod
    def _write_timestamp(image_path: Path, timestamp: datetime) -> None:
        """
        Write timestamp to EXIF fields.

        Raises:
            PorterResourceNotFoundError: If image file doesn't exist
            PorterOperationFailedError: If exiftool fails or times out
        """
        if not image_path.exists():
            raise PorterResourceNotFoundError(
                f'Image file not found: {image_path}',
                resource_path=image_path,
            )

        date_formatted = timestamp.strftime('%Y:%m:%d %H:%M:%S')
        cmd = [
            *ExifTimestampFixer._get_exiftool_command(),
            f'-DateTimeOriginal={date_formatted}',
            f'-CreateDate={date_formatted}',
            f'-ModifyDate={date_formatted}',
            '-overwrite_original',
            str(image_path),
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                timeout=50,
            )
        except subprocess.TimeoutExpired as e:
            raise PorterOperationFailedError(
                f'Timeout writing EXIF to {image_path.name}',
                resource_path=image_path,
                operation='exif_write',
                error_detail=str(e),
            ) from e
        except subprocess.CalledProcessError as e:
            raise PorterOperationFailedError(
                f'Failed to write EXIF to {image_path.name}',
                resource_path=image_path,
                operation='exif_write',
                error_detail=e.stderr,
            ) from e

    @staticmethod
    def _process_image_timestamps(image_dates: dict[Path, datetime]) -> tuple[dict[Path, datetime], int]:
        """
        Process timestamps to resolve collisions.

        Returns:
            Tuple of (adjusted_timestamps dict, number of adjustments made)
        """
        unique_dates = set()
        adjusted_timestamps = {}
        adjustments = 0

        for path, original_dt in image_dates.items():
            adjusted_dt = original_dt

            while adjusted_dt in unique_dates:
                adjusted_dt += timedelta(seconds=1)

            unique_dates.add(adjusted_dt)
            adjusted_timestamps[path] = adjusted_dt

            if adjusted_dt != original_dt:
                adjustments += 1

        return adjusted_timestamps, adjustments

    def fix_metadata(
        self,
        mappings: list[tuple[Path, Path, list[Path]]],
    ) -> int:
        """
        Ensure unique DateTimeOriginal EXIF values for all images.

        Reads EXIF from all temp images and adjusts timestamps by +1 second
        increments when duplicates are found.

        Args:
            mappings: List of (source_path, temp_image_path, temp_sidecar_paths)

        Returns:
            Number of timestamps that were adjusted

        Raises:
            PorterResourceNotFoundError: If any image file is missing
            PorterOperationFailedError: If exiftool operations fail
            PorterMetadataError: If date format is invalid
        """
        if not mappings:
            return 0

        # Read timestamps from all images
        image_dates = {}
        for _, temp_image_path, _ in mappings:
            dt = self._read_timestamp(temp_image_path)
            if dt is not None:
                image_dates[temp_image_path] = dt

        if not image_dates:
            return 0

        # Process collisions
        adjusted_timestamps, adjustments = self._process_image_timestamps(image_dates)

        # Write back adjusted timestamps
        for path, timestamp in adjusted_timestamps.items():
            if timestamp != image_dates[path]:  # Only write if changed
                self._write_timestamp(path, timestamp)

        return adjustments
