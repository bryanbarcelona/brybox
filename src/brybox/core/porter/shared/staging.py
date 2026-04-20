from __future__ import annotations

import secrets
import shutil
import string
import time
from pathlib import Path
from typing import TYPE_CHECKING

from brybox.events.bus import publish_file_copied
from brybox.exceptions.transfers import (
    PorterFileOperationError,
    PorterResourceNotFoundError,
)
from brybox.utils.apple_files import AppleSidecarManager
from brybox.utils.health_check import is_healthy

if TYPE_CHECKING:
    from brybox.core.porter.shared.protocols import FileFilter
    from brybox.utils.apple_files import SidecarRename


def _generate_temp_name(original_path: Path) -> Path:
    """Generate collision-safe temporary filename."""
    timestamp = int(time.time() * 1000)
    rand_suffix = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    ext = original_path.suffix
    return Path(f'IMG_{timestamp}{rand_suffix}{ext}')


def _copy_single_sidecar(rename: SidecarRename, target: Path, temp_sidecar_paths: list) -> None:
    """Copy one sidecar file and verify."""
    target_path = target / rename.new_filename

    try:
        shutil.copy2(rename.original, target_path)
    except OSError as e:
        raise PorterFileOperationError(
            f'Failed to copy sidecar: {rename.original}',
            source_path=rename.original,
            dest_path=target_path,
            operation='copy',
        ) from e

    # Verify copy
    if not target_path.exists():
        raise PorterFileOperationError(
            f'Sidecar missing after copy: {target_path}',
            source_path=rename.original,
            dest_path=target_path,
            operation='verify',
        )

    if target_path.stat().st_size != rename.original.stat().st_size:
        raise PorterFileOperationError(
            f'Sidecar size mismatch: {rename.original}',
            source_path=rename.original,
            dest_path=target_path,
            operation='verify',
        )

    # Publish event
    publish_file_copied(
        source_path=rename.original,
        destination_path=target_path,
        source_size=rename.original.stat().st_size,
        destination_size=target_path.stat().st_size,
        source_healthy=True,
        destination_healthy=True,
    )

    temp_sidecar_paths.append(target_path)


def _copy_main_image(file_path: Path, temp_image_path: Path) -> None:
    """Copy main image file and verify."""
    try:
        shutil.copy2(file_path, temp_image_path)
    except OSError as e:
        raise PorterFileOperationError(
            f'Failed to copy image: {file_path.name}',
            source_path=file_path,
            dest_path=temp_image_path,
            operation='copy',
        ) from e

    # Verify copy
    if not temp_image_path.exists():
        raise PorterFileOperationError(
            f'Image missing after copy: {temp_image_path.name}',
            source_path=file_path,
            dest_path=temp_image_path,
            operation='verify',
        )

    if temp_image_path.stat().st_size != file_path.stat().st_size:
        raise PorterFileOperationError(
            f'Image size mismatch: {file_path.name}',
            source_path=file_path,
            dest_path=temp_image_path,
            operation='verify',
        )

    # Publish event
    publish_file_copied(
        source_path=file_path,
        destination_path=temp_image_path,
        source_size=file_path.stat().st_size,
        destination_size=temp_image_path.stat().st_size,
        source_healthy=is_healthy(file_path),
        destination_healthy=is_healthy(temp_image_path),
    )


def stage_files_to_target(
    source: Path,
    target: Path,
    file_filter: FileFilter,
    migrate_sidecars: bool,
) -> list[tuple[Path, Path, list[Path]]]:
    """
    Copy files from source to target with temporary names.

    Raises:
        PorterResourceNotFoundError: If source directory doesn't exist
        PorterFileOperationError: If file copy fails or size mismatch
        PorterStagingError: If sidecar operations fail
    """
    if not source.exists():
        raise PorterResourceNotFoundError(f'Source directory does not exist: {source}', resource_path=source)

    mappings = []

    for file_path in source.iterdir():
        if not file_path.is_file():
            continue

        if not file_filter.is_valid(file_path):
            continue

        # Generate temp name
        temp_name = _generate_temp_name(file_path)
        temp_image_path = target / temp_name

        # Handle sidecars if enabled
        temp_sidecar_paths = []
        if migrate_sidecars:
            renamed_group = AppleSidecarManager.get_renamed_sidecars(file_path, temp_name.stem)
            for rename in renamed_group.renames:
                _copy_single_sidecar(rename, target, temp_sidecar_paths)

        # Copy main image
        _copy_main_image(file_path, temp_image_path)

        mappings.append((file_path, temp_image_path, temp_sidecar_paths))

    return mappings
