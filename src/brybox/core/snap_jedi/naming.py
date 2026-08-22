from datetime import datetime
from pathlib import Path


class PathStrategy:
    """
    Determines target filenames for processed images.

    Generates timestamp-based filenames and handles conflicts.
    Stateless - all methods are pure functions.
    """

    @staticmethod
    def generate_target_path(
        source_path: Path, creation_date: datetime | None, fallback_name: str | None = None
    ) -> Path:
        """
        Generate target path for an image based on its metadata.

        Priority:
        1. If creation_date exists: use its timestamp as-is
        2. Otherwise: keep the original filename (pre-staging, if known), change to .jpg

        Args:
            source_path: Path to the staged image being processed
            creation_date: Image creation timestamp (naive datetime, local per EXIF standard)
            fallback_name: Filename the source had before staging, used when no
                creation_date is available (e.g. WhatsApp-recompressed images that
                have had their EXIF stripped). Falls back to source_path's own name
                when not provided.

        Returns:
            Target path with timestamp-based filename or original name

        Example:
            >>> PathStrategy.generate_target_path(Path('IMG_1234.HEIC'), datetime(2024, 3, 15, 14, 30, 0))
            Path("20240315 143000.jpg")
        """
        target = PathStrategy.compute_base_target(source_path, creation_date, fallback_name)
        return PathStrategy._resolve_conflict(source_path, target)

    @staticmethod
    def compute_base_target(
        source_path: Path, creation_date: datetime | None, fallback_name: str | None = None
    ) -> Path:
        """
        Compute the desired target path without conflict resolution.

        Callers that need to distinguish a true content-duplicate (same file,
        same name) from a genuine naming collision (different files, same name)
        must check this base path against the filesystem *before* calling
        generate_target_path(), since that method already numbers past any
        existing file and would otherwise mask a real duplicate.

        Args:
            source_path: Path to the staged image being processed
            creation_date: Image creation timestamp (naive datetime, local per EXIF standard)
            fallback_name: Filename the source had before staging, used when no
                creation_date is available

        Returns:
            Desired target path, not yet checked against existing files
        """
        directory = source_path.parent

        # DateTimeOriginal is always local time per EXIF standard - use directly.
        if creation_date is not None:
            base_filename = creation_date.strftime('%Y%m%d %H%M%S')
            return directory / f'{base_filename}.jpg'

        # Case 2: No metadata - keep the pre-staging original name, change extension
        name = fallback_name if fallback_name is not None else source_path.name
        return directory / Path(name).with_suffix('.jpg')

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
