"""PixelPorter - Photo ingestion and processing orchestrator."""

from pathlib import Path
from typing import Optional, Dict, Any

from ...utils.config_loader import ConfigLoader
from ...utils.logging import log_and_display, get_configured_logger
from .protocols import FileProcessor, Deduplicator
from .staging import _stage_files_to_target
from .deduplication import _remove_duplicates
from .timestamps import _fix_overlapping_timestamps
from .processing import _process_and_cleanup

logger = get_configured_logger("PixelPorter")

class PushResult:
    """Result of push_photos operation."""
    def __init__(self):
        self.processed = 0
        self.skipped = 0
        self.failed = 0
        self.duplicates_removed = 0
        self.errors: list[str] = []

def _load_pixelporter_config(
    config_path: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """Load PixelPorter configuration."""
    if config is not None:
        return config
    
    config_path = config_path or "configs"
    return ConfigLoader.load_configs(
        config_path=config_path,
        config_files={"paths": "pixelporter_paths.json"}
    )

def _get_default_processor():
    """Lazy-load SnapJedi adapter as default processor."""
    try:
        # from .adapters import SnapJediAdapter
        # return SnapJediAdapter
        from ..snap_jedi import SnapJedi
        return SnapJedi
    except ImportError:
        logger.warning("SnapJedi not available, files will be moved as-is")
        return None

def _get_default_deduplicator():
    """Lazy-load HashDeduplicator as default."""
    try:
        from ...utils.deduplicator import HashDeduplicator
        return HashDeduplicator()
    except ImportError:
        logger.warning("HashDeduplicator not available, deduplication disabled")
        return None
    

def push_photos(
    source: Optional[Path] = None,
    target: Optional[Path] = None,
    config_path: Optional[str] = None,
    config: Optional[Dict] = None,
    processor_class: Optional[type[FileProcessor]] | bool = None,
    deduplicator: Optional[Deduplicator] | bool = None,
    migrate_sidecars: bool = True,
    ensure_unique_timestamps: bool = True,
    dry_run: bool = False
) -> PushResult:
    action_prefix = "[DRY RUN]" if dry_run else "[ACTION]"
    
    # Load config if paths not provided
    if source is None or target is None:
        loaded_config = _load_pixelporter_config(config_path, config)
        paths = loaded_config.get("paths", {})
        source = source or paths.get("source_folder")
        target = target or paths.get("target_folder")
        
        if not source or not target:
            raise ValueError("Source and target must be provided via args or config")
        
        source = Path(source)
        target = Path(target)
    
    # Validate source exists
    if not source.exists():
        msg = f"Source folder does not exist: {source}"
        log_and_display(f"❌ {action_prefix} {msg}", level="error")
        raise FileNotFoundError(msg)
    
    log_and_display(f"{action_prefix} Processing photos from '{source}' → '{target}'")
    
    # Create target directory
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
    
    # ------------------------------------------------------------------
    # TODO: Replace overloaded processor_class with keyword-only
    #       run_processor: bool = True
    #       processor: type[FileProcessor] | None = None
    #       in next major version to remove union-with-bool.
    # ------------------------------------------------------------------
    if processor_class is True:
        processor_class = _get_default_processor()
    elif processor_class is False:
        processor_class = None
    elif processor_class is None:
        processor_class = _get_default_processor()

    # ------------------------------------------------------------------
    # TODO: Replace overloaded deduplicator with keyword-only
    #       run_deduplication: bool = True
    #       deduplicator: Deduplicator | None = None
    #       in next major version to remove union-with-bool.
    # ------------------------------------------------------------------
    if deduplicator is True:
        deduplicator = _get_default_deduplicator()
    elif deduplicator is False:
        deduplicator = None
    elif deduplicator is None:
        deduplicator = _get_default_deduplicator()

    result = PushResult()
    
    # Phase 1: Copy with temp names
    mappings = _stage_files_to_target(source, target, migrate_sidecars, dry_run, action_prefix)
    
    # Phase 2a: Deduplication (if enabled)
    if deduplicator:
        mappings = _remove_duplicates(mappings, deduplicator, dry_run, action_prefix, result)
    
    # Phase 2b: Timestamp uniqueness (if enabled)
    if ensure_unique_timestamps:
        _fix_overlapping_timestamps(mappings, dry_run, action_prefix)
    
    # Phase 3: Process and cleanup (if processor provided)
    if processor_class:
        _process_and_cleanup(mappings, processor_class, dry_run, action_prefix, result)
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