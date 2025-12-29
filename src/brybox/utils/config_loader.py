import json
from pathlib import Path
from typing import Any


class ConfigLoader:
    """Generic configuration loader for JSON config files."""

    @staticmethod
    def load_configs(config_path: str = 'configs', config_files: dict[str, str] | None = None) -> dict[str, Any]:
        """
        Load multiple JSON config files from a directory.

        Args:
            config_path: Path to config directory
            config_files: Dict mapping config keys to filenames
                          e.g., {"rules": "email_rules.json", "paths": "paths.json"}

        Returns:
            Dict with loaded configs. Missing files or invalid JSON → empty dicts.
        """
        config_dir = Path(config_path)
        result: dict[str, Any] = {}

        config_files = config_files or {}

        for key, filename in config_files.items():
            file_path = config_dir / filename
            try:
                with Path(file_path).open(encoding='utf-8') as f:
                    result[key] = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                result[key] = {}

        return result

    @staticmethod
    def load_single_config(config_path: str = 'configs', filename: str | None = None) -> dict[str, Any]:
        """Load a single JSON config file safely."""
        if not filename:
            return {}

        configs = ConfigLoader.load_configs(config_path, {'config': filename})
        return configs.get('config', {})
