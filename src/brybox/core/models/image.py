from __future__ import annotations
from pathlib import Path
from typing import NamedTuple



class ProcessResult(NamedTuple):
    """Result of processing a single file."""
    success: bool
    target_path: Path
    is_healthy: bool
    error_message: str = ""