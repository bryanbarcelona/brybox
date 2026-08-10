import hashlib
import struct
from collections import defaultdict
from pathlib import Path

from brybox.utils.logging import get_configured_logger

logger = get_configured_logger('Deduplicator')

_JPEG_SOI = b'\xff\xd8'
_JPEG_APP_RANGE = range(0xE0, 0xF0)  # 0xFFE0–0xFFEF
_JPEG_COMMENT = 0xFE


class HashDeduplicator:
    """
    File deduplicator using GPS-stable content hashing for JPEGs, SHA-256 for everything else.

    For JPEG files, parses past all APP segments (EXIF, GPS, XMP, C2PA — everything
    in 0xFFE0-0xFFEF markers) and hashes only the image data from the first non-APP
    marker onwards. Two copies of the same photo with different metadata (e.g. GPS
    stripped by Android or Dropbox) produce the same hash. Falls back to full SHA-256
    for non-JPEG files or any parse failure.
    """

    def __init__(self, chunk_size: int = 8192):
        """
        Initialize deduplicator.

        Args:
            chunk_size: Bytes to read per chunk during SHA-256 fallback hashing.
        """
        self.chunk_size = chunk_size

    def group_by_hash(self, files: list[Path]) -> dict[str, list[Path]]:
        """
        Group files by identity key.

        Args:
            files: List of file paths to analyze.

        Returns:
            Dict mapping identity key -> list of files with that key.

        Example:
            {
                "a1b2c3...": [Path("file1.jpg"), Path("file1_dropbox.jpg")],
                "d4e5f6...": [Path("file2.jpg")],
            }
        """
        hash_groups: dict[str, list[Path]] = defaultdict(list)
        for file_path in files:
            try:
                key = self._compute_key(file_path)
                hash_groups[key].append(file_path)
            except OSError:
                continue
        return dict(hash_groups)

    @staticmethod
    def is_duplicate(file_a: Path, file_b: Path) -> bool:
        """
        Return True if both files represent the same image content.

        Args:
            file_a: First file to compare.
            file_b: Second file to compare.
        """
        try:
            return HashDeduplicator._compute_key(file_a) == HashDeduplicator._compute_key(file_b)
        except OSError:
            return False

    @staticmethod
    def _compute_key(path: Path) -> str:
        """JPEG content hash for .jpg/.jpeg files, full SHA-256 fallback for everything else."""
        if path.suffix.lower() in {'.jpg', '.jpeg'}:
            try:
                return HashDeduplicator._jpeg_content_hash(path)
            except (ValueError, struct.error, OSError):
                logger.debug('JPEG content hash failed for %s, falling back to full-file hash', path.name)
        return HashDeduplicator._hash_file(path)

    @staticmethod
    def _jpeg_content_hash(path: Path) -> str:
        """
        Hash JPEG content from the first non-APP marker onwards.

        Skips all APP segments (0xFFE0-0xFFEF) which contain EXIF, GPS, XMP,
        and C2PA metadata. Everything from DQT onwards (quantization tables,
        Huffman tables, frame header, compressed scan data) is hashed — this
        portion is identical between copies of the same photo regardless of
        what any upload path did to the metadata.

        Args:
            path: JPEG file to hash.

        Returns:
            SHA-256 hex string of the image content bytes.

        Raises:
            ValueError: If file is not a valid JPEG.
        """
        data = path.read_bytes()

        if data[:2] != _JPEG_SOI:
            raise ValueError(f'Not a JPEG: {path.name}')

        pos = 2
        while pos + 3 < len(data):
            if data[pos] != 0xFF:
                break
            marker = data[pos + 1]
            if marker in _JPEG_APP_RANGE or marker == _JPEG_COMMENT:
                length = struct.unpack('>H', data[pos + 2 : pos + 4])[0]
                pos += 2 + length
            else:
                break

        return hashlib.sha256(data[pos:]).hexdigest()

    @staticmethod
    def _hash_file(path: Path, chunk_size: int = 8192) -> str:
        """
        Compute SHA-256 hash of raw file content.

        Args:
            path: File to hash.
            chunk_size: Bytes to read at a time.

        Returns:
            Hex string of SHA-256 hash.
        """
        sha256 = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
