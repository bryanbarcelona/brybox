"""
Event-driven directory verification for brybox file operations.
Path-based verification using pub-sub events to track expected filesystem state.
"""

import os
from pathlib import Path
from typing import Set, Optional

from .bus import event_bus
from .models import FileMovedEvent, FileDeletedEvent, FileCopiedEvent, FileRenamedEvent
from ..utils.logging import log_and_display, get_configured_logger

logger = get_configured_logger("DirectoryVerifier")


class DirectoryVerifier:
    """
    Event-driven verifier that tracks file operations and validates final filesystem state.
    
    Uses pub-sub events to build expected filesystem state, then compares against
    actual filesystem to detect verification failures.
    """
    
    def __init__(self, source_dir: str, target_dir: str):
        """
        Initialize verifier and take initial filesystem snapshots.
        
        Args:
            source_dir: Directory where files are processed from
            target_dir: Directory where files are moved to
        """
        self.source_dir = str(Path(source_dir).resolve())
        self.target_dir = str(Path(target_dir).resolve())
        
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
        
        logger.debug(f"Initialized verifier - Source: {len(self.initial_source_files)} files, "
                   f"Target: {len(self.initial_target_files)} files")
    
    def _scan_directory(self, directory: str) -> Set[str]:
        """
        Scan directory and return set of all file paths.
        
        Args:
            directory: Directory to scan recursively
            
        Returns:
            Set of absolute file paths
        """
        if not os.path.exists(directory):
            os.makedirs(directory)
            return set()
        
        files = set()
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                files.add(str(Path(file_path).resolve()))
        
        return files
    
    def _handle_file_moved(self, event: FileMovedEvent) -> None:
        """
        Handle FileMovedEvent by updating expected filesystem state.
        
        Args:
            event: File move event with source and destination paths
        """
        source_path = str(Path(event.source_path).resolve())
        dest_path = str(Path(event.destination_path).resolve())
        
        # File should no longer be in source location
        self.expected_source_files.discard(source_path)
        
        # File should now be in destination location
        self.expected_target_files.add(dest_path)

        logger.debug(f"Move event: {Path(source_path).name} -> {Path(dest_path).name}")

    def _handle_file_deleted(self, event: FileDeletedEvent) -> None:
        """
        Handle FileDeletedEvent by updating expected filesystem state.
        
        Args:
            event: File deletion event with file path
        """
        file_path = str(Path(event.file_path).resolve())
        
        # File should no longer exist anywhere
        self.expected_source_files.discard(file_path)
        # Note: deletions typically happen in source, but discard from target too for safety
        self.expected_target_files.discard(file_path)
        
        logger.debug(f"Delete event: {Path(file_path).name}")

    def _handle_file_copied(self, event: FileCopiedEvent) -> None:
        """
        Copy: source stays, destination gains the file.
        """
        dest_path = str(Path(event.destination_path).resolve())

        # source is intentionally left untouched
        self.expected_target_files.add(dest_path)

        logger.debug(f"Copy event: {Path(dest_path).name} added to target")

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
        old_path = str(Path(event.old_path).resolve())
        new_path = str(Path(event.new_path).resolve())

        # Determine which expected set contains the old path
        if old_path in self.expected_source_files:
            self.expected_source_files.discard(old_path)
            self.expected_source_files.add(new_path)
            logger.debug(f"Rename event (source): {Path(old_path).name} -> {Path(new_path).name}")
        elif old_path in self.expected_target_files:
            self.expected_target_files.discard(old_path)
            self.expected_target_files.add(new_path)
            logger.debug(f"Rename event (target): {Path(old_path).name} -> {Path(new_path).name}")
        else:
            # Edge-case: rename of an untracked file; treat as a new file in the
            # directory implied by new_path.
            if new_path.startswith(self.source_dir):
                self.expected_source_files.add(new_path)
            elif new_path.startswith(self.target_dir):
                self.expected_target_files.add(new_path)
            logger.debug(f"Rename event (untracked): {Path(old_path).name} -> {Path(new_path).name}")

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
        source_verification = self._verify_directory(
            "source", self.expected_source_files, actual_source_files
        )
        
        target_verification = self._verify_directory(
            "target", self.expected_target_files, actual_target_files
        )
        
        overall_success = source_verification and target_verification
        
        # Summary report
        if overall_success:
            log_and_display(f"✓ Verification passed - Source: {len(actual_source_files)} files, "
                       f"Target: {len(actual_target_files)} files")
        else:
            log_and_display("✗ Verification failed - check file locations above")

        return overall_success
    
    def _verify_directory(self, dir_name: str, expected: Set[str], actual: Set[str]) -> bool:
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
            log_and_display(f"✓ {dir_name} directory verification passed")
            return True
        
        # Report discrepancies
        if missing_files:
            log_and_display(f"✗ Missing files in {dir_name} directory:")
            for file_path in sorted(missing_files):
                log_and_display(f"  - {Path(file_path).name}")
        
        if unexpected_files:
            log_and_display(f"✗ Unexpected files in {dir_name} directory:")
            for file_path in sorted(unexpected_files):
                log_and_display(f"  + {Path(file_path).name}")

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
            "initial_source_count": len(self.initial_source_files),
            "initial_target_count": len(self.initial_target_files),
            "expected_source_count": len(self.expected_source_files),
            "expected_target_count": len(self.expected_target_files),
            "moves_tracked": moves_expected,
            "deletions_tracked": deletions_expected
        }
    
    def cleanup(self) -> None:
        """
        Unsubscribe from events. Call when verification is complete.
        """
        event_bus.unsubscribe(FileMovedEvent, self._handle_file_moved)
        event_bus.unsubscribe(FileDeletedEvent, self._handle_file_deleted)
        event_bus.unsubscribe(FileCopiedEvent, self._handle_file_copied)
        event_bus.unsubscribe(FileRenamedEvent, self._handle_file_renamed)
        logger.debug("Unsubscribed from file operation events")