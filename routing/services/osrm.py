"""Thin client for the public OSRM routing service (free, no API key).

A single request returns the full driving route (geometry + distance), which is
all we need -- this is the one external routing call per API request.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings

METERS_PER_MILE = 1609.344


class RoutingError(Exception):
    pass


@dataclass
class Route:
    distance_miles: float
    duration_seconds: float
    # Polyline as a list of (lat, lon) vertices, in travel order.
    coordinates: list[tuple[float, float]]


def get_route(
    start: tuple[float, float],
    finish: tuple[float, float],
) -> Route:
    """Fetch a driving route between two (lat, lon) points via OSRM.

    OSRM expects coordinates as ``lon,lat``. We request full GeoJSON geometry so
    we can both draw the route and project fuel stations onto it.
    """
    coords = f"{start[1]},{start[0]};{finish[1]},{finish[0]}"
    url = f"{settings.OSRM_BASE_URL}/route/v1/driving/{coords}"
    params = {"overview": "full", "geometries": "geojson", "alternatives": "false"}

    try:
        resp = requests.get(
            url,
            params=params,
            timeout=settings.HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": settings.HTTP_USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RoutingError(f"Routing service request failed: {exc}") from exc

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(
            f"Could not find a route: {data.get('message', data.get('code', 'unknown error'))}"
        )

    route = data["routes"][0]
    # GeoJSON LineString coordinates are [lon, lat]; flip to (lat, lon).
    line = route["geometry"]["coordinates"]
    coordinates = [(lat, lon) for lon, lat in line]

    return Route(
        distance_miles=route["distance"] / METERS_PER_MILE,
        duration_seconds=route["duration"],
        coordinates=coordinates,
    )
