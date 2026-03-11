import datetime
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    Request,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from brybox.events.bus import publish_file_added
from brybox.exceptions.scrapers import (
    ScraperAuthenticationError,
    ScraperConfigurationError,
    ScraperDownloadError,
    ScraperError,
    ScraperHealthCheckError,
    ScraperNavigationError,
)
from brybox.utils.health_check import is_pdf_healthy
from brybox.utils.logging import log_and_display
from brybox.web_marionette.models import DownloadResult

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

    def _create_browser_context(self, playwright: Playwright, **context_kwargs: dict) -> tuple[Browser, BrowserContext]:
        """Create and configure browser context with common settings."""
        browser = playwright.chromium.launch(headless=self.headless)
        return browser, browser.new_context(**context_kwargs)

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


class TechemScraper(BaseScraper):
    """Scraper for Techem heating cost invoices."""

    SITE_URL = 'https://mieter.techem.de/'

    def download(self) -> DownloadResult:
        """Download the latest Techem invoice PDF."""
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = Path(self.download_dir) / f'techem_invoice_{timestamp}.pdf'

        try:
            with sync_playwright() as playwright:
                browser, context = self._create_browser_context(
                    playwright,
                    viewport={'width': 1280, 'height': 1024},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/118.0.5993.90 Safari/537.36',
                    device_scale_factor=1,
                )
                page = context.new_page()

                # Navigate to site
                try:
                    page.goto(self.SITE_URL, wait_until='networkidle')
                    log_and_display('Techem page loaded', log=False, sticky=False)
                except PlaywrightTimeoutError as e:
                    raise ScraperNavigationError(
                        'Timeout loading Techem page', url=self.SITE_URL, scraper_name='TechemScraper'
                    ) from e

                # Handle cookie banner (non-critical)
                if not self.headless:
                    self._handle_cookie_banner(page)

                # Login
                try:
                    self._login(page)
                except PlaywrightTimeoutError as e:
                    raise ScraperAuthenticationError(
                        'Login failed - check credentials or site availability',
                        url=self.SITE_URL,
                        scraper_name='TechemScraper',
                    ) from e

                # Download PDF
                try:
                    self._download_pdf(page, output_path)
                except PlaywrightTimeoutError as e:
                    raise ScraperDownloadError(
                        'Timeout waiting for PDF download button', url=self.SITE_URL, scraper_name='TechemScraper'
                    ) from e

                finally:
                    browser.close()

                # Verify PDF health
                if is_pdf_healthy(output_path):
                    file_size = Path(output_path).stat().st_size

                    publish_file_added(file_path=str(output_path), file_size=file_size, is_healthy=True)

                    log_and_display(f'Downloaded: {output_path.name}', log=True, sticky=False)

                    # Success case - all good
                    return DownloadResult(success=True, total_found=1, downloaded=1, failed=0, errors=[])
                else:
                    # PDF failed health check
                    return DownloadResult(
                        success=False, total_found=1, downloaded=0, failed=1, errors=['PDF failed health check']
                    )

        except (ScraperNavigationError, ScraperAuthenticationError, ScraperDownloadError) as e:
            log_and_display(f'Techem: {e}', level='error')
            raise
        except Exception as e:
            raise ScraperError(f'Techem: Unexpected error: {e!s}') from e

    @staticmethod
    def _handle_cookie_banner(page: Page) -> None:
        """Attempt to dismiss cookie banner if present."""
        try:
            cookie_button = page.get_by_role('button', name='Use necessary cookies only')
            cookie_button.wait_for(state='visible', timeout=5000)
            cookie_button.click()
            log_and_display('Cookie banner accepted', log=False, sticky=False)
        except PlaywrightTimeoutError:
            log_and_display('Cookie banner not visible, skipping', log=False, sticky=False)

    def _login(self, page: Page) -> None:
        """Execute login sequence."""
        login_button = page.get_by_role('button', name='Login').first
        login_button.wait_for(state='visible', timeout=10000)
        login_button.click()
        log_and_display('Login button clicked', log=False, sticky=False)

        page.fill('#signInName', self.username)
        page.fill('#password', self.password)
        page.click('#next')

    @staticmethod
    def _download_pdf(page: Page, output_path: Path) -> None:
        """Download the PDF invoice."""
        # Try multiple possible button names
        pdf_button = page.get_by_role('button', name='PDF herunterladen').or_(
            page.get_by_role('button', name='Download')
        )

        pdf_button.wait_for(state='visible', timeout=15000)

        with page.expect_download() as download_info:
            pdf_button.click()

        download = download_info.value
        download.save_as(str(output_path))


