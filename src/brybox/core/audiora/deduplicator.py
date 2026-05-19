"""Content-based deduplication for audio files using embedded hash tags."""

from pathlib import Path
from typing import Protocol

from brybox.core.audiora.metadata import AudioMetadataExtractor
from brybox.exceptions.audio import AudioraFileOperationError, AudioraMetadataError
from brybox.utils.deduplicator import HashDeduplicator


class DeduplicatorProtocol(Protocol):
    """Protocol for any deduplicator that can check if a source file is a duplicate."""

    def is_duplicate(self, source_path: Path) -> bool: ...

    def add_hash(self, content_hash: str) -> None: ...

    @staticmethod
    def files_have_same_content(file1: str, file2: str) -> bool: ...


class ContentHashDeduplicator:
    def __init__(self, dest_root: Path):
        self.dest_root = dest_root
        self._hashes: set[str] = set()
        self._scanned = False

    def _ensure_index(self) -> None:
        if self._scanned:
            return
        for ext in ('*.m4a', '*.mp3', '*.flac', '*.wav'):
            for f in self.dest_root.rglob(ext):
                h = AudioMetadataExtractor.read_content_hash(f)
                if h is None:
                    h = HashDeduplicator._hash_file(f)
                    AudioMetadataExtractor.write_content_hash(f, h)
                self._hashes.add(h)
        self._scanned = True

    def is_duplicate(self, source_path: Path) -> bool:
        self._ensure_index()
        src_hash = HashDeduplicator._hash_file(source_path)
        return src_hash in self._hashes

    def add_hash(self, content_hash: str) -> None:
        """Add a hash to the in-memory set for in-batch duplicate detection."""
        self._hashes.add(content_hash)

    @staticmethod
    def files_have_same_content(file1: str, file2: str) -> bool:
        """
        Check if two files have identical content via hash comparison.

        Reads stored AUDIOHASH: Comment tag from destination if present to
        avoid re-hashing. Falls back to hashing both files directly if no
        tag exists (e.g. legacy files written before tagging was introduced).

        Args:
            file1: Source file path
            file2: Destination file path

        Returns:
            True if files have identical content, False otherwise

        Raises:
            AudioraFileOperationError: If either file cannot be hashed
        """
        if not Path(file1).exists() or not Path(file2).exists():
            return False

        try:
            dest_hash = AudioMetadataExtractor.read_content_hash(Path(file2))
        except AudioraMetadataError:
            dest_hash = None

        try:
            src_hash = HashDeduplicator._hash_file(Path(file1))
        except OSError as e:
            raise AudioraFileOperationError(
                f'Failed to hash source file {file1}: {e}',
                source_path=file1,
                dest_path=file2,
            ) from e

        if dest_hash:
            return src_hash == dest_hash

        try:
            return src_hash == HashDeduplicator._hash_file(Path(file2))
        except OSError as e:
            raise AudioraFileOperationError(
                f'Failed to hash destination file {file2}: {e}',
                source_path=file1,
                dest_path=file2,
            ) from e
