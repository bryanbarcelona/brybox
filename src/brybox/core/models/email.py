from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from email.message import Message

    from brybox.utils.credentials import WebCredentials


@dataclass(frozen=True)
class ProcessingContext:
    meta: EmailMeta
    save_dir: Path
    msg: Message | None = None
    creds: WebCredentials | None = None
    # Future extensions


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
