import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from brybox.core.inbox_kraken.helpers import classify_link, get_dropbox_download_link, resolve_redirected_url, save_path
from brybox.core.models.email import ProcessingContext, ProcessResult
from brybox.events.bus import publish_file_added
from brybox.exceptions import ScraperError
from brybox.exceptions.emails import (
    InboxKrakenError,
    InboxKrakenFileOperationError,
    InboxKrakenOperationFailedError,
    InboxKrakenResourceNotFoundError,
    InboxKrakenTimeoutError,
)
from brybox.utils.logging import log_and_display
from brybox.web_marionette.scrapers import KfwScraper, TechemScraper


def download_pdf_handler(ctx: ProcessingContext) -> ProcessResult:
    meta = ctx.meta

    if not meta.invoice_link:
        raise InboxKrakenResourceNotFoundError(f'UID {meta.uid}: Invoice link missing from metadata.')

    try:
        # helpers.save_path now raises InboxKrakenConfigurationError if save_dir is bad
        clean_subject = re.sub(r'[^\w\-_ \.]', '_', meta.subject)[:40]
        target_path = save_path(f'{meta.uid}_{clean_subject}.pdf', ctx.save_dir)

        r = requests.get(meta.invoice_link, timeout=30)
        r.raise_for_status()

        target_path.write_bytes(r.content)
        publish_file_added(file_path=str(target_path), file_size=target_path.stat().st_size, is_healthy=True)

        return ProcessResult(success=True, target_path=target_path, is_healthy=True, can_delete=True)

    except requests.Timeout as e:
        raise InboxKrakenTimeoutError('PDF download timed out', resource_path=meta.invoice_link) from e
    except requests.RequestException as e:
        raise InboxKrakenOperationFailedError(
            'PDF download failed', resource_path=meta.invoice_link, error_detail=str(e)
        ) from e
    except OSError as e:
        raise InboxKrakenFileOperationError('Disk write failed', dest_path=target_path) from e


def download_attachment_handler(ctx: ProcessingContext) -> ProcessResult:
    if ctx.msg is None:
        return ProcessResult(
            success=False,
            target_path=None,
            is_healthy=False,
            error_message='No email message available for attachment extraction',
        )

    meta = ctx.meta
    save_dir = ctx.save_dir
    msg = ctx.msg

    last_saved_path = None
    any_success = False

    for part in msg.walk():
        name = part.get_filename()
        if name and name.lower().endswith('.pdf') and part.get_content_disposition() == 'attachment':
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            target_path = save_path(f'{meta.uid}_{name}', save_dir)
            target_path.write_bytes(payload)

            publish_file_added(file_path=str(target_path), file_size=target_path.stat().st_size, is_healthy=True)
            last_saved_path = target_path
            any_success = True

    if not any_success:
        raise InboxKrakenResourceNotFoundError(f'UID {meta.uid}: No PDF attachments found.')

    return ProcessResult(
        success=True,
        target_path=last_saved_path,
        is_healthy=True,
        can_delete=True,
    )


def dropbox_audio_handler(ctx: ProcessingContext) -> ProcessResult:

    meta = ctx.meta
    save_dir = ctx.save_dir

    soup = BeautifulSoup(meta.body_html, 'html.parser')
    links = [a['href'] for a in soup.find_all('a', href=True) if a['href'].startswith('http')]

    downloaded_count = 0
    errors = []
    target_path = None  # Safe default — avoids NameError if no AUDIO links are found

    for link in links:
        if classify_link(link) != 'AUDIO':
            continue

        try:
            resolved_url = resolve_redirected_url(link)
            direct_url = get_dropbox_download_link(resolved_url)

            with requests.get(direct_url, stream=True, timeout=30) as dl_r:
                dl_r.raise_for_status()

                # Filename extraction (Headers -> Path -> Default)
                disp = dl_r.headers.get('content-disposition', '')
                fname_match = re.findall(r'filename="(.+)"', disp)
                filename = fname_match[0] if fname_match else Path(urlparse(dl_r.url).path).name

                if not filename or filename == 'dl=1':
                    filename = f'audio_{meta.uid}_{downloaded_count}.mp3'

                target_path = save_dir / filename

                # Deduplication
                if target_path.exists():
                    downloaded_count += 1
                    continue

                log_and_display(f'Downloading Dropbox Audio: {filename}')

                # Binary stream write
                with target_path.open('wb') as f:
                    for chunk in dl_r.iter_content(chunk_size=8192):
                        f.write(chunk)

                publish_file_added(str(target_path), target_path.stat().st_size, is_healthy=True)
                downloaded_count += 1

        except (requests.RequestException, InboxKrakenError) as e:
            errors.append(f'Link {link} failed: {e!s}')

    success = downloaded_count > 0
    msg_out = f'Downloaded {downloaded_count} files.' + (f' Errors: {errors}' if errors else '')

    if success:
        return ProcessResult(
            success=success,
            target_path=target_path,
            is_healthy=success,
            error_message=msg_out,
            can_delete=success,
        )

    if errors:
        raise InboxKrakenOperationFailedError(f'UID {meta.uid} audio failure', error_detail=msg_out)

    raise InboxKrakenResourceNotFoundError(f'UID {meta.uid} no audio links found')


def techem_handler(ctx: ProcessingContext) -> ProcessResult:
    creds = ctx.creds
    if creds is None or not creds.techem_user or not creds.techem_password:
        raise InboxKrakenOperationFailedError('Missing Techem credentials')

    try:
        scraper = TechemScraper(
            username=creds.techem_user, password=creds.techem_password, download_dir=str(ctx.save_dir), headless=False
        )
        result = scraper.download()

        if not result or result.errors:
            raise InboxKrakenOperationFailedError(
                f'Techem Scraper finished with errors: {result.errors if result else "No result"}'
            )

        return ProcessResult(success=True, target_path=None, is_healthy=True, can_delete=True)

    except ScraperError as e:
        raise InboxKrakenOperationFailedError(f'Techem Scraper failed: {e!s}') from e


def kfw_handler(ctx: ProcessingContext) -> ProcessResult:
    creds = ctx.creds
    if creds is None or not creds.techem_user or not creds.techem_password:
        raise InboxKrakenOperationFailedError('Missing KfW credentials')

    try:
        scraper = KfwScraper(
            username=creds.kfw_user, password=creds.kfw_password, download_dir=str(ctx.save_dir), headless=True
        )
        result = scraper.download()

        if not result or result.downloaded == 0:
            raise InboxKrakenOperationFailedError('KfW Scraper finished but no files were downloaded.')

        return ProcessResult(success=True, target_path=None, is_healthy=True, can_delete=True)

    except ScraperError as e:
        raise InboxKrakenOperationFailedError(f'KfW Scraper failed: {e!s}') from e


def manual_click_handler(_ctx: ProcessingContext) -> ProcessResult:
    """Placeholder for emails requiring manual action — never deletes."""
    return ProcessResult(
        success=True,
        target_path=None,
        is_healthy=True,
        error_message='Manual click required.',
        can_delete=False,
    )


def ignore_handler(_ctx: ProcessingContext) -> ProcessResult:
    """Signals to the engine to skip this email and leave it in the inbox."""
    return ProcessResult(
        success=True,
        target_path=None,
        is_healthy=True,
        error_message='',
        can_delete=False,
    )


def delete_handler(_ctx: ProcessingContext) -> ProcessResult:
    """Signals to the engine that this email should be deleted."""
    return ProcessResult(
        success=True,
        target_path=None,
        is_healthy=True,
        error_message='',
        can_delete=True,
    )
