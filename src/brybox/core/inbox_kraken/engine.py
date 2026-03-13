from __future__ import annotations

import imaplib
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brybox.core.inbox_kraken.classifier import EmailClassifier, Tag
from brybox.core.inbox_kraken.fetcher import EmailFetcher
from brybox.core.inbox_kraken.handlers import (
    delete_handler,
    download_attachment_handler,
    download_pdf_handler,
    dropbox_audio_handler,
    ignore_handler,
    kfw_handler,
    manual_click_handler,
    techem_handler,
)
from brybox.core.models.email import ProcessingContext
from brybox.exceptions.emails import (
    InboxKrakenConfigurationError,
    InboxKrakenError,
    InboxKrakenNetworkError,
)
from brybox.utils.logging import get_configured_logger, log_and_display, trackerator
from brybox.utils.settings import BryboxSettings

if TYPE_CHECKING:
    from types import TracebackType

    from brybox.core.models.email import ProcessResult


logger = get_configured_logger('InboxKraken')


class InboxKraken:
    """
    The Inbox Kraken: High-performance email orchestration.
    Uses a 'Hybrid Fetch' strategy to zip through junk while handling
    heavy-duty attachments and scrapers on-demand.
    """

    def __init__(
        self, mail_conn: imaplib.IMAP4_SSL | None = None, save_dir: Path | str | None = None, *, dry_run: bool = True
    ):

        # 1. Grab everything from centralized settings
        settings = BryboxSettings()
        e_creds = settings.creds.get_email_credentials()
        self.rules = settings.email.get('rules', [])
        self.creds = settings.creds.get_web_credentials()
        self.dry_run = dry_run

        # 2. Resolve Connection (Explicit vs Config vs Gmail Default)
        if mail_conn:
            self.mail = mail_conn
        else:
            if not e_creds.email or not isinstance(e_creds.email, str):
                raise InboxKrakenConfigurationError('Email username must be a non-empty string', config_key='email')

            if not e_creds.password or not isinstance(e_creds.password, str):
                raise InboxKrakenConfigurationError('Email password must be a non-empty string', config_key='password')
            host = e_creds.imap_server or 'imap.gmail.com'
            self.mail = imaplib.IMAP4_SSL(host)
            self.mail.login(e_creds.email, e_creds.password)
            self.mail.select('INBOX')
            log_and_display(f'Logged in to {host}')

        # 3. Resolve Save Directory (Argument -> Config -> TempFallback)
        config_path = settings.email.get('paths', {}).get('save_dir')
        raw_path = save_dir or config_path

        if not raw_path:
            self.save_dir = Path(tempfile.mkdtemp(prefix='inbox_kraken_')).resolve()
            log_and_display(f'Using temp save_dir: {self.save_dir}')
        else:
            self.save_dir = Path(raw_path).resolve()

        self.save_dir.mkdir(exist_ok=True, parents=True)

        # 4. Initialize Core Components
        self.fetcher = EmailFetcher(self.mail)
        self.classifier = EmailClassifier(self.rules)

        # 5. Handler Registry
        self.handlers = {
            Tag.DOWNLOAD_PDF: download_pdf_handler,
            Tag.DOWNLOAD_ATTACH: download_attachment_handler,
            Tag.DOWNLOAD_AUDIO: dropbox_audio_handler,
            Tag.TECHEM: techem_handler,
            Tag.KFW: kfw_handler,
            Tag.MANUAL_CLICK: manual_click_handler,
            Tag.IGNORE: ignore_handler,
            Tag.DELETE: delete_handler,
        }

    def run(self, mailbox: str = 'INBOX', limit: int | None = None, only_uids: list[int] | None = None) -> None:
        """Standard entry point for processing the inbox."""
        try:
            uids = self.fetcher.fetch_uids(mailbox=mailbox, limit=limit, only_uids=only_uids)
        except InboxKrakenConfigurationError as e:
            log_and_display(f'CRITICAL CONFIG ERROR: {e}. Stopping Kraken.', level='ERROR')
            return
        except InboxKrakenNetworkError as e:
            log_and_display(f'NETWORK ERROR: {e}. Will retry next session.', level='ERROR')
            return

        if not uids:
            log_and_display('No emails found to process.')
            return

        for uid in trackerator(uids, description='Kraken Processing'):
            try:
                self._process_single_email(uid)
            except InboxKrakenError as e:
                log_and_display(f'⚠️ UID {uid} processing skipped: {e}', level='WARNING')
            except Exception as e:  # noqa: BLE001
                log_and_display(f'❌ Unexpected error on UID {uid}: {e}', level='ERROR')

    def _process_single_email(self, uid: int) -> None:
        # A. LIGHT FETCH
        meta = self.fetcher.get_light_meta(uid)
        if not meta:
            return

        # B. PRE-CHECK: Is this sender/subject even in our JSON?
        if not self.classifier.is_candidate(meta):
            log_and_display(f'[IGNORE] UID: {uid} | {meta.sender[:25]:<25} | Not in rules.')
            return

        full_meta, msg_obj = self.fetcher.get_full_message(uid)
        if not full_meta or not msg_obj:
            log_and_display(f'[ERROR] UID: {uid} | Failed to fetch full message content')
            return

        # C. INITIAL CLASSIFY (Check for early actions like DELETE)
        tag = self.classifier.classify(full_meta)

        # LOG the found match
        log_msg = f'[{tag.name}] UID: {uid} | {full_meta.sender[:25]:<25} | {full_meta.subject[:45]:<45}'
        log_and_display(log_msg)

        if tag == Tag.DELETE:
            self._cleanup_email(uid)
            return

        if tag == Tag.IGNORE:
            return

        # E. EXECUTE HANDLER
        result = self._execute_handler(tag, full_meta, msg_obj)
        if result and result.success and result.can_delete:
            self._cleanup_email(uid)

    def _cleanup_email(self, uid: int) -> None:
        if self.dry_run:
            log_and_display(f'[DRY RUN] Would delete UID {uid}')
            return

        # Standard IMAP Move to Trash
        self.mail.uid('MOVE', str(uid), '[Gmail]/Trash')
        self.mail.expunge()

        log_and_display(f'Moved UID {uid} to Trash.')

    def _execute_handler(self, tag: Tag, meta: Any, msg_obj: Any | None) -> ProcessResult | None:
        handler = self.handlers.get(tag)
        if not handler:
            return None

        ctx = ProcessingContext(meta=meta, save_dir=self.save_dir, msg=msg_obj, creds=self.creds)
        return handler(ctx)

    def __enter__(self) -> InboxKraken:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        with suppress(Exception):
            self.mail.logout()
