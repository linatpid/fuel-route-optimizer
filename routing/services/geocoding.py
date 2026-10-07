"""Geocode the two trip endpoints via Nominatim (OpenStreetMap, free).

Only the start and finish are geocoded -- never the stations (those are
pre-geocoded at load time). Results are cached so repeated endpoints cost
nothing, and a raw ``"lat,lon"`` input skips the network entirely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

_LATLON_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$"
)
_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days


class GeocodingError(Exception):
    pass


@dataclass
class Place:
    latitude: float
    longitude: float
    label: str


def geocode(location: str) -> Place:
    """Resolve a free-text US location (or ``"lat,lon"``) to coordinates."""
    location = location.strip()
    if not location:
        raise GeocodingError("Location must not be empty.")

    # Fast path: explicit coordinates, no external call.
    m = _LATLON_RE.match(location)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return Place(latitude=lat, longitude=lon, label=f"{lat:.5f}, {lon:.5f}")

    cache_key = f"geocode:{location.lower()}"
    cached = cache.get(cache_key)
    if cached:
        return Place(**cached)

    params = {
        "q": location,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "us",
        "addressdetails": 0,
    }
    try:
        resp = requests.get(
            f"{settings.NOMINATIM_BASE_URL}/search",
            params=params,
            timeout=settings.HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": settings.HTTP_USER_AGENT},
        )
        resp.raise_for_status()
        results = resp.json()
    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding request failed: {exc}") from exc

    if not results:
        raise GeocodingError(f"Could not geocode location: {location!r}")

    top = results[0]
    place = Place(
        latitude=float(top["lat"]),
        longitude=float(top["lon"]),
        label=top.get("display_name", location),
    )
    cache.set(cache_key, place.__dict__, _CACHE_TTL)
    return place
