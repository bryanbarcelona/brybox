import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

from brybox.core.inbox_kraken.helpers import (
    classify_link,
    resolve_redirected_url,
)
from brybox.core.models.email import EmailMeta, ProcessingContext, ProcessResult
from brybox.events.bus import publish_file_added
from brybox.exceptions.emails import (
    InboxKrakenError,
    InboxKrakenOperationFailedError,
    InboxKrakenResourceNotFoundError,
)
from brybox.utils.logging import log_and_display
from brybox.utils.specialized_tools import filter_audio_links


def _get_dropbox_download_link(url: str) -> str:
    """Converts a Dropbox share link (viewing page) to a direct download stream."""
    if 'dropbox.com' not in url.lower():
        return url

    # Force the dl=1 parameter
    direct_url = url.replace('dl=0', 'dl=1')
    if '?dl=1' not in direct_url:
        direct_url += '&dl=1' if '?' in direct_url else '?dl=1'
    return direct_url


def _download_single(
    link: str,
    index: int,
    meta: EmailMeta,
    save_dir: Path,
) -> tuple[Path | None, str | None]:
    """Download a single Dropbox audio link. Returns (path, error)."""
    try:
        resolved_url = resolve_redirected_url(link)
        direct_url = _get_dropbox_download_link(resolved_url)

        with requests.get(direct_url, stream=True, timeout=30) as dl_r:
            dl_r.raise_for_status()

            disp = dl_r.headers.get('content-disposition', '')
            fname_match = re.findall(r'filename="(.+)"', disp)

            filename = fname_match[0] if fname_match else Path(urlparse(dl_r.url).path).name

            if not filename or filename == 'dl=1':
                filename = f'audio_{meta.uid}_{index}.mp3'

            path = save_dir / filename

            if path.exists():
                return path, None

            log_and_display(f'Downloading Dropbox Audio: {filename}')

            with path.open('wb') as f:
                for chunk in dl_r.iter_content(chunk_size=8192):
                    f.write(chunk)

            publish_file_added(path, path.stat().st_size, is_healthy=True)
            return path, None

    except (requests.RequestException, InboxKrakenError) as e:
        return None, f'Link {link} failed: {e!s}'


def _collect_download_results(
    futures: dict,
    errors: list[str],
) -> tuple[int, Path | None]:
    """Process completed download futures. Returns (downloaded_count, last_path)."""
    downloaded_count = 0
    target_path = None

    for future in as_completed(futures):
        try:
            path, error = future.result()
        except (requests.RequestException, InboxKrakenError) as e:
            errors.append(str(e))
            continue

        if error:
            errors.append(error)
        else:
            downloaded_count += 1
            if path:
                target_path = path

    return downloaded_count, target_path


def dropbox_audio_handler(ctx: ProcessingContext) -> ProcessResult:
    meta: EmailMeta = ctx.meta
    save_dir: Path = ctx.save_dir

    links = filter_audio_links(meta)
    errors: list[str] = []
    audio_links: list[str] = []

    for link in links:
        try:
            if classify_link(link) == 'AUDIO':
                audio_links.append(link)
        except (requests.RequestException, InboxKrakenError) as e:
            errors.append(f'Link {link} failed classification: {e!s}')

    if not audio_links:
        if errors:
            raise InboxKrakenOperationFailedError(f'UID {meta.uid} audio failure', error_detail=str(errors))
        raise InboxKrakenResourceNotFoundError(f'UID {meta.uid} no audio links found')

    with ThreadPoolExecutor(max_workers=min(len(audio_links), 5)) as executor:
        futures = {
            executor.submit(_download_single, link, i, meta, save_dir): link for i, link in enumerate(audio_links)
        }
        downloaded_count, target_path = _collect_download_results(futures, errors)

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
