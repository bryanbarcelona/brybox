"""
Brybox - A collection of automation and document processing tools.
"""

import logging
from logging import NullHandler

# --- PACKAGE-LEVEL LOGGING CONFIG ---
VERBOSE_LOGGING = False


_CONFIGURED_LOGGERS = []


def enable_verbose_logging():
    global VERBOSE_LOGGING
    VERBOSE_LOGGING = True
    # Reconfigure all previously configured loggers
    for name in _CONFIGURED_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)

# def _configure_logger(name):
#     logger = logging.getLogger(name)
#     if VERBOSE_LOGGING:
#         logger.setLevel(logging.INFO)
#     else:
#         logger.setLevel(logging.WARNING)
#     _CONFIGURED_LOGGERS.append(name)  # ← track it
#     return logger

# --- IMPORT MODULES AND CONFIGURE THEIR LOGGERS ---
# We import *, but also configure loggers for key classes/functions

from .utils.logging import log_and_display

from .events.verifier import *

from .core.doctopus import *

from .core.inbox_kraken import *

# Uncomment as you add modules:
# from .doismith import *
# _configure_logger("Doismith")
# from .dropboss import *
# _configure_logger("DropBoss")
# from .snap_jedi import *
# _configure_logger("SnapJedi")
# from .video_sith import *
# _configure_logger("VideoSith")
# from .web_marionette import *
# _configure_logger("WebMarionette")

# --- RE-EXPORT (for explicit imports) ---
# You can still do: from brybox import DoctopusPrime, fetch_and_process_emails

# Assuming these are defined in your modules:
# (Adjust names to match your actual class/function names)
# try:
#     from .doctopus import DoctopusPrime
# except ImportError:
#     pass

# try:
#     from .inbox_kraken import fetch_and_process_emails
# except ImportError:
#     pass

# Add others as needed:
# from .web_marionette import download_kfw_invoices

# --- METADATA ---
__version__ = "0.1.0"
__author__ = "Bryan Barcelona"

# --- PREVENT "No handler found" WARNINGS ---
logging.getLogger(__name__).addHandler(NullHandler())

# --- PUBLIC API ---
__all__ = [
    "enable_verbose_logging",  # ← NEW: the magic switch
    "doctopus",
    "doismith",
    "dropboss",
    "inbox_kraken",
    "snap_jedi",
    "video_sith",
    "web_marionette",
    # Add specific classes/functions if you want them in __all__:
    # "DoctopusPrime",
    # "fetch_and_process_emails",
]