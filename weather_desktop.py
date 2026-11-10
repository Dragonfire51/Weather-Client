"""The Weather Channel Desktop - a Win32/Windows XP era look-alike client.

Standard-library Tkinter only: no third-party UI dependency, native widgets,
GIF icons. Data comes from :mod:`weather_scraper`.

Run::

    python weather_desktop.py
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox

import paths
import weather_icons
from weather_scraper import (
    STATUS_CRITICAL,
    CurrentConditions,
    DailyEntry,
    HourlyEntry,
    Location,
    WeatherChannelClient,
    WeatherError,
    format_speed,
    format_temp,
    load_config,
)

LOGGER = logging.getLogger("weather_desktop")

SETTINGS_PATH = paths.SETTINGS_PATH

# --- Windows XP "Luna" palette -------------------------------------------- #
BG_DESKTOP = "#D6E3F7"
BG_PANEL = "#F0F4F9"
BG_BUTTON = "#E2EBF5"
BG_CONTENT = "#FFFFFF"
BG_ROW_ALT = "#F7FAFE"
NAVY = "#003399"
INK = "#333333"
INK_SOFT = "#666666"
INK_LABEL = "#555555"

FONT_UI = ("MS Sans Serif", 9)
FONT_UI_BOLD = ("MS Sans Serif", 9, "bold")
FONT_TITLE = ("MS Sans Serif", 10, "bold")
FONT_SECTION = ("Arial", 14, "bold")
FONT_TEMP = ("Arial", 42, "bold")
FONT_TEMP_SMALL = ("Arial", 20, "bold")
FONT_LOCATION = ("MS Sans Serif", 11, "bold")

SIDEBAR_ITEMS = (
    ("Local Weather", "weather"),
    ("12-Hour Forecast", "hourly"),
    ("Extended Forecast", "daily"),
    ("Weather Maps", "maps"),
    ("Settings", "settings"),
)

UNIT_CELSIUS = "C"
UNIT_FAHRENHEIT = "F"


class WeatherChannelDesktop:
    """Main window and controller."""

    def __init__(self, root: tk.Tk, client: WeatherChannelClient | None = None):
        self.root = root
        if client is None:
            paths.seed_user_config()
            client = WeatherChannelClient(config_path=paths.resolve_config_path())
        self.client = client
        self.settings = self._load_settings()
        self.unit = self.settings.get("unit", UNIT_CELSIUS)
        self.location: Location | None = Location.from_dict(self.settings["location"]) if self.settings.get("location") else None
        self.current: CurrentConditions | None = None
        self.hourly: list[HourlyEntry] = []
        self.daily: list[DailyEntry] = []
        self.icons: dict[str, tk.PhotoImage] = {}
        self.active_view = "weather"
        self._results: queue.Queue = queue.Queue()
        self._pending: list[tuple] = []
        self._busy = False

        self._build_window()
        self._load_icons()
        self._build_top_bar()
        self._build_body()
        self._build_status_bar()
        self.show_view("weather")

        self.root.after(200, self.refresh_weather)
        self.root.after(400, lambda: self.check_structure_async(notify=True))

    # ------------------------------------------------------------------ #
    # Window scaffolding
    # ------------------------------------------------------------------ #
    def _build_window(self) -> None:
        self.root.title("The Weather Channel Desktop")
        self.root.geometry("900x660")
        self.root.minsize(820, 600)
        self.root.configure(bg=BG_DESKTOP)
        try:
            self.root.tk.call("wm", "iconphoto", self.root._w, tk.PhotoImage(file=str(weather_icons.icon_path("mostly_sunny"))))
        except tk.TclError:  # pragma: no cover - cosmetic
            pass

    def _build_top_bar(self) -> None:
        bar = tk.Frame(self.root, bg=BG_CONTENT, bd=1, relief="groove")
        bar.pack(fill="x", side="top", padx=3, pady=3)

        self.lbl_location = tk.Label(
            bar,
            text=self.location.label if self.location else "Select a location...",
            font=FONT_LOCATION,
            bg=BG_CONTENT,
            fg=NAVY,
        )
        self.lbl_location.pack(side="left", padx=12, pady=8)

        self.btn_change = tk.Button(
            bar,
            text="[Change Location]",
            font=("MS Sans Serif", 9, "underline"),
            bg=BG_CONTENT,
            bd=0,
            fg="#0000CC",
            activebackground=BG_CONTENT,
            cursor="hand2",
            command=self.open_location_manager,
        )
        self.btn_change.pack(side="left", padx=4)

        self.lbl_unit = tk.Label(bar, text=self._unit_label(), font=FONT_UI_BOLD, bg=BG_CONTENT, fg=INK_SOFT)
        self.lbl_unit.pack(side="right", padx=12)

        tk.Label(bar, text="Updated:", font=FONT_UI, bg=BG_CONTENT, fg=INK_SOFT).pack(side="right")
        self.lbl_updated = tk.Label(bar, text="--", font=FONT_UI, bg=BG_CONTENT, fg=INK_SOFT)
        self.lbl_updated.pack(side="right", padx=(2, 12))

    def _build_body(self) -> None:
        container = tk.Frame(self.root, bg=BG_DESKTOP)
        container.pack(fill="both", expand=True, padx=3, pady=(0, 2))

        self.sidebar = tk.Frame(container, bg=BG_PANEL, width=178, bd=2, relief="sunken")
        self.sidebar.pack(side="left", fill="y", padx=(0, 4))
        self.sidebar.pack_propagate(False)
        self._build_sidebar()

        self.content_area = tk.Frame(container, bg=BG_CONTENT, bd=2, relief="sunken")
        self.content_area.pack(side="right", fill="both", expand=True)

    def _build_sidebar(self) -> None:
        header = tk.Frame(self.sidebar, bg=NAVY)
        header.pack(fill="x")
        tk.Label(header, text="SECTIONS", font=("MS Sans Serif", 8, "bold"), bg=NAVY, fg="#FFFFFF").pack(pady=3)

        self._nav_buttons: dict[str, tk.Button] = {}
        for label, key in SIDEBAR_ITEMS:
            btn = tk.Button(
                self.sidebar,
                text=f"  {label}",
                font=FONT_UI_BOLD,
                anchor="w",
                bg=BG_BUTTON,
                fg=NAVY,
                activebackground=NAVY,
                activeforeground="#FFFFFF",
                bd=1,
                relief="raised",
                height=2,
                cursor="hand2",
                command=lambda k=key: self.show_view(k),
            )
            btn.pack(fill="x", pady=2, padx=3)
            self._nav_buttons[key] = btn

        tk.Frame(self.sidebar, bg=BG_PANEL).pack(fill="both", expand=True)
        tk.Label(self.sidebar, text="Structure check:", font=("MS Sans Serif", 7), bg=BG_PANEL, fg=INK_SOFT, anchor="w").pack(fill="x", padx=6)
        self.lbl_watchdog = tk.Label(self.sidebar, text="--", font=("MS Sans Serif", 7, "bold"), bg=BG_PANEL, fg=INK_SOFT, anchor="w")
        self.lbl_watchdog.pack(fill="x", padx=6, pady=(0, 6))

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self.root, bg=BG_PANEL, bd=1, relief="sunken")
        bar.pack(fill="x", side="bottom")
        self.lbl_status = tk.Label(bar, text="Ready", font=("MS Sans Serif", 8), bg=BG_PANEL, fg=INK, anchor="w")
        self.lbl_status.pack(side="left", padx=6, pady=2)
        tk.Label(bar, text="weather.com", font=("MS Sans Serif", 8), bg=BG_PANEL, fg=INK_SOFT).pack(side="right", padx=6)

    # ------------------------------------------------------------------ #
    # Icons
    # ------------------------------------------------------------------ #
    def _load_icons(self) -> None:
        for category in weather_icons.ICON_CATEGORIES:
            path = weather_icons.icon_path(category)
            if path.exists():
                try:
                    self.icons[category] = tk.PhotoImage(file=str(path))
                except tk.TclError:  # pragma: no cover - corrupt file
                    LOGGER.warning("Could not load icon %s", path)
        self.icons.setdefault("unknown", tk.PhotoImage(width=32, height=32))

    def _icon_for(self, icon_code: int | None, phrase: str = "") -> tk.PhotoImage:
        category = weather_icons.category_for(icon_code, phrase)
        return self.icons.get(category) or self.icons["unknown"]

    # ------------------------------------------------------------------ #
    # Settings persistence
    # ------------------------------------------------------------------ #
    def _load_settings(self) -> dict:
        defaults = {"unit": UNIT_CELSIUS, "location": None}
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return defaults
        return {**defaults, **data}

    def _save_settings(self) -> None:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "unit": self.unit,
            "location": self.location.to_dict() if self.location else None,
        }
        SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Threading helpers
    # ------------------------------------------------------------------ #
    def _run_async(self, work, on_done=None) -> None:
        """Run ``work`` in a worker thread, deliver its result to ``on_done``.

        Requests are serialised: a call made while another is in flight is
        queued rather than dropped.
        """
        if self._busy:
            self._pending.append((work, on_done))
            self._set_status("Queued...")
            return
        self._busy = True
        self._set_status("Contacting weather.com...")

        def runner() -> None:
            try:
                self._results.put((on_done, work(), None))
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                self._results.put((on_done, None, exc))

        threading.Thread(target=runner, daemon=True).start()
        self.root.after(60, self._drain_results)

    def _drain_results(self) -> None:
        try:
            callback, result, error = self._results.get_nowait()
        except queue.Empty:
            self.root.after(60, self._drain_results)
            return
        self._busy = False
        if error is not None:
            self._set_status(f"Error: {error}")
            if not isinstance(error, WeatherError):
                LOGGER.error("Background task failed", exc_info=error)
        if callback is not None:
            callback(result, error)
        if self._pending:
            work, on_done = self._pending.pop(0)
            self._run_async(work, on_done)

    def _set_status(self, text: str) -> None:
        self.lbl_status.configure(text=text)

    # ------------------------------------------------------------------ #
    # Views
    # ------------------------------------------------------------------ #
    def _clear_content(self) -> None:
        for widget in self.content_area.winfo_children():
            widget.destroy()

    def _view_header(self, title: str) -> tk.Frame:
        header = tk.Frame(self.content_area, bg=NAVY)
        header.pack(fill="x")
        tk.Label(header, text=title, font=FONT_TITLE, bg=NAVY, fg="#FFFFFF").pack(side="left", padx=10, pady=5)
        return header

    def show_view(self, key: str) -> None:
        self.active_view = key
        for nav_key, btn in self._nav_buttons.items():
            btn.configure(relief="sunken" if nav_key == key else "raised", bg=BG_PANEL if nav_key == key else BG_BUTTON)
        {
            "weather": self.render_current,
            "hourly": self.render_hourly,
            "daily": self.render_daily,
            "maps": self.render_maps,
            "settings": self.render_settings,
        }.get(key, self.render_current)()

    def render_current(self) -> None:
        self._clear_content()
        self._view_header("CURRENT CONDITIONS")

        panel = tk.Frame(self.content_area, bg=BG_CONTENT)
        panel.pack(fill="both", expand=True, padx=18, pady=16)

        icon_cell = tk.Frame(panel, bg=BG_CONTENT)
        icon_cell.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 18))
        self.lbl_weather_icon = tk.Label(icon_cell, image=self.icons["unknown"], bg=BG_CONTENT)
        self.lbl_weather_icon.pack()
        self.lbl_condition = tk.Label(icon_cell, text="--", font=FONT_UI_BOLD, bg=BG_CONTENT, fg=INK_SOFT, wraplength=150, justify="center")
        self.lbl_condition.pack(pady=(6, 0))

        self.lbl_temp = tk.Label(panel, text="--", font=FONT_TEMP, bg=BG_CONTENT, fg=INK)
        self.lbl_temp.grid(row=0, column=1, sticky="sw")

        self.lbl_feels = tk.Label(panel, text="", font=FONT_UI, bg=BG_CONTENT, fg=INK_SOFT)
        self.lbl_feels.grid(row=1, column=1, sticky="nw", pady=(0, 12))

        self._render_details(panel, row=2)

        self._apply_current()

    def _render_details(self, parent: tk.Widget, row: int) -> None:
        frame = tk.LabelFrame(parent, text=" Details ", font=("MS Sans Serif", 8, "bold"), bg=BG_CONTENT, fg=NAVY, bd=2, relief="groove")
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0), ipady=4)
        frame.columnconfigure(1, weight=1)
        self._detail_labels: dict[str, tk.Label] = {}
        rows = [
            ("humidity", "Humidity:"),
            ("wind", "Wind:"),
            ("uv", "UV Index:"),
            ("pressure", "Barometer:"),
            ("visibility", "Visibility:"),
            ("dew", "Dew Point:"),
            ("observed", "Observed:"),
        ]
        for index, (key, label) in enumerate(rows):
            tk.Label(frame, text=label, font=FONT_UI_BOLD, bg=BG_CONTENT, fg=INK_LABEL, width=12, anchor="w").grid(row=index, column=0, sticky="w", padx=(10, 4), pady=1)
            value = tk.Label(frame, text="--", font=FONT_UI, bg=BG_CONTENT, fg=INK, anchor="w")
            value.grid(row=index, column=1, sticky="w", padx=(0, 10), pady=1)
            self._detail_labels[key] = value

    def _apply_current(self) -> None:
        current = self.current
        if current is None:
            return
        self.lbl_weather_icon.configure(image=self._icon_for(current.icon_code, current.phrase))
        self.lbl_temp.configure(text=format_temp(current.temperature_c, self.unit))
        self.lbl_condition.configure(text=current.phrase or "--")
        feels = format_temp(current.feels_like_c, self.unit)
        self.lbl_feels.configure(text=f"Feels like {feels}" if current.feels_like_c is not None else "")

        values = {
            "humidity": f"{current.humidity}%" if current.humidity is not None else "--",
            "wind": f"{current.wind_direction} at {format_speed(current.wind_speed_kmh, self.unit)}".strip(),
            "uv": f"{current.uv_index} ({current.uv_description})" if current.uv_index is not None else "--",
            "pressure": f"{current.pressure_mb:.1f} mb" if current.pressure_mb is not None else "--",
            "visibility": f"{current.visibility_km:.1f} km" if current.visibility_km is not None else "--",
            "dew": format_temp(current.dew_point_c, self.unit),
            "observed": current.observed_at or "--",
        }
        for key, label in self._detail_labels.items():
            label.configure(text=values.get(key, "--"))

    def render_hourly(self) -> None:
        self._clear_content()
        self._view_header("12-HOUR FORECAST")
        table = tk.Frame(self.content_area, bg=BG_DESKTOP, bd=2, relief="sunken")
        table.pack(fill="both", expand=True, padx=10, pady=10)

        if not self.hourly:
            tk.Label(table, text="No hourly data loaded yet.", font=FONT_UI, bg=BG_CONTENT, fg=INK_SOFT).pack(padx=12, pady=12)
            return

        self._table_headers(table, ["Hour", "Sky", "Temp", "Precip"])
        for index, entry in enumerate(self.hourly):
            bg = BG_CONTENT if index % 2 == 0 else BG_ROW_ALT
            row = index + 1
            self._cell(table, entry.time_label, row, 0, bg)
            icon_cell = tk.Label(table, image=self._icon_for(entry.icon_code, entry.phrase), bg=bg, bd=1, relief="solid")
            icon_cell.grid(row=row, column=1, sticky="ew")
            self._cell(table, format_temp(entry.temperature_c, self.unit), row, 2, bg)
            self._cell(table, f"{entry.precip_chance}%" if entry.precip_chance is not None else "--", row, 3, bg)

    def render_daily(self) -> None:
        self._clear_content()
        self._view_header("EXTENDED FORECASTS")
        table = tk.Frame(self.content_area, bg=BG_DESKTOP, bd=2, relief="sunken")
        table.pack(fill="both", expand=True, padx=10, pady=10)

        if not self.daily:
            tk.Label(table, text="No forecast data loaded yet.", font=FONT_UI, bg=BG_CONTENT, fg=INK_SOFT).pack(padx=12, pady=12)
            return

        self._table_headers(table, ["Day", "Sky", "High / Low", "Precip."])
        for index, entry in enumerate(self.daily):
            bg = BG_CONTENT if index % 2 == 0 else BG_ROW_ALT
            row = index + 1
            self._cell(table, entry.day_label, row, 0, bg)
            icon_cell = tk.Label(table, image=self._icon_for(entry.icon_code, entry.phrase), bg=bg, bd=1, relief="solid")
            icon_cell.grid(row=row, column=1, sticky="ew")
            highs = f"{format_temp(entry.high_c, self.unit)} / {format_temp(entry.low_c, self.unit)}"
            self._cell(table, highs, row, 2, bg)
            self._cell(table, f"{entry.precip_chance}%" if entry.precip_chance is not None else "--", row, 3, bg)

    def render_maps(self) -> None:
        self._clear_content()
        self._view_header("WEATHER MAPS")
        body = tk.Frame(self.content_area, bg=BG_CONTENT)
        body.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(body, text="Regional radar", font=FONT_SECTION, bg=BG_CONTENT, fg=NAVY).pack(anchor="w")
        tk.Label(
            body,
            text=(
                "The interactive map is provided by weather.com and is not\n"
                "embedded in this desktop client.\n\n"
                "Open in browser:  " + self._radar_url()
            ),
            font=FONT_UI,
            bg=BG_CONTENT,
            fg=INK_SOFT,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        tk.Button(body, text="Copy radar URL", font=FONT_UI, bg=BG_BUTTON, command=self._copy_radar_url).pack(anchor="w", pady=10)

    def _radar_url(self) -> str:
        base = "https://weather.com/weather/maps/radar"
        return f"{base}/l/{self.location.place_id}" if self.location else base

    def _copy_radar_url(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self._radar_url())
        self._set_status("Radar URL copied to clipboard")

    def render_settings(self) -> None:
        self._clear_content()
        self._view_header("SETTINGS")
        body = tk.Frame(self.content_area, bg=BG_CONTENT)
        body.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(body, text="Temperature units", font=FONT_SECTION, bg=BG_CONTENT, fg=NAVY).pack(anchor="w")
        self.unit_var = tk.StringVar(value=self.unit)
        for value, label in ((UNIT_CELSIUS, "Celsius (°C)"), (UNIT_FAHRENHEIT, "Fahrenheit (°F)")):
            tk.Radiobutton(
                body,
                text=label,
                variable=self.unit_var,
                value=value,
                font=FONT_UI,
                bg=BG_CONTENT,
                activebackground=BG_CONTENT,
                command=self.apply_unit_change,
            ).pack(anchor="w", padx=12, pady=2)

        tk.Label(body, text="Data & maintenance", font=FONT_SECTION, bg=BG_CONTENT, fg=NAVY).pack(anchor="w", pady=(18, 0))
        tk.Button(body, text="Refresh weather now", font=FONT_UI, bg=BG_BUTTON, command=self.refresh_weather).pack(anchor="w", padx=12, pady=(6, 2))
        tk.Button(body, text="Verify page structure (watchdog)", font=FONT_UI, bg=BG_BUTTON, command=lambda: self.check_structure_async(notify=True)).pack(anchor="w", padx=12, pady=2)
        tk.Button(body, text="Open log folder", font=FONT_UI, bg=BG_BUTTON, command=self._open_log_folder).pack(anchor="w", padx=12, pady=2)

        tk.Label(
            body,
            text=f"Selector registry: {self.client.config_path}",
            font=("MS Sans Serif", 8),
            bg=BG_CONTENT,
            fg=INK_SOFT,
        ).pack(anchor="w", pady=(14, 0))
        self.lbl_settings_watchdog = tk.Label(body, text=self.lbl_watchdog.cget("text"), font=FONT_UI, bg=BG_CONTENT, fg=INK, justify="left")
        self.lbl_settings_watchdog.pack(anchor="w", pady=(6, 0))

    def _open_log_folder(self) -> None:
        self._set_status(f"Logs: {self.client.report_writer.log_dir}")

    def apply_unit_change(self) -> None:
        self.unit = self.unit_var.get()
        self.lbl_unit.configure(text=self._unit_label())
        self._save_settings()
        self.show_view(self.active_view)
        self._set_status(f"Units set to {'Fahrenheit' if self.unit == UNIT_FAHRENHEIT else 'Celsius'}")

    def _unit_label(self) -> str:
        return "°F" if self.unit == UNIT_FAHRENHEIT else "°C"

    # ------------------------------------------------------------------ #
    # Table helpers
    # ------------------------------------------------------------------ #
    def _table_headers(self, parent: tk.Widget, columns: list[str]) -> None:
        for index, name in enumerate(columns):
            tk.Label(parent, text=name, font=FONT_UI_BOLD, bg=BG_BUTTON, fg=NAVY, bd=1, relief="raised", width=16).grid(row=0, column=index, sticky="ew")
        parent.columnconfigure(1, weight=1)

    def _cell(self, parent: tk.Widget, text: str, row: int, column: int, bg: str) -> None:
        tk.Label(parent, text=text, font=FONT_UI, bg=bg, fg=INK, bd=1, relief="solid", height=2, width=16).grid(row=row, column=column, sticky="ew")

    # ------------------------------------------------------------------ #
    # Location Manager (modal)
    # ------------------------------------------------------------------ #
    def open_location_manager(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Location Manager")
        window.geometry("400x360")
        window.configure(bg=BG_PANEL)
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()

        tk.Label(window, text="Enter City Name or Zip Code:", font=FONT_UI_BOLD, bg=BG_PANEL, fg=NAVY).pack(pady=(14, 2), anchor="w", padx=18)

        input_row = tk.Frame(window, bg=BG_PANEL)
        input_row.pack(fill="x", padx=18, pady=4)
        entry = tk.Entry(input_row, font=("Arial", 10), bd=2, relief="sunken")
        entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        entry.focus_set()

        results = tk.Listbox(window, font=FONT_UI, bd=2, relief="sunken", activestyle="none")
        results.pack(fill="both", expand=True, padx=18, pady=6)

        status = tk.Label(window, text="Type at least 3 characters.", font=("MS Sans Serif", 8), bg=BG_PANEL, fg=INK_SOFT)
        status.pack(anchor="w", padx=18)

        matches: list[Location] = []

        def search() -> None:
            query = entry.get().strip()
            results.delete(0, tk.END)
            matches.clear()
            if len(query) < 3:
                status.configure(text="Type at least 3 characters.")
                return
            status.configure(text="Searching...")

            def done(found, error) -> None:
                if error is not None:
                    status.configure(text=f"Search failed: {error}")
                    return
                matches.extend(found)
                results.delete(0, tk.END)
                for item in found:
                    results.insert(tk.END, item.label)
                status.configure(text=f"{len(found)} location(s) found." if found else "No matches.")

            self._run_async(lambda: self.client.search_locations(query), done)

        def select(event=None) -> None:
            selection = results.curselection()
            if not selection:
                messagebox.showwarning("Location Manager", "Please select a location from the list.", parent=window)
                return
            self.set_location(matches[selection[0]])
            window.destroy()

        entry.bind("<Return>", lambda _event: search())
        results.bind("<Double-Button-1>", select)

        tk.Button(input_row, text="Search", font=("MS Sans Serif", 8, "bold"), bg=BG_BUTTON, command=search).pack(side="right")
        tk.Button(window, text="Select Location", font=FONT_UI_BOLD, bg=BG_BUTTON, fg=NAVY, command=select).pack(pady=10)

    def set_location(self, location: Location) -> None:
        self.location = location
        self.lbl_location.configure(text=location.label)
        self.current = None
        self.hourly = []
        self.daily = []
        self._save_settings()
        self._set_status(f"Location set to {location.label}")
        self.refresh_weather()

    # ------------------------------------------------------------------ #
    # Data loading
    # ------------------------------------------------------------------ #
    def refresh_weather(self) -> None:
        if self.location is None:
            self._set_status("No location selected. Use [Change Location] to pick one.")
            return
        location = self.location

        def work():
            return (
                self.client.get_current(location),
                self.client.get_hourly(location, 12),
                self.client.get_daily(location, 7),
            )

        def done(result, error) -> None:
            if error is not None:
                self._set_status(f"Weather request failed: {error}")
                return
            self.current, self.hourly, self.daily = result
            self.lbl_updated.configure(text=self.current.observed_at or "--")
            self._set_status(f"Updated for {location.label}")
            self.show_view(self.active_view)

        self._run_async(work, done)

    # ------------------------------------------------------------------ #
    # Structure watchdog
    # ------------------------------------------------------------------ #
    def check_structure_async(self, notify: bool = False) -> None:
        location_id = self.location.place_id if self.location and self.location.place_id else "USNY0996"

        def done(results, error) -> None:
            if error is not None:
                self.lbl_watchdog.configure(text="check failed", fg=INK_SOFT)
                if notify:
                    messagebox.showwarning("Structure Watchdog", f"Could not verify the page structure:\n{error}", parent=self.root)
                return
            critical = [r for r in results if r.status == STATUS_CRITICAL]
            warnings = [r for r in results if r.status != STATUS_CRITICAL and (r.missing_critical or r.missing_optional)]
            if critical:
                self.lbl_watchdog.configure(text=f"CRITICAL on {critical[0].page}", fg="#CC0000")
                self._report_critical(critical[0])
            elif warnings:
                self.lbl_watchdog.configure(text="warning", fg="#B25A00")
            else:
                self.lbl_watchdog.configure(text="OK", fg="#006600")
            if hasattr(self, "lbl_settings_watchdog"):
                self.lbl_settings_watchdog.configure(text=self.lbl_watchdog.cget("text"))
            if notify and not critical:
                self._set_status("Structure check passed" if not warnings else "Structure check: optional selectors missing")

        self._run_async(lambda: self.client.check_all(location_id), done)

    def _report_critical(self, result) -> None:
        report = result.report_path or "(report not written)"
        self._set_status(f"CRITICAL: {result.page} structure changed")
        messagebox.showerror(
            "Weather Channel Desktop - Maintenance Required",
            "The Weather Channel changed its page structure.\n\n"
            f"Page: {result.page}\n"
            f"Broken selectors: {', '.join(result.missing_critical)}\n\n"
            "A report with the new HTML was written for selector re-training:\n"
            f"{report}\n\n"
            "Update config/selectors.json, then re-run the watchdog.",
            parent=self.root,
        )


def selftest(*, window: bool = True) -> int:
    """Headless packaging check: resources resolve and the widget tree builds.

    Used by the build pipeline to prove a frozen executable is usable without
    opening a window on a CI machine.
    """
    logging.basicConfig(level=logging.WARNING)
    print(f"frozen        : {paths.is_frozen()}")
    print(f"resource_dir  : {paths.RESOURCE_DIR}")
    print(f"data_dir      : {paths.DATA_DIR}")
    print(f"config        : {paths.resolve_config_path()}")
    print(f"icon_dir      : {paths.ICON_DIR}")

    missing = [c for c in weather_icons.ICON_CATEGORIES if not weather_icons.icon_path(c).exists()]
    if missing:
        print(f"FAIL missing icons: {', '.join(missing)}")
        return 1
    print(f"icons         : {len(weather_icons.ICON_CATEGORIES)} present")

    config = load_config(paths.resolve_config_path())
    print(f"pages         : {', '.join(sorted(config['pages']))}")

    if window:
        root = tk.Tk()
        root.withdraw()
        try:
            app = WeatherChannelDesktop(root, client=WeatherChannelClient(config_path=paths.resolve_config_path()))
            loaded = len(app.icons)
            root.update_idletasks()
            print(f"widgets       : {len(root.winfo_children())} top-level, {loaded} icons loaded")
        finally:
            root.destroy()
    else:
        print("widgets       : skipped (--no-window)")

    print("SELFTEST OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest(window="--no-window" not in argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = tk.Tk()
    # The reference is kept alive for the lifetime of mainloop: Tkinter
    # callbacks do not own the controller instance.
    app = WeatherChannelDesktop(root)
    root.mainloop()
    return 0 if app is not None else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
