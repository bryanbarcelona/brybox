import datetime
import logging
from pathlib import Path

from playwright.sync_api import (
    BrowserContext,
    Locator,
    Page,
    Request,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from brybox.core.models.scrapers import DownloadResult
from brybox.core.web_marionette.base import BaseScraper
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

logger = logging.getLogger('WebMarionette')


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

            publish_file_added(file_path=output_path, file_size=file_size, is_healthy=is_healthy)

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
