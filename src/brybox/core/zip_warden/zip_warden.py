"""
ZipWarden — archive extraction and staging-area normalisation.

Public API:
    ZipWarden      — expands a single ZIP archive into a target directory.
    ZipWardenNexus — expands all ZIP archives found in a directory (in-place).
"""

from pathlib import Path

from brybox.core.zip_warden.extractor import expand_single_archive
from brybox.core.zip_warden.models import ZipWardenResult
from brybox.exceptions.archives import ZipWardenConfigurationError, ZipWardenError
from brybox.utils.logging import get_configured_logger, log_and_display

logger = get_configured_logger('ZipWarden')

_ZIP_EXTENSIONS: frozenset[str] = frozenset({'.zip', '.ZIP'})


class ZipWarden:
    """
    Expand a single ZIP archive into a target directory.

    Validates archive integrity, extracts all members, flattens nested
    directory structure, verifies every extracted file, then deletes the
    source archive — in that strict order.  The source is never deleted
    unless every prior step succeeds.

    Args:
        archive_path:   Path to the ZIP file to expand.
        target_dir:     Directory that receives the extracted files.
                        Defaults to the archive's parent directory (in-place).
        flatten_nested: Collapse subdirectory structure so all files land
                        directly in target_dir.  Default: True.
        delete_archive: Remove the source ZIP after successful extraction.
                        Default: True.
        dry_run:        Log what would happen without performing any I/O.

    Raises:
        ZipWardenConfigurationError: If archive_path does not exist or
                                     target_dir cannot be created.

    Example:
        result = ZipWarden(
            archive_path=Path('staging/bank_docs.zip'),
        ).expand()
        print(f'Extracted {result.files_extracted} file(s)')
    """

    def __init__(
        self,
        archive_path: Path,
        target_dir: Path | None = None,
        *,
        flatten_nested: bool = True,
        delete_archive: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.archive_path = Path(archive_path)
        self.target_dir = Path(target_dir) if target_dir else self.archive_path.parent
        self.flatten_nested = flatten_nested
        self.delete_archive = delete_archive
        self.dry_run = dry_run

    def expand(self) -> ZipWardenResult:
        """
        Expand the archive and return a populated ZipWardenResult.

        Returns:
            ZipWardenResult with counts for this single archive operation.

        Raises:
            ZipWardenConfigurationError:  archive_path missing or unreadable.
            ZipWardenCorruptArchiveError: Not a valid ZIP.
            ZipWardenExtractionError:     Extraction or validation failed.
            ZipWardenFileOperationError:  Move or delete I/O failed.
        """
        if not self.archive_path.exists():
            raise ZipWardenConfigurationError(
                f'Archive not found: {self.archive_path}',
                archive_path=self.archive_path,
            )

        if not self.dry_run:
            self.target_dir.mkdir(parents=True, exist_ok=True)

        return expand_single_archive(
            archive_path=self.archive_path,
            target_dir=self.target_dir,
            flatten_nested=self.flatten_nested,
            delete_archive=self.delete_archive,
            dry_run=self.dry_run,
        )


class ZipWardenNexus:
    """
    Expand all ZIP archives found in a directory, normalising it in-place.

    Scans dir_path for files with a .zip / .ZIP extension and expands each
    one sequentially.  Errors on individual archives are collected into the
    result rather than aborting the batch, so a single corrupt file does not
    prevent the remaining archives from being processed.

    This is the primary entry point in the pipeline, placed between the
    ingestion stage (e.g. InboxKraken) and type-specific consumers
    (DoctopusPrimeNexus, AudioraNexus, push_photos, etc.).

    Args:
        dir_path:       Directory to scan and normalise in-place.
        flatten_nested: Collapse subdirectory structure for every archive.
                        Default: True.
        delete_archives: Remove each source ZIP after successful extraction.
                        Default: True.
        dry_run:        Log what would happen without performing any I/O.

    Raises:
        ZipWardenConfigurationError: If dir_path does not exist.

    Example:
        # In first_run.py, after InboxKraken and before the Nexus consumers:
        result = ZipWardenNexus(dir_path=TEMP_DIR).expand()
        if result.failed:
            log_and_display(f'⚠️  {result.failed} archive(s) failed: {result.errors}')
    """

    def __init__(
        self,
        dir_path: Path,
        *,
        flatten_nested: bool = True,
        delete_archives: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.dir_path = Path(dir_path)
        self.flatten_nested = flatten_nested
        self.delete_archives = delete_archives
        self.dry_run = dry_run

    def expand(self) -> ZipWardenResult:
        """
        Expand all ZIP archives in dir_path and return aggregated results.

        Archives are processed sequentially.  A failure on one archive
        increments result.failed and appends to result.errors, but processing
        continues for the remaining archives.

        Returns:
            ZipWardenResult aggregated across all archives found.

        Raises:
            ZipWardenConfigurationError: If dir_path does not exist.
        """
        if not self.dir_path.exists():
            raise ZipWardenConfigurationError(
                f'Directory not found: {self.dir_path}',
                archive_path=None,
            )

        archives = [p for p in self.dir_path.iterdir() if p.is_file() and p.suffix in _ZIP_EXTENSIONS]

        if not archives:
            log_and_display(f'ZipWardenNexus: no archives found in {self.dir_path}', level='debug')
            return ZipWardenResult()

        action = '[DRY RUN]' if self.dry_run else '[ACTION]'
        log_and_display(f'{action} ZipWardenNexus: {len(archives)} archive(s) found in {self.dir_path}')

        total = ZipWardenResult()

        for archive_path in archives:
            try:
                result = expand_single_archive(
                    archive_path=archive_path,
                    target_dir=self.dir_path,
                    flatten_nested=self.flatten_nested,
                    delete_archive=self.delete_archives,
                    dry_run=self.dry_run,
                )
            except ZipWardenError as e:
                log_and_display(f'❌ Failed to expand {archive_path.name}: {e}', level='error')
                total.failed += 1
                total.errors.append(f'{archive_path.name}: {e}')
                continue

            total.expanded += result.expanded
            total.files_extracted += result.files_extracted
            total.dirs_flattened += result.dirs_flattened
            total.archives_deleted += result.archives_deleted

        log_and_display(
            f'{action} ZipWardenNexus summary: '
            f'expanded={total.expanded}, '
            f'files_extracted={total.files_extracted}, '
            f'archives_deleted={total.archives_deleted}, '
            f'failed={total.failed}'
        )

        return total
