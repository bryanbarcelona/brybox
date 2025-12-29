"""
Brybox - A collection of automation and document processing tools.
"""

import logging
from logging import NullHandler

# --- PACKAGE METADATA ---
__version__ = '0.3.0'
__author__ = 'Bryan Barcelona'

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
from .core.audiora import AudioraCore, AudioraNexus
from .core.doctopus import DoctopusPrime, DoctopusPrimeNexus
from .core.inbox_kraken import fetch_and_process_emails
from .core.porter import push_photos, push_videos
from .core.snap_jedi import SnapJedi
from .core.videosith import VideoSith
from .events.verifier import DirectoryVerifier
from .utils.logging import log_and_display

# --- PREVENT "No handler found" WARNINGS ---
logging.getLogger(__name__).addHandler(NullHandler())

# --- PUBLIC INTERFACE ---
__all__ = [
    'AudioraCore',
    'AudioraNexus',
    'DirectoryVerifier',
    'DoctopusPrime',
    'DoctopusPrimeNexus',
    'SnapJedi',
    'VideoSith',
    'enable_verbose_logging',
    'fetch_and_process_emails',
    'log_and_display',
    'push_photos',
    'push_videos',
]
