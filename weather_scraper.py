"""Weather Channel client: data extraction + HTML structure watchdog.

Two data sources are used, both owned by weather.com:

1. ``api.weather.com`` - the JSON API the weather.com web app itself calls.
   It gives clean, stable data for current conditions and forecasts.
2. The public web pages - fetched only to verify that the CSS/DOM anchors the
   app depends on are still present. weather.com is a Next.js SPA, so the
   payload is rendered client side, but the ``data-testid`` anchors are
   server rendered and act as a cheap canary for layout drift.

When a *critical* selector disappears the verifier raises
``CRITICAL_CHANGE_DETECTED`` and writes a self-contained report (raw HTML
snapshot + diff-friendly selector map) so the selectors can be re-trained
quickly.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

import paths

LOGGER = logging.getLogger("weather_scraper")

DEFAULT_CONFIG_PATH = paths.DEFAULT_CONFIG_PATH
DEFAULT_LOG_DIR = paths.DEFAULT_LOG_DIR

STATUS_OK = "OK"
STATUS_WARNING = "WARNING_SELECTOR_MISSING"
STATUS_CRITICAL = "CRITICAL_CHANGE_DETECTED"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# weather.com occasionally rate limits rapid successive requests.
RETRY_STATUSES = {429, 500, 502, 503, 504}


class WeatherError(RuntimeError):
    """Raised when weather data cannot be retrieved at all."""


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #
def to_fahrenheit(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32.0) * 5.0 / 9.0


def format_temp(value: float | None, unit: str = "C") -> str:
    """Render a temperature using the requested display unit."""
    if value is None:
        return "--"
    unit = unit.upper()
    if unit.startswith("F"):
        celsius = float(value)
        return f"{round(to_fahrenheit(celsius))}°F"
    return f"{round(float(value))}°C"


def format_speed(value_kmh: float | None, unit: str = "C") -> str:
    if value_kmh is None:
        return "--"
    if unit.upper().startswith("F"):
        return f"{round(float(value_kmh) * 0.621371)} mph"
    return f"{round(float(value_kmh))} km/h"


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Location:
    """A resolved Weather Channel location."""

    display_name: str
    place_id: str
    city: str = ""
    admin_district: str = ""
    country: str = ""
    country_code: str = ""
    postal_code: str = ""
    latitude: float | None = None
    longitude: float | None = None

    @property
    def label(self) -> str:
        parts = [self.display_name or self.city]
        if self.admin_district and self.admin_district not in parts:
            parts.append(self.admin_district)
        if self.country:
            parts.append(self.country)
        return ", ".join(p for p in parts if p)

    @property
    def geocode(self) -> str | None:
        if self.latitude is None or self.longitude is None:
            return None
        return f"{self.latitude},{self.longitude}"

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> Location:
        return cls(
            display_name=item.get("displayName") or item.get("city") or "",
            place_id=item.get("placeId") or "",
            city=item.get("city") or "",
            admin_district=item.get("adminDistrict") or "",
            country=item.get("country") or "",
            country_code=item.get("countryCode") or "",
            postal_code=item.get("postalCode") or "",
            latitude=_as_float(item.get("latitude")),
            longitude=_as_float(item.get("longitude")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "place_id": self.place_id,
            "city": self.city,
            "admin_district": self.admin_district,
            "country": self.country,
            "country_code": self.country_code,
            "postal_code": self.postal_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Location:
        return cls(
            display_name=data.get("display_name", ""),
            place_id=data.get("place_id", ""),
            city=data.get("city", ""),
            admin_district=data.get("admin_district", ""),
            country=data.get("country", ""),
            country_code=data.get("country_code", ""),
            postal_code=data.get("postal_code", ""),
            latitude=_as_float(data.get("latitude")),
            longitude=_as_float(data.get("longitude")),
        )


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class CurrentConditions:
    """Current observation for a location (metric values)."""

    location: Location
    temperature_c: float | None = None
    feels_like_c: float | None = None
    phrase: str = ""
    icon_code: int | None = None
    humidity: int | None = None
    wind_speed_kmh: float | None = None
    wind_direction: str = ""
    uv_index: int | None = None
    uv_description: str = ""
    pressure_mb: float | None = None
    visibility_km: float | None = None
    dew_point_c: float | None = None
    observed_at: str = ""

    @classmethod
    def from_api(cls, location: Location, data: dict[str, Any]) -> CurrentConditions:
        return cls(
            location=location,
            temperature_c=_as_float(data.get("temperature")),
            feels_like_c=_as_float(data.get("temperatureFeelsLike")),
            phrase=data.get("wxPhraseLong") or data.get("cloudCoverPhrase") or "",
            icon_code=data.get("iconCode"),
            humidity=data.get("relativeHumidity"),
            wind_speed_kmh=_as_float(data.get("windSpeed")),
            wind_direction=data.get("windDirectionCardinal") or "",
            uv_index=data.get("uvIndex"),
            uv_description=data.get("uvDescription") or "",
            pressure_mb=_as_float(data.get("pressureMeanSeaLevel")),
            visibility_km=_as_float(data.get("visibility")),
            dew_point_c=_as_float(data.get("temperatureDewPoint")),
            observed_at=data.get("observationTimeLocal") or "",
        )


@dataclass
class HourlyEntry:
    time_label: str
    temperature_c: float | None
    phrase: str
    icon_code: int | None
    precip_chance: int | None


@dataclass
class DailyEntry:
    day_label: str
    phrase: str
    icon_code: int | None
    high_c: float | None
    low_c: float | None
    precip_chance: int | None


@dataclass
class VerificationResult:
    """Outcome of an HTML structure check."""

    page: str
    url: str
    status: str
    checked_at: str
    present: list[str] = field(default_factory=list)
    missing_critical: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    report_path: str | None = None
    http_status: int | None = None
    error: str | None = None

    @property
    def is_critical(self) -> bool:
        return self.status == STATUS_CRITICAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "url": self.url,
            "status": self.status,
            "checked_at": self.checked_at,
            "http_status": self.http_status,
            "present": self.present,
            "missing_critical": self.missing_critical,
            "missing_optional": self.missing_optional,
            "report_path": self.report_path,
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# Change report writer
# --------------------------------------------------------------------------- #
class ChangeReportWriter:
    """Persists CRITICAL_CHANGE_DETECTED evidence for fast re-training."""

    def __init__(self, log_dir: Path | str = DEFAULT_LOG_DIR, max_snapshots: int = 10):
        self.log_dir = Path(log_dir)
        self.snapshot_dir = self.log_dir / "snapshots"
        self.max_snapshots = max_snapshots

    def write(
        self,
        result: VerificationResult,
        html: str,
        selector_config: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        snapshot_path = _unique_path(self.snapshot_dir / f"{result.page}-{stamp}.html")
        snapshot_path.write_text(html, encoding="utf-8", errors="replace")

        report_path = _unique_path(self.log_dir / f"critical-change-{result.page}-{stamp}.log")
        lines = [
            "=" * 78,
            f"{STATUS_CRITICAL}",
            "=" * 78,
            f"page          : {result.page}",
            f"url           : {result.url}",
            f"checked_at    : {result.checked_at}",
            f"http_status   : {result.http_status}",
            f"missing       : {', '.join(result.missing_critical) or '(none)'}",
            f"html_snapshot : {snapshot_path}",
            f"html_bytes    : {len(html)}",
            "",
            "-- selectors still present ------------------------------------------",
            *[f"  [ok]      {name}" for name in result.present],
            "",
            "-- selectors that broke --------------------------------------------",
            *[f"  [CRITICAL] {name}" for name in result.missing_critical],
            *[f"  [optional] {name}" for name in result.missing_optional],
            "",
            "-- selector registry in effect -------------------------------------",
            json.dumps(selector_config or {}, indent=2, ensure_ascii=False),
            "",
            "-- prompt for re-training (paste into DeepSeek / any LLM) -----------",
            "The Weather Channel page changed. Above is the selector registry that",
            "used to work and a snapshot of the new HTML. Propose updated CSS",
            "selectors for the broken entries only, keeping the JSON schema.",
            "",
        ]
        if extra:
            lines.insert(6, f"extra         : {json.dumps(extra, ensure_ascii=False)}")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        result.report_path = str(report_path)
        self._prune_snapshots()
        LOGGER.error("Critical structure change logged to %s", report_path)
        return report_path

    def _prune_snapshots(self) -> None:
        snapshots = sorted(self.snapshot_dir.glob("*.html"), key=lambda p: p.stat().st_mtime)
        for stale in snapshots[: max(0, len(snapshots) - self.max_snapshots)]:
            stale.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class WeatherChannelClient:
    """Fetches Weather Channel data and guards against layout drift."""

    def __init__(
        self,
        config_path: Path | str = DEFAULT_CONFIG_PATH,
        log_dir: Path | str = DEFAULT_LOG_DIR,
        timeout: float = 20.0,
        retries: int = 3,
        session: requests.Session | None = None,
        offline: bool = False,
    ):
        self.config = load_config(config_path)
        self.config_path = Path(config_path)
        self.timeout = timeout
        self.retries = retries
        self.offline = offline
        self.report_writer = ChangeReportWriter(log_dir)
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._api_key: str | None = None

    # -- HTTP ------------------------------------------------------------- #
    def _get(self, url: str, params: dict[str, Any] | None = None) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code in RETRY_STATUSES:
                    raise WeatherError(
                        f"HTTP {response.status_code} from {url}"
                    )
                response.raise_for_status()
                return response
            except (requests.RequestException, WeatherError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8))
        raise WeatherError(f"request failed for {url}: {last_error}")

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = self.config["api"]["base_url"].rstrip("/") + path
        payload = dict(params)
        payload["apiKey"] = self.api_key
        response = self._get(url, params=payload)
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise WeatherError(f"invalid JSON from {url}: {exc}") from exc

    # -- API key ---------------------------------------------------------- #
    @property
    def api_key(self) -> str:
        """Resolve the public web-app API key.

        The key is read from ``config/selectors.json`` and, when a page fetch
        is allowed, refreshed from the live JS bundles so it keeps working
        after weather.com rotates it.
        """
        if self._api_key:
            return self._api_key
        discovered = None if self.offline else self.discover_api_key()
        self._api_key = discovered or self.config["api"].get("key_fallback") or ""
        if not self._api_key:
            raise WeatherError("no weather.com API key available")
        return self._api_key

    def discover_api_key(self) -> str | None:
        """Scrape the current API key out of weather.com's JS bundles."""
        pattern = re.compile(r'apiKey:"([0-9a-f]{32})"')
        for page in self.config["api"].get("key_discovery_pages", []):
            try:
                html = self._get(page).text
            except WeatherError:
                continue
            match = pattern.search(html)
            if match:
                return match.group(1)
            for chunk in re.findall(r'src="(/_next/static/[^"]+\.js)"', html)[:60]:
                try:
                    js = self._get("https://weather.com" + chunk).text
                except WeatherError:
                    continue
                match = pattern.search(js)
                if match:
                    return match.group(1)
        return None

    # -- Location search -------------------------------------------------- #
    def search_locations(self, query: str, limit: int = 10) -> list[Location]:
        """Resolve a city name or postal code into candidate locations."""
        query = (query or "").strip()
        if len(query) < 3:
            return []
        data = self._get_json(
            self.config["api"]["endpoints"]["location_search"],
            {"query": query, "language": "en-US", "format": "json"},
        )
        return [Location.from_api(item) for item in _transpose(data.get("location", {}))][:limit]

    # -- Forecasts -------------------------------------------------------- #
    def get_current(self, location: Location) -> CurrentConditions:
        data = self._get_json(
            self.config["api"]["endpoints"]["current_conditions"],
            {"geocode": location.geocode, "units": "m", "language": "en-US", "format": "json"},
        )
        return CurrentConditions.from_api(location, data)

    def get_hourly(self, location: Location, hours: int = 12) -> list[HourlyEntry]:
        data = self._get_json(
            self.config["api"]["endpoints"]["hourly_forecast"],
            {"geocode": location.geocode, "units": "m", "language": "en-US", "format": "json"},
        )
        entries: list[HourlyEntry] = []
        times = data.get("validTimeLocal", []) or []
        for index in range(min(hours, len(times))):
            entries.append(
                HourlyEntry(
                    time_label=_hour_label(times[index]),
                    temperature_c=_pick(data.get("temperature"), index),
                    phrase=_pick(data.get("wxPhraseShort") or data.get("narrative"), index) or "",
                    icon_code=_pick(data.get("iconCode"), index),
                    precip_chance=_pick(data.get("precipChance"), index),
                )
            )
        return entries

    def get_daily(self, location: Location, days: int = 7) -> list[DailyEntry]:
        data = self._get_json(
            self.config["api"]["endpoints"]["daily_forecast"],
            {"geocode": location.geocode, "units": "m", "language": "en-US", "format": "json"},
        )
        weekdays = data.get("dayOfWeek", []) or []
        daytime = _daytime_daypart(data.get("daypart"))
        entries: list[DailyEntry] = []
        for index in range(min(days, len(weekdays))):
            entries.append(
                DailyEntry(
                    day_label=weekdays[index],
                    phrase=_pick(data.get("narrative"), index) or "",
                    icon_code=_pick(daytime.get("iconCode"), index),
                    high_c=_pick(data.get("calendarDayTemperatureMax"), index),
                    low_c=_pick(data.get("calendarDayTemperatureMin"), index),
                    precip_chance=_pick(daytime.get("precipChance"), index),
                )
            )
        return entries

    # -- Structure watchdog ----------------------------------------------- #
    def check_structure(self, page: str = "today", location_id: str = "USNY0996") -> VerificationResult:
        """Fetch a page and verify the configured selectors still match.

        Returns a :class:`VerificationResult`. On a critical miss the result
        carries ``status == CRITICAL_CHANGE_DETECTED`` and a report file with
        the raw HTML is written to ``logs/``.
        """
        page_config = self.config["pages"].get(page)
        if page_config is None:
            raise WeatherError(f"unknown page '{page}'")

        url = page_config["url_template"].format(location_id=location_id)
        checked_at = datetime.now(UTC).isoformat(timespec="seconds")
        result = VerificationResult(page=page, url=url, status=STATUS_OK, checked_at=checked_at)

        try:
            response = self._get(url)
        except WeatherError as exc:
            result.status = STATUS_WARNING
            result.error = str(exc)
            LOGGER.warning("Could not verify %s: %s", page, exc)
            return result

        result.http_status = response.status_code
        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        critical = page_config.get("critical", [])
        optional = page_config.get("optional", [])

        for entry in critical:
            if soup.select_one(entry["selector"]):
                result.present.append(entry["name"])
            else:
                result.missing_critical.append(entry["name"])

        for entry in optional:
            if soup.select_one(entry["selector"]):
                result.present.append(entry["name"])
            else:
                result.missing_optional.append(entry["name"])

        if result.missing_critical and page_config.get("strict", False):
            result.status = STATUS_CRITICAL
            self.report_writer.write(
                result,
                html,
                selector_config={"page": page, "critical": critical, "optional": optional},
                extra={"missing_optional": result.missing_optional},
            )
        elif result.missing_critical or result.missing_optional:
            result.status = STATUS_WARNING
            LOGGER.warning(
                "%s: %d critical / %d optional selectors missing",
                page,
                len(result.missing_critical),
                len(result.missing_optional),
            )
        else:
            LOGGER.info("%s: structure OK (%d selectors matched)", page, len(result.present))
        return result

    def check_all(self, location_id: str = "USNY0996") -> list[VerificationResult]:
        return [self.check_structure(page, location_id) for page in self.config["pages"]]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _unique_path(path: Path) -> Path:
    """Avoid clobbering two reports written within the same second."""
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path


