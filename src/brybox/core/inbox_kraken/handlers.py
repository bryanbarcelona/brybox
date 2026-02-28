import re
from email.message import Message
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from brybox.core.inbox_kraken.helpers import classify_link, get_dropbox_download_link, resolve_redirected_url, save_path
from brybox.core.models.email import EmailMeta, ProcessResult
from brybox.events.bus import publish_file_added
from brybox.utils.credentials import WebCredentials
from brybox.utils.logging import log_and_display
from brybox.web_marionette.scrapers import KfwScraper, TechemScraper


def download_pdf_handler(meta: EmailMeta, save_dir: Path) -> ProcessResult:
    """Download PDF from an embedded link (e.g., Google Drive, direct CDN)."""
    if not meta.invoice_link:
        return ProcessResult(
            success=False,
            target_path=None,
            is_healthy=False,
            error_message='No invoice link found.',
        )

    try:
        r = requests.get(meta.invoice_link, timeout=30)
        r.raise_for_status()

        clean_subject = re.sub(r'[^\w\-_\. ]', '_', meta.subject)[:40]
        target_path = save_path(f'{meta.uid}_{clean_subject}.pdf', save_dir)

        target_path.write_bytes(r.content)
        publish_file_added(file_path=str(target_path), file_size=target_path.stat().st_size, is_healthy=True)

        return ProcessResult(
            success=True,
            target_path=target_path,
            is_healthy=True,
            error_message='',
            can_delete=True,
        )
    except Exception as e:
        return ProcessResult(
            success=False,
            target_path=None,
            is_healthy=False,
            error_message=f'PDF link download failed: {e!s}',
        )


def download_attachment_handler(meta: EmailMeta, save_dir: Path, msg: Message) -> ProcessResult:
    """Extract all PDF attachments from the email message."""
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

    return ProcessResult(
        success=any_success,
        target_path=last_saved_path,
        is_healthy=any_success,
        error_message='',
        can_delete=any_success,
    )


def dropbox_audio_handler(meta: EmailMeta, save_dir: Path, msg: Message) -> ProcessResult:
    """Handles confirmed Dropbox audio links by converting and streaming the download."""
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

            log_and_display(f'Downloading Dropbox Audio: {direct_url}')

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

                # Binary stream write
                with target_path.open('wb') as f:
                    for chunk in dl_r.iter_content(chunk_size=8192):
                        f.write(chunk)

                publish_file_added(str(target_path), target_path.stat().st_size, True)
                downloaded_count += 1

        except Exception as e:
            errors.append(f'Link {link} failed: {e!s}')

    success = downloaded_count > 0
    msg_out = f'Downloaded {downloaded_count} files.' + (f' Errors: {errors}' if errors else '')

    return ProcessResult(
        success=success,
        target_path=target_path,
        is_healthy=success,
        error_message=msg_out,
        can_delete=success,
    )


def techem_handler(meta: EmailMeta, save_dir: Path, creds: WebCredentials) -> ProcessResult:
    """Adapter for the Techem Playwright scraper."""
    try:
        scraper = TechemScraper(
            username=creds.techem_user, password=creds.techem_password, download_dir=str(save_dir), headless=False
        )
        result = scraper.download()
        is_ok = bool(result and not result.errors)
        return ProcessResult(
            success=is_ok,
            target_path=None,
            is_healthy=is_ok,
            error_message='',
            can_delete=is_ok,
        )
    except Exception as e:
        return ProcessResult(
            success=False,
            target_path=None,
            is_healthy=False,
            error_message=str(e),
        )


def kfw_handler(meta: EmailMeta, save_dir: Path, creds: WebCredentials) -> ProcessResult:
    """Adapter for the KfW Playwright scraper."""
    try:
        scraper = KfwScraper(
            username=creds.kfw_user, password=creds.kfw_password, download_dir=str(save_dir), headless=True
        )
        result = scraper.download()
        success = bool(result and result.downloaded > 0)
        return ProcessResult(
            success=success,
            target_path=None,
            is_healthy=success,
            error_message='',
            can_delete=success,
        )
    except Exception as e:
        return ProcessResult(
            success=False,
            target_path=None,
            is_healthy=False,
            error_message=str(e),
        )


def manual_click_handler() -> ProcessResult:
    """Placeholder for emails requiring manual action — never deletes."""
    return ProcessResult(
        success=True,
        target_path=None,
        is_healthy=True,
        error_message='Manual click required.',
        can_delete=False,
    )


def ignore_handler() -> ProcessResult:
    """Signals to the engine to skip this email and leave it in the inbox."""
    return ProcessResult(
        success=True,
        target_path=None,
        is_healthy=True,
        error_message='',
        can_delete=False,
    )


def delete_handler() -> ProcessResult:
    """Signals to the engine that this email should be deleted."""
    return ProcessResult(
        success=True,
        target_path=None,
        is_healthy=True,
        error_message='',
        can_delete=True,
    )