"""App-level user settings (last opened folder, etc.).

Stored as JSON in ~/.lumalapse/settings.json (override the directory with the
LUMALAPSE_CONFIG_DIR environment variable, mainly for tests).
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _settings_path() -> Path:
    base = os.environ.get("LUMALAPSE_CONFIG_DIR")
    root = Path(base) if base else Path.home() / ".lumalapse"
    return root / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def update_settings(**values) -> None:
    data = load_settings()
    data.update(values)
    path = _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass  # settings are a convenience; never break the app over them
