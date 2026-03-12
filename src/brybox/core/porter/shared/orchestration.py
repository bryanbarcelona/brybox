from collections.abc import Callable
from pathlib import Path
from typing import Any

from brybox.core.porter.shared.deduplication import remove_duplicates
from brybox.core.porter.shared.processing import process_and_cleanup
from brybox.core.porter.shared.protocols import Deduplicator, FileFilter, FileProcessor, MetadataFixer, PorterResult
from brybox.core.porter.shared.staging import stage_files_to_target
from brybox.exceptions.base import BryboxError
from brybox.exceptions.transfers import (
    PorterConfigurationError,
    PorterError,
    PorterResourceNotFoundError,
)
from brybox.utils.logging import get_configured_logger, log_and_display

logger = get_configured_logger('Porter')


def _run_phase(
    phase_name: str,
    phase_func: Callable[..., Any],
    result: PorterResult,
    *,
    fatal: bool = False,
    **kwargs: Any,
) -> tuple[bool, Any]:
    """
    Run a pipeline phase with consistent error handling.

    Args:
        phase_name: Name of the phase for logging
        phase_func: Function to execute
        result: PorterResult to update on failure
        fatal: If True, raise on failure instead of returning (False, None)
        **kwargs: Arguments to pass to phase_func

    Returns:
        Tuple of (success, return_value). return_value is None if phase failed.
    """
    try:
        result_value = phase_func(**kwargs)
    except PorterError as e:
        log_and_display(f'❌ {phase_name} failed: {e}', level='error')
        result.failed += 1
        result.errors.append(str(e))
        if fatal:
            raise
        return False, None
    except Exception as e:
        log_and_display(f'❌ Unexpected error during {phase_name}: {e}', level='error')
        result.failed += 1
        result.errors.append(f'Unexpected: {e}')
        if fatal:
            raise
        return False, None
    else:
        return True, result_value


def _validate_paths(source: Path, target: Path, action_prefix: str) -> None:
    """Validate source and target paths. Raises fatal errors."""
    if not source.exists():
        msg = f'Source folder does not exist: {source}'
        log_and_display(f'❌ {action_prefix} {msg}', level='error')
        raise PorterResourceNotFoundError(msg, resource_path=source)
    if target.resolve().is_relative_to(source.resolve()):
        msg = f'Target cannot be inside source: {target} is within {source}'
        log_and_display(f'❌ {action_prefix} {msg}', level='error')
        raise PorterConfigurationError(msg, config_key='paths.target_folder')


def _run_dry_run_staging(source: Path, file_filter: FileFilter, action_prefix: str) -> list:
    """Simulate staging for dry run."""
    mappings = []
    for file_path in source.iterdir():
        if not file_path.is_file() or not file_filter.is_valid(file_path):
            continue
        log_and_display(f'{action_prefix} Would stage: {file_path.name}')
        mappings.append((file_path, file_path))
    return mappings


def _run_dry_run_deduplication(mappings: list, deduplicator: Deduplicator, action_prefix: str) -> None:
    """Simulate deduplication for dry run."""
    temp_files = [m[1] for m in mappings]
    hash_groups = deduplicator.group_by_hash(temp_files)
    duplicate_count = sum(len(files) - 1 for files in hash_groups.values())
    log_and_display(f'{action_prefix} Would remove {duplicate_count} duplicate(s)')


def _run_dry_run_metadata(action_prefix: str) -> None:
    """Simulate metadata fixes for dry run."""
    log_and_display(f'{action_prefix} Timestamp uniqueness check: Skipped in dry-run mode', log=False)
    log_and_display(
        f'{action_prefix} Note: Adjustments are deterministic and safe (+1 second for collisions)', log=False
    )


def _run_dry_run_processing(mappings: list, action_prefix: str) -> None:
    """Simulate processing for dry run."""
    log_and_display(f'{action_prefix} Processing: Skipped (runs on staged files only)', log=False)
    log_and_display(f'{action_prefix} Would process {len(mappings)} file(s) with processor', log=False)


def _run_staging_phase(
    source: Path,
    target: Path,
    file_filter: FileFilter,
    *,
    migrate_sidecars: bool = True,
    dry_run: bool = False,
    action_prefix: str = '',
    result: PorterResult | None = None,
) -> tuple[bool, list]:
    """Run staging phase with proper error handling."""
    if result is None:
        result = PorterResult()
    if dry_run:
        return True, _run_dry_run_staging(source, file_filter, action_prefix)
    return _run_phase(
        'Staging',
        stage_files_to_target,
        result,
        fatal=False,
        source=source,
        target=target,
        file_filter=file_filter,
        migrate_sidecars=migrate_sidecars,
    )


def _run_deduplication_phase(
    mappings: list,
    deduplicator: Deduplicator | None,
    *,
    dry_run: bool = False,
    action_prefix: str = '',
    result: PorterResult | None = None,
) -> tuple[bool, list]:
    """Run deduplication phase with proper error handling."""
    if result is None:
        result = PorterResult()
    if not deduplicator:
        return True, mappings
    if dry_run:
        _run_dry_run_deduplication(mappings, deduplicator, action_prefix)
        return True, mappings

    original_count = len(mappings)
    success, new_mappings = _run_phase(
        'Deduplication',
        remove_duplicates,
        result,
        fatal=False,
        mappings=mappings,
        deduplicator=deduplicator,
    )

    if success:
        result.duplicates_removed = original_count - len(new_mappings)
        if result.duplicates_removed > 0:
            log_and_display(f'{action_prefix} Removed {result.duplicates_removed} duplicate(s)')
        return True, new_mappings

    return False, mappings


