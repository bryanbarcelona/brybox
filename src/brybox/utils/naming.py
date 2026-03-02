"""
Shared filename utilities.

# TODO (snap_jedi/naming.py): migrate PathStrategy._resolve_conflict here
# TODO (videosith/naming.py): migrate PathStrategy._resolve_conflict here
"""

from pathlib import Path


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
