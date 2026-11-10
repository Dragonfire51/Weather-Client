"""Filesystem layout, frozen-aware.

Running from source everything lives next to the package. Running as a
PyInstaller one-file ``.exe`` the read-only resources (icons, selectors) are
unpacked into a temporary ``sys._MEIPASS`` directory that is deleted on exit,
so writable state (settings, logs) must live in the user profile instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "WeatherChannelDesktop"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Directory holding read-only bundled resources (icons, config)."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """Directory for writable state (settings, logs, HTML snapshots)."""
    if is_frozen():
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / f".{APP_NAME.lower()}"
    return Path(__file__).resolve().parent


RESOURCE_DIR = resource_dir()
DATA_DIR = data_dir()

BUNDLED_CONFIG_PATH = RESOURCE_DIR / "config" / "selectors.json"
USER_CONFIG_PATH = DATA_DIR / "config" / "selectors.json"
DEFAULT_LOG_DIR = DATA_DIR / "logs"
SETTINGS_PATH = DATA_DIR / "config" / "user_settings.json"
ICON_DIR = RESOURCE_DIR / "icons"


def resolve_config_path() -> Path:
    """Prefer the user-editable selector registry, fall back to the bundle.

    When a critical-change report tells you a selector moved, editing the copy
    under the data directory is enough: no rebuild required.
    """
    if USER_CONFIG_PATH.exists():
        return USER_CONFIG_PATH
    return BUNDLED_CONFIG_PATH


def seed_user_config() -> Path | None:
    """Copy the bundled selector registry into the writable data directory once."""
    if USER_CONFIG_PATH.exists() or not BUNDLED_CONFIG_PATH.exists():
        return None
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_PATH.write_bytes(BUNDLED_CONFIG_PATH.read_bytes())
    return USER_CONFIG_PATH


DEFAULT_CONFIG_PATH = resolve_config_path()
