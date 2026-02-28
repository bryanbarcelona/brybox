"""
Brybox - A collection of automation and document processing tools.
"""

import logging
from logging import NullHandler

# --- PACKAGE-LEVEL LOGGING CONFIGURATION ---
VERBOSE_LOGGING = False
_CONFIGURED_LOGGERS = []


def enable_verbose_logging():
    """Enable INFO-level logging for all Brybox modules."""
    global VERBOSE_LOGGING
    VERBOSE_LOGGING = True
    for name in _CONFIGURED_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)


# --- PUBLIC API IMPORTS ---
# These imports also trigger logger configuration in their respective modules.
from brybox.core.audiora import AudioraCore, AudioraNexus
from brybox.core.doctopus import DoctopusPrime, DoctopusPrimeNexus
from brybox.core.inbox_kraken.engine import KrakenEngine
from brybox.core.porter import push_photos, push_videos
from brybox.core.snap_jedi import SnapJedi
from brybox.core.videosith import VideoSith
from brybox.events.verifier import DirectoryVerifier
from brybox.utils.logging import log_and_display

# --- PREVENT "No handler found" WARNINGS ---
logging.getLogger(__name__).addHandler(NullHandler())

# --- PUBLIC INTERFACE ---
__all__ = [
    'AudioraCore',
    'AudioraNexus',
    'DirectoryVerifier',
    'DoctopusPrime',
    'DoctopusPrimeNexus',
    'KrakenEngine',
    'SnapJedi',
    'VideoSith',
    'enable_verbose_logging',
    'log_and_display',
    'push_photos',
    'push_videos',
]
