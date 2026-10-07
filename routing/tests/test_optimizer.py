"""Tests for the cost-optimal fuel-stop algorithm (pure logic, no network)."""

from django.test import SimpleTestCase

from routing.services.optimizer import (
    Candidate,
    RouteInfeasibleError,
    optimize_fuel_stops,
)

RANGE = 500.0
MPG = 10.0


def opt(distance, stations):
    return optimize_fuel_stops(
        distance_miles=distance,
        candidates=[Candidate(mile=m, price=p) for m, p in stations],
        max_range_miles=RANGE,
        mpg=MPG,
    )


class OptimizerTests(SimpleTestCase):
    def test_total_gallons_always_distance_over_mpg(self):
        res = opt(300, [(0, 3.0), (100, 2.5)])
        self.assertAlmostEqual(res.total_gallons, 30.0, places=3)

    def test_single_station_covers_short_trip(self):
        res = opt(100, [(0, 3.0)])
        self.assertEqual(len(res.stops), 1)
        self.assertAlmostEqual(res.total_cost, 30.0, places=2)  # 10 gal * $3

    def test_prefers_cheaper_station_once_reachable(self):
        # Miles [0,50) must use the $3 station (the $2 one is still ahead);
        # miles [50,100) use the $2 station. => 5*3 + 5*2 = 25.
        res = opt(100, [(0, 3.0), (50, 2.0)])
        self.assertAlmostEqual(res.total_cost, 25.0, places=2)
        by_mile = {s.mile: s.gallons for s in res.stops}
        self.assertAlmostEqual(by_mile[0.0], 5.0, places=3)
        self.assertAlmostEqual(by_mile[50.0], 5.0, places=3)

    def test_look_ahead_fills_at_cheap_station_to_skip_expensive(self):
        # Cheap station early should power as far as its range reaches.
        res = opt(450, [(0, 3.0), (400, 2.0)])
        # [0,400)=40 gal @3 =120 ; [400,450)=5 gal @2 =10
        self.assertAlmostEqual(res.total_cost, 130.0, places=2)

    def test_infeasible_when_gap_exceeds_range(self):
        with self.assertRaises(RouteInfeasibleError):
            opt(1000, [(0, 3.0)])  # nothing within 500 mi after mile 500

    def test_no_stations_is_infeasible(self):
        with self.assertRaises(RouteInfeasibleError):
            opt(100, [])

    def test_stations_beyond_route_are_ignored(self):
        res = opt(100, [(0, 3.0), (999, 0.1)])
        self.assertEqual(len(res.stops), 1)
        self.assertAlmostEqual(res.total_cost, 30.0, places=2)

    def test_cost_equals_sum_of_stop_costs(self):
        res = opt(600, [(0, 3.2), (250, 2.8), (520, 2.5)])
        self.assertAlmostEqual(
            res.total_cost, round(sum(s.cost for s in res.stops), 2), places=2
        )
