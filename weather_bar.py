#!/usr/bin/env python3
"""weather-bar — Slim weather overlay widget for the GNOME desktop.

Shows current weather in a transparent bar pinned to the top of the screen
and as a system-tray icon.
Data source: wttr.in (no API key needed).

Usage:
  python3 weather_bar.py [--city CITY] [--unit C|F] [--monitor N]

Top bar  : left-click → refresh,  right-click → menu
Tray icon: left-click → refresh,  right-click → menu

Requirements (standard on Ubuntu GNOME):
  sudo apt install python3-gi gir1.2-gtk-3.0
"""

import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib

# Silence GTK C-level critical messages (e.g. StatusIcon scale_factor on GNOME)
GLib.log_set_handler('Gtk', GLib.LogLevelFlags.LEVEL_CRITICAL, lambda *_: None)

import argparse
import json
import os
import ssl
import threading
import urllib.parse
import urllib.request

# ── Constants ────────────────────────────────────────────────────────────────

REFRESH_INTERVAL = 600   # seconds between auto-updates (10 min)
BAR_HEIGHT       = 42    # pixels

CONFIG_DIR  = os.path.expanduser('~/.config/weather-bar')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')

DEFAULT_CFG = {'city': '', 'unit': 'C', 'monitor': 0}

# ── Weather code → emoji, stock icon name & description ─────────────────────

# Maps WMO weather code (open-meteo) → (emoji, GNOME stock icon name, description)
WMO_CODES = {
    0:  ('☀️',  'weather-clear',            'Clear sky'),
    1:  ('☀️',  'weather-clear',            'Mainly clear'),
    2:  ('⛅',  'weather-few-clouds',        'Partly cloudy'),
    3:  ('☁️',  'weather-overcast',          'Overcast'),
    45: ('🌫️', 'weather-fog',               'Foggy'),
    48: ('🌫️', 'weather-fog',               'Icy fog'),
    51: ('🌦️', 'weather-showers-scattered', 'Light drizzle'),
    53: ('🌦️', 'weather-showers-scattered', 'Drizzle'),
    55: ('🌦️', 'weather-showers-scattered', 'Dense drizzle'),
    56: ('🌧️', 'weather-showers',           'Freezing drizzle'),
    57: ('🌧️', 'weather-showers',           'Heavy freezing drizzle'),
    61: ('🌦️', 'weather-showers-scattered', 'Slight rain'),
    63: ('🌧️', 'weather-showers',           'Moderate rain'),
    65: ('🌧️', 'weather-showers',           'Heavy rain'),
    66: ('🌧️', 'weather-showers',           'Freezing rain'),
    67: ('🌧️', 'weather-showers',           'Heavy freezing rain'),
    71: ('🌨️', 'weather-snow',              'Slight snow'),
    73: ('🌨️', 'weather-snow',              'Moderate snow'),
    75: ('❄️',  'weather-snow',              'Heavy snow'),
    77: ('❄️',  'weather-snow',              'Snow grains'),
    80: ('🌦️', 'weather-showers-scattered', 'Slight showers'),
    81: ('🌧️', 'weather-showers',           'Moderate showers'),
    82: ('🌧️', 'weather-showers',           'Violent showers'),
    85: ('🌨️', 'weather-snow',              'Slight snow showers'),
    86: ('❄️',  'weather-snow',              'Heavy snow showers'),
    95: ('⛈️', 'weather-storm',             'Thunderstorm'),
    96: ('⛈️', 'weather-storm',             'Thunderstorm w/ hail'),
    99: ('⛈️', 'weather-storm',             'Thunderstorm w/ hail'),
}

# ── Styling ──────────────────────────────────────────────────────────────────

CSS = b"""
window {
    background-color: transparent;
}
#bar {
    background-color: rgba(12, 12, 22, 0.82);
    border-radius: 0 0 14px 14px;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-top: none;
    padding: 5px 22px;
}
#main-text {
    color: #eeeef8;
    font-size: 14px;
}
#loc-text {
    color: #7788aa;
    font-size: 12px;
    margin-left: 14px;
}
"""

# ── Config helpers ────────────────────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CFG, **json.load(f)}
    return dict(DEFAULT_CFG)


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)


# ── Weather fetch / parse ────────────────────────────────────────────────────

# Build an SSL context that works even when launched outside a shell (e.g. from
# a desktop autostart entry) where SSL_CERT_FILE / SSL_CERT_DIR may be unset.
_SSL_CAFILE = '/etc/ssl/certs/ca-certificates.crt'   # standard on Debian/Ubuntu
_SSL_CTX = ssl.create_default_context(
    cafile=_SSL_CAFILE if os.path.exists(_SSL_CAFILE) else None
)


LOG_FILE = os.path.expanduser('~/.config/weather-bar/weather-bar.log')


def _log(msg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            import datetime
            f.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n')
    except Exception:
        pass


def _api_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'weather-bar/1.0'})
    with urllib.request.urlopen(req, timeout=8, context=_SSL_CTX) as r:
        return json.loads(r.read())


