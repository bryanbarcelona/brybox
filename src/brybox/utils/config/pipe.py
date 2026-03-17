from typing import Any

from brybox.utils.config.models import ListOfDicts, PipeModel
from brybox.utils.config.normalizer import NormalizationEngine


class Pipe:
    """
    A named runtime data structure fed from one or more sources.
    All sources are equal — no hierarchy.
    Owns its merged state and tracks which entries came from which source.
    """

    def __init__(self, name: str, model: PipeModel):
        """
        Args:
            name:  Pipe identifier e.g. 'email.rules'
            model: Declared model for this pipe's contents.
        """
        self.name = name
        self.model = model
        self._data: Any = model.empty()
        self._sources: list[str] = []

    def feed(self, data: Any, source_name: str) -> None:
        """
        Merge normalized data into this pipe from a named source.
        Deduplicates against existing entries using model.primary_key.
        First source initializes the pipe, subsequent sources append.

        Args:
            data:        Already-normalized data in the pipe's model shape.
            source_name: Logical filename of the source (no extension).
        """
        if source_name not in self._sources:
            self._sources.append(source_name)

        if self.is_empty():
            self._data = data
            return

        # Merge based on model shape
        if isinstance(self.model, ListOfDicts):
            existing_keys = {self.model.primary_key(e) for e in self._data}
            new_entries = [e for e in data if self.model.primary_key(e) not in existing_keys]
            self._data += new_entries

        elif isinstance(self.model.empty(), dict):
            # DictOfLists, DictOfObjects, FlatDict — merge keys, existing wins on conflict
            merged = dict(data)
            merged.update(self._data)  # existing entries take precedence
            self._data = merged

        else:
            # ListOfStrings — union, re-normalize
            combined = list(set(self._data) | set(data))
            self._data = NormalizationEngine.normalize(combined, self.model)

    def get(self) -> Any:
        """Return the fully merged, normalized pipe contents."""
        return self._data

    def is_empty(self) -> bool:
        """True if no data has been fed into this pipe yet."""
        return self._data == self.model.empty()

    def sources(self) -> list[str]:
        """Return list of source names that have fed this pipe, in feed order."""
        return list(self._sources)
