"""
Output path construction for the DoiSmith pipeline.
"""

import re
from pathlib import Path

from brybox.utils.logging import get_configured_logger

logger = get_configured_logger('DoiSmith.PathBuilder')

# HTML tags that may appear in CrossRef titles
_HTML_TAGS = re.compile(r'</?(?:i|b|sup|sub)>', re.IGNORECASE)

# Characters forbidden in filenames (Windows-safe superset)
_FORBIDDEN_CHARS = str.maketrans({
    '/': ' ',
    ',': ' ',
    '?': ' ',
    '*': ' ',
    '<': ' ',
    '>': ' ',
    '|': ' ',
    ':': ' - ',
})


class DoiPathBuilder:
    """
    Constructs output paths for renamed academic PDFs.

    Filename format: {title} - {author} ({year}).pdf

    base_dir is set by DoiSmithPrime from either the explicit base_dir
    argument or the config's target_dir — in that priority order. This
    class never reads config directly, so base_dir overrides always land.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    @staticmethod
    def build_filename(title: str, author: str, year: int) -> str:
        """
        Assemble and sanitise the output filename from metadata components.

        Strips HTML tags that CrossRef embeds in some titles, removes
        forbidden filesystem characters, and collapses runs of whitespace.
        """
        raw = f'{title} - {author} ({year}).pdf'
        cleaned = _HTML_TAGS.sub(' ', raw)
        cleaned = cleaned.translate(_FORBIDDEN_CHARS)
        return ' '.join(cleaned.split())

    def build_output_path(self, filename: str) -> Path:
        """
        Resolve the full destination path for a renamed PDF using self.base_dir.

        FileMover handles duplicate detection downstream via HashDeduplicator.
        """
        return self.base_dir / filename

    @staticmethod
    def is_new_file(output_filepath: Path) -> bool:
        return not output_filepath.is_file()
