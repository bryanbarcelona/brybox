"""Hash-based file deduplicator for PixelPorter.

"""

import hashlib
from pathlib import Path
from collections import defaultdict


class HashDeduplicator:
    """Content-based file deduplicator using SHA-256 hashing."""
    
    def __init__(self, chunk_size: int = 8192):
        """
        Initialize deduplicator.
        
        Args:
            chunk_size: Bytes to read at a time
        """
        self.chunk_size = chunk_size
    
    def group_by_hash(self, files: list[Path]) -> dict[str, list[Path]]:
        """
        Group files by content hash.
        
        Args:
            files: List of file paths to analyze
            
        Returns:
            Dict mapping hash -> list of files with that hash
            
        Example:
            {
                "abc123...": [Path("file1.jpg")],
                "def456...": [Path("file2.jpg"), Path("file2_copy.jpg")]
            }
        """
        hash_groups = defaultdict(list)
        
        for file_path in files:
            try:
                file_hash = self._hash_file(file_path)
                hash_groups[file_hash].append(file_path)
            except (OSError, IOError) as e:
                # Skip files we can't read (permissions, corrupt, etc.)
                # Caller can handle logging if needed
                continue
        
        return dict(hash_groups)
    
    def _hash_file(self, path: Path) -> str:
        """
        Compute SHA-256 hash of file content.
        
        Reads file in chunks to handle large files efficiently without
        loading entire file into memory.
        
        Args:
            path: File to hash
            
        Returns:
            Hex string of SHA-256 hash
        """
        sha256 = hashlib.sha256()
        
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(self.chunk_size), b''):
                sha256.update(chunk)
        
        return sha256.hexdigest()