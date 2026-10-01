#!/usr/bin/env python3
"""weather-bar for Windows 11 — System-tray weather widget.

Sits in the Windows notification area (system tray).
Left-click  → refresh
Right-click → menu (Set city, Switch unit, Quit)

Requirements:
  pip install pystray pillow

Usage:
  python weather_bar_win.py [--city CITY] [--unit C|F]
"""

import argparse
import json
import os
import ssl
import threading
import time
import urllib.parse
import urllib.request
from PIL import Image, ImageDraw, ImageFont
import pystray

# ── Constants ────────────────────────────────────────────────────────────────

REFRESH_INTERVAL = 600   # seconds between auto-updates (10 min)
ICON_SIZE        = 64    # tray icon canvas size in pixels

CONFIG_DIR  = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'weather-bar')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
LOG_FILE    = os.path.join(CONFIG_DIR, 'weather-bar.log')

DEFAULT_CFG = {'city': '', 'unit': 'C'}

# ── WMO weather codes ────────────────────────────────────────────────────────

WMO_CODES = {
    0:  ('☀',  'Clear sky'),
    1:  ('☀',  'Mainly clear'),
    2:  ('⛅', 'Partly cloudy'),
    3:  ('☁',  'Overcast'),
    45: ('🌫', 'Foggy'),
    48: ('🌫', 'Icy fog'),
    51: ('🌦', 'Light drizzle'),
    53: ('🌦', 'Drizzle'),
    55: ('🌦', 'Dense drizzle'),
    56: ('🌧', 'Freezing drizzle'),
    57: ('🌧', 'Heavy freezing drizzle'),
    61: ('🌦', 'Slight rain'),
    63: ('🌧', 'Moderate rain'),
    65: ('🌧', 'Heavy rain'),
    66: ('🌧', 'Freezing rain'),
    67: ('🌧', 'Heavy freezing rain'),
    71: ('🌨', 'Slight snow'),
    73: ('🌨', 'Moderate snow'),
    75: ('❄',  'Heavy snow'),
    77: ('❄',  'Snow grains'),
    80: ('🌦', 'Slight showers'),
    81: ('🌧', 'Moderate showers'),
    82: ('🌧', 'Violent showers'),
    85: ('🌨', 'Slight snow showers'),
    86: ('❄',  'Heavy snow showers'),
    95: ('⛈', 'Thunderstorm'),
    96: ('⛈', 'Thunderstorm w/ hail'),
    99: ('⛈', 'Thunderstorm w/ hail'),
}

# ── Config ───────────────────────────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CFG, **json.load(f)}
    return dict(DEFAULT_CFG)


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)


# ── Logging ──────────────────────────────────────────────────────────────────

def _log(msg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            import datetime
            f.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n')
    except Exception:
        pass


# ── Weather fetch / parse ────────────────────────────────────────────────────

_SSL_CTX = ssl.create_default_context()


def _api_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'weather-bar/1.0'})
    with urllib.request.urlopen(req, timeout=8, context=_SSL_CTX) as r:
        return json.loads(r.read())


def fetch_weather(city=''):
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

    wind = wx.get('wind_speed_10m', wx.get('windspeed_10m', 0))
    code = wx.get('weather_code',   wx.get('weathercode', 0))

    return {
        'temp_C':   wx['temperature_2m'],
        'humidity': wx['relative_humidity_2m'],
        'wind_kmh': round(wind, 1),
        'code':     int(code),
        'city':     city_name,
        'country':  country,
    }


def parse_weather(data, unit='C', city_override=''):
    code          = data['code']
    emoji, desc   = WMO_CODES.get(code, ('?', 'Unknown'))
    temp_c        = data['temp_C']
    temp_val      = temp_c if unit == 'C' else round(temp_c * 9 / 5 + 32, 1)
    temp          = f'{temp_val}°{unit}'
    city          = city_override.strip() or data['city']
    country       = data['country']
    hum           = data['humidity']
    wind          = data['wind_kmh']

    return {
        'emoji':    emoji,
        'temp':     temp,
        'desc':     desc,
        'city':     city,
        'country':  country,
        'humidity': hum,
        'wind':     wind,
        'tooltip':  (
            f'{emoji} {city}, {country}\n'
            f'{temp}  {desc}\n'
            f'Humidity: {hum}%   Wind: {wind} km/h'
        ),
        'icon_label': f'{temp_val:.0f}°',
    }


