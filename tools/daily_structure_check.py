#!/usr/bin/env python3
"""Daily Weather Channel structure check.

Designed to be run once every 24 hours by Task Scheduler (Windows), cron
(Linux/macOS) or the OpenHands automation in ``config/daily_check.example.json``.

Exit codes:
    0  every page still matches its selectors
    1  CRITICAL_CHANGE_DETECTED (a report was written to logs/)
    2  the check could not run (network/config problem)

Usage::

    python tools/daily_structure_check.py --location USNY0996
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from weather_scraper import STATUS_CRITICAL, WeatherChannelClient

EXIT_OK = 0
EXIT_CRITICAL = 1
EXIT_ERROR = 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily Weather Channel structure check")
    parser.add_argument("--location", default="USNY0996", help="Weather Channel location id")
    parser.add_argument("--log-dir", default=str(ROOT / "logs"))
    parser.add_argument("--json", action="store_true", help="also print a JSON summary")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    history = log_dir / "structure-check-history.jsonl"

    client = WeatherChannelClient(log_dir=log_dir)
    try:
        results = client.check_all(args.location)
    except Exception as exc:  # noqa: BLE001 - report and exit non-zero
        logging.getLogger("daily_check").error("structure check failed: %s", exc)
        return EXIT_ERROR

    critical = [r for r in results if r.status == STATUS_CRITICAL]
    record = {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "location": args.location,
        "status": STATUS_CRITICAL if critical else "OK",
        "results": [r.to_dict() for r in results],
    }
    with open(history, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")

    for result in results:
        print(f"[{result.status}] {result.page} <- {result.url}")
        if result.missing_critical:
            print(f"    broken : {', '.join(result.missing_critical)}")
        if result.report_path:
            print(f"    report : {result.report_path}")

    if args.json:
        print(json.dumps(record, indent=2))

    if critical:
        print(f"\n{STATUS_CRITICAL}: {len(critical)} page(s) need selector re-training.")
        return EXIT_CRITICAL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
