"""Select the fuel stations that lie along a route and place them on it.

Given the route polyline we need, for every nearby station, (a) whether it is
within the corridor and (b) how far along the route it sits (its "mile
marker"). We build a spatial hash grid of the route's vertices so each station
is tested against only a handful of nearby points -- O(stations + vertices)
rather than O(stations x vertices), which keeps cross-country routes fast.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from django.conf import settings

from routing.geo import cumulative_miles, haversine_miles
from routing.models import FuelStation


@dataclass
class NearbyStation:
    mile: float          # distance from start, along the route
    price: float
    detour_miles: float  # how far off the route the station sits
    station: FuelStation


def _grid_key(lat: float, lon: float, cell_deg: float) -> tuple[int, int]:
    return (math.floor(lat / cell_deg), math.floor(lon / cell_deg))


def find_stations_along_route(
    coordinates: list[tuple[float, float]],
    corridor_miles: float | None = None,
) -> list[NearbyStation]:
    """Return stations within ``corridor_miles`` of the route, with mile markers.

    ``coordinates`` is the route polyline as (lat, lon) vertices.
    """
    if len(coordinates) < 2:
        return []
    corridor_miles = corridor_miles or settings.ROUTE_CORRIDOR_MILES

    cum = cumulative_miles(coordinates)

    # Grid cell sized to the corridor so a station only needs to look at its own
    # cell and the 8 neighbours to find any route vertex within range.
    cell_deg = max(corridor_miles / 69.0, 1e-4)
    grid: dict[tuple[int, int], list[int]] = {}
    for idx, (lat, lon) in enumerate(coordinates):
        grid.setdefault(_grid_key(lat, lon, cell_deg), []).append(idx)

    # Bounding box of the route (plus margin) to prefilter the DB query.
    lats = [c[0] for c in coordinates]
    lons = [c[1] for c in coordinates]
    margin = cell_deg * 1.5
    qs = FuelStation.objects.filter(
        latitude__isnull=False,
        latitude__gte=min(lats) - margin,
        latitude__lte=max(lats) + margin,
        longitude__gte=min(lons) - margin,
        longitude__lte=max(lons) + margin,
    ).only("id", "opis_id", "name", "address", "city", "state", "retail_price",
           "latitude", "longitude")

    nearby: list[NearbyStation] = []
    for st in qs.iterator():
        base = _grid_key(st.latitude, st.longitude, cell_deg)
        best_dist = None
        best_idx = None
        for dlat in (-1, 0, 1):
            for dlon in (-1, 0, 1):
                for idx in grid.get((base[0] + dlat, base[1] + dlon), ()):  # noqa: E501
                    rlat, rlon = coordinates[idx]
                    d = haversine_miles(st.latitude, st.longitude, rlat, rlon)
                    if best_dist is None or d < best_dist:
                        best_dist = d
                        best_idx = idx
        if best_dist is not None and best_dist <= corridor_miles:
            nearby.append(
                NearbyStation(
                    mile=cum[best_idx],
                    price=float(st.retail_price),
                    detour_miles=round(best_dist, 2),
                    station=st,
                )
            )

    nearby.sort(key=lambda n: n.mile)
    return nearby
