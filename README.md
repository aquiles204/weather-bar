# weather-bar

A slim, transparent weather overlay for the GNOME desktop. Shows current conditions in a pill-shaped bar pinned to the top-center of the screen, plus a system-tray icon.

[![Latest release](https://img.shields.io/github/v/release/aquiles204/weather-bar?label=Download&logo=github)](https://github.com/aquiles204/weather-bar/releases/latest/download/weather-bar_1.6_all.deb)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

![weather-bar screenshot](https://raw.githubusercontent.com/aquiles204/weather-bar/master/screenshot.png)

## Features

- Current temperature, weather description, humidity, and wind speed
- Emoji + GNOME stock icons in the system tray
- Celsius / Fahrenheit toggle
- Auto-detects your location via IP (no config needed) or accepts a city name
- Auto-refreshes every 10 minutes
- No API key required — uses [open-meteo](https://open-meteo.com/) and [ipinfo.io](https://ipinfo.io/)

## Requirements

```
python3  python3-gi  gir1.2-gtk-3.0
```

Ubuntu / Debian users get these by default with a GNOME desktop.

## Install (Debian / Ubuntu)

```bash
wget https://github.com/aquiles204/weather-bar/releases/latest/download/weather-bar_1.6_all.deb
sudo dpkg -i weather-bar_1.6_all.deb
```

## Usage

```bash
weather-bar                        # auto-detect city from IP
weather-bar --city Madrid          # fixed city
weather-bar --unit F               # Fahrenheit
weather-bar --monitor 1            # second monitor
```

### Controls

| Action | Result |
|--------|--------|
| Left-click bar | Refresh now |
| Right-click bar | Menu (set city, switch unit, quit) |
| Left-click tray icon | Refresh now |
| Right-click tray icon | Same menu |

## Autostart on login

```bash
weather-bar-autostart
```

This installs a `.desktop` entry in `~/.config/autostart/`.

## Run from source

```bash
git clone https://github.com/aquiles204/weather-bar.git
cd weather-bar
python3 weather_bar.py
```

## Configuration

Settings are saved to `~/.config/weather-bar/config.json`. Logs go to `~/.config/weather-bar/weather-bar.log`.

## License

MIT
