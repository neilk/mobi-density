import unittest
from collections import defaultdict
from datetime import datetime

from flows import SLICES, Group, accumulate, draws_for, group_trips, slice_of


def t(dep_id, ret_id, rider, distance_m, dep):
    return {"dep_id": dep_id, "ret_id": ret_id, "rider": rider, "distance_m": str(distance_m),
            "dep": dep, "departure": dep.isoformat(sep=" ")}


class SliceTests(unittest.TestCase):
    def test_slices_are_24_in_the_documented_order(self):
        self.assertEqual(len(SLICES), 24)
        self.assertEqual(SLICES[0], "weekday|07:00-10:00|member")
        self.assertEqual(SLICES[-1], "weekend|22:00-07:00|casual")

    def test_slice_of_a_saturday_evening_casual_trip(self):
        trip = {"dep": datetime(2026, 7, 4, 18, 0), "rider": "casual"}      # a Saturday
        self.assertEqual(SLICES[slice_of(trip)], "weekend|16:00-19:00|casual")

    def test_draws_for(self):
        self.assertEqual([draws_for(n) for n in (1, 8, 20, 30, 500)], [8, 8, 20, 30, 30])

    def test_draws_for_a_float_count_is_an_int(self):
        self.assertIs(type(draws_for(20.0)), int)         # Group.n sums floats; range() needs an int
        self.assertEqual(draws_for(20.0), 20)


class GroupingTests(unittest.TestCase):
    def test_group_trips_bins_by_250m_and_keeps_slice_counts(self):
        trips = [t("A", "B", "member", 900, datetime(2026, 7, 6, 8)),      # Monday morning
                 t("A", "B", "member", 1100, datetime(2026, 7, 6, 17)),
                 t("A", "B", "member", 1300, datetime(2026, 7, 6, 8))]
        groups = group_trips(trips)
        self.assertEqual(set(groups), {"A|B|member|3", "A|B|member|4", "A|B|member|5"})
        g = groups["A|B|member|3"]
        self.assertEqual(g.n, 1)
        self.assertEqual(g.metres, 900)
        self.assertEqual(g.counts[SLICES.index("weekday|07:00-10:00|member")], 1)

    def test_group_metres_is_the_median_odometer(self):
        trips = [t("A", "A", "casual", d, datetime(2026, 7, 4, 12)) for d in (9000, 9100, 9200)]
        self.assertEqual(group_trips(trips)["A|A|casual|36"].metres, 9100)

    def test_accumulate_spreads_one_trip_over_its_draws(self):
        loads = defaultdict(lambda: [0.0] * 24)
        counts = [0.0] * 24
        counts[0] = 1.0
        accumulate(loads, [([0, 1, 2], [], 0), [[0, 3, 2], 0]], counts, draws=2)
        self.assertAlmostEqual(sum(v[0] for v in loads.values()), 2.0)     # two edges per route, half a trip each
        self.assertAlmostEqual(loads[(0, 1)][0], 0.5)
        self.assertAlmostEqual(loads[(1, 2)][0], 0.5)
        self.assertNotIn((2, 1), loads)                                     # undirected keys


if __name__ == "__main__":
    unittest.main()


class RunTests(unittest.TestCase):
    def test_cache_round_trip_is_keyed_on_settings_and_draws(self):
        from flows import RouteCache
        cache = RouteCache(":memory:")
        cache.put("A|B|member|3", "s1", 8, [[[0, 1, 2], 200.0]])
        self.assertEqual(cache.get("A|B|member|3", "s1", 8), [[[0, 1, 2], 200.0]])
        self.assertIsNone(cache.get("A|B|member|3", "s2", 8))
        self.assertIsNone(cache.get("A|B|member|3", "s1", 30))

    def test_settings_digest_changes_with_a_knob(self):
        from unittest.mock import patch
        import corridors
        from flows import settings_digest
        before = settings_digest()
        with patch.object(corridors, "SIGMA", 0.5):
            self.assertNotEqual(settings_digest(), before)

    def test_snap_stations_reports_the_far_ones(self):
        from corridors import Corridors
        from flows import snap_stations
        from tests.stub import StubAttractors, StubNet
        net = StubNet()
        lat, lon = net.latlon[0]
        stations = {"near": {"lat": lat, "lon": lon, "name": "n"},
                    "far": {"lat": lat + 0.01, "lon": lon, "name": "f"}}     # about 1.1 km off
        snap, far = snap_stations(stations, Corridors(net, StubAttractors()))
        self.assertEqual(list(snap), ["near"])
        self.assertEqual(far, ["far"])


class RunTests(unittest.TestCase):
    def test_workers_for_limits_by_memory(self):
        from flows import workers_for
        self.assertEqual(workers_for(15, 24 * 2 ** 30), 8)
        self.assertEqual(workers_for(2, 64 * 2 ** 30), 2)
        self.assertEqual(workers_for(8, 1 * 2 ** 30), 1)

    def test_sample_origin_takes_destinations_in_order(self):
        import flows
        from corridors import Corridors
        from tests.stub import StubAttractors, StubNet
        flows._CORR = Corridors(StubNet(), StubAttractors())
        jobs = [("k2", 0, 2, "member", 200, 2), ("k1", 0, 1, "member", 100, 2)]
        done, failed = flows.sample_origin(jobs)
        self.assertEqual([k for k, _ in done], ["k1", "k2"])
        self.assertEqual(failed, [])
