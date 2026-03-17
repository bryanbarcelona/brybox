from abc import ABC, abstractmethod
from typing import Any


class PipeModel(ABC):
    """
    Declares the expected shape and uniqueness contract of a pipe's contents.
    Used by NormalizationEngine for coercion, deduplication and sort decisions.
    """

    @staticmethod
    @abstractmethod
    def primary_key(entry: Any) -> Any:
        """Extract the deduplication key from a single entry."""
        ...

    @staticmethod
    @abstractmethod
    def empty() -> Any:
        """Return an appropriate empty structure for this model."""
        ...

    @staticmethod
    @abstractmethod
    def is_compatible(data: Any) -> bool:
        """Return True if data matches the expected shape for this model."""
        ...


class ListOfStrings(PipeModel):
    """
    Flat list of strings.
    Primary key is the string itself (lowercased, stripped).

    Typical sources: email_delete_list.json
    Coercible into:  ListOfDicts (each string becomes a minimal DELETE rule dict)
    """

    @staticmethod
    def primary_key(entry: str) -> str:
        return entry.strip().lower()

    @staticmethod
    def empty() -> list:
        return []

    @staticmethod
    def is_compatible(data: Any) -> bool:
        return isinstance(data, list) and all(isinstance(i, str) for i in data)


class ListOfDicts(PipeModel):
    """
    List of dicts with a composite primary key.
    Deduplication is based on the declared key field(s).

    Typical sources: email_rules.json, email_delete_list.csv
    Primary key:     single field e.g. 'sender'
                     or composite tuple e.g. ('sender', 'subject')
    """

    def __init__(self, key: str | tuple[str, ...]):
        """
        Args:
            key: Single field name or tuple of field names that together
                 form a unique key. e.g. 'sender' or ('sender', 'subject')
        """
        self._key = (key,) if isinstance(key, str) else key

    def primary_key(self, entry: dict) -> tuple:
        return tuple(entry.get(k) for k in self._key)

    @staticmethod
    def empty() -> list:
        return []

    @staticmethod
    def is_compatible(data: Any) -> bool:
        return isinstance(data, list) and all(isinstance(i, dict) for i in data)

    @property
    def key_fields(self) -> tuple[str, ...]:
        """The field names that make up the primary key."""
        return self._key


class DictOfLists(PipeModel):
    """
    Dict whose values are lists of strings.
    Top-level keys are unique. Inner list entries are unique strings.

    Typical sources: extraction_rules.json, metadata_triggers.json
    Normalization:   sort top-level keys, sort+dedupe each inner list
    """

    @staticmethod
    def primary_key(entry: Any) -> Any:
        return entry

    @staticmethod
    def empty() -> dict:
        return {}

    @staticmethod
    def is_compatible(data: Any) -> bool:
        return isinstance(data, dict) and all(
            isinstance(v, list) and all(isinstance(i, str) for i in v) for v in data.values()
        )


class DictOfObjects(PipeModel):
    """
    Dict whose values are complex nested dicts.
    Top-level keys are unique. Internals are not touched.

    Typical sources: doctopus_sorting_rules.json, audiora_rules.json
    Normalization:   sort top-level keys only
    """

    @staticmethod
    def primary_key(entry: Any) -> Any:
        return entry

    @staticmethod
    def empty() -> dict:
        return {}

    @staticmethod
    def is_compatible(data: Any) -> bool:
        return isinstance(data, dict) and all(isinstance(v, dict) for v in data.values())


class FlatDict(PipeModel):
    """
    Simple flat key-value dict.
    Keys are unique. Values are scalars (strings, numbers, paths).

    Typical sources: paths.json, pixelporter_paths.json
    Normalization:   sort top-level keys only, values untouched
    """

    @staticmethod
    def primary_key(entry: Any) -> Any:
        return entry

    @staticmethod
    def empty() -> dict:
        return {}

    @staticmethod
    def is_compatible(data: Any) -> bool:
        return isinstance(data, dict) and all(not isinstance(v, (dict, list)) for v in data.values())
