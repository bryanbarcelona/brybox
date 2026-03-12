"""Base exception hierarchy for all Brybox modules."""


class BryboxError(Exception):
    """Base exception for all Brybox errors."""


class MediaProcessorError(BryboxError):
    """Base exception for all media processing operations (SnapJedi, VideoSith, etc.)."""