def _transpose(columnar: dict[str, Any]) -> list[dict[str, Any]]:
    """Weather.com search responses are column oriented; make them row oriented."""
    if not columnar:
        return []
    keys = list(columnar.keys())
    length = max((len(v) for v in columnar.values() if isinstance(v, list)), default=0)
    rows: list[dict[str, Any]] = []
    for index in range(length):
        row: dict[str, Any] = {}
        for key in keys:
            value = columnar[key]
            if isinstance(value, list):
                row[key] = value[index] if index < len(value) else None
            else:
                row[key] = value
        rows.append(row)
    return rows


def _pick(sequence: Any, index: int) -> Any:
    if isinstance(sequence, list) and index < len(sequence):
        return sequence[index]
    return None


def _daytime_daypart(dayparts: Any) -> dict[str, Any]:
    """Return the daytime slice of a daily-forecast ``daypart`` array."""
    if not isinstance(dayparts, list):
        return {}
    for part in dayparts:
        if isinstance(part, dict) and (part.get("dayOrNight") == "D" or part.get("daypartName") == "Day"):
            return part
    return dayparts[0] if dayparts and isinstance(dayparts[0], dict) else {}


def _hour_label(timestamp: str) -> str:
    match = re.search(r"T(\d{2}):(\d{2})", timestamp or "")
    if not match:
        return timestamp or ""
    hour = int(match.group(1))
    suffix = "AM" if hour < 12 else "PM"
    display = hour % 12 or 12
    return f"{display} {suffix}"


def summarize(results: Iterable[VerificationResult]) -> str:
    lines = []
    for result in results:
        lines.append(f"[{result.status}] {result.page} <- {result.url}")
        if result.missing_critical:
            lines.append(f"    broken: {', '.join(result.missing_critical)}")
        if result.report_path:
            lines.append(f"    report: {result.report_path}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Weather Channel structure watchdog")
    parser.add_argument("--page", default="today", help="page key from config/selectors.json")
    parser.add_argument("--location", default="USNY0996", help="Weather Channel location id")
    parser.add_argument("--all-pages", action="store_true", help="check every configured page")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--offline", action="store_true", help="skip network access")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = WeatherChannelClient(log_dir=args.log_dir, offline=args.offline)
    results = (
        client.check_all(args.location)
        if args.all_pages
        else [client.check_structure(args.page, args.location)]
    )
    print(summarize(results))
    return 1 if any(r.is_critical for r in results) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
