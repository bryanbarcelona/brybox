"""
Event-driven directory verification for brybox file operations.
Path-based verification using pub-sub events to track expected filesystem state.
"""

from pathlib import Path

from brybox.events.bus import event_bus
from brybox.events.models import FileAddedEvent, FileCopiedEvent, FileDeletedEvent, FileMovedEvent, FileRenamedEvent
from brybox.utils.logging import get_configured_logger, log_and_display

logger = get_configured_logger('DirectoryVerifier')


class DirectoryVerifier:
    """
    Event-driven verifier that tracks file operations and validates final filesystem state.

    Uses pub-sub events to build expected filesystem state, then compares against
    actual filesystem to detect verification failures.
    """

    def __init__(self, source_dir: str | Path, target_dir: str | Path):
        """
        Initialize verifier and take initial filesystem snapshots.

        Args:
            source_dir: Directory where files are processed from
            target_dir: Directory where files are moved to
        """
        self.source_dir = Path(source_dir).resolve()
        self.target_dir = Path(target_dir).resolve()

        # Take initial snapshots
        self.initial_source_files = self._scan_directory(self.source_dir)
        self.initial_target_files = self._scan_directory(self.target_dir)

        # Expected final state (will be updated by events)
        self.expected_source_files = self.initial_source_files.copy()
        self.expected_target_files = self.initial_target_files.copy()

        # Subscribe to file operation events
        event_bus.subscribe(FileMovedEvent, self._handle_file_moved)
        event_bus.subscribe(FileDeletedEvent, self._handle_file_deleted)
        event_bus.subscribe(FileCopiedEvent, self._handle_file_copied)
        event_bus.subscribe(FileRenamedEvent, self._handle_file_renamed)
        event_bus.subscribe(FileAddedEvent, self._handle_file_added)

        log_and_display(
            f'Initialized verifier - Source: {len(self.initial_source_files)} files, '
            f'Target: {len(self.initial_target_files)} files',
            level='debug',
        )

    @staticmethod
    def _scan_directory(directory: Path) -> set[Path]:
        """
        Scan directory and return set of all file paths.

        Args:
            directory: Directory to scan recursively

        Returns:
            Set of absolute file paths as Path objects
        """
        if not directory.exists():
            directory.mkdir(parents=True)
            return set()

        return {p.resolve() for p in directory.rglob('*') if p.is_file()}

    def _handle_file_moved(self, event: FileMovedEvent) -> None:
        """
        Handle FileMovedEvent by updating expected filesystem state.

        Args:
            event: File move event with source and destination paths
        """
        source_path = event.source_path.resolve()
        dest_path = event.destination_path.resolve()

        # File should no longer be in source location
        self.expected_source_files.discard(source_path)

        # File should now be in destination location
        self.expected_target_files.add(dest_path)

        log_and_display(f'Move event: {source_path.name} -> {dest_path.name}', level='debug')

    def _handle_file_deleted(self, event: FileDeletedEvent) -> None:
        """
        Handle FileDeletedEvent by updating expected filesystem state.

        Args:
            event: File deletion event with file path
        """
        file_path = event.file_path.resolve()

        # File should no longer exist anywhere
        self.expected_source_files.discard(file_path)
        # Note: deletions typically happen in source, but discard from target too for safety
        self.expected_target_files.discard(file_path)

        log_and_display(f'Delete event: {file_path.name}', level='debug')

    def _handle_file_copied(self, event: FileCopiedEvent) -> None:
        """
        Copy: source stays, destination gains the file.
        """
        dest_path = event.destination_path.resolve()

        # source is intentionally left untouched
        self.expected_target_files.add(dest_path)

        log_and_display(f'Copy event: {dest_path.name} added to target', level='debug')

    def _handle_file_renamed(self, event: FileRenamedEvent) -> None:
        """
        Handle FileRenamedEvent by updating expected filesystem state.

        Renaming is treated as an in-place operation: the file stays in the same
        directory but changes its name.  We therefore:
          1. Remove the old path from the expected set it currently belongs to.
          2. Add the new path to that same set.

        Args:
            event: File rename event with old_path and new_path.
        """
        old_path = event.old_path.resolve()
        new_path = event.new_path.resolve()

        # Determine which expected set contains the old path
        if old_path in self.expected_source_files:
            self.expected_source_files.discard(old_path)
            self.expected_source_files.add(new_path)
            log_and_display(f'Rename event (source): {old_path.name} -> {new_path.name}', level='debug')
        elif old_path in self.expected_target_files:
            self.expected_target_files.discard(old_path)
            self.expected_target_files.add(new_path)
            log_and_display(f'Rename event (target): {old_path.name} -> {new_path.name}', level='debug')
        else:
            # Edge-case: rename of an untracked file; treat as a new file in the
            # directory implied by new_path.
            if new_path.is_relative_to(self.source_dir):
                self.expected_source_files.add(new_path)
            elif new_path.is_relative_to(self.target_dir):
                self.expected_target_files.add(new_path)
            log_and_display(f'Rename event (untracked): {old_path.name} -> {new_path.name}', level='debug')

    def _handle_file_added(self, event: FileAddedEvent) -> None:
        """
        Handle FileAddedEvent by updating expected filesystem state.

        A new file should now appear in the expected target or source set,
        depending on its location. The file must have passed health checks
        before this event is published.

        Args:
            event: File addition event with file path and metadata
        """
        file_path = event.file_path.resolve()

        # Determine whether the added file belongs to source or target directory
        if file_path.is_relative_to(self.source_dir):
            self.expected_source_files.add(file_path)
            log_and_display(f'Add event (source): {file_path.name}', level='debug')
        elif file_path.is_relative_to(self.target_dir):
            self.expected_target_files.add(file_path)
            log_and_display(f'Add event (target): {file_path.name}', level='debug')
        else:
            # Unrecognized location — log for investigation
            log_and_display(f'Add event (untracked): {file_path} not under source or target dirs', level='debug')

    def report(self) -> bool:
        """
        Verify actual filesystem state matches expected state based on events.

        Returns:
            True if verification passed, False if discrepancies found
        """
        # Take final snapshots
        actual_source_files = self._scan_directory(self.source_dir)
        actual_target_files = self._scan_directory(self.target_dir)

        # Compare expected vs actual
        source_verification = self._verify_directory('source', self.expected_source_files, actual_source_files)

        target_verification = self._verify_directory('target', self.expected_target_files, actual_target_files)

        overall_success = source_verification and target_verification

        # Summary report
        if overall_success:
            log_and_display(
                f'✓ Verification passed - Source: {len(actual_source_files)} files, '
                f'Target: {len(actual_target_files)} files'
            )
        else:
            log_and_display('✗ Verification failed - check file locations above')

        return overall_success

    @staticmethod
    def _verify_directory(dir_name: str, expected: set[Path], actual: set[Path]) -> bool:
        """
        Compare expected vs actual file sets for a directory.

        Args:
            dir_name: Human-readable directory name for logging
            expected: Set of expected file paths
            actual: Set of actual file paths

        Returns:
            True if sets match, False if discrepancies found
        """
        missing_files = expected - actual
        unexpected_files = actual - expected

        if not missing_files and not unexpected_files:
            log_and_display(f'✓ {dir_name} directory verification passed')
            return True

        # Report discrepancies
        if missing_files:
            log_and_display(f'✗ Missing files in {dir_name} directory:')
            for file_path in sorted(missing_files):
                log_and_display(f'  - {file_path.name}')

        if unexpected_files:
            log_and_display(f'✗ Unexpected files in {dir_name} directory:')
            for file_path in sorted(unexpected_files):
                log_and_display(f'  + {file_path.name}')

        return False

    def get_stats(self) -> dict:
        """
        Get current verification statistics.

        Returns:
            Dictionary with file counts and expected changes
        """
        moves_expected = len(self.expected_target_files) - len(self.initial_target_files)
        deletions_expected = len(self.initial_source_files) - len(self.expected_source_files) - moves_expected

        return {
            'initial_source_count': len(self.initial_source_files),
            'initial_target_count': len(self.initial_target_files),
            'expected_source_count': len(self.expected_source_files),
            'expected_target_count': len(self.expected_target_files),
            'moves_tracked': moves_expected,
            'deletions_tracked': deletions_expected,
        }

    def cleanup(self) -> None:
        """
        Unsubscribe from events. Call when verification is complete.
        """
        event_bus.unsubscribe(FileMovedEvent, self._handle_file_moved)
        event_bus.unsubscribe(FileDeletedEvent, self._handle_file_deleted)
        event_bus.unsubscribe(FileCopiedEvent, self._handle_file_copied)
        event_bus.unsubscribe(FileRenamedEvent, self._handle_file_renamed)
