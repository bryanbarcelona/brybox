from datetime import datetime
from pathlib import Path


class PathStrategy:
    """
    Determines target filenames for processed images.

    Generates timestamp-based filenames and handles conflicts.
    Stateless - all methods are pure functions.
    """

    @staticmethod
    def generate_target_path(source_path: Path, creation_date: datetime | None) -> Path:
        """
        Generate target path for an image based on its metadata.

        Priority:
        1. If creation_date exists: use its timestamp as-is
        2. Otherwise: keep original filename, change to .jpg

        Args:
            source_path: Original image path
            creation_date: Image creation timestamp (naive datetime, local per EXIF standard)

        Returns:
            Target path with timestamp-based filename or original name

        Example:
            >>> PathStrategy.generate_target_path(Path('IMG_1234.HEIC'), datetime(2024, 3, 15, 14, 30, 0))
            Path("20240315 143000.jpg")
        """
        directory = source_path.parent

        # DateTimeOriginal is always local time per EXIF standard - use directly.
        if creation_date is not None:
            base_filename = creation_date.strftime('%Y%m%d %H%M%S')
            target = directory / f'{base_filename}.jpg'

        # Case 2: No metadata - keep original name, change extension
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
