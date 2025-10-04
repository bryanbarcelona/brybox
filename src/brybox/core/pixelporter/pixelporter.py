"""PixelPorter - Photo ingestion and processing orchestrator."""

import logging
from pathlib import Path
from typing import Optional, Dict, Any
import time
import random
import string
import shutil

from ...utils.config_loader import ConfigLoader
from ...utils.logging import log_and_display, get_configured_logger
from ...events.bus import publish_file_moved, publish_file_deleted
from ...utils.apple_files import AppleSidecarManager
from .protocols import FileProcessor, Deduplicator, ProcessResult

logger = get_configured_logger("PixelPorter")


def _is_valid_image(file_path: Path) -> bool:
    """
    Check if file is a primary image asset (not system file or sidecar).
    
    Args:
        file_path: File to validate
        
    Returns:
        True if file is a processable image
    """
    # Skip macOS/Windows system files
    if file_path.name.startswith('._'):
        return False
    
    # Only process image files
    return file_path.suffix.lower() in {'.jpg', '.jpeg', '.heic', '.heif', '.png'}


def _generate_temp_name(original_path: Path) -> Path:
    """
    Generate collision-safe temporary filename.
    
    Uses timestamp + random suffix to ensure uniqueness during staging.
    Format: pixelporter_temp_{timestamp}_{random}{ext}
    
    Args:
        original_path: Original file path (for extension)
        
    Returns:
        Temporary filename string
        
    Example:
        >>> _generate_temp_name(Path("IMG_1234.HEIC"))
        'IMG_1704452123456abcd1234.HEIC'
    """
    timestamp = int(time.time() * 1000)
    rand_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    ext = original_path.suffix
    
    return Path(f"IMG_{timestamp}{rand_suffix}{ext}")


def _stage_files_to_target(
    source: Path,
    target: Path,
    migrate_sidecars: bool,
    dry_run: bool,
    action_prefix: str
) -> list[tuple[Path, Path, list[Path]]]:
    """
    Copy files from source to target with temporary names (Phase 1).
    
    Creates collision-safe temporary copies of all images and their sidecars.
    Returns mappings to track original -> temp relationships for later phases.
    
    Args:
        source: Source directory
        target: Target directory
        migrate_sidecars: Whether to copy sidecar files
        dry_run: Simulation mode
        action_prefix: Logging prefix (e.g., "[DRY RUN]")
        
    Returns:
        List of tuples: (source_image_path, temp_image_path, [temp_sidecar_paths])
        
    Example:
        >>> mappings = _stage_files_to_target(src, tgt, True, False, "[ACTION]")
        >>> for orig, temp, sidecars in mappings:
        ...     print(f"{orig.name} -> {temp.name} (+ {len(sidecars)} sidecars)")
    """
    mappings = []
    
    log_and_display(f"{action_prefix} Phase 1: Staging files to target with safe names")
    
    for file_path in source.iterdir():
        if not file_path.is_file():
            continue
        
        # Only process valid images
        if not _is_valid_image(file_path):
            logger.debug(f"Skipping non-image: {file_path.name}")
            continue
        
        # Generate collision-safe temp name
        temp_name = _generate_temp_name(file_path)
        temp_image_path = target / temp_name
        print(f"Generated temp name: {file_path.name} -> {temp_name.stem} // {temp_image_path}")
        # Find sidecars if migration enabled
        temp_sidecar_paths = []

        if migrate_sidecars:
            renamed_group = AppleSidecarManager.get_renamed_sidecars(file_path, temp_name.stem)
            for rename in renamed_group.renames:
                target_path = target / rename.new_filename
                if not dry_run:
                    shutil.copy2(rename.original, target_path)

                    # Health check: verify copy
                    if not target_path.exists():
                        raise IOError(f"Failed to copy sidecar: {rename.original}")
                    if target_path.stat().st_size != rename.original.stat().st_size:
                        raise IOError(f"Size mismatch for sidecar: {rename.original}")
                
                logger.debug(f"Staged sidecar: {rename.original} -> {target_path}")
        
        # Copy main image
        if dry_run:
            log_and_display(
                f"{action_prefix} Would stage: {file_path.name} -> {temp_name} "
                f"(+ {len(temp_sidecar_paths)} sidecars)"
            )
        else:
            print(f"Staging image: {file_path.name} -> {temp_name}")
            shutil.copy2(file_path, temp_image_path)
            
            # Health check: verify copy
            if not temp_image_path.exists():
                raise IOError(f"Failed to copy image: {file_path.name}")
            if temp_image_path.stat().st_size != file_path.stat().st_size:
                raise IOError(f"Size mismatch for image: {file_path.name}")
            
            logger.info(
                f"Staged: {file_path.name} -> {temp_name} "
                f"(+ {len(temp_sidecar_paths)} sidecars)"
            )
        
        # Track mapping for later phases
        mappings.append((file_path, temp_image_path, temp_sidecar_paths))
    
    log_and_display(f"{action_prefix} Phase 1 complete: {len(mappings)} image families staged")
    
    return mappings

