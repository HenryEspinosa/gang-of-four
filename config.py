"""Local configuration: API key and council settings.

Stored under the platform's standard per-user config directory, resolved via
Qt's QStandardPaths so the app uses the native location on each OS:
  - Linux:   ~/.config/perplexity-council/config.json
  - Windows: %LOCALAPPDATA%\\perplexity-council\\config.json
  - macOS:   ~/Library/Preferences/perplexity-council/config.json

The API key can also be provided via the PERPLEXITY_API_KEY environment
variable, which takes precedence on load if the stored value is empty.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths

# Folder name kept stable (not renamed to the app's display name) so existing
# installs keep their saved key and settings after the move to QStandardPaths.
APP_DIR_NAME = "perplexity-council"


def config_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.GenericConfigLocation)
    return Path(base) / APP_DIR_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


DEFAULTS = {
    "api_key": "",
    "council_models": [
        "sonar-reasoning-pro",
        "openai/gpt-5.5",
        "google/gemini-3.1-pro-preview",
    ],
    "synth_model": "sonar-pro",
    "temperature": 0.2,
    "search_mode": "web",
    "font_size": 14,
    "council_enabled": True,
    "single_model": "sonar-pro",
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    path = config_path()
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("PERPLEXITY_API_KEY", "")
    # Guard against a config that left no models selected.
    if not cfg.get("council_models"):
        cfg["council_models"] = list(DEFAULTS["council_models"])
    return cfg


def save(cfg: dict) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(cfg, indent=2))
