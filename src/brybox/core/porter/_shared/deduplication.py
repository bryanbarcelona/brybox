from __future__ import annotations

from pathlib import Path

from ....events.bus import publish_file_deleted
from ....utils.apple_files import AppleSidecarManager
from ....utils.logging import log_and_display
from .protocols import Deduplicator, PorterResult


def _remove_duplicates(
    mappings: list[tuple[Path, Path, list[Path]]],
    deduplicator: Deduplicator,
    dry_run: bool,
    action_prefix: str,
    result: PorterResult,
) -> list[tuple[Path, Path, list[Path]]]:
    """
    Remove byte-identical files from staged temps (Phase 2a).

    Groups files by content hash and keeps only the first of each group.
    Deletes duplicate images and their sidecars.

    Args:
        mappings: List of (source_path, temp_image_path, temp_sidecar_paths)
        deduplicator: Deduplicator instance implementing group_by_hash()
        dry_run: Simulation mode
        action_prefix: Logging prefix
        result: PushResult to update with stats

    Returns:
        Filtered mappings list with duplicates removed
    """
    if not mappings:
        return mappings

    # Extract temp file paths for hashing
    temp_files = [mapping[1] for mapping in mappings]

    # Group by content hash
    hash_groups = deduplicator.group_by_hash(temp_files)

    # Track which temp files to keep
    files_to_keep = set()

    for hash_value, duplicate_files in hash_groups.items():
        if len(duplicate_files) == 1:
            # Unique file - keep it
            files_to_keep.add(duplicate_files[0])
        else:
            # Multiple copies - keep first, delete rest
            keep_file = duplicate_files[0]
            files_to_keep.add(keep_file)

            for dup_path in duplicate_files[1:]:
                if dry_run:
                    log_and_display(f'{action_prefix} Would delete duplicate: {dup_path.name}', log=False)
                else:
                    # Find the mapping for this duplicate
                    dup_mapping = next((m for m in mappings if m[1] == dup_path), None)

                    if dup_mapping is None:
                        log_and_display(
                            f'Internal error: No mapping found for duplicate {dup_path.name}', level='error'
                        )
                        result.failed += 1
                        continue

                    source_path = dup_mapping[0]

                    try:
                        # Delete duplicate image
                        dupfile_size = dup_path.stat().st_size
                        dup_path.unlink()
                        publish_file_deleted(file_path=str(dup_path), file_size=dupfile_size)

                        # Also delete the source since this is a duplicate
                        AppleSidecarManager.delete_image_with_sidecars(source_path)

                        # Delete its sidecars
                        for sidecar in dup_mapping[2]:
                            if sidecar.exists():
                                sidecar_size = sidecar.stat().st_size
                                sidecar.unlink()
                                publish_file_deleted(file_path=str(sidecar), file_size=sidecar_size)

                        log_and_display(f'Deleted duplicate: {dup_path.name}')

                    except OSError as e:
                        log_and_display(f'Failed to delete duplicate {dup_path.name}: {e}', level='error')
                        result.failed += 1
                        continue

                    result.duplicates_removed += 1

    # Return only mappings for kept files
    kept_mappings = [m for m in mappings if m[1] in files_to_keep]

    if result.duplicates_removed > 0:
        log_and_display(f'{action_prefix} Removed {result.duplicates_removed} duplicate(s)')

    return kept_mappings
