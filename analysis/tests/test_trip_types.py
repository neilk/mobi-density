import random
import unittest
from datetime import datetime

from trip_types import (FEATURES, assign, describe, kmeans, leisure_points, profile, silhouette,
                        straight_m, usable, vector, zscore)

STATIONS = {
    "A": {"id": "A", "name": "Office", "lat": 49.2800, "lon": -123.1200},
    "B": {"id": "B", "name": "Park", "lat": 49.2900, "lon": -123.1300},
}
SCENIC = {"A": 0.0, "B": 1.0}


def trip(dep="A", ret="B", distance_m=2000, duration_s=600, when=datetime(2026, 7, 6, 8), rider="member", ebike=0):
    return {"dep_id": dep, "ret_id": ret, "distance_m": str(distance_m), "duration_s": str(duration_s),
            "dep": when, "departure": when.isoformat(sep=" "), "rider": rider, "ebike": str(ebike)}


class DescribeTests(unittest.TestCase):
    def test_straight_line_between_the_two_test_stations_is_about_1_3_km(self):
        self.assertAlmostEqual(straight_m(STATIONS["A"], STATIONS["B"]), 1320, delta=30)

    def test_directness_is_straight_line_over_odometer(self):
        d = describe(trip(distance_m=2640), STATIONS, SCENIC)
        self.assertAlmostEqual(d["directness"], 0.5, places=1)

    def test_round_trip_has_directness_zero(self):
        d = describe(trip(dep="B", ret="B", distance_m=5000), STATIONS, SCENIC)
        self.assertEqual(d["directness"], 0.0)
        self.assertTrue(d["round"])

    def test_directness_is_capped_at_one(self):
        d = describe(trip(distance_m=1000), STATIONS, SCENIC)      # shorter than the straight line
        self.assertEqual(d["directness"], 1.0)

    def test_speed_scenic_hour_weekend_and_month(self):
        d = describe(trip(distance_m=3000, duration_s=900, when=datetime(2026, 7, 4, 14)), STATIONS, SCENIC)
        self.assertAlmostEqual(d["speed_kmh"], 12.0)
        self.assertEqual((d["scenic_dep"], d["scenic_ret"]), (0.0, 1.0))
        self.assertEqual(d["hour"], 14)
        self.assertTrue(d["weekend"])                               # a Saturday
        self.assertEqual(d["month"], "2026-07")

    def test_vector_has_one_value_per_feature(self):
        d = describe(trip(), STATIONS, SCENIC)
        self.assertEqual(len(vector(d)), len(FEATURES))
        self.assertEqual(FEATURES[-1], "weekend")
        self.assertEqual(vector(d)[-1], 0.0)                        # a Monday


class UsableTests(unittest.TestCase):
    def test_a_normal_trip_is_usable(self):
        self.assertIsNone(usable(describe(trip(), STATIONS, SCENIC)))

    def test_a_kilometre_in_under_a_minute_is_not(self):
        self.assertEqual(usable(describe(trip(distance_m=1500, duration_s=23), STATIONS, SCENIC)), "duration under 60 s")

    def test_speed_over_30_kmh_is_not(self):
        self.assertEqual(usable(describe(trip(distance_m=6000, duration_s=600), STATIONS, SCENIC)), "speed over 30 km/h")

    def test_odometer_over_40_km_is_not(self):
        self.assertEqual(usable(describe(trip(distance_m=50000, duration_s=7200), STATIONS, SCENIC)), "odometer over 40 km")

    def test_a_station_to_station_trip_with_no_odometer_is_not(self):
        self.assertEqual(usable(describe(trip(distance_m=0, duration_s=600), STATIONS, SCENIC)), "no odometer")

    def test_a_slow_trip_is_kept(self):
        self.assertIsNone(usable(describe(trip(distance_m=1000, duration_s=3600), STATIONS, SCENIC)))


