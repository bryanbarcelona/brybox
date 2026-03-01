"""
Brybox - A collection of automation and document processing tools.
"""

import logging
from logging import NullHandler

# Public API re-exports
from brybox.core.audiora import AudioraCore, AudioraNexus
from brybox.core.doctopus import DoctopusPrime, DoctopusPrimeNexus
from brybox.core.inbox_kraken.engine import InboxKraken
from brybox.core.porter import push_photos, push_videos
from brybox.core.snap_jedi import SnapJedi
from brybox.core.videosith import VideoSith
from brybox.events.verifier import DirectoryVerifier

# Logging helpers (now safe — no circular dependency)
from brybox.utils.logging import (
    enable_verbose_logging,  # ← re-export the function
    log_and_display,
    log_manager,
    trackerator,
)

# Prevent "No handler found" warnings for the package logger itself
logging.getLogger(__name__).addHandler(NullHandler())


# --- PUBLIC INTERFACE ---
__all__ = [
    'AudioraCore',
    'AudioraNexus',
    'DirectoryVerifier',
    'DoctopusPrime',
    'DoctopusPrimeNexus',
    'InboxKraken',
    'SnapJedi',
    'VideoSith',
    'enable_verbose_logging',
    'log_and_display',
    'log_manager',
    'push_photos',
    'push_videos',
    'trackerator',
]
