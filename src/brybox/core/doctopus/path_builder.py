"""
Output path construction for the Doctopus pipeline.
"""

from pathlib import Path
from typing import Any

from brybox.utils.deduplicator import HashDeduplicator
from brybox.utils.naming import resolve_filename_conflict


class PathBuilder:
    """
    Constructs output paths for processed PDFs.

    Handles filename assembly, category-based directory routing,
    duplicate detection, and conflict resolution.
    Holds no I/O responsibility beyond PDF content comparison.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def build_filename(self, date: str | None, category: str | None, invoice_id: str | None) -> str:
        """Assemble output filename from available metadata components."""
        parts = [p for p in (date, category, invoice_id) if p]
        return f'{" ".join(parts).strip()}.pdf'

    def get_filename_component(self, category: str, config: dict[str, Any]) -> str:
        """Return the filename label configured for the given category, falling back to the category name."""
        category_config = config.get('categories', {}).get(category, {})
        return category_config.get('filename', category)

    def build_output_path(
        self, category: str, filename: str, config: dict[str, Any], pdf_filepath: Path
    ) -> Path | None:
        """
        Construct the full destination path for a processed PDF.

        Returns None if the category is not recognised in config.
        Detects duplicates via SHA-256 hash comparison.
        Delegates conflict resolution to utils.naming.resolve_filename_conflict.
        """
        categories = config.get('categories', {})

        if category not in categories:
            return None

        relative_path = categories[category].get('output_path', '')
        filepath = self.base_dir / relative_path / filename

        if not filepath.is_file():
            return filepath

        if HashDeduplicator().is_duplicate(pdf_filepath, filepath):
            return filepath

        return resolve_filename_conflict(filepath)
