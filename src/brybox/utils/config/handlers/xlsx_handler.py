from pathlib import Path
from typing import Any

from brybox.utils.config.handlers.base import BaseFormatHandler


class XlsxHandler(BaseFormatHandler):
    """
    Handles .xlsx files.
    Reads first sheet, first row as headers → list[dict].
    Empty cells are treated as None (field absent, not empty string).
    'action' column defaults to 'DELETE' if the column is absent entirely.
    Writes back to first sheet preserving header order.

    Not yet implemented — stub reserved for near-future implementation.
    """

    @staticmethod
    def read(path: Path) -> list[dict[str, Any]]:
        raise NotImplementedError('XlsxHandler is not yet implemented.')

    @staticmethod
    def write(path: Path, data: Any) -> None:
        raise NotImplementedError('XlsxHandler is not yet implemented.')

    @classmethod
    def supported_extensions(cls) -> set[str]:
        return {'.xlsx'}