def fetch_weather(city=''):
    """Fetch weather via open-meteo (no API key required).

    If *city* is given it is geocoded first; otherwise the current IP location
    is used via ipinfo.io.  Returns a normalised dict consumed by parse_weather.
    """
    if city:
        geo = _api_get(
            'https://geocoding-api.open-meteo.com/v1/search?'
            + urllib.parse.urlencode({'name': city, 'count': 1, 'language': 'en'})
        )
        results = geo.get('results', [])
        if not results:
            raise ValueError(f'City not found: {city!r}')
        r         = results[0]
        lat, lon  = r['latitude'], r['longitude']
        city_name = r['name']
        country   = r.get('country', r.get('country_code', ''))
    else:
        ip        = _api_get('https://ipinfo.io/json')
        lat, lon  = (float(x) for x in ip['loc'].split(','))
        city_name = ip.get('city', '')
        country   = ip.get('country', '')

    wx = _api_get(
        'https://api.open-meteo.com/v1/forecast?'
        + urllib.parse.urlencode({
            'latitude':        lat,
            'longitude':       lon,
            'current':         'temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code',
            'wind_speed_unit': 'kmh',
        })
    )['current']

    # Support both old (weathercode/windspeed_10m) and new (weather_code/wind_speed_10m) API keys
    wind = wx.get('wind_speed_10m', wx.get('windspeed_10m', 0))
    code = wx.get('weather_code', wx.get('weathercode', 0))

    return {
        'temp_C':   wx['temperature_2m'],
        'humidity': wx['relative_humidity_2m'],
        'wind_kmh': round(wind, 1),
        'code':     int(code),
        'city':     city_name,
        'country':  country,
    }


def parse_weather(data, unit='C', city_override=''):
    code             = data['code']
    emoji, icon, desc = WMO_CODES.get(code, ('🌡️', 'weather-severe-alert', 'Unknown'))

    temp_c   = data['temp_C']
    temp_val = temp_c if unit == 'C' else round(temp_c * 9 / 5 + 32, 1)
    temp     = f'{temp_val}°{unit}'

    hum     = data['humidity']
    wind    = data['wind_kmh']
    city    = city_override.strip() or data['city']
    country = data['country']

    return {
        'line':      f'{emoji}  {temp}  {desc}   💧{hum}%   💨{wind} km/h',
        'location':  f'📍 {city}, {country}',
        'tray_tip':  f'{emoji} {city}  {temp}  {desc}\n💧 Humidity: {hum}%   💨 Wind: {wind} km/h',
        'tray_icon': icon,
        'temp':      temp,
        'code':      code,
    }


# ── System-tray icon ─────────────────────────────────────────────────────────

class WeatherTray:
    """Gtk.StatusIcon tray icon showing current temperature."""

    def __init__(self, on_refresh, on_set_city, on_toggle_unit, cfg):
        self._on_refresh     = on_refresh
        self._on_set_city    = on_set_city
        self._on_toggle_unit = on_toggle_unit
        self.cfg = cfg

        self._icon = Gtk.StatusIcon()
        self._icon.set_from_icon_name('weather-few-clouds')
        self._icon.set_tooltip_text('Weather Bar — loading…')
        self._icon.set_visible(True)
        self._icon.connect('activate',            self._left_click)
        self._icon.connect('popup-menu',          self._right_click)

    def update(self, wx):
        self._icon.set_from_icon_name(wx['tray_icon'])
        self._icon.set_tooltip_text(wx['tray_tip'])

    def set_loading(self):
        self._icon.set_tooltip_text('Weather Bar — loading…')

    def _left_click(self, _icon):
        self._on_refresh()

    def _right_click(self, _icon, button, time):
        unit  = self.cfg.get('unit', 'C')
        menu  = Gtk.Menu()
        items = [
            ('↺  Refresh now',                             self._on_refresh),
            ('📍 Set city…',                               self._on_set_city),
            (f'°  Switch to °{"F" if unit=="C" else "C"}', self._on_toggle_unit),
            (None, None),
            ('✕  Quit',                                    Gtk.main_quit),
        ]
        for label, cb in items:
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
            else:
                item = Gtk.MenuItem(label=label)
                item.connect('activate', lambda _w, f=cb: f())
                menu.append(item)
        menu.show_all()
        menu.popup(None, None, Gtk.StatusIcon.position_menu,
                   self._icon, button, time)


# ── Main widget ───────────────────────────────────────────────────────────────