def _run_metadata_phase(
    mappings: list,
    metadata_fixer: MetadataFixer | None,
    *,
    dry_run: bool = False,
    action_prefix: str = '',
    result: PorterResult | None = None,
) -> None:
    """Run metadata fix phase with proper error handling."""
    if result is None:
        result = PorterResult()
    if not metadata_fixer:
        return
    if dry_run:
        _run_dry_run_metadata(action_prefix)
        return

    success, adjustments = _run_phase(
        'Metadata fix',
        metadata_fixer.fix_metadata,
        result,
        fatal=False,
        mappings=mappings,
    )

    if success and adjustments > 0:
        log_and_display(f'{action_prefix} Adjusted {adjustments} timestamp collision(s)')


def _run_processing_phase(
    mappings: list,
    processor_class: type[FileProcessor] | None,
    *,
    dry_run: bool = False,
    action_prefix: str = '',
    result: PorterResult | None = None,
) -> None:
    """Run processing phase with proper error handling."""
    if result is None:
        result = PorterResult()
    if not processor_class:
        log_and_display(f'{action_prefix} No processor provided, files remain staged with temp names', log=False)
        return
    if dry_run:
        _run_dry_run_processing(mappings, action_prefix)
        return

    try:
        process_and_cleanup(mappings, processor_class, dry_run, action_prefix, result)
    except BryboxError as e:
        log_and_display(f'❌ Processing phase failed: {e}', level='error')
        result.failed += 1
        result.errors.append(str(e))
    except Exception as e:  # noqa: BLE001
        log_and_display(f'❌ Unexpected error during processing phase: {e}', level='error')
        result.failed += 1
        result.errors.append(f'Unexpected: {e}')


def _log_summary(result: PorterResult, action_prefix: str, dry_run: bool) -> None:
    """Log final summary."""
    log_and_display(
        f'\n{action_prefix} ✅ Summary: '
        f'Processed: {result.processed}, '
        f'Duplicates removed: {result.duplicates_removed}, '
        f'Failed: {result.failed}'
    )
    if result.failed > 0:
        log_and_display(f'⚠️  {result.failed} error(s) occurred:', level='warning')
        for error in result.errors[:5]:
            log_and_display(f'  - {error}', level='warning')
        if len(result.errors) > 5:
            log_and_display(f'  ... and {len(result.errors) - 5} more', level='warning')

    if dry_run:
        log_and_display('💡 Run with dry_run=False to apply changes.')


def run_porter_pipeline(
    source: Path,
    target: Path,
    file_filter: FileFilter,
    *,
    processor_class: type[FileProcessor] | None = None,
    deduplicator: Deduplicator | None = None,
    metadata_fixer: MetadataFixer | None = None,
    migrate_sidecars: bool = True,
    dry_run: bool = False,
) -> PorterResult:
    """
    Execute generic porter pipeline.

    Pipeline phases:
    1. Stage: Copy files to target with temp names
    2a. Deduplicate: Remove byte-identical files (optional)
    2b. Fix metadata: Adjust metadata to prevent collisions (optional)
    3. Process: Convert/rename files and cleanup sources (optional)

    Args:
        source: Source directory containing files
        target: Target directory for processed files
        file_filter: FileFilter implementation for file type validation
        processor_class: FileProcessor implementation (None = skip processing)
        deduplicator: Deduplicator implementation (None = skip deduplication)
        metadata_fixer: MetadataFixer implementation (None = skip metadata fixes)
        migrate_sidecars: Whether to copy sidecar files alongside main files
        dry_run: Simulation mode (no actual file operations)

    Returns:
        PorterResult with operation statistics

    Raises:
        PorterResourceNotFoundError: If source directory doesn't exist
        PorterConfigurationError: If source or target paths are invalid
    """
    action_prefix = '[DRY RUN]' if dry_run else '[ACTION]'

    _validate_paths(source, target, action_prefix)

    log_and_display(f"{action_prefix} Processing files from '{source}' → '{target}'")

    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)

    result = PorterResult()

    # Phase 1: Stage files
    success, mappings = _run_staging_phase(
        source,
        target,
        file_filter,
        migrate_sidecars=migrate_sidecars,
        dry_run=dry_run,
        action_prefix=action_prefix,
        result=result,
    )
    if not success:
        return result

    # Phase 2a: Deduplication
    success, mappings = _run_deduplication_phase(
        mappings,
        deduplicator,
        dry_run=dry_run,
        action_prefix=action_prefix,
        result=result,
    )

    # Phase 2b: Metadata fixes
    _run_metadata_phase(
        mappings,
        metadata_fixer,
        dry_run=dry_run,
        action_prefix=action_prefix,
        result=result,
    )

    # Phase 3: Process and cleanup
    _run_processing_phase(
        mappings,
        processor_class,
        dry_run=dry_run,
        action_prefix=action_prefix,
        result=result,
    )

    # Summary
    _log_summary(result, action_prefix, dry_run)

    return result
