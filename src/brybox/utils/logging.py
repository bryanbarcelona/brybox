# import inspect
# from tqdm import tqdm


# def log_and_display(message: str, level: str = "info", log: bool = True, display: bool = True):
#     """
#     Log message using caller's module logger and display via tqdm with line replacement.
    
#     Args:
#         message: The message to log and display
#         level: Log level (info, warning, error, debug)
#         log: Whether to log the message (default: True)
#         display: Whether to display via tqdm (default: True)
    
#     Note: Display always replaces current line to preserve progress bars.
#     """
#     # Get the calling module's logger variable
#     frame = inspect.currentframe().f_back
#     caller_logger = frame.f_globals.get('logger')
    
#     # Log if caller has a logger and logging is requested
#     if log and caller_logger:
#         getattr(caller_logger, level.lower())(message)
    
#     # Display via tqdm if requested (always replaces line)
#     if display:
#         import sys
#         print(f"\r{message}", end="\r", flush=True, file=sys.stderr)
#         #tqdm.write(f"{message}", end="\r")  # Move to next line after message


# 📄 display_utils.py — NOW ACTUALLY WORKING 😅

import sys
import inspect
from tqdm import tqdm

class DynamicDisplay:
    def __init__(self):
        self._last_len = 0
        self._has_temp_line = False  # Track if we're currently occupying the temp line

    def write_temp(self, message: str, file=sys.stderr):
        # Pad to clear previous
        padded = message.ljust(self._last_len)
        self._last_len = max(len(message), self._last_len)

        if self._has_temp_line:
            # Move cursor up one line to overwrite
            file.write('\x1b[1A')  # ANSI: move cursor up 1 line

        # Write the message and go to next line (so it becomes visible)
        tqdm.write(padded, file=file, end='\n')
        file.flush()

        self._has_temp_line = True

    def write_sticky(self, message: str, file=sys.stderr):
        # If we had a temp line, we're already on the next line — just write
        tqdm.write(message, file=file)
        self._last_len = 0
        self._has_temp_line = False
        file.flush()


# Singleton
dynamic_display = DynamicDisplay()


def log_and_display(
    message: str,
    level: str = "info",
    log: bool = True,
    display: bool = True,
    sticky: bool = False
):
    frame = inspect.currentframe().f_back
    caller_logger = frame.f_globals.get('logger')

    if log and caller_logger:
        getattr(caller_logger, level.lower())(message)

    if display:
        if sticky:
            dynamic_display.write_sticky(message)
        else:
            dynamic_display.write_temp(message)

def get_configured_logger(name: str):
    """Get logger and configure it according to package settings"""
    from brybox import VERBOSE_LOGGING, _CONFIGURED_LOGGERS
    import logging
    
    logger = logging.getLogger(name)
    if VERBOSE_LOGGING:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARNING)
    
    if name not in _CONFIGURED_LOGGERS:
        _CONFIGURED_LOGGERS.append(name)
    
    return logger