"""Protocol definitions for PixelPorter's pluggable components."""

from typing import Protocol
from pathlib import Path
from dataclasses import dataclass, field

from ..models import ProcessResult


@dataclass
class PorterResult:
    """Result of porter operation."""
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    duplicates_removed: int = 0
    errors: list[str] = field(default_factory=list)


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

class FileFilter(Protocol):
    """Interface for file filtering based on extensions."""
    def is_valid(self, path: Path) -> bool:
            ...
    def get_extensions(self) -> set[str]:
            ...

class MetadataFixer(Protocol):
    """Interface for fixing metadata of files."""
    def fix_metadata(
        self,
        mappings: list[tuple[Path, Path, list[Path]]],
        dry_run: bool,
        action_prefix: str
    ) -> None: ...

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