class PushResult:
    """Result of push_photos operation."""
    def __init__(self):
        self.processed = 0
        self.skipped = 0
        self.failed = 0
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
        from .adapters import SnapJediAdapter
        return SnapJediAdapter
    except ImportError:
        logger.warning("SnapJedi not available, files will be moved as-is")
        return None


def push_photos(
    source: Optional[Path] = None,
    target: Optional[Path] = None,
    config_path: Optional[str] = None,
    config: Optional[Dict] = None,
    processor_class: Optional[type[FileProcessor]] = None,
    deduplicator: Optional[Deduplicator] = None,
    migrate_sidecars: bool = True,
    ensure_unique_timestamps: bool = True,
    dry_run: bool = False
) -> PushResult:
    action_prefix = "[DRY RUN]" if dry_run else "[ACTION]"
    
    # Config loading (existing logic)
    # ... 
    
    # Get default processor
    if processor_class is None:
        processor_class = _get_default_processor()
    
    result = PushResult()
    
    # Phase 1: Copy with temp names
    mappings = _stage_files_to_target(source, target, migrate_sidecars, dry_run, action_prefix)
    
    # # Phase 2a: Deduplication (if enabled)
    # if deduplicator:
    #     mappings = _remove_duplicates(mappings, deduplicator, dry_run, action_prefix, result)
    
    # # Phase 2b: Timestamp uniqueness (if enabled)
    # if ensure_unique_timestamps:
    #     _fix_overlapping_timestamps(mappings, dry_run, action_prefix)
    
    # # Phase 3: Process and cleanup
    # _process_and_cleanup(mappings, processor_class, dry_run, action_prefix, result)
    
    # Summary
    #log_and_display(...)
    
    return result

# NOTE: Legacy implementation preserved during refactoring to 3-phase architecture.
# Remove once new implementation (lines 187-227) is complete and tested.
# 
#  def push_photos(
#      source: Optional[Path] = None,
#      target: Optional[Path] = None,
#      config_path: Optional[str] = None,
#      config: Optional[Dict] = None,
#      processor_class: Optional[type[FileProcessor]] = None,
#      deduplicator: Optional[Deduplicator] = None,
#      dry_run: bool = False
#  ) -> PushResult:
#      """
#      Push photos from source to target with optional processing.
     
#      Args:
#          source: Source directory containing photos
#          target: Target directory for processed photos
#          config_path: Path to config directory
#          config: Pre-loaded config dict
#          processor_class: Class implementing FileProcessor protocol (default: SnapJedi)
#          deduplicator: Deduplicator instance (default: None)
#          dry_run: If True, simulate operations without file changes
         
#      Returns:
#          PushResult with operation statistics
#      """
#      action_prefix = "[DRY RUN]" if dry_run else "[ACTION]"
     
#      # Load config if paths not provided
#      if source is None or target is None:
#          loaded_config = _load_pixelporter_config(config_path, config)
#          paths = loaded_config.get("paths", {})
#          source = source or paths.get("source_folder")
#          target = target or paths.get("target_folder")
         
#          if not source or not target:
#              raise ValueError("Source and target must be provided via args or config")
         
#          source = Path(source)
#          target = Path(target)
     
#      # Validate source exists
#      if not source.exists():
#          msg = f"Source folder does not exist: {source}"
#          log_and_display(f"❌ {action_prefix} {msg}", level="error")
#          raise FileNotFoundError(msg)
     
#      log_and_display(f"{action_prefix} Processing photos from '{source}' → '{target}'")
     
#      # Create target directory
#      if not dry_run:
#          target.mkdir(parents=True, exist_ok=True)
     
#      # Get default processor if not provided
#      if processor_class is None:
#          processor_class = _get_default_processor()
     
#      result = PushResult()
     
#      # TODO: Implement deduplication logic here
     
#      # Process each file
#      for file_path in source.iterdir():
#          if not file_path.is_file():
#              continue
         
#          # TODO: Filter by file extensions (jpg, jpeg, heic, etc.)
         
#          try:
#              _process_single_file(
#                  file_path=file_path,
#                  target_dir=target,
#                  processor_class=processor_class,
#                  dry_run=dry_run,
#                  action_prefix=action_prefix,
#                  result=result
#              )
#          except Exception as e:
#              error_msg = f"Failed processing {file_path.name}: {e}"
#              log_and_display(f"❌ {action_prefix} {error_msg}", level="error")
#              logger.error(error_msg, exc_info=True)
#              result.failed += 1
#              result.errors.append(error_msg)
     
