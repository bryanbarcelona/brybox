"""PixelPorter - Photo ingestion and processing orchestrator."""

from .orchestrator import PushResult, push_photos
from .protocols import Deduplicator, FileProcessor, ProcessResult

__all__ = ['Deduplicator', 'FileProcessor', 'ProcessResult', 'PushResult', 'push_photos']
