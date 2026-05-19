"""
Literature-specific exceptions for the DoiSmith PDF processing pipeline.
All exceptions inherit from LiteratureError → BryboxError.

Severity guide (both continue the batch — distinction is log level only):
    LiteraturePDFError / LiteraturePDFNotFoundError
        → log as ERROR   — file is unreadable, genuinely unexpected
    LiteratureDOIError / LiteratureDOINotFoundError / LiteratureMetadataError
        → log as WARNING — no DOI or bad CrossRef response, normal for non-papers
    LiteratureFileOperationError / LiteratureConfigurationError
        → log as ERROR   — systemic issue, warrants attention
"""

from pathlib import Path

from brybox.exceptions.base import BryboxError


class LiteratureError(BryboxError):
    """Base exception for all DoiSmith pipeline errors."""

    def __init__(self, message: str, pdf_path: str | Path | None = None):
        self.pdf_path = Path(pdf_path) if pdf_path else None
        super().__init__(message)


# ── PDF I/O ───────────────────────────────────────────────────────────────────


class LiteraturePDFError(LiteratureError):
    """PDF file is unreadable — corrupted, password-protected, or malformed."""


class LiteraturePDFNotFoundError(LiteraturePDFError):
    """PDF file does not exist at the given path."""


# ── DOI / CrossRef ────────────────────────────────────────────────────────────


class LiteratureDOIError(LiteratureError):
    """Base for DOI resolution failures."""


class LiteratureDOINotFoundError(LiteratureDOIError):
    """No DOI expression could be extracted from the PDF content.

    Expected for non-paper PDFs (receipts, manuals, pudding recipes).
    Log as WARNING, not ERROR.
    """


class LiteratureMetadataError(LiteratureDOIError):
    """CrossRef returned a response but required metadata fields are missing or unusable.

    Distinct from a network/HTTP failure — the API responded but the payload
    doesn't contain enough to build a filename.
    """


# ── File system ───────────────────────────────────────────────────────────────


class LiteratureFileOperationError(LiteratureError):
    """A filesystem move, delete, or directory creation failed."""

    def __init__(
        self,
        message: str,
        source_path: str | Path | None = None,
        dest_path: str | Path | None = None,
    ):
        self.source_path = Path(source_path) if source_path else None
        self.dest_path = Path(dest_path) if dest_path else None
        super().__init__(message, pdf_path=source_path)


# ── Configuration ─────────────────────────────────────────────────────────────


class LiteratureConfigurationError(LiteratureError):
    """Settings are missing or invalid — target_dir not configured, etc."""
