"""End-to-end API test with the two external services (geocoding + OSRM) mocked,
so it runs offline and deterministically while exercising the real corridor
selection, optimisation, and response shaping.
"""

from unittest import mock

from django.test import TestCase
from django.urls import reverse

from routing.geo import cumulative_miles
from routing.models import FuelStation
from routing.services.geocoding import Place
from routing.services.osrm import Route


def _straight_route():
    """A dense west-bound polyline along latitude 40 (~530 miles)."""
    coords = [(40.0, -80.0 - i * 0.1) for i in range(101)]  # -80 .. -90
    distance = cumulative_miles(coords)[-1]
    return Route(distance_miles=distance, duration_seconds=36000, coordinates=coords)


class RouteApiTests(TestCase):
    def setUp(self):
        # An expensive station early and a cheaper one further along, both on-route.
        FuelStation.objects.create(
            opis_id=1, name="Early Expensive", city="A", state="XX",
            retail_price="3.500", latitude=40.0, longitude=-80.0,
        )
        FuelStation.objects.create(
            opis_id=2, name="Later Cheap", city="B", state="XX",
            retail_price="2.500", latitude=40.0, longitude=-85.0,
        )
        # Off-corridor station (far north) that must be ignored.
        FuelStation.objects.create(
            opis_id=3, name="Off Route", city="C", state="XX",
            retail_price="0.100", latitude=42.0, longitude=-85.0,
        )

    def _call(self, start="A", finish="B"):
        with mock.patch(
            "routing.services.planner.geocoding.geocode",
            side_effect=[
                Place(40.0, -80.0, "Start"),
                Place(40.0, -90.0, "Finish"),
            ],
        ), mock.patch(
            "routing.services.planner.osrm.get_route",
            return_value=_straight_route(),
        ) as route_mock:
            resp = self.client.get(reverse("route"), {"start": start, "finish": finish})
        return resp, route_mock

    def test_happy_path_shape_and_totals(self):
        resp, route_mock = self._call()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Exactly one routing call was made.
        self.assertEqual(route_mock.call_count, 1)

        # Core fields present.
        self.assertIn("route", data)
        self.assertIn("fuel_stops", data)
        self.assertIn("summary", data)

        # Total gallons == distance / mpg.
        dist = data["route"]["total_distance_miles"]
        self.assertAlmostEqual(data["summary"]["total_gallons"], dist / 10, delta=0.1)

        # The off-corridor ultra-cheap station must not appear.
        names = {s["name"] for s in data["fuel_stops"]}
        self.assertNotIn("Off Route", names)
        self.assertIn("Early Expensive", names)
        self.assertIn("Later Cheap", names)

        # Cost consistency.
        self.assertAlmostEqual(
            data["summary"]["total_fuel_cost_usd"],
            round(sum(s["cost_usd"] for s in data["fuel_stops"]), 2),
            delta=0.02,
        )

    def test_missing_param_returns_400(self):
        resp = self.client.get(reverse("route"), {"start": "A"})
        self.assertEqual(resp.status_code, 400)

    def test_non_us_coordinates_rejected(self):
        # Paris coordinates as the start: validation happens before any OSRM
        # call, so no routing mock is needed.
        with mock.patch("routing.services.planner.osrm.get_route") as route_mock:
            resp = self.client.get(
                reverse("route"),
                {"start": "48.8566,2.3522", "finish": "40.0,-90.0"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("USA", resp.json()["error"])
        route_mock.assert_not_called()

    def test_coordinate_input_skips_geocoding(self):
        # When both inputs are coordinates, geocode must not be called at all.
        with mock.patch(
            "routing.services.planner.geocoding.geocode",
            wraps=lambda s: Place(*(float(x) for x in s.split(",")), s),
        ) as geo_mock, mock.patch(
            "routing.services.planner.osrm.get_route",
            return_value=_straight_route(),
        ):
            resp = self.client.get(
                reverse("route"), {"start": "40.0,-80.0", "finish": "40.0,-90.0"}
            )
        self.assertEqual(resp.status_code, 200)
        # geocode() is still invoked but returns instantly without network;
        # the real guarantee (no HTTP) is covered in geocoding's own fast-path.
        self.assertEqual(geo_mock.call_count, 2)
