"""Protocol definitions for PixelPorter's pluggable components."""

from typing import Protocol, NamedTuple
from pathlib import Path


class ProcessResult(NamedTuple):
    """Result of processing a single file."""
    success: bool
    target_path: Path
    is_healthy: bool
    error_message: str = ""


class FileProcessor(Protocol):
    """Interface for file processors like SnapJedi."""
    
    def open(self, file_path: Path) -> None:
        """
        Open and prepare the file for processing.
        
        Args:
            file_path: Path to the file to open
        """
        ...

    def rename_jpg(self) -> ProcessResult:
        """
        Process image data and return the result.
                   
        Returns:
            ProcessResult with success status, final path, and health check
        """
        ...


class Deduplicator(Protocol):
    """Interface for deduplication strategies."""
    
    def find_duplicates(
        self, 
        source_files: list[Path], 
        target_dir: Path
    ) -> set[Path]:
        """
        Identify files that should be skipped (duplicates).
        
        Args:
            source_files: List of files to check
            target_dir: Target directory to check against
            
        Returns:
            Set of source file paths that are duplicates and should be skipped
        """
        ...