class KfwScraper(BaseScraper):
    """Scraper for KFW student loan documents."""

    SITE_URL = 'https://onlinekreditportal.kfw.de/BK_KNPlattform/KfwFormularServer'
    POSTBOX_URL = (
        'https://onlinekreditportal.kfw.de/BK_KNPlattform/KfwFormularServer/BK_KNPlattform/PostkorbEingangBrowseAction'
    )

    # Request capture timeouts
    MAX_CAPTURE_WAIT_MS = 10000
    CAPTURE_POLL_INTERVAL_MS = 100
    MAX_DOWNLOAD_RETRIES = 1

    def download(self) -> DownloadResult:
        """Download all available KFW documents from inbox."""
        try:
            with sync_playwright() as playwright:
                browser, context = self._create_browser_context(playwright, accept_downloads=True)
                page = context.new_page()

                try:
                    return self._execute_download_workflow(page, context)
                finally:
                    browser.close()

        except (ScraperAuthenticationError, ScraperNavigationError, ScraperConfigurationError) as e:
            # Catastrophic errors - re-raise to handler
            log_and_display(f'KFW: Fatal error - {e}', level='error')
            raise
        except Exception as e:
            # Unexpected errors - wrap and re-raise
            raise ScraperError(f'KFW: Unexpected failure: {e}') from e

    def _execute_download_workflow(self, page: Page, context: BrowserContext) -> DownloadResult:
        """Execute the full download workflow."""

        self._login(page)

        self._navigate_to_postbox(page)

        # Get documents
        download_buttons = page.locator("input[type='image'][alt='Dokument anzeigen']").all()
        if len(download_buttons) == 0:
            return DownloadResult(
                success=False,
                total_found=0,
                downloaded=0,
                failed=0,
                errors=[],
            )

        return self._download_all_documents(page, context, download_buttons)

    def _download_all_documents(
        self, page: Page, context: BrowserContext, download_buttons: list[Locator]
    ) -> DownloadResult:
        """Download all documents with retry logic."""
        errors = []
        success_count = 0
        total_documents = len(download_buttons)

        log_and_display(f'Found {total_documents} document(s)', log=False, sticky=False)

        for index, download_button in enumerate(download_buttons, start=1):
            try:
                log_and_display(f'Processing document {index}/{total_documents}', log=False, sticky=False)

                # Try download with retry logic
                success = False
                for attempt in range(self.MAX_DOWNLOAD_RETRIES + 1):
                    # This returns bool, doesn't raise for document failures
                    if self._download_single_document(page, context, download_button, index):
                        success = True
                        break
                    elif attempt < self.MAX_DOWNLOAD_RETRIES:
                        log_and_display(
                            f'Retrying document {index} (attempt {attempt + 2}/{self.MAX_DOWNLOAD_RETRIES + 1})',
                            log=False,
                            sticky=False,
                        )

                if success:
                    success_count += 1
                else:
                    errors.append(f'Document {index}: Failed after {self.MAX_DOWNLOAD_RETRIES + 1} attempts')

            except ScraperError:
                # These should bubble up to the handler
                raise
            except Exception as e:  # noqa: BLE001
                # Unexpected errors in the download process
                error_msg = f'Document {index}: {e!s}'
                log_and_display(error_msg, level='warning', log=True, sticky=False)
                errors.append(error_msg)

        # Determine if ALL documents succeeded
        all_succeeded = success_count == total_documents and total_documents > 0

        if errors:
            log_and_display(
                f'KFW: Downloaded {success_count}/{total_documents} documents, {len(errors)} errors', level='warning'
            )
        else:
            log_and_display(f'KFW: Successfully downloaded all {success_count} documents', level='info')

        return DownloadResult(
            success=all_succeeded,  # To delete or not delete - that is the question
            total_found=total_documents,
            downloaded=success_count,
            failed=len(errors),
            errors=errors,
        )

    def _login(self, page: Page) -> None:
        """Execute KFW login sequence.

        Raises:
            ScraperAuthenticationError: If login fails
        """
        try:
            page.goto(self.SITE_URL)

            page.fill('#BANKING_ID', self.username)
            page.fill('#PIN', self.password)
            page.click("input[name='login'][type='submit']")

            page.wait_for_load_state('networkidle')
        except PlaywrightTimeoutError as e:
            raise ScraperAuthenticationError(
                'Login timeout - site may be slow or down', url=self.SITE_URL, scraper_name='KfwScraper'
            ) from e
        except Exception as e:
            raise ScraperAuthenticationError(f'Login failed: {e}', url=self.SITE_URL, scraper_name='KfwScraper') from e

    def _navigate_to_postbox(self, page: Page) -> None:
        """Navigate to the postbox/inbox page.

        Raises:
            ScraperNavigationError: If navigation fails
        """
        try:
            page.goto(self.POSTBOX_URL)
        except PlaywrightTimeoutError as e:
            raise ScraperNavigationError(
                'Timeout accessing document inbox',
                url=self.POSTBOX_URL,
                scraper_name='KfwScraper',
                expected_element='postbox',
            ) from e

    def _download_single_document(
        self, page: Page, context: BrowserContext, download_button: Locator, doc_index: int
    ) -> bool:
        """
        Download a single document using request interception.
        Returns True if successful, False otherwise.
        """
        try:
            # Get document ID from form
            form = download_button.locator('xpath=ancestor::form[1]')
            dokid = form.locator("input[name='dokid']").get_attribute('value')

            # Capture the POST request
            captured_request = self._capture_download_request(context, download_button, page)

            if not captured_request:
                log_and_display(
                    f'Timeout: no request captured for document {doc_index}', level='warning', log=True, sticky=False
                )
                return False

            # Replay the request to get the PDF
            response = context.request.post(
                captured_request.url, data=captured_request.post_data, headers=captured_request.headers
            )

            if response.status != 200:
                log_and_display(
                    f'Document {doc_index}: HTTP {response.status}', level='warning', log=True, sticky=False
                )
                return False

        except (ScraperDownloadError, ScraperHealthCheckError):
            # These are already handled and logged - just return False
            return False
        except Exception as e:
            # Unexpected errors - log AND re-raise as ScraperError
            log_and_display(f'Document {doc_index}: Unexpected error - {e}', level='warning', log=True, sticky=False)
            raise ScraperError(f'Unexpected error in document {doc_index}: {e}') from e
        else:
            # Save the PDF
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'kfw_document_{doc_index}_{dokid}_{timestamp}.pdf'
            output_path = Path(self.download_dir) / filename

            with Path(output_path).open('wb') as f:
                f.write(response.body())

            file_size = Path(output_path).stat().st_size
            is_healthy = is_pdf_healthy(output_path)

            publish_file_added(file_path=str(output_path), file_size=file_size, is_healthy=is_healthy)

            log_and_display(f'Downloaded: {filename} ({len(response.body())} bytes)', log=True, sticky=False)
            return True

    def _capture_download_request(
        self, context: BrowserContext, download_button: Locator, page: Page
    ) -> Request | None:
        """
        Click button and capture the resulting POST request.
        Returns the captured request or None if timeout.
        """
        captured_request = [None]

        def capture_request(request: Request) -> None:
            if 'KfwFormularServer' in request.url and request.method == 'POST':
                captured_request[0] = request

        context.on('request', capture_request)
        download_button.click()

        # Poll for captured request
        elapsed_ms = 0
        while captured_request[0] is None and elapsed_ms < self.MAX_CAPTURE_WAIT_MS:
            page.wait_for_timeout(self.CAPTURE_POLL_INTERVAL_MS)
            elapsed_ms += self.CAPTURE_POLL_INTERVAL_MS

        context.remove_listener('request', capture_request)
        return captured_request[0]


if __name__ == '__main__':
    pass
