"""
File operations: path building and file I/O for audio files.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import exiftool
from exiftool.exceptions import ExifToolExecuteError

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
        self.file_checker = file_checker or self._files_have_same_content

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

    @staticmethod
    def _files_have_same_content(file1: str, file2: str) -> bool:
        """
        Check if two audio files have the same content via metadata comparison.

        Args:
            file1: First audio file path
            file2: Second audio file path

        Returns:
            True if files appear to have same content, False otherwise

        Raises:
            AudioraFileOperationError: If metadata comparison fails unexpectedly
        """
        # If either file doesn't exist, they can't be the same
        if not Path(file1).exists() or not Path(file2).exists():
            return False

        try:
            with exiftool.ExifToolHelper() as et:
                try:
                    meta1 = et.get_metadata(file1)[0]
                    meta2 = et.get_metadata(file2)[0]
                except ExifToolExecuteError:
                    # If we can't read metadata, assume files are different
                    # Log at debug level? No - worker doesn't log
                    return False
                except Exception as e:
                    # Unexpected errors should be wrapped
                    raise AudioraFileOperationError(
                        f'Failed to compare files {file1} and {file2}: {e}', source_path=file1, dest_path=file2
                    ) from e

                # Compare key fields that indicate same content
                comparison_fields = ['File:FileSize', 'QuickTime:Duration', 'QuickTime:MediaCreateDate']

                for field in comparison_fields:
                    val1 = meta1.get(field)
                    val2 = meta2.get(field)

                    # If one file has the field and the other doesn't, they're different
                    if (val1 is None) != (val2 is None):
                        return False

                    # If both have the field and they differ, they're different
                    if val1 is not None and val2 is not None and val1 != val2:
                        return False

                # If we got here, all checked fields match or are absent
                return True

        except AudioraFileOperationError:
            raise
        except Exception as e:
            # Catch any other unexpected errors
            raise AudioraFileOperationError(
                f'Unexpected error comparing files {file1} and {file2}: {e}', source_path=file1, dest_path=file2
            ) from e
