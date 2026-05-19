"""
File operations: path building and file I/O for audio files.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from brybox.exceptions.audio import (
    AudioraConfigurationError,
    AudioraFileOperationError,
)


class PathBuilder:
    """
    Constructs output paths for audio files.

    Pure logic - no file I/O except metadata reading for content comparison.
    Handles path construction, category validation, and conflict resolution.
    """

    def __init__(self, base_dir: str, file_checker: Callable[[str, str], bool] | None = None):
        """
        Args:
            base_dir: Base directory for output files
            file_checker: Optional callback to check if two files are identical
                         If not provided, uses metadata comparison
        """
        self.base_dir = Path(base_dir)
        self.file_checker = file_checker

    def build_output_path(self, category: str, filename: str, config: dict[str, Any], audio_filepath: str) -> str:
        """
        Build the complete output file path.

        Args:
            category: Category name
            filename: Output filename
            config: Full configuration dictionary
            audio_filepath: Original audio file path (for content comparison)

        Returns:
            Complete output path

        Raises:
            AudioraConfigurationError: If category not found in config
            AudioraFileOperationError: If content comparison fails
        """
        categories = config.get('categories', {})

        if category not in categories:
            raise AudioraConfigurationError(
                f"Unknown category '{category}' - check your configuration", audio_path=audio_filepath
            )

        relative_path = categories[category].get('output_path', '')
        filepath = self.base_dir / relative_path / filename

        # If file doesn't exist, we're done
        if not filepath.is_file():
            return str(filepath)

        # No file_checker available - assume different, resolve conflict
        if self.file_checker is None:
            return self._resolve_filename_conflict(filepath)

        # Check if it's a duplicate (same content)
        try:
            is_duplicate = self.file_checker(audio_filepath, str(filepath))
        except Exception as e:
            raise AudioraFileOperationError(
                f'Failed to check for duplicate between {audio_filepath} and {filepath}: {e}',
                source_path=audio_filepath,
                dest_path=str(filepath),
            ) from e

        if is_duplicate:
            return str(filepath)

        # Resolve conflict by adding number suffix
        return self._resolve_filename_conflict(filepath)

    @staticmethod
    def _resolve_filename_conflict(filepath: Path) -> str:
        """
        Resolve filename conflicts by adding number suffix.

        Args:
            filepath: Conflicting file path

        Returns:
            New filepath with (N) suffix
        """
        i = 1
        while True:
            new_path = filepath.parent / f'{filepath.stem}({i}){filepath.suffix}'
            if not new_path.exists():
                return str(new_path)
            i += 1
