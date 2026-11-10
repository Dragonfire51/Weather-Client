"""Packaging layout tests: bundled vs. frozen resource resolution."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

import paths


def test_source_layout_uses_package_dir():
    assert not paths.is_frozen()
    assert paths.resource_dir() == Path(paths.__file__).resolve().parent
    assert paths.DATA_DIR == Path(paths.__file__).resolve().parent
    assert paths.ICON_DIR == paths.RESOURCE_DIR / "icons"
    assert paths.DEFAULT_LOG_DIR == paths.DATA_DIR / "logs"


def test_bundled_config_exists_in_source():
    assert paths.BUNDLED_CONFIG_PATH.exists()
    assert paths.DEFAULT_CONFIG_PATH.exists()


def test_frozen_resources_come_from_meipass(tmp_path, monkeypatch):
    meipass = tmp_path / "bundle"
    (meipass / "icons").mkdir(parents=True)
    appdata = tmp_path / "AppData"
    appdata.mkdir()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))

    reloaded = importlib.reload(paths)
    try:
        assert reloaded.is_frozen()
        assert reloaded.resource_dir() == meipass
        assert reloaded.ICON_DIR == meipass / "icons"
        assert reloaded.DATA_DIR == appdata / "WeatherChannelDesktop"
        assert reloaded.SETTINGS_PATH == reloaded.DATA_DIR / "config" / "user_settings.json"
        assert reloaded.DEFAULT_LOG_DIR == reloaded.DATA_DIR / "logs"
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        importlib.reload(paths)


def test_seed_user_config_copies_bundled_registry(tmp_path, monkeypatch):
    bundled = tmp_path / "bundle" / "config" / "selectors.json"
    bundled.parent.mkdir(parents=True)
    bundled.write_text('{"version": 2}', encoding="utf-8")
    user = tmp_path / "data" / "config" / "selectors.json"

    monkeypatch.setattr(paths, "BUNDLED_CONFIG_PATH", bundled)
    monkeypatch.setattr(paths, "USER_CONFIG_PATH", user)

    assert paths.seed_user_config() == user
    assert user.read_text(encoding="utf-8") == '{"version": 2}'
    # A second call is a no-op and must not clobber user edits.
    user.write_text('{"version": 3}', encoding="utf-8")
    assert paths.seed_user_config() is None
    assert user.read_text(encoding="utf-8") == '{"version": 3}'


def test_resolve_config_prefers_user_copy(tmp_path, monkeypatch):
    bundled = tmp_path / "bundle.json"
    bundled.write_text("{}", encoding="utf-8")
    user = tmp_path / "user.json"
    monkeypatch.setattr(paths, "BUNDLED_CONFIG_PATH", bundled)
    monkeypatch.setattr(paths, "USER_CONFIG_PATH", user)

    assert paths.resolve_config_path() == bundled
    user.write_text("{}", encoding="utf-8")
    assert paths.resolve_config_path() == user


@pytest.mark.gui
def test_client_and_gui_boot_with_seeded_config(tmp_path, monkeypatch):
    """Smoke: the frozen-style config seeding path builds a usable client."""
    from weather_scraper import WeatherChannelClient

    bundled = paths.BUNDLED_CONFIG_PATH
    user = tmp_path / "config" / "selectors.json"
    monkeypatch.setattr(paths, "BUNDLED_CONFIG_PATH", bundled)
    monkeypatch.setattr(paths, "USER_CONFIG_PATH", user)

    paths.seed_user_config()
    client = WeatherChannelClient(config_path=paths.resolve_config_path(), log_dir=tmp_path / "logs")
    assert client.config["pages"]["today"]["strict"] is True
