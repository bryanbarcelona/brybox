"""
File move operations for the Doctopus pipeline.
"""

import shutil
from pathlib import Path

from brybox.events.bus import publish_file_deleted, publish_file_moved
from brybox.exceptions.documents import DoctopusFileOperationError, DoctopusPDFNotFoundError
from brybox.utils.health_check import is_healthy
from brybox.utils.logging import get_configured_logger, log_and_display

logger = get_configured_logger('File Ops')


class FileMover:
    """
    Handles filesystem move operations for processed PDFs.

    Pure I/O — no path construction or domain logic.
    See PathBuilder for output path assembly.
    """

    def __init__(self, *, dry_run: bool = False):
        self.dry_run = dry_run

    def move_file(self, source: Path, destination: Path) -> tuple[bool, bool]:
        """
        Move source to destination.

        Returns:
            (success, is_new_file) — is_new_file is False when the destination
            already existed and the source was deleted as a duplicate.
        """
        if not source.exists():
            raise DoctopusPDFNotFoundError(f'Source file does not exist: {source}', pdf_path=source)

        file_size = source.stat().st_size
        output_dir = destination.parent

        if self.dry_run:
            return self._handle_dry_run(source, destination, output_dir)

        self._ensure_directory_exists(output_dir, source, destination)

        # Handle duplicates (source is deleted if destination already exists and is healthy)
        if destination.exists() and is_healthy(destination):
            self._remove_duplicate_source(source, destination, file_size)
            return True, False

        # Execute move
        self._execute_move(source, destination)

        # Post-move validation and event
        if not is_healthy(destination):
            raise DoctopusFileOperationError(
                f'Moved file appears corrupted: {destination}', source_path=source, dest_path=destination
            )

        publish_file_moved(source, destination, file_size, is_new=True)
        return True, True

    @staticmethod
    def _handle_dry_run(source: Path, destination: Path, output_dir: Path) -> tuple[bool, bool]:
        """Helper to reduce move_file complexity."""
        log_and_display(f'Would create directory: {output_dir}')
        if destination.exists():
            log_and_display(f'Would delete source file (duplicate): {source}')
            return True, False

        log_and_display(f'Would move {source} to {destination}')
        return True, True

    @staticmethod
    def _ensure_directory_exists(output_dir: Path, source: Path, destination: Path) -> None:
        """Helper to reduce move_file branching/complexity."""
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True)
            except (PermissionError, OSError) as e:
                raise DoctopusFileOperationError(
                    f'Failed to create directory {output_dir}: {e}', source_path=source, dest_path=destination
                ) from e

    @staticmethod
    def _remove_duplicate_source(source: Path, destination: Path, file_size: int) -> None:
        """Helper to handle source deletion when a healthy duplicate exists."""
        try:
            source.unlink()
        except (PermissionError, OSError) as e:
            raise DoctopusFileOperationError(
                f'Failed to delete source file {source}: {e}', source_path=source, dest_path=destination
            ) from e
        else:
            publish_file_deleted(source, file_size)

    @staticmethod
    def _execute_move(source: Path, destination: Path) -> None:
        """Helper to execute the actual move with error handling."""
        try:
            shutil.move(source, destination)
        except PermissionError as e:
            raise DoctopusFileOperationError(
                f'Permission denied moving {source} to {destination}', source_path=source, dest_path=destination
            ) from e
        except OSError as e:
            msg = 'Disk full' if 'No space left' in str(e) else 'Failed to move'
            raise DoctopusFileOperationError(
                f'{msg}: {source} to {destination} - {e}', source_path=source, dest_path=destination
            ) from e
