import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from ...utils.logging import log_and_display


def _fix_overlapping_timestamps(
    mappings: list[tuple[Path, Path, list[Path]]], dry_run: bool, action_prefix: str
) -> None:
    """
    Ensure unique DateTimeOriginal EXIF values (Phase 2b).

    Reads EXIF from all temp images and adjusts timestamps by +1 second
    increments when duplicates are found. This prevents SnapJedi from
    creating filename collisions during datetime-based renaming.

    Args:
        mappings: List of (source_path, temp_image_path, temp_sidecar_paths)
        dry_run: Simulation mode
        action_prefix: Logging prefix

    Note:
        Skips processing in dry-run mode (would need to simulate merged state
        of source + target to be accurate, which is complex and low-value).
    """
    if dry_run:
        log_and_display(f'{action_prefix} Timestamp uniqueness check: Skipped in dry-run mode', log=False)
        log_and_display(
            f'{action_prefix} Note: Adjustments are deterministic and safe (+1 second for collisions)', log=False
        )
        return

    if not mappings:
        return

    # Read DateTimeOriginal from all temp images
    image_dates = {}

    for source_path, temp_image_path, temp_sidecars in mappings:
        try:
            # Use exiftool to read EXIF
            result = subprocess.run(
                ['exiftool', '-DateTimeOriginal', '-s', '-s', '-s', str(temp_image_path)],
                capture_output=True,
                text=True,
                check=True,
            )

            date_str = result.stdout.strip()
            if date_str:
                # Parse EXIF format: "2024:01:15 14:30:00"
                dt = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
                image_dates[temp_image_path] = dt
            else:
                log_and_display(f'No DateTimeOriginal found in {temp_image_path.name}, skipping', level='warning')

        except subprocess.CalledProcessError as e:
            log_and_display(f'Failed to read EXIF from {temp_image_path.name}: {e}', level='warning')
        except ValueError as e:
            log_and_display(f'Invalid date format in {temp_image_path.name}: {e}', level='warning')

    if not image_dates:
        log_and_display('No EXIF dates found to process', level='warning')
        return

    # Find and fix overlapping timestamps
    unique_dates = set()
    adjustments_made = 0

    for temp_path, original_dt in image_dates.items():
        adjusted_dt = original_dt

        # Increment by 1 second until we find a unique timestamp
        while adjusted_dt in unique_dates:
            adjusted_dt = adjusted_dt + timedelta(seconds=1)

        unique_dates.add(adjusted_dt)

        # Write back to EXIF if changed
        if adjusted_dt != original_dt:
            date_formatted = adjusted_dt.strftime('%Y:%m:%d %H:%M:%S')

            try:
                subprocess.run(
                    [
                        'exiftool',
                        f'-DateTimeOriginal={date_formatted}',
                        f'-CreateDate={date_formatted}',
                        f'-ModifyDate={date_formatted}',
                        '-overwrite_original',
                        str(temp_path),
                    ],
                    capture_output=True,
                    check=True,
                )

                log_and_display(f'Adjusted timestamp: {temp_path.name} → {date_formatted}')
                adjustments_made += 1

            except subprocess.CalledProcessError as e:
                log_and_display(f'Failed to write EXIF to {temp_path.name}: {e}', level='error')

    if adjustments_made > 0:
        log_and_display(f'Adjusted {adjustments_made} timestamp collision(s)')
    else:
        log_and_display('No timestamp collisions detected', log=False)
