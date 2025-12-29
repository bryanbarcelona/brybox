from __future__ import annotations

import random
import shutil
import string
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ....events.bus import publish_file_copied
from ....utils.apple_files import AppleSidecarManager
from ....utils.health_check import is_healthy
from ....utils.logging import log_and_display

if TYPE_CHECKING:
    from .protocols import FileFilter


def _is_valid_image(file_path: Path) -> bool:
    """
    Check if file is a primary image asset (not system file or sidecar).

    Args:
        file_path: File to validate

    Returns:
        True if file is a processable image
    """
    # Skip macOS/Windows system files
    if file_path.name.startswith('._'):
        return False

    # Only process image files
    return file_path.suffix.lower() in {'.jpg', '.jpeg', '.heic', '.heif', '.png'}


def _generate_temp_name(original_path: Path) -> Path:
    """
    Generate collision-safe temporary filename.

    Uses timestamp + random suffix to ensure uniqueness during staging.
    Format: IMG_{timestamp}{random}{ext}

    Args:
        original_path: Original file path (for extension)

    Returns:
        Temporary filename string

    Example:
        >>> _generate_temp_name(Path('IMG_1234.HEIC'))
        'IMG_1704452123456abcd1234.HEIC'
    """
    timestamp = int(time.time() * 1000)
    rand_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    ext = original_path.suffix

    return Path(f'IMG_{timestamp}{rand_suffix}{ext}')


def _stage_files_to_target(
    source: Path, target: Path, file_filter: FileFilter, migrate_sidecars: bool, dry_run: bool, action_prefix: str
) -> list[tuple[Path, Path, list[Path]]]:
    """
    Copy files from source to target with temporary names (Phase 1).

    Creates collision-safe temporary copies of all images and their sidecars.
    Returns mappings to track original -> temp relationships for later phases.

    Args:
        source: Source directory
        target: Target directory
        migrate_sidecars: Whether to copy sidecar files
        dry_run: Simulation mode
        action_prefix: Logging prefix (e.g., "[DRY RUN]")

    Returns:
        List of tuples: (source_image_path, temp_image_path, [temp_sidecar_paths])

    Example:
        >>> mappings = _stage_files_to_target(src, tgt, True, False, '[ACTION]')
        >>> for orig, temp, sidecars in mappings:
        ...     print(f'{orig.name} -> {temp.name} (+ {len(sidecars)} sidecars)')
    """
    mappings = []

    for file_path in source.iterdir():
        if not file_path.is_file():
            continue

        # Only process valid images
        if not file_filter.is_valid(file_path):
            continue

        # Generate collision-safe temp name
        temp_name = _generate_temp_name(file_path)
        temp_image_path = target / temp_name

        # Find sidecars if migration enabled
        temp_sidecar_paths = []

        if migrate_sidecars:
            renamed_group = AppleSidecarManager.get_renamed_sidecars(file_path, temp_name.stem)
            for rename in renamed_group.renames:
                target_path = target / rename.new_filename

                if not dry_run:
                    shutil.copy2(rename.original, target_path)

                    publish_file_copied(
                        source_path=str(rename.original),
                        destination_path=str(target_path),
                        source_size=rename.original.stat().st_size,
                        destination_size=target_path.stat().st_size,
                        source_healthy=is_healthy(rename.original),
                        destination_healthy=is_healthy(target_path),
                    )

                    if not target_path.exists():
                        raise OSError(f'Failed to copy sidecar: {rename.original}')
                    if target_path.stat().st_size != rename.original.stat().st_size:
                        raise OSError(f'Size mismatch for sidecar: {rename.original}')

                    temp_sidecar_paths.append(target_path)

                    log_and_display(f'Staged sidecar: {rename.original} -> {target_path}')

        # Copy main image
        if dry_run:
            log_and_display(
                f'{action_prefix} Would stage: {file_path.name} -> {temp_name} (+ {len(temp_sidecar_paths)} sidecars)'
            )
        else:
            log_and_display(f'Staging file: {file_path.name} -> {temp_name}', log=False)
            shutil.copy2(file_path, temp_image_path)

            publish_file_copied(
                source_path=str(file_path),
                destination_path=str(temp_image_path),
                source_size=file_path.stat().st_size,
                destination_size=temp_image_path.stat().st_size,
                source_healthy=is_healthy(file_path),
                destination_healthy=is_healthy(temp_image_path),
            )

            if not temp_image_path.exists():
                raise OSError(f'Failed to copy image: {file_path.name}')
            if temp_image_path.stat().st_size != file_path.stat().st_size:
                raise OSError(f'Size mismatch for image: {file_path.name}')

            log_and_display(f'Staged: {file_path.name} -> {temp_name} (+ {len(temp_sidecar_paths)} sidecars)')

        # Track mapping for later phases
        mappings.append((file_path, temp_image_path, temp_sidecar_paths))

    return mappings
