"""Orchestrate geocoding -> routing -> station selection -> optimisation.

Exactly one external routing call (OSRM) is made per request. Geocoding the two
endpoints uses Nominatim but is cached and skipped entirely when coordinates are
supplied directly, so a request can be served with a single external call.
"""

from __future__ import annotations

from django.conf import settings

from routing.geo import is_within_usa
from routing.services import geocoding, osrm
from routing.services.optimizer import Candidate, optimize_fuel_stops
from routing.services.stations import find_stations_along_route


def plan_route(start: str, finish: str) -> dict:
    """Plan a fuelled route between two locations and build the response dict."""
    origin = geocoding.geocode(start)
    destination = geocoding.geocode(finish)

    # Both endpoints must be within the USA (per the brief). This also guards
    # raw lat,lon input, which bypasses the US-pinned geocoder.
    for place, which in ((origin, "start"), (destination, "finish")):
        if not is_within_usa(place.latitude, place.longitude):
            raise geocoding.LocationOutsideUSAError(
                f"The {which} location ({place.label}) is outside the USA; "
                "both start and finish must be within the USA."
            )

    route = osrm.get_route(
        (origin.latitude, origin.longitude),
        (destination.latitude, destination.longitude),
    )

    nearby = find_stations_along_route(route.coordinates)

    candidates = [
        Candidate(
            mile=n.mile,
            price=n.price,
            payload={
                "opis_id": n.station.opis_id,
                "name": n.station.name,
                "address": n.station.address,
                "city": n.station.city,
                "state": n.station.state,
                "price_per_gallon": round(n.price, 3),
                "latitude": n.station.latitude,
                "longitude": n.station.longitude,
                "distance_from_start_miles": round(n.mile, 1),
                "detour_miles": n.detour_miles,
            },
        )
        for n in nearby
    ]

    result = optimize_fuel_stops(
        distance_miles=route.distance_miles,
        candidates=candidates,
        max_range_miles=settings.VEHICLE_MAX_RANGE_MILES,
        mpg=settings.VEHICLE_MPG,
    )

    fuel_stops = []
    for order, stop in enumerate(result.stops, start=1):
        fuel_stops.append(
            {
                "order": order,
                **stop.payload,
                "gallons_purchased": stop.gallons,
                "cost_usd": stop.cost,
            }
        )

    return {
        "start": {
            "query": start,
            "label": origin.label,
            "latitude": origin.latitude,
            "longitude": origin.longitude,
        },
        "finish": {
            "query": finish,
            "label": destination.label,
            "latitude": destination.latitude,
            "longitude": destination.longitude,
        },
        "route": {
            "total_distance_miles": round(route.distance_miles, 1),
            "estimated_drive_time_hours": round(route.duration_seconds / 3600, 2),
            "geometry": {
                "type": "LineString",
                # GeoJSON order is [lon, lat].
                "coordinates": [[lon, lat] for lat, lon in route.coordinates],
            },
        },
        "vehicle": {
            "max_range_miles": settings.VEHICLE_MAX_RANGE_MILES,
            "miles_per_gallon": settings.VEHICLE_MPG,
            "tank_capacity_gallons": round(
                settings.VEHICLE_MAX_RANGE_MILES / settings.VEHICLE_MPG, 1
            ),
        },
        "fuel_stops": fuel_stops,
        "summary": {
            "number_of_fuel_stops": len(fuel_stops),
            "total_gallons": result.total_gallons,
            "total_fuel_cost_usd": result.total_cost,
            "average_price_per_gallon": (
                round(result.total_cost / result.total_gallons, 3)
                if result.total_gallons
                else None
            ),
        },
    }
