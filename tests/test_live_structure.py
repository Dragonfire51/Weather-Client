"""Live structure checks - the tests that run once every 24 hours.

These hit the real weather.com pages. They are skipped by default so the normal
``pytest`` run stays fast and offline. Enable them with::

    WEATHER_LIVE=1 pytest tests/test_live_structure.py -v

or simply run ``pytest -m live``. The scheduled task described in
``config/daily_check.example.json`` runs ``tools/daily_structure_check.py``,
which performs the same verification and is the recommended automation entry
point (it also writes the CRITICAL report file).
"""

from __future__ import annotations

import os

import pytest

from weather_scraper import STATUS_CRITICAL, WeatherChannelClient, WeatherError

pytestmark = pytest.mark.live

live_only = pytest.mark.skipif(
    os.environ.get("WEATHER_LIVE") != "1",
    reason="set WEATHER_LIVE=1 (or run -m live) to hit the real weather.com",
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    return WeatherChannelClient(log_dir=tmp_path_factory.mktemp("live-logs"), retries=2)


@live_only
def test_live_today_structure_is_unchanged(client):
    result = client.check_structure("today", "USNY0996")
    if result.error:
        pytest.skip(f"weather.com unreachable: {result.error}")
    assert result.status != STATUS_CRITICAL, (
        f"CRITICAL_CHANGE_DETECTED on weather.com/weather/today.\n"
        f"Broken selectors: {result.missing_critical}\n"
        f"Report: {result.report_path}"
    )


@live_only
def test_live_search_returns_locations(client):
    try:
        locations = client.search_locations("New York")
    except WeatherError as exc:  # pragma: no cover - network dependent
        pytest.skip(f"weather.com unreachable: {exc}")
    assert locations, "location search returned no results"
    assert locations[0].place_id


@live_only
def test_live_current_conditions_are_plausible(client):
    try:
        location = client.search_locations("New York")[0]
        current = client.get_current(location)
    except WeatherError as exc:  # pragma: no cover - network dependent
        pytest.skip(f"weather.com unreachable: {exc}")
    assert current.temperature_c is not None
    assert -90 <= current.temperature_c <= 60, "temperature out of physical range"
    assert current.humidity is None or 0 <= current.humidity <= 100
