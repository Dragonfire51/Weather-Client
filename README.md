# The Weather Channel Desktop (cliente Win32 retro en Python)

Un cliente de escritorio que imita la estética de *The Weather Channel Desktop*
de la era Windows XP (paleta Luna `#D6E3F7` / `#003399`, widgets nativos,
iconos pixel-art GIF). Extrae datos reales de weather.com, permite buscar
ciudades por nombre o código postal y vigila automáticamente la estructura HTML
de la página para avisar cuando los selectores se rompen.

```
weather_desktop.py     interfaz Tkinter (Win32 retro)
weather_scraper.py     cliente de datos + vigilante de estructura
weather_icons.py       mapeo código de icono -> categoría GIF
icons/                 sprites pixel-art 32x32 en GIF (se regeneran)
tools/make_icons.py    generador de iconos (sin dependencias externas)
tools/daily_structure_check.py   chequeo diario (cron / Task Scheduler)
config/selectors.json  registro de selectores + configuración de API
config/daily_check*.json / .xml / crontab.example   automatización cada 24 h
tests/                 suite de pruebas
logs/                  reportes CRITICAL y snapshots de HTML
```

## Instalación

```bash
python -m pip install -r requirements.txt
python tools/make_icons.py     # (opcional) regenera icons/*.gif
python weather_desktop.py      # abre la interfaz
```

Solo la biblioteca estándar es necesaria para la interfaz; `requests` y
`beautifulsoup4` se usan para los datos y el vigilante de estructura.

## Uso

1. Al abrir, la ventana muestra las condiciones actuales de la última ubicación
   guardada (por defecto New York).
2. Pulsa **[Change Location]** para abrir el *Location Manager*, escribe una
   ciudad o código postal (mínimo 3 caracteres) y selecciona un resultado.
3. Usa la barra lateral para cambiar entre **Local Weather**, **12-Hour
   Forecast**, **Extended Forecast**, **Weather Maps** y **Settings**.
4. En **Settings** puedes alternar entre **°C** y **°F**; la preferencia se
   guarda en `config/user_settings.json`.

## Fuente de datos

weather.com es hoy una SPA Next.js: el HTML ya no incluye los datos. El cliente
usa dos vías complementarias:

* **Datos** — la API JSON que la propia web consume
  (`api.weather.com/v3/wx/observations/current`,
  `/v3/wx/forecast/hourly/2day`, `/v3/wx/forecast/daily/10day`,
  `/v3/location/search`). La clave pública se descubre desde los bundles JS de
  weather.com y, si eso falla, se usa la de `config/selectors.json`.
* **Vigilancia** — se descarga el HTML de las páginas `today`, `hourbyhour` y
  `tenday` y se comprueba que sigan existiendo las anclas `data-testid`
  declaradas en `config/selectors.json`. Esas anclas se renderizan en el
  servidor y actúan como canario barato de cambios de maquetación.

## Vigilante de estructura y `CRITICAL_CHANGE_DETECTED`

Cada selector del registro es `critical` u `optional`:

| Estado | Significado | Acción |
| --- | --- | --- |
| `OK` | Todos los selectores presentes | Nada |
| `WARNING_SELECTOR_MISSING` | Falta un selector `optional` | Revisar, no urgente |
| `CRITICAL_CHANGE_DETECTED` | Falta un selector `critical` en una página `strict` | Reporte + aviso en la interfaz |

Cuando se detecta un cambio crítico:

* La interfaz muestra un `messagebox.showerror` clásico indicando la página y
  los selectores rotos.
* Se escribe `logs/critical-change-<pagina>-<AAAAMMDD-HHMMSS>.log` con:
  * la lista de selectores que aún funcionan y los que se rompieron,
  * el registro de selectores vigente en formato JSON,
  * la ruta al snapshot del HTML nuevo,
  * un prompt listo para pegar en DeepSeek/otro LLM para regenerar selectores.
* El HTML completo se guarda en `logs/snapshots/` (se conservan los 10 últimos).

Ejemplo de ejecución manual:

```bash
python weather_scraper.py --all-pages --location USNY0996
python tools/daily_structure_check.py --location USNY0996 --json
```

Códigos de salida del chequeo diario: `0` OK, `1` `CRITICAL_CHANGE_DETECTED`,
`2` no se pudo ejecutar. El histórico se acumula en
`logs/structure-check-history.jsonl`.

