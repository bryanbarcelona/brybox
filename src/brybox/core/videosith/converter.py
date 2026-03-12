import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from brybox.exceptions.videos import (
    VideoSithConversionFailedError,
    VideoSithConversionTimeoutError,
    VideoSithFileOperationError,
    VideoSithToolNotFoundError,
)
from brybox.utils.logging import get_configured_logger

logger = get_configured_logger('VideoConverter')


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
            VideoSithConversionError: If conversion fails
        """


class FFmpegConverter(VideoConverter):
    """
    Converts videos using FFmpeg.

    Attempts copy codec first for speed, falls back to re-encoding if needed.
    Preserves metadata during conversion.
    """

    def __init__(self, ffmpeg_path: str | None = None):
        """
        Initialize converter.

        Args:
            ffmpeg_path: Path to ffmpeg command. If None, attempts to find it.

        Raises:
            VideoSithToolNotFoundError: If ffmpeg not found
        """
        self.ffmpeg_path = ffmpeg_path or self._find_ffmpeg()
        self.STREAM_COPY_TIMEOUT = 300  # 5 minutes
        self.REENCODE_TIMEOUT = 600  # 10 minutes

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
            VideoSithConversionFailedError: If both conversion attempts fail
            VideoSithConversionTimeoutError: If conversion times out
            VideoSithFileOperationError: If file operations fail
        """
        # Try stream copy first
        try:
            self._run_stream_copy(source, target)
        except subprocess.TimeoutExpired as e:
            self._safe_cleanup(target)
            raise VideoSithConversionTimeoutError(
                f'Stream copy timed out after {self.STREAM_COPY_TIMEOUT}s for {source.name}',
                video_path=source,
                timeout_seconds=self.STREAM_COPY_TIMEOUT,
            ) from e
        except subprocess.CalledProcessError:
            # Stream copy failed - try re-encode
            self._safe_cleanup(target)
        except (OSError, PermissionError) as e:
            self._safe_cleanup(target)
            raise VideoSithFileOperationError(
                f'File operation failed during stream copy: {e}', source_path=source, dest_path=target
            ) from e
        else:
            return

        # Try re-encode
        try:
            self._run_reencode(source, target)
        except subprocess.TimeoutExpired as e:
            self._safe_cleanup(target)
            raise VideoSithConversionTimeoutError(
                f'Re-encode timed out after {self.REENCODE_TIMEOUT}s for {source.name}',
                video_path=source,
                timeout_seconds=self.REENCODE_TIMEOUT,
            ) from e
        except subprocess.CalledProcessError as e:
            self._safe_cleanup(target)
            error_msg = f'Both stream copy and re-encoding failed for {source.name}'
            if e.stderr:
                error_msg += f'\nFFmpeg error: {e.stderr}'
            raise VideoSithConversionFailedError(error_msg, video_path=source, stderr=e.stderr) from e
        except (OSError, PermissionError) as e:
            self._safe_cleanup(target)
            raise VideoSithFileOperationError(
                f'File operation failed during re-encode: {e}', source_path=source, dest_path=target
            ) from e
        else:
            return

    def _run_stream_copy(self, source: Path, target: Path) -> None:
        """
        Run stream copy conversion.

        Args:
            source: Source video path
            target: Target MP4 path

        Raises:
            subprocess.TimeoutExpired: If timeout occurs
            subprocess.CalledProcessError: If ffmpeg fails
            OSError: If file operations fail
        """
        cmd = [
            'cmd',
            '/c',
            self.ffmpeg_path,
            '-i',
            str(source),
            '-c:v',
            'copy',
            '-c:a',
            'copy',
            '-map_metadata',
            '0',
            '-movflags',
            '+faststart',
            str(target),
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.STREAM_COPY_TIMEOUT,
            )
        except FileNotFoundError as e:
            raise VideoSithToolNotFoundError(
                f'FFmpeg not executable at {self.ffmpeg_path}. Check installation and permissions.', tool_name='ffmpeg'
            ) from e

    def _run_reencode(self, source: Path, target: Path) -> None:
        """
        Run re-encode conversion.

        Args:
            source: Source video path
            target: Target MP4 path

        Raises:
            subprocess.TimeoutExpired: If timeout occurs
            subprocess.CalledProcessError: If ffmpeg fails
            OSError: If file operations fail
        """
        cmd = [
            'cmd',
            '/c',
            self.ffmpeg_path,
            '-i',
            str(source),
            '-c:v',
            'libx264',
            '-preset',
            'medium',
            '-crf',
            '23',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            '-map_metadata',
            '0',
            '-movflags',
            '+faststart',
            str(target),
        ]

        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.REENCODE_TIMEOUT,
            )
        except FileNotFoundError as e:
            raise VideoSithToolNotFoundError(
                f'FFmpeg not executable at {self.ffmpeg_path}. Check installation and permissions.', tool_name='ffmpeg'
            ) from e

    @staticmethod
    def _safe_cleanup(path: Path) -> None:
        """
        Safely delete a file if it exists, ignoring errors.

        This is a cleanup helper - it NEVER raises exceptions.
        Only handles expected filesystem errors, lets unexpected ones bubble up.

        Args:
            path: Path to delete
        """
        try:
            if path.exists():
                path.unlink()
        except (FileNotFoundError, PermissionError, OSError):
            pass  # Expected filesystem errors - ignore silently

    @staticmethod
    def _find_ffmpeg() -> str:
        """
        Locate ffmpeg command.

        Returns:
            Path to ffmpeg

        Raises:
            VideoSithToolNotFoundError: If ffmpeg not found
        """
        if shutil.which('ffmpeg'):
            return 'ffmpeg'

        # Check common locations on Windows
        common_paths = [
            r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
            r'C:\ffmpeg\bin\ffmpeg.exe',
        ]

        for path in common_paths:
            if Path(path).exists():
                return path

        raise VideoSithToolNotFoundError(
            'FFmpeg not found. Install FFmpeg from https://ffmpeg.org/ and add to PATH or install to C:\\ffmpeg\\',
            tool_name='ffmpeg',
        )
