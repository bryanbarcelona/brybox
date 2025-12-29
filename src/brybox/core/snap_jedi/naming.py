from datetime import datetime, timedelta
from pathlib import Path


class PathStrategy:
    """
    Determines target filenames for processed images.

    Generates timestamp-based filenames and handles conflicts.
    Stateless - all methods are pure functions.
    """

    @staticmethod
    def generate_target_path(source_path: Path, creation_date: datetime | None, time_offset: int | None = None) -> Path:
        """
        Generate target path for an image based on its metadata.

        Priority:
        1. If creation_date + time_offset exist: use adjusted timestamp
        2. If only creation_date exists: use as-is timestamp
        3. Otherwise: keep original filename, change to .jpg

        Args:
            source_path: Original image path
            creation_date: Image creation timestamp (naive datetime)
            time_offset: Timezone offset in hours (e.g., -5 for EST)

        Returns:
            Target path with timestamp-based filename or original name

        Example:
            >>> PathStrategy.generate_target_path(
            ...     Path('IMG_1234.HEIC'), datetime(2024, 3, 15, 14, 30, 0), time_offset=-5
            ... )
            Path("20240315 093000.jpg")
        """
        directory = source_path.parent

        # Case 1: Have both date and offset - apply timezone adjustment
        if creation_date is not None and time_offset is not None:
            adjusted_date = creation_date + timedelta(hours=time_offset)
            base_filename = adjusted_date.strftime('%Y%m%d %H%M%S')
            target = directory / f'{base_filename}.jpg'

        # Case 2: Have date but no offset - use as-is
        elif creation_date is not None:
            base_filename = creation_date.strftime('%Y%m%d %H%M%S')
            target = directory / f'{base_filename}.jpg'

        # Case 3: No metadata - keep original name, change extension
        else:
            target = source_path.with_suffix('.jpg')

        # Handle conflicts
        return PathStrategy._resolve_conflict(source_path, target)

    @staticmethod
    def _resolve_conflict(source_path: Path, target_path: Path) -> Path:
        """
        Resolve filename conflicts by adding (1), (2), etc.

        Args:
            source_path: Original file path
            target_path: Desired target path

        Returns:
            Conflict-free target path
        """
        # If target equals source, no rename needed
        if target_path == source_path:
            return target_path

        # If target doesn't exist, we're good
        if not target_path.exists():
            return target_path

        # Target exists find available numbered variant
        directory = target_path.parent
        stem = target_path.stem
        suffix = target_path.suffix

        counter = 1
        while (candidate := directory / f'{stem}({counter}){suffix}').exists():
            counter += 1

        return candidate
