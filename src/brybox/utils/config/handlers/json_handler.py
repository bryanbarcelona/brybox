import json
from pathlib import Path
from typing import Any

from brybox.utils.config.handlers.base import BaseFormatHandler


class JsonHandler(BaseFormatHandler):
    """
    Handles .json files.
    Reads any valid JSON structure into native Python types.
    Writes back with 2-space indent and ensure_ascii=False to preserve
    unicode characters (e.g. German umlauts in sender addresses).
    """

    @staticmethod
    def read(path: Path) -> Any:
        """
        Read and parse a JSON file.
        Raises: FileNotFoundError if path does not exist.
                ValueError if content is not valid JSON.
        """
        try:
            with path.open(encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f'Invalid JSON in {path}: {e}') from e

    @staticmethod
    def write(path: Path, data: Any) -> None:
        """Write data back to disk as formatted JSON."""
        with path.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def supported_extensions(cls) -> set[str]:
        return {'.json'}
