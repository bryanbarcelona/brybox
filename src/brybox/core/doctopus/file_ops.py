"""
File move operations for the Doctopus pipeline.
"""

import shutil
from pathlib import Path

from brybox.events.bus import publish_file_deleted, publish_file_moved
from brybox.utils.health_check import is_healthy
from brybox.utils.logging import get_configured_logger, log_and_display

logger = get_configured_logger('Doctopus')


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
            logger.warning('Source file does not exist: %s', source)
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

        if not output_dir.exists():
            output_dir.mkdir(parents=True)

        if destination.exists() and is_healthy(destination):
            source.unlink()
            log_and_display(f'Destination exists. Deleted source file: {source}')
            publish_file_deleted(source, file_size)
            return True, False

        shutil.move(source, destination)

        if not is_healthy(destination):
            log_and_display(f'Moved file is corrupted: {destination}', level='error')
            return False, False

        log_and_display(f'Moved {source} to {destination}.')
        publish_file_moved(source, destination, file_size, True)
        return True, True
