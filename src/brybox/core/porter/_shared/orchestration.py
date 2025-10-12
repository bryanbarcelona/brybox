"""Generic porter pipeline orchestration."""

from pathlib import Path
from typing import Optional

from ....utils.logging import log_and_display, get_configured_logger
from .protocols import FileProcessor, Deduplicator, FileFilter, MetadataFixer, PorterResult
from .staging import _stage_files_to_target
from .deduplication import _remove_duplicates
from .processing import _process_and_cleanup

logger = get_configured_logger("Porter")


def run_porter_pipeline(
    source: Path,
    target: Path,
    file_filter: FileFilter,
    processor_class: Optional[type[FileProcessor]],
    deduplicator: Optional[Deduplicator] = None,
    metadata_fixer: Optional[MetadataFixer] = None,
    migrate_sidecars: bool = True,
    dry_run: bool = False
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
        FileNotFoundError: If source directory doesn't exist
        ValueError: If source or target paths are invalid
    """
    action_prefix = "[DRY RUN]" if dry_run else "[ACTION]"
    
    # Validate source exists
    if not source.exists():
        msg = f"Source folder does not exist: {source}"
        log_and_display(f"❌ {action_prefix} {msg}", level="error")
        raise FileNotFoundError(msg)
    
    if target.resolve().is_relative_to(source.resolve()):
        msg = f"Target cannot be inside source: {target} is within {source}"
        log_and_display(f"❌ {action_prefix} {msg}", level="error")
        raise ValueError(msg)

    log_and_display(f"{action_prefix} Processing files from '{source}' → '{target}'")
    
    # Create target directory
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
    
    result = PorterResult()
    
    # Phase 1: Stage files with temp names
    mappings = _stage_files_to_target(
        source, 
        target, 
        file_filter,
        migrate_sidecars, 
        dry_run, 
        action_prefix
    )
    
    # Phase 2a: Deduplication (if enabled)
    if deduplicator:
        mappings = _remove_duplicates(
            mappings, 
            deduplicator, 
            dry_run, 
            action_prefix, 
            result
        )
    
    # Phase 2b: Metadata fixes (if enabled)
    if metadata_fixer:
        metadata_fixer.fix_metadata(mappings, dry_run, action_prefix)
    
    # Phase 3: Process and cleanup (if processor provided)
    if processor_class:
        _process_and_cleanup(
            mappings, 
            processor_class, 
            dry_run, 
            action_prefix, 
            result
        )
    else:
        log_and_display(
            f"{action_prefix} No processor provided, files remain staged with temp names",
            log=False
        )
    
    # Summary
    log_and_display(
        f"\n{action_prefix} ✅ Summary: "
        f"Processed: {result.processed}, "
        f"Duplicates removed: {result.duplicates_removed}, "
        f"Failed: {result.failed}"
    )

    if result.failed > 0:
        log_and_display(f"⚠️  {result.failed} error(s) occurred:", level="warning")
        for error in result.errors[:5]:  # Show first 5 errors
            log_and_display(f"  - {error}", level="warning")
        if len(result.errors) > 5:
            log_and_display(f"  ... and {len(result.errors) - 5} more", level="warning")

    if dry_run:
        log_and_display("💡 Run with dry_run=False to apply changes.")

    return result