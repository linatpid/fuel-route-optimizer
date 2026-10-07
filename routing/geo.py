"""Lightweight geometry helpers.

Pure-Python, no PostGIS/GEOS dependency, so the project runs on plain SQLite.
The dataset (~8k stations, a single route polyline) is small enough that these
simple vectate-free routines are more than fast enough.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _local_scale(lat: float) -> tuple[float, float]:
    """Miles-per-degree of latitude and longitude near a given latitude.

    Good enough for the short distances involved in matching a station to a
    route corridor, and far cheaper than a haversine per segment.
    """
    miles_per_deg_lat = 69.0
    miles_per_deg_lon = 69.0 * math.cos(math.radians(lat))
    return miles_per_deg_lat, miles_per_deg_lon


def point_to_segment_miles(
    plat: float,
    plon: float,
    alat: float,
    alon: float,
    blat: float,
    blon: float,
) -> tuple[float, float]:
    """Distance from point P to segment A-B and the fraction (0..1) along A-B
    of the closest point. Uses a local equirectangular projection (miles).
    """
    mlat, mlon = _local_scale((alat + blat) / 2)

    # Project to a local planar frame centred on A (units: miles).
    ax, ay = 0.0, 0.0
    bx = (blon - alon) * mlon
    by = (blat - alat) * mlat
    px = (plon - alon) * mlon
    py = (plat - alat) * mlat

    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        t = 0.0
    else:
        t = (px * dx + py * dy) / seg_len_sq
        t = max(0.0, min(1.0, t))

    cx, cy = ax + t * dx, ay + t * dy
    dist = math.hypot(px - cx, py - cy)
    return dist, t


def cumulative_miles(coords: Sequence[tuple[float, float]]) -> list[float]:
    """Cumulative great-circle distance (miles) at each vertex of a polyline.

    `coords` is a list of (lat, lon). Returns a list the same length where
    element i is the distance from the first vertex to vertex i.
    """
    cum = [0.0]
    for (lat1, lon1), (lat2, lon2) in zip(coords, coords[1:]):
        cum.append(cum[-1] + haversine_miles(lat1, lon1, lat2, lon2))
    return cum


def bounding_box(
    coords: Iterable[tuple[float, float]], margin_miles: float
) -> tuple[float, float, float, float]:
    """Axis-aligned lat/lon bounding box around a polyline, expanded by a margin.

    Returns (min_lat, min_lon, max_lat, max_lon).
    """
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    mid_lat = (min_lat + max_lat) / 2
    mlat, mlon = _local_scale(mid_lat)
    dlat = margin_miles / mlat
    dlon = margin_miles / max(mlon, 1e-6)
    return (min_lat - dlat, min_lon - dlon, max_lat + dlat, max_lon + dlon)
