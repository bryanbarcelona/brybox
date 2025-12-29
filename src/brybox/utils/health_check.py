import mimetypes
from collections.abc import Callable
from pathlib import Path

import pdfplumber
from PIL import Image

# --- Specific file-type health checks ---


def is_pdf_healthy(file_path: str | Path) -> bool:
    file_path = Path(file_path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False

    try:
        with pdfplumber.open(file_path) as pdf:
            _ = pdf.pages[0]
        return True
    except Exception:
        return False


# TODO: Extend with more image check support (e.g. HEIC)
def is_image_healthy(file_path: str | Path) -> bool:
    file_path = Path(file_path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False

    try:
        with Image.open(file_path) as img:
            img.verify()
        return True
    except Exception:
        return False


# --- Dispatcher / main API ---

_FILETYPE_CHECKERS: dict[str, Callable[[Path], bool]] = {
    'application/pdf': is_pdf_healthy,
    'image/jpeg': is_image_healthy,
    'image/png': is_image_healthy,
    'image/gif': is_image_healthy,
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


__all__ = ['is_healthy', 'is_image_healthy', 'is_pdf_healthy']
