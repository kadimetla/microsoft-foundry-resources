"""Open-Meteo weather service for the workshop MCP server.

Self-contained: no API key, no extra SDK. The geocoding step turns a free-form
city string into (lat, lon, canonical_name), then the forecast endpoint returns
current conditions. Adapted from the Azure-Samples `remote-mcp-functions-python`
McpWeatherApp sample (MIT-licensed).

This is an imported helper, not a standalone application. Do not launch it
with python or create another environment for it. function_app.py imports
get_current_weather and exposes the MCP tool. Follow the complete macOS
Terminal or Windows PowerShell instructions at the top of function_app.py
to start Azurite and the Functions host with func start.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

_REQUEST_TIMEOUT_SECONDS = 8.0

_WMO_CONDITIONS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Fog (depositing rime)",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm w/ hail",
    99: "Thunderstorm w/ heavy hail",
}


def _normalize_location(location: str | None) -> str:
    if not location or not location.strip():
        return "Seattle, WA"
    return location.strip()


def _deg_to_cardinal(deg: float) -> str:
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    return dirs[round((deg % 360) / 22.5) % 16]


def _http_get_json(url: str) -> dict[str, Any] | None:
    """Tiny GET helper; returns parsed JSON or None on failure."""
    try:
        with urllib.request.urlopen(url, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logging.warning("Open-Meteo call failed: %s — %s", url, exc)
        return None


def _geocode_candidates(location: str) -> list[str]:
    """Open-Meteo's geocoder only matches single tokens like 'Seattle' — not
    'Seattle, WA'. Try the full string first, then progressively simpler
    variants so that natural-language inputs from the LLM still resolve.
    """
    location = location.strip()
    seen: list[str] = [location]
    # 'Seattle, WA' -> 'Seattle'
    if "," in location:
        head = location.split(",", 1)[0].strip()
        if head and head not in seen:
            seen.append(head)
    # 'New York City' -> 'New York' (drop trailing word) is too aggressive; skip.
    return seen


def _geocode(location: str) -> tuple[float, float, str] | None:
    for candidate in _geocode_candidates(location):
        qs = urllib.parse.urlencode({"name": candidate, "count": 1, "language": "en", "format": "json"})
        data = _http_get_json(f"https://geocoding-api.open-meteo.com/v1/search?{qs}")
        if not data:
            continue
        results = data.get("results") or []
        if not results:
            logging.info("geocode miss for %r", candidate)
            continue
        r = results[0]
        parts = [r.get("name"), r.get("admin1"), r.get("country")]
        canonical = ", ".join(p for p in parts if p)
        return float(r["latitude"]), float(r["longitude"]), canonical or candidate
    return None


def _current_observation(lat: float, lon: float) -> dict[str, Any] | None:
    qs = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,weather_code",
        "wind_speed_unit": "kmh",
    })
    data = _http_get_json(f"https://api.open-meteo.com/v1/forecast?{qs}")
    return data.get("current") if data else None


def get_current_weather(location: str | None) -> dict[str, Any]:
    """Return current weather for ``location`` as a JSON-serializable dict.

    Always returns a structured dict; on failure ``error`` is populated so the
    LLM has something useful to relay to the user instead of an exception
    bubbling up.
    """
    requested = _normalize_location(location)
    logging.info("get_current_weather requested for %r", requested)

    geo = _geocode(requested)
    if not geo:
        return {
            "location": requested,
            "error": "Could not resolve this location. Try a city, region, or ZIP/postal code.",
            "source": "open-meteo",
        }

    lat, lon, canonical = geo
    obs = _current_observation(lat, lon)
    if not obs:
        return {
            "location": canonical,
            "error": "Could not retrieve current observations.",
            "source": "open-meteo",
        }

    temp_c = obs.get("temperature_2m")
    temp_f = round(temp_c * 1.8 + 32) if isinstance(temp_c, (int, float)) else None
    wind_kph = obs.get("wind_speed_10m")
    wind_dir_deg = obs.get("wind_direction_10m")
    wind = (
        f"{round(wind_kph)} km/h {_deg_to_cardinal(wind_dir_deg)}"
        if isinstance(wind_kph, (int, float)) and isinstance(wind_dir_deg, (int, float))
        else None
    )
    code = obs.get("weather_code")
    condition = _WMO_CONDITIONS.get(int(code), "Unknown") if isinstance(code, (int, float)) else "Unknown"

    reported = obs.get("time")
    try:
        reported_utc = (
            datetime.fromisoformat(str(reported).replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except (TypeError, ValueError):
        reported_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "location": canonical,
        "condition": condition,
        "temperature_c": round(temp_c) if isinstance(temp_c, (int, float)) else None,
        "temperature_f": temp_f,
        "humidity_percent": round(obs["relative_humidity_2m"])
            if isinstance(obs.get("relative_humidity_2m"), (int, float)) else None,
        "wind": wind,
        "reported_at_utc": reported_utc,
        "source": "open-meteo",
    }
