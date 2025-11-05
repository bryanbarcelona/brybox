"""
File operations: moving, conflict resolution, and path management.
"""

import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import exiftool
from exiftool.exceptions import ExifToolExecuteError

from ...utils.logging import log_and_display, get_configured_logger
from ...events.bus import publish_file_moved, publish_file_deleted


class _FileMover:
    """Handles file operations and path management."""
    
    def __init__(self, base_dir: str, dry_run: bool = False):
        """
        Initialize file mover.
        
        Args:
            base_dir: Base directory for output files
            dry_run: If True, no files are moved or deleted
        """
        self.base_dir = base_dir
        self.dry_run = dry_run
    
    def build_output_path(self, category: str, filename: str, config: Dict[str, Any],
                         audio_filepath: str) -> Optional[str]:
        """
        Build the complete output file path.
        
        Args:
            category: Category name
            filename: Output filename
            config: Full configuration dictionary
            audio_filepath: Original audio file path (for content comparison)
            
        Returns:
            Complete output path, or None if category not found
        """
        categories = config.get("categories", {})
        
        if category not in categories:
            return None
        
        relative_path = categories[category].get("output_path", "")
        filepath = os.path.join(self.base_dir, relative_path, filename).replace("/", "\\")
        
        if not os.path.isfile(filepath):
            return filepath
        
        # Check if files have same content
        try:
            if self._files_have_same_content(audio_filepath, filepath):
                return filepath
        except Exception:
            pass
        
        # Handle filename conflicts
        return self._resolve_filename_conflict(filepath)
    
    def _files_have_same_content(self, file1: str, file2: str) -> bool:
        """
        Check if two audio files have the same content via metadata comparison.
        
        Uses exiftool to compare key metadata fields as a proxy for content equality.
        
        Args:
            file1: First audio file path
            file2: Second audio file path
            
        Returns:
            True if files appear to have same content, False otherwise
        """
        try:
            with exiftool.ExifToolHelper() as et:
                meta1 = et.get_metadata(str(file1))[0]
                meta2 = et.get_metadata(str(file2))[0]
                
                # Compare key fields that indicate same content
                comparison_fields = [
                    'File:FileSize',
                    'QuickTime:Duration',
                    'QuickTime:MediaCreateDate'
                ]
                
                for field in comparison_fields:
                    if field in meta1 and field in meta2:
                        if meta1[field] != meta2[field]:
                            return False
                
                return True
                
        except (ExifToolExecuteError, Exception):
            return False
    
    def _resolve_filename_conflict(self, filepath: str) -> str:
        """
        Resolve filename conflicts by adding number suffix.
        
        Args:
            filepath: Conflicting file path
            
        Returns:
            New filepath with (N) suffix
        """
        i = 1
        base, ext = os.path.splitext(filepath)
        
        while os.path.isfile(f"{base}({i}){ext}"):
            i += 1
        
        return f"{base}({i}){ext}"
    
    def move_file(self, source: str, destination: str) -> Tuple[bool, bool]:
        """
        Move file from source to destination.
        
        Args:
            source: Source file path
            destination: Destination file path
            
        Returns:
            Tuple of (success, is_new_file)
            - success: True if operation completed successfully
            - is_new_file: True if file was moved (new), False if duplicate deleted
        """
        if not os.path.exists(source):
            logger.warning(f"Source file does not exist: {source}")
            return False, False
        
        file_size = os.path.getsize(source)
        output_dir = os.path.dirname(destination)
        
        if self.dry_run:
            log_and_display(f"Would create directory: {output_dir}")
            if os.path.exists(destination):
                log_and_display(f"Would delete source file (duplicate): {source}")
                return True, False
            else:
                log_and_display(f"Would move {source} to {destination}")
                return True, True
        
        # Create directory if needed
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Handle existing destination
        if os.path.exists(destination) and self._is_healthy(destination):
            os.remove(source)
            log_and_display(f"Destination exists. Deleted source file: {source}")
            publish_file_deleted(source, file_size)
            return True, False
        else:
            shutil.move(source, destination)
            if not self._is_healthy(destination):
                log_and_display(f"Moved file is corrupted: {destination}", level="error")
                return False, False
            
            log_and_display(f"Moved {source} to {destination}.")
            publish_file_moved(source, destination, file_size, True)
            return True, True
    
    def _is_healthy(self, filepath: str) -> bool:
        """
        Verify audio file health using exiftool.
        
        Args:
            filepath: Path to audio file
            
        Returns:
            True if file can be read successfully, False otherwise
        """
        try:
            with exiftool.ExifToolHelper() as et:
                et.get_metadata(str(filepath))
                return True
        except (ExifToolExecuteError, Exception):
            return False
