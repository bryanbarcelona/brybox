"""Protocol definitions for PixelPorter's pluggable components."""

from typing import Protocol
from pathlib import Path

from ..models import ProcessResult


class FileProcessor(Protocol):
    """Interface for file processors like SnapJedi."""
    
    def open(self, file_path: Path) -> None:
        """
        Open and prepare the file for processing.
        
        Args:
            file_path: Path to the file to open
        """
        ...

    def process(self) -> ProcessResult:
        """
        Process image data and return the result.
                   
        Returns:
            ProcessResult with success status, final path, and health check
        """
        ...


class Deduplicator(Protocol):
    """Interface for file deduplication via content hashing."""
    
    def group_by_hash(self, files: list[Path]) -> dict[str, list[Path]]:
        """
        Group files by content hash.
        
        Computes a hash (e.g., SHA-256) for each file and groups files
        with identical content together.
        
        Args:
            files: List of file paths to analyze
            
        Returns:
            Dict mapping hash string -> list of file paths with that hash.
            Files with unique content will have a list with one element.
            
        Example:
            {
                "abc123def...": [Path("photo1.jpg")],  # Unique
                "789ghi456...": [  # Duplicates
                    Path("photo2.jpg"),
                    Path("photo2_copy.jpg"),
                    Path("photo2_backup.jpg")
                ]
            }
        """
        ...