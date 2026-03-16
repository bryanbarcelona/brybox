from brybox.core.inbox_kraken.helpers import (
    save_path,
)
from brybox.core.models.email import ProcessingContext, ProcessResult
from brybox.events.bus import publish_file_added
from brybox.exceptions.emails import (
    InboxKrakenResourceNotFoundError,
)


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
            if not payload or not isinstance(payload, bytes):
                continue

            target_path = save_path(f'{meta.uid}_{name}', save_dir)
            target_path.write_bytes(payload)

            publish_file_added(file_path=target_path, file_size=target_path.stat().st_size, is_healthy=True)
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
