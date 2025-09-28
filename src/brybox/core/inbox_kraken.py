import requests
import imaplib
import email
from email.header import decode_header
import json
import re
from bs4 import BeautifulSoup
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Callable, List, Optional, Tuple, Any
import os
from pathlib import Path
from urllib.parse import urlparse
import tempfile

from tqdm import tqdm

from .web_marionette import download_kfw_invoices, download_techem_invoice
from ..utils.credentials import CredentialsManager, EmailCredentials, WebCredentials
from ..utils.logging import log_and_display, get_configured_logger
from ..utils.config_loader import ConfigLoader

# --- config ------------------------------------------------------------------

logger = get_configured_logger("InboxKraken")

def _load_email_config(
    config_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load merged email configs, matching PDF pattern."""
    if config is not None:
        return config
    config_path = config_path or "configs"
    config_dir = Path(config_path)
    if not config_dir.is_dir():
        log_and_display(f"Config path {config_path} is not a directory - using defaults")
        return {"paths": {}, "rules": []}
    loaded = ConfigLoader.load_configs(
        config_path=str(config_dir),
        config_files={"paths": "paths.json", "rules": "email_rules.json"}
    )
    log_and_display(f"Loaded configs from {config_path}")
    return loaded

# -----------------------------------------------------------------------------

# ---------- TAGS ----------
class Tag(Enum):
    DELETE            = auto()
    DOWNLOAD_PDF      = auto()
    DOWNLOAD_ATTACH   = auto()
    MANUAL_CLICK      = auto()
    IGNORE            = auto()
    DOWNLOAD_AUDIO    = auto()
    TECHEM            = auto()
    KFW               = auto()

# ---------- DATA ----------
@dataclass
class Meta:
    uid: int
    sender: str
    subject: str
    body_html: str
    attachments: list[str]
    invoice_link: str | None = None

# ---------- UTILS ----------
def classify_link(url: str) -> str:
    try:
        r = requests.head(url, allow_redirects=True, timeout=10)
        ctype = r.headers.get("Content-Type", "").lower()
        return "PDF" if "pdf" in ctype else "HTML page"
    except Exception:
        return "Error"

def extract_invoice_link(html: str) -> str | None:
    """
    Return the first <a href="..."> whose visible text or URL
    contains 'invoice', 'receipt', 'rechnung' (case-insensitive).
    """
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"].lower()
        if any(k in text or k in href for k in ("invoice", "receipt", "rechnung")):
            return a["href"]
    return None

def save_path(base_name: str, save_dir: str) -> str:
    """Generate safe file path in save_dir."""
    if save_dir is None:
        raise ValueError("save_dir required")
    base_name = safe_filename(base_name)
    return os.path.join(save_dir, base_name)

def safe_filename(s):
    """Convert string to safe filename by replacing illegal characters with '_'."""
    illegal = r'/\:*?"<>|=' + '\r\n\t'
    safe = ''.join('_' if c in illegal else c for c in (s or 'unnamed'))
    safe = '_'.join(safe.split()).strip('_')
    return safe or 'unnamed' if safe.lower() not in ('con', 'prn', 'aux', 'nul', 'com1', 'com2', 
                                                     'com3', 'com4', 'com5', 'com6', 'com7', 'com8', 
                                                     'com9', 'lpt1', 'lpt2', 'lpt3', 'lpt4', 'lpt5', 
                                                     'lpt6', 'lpt7', 'lpt8', 'lpt9') else 'unnamed'

def download_dropbox_audio(body_html: str, save_dir: str) -> list[str]:
    """Extract and download Dropbox audio files. Requires save_dir."""
    if save_dir is None:
        raise ValueError("save_dir required")
    downloaded_files = []
    soup = BeautifulSoup(body_html, 'html.parser')
    links = [a['href'] for a in soup.find_all('a', href=True) if a['href'].startswith('http')]
    audio_extensions = {'.mp3', '.wav', '.m4a', '.ogg', '.aac', '.flac'}

    for link in links:
        try:
            r = requests.get(link, allow_redirects=True, timeout=5, stream=True)
            final_url = r.url

            if 'dropbox.com' not in final_url.lower():
                continue
            download_url = final_url.replace('dl=0', 'dl=1')
            if '?dl=1' not in download_url and '?' in download_url:
                download_url += '&dl=1'
            elif '?dl=1' not in download_url:
                download_url += '?dl=1'

            parsed = urlparse(download_url)
            url_path = parsed.path.lower()
            if not any(ext in url_path for ext in audio_extensions):
                continue
            filename = None
            disposition = r.headers.get('content-disposition', '')
            if 'filename=' in disposition:
                filename = disposition.split('filename=')[-1].strip('"')
            if not filename:
                parsed = urlparse(download_url)
                filename = os.path.basename(parsed.path) or f'audio_{len(downloaded_files) + 1}'
            file_path = save_path(filename, save_dir=save_dir)

            if os.path.exists(file_path):
                log_and_display(f"Skipped duplicate: {file_path}")
                continue
            with requests.get(download_url, stream=True, timeout=10) as dl_r:
                dl_r.raise_for_status()
                with open(file_path, 'wb') as f:
                    for chunk in dl_r.iter_content(chunk_size=8192):
                        f.write(chunk)
            downloaded_files.append(file_path)
            log_and_display(f"Downloaded: {file_path}")
            logger.info(f"Downloaded audio file: {file_path}")
        except Exception as e:
            log_and_display(f"Error downloading {link}: {e}")
            continue

    return downloaded_files

def decode_mime_words(s):
    decoded_fragments = decode_header(s)
    fragments = []
    for content, encoding in decoded_fragments:
        if isinstance(content, bytes):
            charset = encoding or 'utf-8'
            try:
                content = content.decode(charset, errors='replace')
            except LookupError:
                # Fallback for unknown encodings
                content = content.decode('utf-8', errors='replace')
        fragments.append(content)

    full_string = ''.join(fragments)

    # Step 1: Replace any kind of whitespace (including U+00A0) with a regular space
    # \s covers regular space, \t, \n, \r, etc.
    # \xa0 is the Unicode code point for non-breaking space
    full_string = re.sub(r'[\s\u00A0]+', ' ', full_string)

    # Step 2: Strip leading/trailing spaces
    full_string = full_string.strip()

    return full_string

def parse_email_content(uid: int, raw_message: bytes) -> Meta:
    """Extract structured data from raw email message."""
    msg = email.message_from_bytes(raw_message)
    
    # Extract HTML body
    body_html = ""
    for part in msg.walk():
        if part.get_content_type() == "text/html" and not part.get_filename():
            body_html = part.get_payload(decode=True).decode(errors="ignore")
            break
    
    # Extract attachments
    attachments = [p.get_filename() for p in msg.walk() if p.get_filename()]
    
    # Extract invoice links
    link = extract_invoice_link(body_html)

    return Meta(
        uid=uid,
        subject=decode_mime_words(msg.get("Subject", "")),
        sender=decode_mime_words(msg.get("From", "")),
        body_html=body_html,
        attachments=attachments,
        invoice_link=link,
    )

def get_emails_to_process(mail: imaplib.IMAP4_SSL, mailbox: str = "INBOX", limit: Optional[int] = None) -> List[Tuple[int, bytes]]:
    """Fetch email UIDs and raw content for processing."""
    mail.select(mailbox)
    
    typ, data = mail.uid('SEARCH', None, 'ALL')
    uids = [int(u) for u in data[0].split()]
    
    if limit:
        uids = uids[-limit:]
    
    emails = []
    for uid in uids:
        # if uid != 43798:  # Debug skip
        #     continue
        typ, data = mail.uid('FETCH', str(uid), '(RFC822)')
        raw = data[0][1]
        emails.append((uid, raw))
    
    log_and_display(f"Fetched {len(emails)} emails for processing.")
    return emails

# def _delete(uid: int) -> None:
#     #mail.uid('MOVE', str(uid).encode(), "[Gmail]/Trash")
#     pass

def _delete(uid: int, mail: imaplib.IMAP4_SSL) -> None:
    """
    Permanently move the e-mail with the given UID to the server's trash folder.
    NOTE: disabled during testing to avoid data loss.
    """
    # TODO: uncomment the block below after staging tests
    # ----------------------------------------------------------
    # trash_folder = "[Gmail]/Trash"          # or mail.probably_trash_folder
    # status, _ = mail.uid('MOVE', str(uid).encode(), trash_folder)
    # if status != 'OK':
    #     raise RuntimeError(f"Could not move UID {uid} to {trash_folder}")
    # ----------------------------------------------------------

    raise NotImplementedError(
        "Delete is disabled for test runs - see TODO in _delete()."
    )

# ---------- CLASSIFIER ----------

def classify(meta: Meta, rules: List[Dict[str, Any]]) -> Tag:
    """Classify using provided rules."""
    for rule in rules:
        match = True
        # Check sender condition
        if 'sender' in rule:
            if rule['sender'].lower() not in meta.sender.lower():
                match = False
        # Check subject condition  
        if 'subject' in rule:
            if rule['subject'].lower() not in meta.subject.lower():
                match = False
        # Check attachment condition
        if 'has_pdf_attachment' in rule:
            if rule['has_pdf_attachment']:
                if not any(a.lower().endswith(".pdf") for a in meta.attachments):
                    match = False
        # Check custom conditions
        if 'embedded_link' in rule:
            if rule['embedded_link']:
                if not (meta.invoice_link and classify_link(meta.invoice_link) == "PDF"):
                    match = False
        if match:
            return Tag[rule['action']]
    return Tag.IGNORE

# ---------- HANDLERS ----------

def delete_handler(meta: Meta, mail: imaplib.IMAP4_SSL, _save_dir: Optional[str] = None, _web_credentials: Optional[WebCredentials] = None, dry_run: bool = True) -> None:
    if dry_run:
        log_and_display(f"UID {meta.uid} | DRY-RUN | DELETE | skipped")
        return

    # TODO: uncomment _delete body when ready for production
    _delete(meta.uid, mail)
    log_and_display(
        f"UID {meta.uid} | DELETED | {meta.sender} | '{meta.subject}'"
    )

def download_pdf_handler(meta: Meta, mail: imaplib.IMAP4_SSL, save_dir: Optional[str] = None, _web_credentials: Optional[WebCredentials] = None, dry_run: bool = True) -> None:
    if dry_run:
        log_and_display(f"UID {meta.uid} | DRY-RUN | DOWNLOAD-PDF | skipped")
        return
    
    assert meta.invoice_link
    r = requests.get(meta.invoice_link, timeout=30)
    r.raise_for_status()
    fname = save_path(f"{meta.uid}_{re.sub(r'[^\w\-_\. ]', '_', meta.subject)[:40]}.pdf", save_dir=save_dir)
    with open(fname, "wb") as f:
        f.write(r.content)
    log_and_display(f"UID {meta.uid} | DOWNLOAD | Downloaded PDF from {meta.invoice_link} to {fname}")
    delete_handler(meta, mail)

def download_attachment_handler(meta: Meta, mail: imaplib.IMAP4_SSL, save_dir: Optional[str] = None, _web_credentials: Optional[WebCredentials] = None, dry_run: bool = True) -> None:
    if dry_run:
        log_and_display(f"UID {meta.uid} | DRY-RUN | DOWNLOAD-ATTACH | skipped")
        return
    typ, data = mail.uid('FETCH', str(meta.uid).encode(), '(RFC822)')
    raw = data[0][1]
    msg = email.message_from_bytes(raw)

    downloaded_any = False
    for part in msg.walk():
        name = part.get_filename()
        if name and name.lower().endswith(".pdf") and part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True)
            fname = save_path(f"{meta.uid}_{name}", save_dir=save_dir)
            with open(fname, "wb") as f:
                f.write(payload)
            log_and_display(f"UID {meta.uid} | DOWNLOAD | Downloaded PDF attachment: {fname}")
            downloaded_any = True

    if downloaded_any:
        delete_handler(meta, mail)

def download_audio_handler(meta: Meta, mail: imaplib.IMAP4_SSL, save_dir: Optional[str] = None, _web_credentials: Optional[WebCredentials] = None, dry_run: bool = True) -> None:
    """Handler to download Dropbox audio files and update meta."""
    if dry_run:
        log_and_display(f"UID {meta.uid} | DRY-RUN | DOWNLOAD-AUDIO | skipped")
        return

    audio_files = download_dropbox_audio(meta.body_html, save_dir=save_dir)
    meta.audio_files = audio_files  # Assuming Meta can store audio_files

def download_techem_handler(meta: Meta, mail: imaplib.IMAP4_SSL, save_dir: Optional[str] = None, web_credentials: Optional[WebCredentials] = None, dry_run: bool = True) -> None:
    """Handler to download Techem invoices using Playwright automation."""
    if dry_run:
        log_and_display(f"UID {meta.uid} | DRY-RUN | TECHEM-DOWNLOAD | skipped")
        return

    try:       
        success = download_techem_invoice(
            user=web_credentials.techem_user,
            password=web_credentials.techem_password,
            download_dir=save_dir,
            headless=False
        )
        
        if success:
            log_and_display(f"UID {meta.uid} | TECHEM_DOWNLOAD | Successfully downloaded Techem invoice")
            delete_handler(meta, mail)
        else:
            log_and_display(f"UID {meta.uid} | TECHEM_FAILED | Failed to download Techem invoice - email retained")
            
    except Exception as e:
        log_and_display(f"UID {meta.uid} | TECHEM_ERROR | Error downloading Techem invoice: {e}")

def download_kfw_handler(meta: Meta, mail: imaplib.IMAP4_SSL, save_dir: Optional[str] = None, web_credentials: Optional[WebCredentials] = None, dry_run: bool = True) -> None:    
    """Handler to download KFW documents using Playwright automation."""
    if dry_run:
        log_and_display(f"UID {meta.uid} | DRY-RUN | KFW-DOWNLOAD | skipped")
        return

    try:
        success = download_kfw_invoices(
            user=web_credentials.kfw_user,
            password=web_credentials.kfw_password,
            download_dir=save_dir,
            headless=True
        )
        
        if success:
            log_and_display(f"UID {meta.uid} | KFW_DOWNLOAD | Successfully downloaded KFW documents")
            delete_handler(meta, mail)
        else:
            log_and_display(f"UID {meta.uid} | KFW_FAILED | Failed to download KFW documents - email retained")
            
    except Exception as e:
        log_and_display(f"UID {meta.uid} | KFW_ERROR | Error downloading KFW documents: {e}")

def manual_click_handler(meta: Meta, mail: imaplib.IMAP4_SSL, _save_dir: Optional[str] = None, _web_credentials: Optional[WebCredentials] = None, _dry_run: bool = True) -> None:
    log_and_display(f"UID {meta.uid} | MANUAL_CLICK | Click manually: {meta.invoice_link}")

def ignore_handler(meta: Meta, mail: imaplib.IMAP4_SSL, _save_dir: Optional[str] = None, _web_credentials: Optional[WebCredentials] = None, _dry_run: bool = True) -> None:
    log_and_display(f"UID {meta.uid} | IGNORED | {meta.sender} | '{meta.subject}'")
    
# ---------- ROUTING ----------
HANDLERS: Dict[Tag, Callable[[Meta, imaplib.IMAP4_SSL, Optional[str], Optional[WebCredentials], bool], None]] = {
    Tag.DELETE: delete_handler,
    Tag.DOWNLOAD_PDF: download_pdf_handler,
    Tag.DOWNLOAD_ATTACH: download_attachment_handler,
    Tag.MANUAL_CLICK: manual_click_handler,
    Tag.IGNORE: ignore_handler,
    Tag.DOWNLOAD_AUDIO: download_audio_handler,
    Tag.TECHEM: download_techem_handler,
    Tag.KFW: download_kfw_handler,
}

# ---------- LIVE LOOP ----------

def fetch_and_process_emails(
    mailbox: str = "INBOX",
    email_credentials: Optional[EmailCredentials] = None,
    web_credentials: Optional[WebCredentials] = None,
    config_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    save_dir: Optional[str] = None,
    progress_bar: bool = True,
    dry_run: bool = False
):
    # Default to loading from .env if not provided
    if email_credentials is None:
        credential_manager = CredentialsManager()
        email_credentials = credential_manager.get_email_credentials()
    
    if web_credentials is None:
        credential_manager = CredentialsManager()
        web_credentials = credential_manager.get_web_credentials()

    # Load configs
    loaded_config = _load_email_config(config_path, config)
    paths = loaded_config.get("paths", {})
    effective_save_dir = save_dir or paths.get("save_dir")
    if not effective_save_dir:
        effective_save_dir = tempfile.mkdtemp(prefix="inbox_kraken_")
        log_and_display(f"Using temp save_dir: {effective_save_dir}")
    effective_save_dir = str(Path(effective_save_dir).resolve())
    os.makedirs(effective_save_dir, exist_ok=True)
    
    rules = loaded_config.get("rules", [])
    if not rules:
        log_and_display("No rules loaded - all emails will be IGNORED")

    with imaplib.IMAP4_SSL(email_credentials.imap_server) as mail:
        mail.login(email_credentials.email, email_credentials.password)
        mail.select(mailbox)

        log_and_display(f"Logged in to server {email_credentials.imap_server}")
        emails = get_emails_to_process(mail, mailbox, limit=160)  # Your current limit

        emails = tqdm(emails, desc="Processing Emails", colour="#ace1af") if progress_bar else emails
        
        for uid, raw_message in emails:

            try:
                meta = parse_email_content(uid, raw_message)
                tag = classify(meta, rules=rules)

                if tag in HANDLERS:
                    HANDLERS[tag](meta, mail, effective_save_dir, web_credentials, dry_run)
                else:
                    logger.error(f"Unknown tag: {tag}")
                    ignore_handler(meta, mail, save_dir=effective_save_dir)
            except Exception as e:
                logger.exception(f"Failed to process email UID {uid}: {e}")
                continue
    log_and_display(f"Finished email processing")


if __name__ == "__main__":

    fetch_and_process_emails()
