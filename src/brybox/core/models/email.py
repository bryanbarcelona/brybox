from pathlib import Path
from typing import NamedTuple


class ProcessResult(NamedTuple):
    """Result of processing a single email or attachment."""

    success: bool
    target_path: Path | None
    is_healthy: bool
    error_message: str = ''
    can_delete: bool = False


class EmailMeta(NamedTuple):
    """Extracted metadata from a raw email."""

    uid: int
    sender: str
    subject: str
    body_html: str
    attachments: list[str]
    invoice_link: str | None = None
