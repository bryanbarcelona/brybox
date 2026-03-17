from typing import Any

from brybox.utils.config.models import (
    DictOfLists,
    DictOfObjects,
    FlatDict,
    ListOfDicts,
    ListOfStrings,
    PipeModel,
)


class NormalizationEngine:
    """
    Normalizes, sorts and deduplicates data according to its model.
    Handles coercion between compatible shapes and conflict resolution
    across sources feeding the same pipe.
    """

    # ── Shape Detection ───────────────────────────────────────────────────────

    @staticmethod
    def detect_model(data: Any) -> PipeModel:
        """
        Inspect data and return the matching PipeModel instance.

        Detection rules (evaluated in order):
          list, all items str              → ListOfStrings
          list, all items dict             → ListOfDicts(key='sender') as default
          dict, all values list of str     → DictOfLists
          dict, all values dict            → DictOfObjects
          dict, all values scalar          → FlatDict
        """
        if isinstance(data, list):
            if not data or all(isinstance(i, str) for i in data):
                return ListOfStrings()
            if all(isinstance(i, dict) for i in data):
                return ListOfDicts(key='sender')
        if isinstance(data, dict):
            if not data or all(not isinstance(v, (dict, list)) for v in data.values()):
                return FlatDict()
            values = list(data.values())
            if all(isinstance(v, list) and all(isinstance(i, str) for i in v) for v in values):
                return DictOfLists()
            if all(isinstance(v, dict) for v in values):
                return DictOfObjects()
        return FlatDict()  # safe fallback

    # ── Coercion ──────────────────────────────────────────────────────────────

    @staticmethod
    def coerce(data: Any, source_model: PipeModel, target_model: PipeModel) -> Any:
        """
        Coerce data from source_model shape to target_model shape.

        Supported coercions:
          ListOfStrings → ListOfDicts   each string becomes a minimal DELETE rule dict
          ListOfDicts   → ListOfDicts   no-op, already correct shape

        Raises ValueError for unsupported combinations.
        """
        if isinstance(source_model, ListOfDicts) and isinstance(target_model, ListOfDicts):
            return data

        if isinstance(source_model, ListOfStrings) and isinstance(target_model, ListOfDicts):
            return [NormalizationEngine._sender_to_delete_rule(s) for s in data if isinstance(s, str) and s.strip()]

        raise ValueError(f'No coercion path from {type(source_model).__name__} to {type(target_model).__name__}.')

    @staticmethod
    def reverse_coerce(data: Any, source_model: PipeModel, target_model: PipeModel) -> Any:
        """
        Reverse-coerce data from pipe model shape back to a source's native shape
        for write-back purposes.

        Supported reverse coercions:
          ListOfDicts → ListOfStrings   extract the 'sender' field from each DELETE rule dict
        """
        if isinstance(source_model, ListOfDicts) and isinstance(target_model, ListOfStrings):
            return [entry['sender'] for entry in data if isinstance(entry, dict) and 'sender' in entry]

        raise ValueError(
            f'No reverse coercion path from {type(source_model).__name__} to {type(target_model).__name__}.'
        )

    @staticmethod
    def _sender_to_delete_rule(sender: str) -> dict:
        """
        Convert a raw sender string to a fully formed DELETE rule dict.
        e.g. 'foo@bar.de' → {'domain': 'bar', 'sender': 'foo@bar.de', 'action': 'DELETE'}
        """
        sender = sender.strip().lower()
        try:
            hostname = sender.split('@')[1]
            domain = hostname.rsplit('.', 1)[0]
        except IndexError:
            domain = sender
        return {'domain': domain, 'sender': sender, 'action': 'DELETE'}

    # ── Normalization ─────────────────────────────────────────────────────────

    @staticmethod
    def normalize(data: Any, model: PipeModel) -> Any:
        """
        Sort and deduplicate data according to its model.
        Returns a new normalized structure — does not mutate input.

        ListOfStrings  → sorted, deduped, lowercased, stripped
        ListOfDicts    → sorted by primary_key, deduped by primary_key
        DictOfLists    → keys sorted, each inner list sorted+deduped
        DictOfObjects  → keys sorted, values untouched
        FlatDict       → keys sorted, values untouched
        """
        if isinstance(model, ListOfStrings):
            return sorted({s.strip().lower() for s in data if isinstance(s, str) and s.strip()})

        if isinstance(model, ListOfDicts):
            seen: dict[Any, dict[str, Any]] = {}
            for entry in data:
                row: dict[str, Any] = entry
                k = model.primary_key(row)
                if k not in seen:
                    seen[k] = row
            return sorted(
                seen.values(),
                key=lambda e: tuple((v or '') if not isinstance(v, str) else v.lower() for v in model.primary_key(e)),
            )

        if isinstance(model, DictOfLists):
            return {k: sorted(set(v)) for k, v in sorted(data.items())}

        if isinstance(model, (DictOfObjects, FlatDict)):
            return dict(sorted(data.items()))

        return data  # unknown model — return as-is

    # ── Conflict Resolution ───────────────────────────────────────────────────

    @staticmethod
    def resolve_conflicts(
        data_a: Any,
        data_b: Any,
        model: PipeModel,
    ) -> tuple[Any, Any]:
        """
        Resolve conflicts between two sources feeding the same pipe.
        Returns (resolved_a, resolved_b) for write-back to each source file.

        Conflict rules for ListOfDicts with an 'action' field:

          Same primary key, both DELETE, no conditions
            → migrate to data_b (delete list), remove from data_a (rules)

          Same primary key, DELETE + subject/conditions in data_a
            → keep in data_a, remove from data_b

          Same primary key, non-DELETE in data_a vs DELETE in data_b
            → keep non-DELETE in data_a, remove from data_b

        All other models: no meaningful conflict possible — return inputs unchanged.
        """
        if not (isinstance(model, ListOfDicts) and isinstance(data_a, list) and isinstance(data_b, list)):
            return data_a, data_b

        # Index data_b by primary key for fast lookup
        index_b: dict[Any, dict[str, Any]] = {model.primary_key(e): e for e in data_b}

        resolved_a: list[dict[str, Any]] = []
        resolved_b: list[dict[str, Any]] = [dict(e) for e in data_b]

        for entry_a in data_a:
            row_a: dict[str, Any] = entry_a
            key = model.primary_key(row_a)

            if key not in index_b:
                resolved_a.append(row_a)
                continue

            entry_b = index_b[key]
            action_a = (row_a.get('action') or '').upper()
            action_b = (entry_b.get('action') or '').upper()  # noqa: F841 — reserved for future asymmetric action handling
            has_conditions = any(row_a.get(f) for f in ('subject', 'has_pdf_attachment', 'embedded_link'))

            if action_a == 'DELETE' and not has_conditions:
                # Pure duplicate delete — belongs in delete list, remove from rules
                resolved_b = [e for e in resolved_b if model.primary_key(e) != key]
                resolved_b.append(entry_b)
                # Drop from rules (do not append to resolved_a)
            else:
                # Conditional delete or non-delete — rules wins, remove from delete list
                resolved_a.append(row_a)
                resolved_b = [e for e in resolved_b if model.primary_key(e) != key]

        return resolved_a, resolved_b
