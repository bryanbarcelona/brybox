import json
from pathlib import Path
from typing import Any, ClassVar

from brybox.utils.config.handlers import BaseFormatHandler, CsvHandler, JsonHandler, XlsxHandler
from brybox.utils.config.models import ListOfDicts, ListOfStrings, PipeModel
from brybox.utils.config.normalizer import NormalizationEngine
from brybox.utils.config.pipe import Pipe


class ConfigLoader:
    """
    Single entry point for all config I/O.
    Manages format detection, pipe registry, normalization and write-back.
    All sources feeding a pipe are treated as equal — no hierarchy.
    """

    # Handler registry — ordered, first match wins on extension lookup
    _handlers: ClassVar[list[BaseFormatHandler]] = [
        JsonHandler(),
        CsvHandler(),
        XlsxHandler(),
    ]

    def __init__(self, search_dirs: list[Path]):
        """
        Args:
            search_dirs: Ordered list of directories to search for config files.
                         Most recently modified match wins across all dirs and extensions.
        """
        self._search_dirs = [d for d in search_dirs if d is not None]
        self._pipes: dict[str, Pipe] = {}
        # Tracks resolved file paths per logical source name for write-back
        self._resolved_paths: dict[str, Path] = {}

    # ── Resolution & dispatch ─────────────────────────────────────────────────

    def _resolve_all(self, logical_name: str) -> list[Path]:
        """
        Find ALL matching files for a logical source name (no extension).
        Returns one path per format found, across all search dirs.
        Most recently modified file wins per extension when duplicates
        exist across multiple search dirs.

        e.g. 'email_delete_list' may return:
            [/configs/email_delete_list.json, /configs/email_delete_list.csv]
        """
        supported_extensions = {ext for handler in self._handlers for ext in handler.supported_extensions()}

        # Group candidates by extension, best (newest) per extension wins
        best_per_ext: dict[str, Path] = {}
        for d in self._search_dirs:
            for ext in supported_extensions:
                candidate = d / f'{logical_name}{ext}'
                if not candidate.exists():
                    continue
                existing = best_per_ext.get(ext)
                if existing is None or candidate.stat().st_mtime > existing.stat().st_mtime:
                    best_per_ext[ext] = candidate

        return list(best_per_ext.values())

    def _get_handler(self, path: Path) -> BaseFormatHandler:
        """Return the appropriate handler for the given file's extension."""
        ext = path.suffix.lower()
        for handler in self._handlers:
            if ext in handler.supported_extensions():
                return handler
        raise ValueError(f"No handler registered for extension '{ext}' (file: {path})")

    # ── Migration helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _is_simple_delete(entry: dict) -> bool:
        """
        Return True if a rule entry is an unconditional DELETE —
        i.e. action is DELETE and no conditions are set.
        These belong in the delete list, not in the rules file.
        """
        return (
            entry.get('action', '').upper() == 'DELETE'
            and not entry.get('subject')
            and not entry.get('has_pdf_attachment')
            and not entry.get('embedded_link')
        )

    @staticmethod
    def _migrate_simple_deletes(
        loaded: dict[str, tuple[Path, PipeModel, Any]],
        rules_name: str,
        delete_list_name: str | None,
        delete_list_dir: Path | None,
        model: PipeModel,
    ) -> dict[str, tuple[Path, PipeModel, Any]]:
        """
        Scan the rules source for unconditional DELETE entries and migrate
        them to the delete list source.

        If the delete list source doesn't exist yet, creates it as a JSON
        flat string list in the same directory as the rules file.

        Args:
            loaded:           Current loaded sources dict (mutated in place).
            rules_name:       Logical name of the rules source e.g. 'email_rules'.
            delete_list_name: Logical name of the delete list source e.g. 'email_delete_list'.
            delete_list_dir:  Directory to create delete list in if it doesn't exist.
            model:            Registered pipe model.

        Returns:
            Updated loaded dict.
        """
        if rules_name not in loaded or not delete_list_name:
            return loaded

        rules_path, rules_source_model, rules_data = loaded[rules_name]

        # Partition rules into simple deletes and everything else
        simple_deletes = [e for e in rules_data if ConfigLoader._is_simple_delete(e)]
        remaining_rules = [e for e in rules_data if not ConfigLoader._is_simple_delete(e)]

        if not simple_deletes:
            return loaded  # nothing to migrate

        # Extract sender strings from simple deletes
        migrated_senders = [e['sender'] for e in simple_deletes if e.get('sender')]

        if delete_list_name in loaded:
            # Merge into existing delete list source
            dl_path, dl_source_model, dl_data = loaded[delete_list_name]
            if isinstance(dl_source_model, ListOfStrings):
                # Source is a flat string list — dl_data is already coerced to list[dict]
                # for the pipe. Merge by primary key to avoid duplicates.
                existing_keys = {model.primary_key(e) for e in dl_data}
                new_entries = [e for e in simple_deletes if model.primary_key(e) not in existing_keys]
                merged = NormalizationEngine.normalize(dl_data + new_entries, model)
                loaded[delete_list_name] = (dl_path, dl_source_model, merged)
            elif isinstance(dl_source_model, ListOfDicts):
                # CSV/XLSX — append as rule dicts, dedup handled by normalize
                existing_keys = {model.primary_key(e) for e in dl_data}
                new_entries = [e for e in simple_deletes if model.primary_key(e) not in existing_keys]
                merged = NormalizationEngine.normalize(dl_data + new_entries, model)
                loaded[delete_list_name] = (dl_path, dl_source_model, merged)
        else:
            # No delete list exists yet — create one as a JSON flat string list
            if delete_list_dir is None:
                return loaded
            new_path = delete_list_dir / f'{delete_list_name}.json'
            # pipe_data must be list[dict] for the pipe — source_model stays
            # ListOfStrings so write-back reverse-coerces to strings on disk
            pipe_data = NormalizationEngine.normalize(
                NormalizationEngine.coerce(sorted(set(migrated_senders)), ListOfStrings(), model),
                model,
            )
            loaded[delete_list_name] = (new_path, ListOfStrings(), pipe_data)

        # Update rules with simple deletes removed
        loaded[rules_name] = (
            rules_path,
            rules_source_model,
            NormalizationEngine.normalize(remaining_rules, model),
        )

        return loaded

    # ── Pipe registration ─────────────────────────────────────────────────────

    def _load_sources(
        self,
        sources: list[str],
        model: PipeModel,
    ) -> dict[str, tuple[Path, PipeModel, Any]]:
        """
        Resolve, read, coerce and normalize all source files for a pipe.
        Returns loaded dict keyed by source_key → (path, source_model, pipe_data).
        Missing, unreadable or incompatible sources are silently skipped.
        """
        loaded: dict[str, tuple[Path, PipeModel, Any]] = {}
        for logical_name in sources:
            paths = self._resolve_all(logical_name)
            if not paths:
                continue
            for path in paths:
                source_key = logical_name if len(paths) == 1 else f'{logical_name}{path.suffix}'
                handler = self._get_handler(path)
                try:
                    raw = handler.read(path)
                except (ValueError, OSError):
                    continue
                source_model = NormalizationEngine.detect_model(raw)
                if type(source_model) is not type(model):
                    try:
                        pipe_data = NormalizationEngine.coerce(raw, source_model, model)
                    except ValueError:
                        continue
                else:
                    pipe_data = raw
                pipe_data = NormalizationEngine.normalize(pipe_data, model)
                loaded[source_key] = (path, source_model, pipe_data)
                self._resolved_paths[source_key] = path
        return loaded

    @staticmethod
    def _run_conflict_resolution(
        loaded: dict[str, tuple[Path, PipeModel, Any]],
        model: PipeModel,
    ) -> dict[str, Any]:
        """
        Run pairwise conflict resolution across all loaded sources.
        Returns resolved_pipe_data keyed by source_key.
        """
        source_keys = list(loaded.keys())
        resolved: dict[str, Any] = {key: pipe_data for key, (_, _, pipe_data) in loaded.items()}
        for i in range(len(source_keys)):
            for j in range(i + 1, len(source_keys)):
                key_a = source_keys[i]
                key_b = source_keys[j]
                resolved[key_a], resolved[key_b] = NormalizationEngine.resolve_conflicts(
                    data_a=resolved[key_a],
                    data_b=resolved[key_b],
                    model=model,
                )
        return resolved

    def _write_back(
        self,
        loaded: dict[str, tuple[Path, PipeModel, Any]],
        resolved: dict[str, Any],
        model: PipeModel,
    ) -> None:
        """
        Write resolved data back to each source file in its native shape.
        Sources with a different native shape are reverse-coerced before writing.
        """
        for source_key, (path, source_model, _) in loaded.items():
            handler = self._get_handler(path)
            pipe_data = resolved[source_key]
            if type(source_model) is not type(model):
                native_data = NormalizationEngine.reverse_coerce(pipe_data, model, source_model)
                final = NormalizationEngine.normalize(native_data, source_model)
            else:
                final = NormalizationEngine.normalize(pipe_data, model)
            handler.write(path, final)

    def register_pipe(
        self,
        name: str,
        model: PipeModel,
        sources: list[str],
    ) -> None:
        """
        Declare a pipe and all its valid sources.

        Orchestrates four phases:
          1. Load — resolve, read, coerce and normalize all sources
          2. Migrate — move unconditional DELETEs from rules to delete list
          3. Resolve — pairwise conflict resolution across sources
          4. Write back — persist normalized data to disk in native shape

        Multiple formats of the same logical source (e.g. both .json and .csv)
        are all loaded and merged. Sources that do not exist are silently skipped.

        Args:
            name:    Pipe identifier e.g. 'email.rules'
            model:   PipeModel instance declaring shape and uniqueness contract.
            sources: Logical filenames (no extension) that feed this pipe.
                     All are equal — no hierarchy.
        """
        loaded = self._load_sources(sources, model)

        if isinstance(model, ListOfDicts) and sources:
            rules_name = sources[0]
            delete_list_name = sources[1] if len(sources) > 1 else None
            delete_list_dir = (
                loaded[delete_list_name][0].parent
                if delete_list_name and delete_list_name in loaded
                else (loaded[rules_name][0].parent if rules_name in loaded else None)
            )
            loaded = self._migrate_simple_deletes(
                loaded=loaded,
                rules_name=rules_name,
                delete_list_name=delete_list_name,
                delete_list_dir=delete_list_dir,
                model=model,
            )

        resolved = ConfigLoader._run_conflict_resolution(loaded, model)
        self._write_back(loaded, resolved, model)

        pipe = Pipe(name=name, model=model)
        for source_key, pipe_data in resolved.items():
            pipe.feed(pipe_data, source_name=source_key)
        self._pipes[name] = pipe

    # ── Runtime access ────────────────────────────────────────────────────────

    def get(self, pipe_name: str) -> Any:
        """
        Return fully merged, normalized pipe contents.
        Returns model.empty() if pipe is unknown or no sources loaded.
        """
        pipe = self._pipes.get(pipe_name)
        return pipe.get() if pipe else {}

    # ── Legacy API ────────────────────────────────────────────────────────────
    # Kept so nothing outside breaks during transition.

    @staticmethod
    def load_configs(
        config_path: str = 'configs',
        config_files: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Load multiple JSON config files from a directory. Legacy interface."""
        config_dir = Path(config_path)
        result: dict[str, Any] = {}
        for key, filename in (config_files or {}).items():
            file_path = config_dir / filename
            try:
                with file_path.open(encoding='utf-8') as f:
                    result[key] = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                result[key] = {}
        return result

    @staticmethod
    def load_single_config(
        config_path: str = 'configs',
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Load a single JSON config file safely. Legacy interface."""
        if not filename:
            return {}
        configs = ConfigLoader.load_configs(config_path, {'config': filename})
        return configs.get('config', {})
