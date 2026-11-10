"""Shared pytest helpers: fake HTTP transport and HTML fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The anchors the "today" page must keep for the client to work.
TODAY_ANCHORS = [
    "header-main",
    "location-picker-trigger",
    "sidebar-navigation",
    "subnavigation",
    "current-conditions",
    "current-conditions-temperatures",
    "current-widgets",
    "next-48-hours",
    "daily-forecast",
    "DynamicMap",
    "header-logo",
]

HOURBYHOUR_ANCHORS = [
    "hourly-data-graph",
    "location-picker-trigger",
    "subnavigation",
    "sidebar-navigation",
]

TENDAY_ANCHORS = [
    "daily-forecast",
    "location-picker-trigger",
    "subnavigation",
    "sidebar-navigation",
]

ANCHORS_BY_PAGE = {
    "today": TODAY_ANCHORS,
    "hourbyhour": HOURBYHOUR_ANCHORS,
    "tenday": TENDAY_ANCHORS,
}


def build_page_html(page: str = "today", anchors: list[str] | None = None) -> str:
    """Return a minimal weather.com-shaped document with the given anchors."""
    anchors = ANCHORS_BY_PAGE.get(page, []) if anchors is None else anchors
    sections = "\n".join(
        f'    <div data-testid="{name}"><span class="skeleton">loading</span></div>' for name in anchors
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "  <title>National and Local Weather Radar, Daily Forecast</title>\n"
        "</head>\n<body>\n"
        f"{sections}\n"
        "</body>\n</html>\n"
    )


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, text: str = "", payload: Any = None, status_code: int = 200):
        self.text = text
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON payload")
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Minimal ``requests.Session`` stand-in driven by URL rules.

    ``rules`` maps a URL substring to a :class:`FakeResponse` or to a callable
    receiving the request URL and params.
    """

    def __init__(self, rules: dict[str, Any] | None = None, default: Any = None):
        self.rules = rules or {}
        self.default = default
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> FakeResponse:
        self.calls.append((url, params or {}))
        for needle, response in self.rules.items():
            if needle in url:
                return response(url, params) if callable(response) else response
        if self.default is not None:
            return self.default(url, params) if callable(self.default) else self.default
        raise AssertionError(f"unexpected request to {url}")


@pytest.fixture
def api_payloads() -> dict[str, dict[str, Any]]:
    """Realistic api.weather.com payloads (column oriented)."""
    return {
        "search": {
            "location": {
                "displayName": ["Santiago", "Santiago de Compostela"],
                "city": ["Santiago", "Santiago de Compostela"],
                "adminDistrict": ["Santiago Metropolitan Region", "A Coruna"],
                "country": ["Chile", "Spain"],
                "countryCode": ["CL", "ES"],
                "placeId": ["place-cl-1", "place-es-1"],
                "latitude": [-33.441, 42.88],
                "longitude": [-70.649, -8.542],
                "postalCode": [None, None],
            }
        },
        "current": {
            "temperature": 25,
            "temperatureFeelsLike": 26,
            "wxPhraseLong": "Partly Cloudy",
            "iconCode": 30,
            "relativeHumidity": 44,
            "windSpeed": 11,
            "windDirectionCardinal": "SW",
            "uvIndex": 7,
            "uvDescription": "High",
            "pressureMeanSeaLevel": 1020.1,
            "visibility": 16.0,
            "temperatureDewPoint": 12,
            "observationTimeLocal": "2026-11-10T15:00:00-0300",
        },
        "hourly": {
            "validTimeLocal": [
                "2026-11-10T15:00:00-0300",
                "2026-11-10T16:00:00-0300",
                "2026-11-10T17:00:00-0300",
            ],
            "temperature": [25, 26, 24],
            "wxPhraseShort": ["M Sunny", "M Sunny", "Sunny"],
            "iconCode": [34, 34, 32],
            "precipChance": [0, 0, 0],
        },
        "daily": {
            "dayOfWeek": ["Tuesday", "Wednesday", "Thursday"],
            "narrative": ["Sunny.", "Partly cloudy.", "Rain."],
            "calendarDayTemperatureMax": [26, 31, 15],
            "calendarDayTemperatureMin": [14, 16, 11],
            "daypart": [
                {
                    "dayOrNight": "D",
                    "daypartName": "Day",
                    "iconCode": [32, 30, 12],
                    "precipChance": [0, 5, 90],
                }
            ],
        },
    }


def api_rules(payloads: dict[str, dict[str, Any]], page_html: dict[str, str] | None = None) -> dict[str, Any]:
    """Build FakeSession rules for the API endpoints and page URLs."""
    rules: dict[str, Any] = {
        "/v3/location/search": FakeResponse(payload=payloads["search"]),
        "/v3/wx/observations/current": FakeResponse(payload=payloads["current"]),
        "/v3/wx/forecast/hourly/2day": FakeResponse(payload=payloads["hourly"]),
        "/v3/wx/forecast/daily/10day": FakeResponse(payload=payloads["daily"]),
    }
    for page, html in (page_html or {}).items():
        rules[page] = FakeResponse(text=html)
    return rules


def json_dump(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
