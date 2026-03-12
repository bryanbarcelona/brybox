from pathlib import Path

from brybox.core.porter.shared.protocols import Deduplicator
from brybox.events.bus import publish_file_deleted
from brybox.exceptions.transfers import PorterFileOperationError, PorterOperationFailedError
from brybox.utils.apple_files import AppleSidecarManager


def _delete_duplicate_file(dup_path: Path) -> None:
    """Delete a single duplicate file and publish event."""
    try:
        file_size = dup_path.stat().st_size
        dup_path.unlink()
        publish_file_deleted(str(dup_path), file_size)
    except OSError as e:
        raise PorterFileOperationError(
            f'Failed to delete duplicate file: {dup_path}',
            source_path=dup_path,
            operation='delete',
            error_detail=str(e),
        ) from e


def _delete_sidecars(sidecar_paths: list[Path]) -> None:
    """Delete sidecar files for a duplicate."""
    for sidecar in sidecar_paths:
        if not sidecar.exists():
            continue

        try:
            sidecar_size = sidecar.stat().st_size
            sidecar.unlink()
            publish_file_deleted(str(sidecar), sidecar_size)
        except OSError as e:
            raise PorterFileOperationError(
                f'Failed to delete sidecar for duplicate: {sidecar}',
                source_path=sidecar,
                operation='delete',
                error_detail=str(e),
            ) from e


def _process_duplicate_group(
    duplicate_files: list[Path],
    mapping_dict: dict[Path, tuple[Path, Path, list[Path]]],
    files_to_keep: set[Path],
) -> None:
    """Process a group of duplicate files - keep first, delete rest."""
    keep_file = duplicate_files[0]
    files_to_keep.add(keep_file)

    for dup_path in duplicate_files[1:]:
        # Get mapping for this duplicate
        dup_mapping = mapping_dict.get(dup_path)
        if not dup_mapping:
            continue

        source_path, _, sidecar_paths = dup_mapping

        # Delete the duplicate image
        _delete_duplicate_file(dup_path)

        # Delete the source image and its sidecars (since it's a duplicate)
        AppleSidecarManager.delete_image_with_sidecars(source_path)

        # Delete temp sidecars
        _delete_sidecars(sidecar_paths)


def remove_duplicates(
    mappings: list[tuple[Path, Path, list[Path]]],
    deduplicator: Deduplicator,
) -> list[tuple[Path, Path, list[Path]]]:
    """
    Remove byte-identical files from staged temps.

    Groups files by content hash and keeps only the first of each group.
    Deletes duplicate images from filesystem. Sidecars are handled separately
    via their association with the main image in mappings.

    Args:
        mappings: List of (source_path, temp_image_path, temp_sidecar_paths)
        deduplicator: Deduplicator instance implementing group_by_hash()

    Returns:
        Filtered mappings list with duplicates removed

    Raises:
        PorterOperationFailedError: If hashing fails for any file
        PorterFileOperationError: If deletion of a duplicate file fails
    """
    if not mappings:
        return mappings

    # Extract temp file paths for hashing
    temp_files = [mapping[1] for mapping in mappings]

    # Group by content hash
    try:
        hash_groups = deduplicator.group_by_hash(temp_files)
    except Exception as e:
        raise PorterOperationFailedError(
            f'Failed to compute file hashes for deduplication: {e}',
            error_detail=str(e),
        ) from e

    # Build lookup dictionary for mappings
    mapping_dict = {mapping[1]: mapping for mapping in mappings}
    files_to_keep = set()

    # Process each hash group
    for duplicate_files in hash_groups.values():
        if len(duplicate_files) == 1:
            # Unique file - keep it
            files_to_keep.add(duplicate_files[0])
        else:
            # Multiple copies - process as duplicates
            _process_duplicate_group(duplicate_files, mapping_dict, files_to_keep)

    # Return only mappings for kept files
    return [mapping_dict[f] for f in files_to_keep]
