"""
Output path construction for the Doctopus pipeline.
"""

from pathlib import Path
from typing import Any

from brybox.exceptions.documents import DoctopusConfigurationError, DoctopusFileOperationError
from brybox.utils.deduplicator import HashDeduplicator
from brybox.utils.logging import get_configured_logger
from brybox.utils.naming import resolve_filename_conflict

logger = get_configured_logger('Path Builder')


class PathBuilder:
    """
    Constructs output paths for processed PDFs.

    Handles filename assembly, category-based directory routing,
    duplicate detection, and conflict resolution.
    Holds no I/O responsibility beyond PDF content comparison.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    @staticmethod
    def build_filename(date: str | None, category: str | None, invoice_id: str | None) -> str:
        """Assemble output filename from available metadata components."""
        parts = [p for p in (date, category, invoice_id) if p]
        return f'{" ".join(parts).strip()}.pdf'

    @staticmethod
    def get_filename_component(category: str, config: dict[str, Any]) -> str:
        """Return the filename label configured for the given category, falling back to the category name."""
        category_config = config.get('categories', {}).get(category, {})
        return category_config.get('filename', category)

    def build_output_path(self, category: str, filename: str, config: dict[str, Any], pdf_filepath: Path) -> Path:
        """
        Construct the full destination path for a processed PDF.

        Detects duplicates via SHA-256 hash comparison.
        Delegates conflict resolution to utils.naming.resolve_filename_conflict.

        Raises:
            DoctopusConfigurationError: Category not found in config
            DoctopusFileOperationError: Duplicate detection failed
        """
        categories = config.get('categories', {})

        if category not in categories:
            raise DoctopusConfigurationError(
                f"Unknown category '{category}' - check your configuration", pdf_path=pdf_filepath
            )

        relative_path = categories[category].get('output_path', '')
        filepath = self.base_dir / relative_path / filename

        # If file doesn't exist, we're done
        if not filepath.is_file():
            return filepath

        # Check if it's a duplicate
        try:
            is_duplicate = HashDeduplicator().is_duplicate(pdf_filepath, filepath)
        except Exception as e:
            raise DoctopusFileOperationError(
                f'Failed to check for duplicate between {pdf_filepath} and {filepath}: {e}',
                source_path=pdf_filepath,
                dest_path=filepath,
            ) from e
        else:
            if is_duplicate:
                return filepath

        # Resolve conflict
        try:
            return resolve_filename_conflict(filepath)
        except Exception as e:
            raise DoctopusFileOperationError(
                f'Failed to resolve filename conflict for {filepath}: {e}', source_path=pdf_filepath, dest_path=filepath
            ) from e
