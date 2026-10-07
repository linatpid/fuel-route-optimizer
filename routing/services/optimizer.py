"""Cost-optimal fuel-stop planning.

Problem: a vehicle drives ``distance`` miles. It has a maximum range of
``max_range`` miles and does ``mpg`` miles per gallon (so a full tank holds
``max_range / mpg`` gallons). Fuel can be bought at any station lying along the
route, each at its own price. Choose where to buy so the whole trip is covered
and the **total fuel cost is minimised**.

Model / assumptions
-------------------
* Total fuel burned over the trip is fixed at ``distance / mpg`` gallons.
* The cost therefore depends only on *where* those gallons are bought.
* Stopping is free and any amount may be purchased, up to a tank's worth.

Optimal solution
----------------
Every mile of the trip is powered by fuel bought at some station that is at
most ``max_range`` miles behind that mile (you cannot carry fuel further than a
tank's range). To minimise cost, each mile should draw from the **cheapest
station within that backward window**. Assigning every mile to the cheapest
reachable preceding station is both a lower bound (any feasible plan must buy
each mile's fuel from within the window) and achievable (just buy exactly those
amounts at each station), so it is optimal.

We evaluate that assignment exactly with a sweep over the breakpoints where the
"stations currently within range" set changes -- i.e. where a station enters the
window (at its own mile marker) or leaves it (``max_range`` miles later).

The only concession to reality: the stretch before the first station (the truck
leaves with an empty tank) is attributed to that first station, i.e. we assume
the driver tops up at the first stop. In practice the nearest truck-stop is a
few miles from any US start point, so this is negligible.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class RouteInfeasibleError(Exception):
    """Raised when some stretch of the route has no reachable fuel station."""


@dataclass
class Candidate:
    """A station available along the route."""

    mile: float          # distance from start, along the route
    price: float         # retail price per gallon
    payload: dict = field(default_factory=dict)  # station details for the response


@dataclass
class FuelStop:
    mile: float
    price: float
    gallons: float
    cost: float
    payload: dict


@dataclass
class OptimizationResult:
    stops: list[FuelStop]
    total_gallons: float
    total_cost: float


def optimize_fuel_stops(
    distance_miles: float,
    candidates: list[Candidate],
    max_range_miles: float,
    mpg: float,
) -> OptimizationResult:
    """Return the minimum-cost set of fuel stops for the trip.

    ``candidates`` need not be sorted. Stations beyond the route (mile > distance)
    or before it are ignored.
    """
    if distance_miles <= 0:
        return OptimizationResult(stops=[], total_gallons=0.0, total_cost=0.0)

    usable = sorted(
        (c for c in candidates if 0.0 <= c.mile <= distance_miles),
        key=lambda c: c.mile,
    )
    if not usable:
        raise RouteInfeasibleError("No fuel stations found along the route.")

    # Build sweep breakpoints: every station mile, every station mile + range,
    # plus the trip endpoints. Between consecutive breakpoints the set of
    # in-range stations is constant, so one station is cheapest throughout.
    marks = {0.0, distance_miles}
    for c in usable:
        if c.mile < distance_miles:
            marks.add(c.mile)
        if c.mile + max_range_miles < distance_miles:
            marks.add(c.mile + max_range_miles)
    breakpoints = sorted(m for m in marks if 0.0 <= m <= distance_miles)

    gallons_by_index: dict[int, float] = {}
    cost_total = 0.0
    gallons_total = 0.0
    first_mile = usable[0].mile

    for start, end in zip(breakpoints, breakpoints[1:]):
        seg_len = end - start
        if seg_len <= 0:
            continue
        # Pick a representative point inside the segment to decide the window.
        x = (start + end) / 2.0

        best_idx = -1
        best_price = None
        for i, c in enumerate(usable):
            # Station powers miles in [c.mile, c.mile + max_range].
            if c.mile <= x <= c.mile + max_range_miles:
                if best_price is None or c.price < best_price:
                    best_price = c.price
                    best_idx = i

        if best_idx == -1:
            # Only acceptable before the very first station: attribute to it.
            if x < first_mile:
                best_idx = 0
                best_price = usable[0].price
            else:
                raise RouteInfeasibleError(
                    f"No fuel station within {max_range_miles:.0f} miles around "
                    f"mile {x:.0f}; the vehicle cannot complete the route."
                )

        gallons = seg_len / mpg
        gallons_by_index[best_idx] = gallons_by_index.get(best_idx, 0.0) + gallons
        gallons_total += gallons
        cost_total += gallons * best_price

    stops: list[FuelStop] = []
    for i in sorted(gallons_by_index):
        c = usable[i]
        gallons = gallons_by_index[i]
        stops.append(
            FuelStop(
                mile=c.mile,
                price=c.price,
                gallons=round(gallons, 3),
                cost=round(gallons * c.price, 2),
                payload=c.payload,
            )
        )

    return OptimizationResult(
        stops=stops,
        total_gallons=round(gallons_total, 3),
        total_cost=round(cost_total, 2),
    )
