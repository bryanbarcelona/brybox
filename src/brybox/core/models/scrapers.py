"""
Models for web automation results.
"""

from dataclasses import dataclass, field


@dataclass
class DownloadResult:
    """
    Result of a web automation download operation.

    Attributes:
        success: True if at least one document was successfully downloaded
        total_found: Total number of documents found/attempted
        downloaded: Number of documents successfully downloaded
        failed: Number of documents that failed to download
        errors: List of error messages for failed downloads
    """

    success: bool
    total_found: int
    downloaded: int
    failed: int
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Allow truthiness checks: if result: ..."""
        return self.success

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f'DownloadResult(success={self.success}, '
            f'downloaded={self.downloaded}/{self.total_found}, '
            f'failed={self.failed})'
        )
