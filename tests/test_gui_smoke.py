"""Headless smoke tests for the Tkinter interface.

Skipped automatically when no display is available (CI without Xvfb). Run with::

    xvfb-run -a pytest tests/test_gui_smoke.py -v
"""

from __future__ import annotations

import tkinter as tk

import pytest

from tests.conftest import (
    FakeResponse,
    FakeSession,
    api_rules,
    load_fixture,
)
from weather_scraper import WeatherChannelClient

pytestmark = pytest.mark.gui


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no display available: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def gui(tk_root, tmp_path, api_payloads, monkeypatch):
    import weather_desktop

    monkeypatch.setattr(weather_desktop, "SETTINGS_PATH", tmp_path / "config" / "user_settings.json")
    monkeypatch.setattr(WeatherChannelClient, "discover_api_key", lambda self: None)
    pages = {"today": load_fixture("weather_today_ok.html")}
    rules = api_rules(api_payloads, pages)
    rules["/weather/today/"] = FakeResponse(text=load_fixture("weather_today_ok.html"))
    client = WeatherChannelClient(session=FakeSession(rules=rules), log_dir=tmp_path / "logs")
    app = weather_desktop.WeatherChannelDesktop(tk_root, client=client)
    return app


def test_window_uses_xp_luna_colours(gui):
    assert gui.root.cget("bg") == "#D6E3F7"


def test_sidebar_exposes_all_sections(gui):
    assert set(gui._nav_buttons) == {"weather", "hourly", "daily", "maps", "settings"}


def test_every_view_renders_without_error(gui):
    for view in ("weather", "hourly", "daily", "maps", "settings"):
        gui.show_view(view)
        gui.root.update_idletasks()
        assert gui.active_view == view


def test_unit_toggle_switches_celsius_and_fahrenheit(gui):
    gui.show_view("settings")
    gui.unit_var.set("F")
    gui.apply_unit_change()
    assert gui.unit == "F"
    assert gui.lbl_unit.cget("text") == "°F"
    gui.unit_var.set("C")
    gui.apply_unit_change()
    assert gui.lbl_unit.cget("text") == "°C"


def test_set_location_updates_header_and_persists(gui, api_payloads):
    from weather_scraper import Location

    gui.set_location(Location.from_dict({"display_name": "Santiago", "place_id": "p1", "country": "Chile"}))
    assert "Santiago" in gui.lbl_location.cget("text")
    import json

    import weather_desktop

    saved = json.loads(weather_desktop.SETTINGS_PATH.read_text())
    assert saved["location"]["display_name"] == "Santiago"


def test_location_manager_opens_and_closes(gui):
    before = len(gui.root.winfo_children())
    gui.open_location_manager()
    gui.root.update_idletasks()
    toplevels = [w for w in gui.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert toplevels, "location manager window was not created"
    for window in toplevels:
        window.destroy()
    assert len(gui.root.winfo_children()) == before


def test_icon_set_is_loaded(gui):
    assert len(gui.icons) >= 14
    assert "sunny" in gui.icons
