from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from brybox.utils.config import ConfigLoader
from brybox.utils.config.models import DictOfLists, DictOfObjects, FlatDict, ListOfDicts
from brybox.utils.credentials import CredentialsManager

# ── Config source names (no extension — format is resolved at runtime) ────────
CF_AUDIORA_RULES = 'audiora_rules'
CF_DOCTOPUS_SORTING = 'doctopus_sorting_rules'
CF_EXTRACTION_RULES = 'extraction_rules'
CF_METADATA_TRIGGERS = 'metadata_triggers'
CF_PATHS = 'paths'
CF_EMAIL_RULES = 'email_rules'
CF_EMAIL_DELETE_LIST = 'email_delete_list'
CF_PIXELPORTER_PATHS = 'pixelporter_paths'
CF_DOISMITH_PATHS = 'doismith_paths'


class BryboxSettings:
    _instance = None

    def __new__(cls, *args, **kwargs):
        """Standard Python Singleton: ensures only one instance ever exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, explicit_path: str | None = None):
        if self._initialized:
            return

        search_dirs = [
            Path(explicit_path) if explicit_path else None,
            Path(user_config_dir('brybox')),
            Path.cwd() / 'configs',
        ]
        search_dirs = [p for p in search_dirs if p]

        self.creds = CredentialsManager()
        self._loader = ConfigLoader(search_dirs)
        self._register_pipes()
        self._initialized = True

    def _register_pipes(self) -> None:
        """Declare all pipes and their sources. Called once on startup."""

        self._loader.register_pipe(
            name='audiora.categories',
            model=DictOfObjects(),
            sources=[CF_AUDIORA_RULES],
        )
        self._loader.register_pipe(
            name='doctopus.categories',
            model=DictOfObjects(),
            sources=[CF_DOCTOPUS_SORTING],
        )
        self._loader.register_pipe(
            name='doctopus.extraction_rules',
            model=DictOfLists(),
            sources=[CF_EXTRACTION_RULES],
        )
        self._loader.register_pipe(
            name='doctopus.metadata_triggers',
            model=DictOfLists(),
            sources=[CF_METADATA_TRIGGERS],
        )
        self._loader.register_pipe(
            name='email.paths',
            model=FlatDict(),
            sources=[CF_PATHS],
        )
        self._loader.register_pipe(
            name='email.rules',
            model=ListOfDicts(key=('domain', 'sender', 'subject')),
            sources=[CF_EMAIL_RULES, CF_EMAIL_DELETE_LIST],
        )
        self._loader.register_pipe(
            name='pixelporter.paths',
            model=FlatDict(),
            sources=[CF_PIXELPORTER_PATHS],
        )
        self._loader.register_pipe(
            name='literature.paths',
            model=FlatDict(),
            sources=[CF_PATHS],
        )

    # ── Public API (unchanged) ────────────────────────────────────────────────

    @property
    def audiora(self) -> dict[str, Any]:
        return {
            'categories': self._loader.get('audiora.categories'),
        }

    @property
    def doctopus(self) -> dict[str, Any]:
        return {
            'categories': self._loader.get('doctopus.categories'),
            'extraction_rules': self._loader.get('doctopus.extraction_rules'),
            'metadata_triggers': self._loader.get('doctopus.metadata_triggers'),
        }

    @property
    def email(self) -> dict[str, Any]:
        return {
            'paths': self._loader.get('email.paths'),
            'rules': self._loader.get('email.rules'),
        }

    @property
    def motionporter(self) -> dict[str, Any]:
        return {'paths': self._loader.get('pixelporter.paths')}

    @property
    def pixelporter(self) -> dict[str, Any]:
        return {'paths': self._loader.get('pixelporter.paths')}

    @property
    def doismith(self) -> dict[str, Any]:
        return {'target_dir': self._loader.get('literature.paths').get('literature_dir')}
