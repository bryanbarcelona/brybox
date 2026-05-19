"""
File operations: path building and file I/O for audio files.
"""

import shutil
from pathlib import Path

import exiftool
from exiftool.exceptions import ExifToolExecuteError

from brybox.core.audiora.metadata import AudioMetadataExtractor
from brybox.events.bus import publish_file_deleted, publish_file_moved
from brybox.exceptions.audio import (
    AudioraAudioNotFoundError,
    AudioraCorruptedFileError,
    AudioraFileOperationError,
)
from brybox.utils.deduplicator import HashDeduplicator


class FileMover:
    """
    Handles actual file I/O operations.

    Responsible for moving files, creating directories, and health checking.
    No path construction logic - just executes file operations.
    """

    def __init__(self, base_dir: str, *, dry_run: bool = False):
        """
        Args:
            base_dir: Base directory for output files (used for context only)
            dry_run: If True, no files are actually moved or deleted
        """
        self.base_dir = Path(base_dir)
        self.dry_run = dry_run

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

        Raises:
            AudioraAudioNotFoundError: If source file doesn't exist
            AudioraFileOperationError: If file operations fail
            AudioraCorruptedFileError: If moved file is corrupted
        """
        source_path = Path(source)
        dest_path = Path(destination)

        self._validate_source_exists(source_path)

        file_size = source_path.stat().st_size

        if self.dry_run:
            return True, not dest_path.exists()

        self._ensure_directory_exists(dest_path.parent)

        if dest_path.exists():
            return self._handle_existing_destination(source_path, dest_path, file_size)

        return self._perform_move(source_path, dest_path, file_size)

    @staticmethod
    def _validate_source_exists(source_path: Path) -> None:
        """Validate that source file exists."""
        if not source_path.exists():
            raise AudioraAudioNotFoundError(f'Source file does not exist: {source_path}', audio_path=str(source_path))

    @staticmethod
    def _ensure_directory_exists(directory: Path) -> None:
        """Create directory if it doesn't exist."""
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise AudioraFileOperationError(
                f'Permission denied creating directory {directory}: {e}', dest_path=str(directory)
            ) from e
        except OSError as e:
            raise AudioraFileOperationError(
                f'Failed to create directory {directory}: {e}', dest_path=str(directory)
            ) from e

    def _handle_existing_destination(self, source_path: Path, dest_path: Path, file_size: int) -> tuple[bool, bool]:
        """Handle case where destination file already exists."""
        if self._is_healthy(dest_path):
            self._delete_source(source_path)
            publish_file_deleted(source_path, file_size)
            return True, False
        # Corrupted file - overwrite it by continuing to move
        return self._perform_move(source_path, dest_path, file_size)

    @staticmethod
    def _delete_source(source_path: Path) -> None:
        """Delete source file."""
        try:
            source_path.unlink()
        except PermissionError as e:
            raise AudioraFileOperationError(
                f'Permission denied deleting source {source_path}: {e}', source_path=str(source_path)
            ) from e
        except OSError as e:
            raise AudioraFileOperationError(
                f'Failed to delete source {source_path}: {e}', source_path=str(source_path)
            ) from e

    def _perform_move(self, source_path: Path, dest_path: Path, file_size: int) -> tuple[bool, bool]:
        """Move file and verify health."""
        source_hash = HashDeduplicator._hash_file(source_path)

        self._execute_move(source_path, dest_path)
        self._verify_health(dest_path)

        AudioMetadataExtractor.write_content_hash(dest_path, source_hash)
        publish_file_moved(source_path, dest_path, file_size, is_healthy=True)
        return True, True

    def _execute_move(self, source_path: Path, dest_path: Path) -> None:
        """Execute the actual file move operation."""
        try:
            shutil.move(str(source_path), str(dest_path))
        except PermissionError as e:
            raise AudioraFileOperationError(
                f'Permission denied moving {source_path} to {dest_path}: {e}',
                source_path=str(source_path),
                dest_path=str(dest_path),
            ) from e
        except OSError as e:
            self._handle_os_error(e, source_path, dest_path)
        except Exception as e:
            raise AudioraFileOperationError(
                f'Unexpected error moving {source_path} to {dest_path}: {e}',
                source_path=str(source_path),
                dest_path=str(dest_path),
            ) from e

    @staticmethod
    def _handle_os_error(error: OSError, source_path: Path, dest_path: Path) -> None:
        """Handle OSError during file move."""
        if 'No space left on device' in str(error):
            raise AudioraFileOperationError(
                f'Disk full - cannot move {source_path} to {dest_path}',
                source_path=str(source_path),
                dest_path=str(dest_path),
            ) from error
        raise AudioraFileOperationError(
            f'Failed to move {source_path} to {dest_path}: {error}',
            source_path=str(source_path),
            dest_path=str(dest_path),
        ) from error

    def _verify_health(self, filepath: Path) -> None:
        """Verify moved file is healthy."""
        if not self._check_file_health(filepath):
            raise AudioraCorruptedFileError(f'Moved file is corrupted: {filepath}', audio_path=str(filepath))

    def _check_file_health(self, filepath: Path) -> bool:
        """Check file health and handle unexpected errors."""
        try:
            return self._is_healthy(filepath)
        except Exception as e:
            raise AudioraFileOperationError(
                f'Failed to verify health of moved file {filepath}: {e}', dest_path=str(filepath)
            ) from e

    @staticmethod
    def _is_healthy(filepath: str | Path) -> bool:
        """
        Verify audio file health using exiftool.

        Args:
            filepath: Path to audio file

        Returns:
            True if file can be read successfully, False otherwise

        Raises:
            AudioraFileOperationError: If health check fails unexpectedly
        """
        try:
            with exiftool.ExifToolHelper() as et:
                et.get_metadata(str(filepath))
                return True
        except ExifToolExecuteError:
            # File is corrupted or unreadable
            return False
        except Exception as e:
            # Unexpected error in the check itself
            raise AudioraFileOperationError(
                f'Health check failed for {filepath}: {e}', source_path=str(filepath)
            ) from e
