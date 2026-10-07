from django.test import SimpleTestCase

from routing.geo import (
    cumulative_miles,
    haversine_miles,
    is_within_usa,
    point_to_segment_miles,
)


class GeoTests(SimpleTestCase):
    def test_haversine_known_distance(self):
        # New York City -> Los Angeles, great-circle ~2448 miles.
        d = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        self.assertAlmostEqual(d, 2448, delta=25)

    def test_haversine_zero(self):
        self.assertAlmostEqual(haversine_miles(10, 20, 10, 20), 0.0, places=6)

    def test_cumulative_miles_monotonic(self):
        coords = [(40.0, -80.0), (40.0, -81.0), (40.0, -82.0)]
        cum = cumulative_miles(coords)
        self.assertEqual(cum[0], 0.0)
        self.assertLess(cum[0], cum[1])
        self.assertLess(cum[1], cum[2])

    def test_point_on_segment_has_zero_distance(self):
        dist, t = point_to_segment_miles(40.0, -80.5, 40.0, -80.0, 40.0, -81.0)
        self.assertAlmostEqual(dist, 0.0, delta=0.1)
        self.assertAlmostEqual(t, 0.5, delta=0.05)

    def test_point_off_segment_distance_positive(self):
        dist, _ = point_to_segment_miles(40.5, -80.5, 40.0, -80.0, 40.0, -81.0)
        self.assertGreater(dist, 10)

    def test_within_usa_accepts_us_points(self):
        self.assertTrue(is_within_usa(41.88, -87.63))   # Chicago
        self.assertTrue(is_within_usa(29.76, -95.37))   # Houston
        self.assertTrue(is_within_usa(61.22, -149.90))  # Anchorage, AK
        self.assertTrue(is_within_usa(21.31, -157.86))  # Honolulu, HI

    def test_within_usa_rejects_foreign_and_ocean_points(self):
        self.assertFalse(is_within_usa(48.8566, 2.3522))    # Paris
        self.assertFalse(is_within_usa(19.4326, -99.1332))  # Mexico City
        self.assertFalse(is_within_usa(0.0, -40.0))         # mid-Atlantic
        self.assertFalse(is_within_usa(51.5074, -0.1278))   # London
