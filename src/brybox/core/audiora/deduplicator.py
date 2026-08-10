"""Content-based deduplication for audio files."""

from pathlib import Path
from typing import Protocol

from brybox.exceptions.audio import AudioraFileOperationError
from brybox.utils.deduplicator import HashDeduplicator
from brybox.utils.health_check import is_audio_healthy
from brybox.utils.logging import log_and_display


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
        """
        Build the destination hash index.

        Hashes every destination file directly - no cache is stored in the
        files themselves, since embedding a hash in a file's own metadata
        made every file's raw-byte hash unique to itself the moment it was
        written, permanently defeating cross-file duplicate detection.

        One unreadable file must never take down the whole scan - each file
        is isolated so a single bad entry gets skipped (and logged) rather
        than aborting `_scanned` before it's ever set, which would otherwise
        force every subsequent file in the batch to re-run this full scan
        from zero against the same bad file.
        """
        if self._scanned:
            return
        for ext in ('*.m4a', '*.mp3', '*.flac', '*.wav'):
            for f in self.dest_root.rglob(ext):
                if not is_audio_healthy(f):
                    log_and_display(f'⚠️ Skipping unhealthy audio file during dedup index: {f}', level='warning')
                    continue
                try:
                    self._hashes.add(HashDeduplicator._hash_file(f))
                except OSError as e:
                    log_and_display(f'⚠️ Skipping {f} during dedup index: {e}', level='warning')
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
            return HashDeduplicator._hash_file(Path(file1)) == HashDeduplicator._hash_file(Path(file2))
        except OSError as e:
            raise AudioraFileOperationError(
                f'Failed to hash {file1} or {file2}: {e}',
                source_path=file1,
                dest_path=file2,
            ) from e
