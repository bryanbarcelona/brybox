"""Standalone script to bulk-download all Amazon.de invoices.

Usage:
    uv run amazon_bulk.py
    uv run amazon_bulk.py --start-year 2015
    uv run amazon_bulk.py --start-year 2020 --output-dir ~/Downloads/amazon_invoices

Run with headless=False on the first execution to observe the login + TOTP flow.
Once a session file is saved (~/.brybox/sessions/amazon_state.json), subsequent
runs skip the login entirely until the session expires (~30 days).
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from brybox.core.web_marionette.amazon import AmazonScraper
from brybox.utils.logging import log_and_display


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Bulk-download all Amazon.de order invoices to PDF.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--start-year',
        type=int,
        default=2010,
        help='Earliest year to fetch (inclusive). Iterates from current year back to this value.',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path.home() / 'Downloads' / 'amazon_invoices',
        help='Directory where invoice PDFs are saved.',
    )
    parser.add_argument(
        '--headless',
        action=argparse.BooleanOptionalAction,
        default=False,
        help='Run the login phase headless. Disable (default) to observe the browser on first run.',
    )
    return parser.parse_args()


def main() -> None:
    """Run the Amazon.de bulk invoice downloader."""
    load_dotenv()
    args = _parse_args()

    amazon_user = os.getenv('USER_AMAZON')
    amazon_password = os.getenv('AMAZON_PWD')
    amazon_totp_secret = os.getenv('AMAZON_TOTP_SECRET')

    if not amazon_user or not amazon_password or not amazon_totp_secret:
        log_and_display(
            'Missing required env vars: USER_AMAZON, AMAZON_PWD, AMAZON_TOTP_SECRET',
            level='error',
        )
        return

    args.output_dir.mkdir(parents=True, exist_ok=True)

    scraper = AmazonScraper(
        username=amazon_user,
        password=amazon_password,
        totp_secret=amazon_totp_secret,
        download_dir=str(args.output_dir),
        headless=args.headless,
        start_year=args.start_year,
    )

    log_and_display(f'Starting Amazon bulk download → {args.output_dir}')
    result = scraper.download()

    if result.success:
        log_and_display(f'Complete: {result.downloaded}/{result.total_found} invoices downloaded')
    else:
        log_and_display(
            f'Finished with issues: {result.downloaded}/{result.total_found} downloaded, {result.failed} failed',
            level='warning',
        )
        for error in result.errors:
            log_and_display(f'  — {error}', level='warning')


if __name__ == '__main__':
    main()
