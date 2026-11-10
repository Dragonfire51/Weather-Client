"""The HTML structure watchdog tests.

These are the tests that detect that Weather Channel changed its page. They run
against local fixtures by default so the suite stays deterministic and offline;
``tests/test_live_structure.py`` performs the same checks against the real site
on a schedule.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import (
    ANCHORS_BY_PAGE,
    FakeResponse,
    FakeSession,
    build_page_html,
    load_fixture,
)
from weather_scraper import (
    STATUS_CRITICAL,
    STATUS_OK,
    STATUS_WARNING,
    WeatherChannelClient,
    WeatherError,
    load_config,
)


@pytest.fixture
def client_factory(tmp_path):
    def make(page_html: dict[str, str], retries: int = 1) -> WeatherChannelClient:
        rules = {f"/weather/{page}/": FakeResponse(text=html) for page, html in page_html.items()}
        client = WeatherChannelClient(session=FakeSession(rules=rules), log_dir=tmp_path / "logs", retries=retries)
        client._api_key = "test"
        return client

    return make


def test_config_declares_selectors_for_every_page():
    config = load_config()
    for page in ("today", "hourbyhour", "tenday"):
        assert page in config["pages"], f"missing page config for {page}"
        assert config["pages"][page]["critical"] or config["pages"][page]["optional"]
    assert config["pages"]["today"]["strict"] is True


def test_today_page_with_real_fixture_is_ok(client_factory):
    client = client_factory({"today": load_fixture("weather_today_ok.html")})
    result = client.check_structure("today", "USNY0996")
    assert result.status == STATUS_OK
    assert result.missing_critical == []
    assert result.missing_optional == []
    assert result.report_path is None
    assert set(result.present) == set(ANCHORS_BY_PAGE["today"])


def test_all_configured_selectors_exist_in_ok_fixture():
    """Guards against typos: every configured selector must match the fixture."""
    config = load_config()
    html = load_fixture("weather_today_ok.html")
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for entry in config["pages"]["today"]["critical"] + config["pages"]["today"]["optional"]:
        assert soup.select_one(entry["selector"]), f"selector not found in fixture: {entry['name']}"


def test_missing_critical_selector_triggers_critical_and_writes_report(client_factory, tmp_path):
    anchors = [a for a in ANCHORS_BY_PAGE["today"] if a != "current-conditions"]
    client = client_factory({"today": build_page_html("today", anchors)})

    result = client.check_structure("today", "USNY0996")

    assert result.status == STATUS_CRITICAL
    assert result.is_critical
    assert result.missing_critical == ["current-conditions"]
    assert result.report_path is not None

    report = Path(result.report_path)
    assert report.exists()
    body = report.read_text(encoding="utf-8")
    assert STATUS_CRITICAL in body
    assert "current-conditions" in body
    assert "html_snapshot" in body
    # the report must embed the selector registry so re-training is self-contained
    assert "data-testid='current-conditions'" in body
    assert "re-training" in body


def test_critical_report_saves_html_snapshot(client_factory):
    anchors = [a for a in ANCHORS_BY_PAGE["today"] if a != "subnavigation"]
    html = build_page_html("today", anchors)
    client = client_factory({"today": html})

    result = client.check_structure("today", "USNY0996")

    snapshot_line = next(line for line in Path(result.report_path).read_text().splitlines() if "html_snapshot" in line)
    snapshot_path = Path(snapshot_line.split(":", 1)[1].strip())
    assert snapshot_path.exists()
    assert snapshot_path.read_text(encoding="utf-8") == html


def test_report_name_is_timestamped_per_page(client_factory):
    anchors = [a for a in ANCHORS_BY_PAGE["today"] if a != "header-main"]
    client = client_factory({"today": build_page_html("today", anchors)})
    result = client.check_structure("today", "USNY0996")
    assert re.search(r"critical-change-today-\d{8}-\d{6}\.log$", result.report_path)


def test_missing_optional_selector_only_warns(client_factory):
    anchors = [a for a in ANCHORS_BY_PAGE["today"] if a != "DynamicMap"]
    client = client_factory({"today": build_page_html("today", anchors)})

    result = client.check_structure("today", "USNY0996")

    assert result.status == STATUS_WARNING
    assert result.missing_critical == []
    assert result.missing_optional == ["DynamicMap"]
    assert result.report_path is None


def test_renamed_testid_is_detected_as_critical(client_factory):
    """Simulates weather.com renaming a data-testid (the classic breakage)."""
    html = build_page_html("today", ANCHORS_BY_PAGE["today"]).replace(
        'data-testid="current-conditions"', 'data-testid="current-conditions-panel"'
    )
    client = client_factory({"today": html})

    result = client.check_structure("today", "USNY0996")

    assert result.status == STATUS_CRITICAL
    assert "current-conditions" in result.missing_critical


def test_structural_rewrite_without_testids_is_critical(client_factory):
    """A full layout rewrite that drops every anchor must be reported."""
    client = client_factory({"today": "<html><body><div class='new-layout'>hi</div></body></html>"})
    result = client.check_structure("today", "USNY0996")
    assert result.status == STATUS_CRITICAL
    assert set(result.missing_critical) == {
        "header-main",
        "location-picker-trigger",
        "sidebar-navigation",
        "subnavigation",
        "current-conditions",
        "current-conditions-temperatures",
        "current-widgets",
    }


def test_http_failure_is_reported_without_crashing(client_factory):
    client = client_factory({"today": ""})
    client.session.rules["/weather/today/"] = FakeResponse(text="", status_code=500)

    result = client.check_structure("today", "USNY0996")

    assert result.status == STATUS_WARNING
    assert result.error is not None
    assert result.missing_critical == []


def test_check_all_covers_every_page(client_factory):
    pages = {page: build_page_html(page, ANCHORS_BY_PAGE[page]) for page in ANCHORS_BY_PAGE}
    client = client_factory(pages)
    results = client.check_all("USNY0996")
    assert {r.page for r in results} == {"today", "hourbyhour", "tenday"}
    assert all(r.status == STATUS_OK for r in results)


def test_every_page_can_raise_critical(client_factory):
    """Each monitored page must be strict, or drift there would pass silently."""
    config = load_config()
    for page in ("today", "hourbyhour", "tenday"):
        assert config["pages"][page]["strict"] is True
        assert config["pages"][page]["critical"], f"{page} declares no critical selectors"


def test_hourly_page_missing_critical_is_reported(client_factory):
    anchors = [a for a in ANCHORS_BY_PAGE["hourbyhour"] if a != "subnavigation"]
    client = client_factory({"hourbyhour": build_page_html("hourbyhour", anchors)})

    result = client.check_structure("hourbyhour", "USNY0996")

    assert result.status == STATUS_CRITICAL
    assert result.missing_critical == ["subnavigation"]
    assert result.report_path is not None


def test_unknown_page_raises(client_factory):
    client = client_factory({"today": build_page_html("today")})
    with pytest.raises(WeatherError):
        client.check_structure("nope", "USNY0996")


def test_snapshots_are_pruned(tmp_path):
    from weather_scraper import ChangeReportWriter, VerificationResult

    writer = ChangeReportWriter(tmp_path, max_snapshots=2)
    for index in range(5):
        result = VerificationResult(page="today", url="u", status=STATUS_CRITICAL, checked_at=str(index))
        writer.write(result, f"<html>{index}</html>")
    assert len(list((tmp_path / "snapshots").glob("*.html"))) == 2