# ── Tray icon image ──────────────────────────────────────────────────────────

def _make_icon_image(label, bg=(30, 30, 50), fg=(238, 238, 248)):
    """Render *label* (e.g. '22°') into a small square PIL image."""
    img  = Image.new('RGBA', (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Rounded rectangle background
    draw.rounded_rectangle([0, 0, ICON_SIZE - 1, ICON_SIZE - 1], radius=12, fill=bg)

    # Try to load a small font; fall back to default if not available
    font = None
    font_size = 22
    for font_path in [
        'C:/Windows/Fonts/segoeui.ttf',
        'C:/Windows/Fonts/arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ]:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, font_size)
            except Exception:
                pass
            break

    if font is None:
        font = ImageFont.load_default()

    bbox  = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (ICON_SIZE - tw) // 2 - bbox[0]
    y = (ICON_SIZE - th) // 2 - bbox[1]
    draw.text((x, y), label, font=font, fill=fg)
    return img


def _loading_image():
    return _make_icon_image('...', bg=(40, 40, 60))


def _error_image():
    return _make_icon_image('!', bg=(120, 30, 30))


# ── App ───────────────────────────────────────────────────────────────────────

class WeatherTrayApp:

    def __init__(self, cfg):
        self.cfg      = cfg
        self._wx      = None
        self._lock    = threading.Lock()

        self._icon = pystray.Icon(
            name='weather-bar',
            icon=_loading_image(),
            title='Weather Bar — loading…',
            menu=self._build_menu(),
        )

    # ── Menu ─────────────────────────────────────────────────────────────────

    def _build_menu(self):
        unit = self.cfg.get('unit', 'C')
        return pystray.Menu(
            pystray.MenuItem('Refresh now',                      lambda _: self._trigger_refresh()),
            pystray.MenuItem('Set city…',                        lambda _: self._prompt_city()),
            pystray.MenuItem(f'Switch to °{"F" if unit=="C" else "C"}',
                             lambda _: self._toggle_unit()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit',                             lambda _: self._quit()),
        )

    def _rebuild_menu(self):
        self._icon.menu = self._build_menu()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _trigger_refresh(self):
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self):
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
                _log(f'fetch ok: {wx["temp"]} {wx["desc"]}')
                with self._lock:
                    self._wx = wx
                self._icon.icon  = _make_icon_image(wx['icon_label'])
                self._icon.title = wx['tooltip']
                return
            except Exception as e:
                last_err = e
                _log(f'fetch error: {e}')
        self._icon.icon  = _error_image()
        self._icon.title = f'Weather Bar — error: {last_err}'

    def _auto_refresh_loop(self):
        while True:
            time.sleep(REFRESH_INTERVAL)
            self._trigger_refresh()

    # ── Interactions ──────────────────────────────────────────────────────────

    def _prompt_city(self):
        # Use tkinter for a minimal input dialog (ships with Python on Windows)
        try:
            import tkinter as tk
            from tkinter import simpledialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            city = simpledialog.askstring(
                'Weather Bar — Set city',
                'Enter city name (leave blank for auto-detect by IP):',
                initialvalue=self.cfg.get('city', ''),
                parent=root,
            )
            root.destroy()
            if city is not None:
                self.cfg['city'] = city.strip()
                save_config(self.cfg)
                self._trigger_refresh()
        except Exception as e:
            _log(f'city dialog error: {e}')

    def _toggle_unit(self):
        self.cfg['unit'] = 'F' if self.cfg.get('unit', 'C') == 'C' else 'C'
        save_config(self.cfg)
        self._rebuild_menu()
        self._trigger_refresh()

    def _quit(self):
        self._icon.stop()

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        threading.Thread(target=self._auto_refresh_loop, daemon=True).start()
        self._icon.run(setup=lambda _: self._trigger_refresh())


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='Weather Bar for Windows 11')
    p.add_argument('--city', help='City name (overrides saved config)')
    p.add_argument('--unit', choices=['C', 'F'], help='Temperature unit')
    args = p.parse_args()

    cfg = load_config()
    if args.city is not None: cfg['city'] = args.city
    if args.unit is not None: cfg['unit'] = args.unit

    WeatherTrayApp(cfg).run()


if __name__ == '__main__':
    main()