## Chequeo automático cada 24 horas

Hay tres formas equivalentes; elige la de tu plataforma.

* **Windows (Task Scheduler)** — `config/daily_check_task.xml`:

  ```bat
  schtasks /Create /TN "Weather Channel Structure Watchdog" /XML "config\daily_check_task.xml" /F
  ```

* **Linux / macOS (cron)** — `config/crontab.example`:

  ```
  0 6 * * *   cd /opt/weather-channel-desktop && python3 tools/daily_structure_check.py --location USNY0996
  ```

* **OpenHands (automatización)** — `config/daily_check.example.json` define un
  cron diario que ejecuta el chequeo y, ante `CRITICAL_CHANGE_DETECTED`, lanza
  un agente que lee el reporte, propone los selectores corregidos y abre un PR.

## Pruebas

```bash
pytest                                   # unitarias + vigilante (offline)
xvfb-run -a pytest tests/test_gui_smoke.py -m gui   # interfaz (requiere display)
WEATHER_LIVE=1 pytest -m live            # contra weather.com real
```

* `tests/test_scraper.py` — búsqueda de ubicaciones, condiciones actuales,
  pronóstico, claves de API, reintentos y conversión de unidades.
* `tests/test_structure_watchdog.py` — el núcleo del requerimiento: verifica
  que un selector renombrado, eliminado o una reescritura completa del layout
  produce `CRITICAL_CHANGE_DETECTED` y que el reporte con el HTML se escribe.
  Usa fixtures locales (`tests/fixtures/weather_today_ok.html`), derivados de
  una captura real de weather.com.
* `tests/test_live_structure.py` — los mismos chequeos contra el sitio real;
  es lo que se ejecuta a diario.
* `tests/test_gui_smoke.py` — la interfaz se construye, todas las vistas
  renderizan, el cambio de unidades funciona y el modal abre/cierra.
* `tests/test_packaging.py` — resolución de rutas en modo código y en modo
  congelado (`sys._MEIPASS` / `%APPDATA%`) y el sembrado del registro de
  selectores editable.

## Regenerar los iconos

`tools/make_icons.py` dibuja cada sprite y escribe GIF89a con un codificador
LZW propio, así que no necesita Pillow ni ninguna otra librería:

```bash
python tools/make_icons.py
```

Para cambiar un dibujo, edita la función correspondiente en `SPRITES` dentro de
`tools/make_icons.py` y vuelve a ejecutarlo.

## Empaquetar como .exe (Windows x64 y x86)

El repositorio trae un *spec* de PyInstaller, el icono `.ico` multirresolución y
el recurso de versión, así que el ejecutable se construye en un paso:

```bat
pip install pyinstaller pillow
python tools/make_icons.py
python tools/make_icon_ico.py
pyinstaller packaging\weather_desktop.spec --noconfirm --clean
```

El resultado es `dist\WeatherChannelDesktop.exe`: un único archivo, sin consola.

### Rutas cuando corre empaquetado

`paths.py` centraliza el layout:

| Contenido | Desde el código | Empaquetado |
| --- | --- | --- |
| Iconos y selectores (solo lectura) | carpeta del repo | `sys._MEIPASS` |
| `user_settings.json`, `logs/`, snapshots HTML | carpeta del repo | `%APPDATA%\WeatherChannelDesktop` |

Como el `.exe` de un archivo se descomprime en una carpeta temporal que se borra
al salir, los logs y ajustes viven en el perfil del usuario. En el primer
arranque se copia `config/selectors.json` a `%APPDATA%\WeatherChannelDesktop\config\`
y esa copia tiene prioridad: si el vigilante detecta un cambio crítico, corriges
el JSON **sin recompilar**.

### Verificar el binario

```bat
dist\WeatherChannelDesktop.exe --selftest
```

Comprueba que los 14 iconos, el registro de selectores y el árbol de widgets se
resuelven desde dentro del bundle. En CI se usa `--selftest --no-window`, que
omite la ventana.

### Automatización (GitHub Actions)

`.github/workflows/build.yml` corre lint y pruebas, y luego compila la matriz
**x64 + x86** en runners Windows (`setup-python` con `architecture: x86` produce
el binario de 32 bits). El job de release adjunta ambos `.exe` y un
`SHA256SUMS.txt` al release `latest` en cada push a `main`, y a un release
versionado cuando se empuja un tag `v*`.
