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

    def __init__(self, dry_run: bool = False):
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
            log_and_display(f'Would create directory: {output_dir}')
            if destination.exists():
                log_and_display(f'Would delete source file (duplicate): {source}')
                return True, False
            else:
                log_and_display(f'Would move {source} to {destination}')
                return True, True

        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True)
            except PermissionError as e:
                raise DoctopusFileOperationError(
                    f'Permission denied creating directory: {output_dir}', source_path=source, dest_path=destination
                ) from e
            except OSError as e:
                raise DoctopusFileOperationError(
                    f'Failed to create directory {output_dir}: {e}', source_path=source, dest_path=destination
                ) from e

        if destination.exists() and is_healthy(destination):
            try:
                source.unlink()
                publish_file_deleted(source, file_size)
                return True, False
            except PermissionError as e:
                raise DoctopusFileOperationError(
                    f'Permission denied deleting source file: {source}', source_path=source, dest_path=destination
                ) from e
            except OSError as e:
                raise DoctopusFileOperationError(
                    f'Failed to delete source file {source}: {e}', source_path=source, dest_path=destination
                ) from e

        try:
            shutil.move(source, destination)
        except PermissionError as e:
            raise DoctopusFileOperationError(
                f'Permission denied moving {source} to {destination}', source_path=source, dest_path=destination
            ) from e
        except OSError as e:
            disk_full = 'No space left' in str(e)
            msg = 'Disk full' if disk_full else 'Failed to move'
            raise DoctopusFileOperationError(
                f'{msg}: {source} to {destination} - {e}', source_path=source, dest_path=destination
            ) from e

        if not is_healthy(destination):
            raise DoctopusFileOperationError(
                f'Moved file appears corrupted: {destination}', source_path=source, dest_path=destination
            )

        publish_file_moved(source, destination, file_size, True)
        return True, True
