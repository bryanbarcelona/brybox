import email
import imaplib
from email.message import Message

from brybox.core.inbox_kraken.helpers import decode_mime_words, extract_invoice_link
from brybox.core.models.email import EmailMeta
from brybox.exceptions.emails import (
    InboxKrakenNetworkError,
    InboxKrakenOperationFailedError,
    InboxKrakenTimeoutError,
)


class EmailFetcher:
    def __init__(self, mail_conn: imaplib.IMAP4_SSL):
        self.mail = mail_conn

    def fetch_uids(
        self,
        mailbox: str = 'INBOX',
        limit: int | None = None,
        only_uids: list[int] | None = None,
    ) -> list[int]:
        """Returns the list of UIDs to process."""
        self.mail.select(mailbox)
        if only_uids:
            return sorted([int(u) for u in only_uids])

        try:
            typ, data = self.mail.uid('SEARCH', None, 'ALL')
        except TimeoutError as e:
            raise InboxKrakenTimeoutError('IMAP search timed out', error_detail=str(e)) from e
        except (imaplib.IMAP4.error, OSError) as e:
            raise InboxKrakenNetworkError('Network failure during IMAP search', error_detail=str(e)) from e

        if typ != 'OK':
            raise InboxKrakenOperationFailedError(f'IMAP SEARCH failed with status: {typ}')

        if not data[0]:
            return []

        uids = [int(u) for u in data[0].split()]
        return uids[-limit:] if limit else uids

    def get_light_meta(self, uid: int) -> EmailMeta | None:
        """FAST: Fetches only headers for classification, DELETE, and Scraper triggers."""
        try:
            typ, data = self.mail.uid('FETCH', str(uid), '(BODY.PEEK[HEADER])')
        except TimeoutError as e:
            raise InboxKrakenTimeoutError(f'Timeout fetching headers for UID {uid}', error_detail=str(e)) from e
        except (imaplib.IMAP4.error, OSError) as e:
            raise InboxKrakenNetworkError(f'Connection failed fetching UID {uid}', error_detail=str(e)) from e

        if typ != 'OK' or not data:
            raise InboxKrakenOperationFailedError(f'IMAP fetch failed for UID {uid}. Status: {typ}')

        msg = email.message_from_bytes(data[0][1])
        return EmailMeta(
            uid=uid,
            subject=decode_mime_words(msg.get('Subject', '')),
            sender=decode_mime_words(msg.get('From', '')),
            body_html='',
            attachments=[],
            invoice_link=None,
        )

    def get_full_message(self, uid: int) -> tuple[EmailMeta | None, Message | None]:
        """SLOW: Fetches full content for PDF/Attachment extraction."""
        try:
            typ, data = self.mail.uid('FETCH', str(uid), '(RFC822)')
        except TimeoutError as e:
            raise InboxKrakenTimeoutError(f'Timeout during full fetch of UID {uid}', error_detail=str(e)) from e
        except (imaplib.IMAP4.error, OSError) as e:
            raise InboxKrakenNetworkError(f'Network error during full fetch of UID {uid}', error_detail=str(e)) from e

        if typ != 'OK' or not data or data[0] is None:
            raise InboxKrakenOperationFailedError(f'Full fetch failed for UID {uid}. Status: {typ}')

        raw_message = data[0][1]
        msg = email.message_from_bytes(raw_message)

        body_html = ''
        for part in msg.walk():
            if part.get_content_type() == 'text/html' and not part.get_filename():
                body_html = part.get_payload(decode=True).decode(errors='ignore')
                break

        attachments = [p.get_filename() for p in msg.walk() if p.get_filename()]
        link = extract_invoice_link(body_html)

        meta = EmailMeta(
            uid=uid,
            subject=decode_mime_words(msg.get('Subject', '')),
            sender=decode_mime_words(msg.get('From', '')),
            body_html=body_html,
            attachments=attachments,
            invoice_link=link,
        )
        return meta, msg
