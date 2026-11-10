"""Unit tests for the Weather Channel data client (network fully faked)."""

from __future__ import annotations

import pytest

from tests.conftest import FakeResponse, FakeSession, api_rules
from weather_scraper import (
    WeatherChannelClient,
    WeatherError,
    format_speed,
    format_temp,
    to_celsius,
    to_fahrenheit,
)


@pytest.fixture
def client(tmp_path, api_payloads, monkeypatch):
    monkeypatch.setattr(WeatherChannelClient, "discover_api_key", lambda self: None)
    session = FakeSession(rules=api_rules(api_payloads))
    return WeatherChannelClient(session=session, log_dir=tmp_path / "logs", retries=1)


def test_search_locations_transposes_columnar_payload(client):
    locations = client.search_locations("Santiago")
    assert [loc.display_name for loc in locations] == ["Santiago", "Santiago de Compostela"]
    assert locations[0].country_code == "CL"
    assert locations[0].geocode == "-33.441,-70.649"
    assert locations[0].label == "Santiago, Santiago Metropolitan Region, Chile"


def test_search_requires_three_characters(client):
    assert client.search_locations("sa") == []
    assert client.session.calls == []


def test_current_conditions_mapping(client, api_payloads):
    location = client.search_locations("Santiago")[0]
    current = client.get_current(location)
    assert current.temperature_c == 25
    assert current.humidity == 44
    assert current.phrase == "Partly Cloudy"
    assert current.icon_code == 30
    assert current.wind_speed_kmh == 11
    assert current.uv_description == "High"


def test_hourly_forecast_uses_local_hour_labels(client):
    location = client.search_locations("Santiago")[0]
    hourly = client.get_hourly(location, hours=3)
    assert [entry.time_label for entry in hourly] == ["3 PM", "4 PM", "5 PM"]
    assert [entry.temperature_c for entry in hourly] == [25, 26, 24]


def test_hourly_forecast_respects_hour_limit(client):
    location = client.search_locations("Santiago")[0]
    assert len(client.get_hourly(location, hours=2)) == 2


def test_daily_forecast_uses_daytime_daypart(client):
    location = client.search_locations("Santiago")[0]
    daily = client.get_daily(location, days=3)
    assert [entry.day_label for entry in daily] == ["Tuesday", "Wednesday", "Thursday"]
    assert [entry.high_c for entry in daily] == [26, 31, 15]
    assert [entry.icon_code for entry in daily] == [32, 30, 12]
    assert [entry.precip_chance for entry in daily] == [0, 5, 90]


def test_api_key_falls_back_to_config_when_discovery_is_offline(tmp_path):
    client = WeatherChannelClient(log_dir=tmp_path, offline=True)
    assert client.api_key == client.config["api"]["key_fallback"]


def test_api_key_is_discovered_from_js_bundle(tmp_path, monkeypatch):
    html = '<html><script src="/_next/static/immutable/chunks/abc.js"></script></html>'
    js = 'x={query:e,apiKey:"0123456789abcdef0123456789abcdef"};'
    session = FakeSession(
        rules={
            "weather.com/weather/today": FakeResponse(text=html),
            "/_next/static/immutable/chunks/abc.js": FakeResponse(text=js),
        }
    )
    client = WeatherChannelClient(session=session, log_dir=tmp_path)
    assert client.api_key == "0123456789abcdef0123456789abcdef"


def test_retries_then_succeeds(tmp_path, api_payloads, monkeypatch):
    monkeypatch.setattr("weather_scraper.time.sleep", lambda _s: None)
    attempts = {"n": 0}

    def flaky(url, params):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return FakeResponse(text="", status_code=503)
        return FakeResponse(payload=api_payloads["search"])

    session = FakeSession(rules={"/v3/location/search": flaky})
    client = WeatherChannelClient(session=session, log_dir=tmp_path, retries=3)
    client._api_key = "test"
    assert client.search_locations("Santiago")
    assert attempts["n"] == 2


def test_retries_exhausted_raises_weather_error(tmp_path, monkeypatch):
    monkeypatch.setattr("weather_scraper.time.sleep", lambda _s: None)
    session = FakeSession(rules={"/v3/location/search": FakeResponse(status_code=500)})
    client = WeatherChannelClient(session=session, log_dir=tmp_path, retries=2)
    client._api_key = "test"
    with pytest.raises(WeatherError):
        client.search_locations("Santiago")


@pytest.mark.parametrize(
    "celsius,expected",
    [(0, 32), (25, 77), (37, 99), (-40, -40)],
)
def test_temperature_conversions(celsius, expected):
    assert round(to_fahrenheit(celsius)) == expected


def test_format_temp_and_speed_units():
    assert format_temp(25, "C") == "25°C"
    assert format_temp(25, "F") == "77°F"
    assert format_temp(None) == "--"
    assert format_speed(10, "C") == "10 km/h"
    assert format_speed(10, "F") == "6 mph"


def test_to_celsius_roundtrip():
    assert round(to_celsius(to_fahrenheit(21.5)), 1) == 21.5
