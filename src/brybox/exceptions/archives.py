"""
ZipWarden-specific exceptions for archive extraction and flattening.
All exceptions inherit from ZipWardenError → BryboxError.
"""

from pathlib import Path

from brybox.exceptions.base import BryboxError


class ZipWardenError(BryboxError):
    """Base exception for all ZipWarden-related errors."""

    def __init__(self, message: str, archive_path: str | Path | None = None):
        self.archive_path = Path(archive_path) if archive_path else None
        super().__init__(message)


class ZipWardenConfigurationError(ZipWardenError):
    """Invalid configuration — directory does not exist, conflicting parameters, etc. FATAL."""


class ZipWardenCorruptArchiveError(ZipWardenError):
    """Archive exists but is not a valid ZIP file or is truncated."""


class ZipWardenExtractionError(ZipWardenError):
    """Extraction succeeded partially or fully but post-extraction validation failed."""

    def __init__(self, message: str, archive_path: str | Path | None = None, member: str | None = None):
        self.member = member
        super().__init__(message, archive_path)


class ZipWardenFileOperationError(ZipWardenError):
    """Filesystem operation (move, delete) failed during extraction or cleanup."""

    def __init__(
        self,
        message: str,
        archive_path: str | Path | None = None,
        source_path: str | Path | None = None,
        dest_path: str | Path | None = None,
    ):
        self.source_path = Path(source_path) if source_path else None
        self.dest_path = Path(dest_path) if dest_path else None
        super().__init__(message, archive_path)
