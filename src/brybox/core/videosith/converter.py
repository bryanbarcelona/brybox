from pathlib import Path
from abc import ABC, abstractmethod
import subprocess
import shutil
from typing import Optional

from ...utils.logging import get_configured_logger

logger = get_configured_logger("VideoConverter")


class ConversionError(Exception):
    """Raised when video conversion fails."""
    pass


class VideoConverter(ABC):
    """Abstract interface for video format conversion."""
    
    @abstractmethod
    def convert_to_mp4(self, source: Path, target: Path) -> None:
        """
        Convert video to MP4 format.
        
        Args:
            source: Source video path
            target: Target MP4 path
            
        Raises:
            ConversionError: If conversion fails
        """
        pass


class FFmpegConverter(VideoConverter):
    """
    Converts videos using FFmpeg.
    
    Attempts copy codec first for speed, falls back to re-encoding if needed.
    Preserves metadata during conversion.
    """
    
    def __init__(self, ffmpeg_path: Optional[str] = None):
        """
        Initialize converter.
        
        Args:
            ffmpeg_path: Path to ffmpeg command. If None, attempts to find it.
        """
        self.ffmpeg_path = ffmpeg_path or self._find_ffmpeg()
    
    def convert_to_mp4(self, source: Path, target: Path) -> None:
        """
        Convert MOV to MP4 preserving metadata.
        
        Strategy:
        1. Try stream copy (fast, no re-encoding)
        2. If that fails, re-encode with H.264/AAC
        
        Args:
            source: Source video path (MOV, etc.)
            target: Target MP4 path
            
        Raises:
            ConversionError: If conversion fails
        """
        # Primary: stream copy (fast)
        primary_cmd = [
            self.ffmpeg_path,
            '-i', str(source),
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-map_metadata', '0',
            str(target)
        ]
        
        # Fallback: re-encode
        fallback_cmd = [
            self.ffmpeg_path,
            '-i', str(source),
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-map_metadata', '0',
            str(target)
        ]
        
        try:
            # Try primary command (stream copy)
            result = subprocess.run(
                primary_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                logger.info(f"Converted {source.name} using stream copy")
                return
            
            # Primary failed, clean up and try fallback
            logger.warning(f"Stream copy failed for {source.name}, re-encoding...")
            
            if target.exists():
                target.unlink()
            
            fallback_result = subprocess.run(
                fallback_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=600  # 10 minute timeout for re-encoding
            )
            
            if fallback_result.returncode == 0:
                logger.info(f"Converted {source.name} using re-encoding")
                return
            
            raise ConversionError("Both stream copy and re-encoding failed")
            
        except subprocess.TimeoutExpired:
            if target.exists():
                target.unlink()
            raise ConversionError("Conversion timed out")
        except Exception as e:
            if target.exists():
                target.unlink()
            raise ConversionError(f"Conversion failed: {str(e)}")
    
    def _find_ffmpeg(self) -> str:
        """
        Locate ffmpeg command.
        
        Returns:
            Path to ffmpeg
            
        Raises:
            RuntimeError: If ffmpeg not found
        """
        if shutil.which("ffmpeg"):
            return "ffmpeg"
        
        raise RuntimeError(
            "FFmpeg not found. Install FFmpeg and add to PATH."
        )
