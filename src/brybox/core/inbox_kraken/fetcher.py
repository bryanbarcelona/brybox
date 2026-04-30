import email
import imaplib
import re
from email.message import Message

from brybox.core.inbox_kraken.helpers import decode_mime_words, extract_invoice_link, extract_invoice_link_from_text
from brybox.core.models.email import EmailMeta
from brybox.exceptions.emails import (
    InboxKrakenNetworkError,
    InboxKrakenOperationFailedError,
    InboxKrakenTimeoutError,
)


class EmailFetcher:
    def __init__(self, mail_conn: imaplib.IMAP4_SSL):
        self.mail: imaplib.IMAP4_SSL = mail_conn

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
            typ, data = self.mail.uid('SEARCH', 'ALL')
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

    def get_light_meta_batch(
        self,
        uids: list[int],
        limit: int | None = None,
        only_uids: list[int] | None = None,
    ) -> list[EmailMeta]:
        """
        FAST: Fetches headers for multiple UIDs in a single IMAP round trip.
        Intended for preview — never triggers a full message fetch.

        Args:
            uids:      Full list of UIDs to fetch (already resolved by fetch_uids).
            limit:     Optional cap — takes the last N UIDs (consistent with fetch_uids).
            only_uids: Optional explicit UID subset to restrict to.

        Returns:
            List of EmailMeta objects with uid, sender, subject populated.
            attachments=[], invoice_link=None, body_html='' — same as get_light_meta.
        """
        if only_uids:
            uids = [u for u in uids if u in only_uids]
        if limit:
            uids = uids[-limit:]
        if not uids:
            return []

        uid_str = ','.join(str(u) for u in uids)

        try:
            typ, data = self.mail.uid('FETCH', uid_str, '(BODY.PEEK[HEADER])')
        except TimeoutError as e:
            raise InboxKrakenTimeoutError('Timeout during batch header fetch', error_detail=str(e)) from e
        except (imaplib.IMAP4.error, OSError) as e:
            raise InboxKrakenNetworkError('Network failure during batch header fetch', error_detail=str(e)) from e

        if typ != 'OK' or not data:
            raise InboxKrakenOperationFailedError(f'Batch IMAP fetch failed. Status: {typ}')

        results: list[EmailMeta] = []
        for i, item in enumerate(data):
            # imaplib interleaves response tuples with b')' separator bytes — skip those
            if not isinstance(item, tuple):
                continue
            raw_uid_header, raw_headers = item
            # UID is embedded in the response header e.g. b'123 (UID 456 BODY...)'
            uid_match = re.search(rb'UID (\d+)', raw_uid_header)
            uid = int(uid_match.group(1)) if uid_match else uids[i // 2]

            msg = email.message_from_bytes(raw_headers)
            results.append(
                EmailMeta(
                    uid=uid,
                    subject=decode_mime_words(msg.get('Subject', '')),
                    sender=decode_mime_words(msg.get('From', '')),
                    body_html='',
                    attachments=[],
                    invoice_link=None,
                )
            )

        return results

    @staticmethod
    def _extract_body_and_link(msg: Message) -> tuple[str, str | None]:
        """Extract HTML body (if any) and invoice link from email message."""
        body_html = ''
        link = None

        # First pass: HTML part
        for part in msg.walk():
            if part.get_content_type() == 'text/html' and not part.get_filename():
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    body_html = payload.decode(errors='ignore')
                link = extract_invoice_link(body_html)
                if link:
                    return body_html, link
                break  # Stop searching HTML after first HTML part

        # Second pass: plain text part if link not found
        if not link:
            for part in msg.walk():
                if part.get_content_type() == 'text/plain' and not part.get_filename():
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        text = payload.decode(errors='ignore')
                        link = extract_invoice_link_from_text(text)
                    break

        return body_html, link

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

        body_html, link = self._extract_body_and_link(msg)

        attachments = [p.get_filename() for p in msg.walk() if p.get_filename()]
        attachments = [f for f in attachments if f is not None]

        meta = EmailMeta(
            uid=uid,
            subject=decode_mime_words(msg.get('Subject', '')),
            sender=decode_mime_words(msg.get('From', '')),
            body_html=body_html,
            attachments=attachments,
            invoice_link=link,
        )
        return meta, msg
