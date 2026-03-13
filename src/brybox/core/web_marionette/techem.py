import datetime
import logging
from pathlib import Path

from playwright.sync_api import (
    Page,
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
from brybox.utils.health_check import is_pdf_healthy
from brybox.utils.logging import log_and_display

logger = logging.getLogger('WebMarionette')


class TechemScraper(BaseScraper):
    """Scraper for Techem heating cost invoices."""

    SITE_URL = 'https://mieter.techem.de/'

    def download(self) -> DownloadResult:
        """Download the latest Techem invoice PDF."""
        try:
            with sync_playwright() as playwright:
                browser, context = self._create_browser_context(
                    playwright,
                    viewport={'width': 1280, 'height': 1024},
                    user_agent=(
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/118.0.5993.90 Safari/537.36'
                    ),
                    device_scale_factor=1,
                )

                page = context.new_page()

                try:
                    return self._execute_download_workflow(page)
                finally:
                    browser.close()

        except (ScraperNavigationError, ScraperAuthenticationError, ScraperDownloadError) as e:
            log_and_display(f'Techem: {e}', level='error')
            raise
        except Exception as e:
            raise ScraperError(f'Techem: Unexpected error: {e!s}') from e

    def _execute_download_workflow(self, page: Page) -> DownloadResult:
        """Execute the full Techem download workflow."""

        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = Path(self.download_dir) / f'techem_invoice_{timestamp}.pdf'

        # Navigate to site
        try:
            page.goto(self.SITE_URL, wait_until='networkidle')
            log_and_display('Techem page loaded', log=False, sticky=False)
        except PlaywrightTimeoutError as e:
            raise ScraperNavigationError(
                'Timeout loading Techem page',
                url=self.SITE_URL,
                scraper_name='TechemScraper',
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
                'Timeout waiting for PDF download button',
                url=self.SITE_URL,
                scraper_name='TechemScraper',
            ) from e

        # Verify PDF health
        if is_pdf_healthy(output_path):
            file_size = Path(output_path).stat().st_size

            publish_file_added(
                file_path=output_path,
                file_size=file_size,
                is_healthy=True,
            )

            log_and_display(f'Downloaded: {output_path.name}', log=True, sticky=False)

            return DownloadResult(
                success=True,
                total_found=1,
                downloaded=1,
                failed=0,
                errors=[],
            )

        return DownloadResult(
            success=False,
            total_found=1,
            downloaded=0,
            failed=1,
            errors=['PDF failed health check'],
        )

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
