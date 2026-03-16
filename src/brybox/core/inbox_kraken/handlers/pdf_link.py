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

        r = requests.get(meta.invoice_link, timeout=30)
        r.raise_for_status()

        target_path.write_bytes(r.content)
        publish_file_added(file_path=target_path, file_size=target_path.stat().st_size, is_healthy=True)

        return ProcessResult(success=True, target_path=target_path, is_healthy=True, can_delete=True)

    except requests.Timeout as e:
        raise InboxKrakenTimeoutError('PDF download timed out', resource_path=meta.invoice_link) from e
    except requests.RequestException as e:
        raise InboxKrakenOperationFailedError(
            'PDF download failed', resource_path=meta.invoice_link, error_detail=str(e)
        ) from e
    except OSError as e:
        raise InboxKrakenFileOperationError('Disk write failed', dest_path=target_path) from e
