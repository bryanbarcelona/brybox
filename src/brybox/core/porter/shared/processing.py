from __future__ import annotations

from pathlib import Path

from brybox.core.porter.models.image import ProcessResult
from brybox.core.porter.shared.protocols import FileProcessor, PorterResult
from brybox.events.bus import publish_file_renamed
from brybox.utils.apple_files import AppleSidecarManager
from brybox.utils.logging import log_and_display


def process_and_cleanup(
    mappings: list[tuple[Path, Path, list[Path]]],
    processor_class: type[FileProcessor],
    dry_run: bool,
    action_prefix: str,
    result: PorterResult,
) -> None:
    """
    Process temp files and clean up sources (Phase 3).

    For each staged file:
    1. Process temp image with SnapJedi (convert HEIC→JPG, rename by timestamp)
    2. On success: delete source image + source sidecars
    3. On failure: keep everything for debugging

    Args:
        mappings: List of (source_path, temp_image_path, temp_sidecar_paths)
        processor_class: Class implementing FileProcessor protocol
        dry_run: Simulation mode
        action_prefix: Logging prefix
        result: PushResult to update with stats
    """
    if dry_run:
        log_and_display(f'{action_prefix} Processing: Skipped (runs on staged files only)', log=False)
        log_and_display(f'{action_prefix} Would process {len(mappings)} image(s) with SnapJedi', log=False)
        return

    if not mappings:
        log_and_display('No files to process', log=False)
        return

    log_and_display(f'Processing {len(mappings)} file(s)...')

    for source_path, temp_image_path, _temp_sidecar_paths in mappings:
        try:
            processor = processor_class()

            processor.open(temp_image_path)

            process_result: ProcessResult = processor.process()

            if not process_result.success:
                error_msg = process_result.error_message or 'Unknown error'
                log_and_display(f'✗ Processing failed: {temp_image_path.name} - {error_msg}', level='error')
                result.failed += 1
                result.errors.append(f'{temp_image_path.name}: {error_msg}')
                continue

            if not process_result.is_healthy:
                log_and_display(f'✗ Health check failed: {temp_image_path.name}', level='error')
                result.failed += 1
                result.errors.append(f'{temp_image_path.name}: Health check failed')
                continue

            if not process_result.target_path.exists():
                log_and_display(f'✗ Output file missing: {process_result.target_path.name}', level='error')
                result.failed += 1
                result.errors.append(f'{temp_image_path.name}: Output file not found')
                continue

            publish_file_renamed(
                old_path=str(temp_image_path),
                new_path=str(process_result.target_path),
                file_size=process_result.target_path.stat().st_size,
                is_healthy=process_result.is_healthy,
            )

            result.processed += 1

            deleted_files = AppleSidecarManager.delete_image_with_sidecars(source_path)

            sidecar_count = len(deleted_files) - 1  # Subtract the image itself
            log_and_display(
                f'✓ Processed: {source_path.name} → {process_result.target_path.name} '
                f'(cleaned {sidecar_count} sidecar(s))'
            )

        except Exception as e:
            error_msg = f'Exception processing {temp_image_path.name}: {e}'
            log_and_display(f'✗ {error_msg}', level='error')
            result.failed += 1
            result.errors.append(error_msg)
            continue

    # Summary
    if result.failed > 0:
        log_and_display(f'⚠️  Processing completed with {result.failed} failure(s)', level='warning')