class LeisurePointsTests(unittest.TestCase):
    """The explorer's heuristic: round trip +3, seawall end +2, >40 min +2 (>20 +1),
    weekend +1, midday +1, detour over 1.8x +1; four points is leisure."""

    def test_weekday_morning_office_to_park_direct_ride_scores_two_for_the_park(self):
        d = describe(trip(duration_s=600, distance_m=1400), STATIONS, SCENIC)
        self.assertEqual(leisure_points(d), 2)

    def test_round_trip_from_the_park_on_a_weekend_afternoon_for_an_hour(self):
        d = describe(trip("B", "B", 8000, 3600, datetime(2026, 7, 4, 13)), STATIONS, SCENIC)
        self.assertEqual(leisure_points(d), 3 + 2 + 2 + 1 + 1)

    def test_detour_point_needs_ends_300_m_apart_and_ratio_over_1_8(self):
        far = describe(trip("A", "B", 2640, 600), STATIONS, SCENIC)          # 2x the straight line
        self.assertEqual(leisure_points(far), 2 + 1)
        near = {**far, "straight_m": 100.0, "distance_m": 1000.0}
        self.assertEqual(leisure_points(near), 2)

    def test_twenty_five_minutes_is_one_point_not_two(self):
        d = describe(trip("A", "A", 3000, 1500), STATIONS, SCENIC)
        self.assertEqual(leisure_points(d), 3 + 1)


class KMeansTests(unittest.TestCase):
    def blobs(self):
        rng = random.Random(1)
        pts = [[rng.gauss(0, .3), rng.gauss(0, .3)] for _ in range(200)]
        pts += [[rng.gauss(5, .3), rng.gauss(5, .3)] for _ in range(200)]
        return pts

    def test_zscore_centres_and_scales_each_column(self):
        means, sds, z = zscore([[1, 10], [3, 30], [5, 50]])
        self.assertEqual(means, [3, 30])
        self.assertAlmostEqual(z[0][0], -z[2][0])
        self.assertAlmostEqual(sum(v[1] ** 2 for v in z) / 3, 1.0)

    def test_zscore_leaves_a_constant_column_at_zero(self):
        _, _, z = zscore([[1, 7], [2, 7]])
        self.assertEqual([v[1] for v in z], [0.0, 0.0])

    def test_kmeans_finds_two_blobs(self):
        pts = self.blobs()
        centroids, labels, inertia = kmeans(pts, 2, random.Random(0))
        self.assertEqual(len(centroids), 2)
        self.assertEqual(len(set(labels[:200])), 1)
        self.assertEqual(len(set(labels[200:])), 1)
        self.assertNotEqual(labels[0], labels[-1])
        self.assertLess(inertia, 400 * 2 * .3 ** 2 * 2)

    def test_assign_gives_the_nearest_centroid(self):
        self.assertEqual(assign([[0.1, 0], [4.9, 5]], [[0, 0], [5, 5]]), [0, 1])

    def test_silhouette_is_high_for_separated_blobs_and_low_for_a_bad_split(self):
        pts = self.blobs()
        good = [0] * 200 + [1] * 200
        bad = [i % 2 for i in range(400)]
        self.assertGreater(silhouette(pts, good, random.Random(0), 100), 0.8)
        self.assertLess(silhouette(pts, bad, random.Random(0), 100), 0.1)


class ProfileTests(unittest.TestCase):
    def test_profile_counts_and_medians_per_cluster(self):
        recs = [describe(trip(distance_m=1000, duration_s=300), STATIONS, SCENIC),
                describe(trip(distance_m=3000, duration_s=600, rider="casual"), STATIONS, SCENIC),
                describe(trip("B", "B", 9000, 3600, datetime(2026, 7, 4, 13), rider="casual", ebike=1), STATIONS, SCENIC)]
        p = profile(recs, [0, 0, 1], 2, STATIONS)
        self.assertEqual([c["n"] for c in p], [2, 1])
        self.assertEqual(p[0]["median"]["distance_m"], 2000)
        self.assertEqual(p[0]["casual_share"], 0.5)
        self.assertEqual(p[1]["round_share"], 1.0)
        self.assertEqual(p[1]["ebike_share"], 1.0)
        self.assertEqual(p[1]["hours"][13], 1)
        self.assertEqual(p[1]["months"]["2026-07"], 1)
        self.assertEqual(p[1]["top_dep"][0]["name"], "Park")
        self.assertEqual(p[1]["leisure_share"], 1.0)


if __name__ == "__main__":
    unittest.main()
