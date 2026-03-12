"""PixelPorter - Photo ingestion and processing orchestrator."""

from pathlib import Path
from typing import Any

from brybox.core.porter.shared.file_filters import ImageFileFilter
from brybox.core.porter.shared.metadata_fixers import ExifTimestampFixer
from brybox.core.porter.shared.orchestration import run_porter_pipeline
from brybox.core.porter.shared.protocols import PorterResult
from brybox.utils.logging import get_configured_logger, log_and_display
from brybox.utils.settings import BryboxSettings

logger = get_configured_logger('PixelPorter')


def _get_default_processor() -> type | None:
    """Lazy-load SnapJedi as default processor."""
    try:
        from brybox.core.snap_jedi.snapjedi import SnapJedi  # noqa: PLC0415

    except ImportError:
        log_and_display('SnapJedi not available, files will be moved as-is', level='warning')
        return None
    else:
        return SnapJedi


def _get_default_deduplicator() -> Any | None:
    """Lazy-load HashDeduplicator as default."""
    try:
        from brybox.utils.deduplicator import HashDeduplicator  # noqa: PLC0415

        return HashDeduplicator()
    except ImportError:
        log_and_display('HashDeduplicator not available, deduplication disabled', level='warning')
        return None


def push_photos(
    source: Path | None = None,
    target: Path | None = None,
    config: dict | None = None,
    processor_class: type | bool | None = None,
    deduplicator: Any | bool | None = None,
    *,
    migrate_sidecars: bool = True,
    ensure_unique_timestamps: bool = True,
    dry_run: bool = False,
) -> PorterResult:
    """
    Process photos from source to target directory.

    Pipeline:
    1. Stage photos with temp names
    2. Remove duplicates (optional)
    3. Fix EXIF timestamp collisions (optional)
    4. Convert HEIC→JPG and rename by timestamp (optional)
    5. Cleanup source files

    Args:
        source: Source directory path
        target: Target directory path
        config_path: Path to config directory (alternative to source/target)
        config: Config dict (alternative to config_path)
        processor_class: FileProcessor class (True=SnapJedi, False=None, None=SnapJedi)
        deduplicator: Deduplicator instance (True=default, False=None, None=default)
        migrate_sidecars: Copy sidecar files (.AAE, .xmp, etc.)
        ensure_unique_timestamps: Fix EXIF timestamp collisions
        dry_run: Simulation mode (no actual changes)

    Returns:
        PorterResult with operation statistics

    Raises:
        FileNotFoundError: If source doesn't exist
        ValueError: If source/target not provided and not in config
    """
    # Load config if paths not provided
    if source is None or target is None:
        loaded_config = config or BryboxSettings().pixelporter
        paths = loaded_config.get('paths', {})
        source = source or paths.get('source_folder')
        target = target or paths.get('target_folder')

        if not source or not target:
            raise ValueError('Source and target must be provided via args or config')

        source = Path(source)
        target = Path(target)

    # Handle processor_class parameter (backward compatibility)
    if processor_class is True:
        processor_class = _get_default_processor()
    elif processor_class is False:
        processor_class = None
    elif processor_class is None:
        processor_class = _get_default_processor()

    # Handle deduplicator parameter (backward compatibility)
    if deduplicator is True:
        deduplicator = _get_default_deduplicator()
    elif deduplicator is False:
        deduplicator = None
    elif deduplicator is None:
        deduplicator = _get_default_deduplicator()

    # Setup photo-specific components
    file_filter = ImageFileFilter()
    metadata_fixer = ExifTimestampFixer() if ensure_unique_timestamps else None

    # Run generic porter pipeline
    return run_porter_pipeline(
        source=source,
        target=target,
        file_filter=file_filter,
        processor_class=processor_class,
        deduplicator=deduplicator,
        metadata_fixer=metadata_fixer,
        migrate_sidecars=migrate_sidecars,
        dry_run=dry_run,
    )
