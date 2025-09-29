from __future__ import annotations
import inspect
import logging
from rich.console import Console
from rich.progress import (
    Progress,
    BarColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
    TextColumn,
)

__all__ = ["log_manager", "get_configured_logger", "log_and_display", "trackerator"]

# --------------------------------------------------------------------------- #
#  classic logger factory (unchanged)
# --------------------------------------------------------------------------- #
def get_configured_logger(name: str) -> logging.Logger:
    """Build or return an already-configured logger."""
    from brybox import VERBOSE_LOGGING, _CONFIGURED_LOGGERS

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO if VERBOSE_LOGGING else logging.WARNING)

    if name not in _CONFIGURED_LOGGERS:
        _CONFIGURED_LOGGERS.append(name)
    return logger


# --------------------------------------------------------------------------- #
#  rich-backed console / progress singleton
# --------------------------------------------------------------------------- #

def _find_logger() -> logging.Logger | None:
    """First logger found outside this file."""
    for frm in inspect.stack()[2:]:          # skip _find_logger + log
        if frm.filename == __file__:
            continue
        if (lg := frm.frame.f_globals.get("logger")) is not None:
            return lg
    return None

class ConsoleLogger:
    """Thin façade: progress + optional sticky messages."""

    def __init__(self) -> None:
        self.console = Console()
        self._progress: Progress | None = None
        self._task: int | None = None
        # --- explicit wiring point ----------------------------------------- #
        self.logger: logging.Logger | None = None

    #  progress lifecycle
    def start_progress(self, total: int, description: str = "Working…") -> None:
        if self._progress:
            self._progress.stop()

        self._progress = Progress(
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TextColumn("[progress.description]{task.description}"),  # mutable text
            console=self.console,
            transient=False,
        )
        self._progress.start()
        self._task = self._progress.add_task(description, total=total)

    def update_progress(self, advance: int = 1, description: str | None = None) -> None:
        if not self._progress or self._task is None:
            return
        self._progress.advance(self._task, advance)
        if description is not None:
            self._progress.update(self._task, description=description)

        if self._progress.tasks[self._task].finished:
            self._progress.stop()
            self._progress = self._task = None

    #  unified message API
    def log(self, message: str, *, sticky: bool = False,
            level: str = "info", log: bool = True) -> None:

        # 1. explicit logger takes precedence
        logger = self.logger
        # 2. otherwise walk the stack once
        if logger is None and log:
            logger = _find_logger()          # no arguments, cached
        # 3. log if we found one
        if logger is not None:
            getattr(logger, level.lower())(message)

        # 4. display part unchanged
        if sticky:
            self.console.print(message)
        elif self._progress:
            self._progress.update(self._task, description=message)
        else:
            self.console.print(message, end="\r")


# --------------------------------------------------------------------------- #
#  public façade
# --------------------------------------------------------------------------- #
log_manager = ConsoleLogger()


def log_and_display(message: str, sticky: bool = False, level: str = "info", log: bool = True) -> None:
    """Log (if logger bound) + display (rich or plain)."""
    log_manager.log(message, sticky=sticky, level=level, log=log)


def trackerator(items, description: str = "Working..."):
    """Yield items while driving the progress bar."""
    log_manager.start_progress(total=len(items), description=description)
    for idx, item in enumerate(items, start=1):
        yield item
        log_manager.update_progress(advance=1)

