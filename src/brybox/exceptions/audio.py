"""
Audio-specific exceptions for Audiora.
All exceptions inherit from AudioraError → BryboxError.
"""

from pathlib import Path

from brybox.exceptions.base import BryboxError


class AudioraError(BryboxError):
    """Base exception for all Audiora-related errors."""

    def __init__(self, message: str, audio_path: str | Path | None = None):
        self.audio_path = Path(audio_path) if audio_path else None
        super().__init__(message)


class AudioraAudioError(AudioraError):
    """Base for audio file-related errors."""

    def __init__(self, message: str, audio_path: str | Path | None = None):
        super().__init__(message, audio_path)


class AudioraAudioNotFoundError(AudioraAudioError):
    """Audio file does not exist."""


class AudioraConfigurationError(AudioraError):
    """Configuration issues (missing category, invalid rules)."""

    def __init__(self, message: str, audio_path: str | Path | None = None, config_key: str | None = None):
        self.config_key = config_key
        super().__init__(message, audio_path)


class AudioraFileOperationError(AudioraError):
    """File system operation failed."""

    def __init__(
        self,
        message: str,
        source_path: str | Path | None = None,
        dest_path: str | Path | None = None,
        audio_path: str | Path | None = None,
    ):
        self.source_path = Path(source_path) if source_path else None
        self.dest_path = Path(dest_path) if dest_path else None
        # Use source_path as the primary audio_path for consistency
        super().__init__(message, audio_path or source_path)


class AudioraMetadataError(AudioraError):
    """Metadata extraction failed."""

    def __init__(self, message: str, audio_path: str | Path | None = None, metadata_field: str | None = None):
        self.metadata_field = metadata_field
        super().__init__(message, audio_path)


class AudioraCorruptedFileError(AudioraAudioError):
    """Audio file is corrupted or unreadable."""
