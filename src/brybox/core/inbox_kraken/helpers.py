import re
from email.header import decode_header
from pathlib import Path

import requests
from bs4 import BeautifulSoup

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


def resolve_redirected_url(url: str) -> str:
    """
    Unmasks tracking URLs (mlsend, bitly, etc.) to find the real destination.
    Uses stream=True to trigger redirects without downloading file bodies.
    """
    try:
        # HEAD is often ignored by trackers; GET with stream=True is the reliable way.
        with requests.get(url, allow_redirects=True, timeout=10, stream=True) as r:
            return r.url
    except requests.RequestException:
        return url


def get_dropbox_download_link(url: str) -> str:
    """Converts a Dropbox share link (viewing page) to a direct download stream."""
    if 'dropbox.com' not in url.lower():
        return url

    # Force the dl=1 parameter
    direct_url = url.replace('dl=0', 'dl=1')
    if '?dl=1' not in direct_url:
        direct_url += '&dl=1' if '?' in direct_url else '?dl=1'
    return direct_url


# --- 2. CLASSIFICATION HELPERS ---


def classify_link(url: str) -> str:
    """
    Determines if a link is a PDF or Dropbox Audio.
    Leverages resolve_redirected_url to see past tracking masks.
    """
    try:
        # Step 1: Get the real destination
        resolved_url = resolve_redirected_url(url)
        resolved_lower = resolved_url.lower()

        # Step 2: Quick check for direct extensions in URL
        audio_exts = {'.mp3', '.wav', '.m4a', '.ogg', '.aac', '.flac'}

        # Step 3: Peek at headers via a stream request
        with requests.get(resolved_url, allow_redirects=True, timeout=10, stream=True) as r:
            ctype = r.headers.get('Content-Type', '').lower()
            disp = r.headers.get('Content-Disposition', '').lower()

            if 'pdf' in ctype or resolved_lower.endswith('.pdf'):
                return 'PDF'

            if 'dropbox.com' in resolved_lower and (
                any(ext in resolved_lower for ext in audio_exts) or any(ext in disp for ext in audio_exts)
            ):
                return 'AUDIO'

    except requests.RequestException:
        return 'Error'
    else:
        return 'HTML page'


# --- 3. HTML PARSING HELPERS ---


def extract_invoice_link(html: str) -> str | None:
    """Finds potential invoice/receipt links in the HTML body."""
    if not html:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a', href=True):
        text = a.get_text(strip=True).lower()
        href = a['href'].lower()
        # Keywords for matching
        if any(k in text or k in href for k in ('invoice', 'receipt', 'rechnung', 'beleg')):
            return a['href']
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
    """FIXED: Now returns a Path object instead of a string."""
    if not save_dir:
        raise ValueError('save_dir required')
    return Path(save_dir) / safe_filename(base_name)


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
