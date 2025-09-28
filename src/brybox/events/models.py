"""
Event models for brybox pub-sub system.
File-type agnostic events for tracking file operations across all processors.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class FileMovedEvent:
    """
    Event published when a file is successfully moved from source to destination.
    
    This event is only published for successful moves where the destination file
    passes health checks. Failed moves or unhealthy files do not generate events.
    """
    source_path: str
    destination_path: str
    file_size: int
    is_healthy: bool
    timestamp: datetime
    
    def __post_init__(self):
        """Validate event data on creation."""
        if not self.source_path or not self.destination_path:
            raise ValueError("Source and destination paths cannot be empty")
        
        if self.file_size < 0:
            raise ValueError("File size cannot be negative")
    
    @property
    def source_name(self) -> str:
        """Get the filename from source path."""
        return Path(self.source_path).name
    
    @property
    def destination_name(self) -> str:
        """Get the filename from destination path."""
        return Path(self.destination_path).name
    
    @property
    def source_dir(self) -> str:
        """Get the directory from source path."""
        return str(Path(self.source_path).parent)
    
    @property
    def destination_dir(self) -> str:
        """Get the directory from destination path."""
        return str(Path(self.destination_path).parent)
    
    def __repr__(self) -> str:
        """Human-readable representation for debugging."""
        return (f"FileMovedEvent("
                f"'{self.source_name}' -> '{self.destination_name}', "
                f"size={self.file_size}, healthy={self.is_healthy})")

@dataclass(frozen=True)
class FileDeletedEvent:
    """
    Event published when a file is successfully deleted.

    This event is published for successful file deletions.
    """
    file_path: str
    file_size: int
    timestamp: datetime
    
    def __post_init__(self):
        """Validate event data on creation."""
        if not self.file_path:
            raise ValueError("File path cannot be empty")
        
        if self.file_size < 0:
            raise ValueError("File size cannot be negative")
    
    @property
    def filename(self) -> str:
        """Get the filename from file path."""
        return Path(self.file_path).name
    
    @property
    def file_dir(self) -> str:
        """Get the directory from file path."""
        return str(Path(self.file_path).parent)
    
    def __repr__(self) -> str:
        """Human-readable representation for debugging."""
        return (f"FileDeletedEvent("
                f"'{self.filename}', "
                f"size={self.file_size})")
    

# ---------------------------------------------------------------------------
# TODO: Implement FileIgnoredEvent
# @dataclass(frozen=True)
# class FileIgnoredEvent:
#     """Event for when files are skipped due to processing rules."""
#     pass
#
# TODO: Implement FileCopyEvent
# @dataclass(frozen=True)
# class FileCopyEvent:
#     """Event for when files are copied as part of processing."""
#     pass
# ---------------------------------------------------------------------------