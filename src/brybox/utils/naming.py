"""
Shared filename utilities.

# TODO (snap_jedi/naming.py): migrate PathStrategy._resolve_conflict here
# TODO (videosith/naming.py): migrate PathStrategy._resolve_conflict here
"""

import re
from pathlib import Path

_FORBIDDEN_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_component(text: str) -> str:
    """
    Strip characters forbidden in Windows filenames and collapse whitespace.

    Args:
        text: Free-text filename component (e.g. an extracted document subject).

    Returns:
        Text safe to embed in a filename.
    """
    cleaned = _FORBIDDEN_FILENAME_CHARS.sub('', text)
    return re.sub(r'\s+', ' ', cleaned).strip()


def resolve_filename_conflict(target_path: Path) -> Path:
    """
    Resolve filename conflicts by appending (1), (2), etc.

    Args:
        target_path: Desired target path

    Returns:
        Conflict-free target path — unchanged if no conflict exists
    """
    if not target_path.exists():
        return target_path

    directory = target_path.parent
    stem = target_path.stem
    suffix = target_path.suffix

    counter = 1
    while (candidate := directory / f'{stem}({counter}){suffix}').exists():
        counter += 1

    return candidate
