import datetime
import re
from pathlib import Path
from typing import ClassVar

import pyotp
from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from brybox.core.models.scrapers import DownloadResult
from brybox.core.web_marionette.base import BaseScraper
from brybox.events.bus import publish_file_added
from brybox.exceptions.scrapers import (
    ScraperAuthenticationError,
    ScraperDownloadError,
    ScraperError,
    ScraperNavigationError,
)
from brybox.utils.logging import log_and_display


class AmazonScraper(BaseScraper):
    """Scraper for Amazon.de order invoices.

    Two modes:
    - Bulk: iterates all years from current back to start_year, downloads every invoice.
    - Targeted: downloads invoices for specific order IDs (InboxKraken production mode).

    Authentication uses TOTP + session persistence. First run executes a full login + TOTP
    flow and saves the session to disk; subsequent runs reuse the cached session (~30 days
    when 'remember device' is checked at login).

    Note: PDF rendering requires headless Chromium. Downloads always run headless regardless
    of the headless constructor argument; that setting only affects the login phase.
    """

    LOGIN_URL: ClassVar[str] = 'https://www.amazon.de/ap/signin'
    ACCOUNT_HOME_URL: ClassVar[str] = 'https://www.amazon.de/gp/css/homepage.html'
    ORDER_HISTORY_URL: ClassVar[str] = 'https://www.amazon.de/gp/your-account/order-history'
    INVOICE_PRINT_URL: ClassVar[str] = 'https://www.amazon.de/gps/css/summary/print.html?orderID={order_id}'
    DEFAULT_SESSION_FILE: ClassVar[Path] = Path.home() / '.brybox' / 'sessions' / 'amazon_state.json'
    ORDER_ID_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r'[A-Z0-9]{3}-[0-9]{7}-[0-9]{7}')

    def __init__(
        self,
        username: str,
        password: str,
        totp_secret: str,
        download_dir: str | None = None,
        *,
        headless: bool = True,
        session_file: str | None = None,
        order_ids: list[str] | None = None,
        start_year: int = 2010,
    ) -> None:
        super().__init__(username=username, password=password, download_dir=download_dir, headless=headless)
        self.totp_secret = totp_secret
        self._session_path = Path(session_file) if session_file else self.DEFAULT_SESSION_FILE
        self.order_ids = order_ids
        self.start_year = start_year

    def download(self) -> DownloadResult:
        """Download Amazon.de invoices in bulk or targeted mode."""
        try:
            with sync_playwright() as playwright:
                return self._run(playwright)
        except (ScraperAuthenticationError, ScraperNavigationError) as e:
            log_and_display(f'Amazon: Fatal error — {e}', level='error')
            raise
        except Exception as e:
            raise ScraperError(f'Amazon: Unexpected failure: {e}') from e

    # ------------------------------------------------------------------ #
    # Session management
    # ------------------------------------------------------------------ #

    def _run(self, playwright: Playwright) -> DownloadResult:
        """Ensure auth, open a headless download context, dispatch to the active mode."""
        self._ensure_session(playwright)
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(self._session_path))
        page = context.new_page()
        try:
            if self.order_ids is not None:
                return self._fetch_by_ids(page, context)
            return self._fetch_all_years(page, context)
        finally:
            browser.close()

    def _ensure_session(self, playwright: Playwright) -> None:
        """Use the cached session if it's still valid; otherwise authenticate fresh."""
        if self._session_path.exists():
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(self._session_path))
            page = context.new_page()
            still_valid = self._is_authenticated(page)
            browser.close()
            if still_valid:
                log_and_display('Amazon: Loaded cached session', log=False, sticky=False)
                return
            log_and_display('Amazon: Cached session expired, re-authenticating', log=True, sticky=False)

        self._authenticate(playwright)

    def _authenticate(self, playwright: Playwright) -> None:
        """Execute the full login + TOTP flow and persist session state to disk."""
        browser = playwright.chromium.launch(headless=self.headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            self._login(page)
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(self._session_path))
            log_and_display('Amazon: Authenticated and session saved', log=True, sticky=False)
        finally:
            browser.close()

    def _is_authenticated(self, page: Page) -> bool:
        """Return True if navigating to the account home does not redirect to signin."""
        try:
            page.goto(self.ACCOUNT_HOME_URL, wait_until='domcontentloaded', timeout=15000)
        except Exception:  # ruff: ignore[blind-except]
            return False
        else:
            return 'signin' not in page.url

    # ------------------------------------------------------------------ #
    # Login
    # ------------------------------------------------------------------ #

    def _login(self, page: Page) -> None:
        """Email → password → optional TOTP (with 'remember device') → post-auth confirm."""
        try:
            self._enter_credentials(page)
            self._handle_totp(page)
            page.wait_for_url(re.compile(r'amazon\.de(?!/ap/)'), timeout=15000)
        except PlaywrightTimeoutError as e:
            raise ScraperAuthenticationError(
                'Login timeout — verify credentials and TOTP secret',
                url=self.LOGIN_URL,
                scraper_name='AmazonScraper',
            ) from e
        except ScraperAuthenticationError:
            raise
        except Exception as e:
            raise ScraperAuthenticationError(
                f'Login failed: {e}',
                url=self.LOGIN_URL,
                scraper_name='AmazonScraper',
            ) from e

    def _enter_credentials(self, page: Page) -> None:
        """Navigate to the login page and submit email + password."""
        page.goto(self.LOGIN_URL, wait_until='domcontentloaded')
        page.fill('#ap_email', self.username)
        page.click('#continue')
        page.wait_for_selector('#ap_password', state='visible', timeout=10000)
        page.fill('#ap_password', self.password)
        page.click('#signInSubmit')

    def _handle_totp(self, page: Page) -> None:
        """Fill the TOTP challenge if one appears; silently skips if the device is trusted."""
        try:
            page.wait_for_selector('input[name="otpCode"]', state='visible', timeout=8000)
            page.fill('input[name="otpCode"]', pyotp.TOTP(self.totp_secret).now())
            self._tick_remember_device(page)
            page.click('#auth-signin-button')
        except PlaywrightTimeoutError:
            pass  # no 2FA challenge: device already trusted or skipped

    @staticmethod
    def _tick_remember_device(page: Page) -> None:
        """Check 'remember this device' if the checkbox is present."""
        remember = page.locator('input[name="rememberDevice"]')
        if remember.count() > 0 and remember.is_visible():
            remember.check()

    # ------------------------------------------------------------------ #
    # Download orchestration
    # ------------------------------------------------------------------ #

    def _fetch_all_years(self, page: Page, context: BrowserContext) -> DownloadResult:
        """Iterate from current year back to start_year, downloading all invoices."""
        total_found = 0
        total_downloaded = 0
        all_errors: list[str] = []

        for year in range(datetime.date.today().year, self.start_year - 1, -1):
            found, downloaded, errors = self._scrape_year(page, context, year)
            total_found += found
            total_downloaded += downloaded
            all_errors.extend(errors)
            log_and_display(f'Amazon: {year} — {downloaded}/{found} invoices downloaded', log=True, sticky=False)

        return self._build_result(total_found=total_found, downloaded=total_downloaded, errors=all_errors)

    def _fetch_by_ids(self, page: Page, context: BrowserContext) -> DownloadResult:  # ruff: ignore[unused-method-argument]
        """Download invoices for a specific list of order IDs (targeted/InboxKraken mode)."""
        assert self.order_ids is not None  # guaranteed by _run()
        errors: list[str] = []
        downloaded = 0

        for order_id in self.order_ids:
            if self._download_invoice(page, order_id):
                downloaded += 1
            else:
                errors.append(f'Order {order_id}: invoice unavailable or download failed')

        return self._build_result(total_found=len(self.order_ids), downloaded=downloaded, errors=errors)

    def _scrape_year(
        self,
        page: Page,
        context: BrowserContext,  # ruff: ignore[unused-method-argument]
        year: int,
    ) -> tuple[int, int, list[str]]:
        """Paginate through all orders for a given year and download each invoice."""
        order_ids: list[str] = []
        offset = 0

        while True:
            url = f'{self.ORDER_HISTORY_URL}?orderFilter=year-{year}&startIndex={offset}'
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_selector('.order, #ordersContainer, .a-box-group', state='visible', timeout=10000)
            except PlaywrightTimeoutError:
                break

            new_ids = self._collect_order_ids_from_page(page, order_ids)
            order_ids.extend(new_ids)

            if not new_ids:
                break  # empty page or all IDs already seen — no more orders this year

            next_btn = page.locator('ul.a-pagination li.a-last:not(.a-disabled) a')
            if next_btn.count() == 0 or not next_btn.is_visible():
                break
            offset += 10

        if not order_ids:
            return 0, 0, []

        errors: list[str] = []
        downloaded = 0
        for order_id in order_ids:
            if self._download_invoice(page, order_id):
                downloaded += 1
            else:
                errors.append(f'Order {order_id}: invoice unavailable')

        return len(order_ids), downloaded, errors

    def _collect_order_ids_from_page(self, page: Page, known_ids: list[str]) -> list[str]:
        """Return new order IDs found on the current page, excluding already-seen ones."""
        hrefs: list[str] = page.eval_on_selector_all('a[href*="orderID="]', 'els => els.map(el => el.href)')
        new_ids: list[str] = []
        for href in hrefs:
            match = self.ORDER_ID_PATTERN.search(href)
            if match:
                oid = match.group()
                if oid not in known_ids and oid not in new_ids:
                    new_ids.append(oid)
        return new_ids

    # ------------------------------------------------------------------ #
    # Invoice download
    # ------------------------------------------------------------------ #

    def _download_invoice(self, page: Page, order_id: str) -> bool:
        """Render the Amazon.de print invoice page to PDF and write to download_dir."""
        invoice_url = self.INVOICE_PRINT_URL.format(order_id=order_id)
        default_path = (
            Path(self.download_dir) / f'amazon_invoice_{order_id}_{datetime.date.today().strftime("%Y-%m-%d")}.pdf'
        )

        try:
            output_path = self._navigate_invoice_page(page, order_id, invoice_url, default_path)
            body = self._render_invoice_to_pdf(page, output_path)
        except ScraperNavigationError as e:
            log_and_display(str(e), level='warning', log=True, sticky=False)
            return False
        except ScraperDownloadError as e:
            log_and_display(str(e), level='warning', log=True, sticky=False)
            return False
        except PlaywrightTimeoutError:
            log_and_display(f'Order {order_id}: timeout loading invoice page', level='warning', log=True, sticky=False)
            return False
        except Exception as e:  # ruff: ignore[blind-except]
            log_and_display(f'Order {order_id}: unexpected error — {e}', level='warning', log=True, sticky=False)
            return False

        publish_file_added(file_path=output_path, file_size=output_path.stat().st_size, is_healthy=True)
        log_and_display(f'Downloaded: {output_path.name} ({len(body)} bytes)', log=True, sticky=False)
        return True

    def _navigate_invoice_page(self, page: Page, order_id: str, invoice_url: str, default_path: Path) -> Path:
        """Navigate to the invoice print URL and return the resolved output path.

        Raises:
            ScraperNavigationError: If session became invalid mid-run.
            ScraperDownloadError: If the order has no accessible invoice.
        """
        page.goto(invoice_url, wait_until='domcontentloaded', timeout=20000)

        if 'signin' in page.url:
            raise ScraperNavigationError(
                f'Order {order_id}: session invalid mid-run',
                url=invoice_url,
                scraper_name='AmazonScraper',
            )
        if 'homepage' in page.url or 'your-account' in page.url:
            raise ScraperDownloadError(
                f'Order {order_id}: no invoice accessible (redirected away)',
                url=invoice_url,
                scraper_name='AmazonScraper',
                document_id=order_id,
            )

        extracted_date = self._extract_order_date(page)
        if extracted_date:
            return default_path.parent / f'amazon_invoice_{order_id}_{extracted_date}.pdf'
        return default_path

    @staticmethod
    def _render_invoice_to_pdf(page: Page, output_path: Path) -> bytes:
        """Render the current page as a print-formatted PDF and validate the output.

        Raises:
            ScraperDownloadError: If the rendered file is not a valid PDF.
        """
        page.emulate_media(media='print')
        page.pdf(path=str(output_path), format='A4', print_background=True)

        body = output_path.read_bytes()
        if not body.startswith(b'%PDF'):
            output_path.unlink(missing_ok=True)
            raise ScraperDownloadError(
                f'Rendered invoice is not a valid PDF: {output_path.name}',
                scraper_name='AmazonScraper',
            )
        return body

    @staticmethod
    def _extract_order_date(page: Page) -> str | None:
        """Extract order date from the invoice print page; returns ISO date string or None."""
        try:
            text = page.inner_text('body')
            match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
            if match:
                day, month, year_str = match.group(1), match.group(2), match.group(3)
                return f'{year_str}-{month.zfill(2)}-{day.zfill(2)}'
        except Exception:  # ruff: ignore[blind-except, try-except-pass]
            pass
        return None
