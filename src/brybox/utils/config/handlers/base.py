from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseFormatHandler(ABC):
    """
    Abstract base for all format handlers.
    Each handler owns read and write for one file format.
    All handlers normalize to standard Python structures on read.
    """

    @staticmethod
    @abstractmethod
    def read(path: Path) -> Any:
        """
        Read and parse a config file.
        Returns raw Python structures (list, dict etc.)
        Raises: FileNotFoundError, ValueError on parse failure.
        """
        ...

    @staticmethod
    @abstractmethod
    def write(path: Path, data: Any) -> None:
        """
        Write normalized data back to disk.
        Raises: OSError on write failure.
        """
        ...

    @classmethod
    @abstractmethod
    def supported_extensions(cls) -> set[str]:
        """
        Return the set of file extensions this handler supports.
        Extensions must include the leading dot. e.g. {'.json'}
        """
        ...
