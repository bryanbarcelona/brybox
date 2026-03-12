"""Porter-specific exception hierarchy."""

from pathlib import Path

from brybox.exceptions.base import BryboxError


class PorterError(BryboxError):
    """Base exception for all Porter-related errors."""

    def __init__(self, message: str, resource_path: str | Path | None = None):
        self.resource_path = Path(resource_path) if resource_path else None
        super().__init__(message)


# The "Big Four"
class PorterResourceNotFoundError(PorterError):
    """Source file/directory doesn't exist or vanishes during processing."""


class PorterOperationFailedError(PorterError):
    """Core operation failed (processing, hashing, metadata ops)."""

    def __init__(
        self,
        message: str,
        resource_path: str | Path | None = None,
        operation: str | None = None,
        error_detail: str | None = None,
    ):
        self.operation = operation
        self.error_detail = error_detail
        super().__init__(message, resource_path)


class PorterConfigurationError(PorterError):
    """Invalid configuration or missing dependencies. FATAL."""

    def __init__(self, message: str, config_key: str | None = None):
        self.config_key = config_key
        super().__init__(message)


class PorterFileOperationError(PorterError):
    """File operations (copy/move/delete) failed."""

    def __init__(
        self,
        message: str,
        source_path: str | Path | None = None,
        dest_path: str | Path | None = None,
        operation: str | None = None,
    ):
        self.source_path = Path(source_path) if source_path else None
        self.dest_path = Path(dest_path) if dest_path else None
        self.operation = operation
        super().__init__(message, resource_path=source_path)


# Porter-specific extensions
class PorterMetadataError(PorterError):
    """Metadata read/write/fix operations failed."""

    def __init__(self, message: str, resource_path: str | Path | None = None, metadata_field: str | None = None):
        self.metadata_field = metadata_field
        super().__init__(message, resource_path)


class PorterCorruptedFileError(PorterError):
    """File exists but is corrupted or unreadable."""


class PorterStagingError(PorterError):
    """Staging area operations failed."""

    def __init__(self, message: str, staging_path: Path | None = None, operation: str | None = None):
        self.staging_path = staging_path
        self.operation = operation
        super().__init__(message, resource_path=staging_path)
