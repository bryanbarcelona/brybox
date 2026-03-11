import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Playwright,
)

from brybox.core.models.scrapers import DownloadResult
from brybox.utils.logging import log_and_display

logger = logging.getLogger('WebMarionette')


class BaseScraper(ABC):
    """
    Base class for web scrapers that download documents from various portals.

    Provides common browser setup, error handling patterns, and result construction.
    Each concrete scraper implements its specific download logic.
    """

    def __init__(self, username: str, password: str, download_dir: str | None = None, *, headless: bool = True):
        self.username = username
        self.password = password
        self.download_dir = download_dir or str(Path.home() / 'Downloads')
        self.headless = headless

    @abstractmethod
    def download(self) -> DownloadResult:
        """
        Execute the scraping operation to download documents.
        Each scraper implements its specific logic.
        """

    def _create_browser_context(self, playwright: Playwright, **context_kwargs: Any) -> tuple[Browser, BrowserContext]:
        """Create and configure browser context with common settings."""
        browser = playwright.chromium.launch(headless=self.headless)
        return browser, browser.new_context(**context_kwargs)

    @staticmethod
    def _build_result(total_found: int, downloaded: int, errors: list[str] | None = None) -> DownloadResult:
        """Construct result from operation statistics."""
        if errors is None:
            errors = []

        failed = total_found - downloaded
        success = downloaded == total_found and total_found > 0

        return DownloadResult(
            success=success, total_found=total_found, downloaded=downloaded, failed=failed, errors=errors
        )

    @staticmethod
    def _failure_result(error_msg: str, total_found: int = 0) -> DownloadResult:
        """Construct a failure result with consistent logging."""
        log_and_display(error_msg, level='error', log=True, sticky=False)
        return DownloadResult(
            success=False,
            total_found=total_found,
            downloaded=0,
            failed=total_found if total_found > 0 else 1,
            errors=[error_msg],
        )
