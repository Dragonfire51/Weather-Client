# AGENTS.md

Retro Win32/Windows XP look-alike Weather Channel desktop client (Tkinter) plus
a weather.com data client and an HTML-structure watchdog.

## Layout

| Path | Purpose |
| --- | --- |
| `weather_desktop.py` | Tkinter UI (Luna palette, sidebar views, Location Manager modal, °C/°F setting) |
| `weather_scraper.py` | Data client (api.weather.com) + `CRITICAL_CHANGE_DETECTED` verifier + report writer |
| `weather_icons.py` | icon-code → GIF category mapping |
| `icons/*.gif` | generated pixel-art sprites (32×32) |
| `tools/make_icons.py` | pure-Python GIF generator (no Pillow) |
| `tools/daily_structure_check.py` | 24-hour scheduled entry point |
| `config/selectors.json` | selector registry + API endpoints/keys |
| `tests/` | pytest suite |

## Commands

```bash
python tools/make_icons.py                      # regenerate icons/*.gif
python weather_desktop.py                       # run the app (needs a display)
python tools/daily_structure_check.py           # structure check (exit 0/1/2)
pytest                                          # offline suite (unit + watchdog)
xvfb-run -a pytest tests/test_gui_smoke.py -m gui
WEATHER_LIVE=1 pytest -m live                   # hits weather.com
python -m ruff check .                          # lint (must be clean)
```

## Key facts

* weather.com is a **Next.js SPA**: weather data is *not* in the static HTML.
  Data comes from `api.weather.com`; the HTML is fetched only to check that
  `data-testid` anchors still exist (a cheap canary for layout drift).
* An API key is discovered from weather.com JS bundles; `config/selectors.json`
  → `api.key_fallback` is the offline fallback. Do not hardcode keys elsewhere.
* Statuses: `OK`, `WARNING_SELECTOR_MISSING`, `CRITICAL_CHANGE_DETECTED`.
  Only `strict: true` pages raise CRITICAL. Every monitored page should be
  strict and declare at least one critical selector.
* On CRITICAL, `ChangeReportWriter` writes
  `logs/critical-change-<page>-<ts>.log` (broken vs present selectors, the
  registry in effect, a re-training prompt) and saves the raw HTML under
  `logs/snapshots/` (last 10 kept). `logs/` is gitignored.
* The UI must stay standard-library Tkinter; only the data layer uses
  `requests`/`beautifulsoup4`.

## Testing conventions

* `tests/conftest.py` provides `FakeSession`/`FakeResponse` and payload builders.
  No test may hit the network except those marked `live`.
* `tests/test_structure_watchdog.py` is the authoritative coverage for selector
  drift: renamed selector, removed selector, full layout rewrite.
* `tests/fixtures/weather_today_ok.html` mirrors the real page's anchors; keep
  it in sync with `config/selectors.json`.
* Markers `live` and `gui` are excluded by default via `pytest.ini`.
