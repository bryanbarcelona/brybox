"""Result model for ZipWarden archive expansion operations."""

from dataclasses import dataclass, field


@dataclass
class ZipWardenResult:
    """
    Aggregated outcome of a ZipWarden expansion run.

    Tracks per-operation counts so callers can verify the staging directory
    was fully normalised and decide whether to proceed with downstream processing.

    Attributes:
        expanded:          Archives that were fully processed without error.
        files_extracted:   Total individual files placed into the target directory.
        dirs_flattened:    Nested subdirectory levels collapsed during flattening.
        archives_deleted:  Source ZIP files removed after successful extraction.
        failed:            Archives that could not be processed (corrupt, I/O error, etc.).
        errors:            Human-readable error descriptions, one entry per failure.

    Example:
        result = ZipWardenNexus(dir_path=staging).expand()
        if result.failed:
            raise RuntimeError(f'Archive expansion incomplete: {result.errors}')
    """

    expanded: int = 0
    files_extracted: int = 0
    dirs_flattened: int = 0
    archives_deleted: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
