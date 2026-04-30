import re
from email.header import decode_header
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup, Tag

from brybox.exceptions.emails import (
    InboxKrakenConfigurationError,
    InboxKrakenNetworkError,
    InboxKrakenResourceNotFoundError,
    InboxKrakenTimeoutError,
)

# --- CONFIG / CONSTANTS ---
RESERVED_NAMES = {
    'con',
    'prn',
    'aux',
    'nul',
    'com1',
    'com2',
    'com3',
    'com4',
    'com5',
    'com6',
    'com7',
    'com8',
    'com9',
    'lpt1',
    'lpt2',
    'lpt3',
    'lpt4',
    'lpt5',
    'lpt6',
    'lpt7',
    'lpt8',
    'lpt9',
}


# --- 1. RESOLUTION HELPERS ---


def resolve_redirected_url(url: str, session: requests.Session | None = None) -> str:
    """
    Unmasks tracking URLs (mlsend, bitly, etc.) to find the real destination.
    Uses stream=True to trigger redirects without downloading file bodies.
    """
    requester = session if session is not None else requests
    try:
        with requester.get(url, allow_redirects=True, timeout=10, stream=True) as r:
            return r.url
    except requests.Timeout as e:
        raise InboxKrakenTimeoutError(f'Redirection check timed out for {url}', resource_path=url) from e
    except requests.RequestException as e:
        raise InboxKrakenNetworkError(
            f'Failed to connect to resolution server for {url}', resource_path=url, error_detail=str(e)
        ) from e


# --- 2. CLASSIFICATION HELPERS ---


def classify_link(url: str) -> str:
    """
    Determines link type.
    NO try/except here. Let resolution and request errors bubble.
    """
    # 1. Resolve (This will now raise Timeout/NetworkError if it fails)
    resolved_url = resolve_redirected_url(url)
    resolved_lower = resolved_url.lower()

    audio_exts = {'.mp3', '.wav', '.m4a', '.ogg', '.aac', '.flac'}

    # 2. Peek headers
    try:
        with requests.get(resolved_url, allow_redirects=True, timeout=10, stream=True) as r:
            # We still don't use raise_for_status() because we want to see headers
            # even on some 'failed' pages, but we catch connection issues.
            ctype = r.headers.get('Content-Type', '').lower()
            disp = r.headers.get('Content-Disposition', '').lower()

            if 'pdf' in ctype or resolved_lower.endswith('.pdf'):
                return 'PDF'

            if 'dropbox.com' in resolved_lower and (
                any(ext in resolved_lower for ext in audio_exts) or any(ext in disp for ext in audio_exts)
            ):
                return 'AUDIO'

            return 'HTML page'

    except requests.Timeout as e:
        raise InboxKrakenTimeoutError(f'Classification timeout for {resolved_url}', resource_path=resolved_url) from e
    except requests.RequestException as e:
        raise InboxKrakenNetworkError(
            f'Classification network failure for {resolved_url}', resource_path=resolved_url, error_detail=str(e)
        ) from e


# --- 3. HTML PARSING HELPERS ---


def extract_invoice_link(html: str) -> str | None:
    """Finds potential invoice/receipt links in the HTML body."""
    if not html:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a', href=True):
        if not isinstance(a, Tag):
            continue

        href_attr = a.get('href')
        if href_attr is None:
            continue

        if isinstance(href_attr, list):
            href_value = next((str(v) for v in href_attr if isinstance(v, str)), None)
            if href_value is None:
                continue
        else:
            href_value = str(href_attr)

        href_lower = href_value.lower()
        text = a.get_text(strip=True).lower()

        if any(k in text or k in href_lower for k in ('invoice', 'receipt', 'rechnung', 'beleg')):
            return href_value

    return None


def extract_invoice_link_from_text(text: str) -> str | None:

    urls = re.findall(r'https?://[^\s<>"\'()]+', text)
    for url in urls:
        decoded = unquote(url.lower())
        if any(k in decoded for k in ('invoice', 'receipt', 'rechnung', 'beleg', 'download')):
            return unquote(url)  # Return decoded URL
    return None


# --- STRING & FILESYSTEM HELPERS ---


def safe_filename(s: str) -> str:
    """Modified: Retains Windows protection but cleaned up redundant assignments."""
    illegal = r'/\:*?"<>|=' + '\r\n\t'
    # Use empty string fallback initially to stay lean
    safe = ''.join('_' if c in illegal else c for c in (s or ''))
    safe = '_'.join(safe.split()).strip('_')

    if not safe or safe.lower() in RESERVED_NAMES:
        return 'unnamed'
    return safe


def save_path(base_name: str, save_dir: str | Path) -> Path:
    """Returns a Path object instead of a string."""
    if not save_dir:
        raise InboxKrakenConfigurationError('Save directory not provided', config_key='save_dir')

    path = Path(save_dir)
    if not path.exists():
        raise InboxKrakenResourceNotFoundError(f'Target save directory missing: {save_dir}', resource_path=save_dir)

    # safe_filename call remains same
    return path / safe_filename(base_name)


def decode_mime_words(s: str) -> str:
    """Exact logic from original decode_mime_words."""
    if not s:
        return ''
    decoded_fragments = decode_header(s)
    fragments = []
    for content, encoding in decoded_fragments:
        if isinstance(content, bytes):
            charset = encoding or 'utf-8'
            try:
                decoded = content.decode(charset, errors='replace')
            except LookupError:
                decoded = content.decode('utf-8', errors='replace')
            fragments.append(decoded)
        else:
            fragments.append(content)

    full_string = ''.join(fragments)
    # Replaces non-breaking space \u00A0 and other whitespace
    full_string = re.sub(r'[\s\u00A0]+', ' ', full_string)
    return full_string.strip()
