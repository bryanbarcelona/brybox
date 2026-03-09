"""
SnapJedi-specific exceptions for image conversion.
All exceptions inherit from SnapJediError → BryboxError.
"""

from pathlib import Path

from brybox.exceptions.base import BryboxError


class SnapJediError(BryboxError):
    """Base exception for all SnapJedi-related errors."""

    def __init__(self, message: str, image_path: str | Path | None = None):
        self.image_path = Path(image_path) if image_path else None
        super().__init__(message)


class SnapJediConversionError(SnapJediError):
    """Base for image conversion errors."""

    def __init__(self, message: str, image_path: str | Path | None = None):
        super().__init__(message, image_path)


class SnapJediConversionFailedError(SnapJediConversionError):
    """Image conversion process failed."""

    def __init__(self, message: str, image_path: str | Path | None = None, stderr: str | None = None):
        self.stderr = stderr
        super().__init__(message, image_path)


class SnapJediConversionTimeoutError(SnapJediConversionError):
    """Image conversion timed out."""

    def __init__(self, message: str, image_path: str | Path | None = None, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds
        super().__init__(message, image_path)


class SnapJediToolNotFoundError(SnapJediError):
    """Required image conversion tool not found."""

    def __init__(self, message: str, tool_name: str | None = None):
        self.tool_name = tool_name
        super().__init__(message)


class SnapJediFileOperationError(SnapJediError):
    """File system operation failed during conversion."""

    def __init__(self, message: str, source_path: str | Path | None = None, dest_path: str | Path | None = None):
        self.source_path = Path(source_path) if source_path else None
        self.dest_path = Path(dest_path) if dest_path else None
        # Pass source_path as image_path to parent for consistent context
        super().__init__(message, image_path=source_path)


class SnapJediImageNotFoundError(SnapJediError):
    """Source image file does not exist."""

    def __init__(self, message: str, image_path: str | Path | None = None):
        super().__init__(message, image_path)


class SnapJediMetadataError(SnapJediError):
    """Base for metadata-related errors."""

    def __init__(self, message: str, image_path: str | Path | None = None):
        super().__init__(message, image_path)


class SnapJediMetadataReadError(SnapJediMetadataError):
    """Failed to read metadata from image."""

    def __init__(self, message: str, image_path: str | Path | None = None, stderr: str | None = None):
        self.stderr = stderr
        super().__init__(message, image_path)


class SnapJediMetadataParseError(SnapJediMetadataError):
    """Failed to parse specific metadata field."""

    def __init__(self, message: str, image_path: str | Path | None = None, field: str | None = None):
        self.field = field
        super().__init__(message, image_path)
