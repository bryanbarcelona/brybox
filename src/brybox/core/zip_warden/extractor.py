"""Single-archive extraction, flattening, validation, and cleanup logic."""

import secrets
import shutil
import zipfile
from pathlib import Path

from brybox.core.zip_warden.models import ZipWardenResult
from brybox.events.bus import publish_file_added, publish_file_deleted
from brybox.exceptions.archives import (
    ZipWardenCorruptArchiveError,
    ZipWardenExtractionError,
    ZipWardenFileOperationError,
)
from brybox.utils.health_check import is_healthy
from brybox.utils.logging import log_and_display
from brybox.utils.naming import resolve_filename_conflict

_TEMP_PREFIX = '._zw_'


def _temp_subdir(target_dir: Path) -> Path:
    """Generate a unique hidden temp subdirectory path inside target_dir."""
    token = secrets.token_hex(8)
    return target_dir / f'{_TEMP_PREFIX}{token}'


def _validate_archive(archive_path: Path) -> list[zipfile.ZipInfo]:
    """
    Open and validate a ZIP archive.

    Returns the member list on success.

    Raises:
        ZipWardenCorruptArchiveError: If the path is not a valid ZIP.
    """
    if not zipfile.is_zipfile(archive_path):
        raise ZipWardenCorruptArchiveError(
            f'Not a valid ZIP file: {archive_path.name}',
            archive_path=archive_path,
        )
    with zipfile.ZipFile(archive_path, 'r') as zf:
        return zf.infolist()


def _extract_to_temp(archive_path: Path, temp_dir: Path) -> None:
    """
    Extract all archive members into temp_dir.

    Raises:
        ZipWardenExtractionError: If extraction raises any zipfile exception.
    """
    try:
        with zipfile.ZipFile(archive_path, 'r') as zf:
            zf.extractall(temp_dir)
    except zipfile.BadZipFile as e:
        raise ZipWardenExtractionError(
            f'Extraction failed for {archive_path.name}: {e}',
            archive_path=archive_path,
        ) from e
    except OSError as e:
        raise ZipWardenExtractionError(
            f'I/O error extracting {archive_path.name}: {e}',
            archive_path=archive_path,
        ) from e


def _validate_extracted_files(temp_dir: Path, archive_path: Path) -> list[Path]:
    """
    Collect all extracted files and verify each exists with non-zero size.

    Returns the flat list of file paths found anywhere under temp_dir.

    Raises:
        ZipWardenExtractionError: If any file is missing or zero-byte.
    """
    extracted = [p for p in temp_dir.rglob('*') if p.is_file()]

    for file_path in extracted:
        if not file_path.exists():
            raise ZipWardenExtractionError(
                f'Extracted file missing: {file_path.name}',
                archive_path=archive_path,
                member=file_path.name,
            )
        if file_path.stat().st_size == 0:
            raise ZipWardenExtractionError(
                f'Extracted file is zero-byte: {file_path.name}',
                archive_path=archive_path,
                member=file_path.name,
            )

    return extracted


def _count_nested_dirs(temp_dir: Path) -> int:
    """Count subdirectory levels that will be collapsed by flattening."""
    return sum(1 for p in temp_dir.rglob('*') if p.is_dir())


def _move_files_to_target(
    files: list[Path],
    target_dir: Path,
    archive_path: Path,
) -> int:
    """
    Move files into target_dir, resolving name conflicts with (1), (2) suffixes.

    Returns the number of files successfully moved.

    Raises:
        ZipWardenFileOperationError: If a move fails.
    """
    moved = 0
    for file_path in files:
        destination = resolve_filename_conflict(target_dir / file_path.name)
        try:
            shutil.move(str(file_path), destination)
        except OSError as e:
            raise ZipWardenFileOperationError(
                f'Failed to move extracted file {file_path.name} to {destination}: {e}',
                archive_path=archive_path,
                source_path=file_path,
                dest_path=destination,
            ) from e

        publish_file_added(
            file_path=destination,
            file_size=destination.stat().st_size,
            is_healthy=is_healthy(destination),
        )
        moved += 1

    return moved


