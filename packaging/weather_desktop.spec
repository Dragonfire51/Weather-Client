# PyInstaller spec for the Weather Channel Desktop client.
#
# Build (from the repository root):
#     pyinstaller packaging/weather_desktop.spec --noconfirm
#
# The bundle is one-file and windowed (no console). Read-only resources
# (icons/, config/selectors.json) are embedded; the application writes its
# settings, logs and HTML snapshots to %APPDATA%\WeatherChannelDesktop via
# paths.py, so nothing is written next to the executable.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "icons"), "icons"),
    (str(ROOT / "config" / "selectors.json"), "config"),
]

hiddenimports = ["bs4", "soupsieve", "requests", "charset_normalizer", "idna", "urllib3"]

a = Analysis(
    [str(ROOT / "weather_desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "PIL", "tkinter.test", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WeatherChannelDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "weather.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)
