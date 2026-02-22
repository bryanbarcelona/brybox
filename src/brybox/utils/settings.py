from pathlib import Path
from platformdirs import user_config_dir
from typing import Any

from brybox.utils.config_loader import ConfigLoader
from brybox.utils.credentials import CredentialsManager


class BryboxSettings:
    _instance = None

    def __new__(cls, *args, **kwargs):
        """Standard Python Singleton: ensures only one instance ever exists."""
        if cls._instance is None:
            cls._instance = super(BryboxSettings, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, explicit_path: str | None = None):
        if self._initialized:
            return

        self.search_dirs = [
            Path(explicit_path) if explicit_path else None,
            Path(user_config_dir('brybox')),
            Path.cwd() / 'configs',
        ]
        self.search_dirs = [p for p in self.search_dirs if p]
        self.creds = CredentialsManager()
        self._cache = {}
        self._initialized = True

    def _get_best_file_path(self, filename: str) -> Path | None:
        candidates = [d / filename for d in self.search_dirs if (d / filename).exists()]
        return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

    def _load_component(self, filename: str) -> dict[str, Any]:
        if filename not in self._cache:
            best_path = self._get_best_file_path(filename)
            if best_path:
                self._cache[filename] = ConfigLoader.load_single_config(
                    config_path=str(best_path.parent), filename=filename
                )
            else:
                self._cache[filename] = {}
        return self._cache[filename]

    @property
    def audiora(self) -> dict[str, Any]:
        return {'categories': self._load_component('audiora_rules.json')}

    @property
    def doctopus(self) -> dict[str, Any]:
        return {
            'categories': self._load_component('doctopus_sorting_rules.json'),
            'extraction_rules': self._load_component('extraction_rules.json'),
            'metadata_triggers': self._load_component('metadata_triggers.json'),
        }

    @property
    def email(self) -> dict[str, Any]:
        return {
            'paths': self._load_component('paths.json'),
            'rules': self._load_component('email_rules.json'),
        }

    @property
    def motionporter(self) -> dict[str, Any]:
        return {'paths': self._load_component('pixelporter_paths.json')}

    @property
    def pixelporter(self) -> dict[str, Any]:
        return {'paths': self._load_component('pixelporter_paths.json')}
