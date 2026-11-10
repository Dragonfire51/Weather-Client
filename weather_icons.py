"""Mapping between Weather Channel icon codes and the retro pixel-art GIF set."""

from __future__ import annotations

from pathlib import Path

import paths

ICON_DIR = paths.ICON_DIR

# Every GIF the generator produces. Keep in sync with tools/make_icons.py.
ICON_CATEGORIES: tuple[str, ...] = (
    "sunny",
    "mostly_sunny",
    "partly_cloudy",
    "cloudy",
    "rain",
    "showers",
    "thunderstorm",
    "snow",
    "sleet",
    "fog",
    "windy",
    "clear_night",
    "cloudy_night",
    "unknown",
)

# Weather Channel `iconCode` -> category. Codes come from the TWC icon table.
ICON_CODE_TO_CATEGORY: dict[int, str] = {
    0: "thunderstorm",
    1: "thunderstorm",
    2: "thunderstorm",
    3: "thunderstorm",
    4: "thunderstorm",
    5: "sleet",
    6: "sleet",
    7: "sleet",
    8: "sleet",
    9: "showers",
    10: "sleet",
    11: "showers",
    12: "rain",
    13: "snow",
    14: "snow",
    15: "snow",
    16: "snow",
    17: "sleet",
    18: "sleet",
    19: "fog",
    20: "fog",
    21: "fog",
    22: "fog",
    23: "windy",
    24: "windy",
    25: "sleet",
    26: "cloudy",
    27: "cloudy_night",
    28: "cloudy",
    29: "cloudy_night",
    30: "partly_cloudy",
    31: "clear_night",
    32: "sunny",
    33: "clear_night",
    34: "mostly_sunny",
    35: "sleet",
    36: "sunny",
    37: "thunderstorm",
    38: "thunderstorm",
    39: "showers",
    40: "rain",
    41: "snow",
    42: "snow",
    43: "snow",
    44: "sleet",
    45: "showers",
    46: "snow",
    47: "thunderstorm",
}

# Coarse keyword fallback for when only a phrase is available.
PHRASE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("thunder", "thunderstorm"),
    ("t-storm", "thunderstorm"),
    ("storm", "thunderstorm"),
    ("snow", "snow"),
    ("flurr", "snow"),
    ("sleet", "sleet"),
    ("ice", "sleet"),
    ("freez", "sleet"),
    ("shower", "showers"),
    ("rain", "rain"),
    ("drizzle", "showers"),
    ("fog", "fog"),
    ("mist", "fog"),
    ("haze", "fog"),
    ("wind", "windy"),
    ("cloud", "cloudy"),
    ("overcast", "cloudy"),
    ("partly", "partly_cloudy"),
    ("mostly sunny", "mostly_sunny"),
    ("sunny", "sunny"),
    ("clear", "sunny"),
    ("fair", "mostly_sunny"),
)


def category_for(icon_code: int | None, phrase: str = "", is_night: bool = False) -> str:
    """Best-effort mapping from an icon code and/or phrase to a GIF category."""
    if icon_code is not None:
        category = ICON_CODE_TO_CATEGORY.get(int(icon_code))
        if category:
            return category
    text = (phrase or "").lower()
    for needle, category in PHRASE_KEYWORDS:
        if needle in text:
            if is_night and category in {"sunny", "mostly_sunny", "partly_cloudy"}:
                return "clear_night" if category != "partly_cloudy" else "cloudy_night"
            return category
    return "cloudy_night" if is_night else "unknown"


def icon_path(category: str, icon_dir: Path | str = ICON_DIR) -> Path:
    name = category if category in ICON_CATEGORIES else "unknown"
    return Path(icon_dir) / f"{name}.gif"
