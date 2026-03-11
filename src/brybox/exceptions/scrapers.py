from pathlib import Path

from brybox.exceptions.base import BryboxError


class ScraperError(BryboxError):
    """Base class for all scraping-related failures."""

    def __init__(self, message: str, url: str | None = None, scraper_name: str | None = None):
        self.url = url
        self.scraper_name = scraper_name
        super().__init__(message)


class ScraperAuthenticationError(ScraperError):
    """Login failed - credentials invalid or site changed."""

    def __init__(self, message: str, url: str | None = None, scraper_name: str | None = None):
        super().__init__(message, url, scraper_name)


class ScraperNavigationError(ScraperError):
    """Failed to navigate to expected page or find elements."""

    def __init__(
        self, message: str, url: str | None = None, scraper_name: str | None = None, expected_element: str | None = None
    ):
        self.expected_element = expected_element
        super().__init__(message, url, scraper_name)


class ScraperTimeoutError(ScraperError):
    """Operation timed out."""

    def __init__(
        self, message: str, url: str | None = None, scraper_name: str | None = None, timeout_seconds: int | None = None
    ):
        self.timeout_seconds = timeout_seconds
        super().__init__(message, url, scraper_name)


class ScraperConfigurationError(ScraperError):
    """Browser or environment configuration issue."""

    def __init__(self, message: str, config_key: str | None = None):
        self.config_key = config_key
        super().__init__(message, scraper_name='BaseScraper')


class ScraperDownloadError(ScraperError):
    """Failed to download a specific document."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        scraper_name: str | None = None,
        document_index: int | None = None,
        document_id: str | None = None,
    ):
        self.document_index = document_index
        self.document_id = document_id
        super().__init__(message, url, scraper_name)


class ScraperHealthCheckError(ScraperError):
    """Download succeeded but file failed health check."""

    def __init__(self, message: str, file_path: Path, scraper_name: str | None = None):
        self.file_path = file_path
        super().__init__(message, url=None, scraper_name=scraper_name)