#      # Summary
#      log_and_display(
#          f"\n{action_prefix} ✅ Processed: {result.processed}, "
#          f"Skipped: {result.skipped}, Failed: {result.failed}"
#      )
     
#      if dry_run:
#          log_and_display("💡 Run with dry_run=False to apply changes.")
     
#      return result
# def _process_single_file(
#     file_path: Path,
#     target_dir: Path,
#     processor_class: Optional[type[FileProcessor]],
#     dry_run: bool,
#     action_prefix: str,
#     result: PushResult
# ) -> None:
#     """
#     Process a single file through the pipeline.
    
#     Args:
#         file_path: Source file to process
#         target_dir: Target directory
#         processor_class: Processor class to use (or None for move-only)
#         dry_run: Simulation mode
#         action_prefix: Logging prefix
#         result: PushResult to update
#     """
#     # Filter by image extensions
#     valid_extensions = {'.jpg', '.jpeg', '.heic', '.png'}
#     if file_path.suffix.lower() not in valid_extensions:
#         logger.debug(f"Skipping non-image file: {file_path.name}")
#         result.skipped += 1
#         return
    
#     if processor_class is None:
#         # No processor - just move file as-is
#         _move_file_without_processing(
#             file_path=file_path,
#             target_dir=target_dir,
#             dry_run=dry_run,
#             action_prefix=action_prefix,
#             result=result
#         )
#         return
    
#     # Process with provided processor
#     if dry_run:
#         log_and_display(f"{action_prefix} Would process: {file_path.name}")
#         result.processed += 1
#         return
    
#     # Real processing
#     processor = processor_class()
#     processor.open(file_path)
#     process_result: ProcessResult = processor.process()
    
#     if not process_result.success:
#         error_msg = f"Processing failed: {process_result.error_message}"
#         log_and_display(f"⚠️ {file_path.name}: {error_msg}", level="warning")
#         result.skipped += 1
#         return
    
#     # Check health before deleting original
#     if process_result.is_healthy and process_result.target_path.exists():
#         # Publish event for DirectoryVerifier
#         publish_file_moved(
#             source_path=str(file_path),
#             destination_path=str(process_result.target_path),
#             file_size=file_path.stat().st_size,
#             is_healthy=True
#         )
        
#         # Delete original
#         file_path.unlink()
#         publish_file_deleted(
#             file_path=str(file_path),
#             file_size=file_path.stat().st_size
#         )
        
#         logger.info(f"Successfully processed and deleted original: {file_path.name}")
#         result.processed += 1
#     else:
#         reason = "health check failed" if not process_result.is_healthy else "target file missing"
#         log_and_display(f"⚠️ Not deleting original: {reason} → {file_path.name}", level="warning")
#         result.skipped += 1


# def _move_file_without_processing(
#     file_path: Path,
#     target_dir: Path,
#     dry_run: bool,
#     action_prefix: str,
#     result: PushResult
# ) -> None:
#     """Move file to target without processing (when no processor provided)."""
#     target_path = target_dir / file_path.name
    
#     # Handle collision
#     if target_path.exists():
#         target_path = _get_safe_target_path(file_path.name, target_dir)
    
#     if dry_run:
#         log_and_display(f"{action_prefix} Would move: {file_path.name} → {target_path.name}")
#         result.processed += 1
#         return
    
#     # Real move
#     shutil.move(str(file_path), str(target_path))
    
#     # Publish events
#     publish_file_moved(
#         source_path=str(file_path),
#         destination_path=str(target_path),
#         file_size=target_path.stat().st_size,
#         is_healthy=True  # Assume healthy for simple moves
#     )
    
#     logger.info(f"Moved without processing: {file_path.name} → {target_path.name}")
#     result.processed += 1


# def _get_safe_target_path(filename: str, target_dir: Path) -> Path:
#     """
#     Ensure target path doesn't collide with existing files.
    
#     Args:
#         filename: Original filename
#         target_dir: Target directory
        
#     Returns:
#         Safe path with incremented suffix if needed
#     """
#     file_path = Path(filename)
#     stem = file_path.stem
#     suffix = file_path.suffix
    
#     target_path = target_dir / filename
#     if not target_path.exists():
#         return target_path
    
#     # Collision - increment
#     counter = 1
#     while (target_dir / f"{stem}_{counter}{suffix}").exists():
#         counter += 1
    
#     return target_dir / f"{stem}_{counter}{suffix}"