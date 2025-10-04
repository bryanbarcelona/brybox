"""Adapters to make existing tools compatible with PixelPorter protocols."""

from pathlib import Path
import logging

from .protocols import FileProcessor, ProcessResult

logger = logging.getLogger("PixelPorter.Adapters")


class SnapJediAdapter:
    """
    Temporary adapter until SnapJedi is refactored to match protocol.
    
    Wraps SnapJedi's current initialization-heavy design to match
    the FileProcessor protocol's open/process pattern.
    """
    
    def __init__(self):
        """Initialize adapter without file (protocol requirement)."""
        self._snap_jedi = None
        self._file_path = None
    
    def open(self, file_path: Path) -> None:
        """
        Open file using SnapJedi.
        
        Note: SnapJedi does heavy lifting in __init__, so we instantiate here.
        This will be cleaner once SnapJedi is refactored.
        """
        from ..snap_jedi import SnapJedi
        
        self._file_path = file_path
        try:
            self._snap_jedi = SnapJedi(str(file_path))
            logger.debug(f"Opened file with SnapJedi: {file_path.name}")
        except Exception as e:
            logger.error(f"Failed to open file with SnapJedi: {file_path.name}", exc_info=True)
            raise
    
    def process(self) -> ProcessResult:
        """
        Process using SnapJedi's rename_jpg method.
        
        Returns:
            ProcessResult with processing outcome
        """
        if self._snap_jedi is None:
            raise RuntimeError("Must call open() before process()")
        
        try:
            # Execute SnapJedi's processing
            self._snap_jedi.rename_jpg()
            
            # Extract results
            return ProcessResult(
                success=True,
                target_path=Path(self._snap_jedi.target_path),
                is_healthy=self._snap_jedi.image_health,
                error_message=""
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"SnapJedi processing failed: {error_msg}", exc_info=True)
            
            return ProcessResult(
                success=False,
                target_path=self._file_path,  # Unchanged on failure
                is_healthy=False,
                error_message=error_msg
            )