class WeatherBar(Gtk.Window):

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._setup_window()
        self._build_ui()
        self._position()
        self._tray = WeatherTray(
            on_refresh=self.refresh,
            on_set_city=self._set_city,
            on_toggle_unit=self._toggle_unit,
            cfg=cfg,
        )
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_INTERVAL, self._tick)

    # ── Window setup ─────────────────────────────────────────────────────────

    def _setup_window(self):
        self.set_title('weather-bar')
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_app_paintable(True)

        self.connect('realize', lambda *_: self._position())
        self.connect('size-allocate', lambda *_: GLib.idle_add(self._recenter))

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self):
        # Outer box: centers the pill-shaped bar horizontally
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.START)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar.set_name('bar')
        outer.pack_start(bar, False, False, 0)

        self.main_lbl = Gtk.Label(label='⏳  Fetching weather…')
        self.main_lbl.set_name('main-text')

        self.loc_lbl = Gtk.Label(label='')
        self.loc_lbl.set_name('loc-text')

        bar.pack_start(self.main_lbl, False, False, 0)
        bar.pack_start(self.loc_lbl,  False, False, 0)

        self.add(outer)
        self.connect('button-press-event', self._on_click)

    def _position(self):
        display  = Gdk.Display.get_default()
        idx      = min(self.cfg['monitor'], display.get_n_monitors() - 1)
        monitor  = display.get_monitor(idx)
        workarea = monitor.get_workarea()
        self._workarea = workarea
        # Size the window to its natural content width — no full-width overlay
        # that would block clicks on other windows (e.g. Firefox title bar).
        self.set_size_request(-1, BAR_HEIGHT)
        self.resize(1, BAR_HEIGHT)

    def _recenter(self):
        """Re-position the pill at the top-center of the monitor."""
        wa = getattr(self, '_workarea', None)
        if wa is None:
            return False
        w = self.get_allocated_width()
        if w <= 1:
            return False
        self.move(wa.x + (wa.width - w) // 2, wa.y)
        return False

    # ── Data ─────────────────────────────────────────────────────────────────

    def refresh(self):
        self.main_lbl.set_text('⏳  Loading…')
        self.loc_lbl.set_text('')
        self._tray.set_loading()
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    def _fetch_thread(self):
        import time
        city = self.cfg.get('city', '')
        unit = self.cfg.get('unit', 'C')
        last_err = None
        for attempt in range(2):
            if attempt:
                time.sleep(5)
            try:
                _log(f'fetch attempt {attempt + 1}, city={city!r}')
                data = fetch_weather(city)
                wx   = parse_weather(data, unit, city)
                _log(f'fetch ok: {wx["line"]}')
                GLib.idle_add(self._apply, wx, None)
                return
            except Exception as e:
                last_err = e
                _log(f'fetch error: {e}')
        GLib.idle_add(self._apply, None, str(last_err))

    def _apply(self, wx, err):
        if err:
            self.main_lbl.set_text(f'⚠  {err}')
            self.loc_lbl.set_text('')
        else:
            self.main_lbl.set_text(wx['line'])
            self.loc_lbl.set_text(wx['location'])
            self._tray.update(wx)
        return False   # idle_add one-shot

    def _tick(self):
        self.refresh()
        return True    # keep the timer alive

    # ── Interaction ───────────────────────────────────────────────────────────

    def _on_click(self, _widget, event):
        if event.button == 1:
            self.refresh()
        elif event.button == 3:
            self._show_menu(event)

    def _show_menu(self, event):
        menu  = Gtk.Menu()
        unit  = self.cfg.get('unit', 'C')
        items = [
            ('↺  Refresh now',                    self.refresh),
            ('📍 Set city…',                       self._set_city),
            (f'°  Switch to °{"F" if unit=="C" else "C"}', self._toggle_unit),
            (None, None),
            ('✕  Quit',                            Gtk.main_quit),
        ]
        for label, cb in items:
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
            else:
                item = Gtk.MenuItem(label=label)
                item.connect('activate', lambda _w, f=cb: f())
                menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)

    def _set_city(self):
        dlg = Gtk.Dialog(title='Set city', transient_for=self, modal=True)
        dlg.add_buttons('Cancel', Gtk.ResponseType.CANCEL,
                        'OK',     Gtk.ResponseType.OK)
        entry = Gtk.Entry(
            text=self.cfg.get('city', ''),
            placeholder_text='e.g. Madrid   (empty = auto-detect by IP)',
        )
        entry.connect('activate', lambda *_: dlg.response(Gtk.ResponseType.OK))
        box = dlg.get_content_area()
        box.set_border_width(14)
        box.add(entry)
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            self.cfg['city'] = entry.get_text().strip()
            save_config(self.cfg)
            self.refresh()
        dlg.destroy()

    def _toggle_unit(self):
        self.cfg['unit'] = 'F' if self.cfg.get('unit', 'C') == 'C' else 'C'
        save_config(self.cfg)
        self.refresh()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='Weather bar for GNOME desktop')
    p.add_argument('--city',    help='City name (overrides saved config)')
    p.add_argument('--unit',    choices=['C', 'F'], help='Temperature unit')
    p.add_argument('--monitor', type=int, default=None,
                   help='Monitor index (0 = primary)')
    args = p.parse_args()

    cfg = load_config()
    if args.city    is not None: cfg['city']    = args.city
    if args.unit    is not None: cfg['unit']    = args.unit
    if args.monitor is not None: cfg['monitor'] = args.monitor

    win = WeatherBar(cfg)
    win.show_all()
    win.connect('destroy', Gtk.main_quit)
    Gtk.main()


if __name__ == '__main__':
    main()
