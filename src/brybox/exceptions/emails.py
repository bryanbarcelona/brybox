from pathlib import Path

from brybox.exceptions.base import BryboxError


class InboxKrakenError(BryboxError):
    """Base exception for all InboxKraken-related errors."""

    def __init__(self, message: str, resource_path: str | Path | None = None):
        self.resource_path = Path(resource_path) if resource_path else None
        super().__init__(message)


class InboxKrakenResourceNotFoundError(InboxKrakenError):
    """Resource (file/dir/UID) does not exist."""


class InboxKrakenLinkNotFoundError(InboxKrakenResourceNotFoundError):
    """Specific expected link (e.g. invoice) was not found in email body."""


class InboxKrakenOperationFailedError(InboxKrakenError):
    """Core operation failed."""

    def __init__(self, message: str, resource_path: str | Path | None = None, error_detail: str | None = None):
        self.error_detail = error_detail
        super().__init__(message, resource_path)


class InboxKrakenNetworkError(InboxKrakenOperationFailedError):
    """Temporary network-level failures (Connection refused, DNS)."""


class InboxKrakenTimeoutError(InboxKrakenNetworkError):
    """Operation timed out (IMAP or HTTP)."""


class InboxKrakenConfigurationError(InboxKrakenError):
    """Invalid configuration or missing dependencies."""

    def __init__(self, message: str, config_key: str | None = None):
        self.config_key = config_key
        super().__init__(message)


class InboxKrakenFileOperationError(InboxKrakenError):
    """File operations (move/copy/delete/write) failed."""

    def __init__(self, message: str, source_path: str | Path | None = None, dest_path: str | Path | None = None):
        self.source_path = Path(source_path) if source_path else None
        self.dest_path = Path(dest_path) if dest_path else None
        super().__init__(message, resource_path=source_path)
