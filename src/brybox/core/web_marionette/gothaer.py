import datetime
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, unquote, urlparse

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
    ScraperError,
    ScraperNavigationError,
)
from brybox.utils.health_check import is_pdf_healthy
from brybox.utils.logging import log_and_display


class GothaerScraper(BaseScraper):
    """Scraper for Gothaer insurance documents."""

    LOGIN_PAGE: ClassVar[str] = 'https://www.gothaer.de/meine-gothaer/portal.htm'
    POSTBOX_URL: ClassVar[str] = 'https://www.gothaer.de/meine-gothaer/portal.htm#/webMailer'
    MAX_CAPTURE_WAIT_MS: ClassVar[int] = 15000
    CAPTURE_POLL_INTERVAL_MS: ClassVar[int] = 100

    DOWNLOAD_SELECTORS: ClassVar[list[str]] = [
        'span.anchor__text:has-text(".pdf")',
        'a:has-text(".pdf")',
        'span.anchor__icon',
        'button:has-text("Download")',
        'a[href*="download"]',
        'a[href$=".pdf"]',
    ]

    def download(self) -> DownloadResult:
        """Download all available Gothaer documents from inbox."""
        try:
            with sync_playwright() as playwright:
                browser, context = self._create_browser_context(playwright, accept_downloads=True)
                page = context.new_page()

                try:
                    return self._execute_download_workflow(page, context)
                finally:
                    browser.close()

        except (ScraperAuthenticationError, ScraperNavigationError) as e:
            log_and_display(f'Gothaer: Fatal error - {e}', level='error')
            raise
        except Exception as e:
            raise ScraperError(f'Gothaer: Unexpected failure: {e}') from e

    def _execute_download_workflow(self, page: Page, context: BrowserContext) -> DownloadResult:
        """Execute the full download workflow."""
        self._login(page)
        self._navigate_to_inbox(page)

        # Count items once - just the count, not live locator references.
        # We re-query by index each iteration to avoid stale locators after
        # the mask open/close cycle.
        total = page.locator('.webmailer__inboxItem').count()
        if total == 0:
            return DownloadResult(
                success=False,
                total_found=0,
                downloaded=0,
                failed=0,
                errors=[],
            )

        return self._download_all_documents(page, context, total)

    def _login(self, page: Page) -> None:
        """Execute Gothaer login sequence.

        Raises:
            ScraperAuthenticationError: If login fails.
        """
        try:
            page.goto(self.LOGIN_PAGE)
            self._handle_cookie_consent(page)

            page.fill('#v-username', self.username)
            page.fill('#v-password', self.password)
            page.click('#login button:has-text("Anmelden")')

            page.wait_for_selector(
                'span.anchor__text:has-text("Zum Postfach")',
                state='visible',
                timeout=10000,
            )
        except PlaywrightTimeoutError as e:
            raise ScraperAuthenticationError(
                'Login timeout - site may be slow or credentials invalid',
                url=self.LOGIN_PAGE,
                scraper_name='GothaerScraper',
            ) from e
        except Exception as e:
            raise ScraperAuthenticationError(
                f'Login failed: {e}',
                url=self.LOGIN_PAGE,
                scraper_name='GothaerScraper',
            ) from e

    def _navigate_to_inbox(self, page: Page) -> None:
        """Navigate to the document inbox.

        Raises:
            ScraperNavigationError: If navigation or inbox load fails.
        """
        try:
            self._handle_cookie_consent(page)
            page.goto(self.POSTBOX_URL)
            page.wait_for_selector('.webmailer__list', state='visible', timeout=10000)
        except PlaywrightTimeoutError as e:
            raise ScraperNavigationError(
                'Timeout loading document inbox',
                url=self.POSTBOX_URL,
                scraper_name='GothaerScraper',
                expected_element='.webmailer__list',
            ) from e

    def _download_all_documents(self, page: Page, context: BrowserContext, total: int) -> DownloadResult:
        """Iterate inbox items and download any PDFs found."""
        errors = []
        success_count = 0

        log_and_display(f'Found {total} inbox item(s)', log=False, sticky=False)

        for index in range(total):
            log_and_display(f'Processing item {index + 1}/{total}', log=False, sticky=False)
            try:
                if self._process_inbox_item(page, context, index):
                    success_count += 1
                else:
                    errors.append(f'Item {index + 1}: no PDF downloaded')
            except ScraperError:
                raise
            except Exception as e:  # noqa: BLE001
                error_msg = f'Item {index + 1}: {e!s}'
                log_and_display(error_msg, level='warning', log=True, sticky=False)
                errors.append(error_msg)

            # Return to inbox after each item - outside try/except so a navigation
            # failure here is visible, but we still attempt the next item.
            self._return_to_inbox(page)

        if errors:
            log_and_display(
                f'Gothaer: Downloaded {success_count}/{total} documents, {len(errors)} errors',
                level='warning',
            )
        else:
            log_and_display(f'Gothaer: Successfully downloaded all {success_count} documents', level='info')

        return self._build_result(total_found=total, downloaded=success_count, errors=errors)

    def _process_inbox_item(self, page: Page, context: BrowserContext, index: int) -> bool:
        """
        Open a single inbox item, find its download element, capture the PDF URL
        from the GA ping, and fetch the file.
        Returns True if a PDF was successfully saved.

        Note: re-queries the inbox item locator fresh each call - the mask open/close
        cycle can detach previously resolved locator references.
        """
        # Fresh locator query every time - never hold onto .all() references across iterations
        item = page.locator('.webmailer__inboxItem').nth(index)
        item.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        item.click()

        # The item opens as a mask/overlay on top of the inbox (same URL).
        # wait_for_load_state('networkidle') can be flaky for JS-driven overlays,
        # so we wait for the download element to appear instead.
        download_elem = self._find_download_element(page)
        if not download_elem:
            log_and_display(f'Item {index + 1}: no download element found', level='warning', log=True, sticky=False)
            return False

        pdf_url = self._capture_pdf_url(context, download_elem, page)
        if not pdf_url:
            log_and_display(f'Item {index + 1}: no PDF URL captured', level='warning', log=True, sticky=False)
            return False

        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'gothaer_document_{index + 1}_{timestamp}.pdf'
        output_path = Path(self.download_dir) / filename

        return self._fetch_and_save(context, pdf_url, output_path, index + 1)

    def _find_download_element(self, page: Page) -> Locator | None:
        """
        Wait briefly for the overlay to settle, then return the first visible
        download element, or None if nothing appears.
        """
        # Give the overlay a moment to render before scanning for download elements
        page.wait_for_timeout(800)

        for selector in self.DOWNLOAD_SELECTORS:
            elems = page.locator(selector)
            for j in range(elems.count()):
                candidate = elems.nth(j)
                if candidate.is_visible():
                    log_and_display(f'Download element found via: {selector}', log=False, sticky=False)
                    return candidate
        return None

    def _capture_pdf_url(self, context: BrowserContext, download_elem: Locator, page: Page) -> str | None:
        """
        Click the download element and extract the real PDF URL from the Google
        Analytics ping Gothaer fires on click. The ping goes to tsrvce.gothaer.de
        and carries the actual download URL as the `ep.link_url` query parameter.
        Returns the decoded URL or None if it does not arrive within the timeout.
        """
        captured_pdf_url = [None]

        def on_request(request: Request) -> None:
            if captured_pdf_url[0] is not None:
                return
            if 'tsrvce.gothaer.de' not in request.url:
                return
            params = parse_qs(urlparse(request.url).query)
            link_url = params.get('ep.link_url', [None])[0]
            if link_url and '/app/webmailerdata/download/' in link_url:
                captured_pdf_url[0] = unquote(link_url)

        context.on('request', on_request)
        download_elem.click()

        elapsed_ms = 0
        while captured_pdf_url[0] is None and elapsed_ms < self.MAX_CAPTURE_WAIT_MS:
            page.wait_for_timeout(self.CAPTURE_POLL_INTERVAL_MS)
            elapsed_ms += self.CAPTURE_POLL_INTERVAL_MS

        context.remove_listener('request', on_request)
        return captured_pdf_url[0]

    @staticmethod
    def _fetch_and_save(context: BrowserContext, pdf_url: str, output_path: Path, doc_index: int) -> bool:
        """Fetch the PDF from the captured URL and write it to disk."""
        response = context.request.get(pdf_url)

        if response.status != 200:
            log_and_display(f'Document {doc_index}: HTTP {response.status}', level='warning', log=True, sticky=False)
            return False

        body = response.body()

        if not body.startswith(b'%PDF'):
            log_and_display(
                f'Document {doc_index}: response is not a PDF ({len(body)} bytes)',
                level='warning',
                log=True,
                sticky=False,
            )
            return False

        output_path.write_bytes(body)

        file_size = output_path.stat().st_size
        is_healthy = is_pdf_healthy(output_path)
        publish_file_added(file_path=output_path, file_size=file_size, is_healthy=is_healthy)

        log_and_display(f'Downloaded: {output_path.name} ({len(body)} bytes)', log=True, sticky=False)
        return True

    def _return_to_inbox(self, page: Page) -> None:
        """
        Navigate back to the inbox list after processing an item.
        The inbox and message view share the same URL (mask/overlay pattern),
        so page.goto(POSTBOX_URL) is not reliable here - we must use the back button.
        Falls back to goto only if the button genuinely isn't present.
        """
        try:
            back_btn = page.locator('button:has-text("Eingang")').first
            if back_btn.count() > 0 and back_btn.is_visible(timeout=2000):
                back_btn.click()
            else:
                page.goto(self.POSTBOX_URL)

            page.wait_for_selector('.webmailer__list', state='visible', timeout=10000)
        except Exception:  # noqa: BLE001
            # Best-effort recovery - if we can't get back to the list the next
            # iteration will fail and be recorded as an error
            try:
                page.goto(self.POSTBOX_URL)
                page.wait_for_selector('.webmailer__list', state='visible', timeout=10000)
            except Exception:  # noqa: BLE001, S110
                pass

    @staticmethod
    def _handle_cookie_consent(page: Page) -> None:
        """Dismiss cookie consent popup if present (non-critical)."""
        try:
            cookie_selectors = [
                '#cmpbntyestxt',
                'span:has-text("Alle akzeptieren")',
                'button:has-text("Alle akzeptieren")',
                'a:has-text("Alle akzeptieren")',
            ]
            for selector in cookie_selectors:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(1000)
                    return
        except Exception:  # noqa: BLE001,S110
            pass