def _delete_archive(archive_path: Path) -> None:
    """
    Delete the source ZIP and emit FileDeletedEvent.

    Raises:
        ZipWardenFileOperationError: If deletion fails.
    """
    archive_size = archive_path.stat().st_size
    try:
        archive_path.unlink()
    except OSError as e:
        raise ZipWardenFileOperationError(
            f'Failed to delete source archive {archive_path.name}: {e}',
            archive_path=archive_path,
        ) from e

    publish_file_deleted(file_path=archive_path, file_size=archive_size)


def expand_single_archive(
    archive_path: Path,
    target_dir: Path,
    *,
    flatten_nested: bool = True,
    delete_archive: bool = True,
    dry_run: bool = False,
) -> ZipWardenResult:
    """
    Extract, flatten, validate, and optionally delete a single ZIP archive.

    Implements a strict transactional ordering — the source archive is only
    deleted after every extracted file has been validated and placed in
    target_dir.  If any step fails the archive remains untouched.

    Pipeline:
        1. Validate: confirm the path is a well-formed ZIP (zipfile.is_zipfile).
        2. Extract:  unpack all members into an isolated hidden temp subdirectory.
        3. Validate: verify every extracted file exists with non-zero size.
        4. Flatten:  move all files from temp subdir into target_dir, resolving
                     name collisions via (1), (2) suffixes.
        5. Publish:  emit FileAddedEvent per placed file.
        6. Cleanup:  remove the temp subdir.
        7. Delete:   unlink the source ZIP (if delete_archive=True).
        8. Publish:  emit FileDeletedEvent for the removed archive.

    Args:
        archive_path:   Path to the ZIP file to expand.
        target_dir:     Directory where extracted files will land.
        flatten_nested: Collapse all subdirectory structure so every file lands
                        directly in target_dir.  Always True for this pipeline.
        delete_archive: Remove the source ZIP after successful extraction.
        dry_run:        Log intended operations without performing any I/O.

    Returns:
        ZipWardenResult populated with counts for this single archive.

    Raises:
        ZipWardenCorruptArchiveError:  Archive is not a valid ZIP file.
        ZipWardenExtractionError:      Extraction or post-extraction validation failed.
        ZipWardenFileOperationError:   A filesystem move or delete operation failed.

    Example:
        result = expand_single_archive(
            archive_path=Path('staging/bank_docs.zip'),
            target_dir=Path('staging'),
            delete_archive=True,
        )
        print(f'Extracted {result.files_extracted} files')
    """
    action = '[DRY RUN]' if dry_run else '[ACTION]'
    result = ZipWardenResult()

    members = _validate_archive(archive_path)

    if not members:
        log_and_display(f'{action} Skipping empty archive: {archive_path.name}', level='warning')
        return result

    file_members = [m for m in members if not m.is_dir()]
    dirs_in_zip = _count_dirs_in_members(members)

    log_and_display(
        f'{action} ZipWarden: expanding {archive_path.name} ({len(file_members)} file(s), {dirs_in_zip} nested dir(s))'
    )

    if dry_run:
        for member in file_members:
            log_and_display(f'{action}   Would extract: {member.filename}')
        if delete_archive:
            log_and_display(f'{action}   Would delete archive: {archive_path.name}')
        result.expanded += 1
        result.files_extracted += len(file_members)
        result.dirs_flattened += dirs_in_zip
        return result

    temp_dir = _temp_subdir(target_dir)
    temp_dir.mkdir(parents=True)

    try:
        _extract_to_temp(archive_path, temp_dir)
        extracted_files = _validate_extracted_files(temp_dir, archive_path)
        dirs_flattened = _count_nested_dirs(temp_dir) if flatten_nested else 0
        moved = _move_files_to_target(extracted_files, target_dir, archive_path)
    finally:
        # Always clean up temp dir, whether we succeed or fail
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    result.expanded += 1
    result.files_extracted += moved
    result.dirs_flattened += dirs_flattened

    if delete_archive:
        _delete_archive(archive_path)
        result.archives_deleted += 1
        log_and_display(f'{action} ZipWarden: done - {archive_path.name} expanded ({moved} file(s)), archive deleted')
    else:
        log_and_display(f'{action} ZipWarden: done - {archive_path.name} expanded ({moved} file(s)), archive kept')

    return result


def _count_dirs_in_members(members: list[zipfile.ZipInfo]) -> int:
    """Count directory entries in a ZIP member list."""
    return sum(1 for m in members if m.is_dir())
