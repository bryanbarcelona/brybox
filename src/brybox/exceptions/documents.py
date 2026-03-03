"""
Doctopus-specific exceptions for PDF processing.
All exceptions inherit from DoctopusError → BryboxError.
"""

from pathlib import Path

from brybox.exceptions.base import BryboxError


class DoctopusError(BryboxError):
    """Base exception for all Doctopus-related errors."""

    def __init__(self, message: str, pdf_path: str | Path | None = None):
        self.pdf_path = Path(pdf_path) if pdf_path else None
        super().__init__(message)


class DoctopusPDFError(DoctopusError):
    """Base for PDF file-related errors."""

    def __init__(self, message: str, pdf_path: str | Path | None = None):
        super().__init__(message, pdf_path)


class DoctopusPDFNotFoundError(DoctopusPDFError):
    """PDF file does not exist."""


class DoctopusConfigurationError(DoctopusError):
    """Configuration issues."""

    def __init__(self, message: str, pdf_path: str | Path | None = None):
        super().__init__(message, pdf_path)


class DoctopusFileOperationError(DoctopusError):
    """File system operation failed."""

    def __init__(self, message: str, source_path: str | Path | None = None, dest_path: str | Path | None = None):
        self.source_path = Path(source_path) if source_path else None
        self.dest_path = Path(dest_path) if dest_path else None
        super().__init__(message, pdf_path=source_path)
