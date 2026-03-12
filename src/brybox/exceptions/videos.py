from pathlib import Path

from brybox.exceptions.base import MediaProcessorError


class VideoSithError(MediaProcessorError):
    def __init__(self, message: str, video_path: str | Path | None = None):
        self.video_path = Path(video_path) if video_path else None
        super().__init__(message)


class VideoSithConversionError(VideoSithError):
    pass


class VideoSithConversionFailedError(VideoSithConversionError):
    def __init__(self, message: str, video_path: Path | None = None, stderr: str | None = None):
        self.stderr = stderr
        super().__init__(message, video_path)


class VideoSithConversionTimeoutError(VideoSithConversionError):
    def __init__(self, message: str, video_path: Path | None = None, timeout_seconds: int = 300):
        self.timeout_seconds = timeout_seconds
        super().__init__(message, video_path)


class VideoSithToolNotFoundError(VideoSithError):
    def __init__(self, message: str, tool_name: str | None = None):
        self.tool_name = tool_name
        super().__init__(message)


class VideoSithFileOperationError(VideoSithError):
    def __init__(self, message: str, source_path: Path | None = None, dest_path: Path | None = None):
        self.source_path = source_path
        self.dest_path = dest_path
        super().__init__(message, source_path)


class VideoSithVideoNotFoundError(VideoSithError):
    pass


class VideoSithMetadataError(VideoSithError):
    pass


class VideoSithMetadataReadError(VideoSithMetadataError):
    def __init__(self, message: str, video_path: Path | None = None, stderr: str | None = None):
        self.stderr = stderr
        super().__init__(message, video_path)


class VideoSithMetadataParseError(VideoSithMetadataError):
    def __init__(self, message: str, video_path: Path | None = None, field: str | None = None):
        self.field = field
        super().__init__(message, video_path)


class VideoSithMetadataWriteError(VideoSithMetadataError):
    def __init__(self, message: str, video_path: Path | None = None, stderr: str | None = None):
        self.stderr = stderr
        super().__init__(message, video_path)


class VideoSithTimezoneError(VideoSithMetadataError):
    """Failed to calculate timezone from GPS coordinates."""

    def __init__(
        self, message: str, video_path: Path | None = None, coordinates: tuple[float, float, float] | None = None
    ):
        self.coordinates = coordinates
        super().__init__(message, video_path)


class VideoSithFilenameParseError(VideoSithMetadataError):
    """Failed to parse date from filename."""

    def __init__(self, message: str, video_path: Path | None = None, filename: str | None = None):
        self.filename = filename
        super().__init__(message, video_path)
