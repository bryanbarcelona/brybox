"""
File operations: moving, conflict resolution, and path management.
"""

import shutil
from pathlib import Path
from typing import Any

import exiftool
from exiftool.exceptions import ExifToolExecuteError

from brybox.events.bus import publish_file_deleted, publish_file_moved
from brybox.utils.logging import log_and_display


class FileMover:
    """Handles file operations and path management."""

    def __init__(self, base_dir: str, *, dry_run: bool = False) -> None:
        """
        Initialize file mover.

        Args:
            base_dir: Base directory for output files
            dry_run: If True, no files are moved or deleted
        """
        self.base_dir = base_dir
        self.dry_run = dry_run

    def build_output_path(
        self, category: str, filename: str, config: dict[str, Any], audio_filepath: str
    ) -> str | None:
        """
        Build the complete output file path.

        Args:
            category: Category name
            filename: Output filename
            config: Full configuration dictionary
            audio_filepath: Original audio file path (for content comparison)

        Returns:
            Complete output path, or None if category not found
        """
        categories = config.get('categories', {})

        if category not in categories:
            return None

        relative_path = categories[category].get('output_path', '')
        filepath = Path(self.base_dir) / relative_path / filename

        if not Path(filepath).is_file():
            return filepath

        # Check if files have same content
        try:
            if self._files_have_same_content(audio_filepath, filepath):
                return filepath
        except Exception:
            pass

        # Handle filename conflicts
        return self._resolve_filename_conflict(filepath)

    @staticmethod
    def _files_have_same_content(file1: str | Path, file2: str | Path) -> bool:
        """
        Check if two audio files have the same content via metadata comparison.

        Uses exiftool to compare key metadata fields as a proxy for content equality.

        Args:
            file1: First audio file path
            file2: Second audio file path

        Returns:
            True if files appear to have same content, False otherwise
        """
        file1 = str(file1)
        file2 = str(file2)
        try:
            with exiftool.ExifToolHelper() as et:
                meta1 = et.get_metadata(file1)[0]
                meta2 = et.get_metadata(file2)[0]

                # Compare key fields that indicate same content
                comparison_fields = ['File:FileSize', 'QuickTime:Duration', 'QuickTime:MediaCreateDate']

                for field in comparison_fields:
                    if field in meta1 and field in meta2 and meta1[field] != meta2[field]:
                        return False

                return True

        except (ExifToolExecuteError, Exception):
            return False

    @staticmethod
    def _resolve_filename_conflict(filepath: str | Path) -> str:
        """
        Resolve filename conflicts by adding number suffix.

        Args:
            filepath: Conflicting file path

        Returns:
            New filepath with (N) suffix
        """
        filepath = Path(filepath)
        i = 1

        while Path(f'{filepath.stem}({i}){filepath.suffix}').is_file():
            i += 1

        return f'{filepath.stem}({i}){filepath.suffix}'

    def move_file(self, source: str | Path, destination: str | Path) -> tuple[bool, bool]:
        """
        Move file from source to destination.

        Args:
            source: Source file path
            destination: Destination file path

        Returns:
            Tuple of (success, is_new_file)
            - success: True if operation completed successfully
            - is_new_file: True if file was moved (new), False if duplicate deleted
        """
        source = Path(source)
        destination = Path(destination)

        if not source.exists():
            log_and_display(f'Source file does not exist: {source}', level='warning')
            return False, False

        file_size = source.stat().st_size
        output_dir = destination.parent

        if self.dry_run:
            log_and_display(f'Would create directory: {output_dir}')
            if destination.exists():
                log_and_display(f'Would delete source file (duplicate): {source}')
                return True, False
            else:
                log_and_display(f'Would move {source} to {destination}')
                return True, True

        # Create directory if needed
        if not output_dir.exists():
            output_dir.mkdir(parents=True)

        # Handle existing destination
        if destination.exists() and self._is_healthy(destination):
            source.unlink()
            log_and_display(f'Destination exists. Deleted source file: {source}')
            publish_file_deleted(source, file_size)
            return True, False
        else:
            shutil.move(source, destination)
            if not self._is_healthy(destination):
                log_and_display(f'Moved file is corrupted: {destination}', level='error')
                return False, False

            log_and_display(f'Moved {source} to {destination}.')
            publish_file_moved(source, destination, file_size, is_healthy=True)
            return True, True

    @staticmethod
    def _is_healthy(filepath: str | Path) -> bool:
        """
        Verify audio file health using exiftool.

        Args:
            filepath: Path to audio file

        Returns:
            True if file can be read successfully, False otherwise
        """
        try:
            with exiftool.ExifToolHelper() as et:
                et.get_metadata(str(filepath))
                return True
        except (ExifToolExecuteError, Exception):
            return False
