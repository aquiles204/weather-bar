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
import threading
import urllib.request

# ── Constants ────────────────────────────────────────────────────────────────

REFRESH_INTERVAL = 600   # seconds between auto-updates (10 min)
BAR_HEIGHT       = 42    # pixels

CONFIG_DIR  = os.path.expanduser('~/.config/weather-bar')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')

DEFAULT_CFG = {'city': '', 'unit': 'C', 'monitor': 0}

# ── Weather code → emoji & stock icon name ───────────────────────────────────

# Maps wttr.in weather code → (emoji, GNOME stock icon name)
# (emoji, GNOME stock icon name)
WX_ICON = {
    113: ('☀️',  'weather-clear'),
    116: ('⛅',  'weather-few-clouds'),
    119: ('☁️',  'weather-overcast'),
    122: ('☁️',  'weather-overcast'),
    143: ('🌫️', 'weather-fog'),
    176: ('🌦️', 'weather-showers-scattered'),
    179: ('🌨️', 'weather-snow'),
    182: ('🌧️', 'weather-showers'),
    185: ('🌧️', 'weather-showers'),
    200: ('⛈️', 'weather-storm'),
    227: ('🌨️', 'weather-snow'),
    230: ('❄️',  'weather-snow'),
    248: ('🌫️', 'weather-fog'),
    260: ('🌫️', 'weather-fog'),
    263: ('🌦️', 'weather-showers-scattered'),
    266: ('🌦️', 'weather-showers-scattered'),
    281: ('🌧️', 'weather-showers'),
    284: ('🌧️', 'weather-showers'),
    293: ('🌦️', 'weather-showers-scattered'),
    296: ('🌦️', 'weather-showers-scattered'),
    299: ('🌧️', 'weather-showers'),
    302: ('🌧️', 'weather-showers'),
    305: ('🌧️', 'weather-showers'),
    308: ('🌧️', 'weather-showers'),
    311: ('🌧️', 'weather-showers'),
    314: ('🌧️', 'weather-showers'),
    317: ('🌧️', 'weather-showers'),
    320: ('🌨️', 'weather-snow'),
    323: ('🌨️', 'weather-snow'),
    326: ('🌨️', 'weather-snow'),
    329: ('❄️',  'weather-snow'),
    332: ('❄️',  'weather-snow'),
    335: ('❄️',  'weather-snow'),
    338: ('❄️',  'weather-snow'),
    350: ('🌧️', 'weather-showers'),
    353: ('🌦️', 'weather-showers-scattered'),
    356: ('🌧️', 'weather-showers'),
    359: ('🌧️', 'weather-showers'),
    362: ('🌧️', 'weather-showers'),
    365: ('🌧️', 'weather-showers'),
    368: ('🌨️', 'weather-snow'),
    371: ('❄️',  'weather-snow'),
    374: ('🌧️', 'weather-showers'),
    377: ('🌧️', 'weather-showers'),
    386: ('⛈️', 'weather-storm'),
    389: ('⛈️', 'weather-storm'),
    392: ('⛈️', 'weather-storm'),
    395: ('⛈️', 'weather-storm'),
}

def wx_emoji(code):
    return WX_ICON.get(code, ('🌡️', 'weather-severe-alert'))[0]

def wx_stock(code):
    return WX_ICON.get(code, ('🌡️', 'weather-severe-alert'))[1]

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

def fetch_weather(city=''):
    url = f'https://wttr.in/{city}?format=j1'
    req = urllib.request.Request(url, headers={'User-Agent': 'weather-bar/1.0'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def parse_weather(data, unit='C', city_override=''):
    cur  = data['current_condition'][0]
    area = data['nearest_area'][0]

    country = area['country'][0]['value']
    # Prefer the user-configured city name; fall back to API area name
    city    = city_override.strip() or area['areaName'][0]['value']
    code    = int(cur['weatherCode'])
    temp    = cur['temp_F' if unit == 'F' else 'temp_C'] + f'°{unit}'
    desc    = cur['weatherDesc'][0]['value']
    hum     = cur['humidity']
    wind    = cur['windspeedKmph']

    return {
        'line':     f'{wx_emoji(code)}  {temp}  {desc}   💧{hum}%   💨{wind} km/h',
        'location': f'📍 {city}, {country}',
        'tray_tip': f'{wx_emoji(code)} {city}  {temp}  {desc}\n💧 Humidity: {hum}%   💨 Wind: {wind} km/h',
        'tray_icon': wx_stock(code),
        'temp':     temp,
        'code':     code,
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
        display = Gdk.Display.get_default()
        idx     = min(self.cfg['monitor'], display.get_n_monitors() - 1)
        geo     = display.get_monitor(idx).get_geometry()
        self.set_default_size(geo.width, BAR_HEIGHT)
        self.move(geo.x, geo.y)

    # ── Data ─────────────────────────────────────────────────────────────────

    def refresh(self):
        self.main_lbl.set_text('⏳  Loading…')
        self.loc_lbl.set_text('')
        self._tray.set_loading()
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    def _fetch_thread(self):
        try:
            data = fetch_weather(self.cfg.get('city', ''))
            wx   = parse_weather(data, self.cfg.get('unit', 'C'), self.cfg.get('city', ''))
            GLib.idle_add(self._apply, wx, None)
        except Exception as e:
            GLib.idle_add(self._apply, None, str(e))

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
