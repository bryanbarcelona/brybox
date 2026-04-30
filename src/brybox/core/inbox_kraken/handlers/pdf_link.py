import re

import requests

from brybox.core.inbox_kraken.helpers import (
    save_path,
)
from brybox.core.models.email import ProcessingContext, ProcessResult
from brybox.events.bus import publish_file_added
from brybox.exceptions.emails import (
    InboxKrakenFileOperationError,
    InboxKrakenOperationFailedError,
    InboxKrakenResourceNotFoundError,
    InboxKrakenTimeoutError,
)


def download_pdf_handler(ctx: ProcessingContext) -> ProcessResult:
    meta = ctx.meta

    if not meta.invoice_link:
        raise InboxKrakenResourceNotFoundError(f'UID {meta.uid}: Invoice link missing from metadata.')

    try:
        # helpers.save_path now raises InboxKrakenConfigurationError if save_dir is bad
        clean_subject = re.sub(r'[^\w\-_ \.]', '_', meta.subject)[:40]
        target_path = save_path(f'{meta.uid}_{clean_subject}.pdf', ctx.save_dir)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        with requests.Session() as session:
            session.headers.update(headers)
            r = session.get(meta.invoice_link, timeout=30)
            r.raise_for_status()

        target_path.write_bytes(r.content)
        publish_file_added(file_path=target_path, file_size=target_path.stat().st_size, is_healthy=True)

        return ProcessResult(success=True, target_path=target_path, is_healthy=True, can_delete=True)

    except requests.Timeout as e:
        raise InboxKrakenTimeoutError('PDF download timed out', resource_path=meta.invoice_link) from e
    except requests.RequestException as e:
        print(
            f'Download error for {meta.invoice_link}: {e}, response status: {e.response.status_code if e.response else "no response"}'
        )
        raise InboxKrakenOperationFailedError(
            'PDF download failed', resource_path=meta.invoice_link, error_detail=str(e)
        ) from e
    except OSError as e:
        raise InboxKrakenFileOperationError('Disk write failed', dest_path=target_path) from e
