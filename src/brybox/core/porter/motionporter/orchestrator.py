"""MotionPorter - Video ingestion and processing orchestrator."""

from pathlib import Path
from typing import Any

from brybox.core.porter.shared.file_filters import VideoFileFilter
from brybox.core.porter.shared.orchestration import run_porter_pipeline
from brybox.core.porter.shared.protocols import PorterResult
from brybox.utils.logging import get_configured_logger
from brybox.utils.settings import BryboxSettings

logger = get_configured_logger('MotionPorter')


def _get_default_processor() -> type | None:
    """Lazy-load VideoSith as default processor."""
    try:
        from brybox.core.videosith import VideoSith  # noqa: PLC0415

        return VideoSith
    except ImportError:
        logger.warning('VideoSith not available, files will be moved as-is')
        return None


def _get_default_deduplicator() -> Any | None:
    """Lazy-load HashDeduplicator as default."""
    try:
        from brybox.utils.deduplicator import HashDeduplicator  # noqa: PLC0415

        return HashDeduplicator()
    except ImportError:
        logger.warning('HashDeduplicator not available, deduplication disabled')
        return None


def push_videos(
    source: Path | None = None,
    target: Path | None = None,
    config: dict | None = None,
    processor_class: type | bool | None = None,
    deduplicator: Any | bool | None = None,
    *,
    migrate_sidecars: bool = True,
    dry_run: bool = False,
) -> PorterResult:
    """
    Process videos from source to target directory.

    Pipeline:
    1. Stage videos with temp names
    2. Remove duplicates (optional)
    3. Convert MOV→MP4 and rename by timestamp (optional)
    4. Cleanup source files
    """
    # Load config if paths not provided
    if source is None or target is None:
        loaded_config = config or BryboxSettings().motionporter
        paths = loaded_config.get('paths', {})
        source = source or paths.get('source_folder')
        target = target or paths.get('target_folder')

        if not source or not target:
            raise ValueError('Source and target must be provided via args or config')

        source = Path(source)
        target = Path(target)

    # Handle processor_class parameter
    if processor_class is True:
        processor_class = _get_default_processor()
    elif processor_class is False:
        processor_class = None
    elif processor_class is None:
        processor_class = _get_default_processor()

    # Handle deduplicator parameter
    if deduplicator is True:
        deduplicator = _get_default_deduplicator()
    elif deduplicator is False:
        deduplicator = None
    elif deduplicator is None:
        deduplicator = _get_default_deduplicator()

    # Setup video-specific components
    file_filter = VideoFileFilter()

    # Run generic porter pipeline (no metadata_fixer for videos)
    return run_porter_pipeline(
        source=source,
        target=target,
        file_filter=file_filter,
        processor_class=processor_class,
        deduplicator=deduplicator,
        metadata_fixer=None,  # Videos don't need timestamp fixing yet
        migrate_sidecars=migrate_sidecars,
        dry_run=dry_run,
    )
