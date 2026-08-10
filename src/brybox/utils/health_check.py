import mimetypes
from collections.abc import Callable
from pathlib import Path

import pdfplumber
from PIL import Image, UnidentifiedImageError

# --- Specific file-type health checks ---


def is_pdf_healthy(file_path: str | Path) -> bool:
    file_path = Path(file_path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False

    try:
        with pdfplumber.open(file_path) as pdf:
            _ = pdf.pages[0]
    except Exception:  # ruff: ignore[blind-except] - Any error means unhealthy, caller doesn't need specifics
        return False
    else:
        return True


# TODO: Extend with more image check support (e.g. HEIC)
def is_image_healthy(file_path: str | Path) -> bool:
    file_path = Path(file_path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False

    try:
        with Image.open(file_path) as img:
            _ = img.size  # reads header without strict full-content verification
    except UnidentifiedImageError:
        # Pillow doesn't recognise the format (e.g. HEIC with .jpg extension) —
        # the file is not corrupt, just misidentified; fall back to size check.
        return file_path.stat().st_size > 0
    except Exception:  # ruff: ignore[blind-except]
        return False
    else:
        return True


def _is_mp3_signature(header: bytes) -> bool:
    """True for an ID3 tag or a valid MPEG frame sync (11 set bits)."""
    if header[:3] == b'ID3':
        return True
    return len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0


# Signature bytes that confirm a file's content actually matches its audio
# extension, keyed by suffix since each container format is structured
# differently. Guards against e.g. an HTML error page saved with a .m4a
# extension by a download that silently received the wrong response.
_AUDIO_SIGNATURE_CHECKS: dict[str, Callable[[bytes], bool]] = {
    '.m4a': lambda header: header[4:8] == b'ftyp',
    '.mp3': _is_mp3_signature,
    '.flac': lambda header: header[:4] == b'fLaC',
    '.wav': lambda header: header[:4] == b'RIFF' and header[8:12] == b'WAVE',
}


def is_audio_healthy(file_path: str | Path) -> bool:
    file_path = Path(file_path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False

    check = _AUDIO_SIGNATURE_CHECKS.get(file_path.suffix.lower())
    if check is None:
        return True

    try:
        header = file_path.read_bytes()[:12]
    except OSError:
        return False

    return check(header)


# --- Dispatcher / main API ---

_FILETYPE_CHECKERS: dict[str, Callable[[Path], bool]] = {
    'application/pdf': is_pdf_healthy,
    'image/jpeg': is_image_healthy,
    'image/png': is_image_healthy,
    'image/gif': is_image_healthy,
    'audio/mp4': is_audio_healthy,
    'audio/mpeg': is_audio_healthy,
    'audio/x-flac': is_audio_healthy,
    'audio/wav': is_audio_healthy,
}


def is_healthy(file_path: str | Path) -> bool:
    """Dispatch to appropriate health checker based on mimetype."""
    file_path = Path(file_path)
    if not file_path.exists():
        return False

    mime, _ = mimetypes.guess_type(str(file_path))
    checker = _FILETYPE_CHECKERS.get(mime) if mime else None
    if checker is None:
        # default fallback: check existence & size only
        return file_path.stat().st_size > 0

    return checker(file_path)


__all__ = ['is_audio_healthy', 'is_healthy', 'is_image_healthy', 'is_pdf_healthy']
