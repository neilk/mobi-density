import random
import unittest
from unittest.mock import patch

from corridors import (MIN_FILL, Bounded, Corridors, NoRoute, Rider, build_graph, corridor, corridor_adj, cost_table,
                       metres_table, plain_route, sample_detour, sample_hop, shortest)
from tests.stub import StubAttractors, StubNet

ONES = {w: 1.0 for w in range(5)}


class CorridorTests(unittest.TestCase):
    def setUp(self):
        self.net = StubNet()
        self.fwd, self.rev = build_graph(self.net)
        self.out_m = metres_table(self.fwd, 0, 500)
        self.in_m = metres_table(self.rev, 2, 500)

    def test_corridor_drops_the_spur_and_keeps_the_square(self):
        edges = corridor(self.fwd, self.out_m, self.in_m, budget=210)     # 0->2 is 200 m either way round
        self.assertEqual({e[2] for e in edges}, {0, 1, 2, 3})

    def test_corridor_tightens_with_the_budget(self):
        self.assertEqual(corridor(self.fwd, self.out_m, self.in_m, budget=150), [])

    def test_shortest_follows_the_cheaper_way(self):
        adj = corridor_adj(corridor(self.fwd, self.out_m, self.in_m, budget=210))
        nodes, ways, metres = shortest(adj, 0, 2, ONES, {0: 5.0})   # way 0 made dear
        self.assertEqual(nodes, [0, 3, 2])
        self.assertAlmostEqual(metres, 200)

    def test_corridor_adj_bakes_in_the_edge_multiplier(self):
        edges = corridor(self.fwd, self.out_m, self.in_m, budget=210)
        adj = corridor_adj(edges, lambda u, v: 5.0 if (u, v) == (0, 1) else 1.0)
        self.assertEqual(shortest(adj, 0, 2, ONES, {})[0], [0, 3, 2])
        self.assertEqual(shortest(corridor_adj(edges), 0, 2, ONES, {})[0], [0, 1, 2])

    def test_sample_hop_stays_inside_the_fill_window(self):
        adj = corridor_adj(corridor(self.fwd, self.out_m, self.in_m, budget=210))
        factor, (nodes, ways, metres) = sample_hop(adj, 0, 2, 210, 200, random.Random(1))
        self.assertTrue(MIN_FILL * 200 <= metres <= 210)
        self.assertEqual((nodes[0], nodes[-1]), (0, 2))

    def test_sample_hop_raises_when_nothing_fits(self):
        adj = corridor_adj(corridor(self.fwd, self.out_m, self.in_m, budget=150))
        with self.assertRaises(NoRoute):
            sample_hop(adj, 0, 2, 150, 140, random.Random(1))

    def test_sample_detour_goes_out_and_back_on_the_spur(self):
        # 0->2 is 200 m, the odometer says 400: the only way to fill it is 0-1-4-1-2.
        out_m, in_m = metres_table(self.fwd, 0, 420), metres_table(self.rev, 2, 420)
        adj = corridor_adj(corridor(self.fwd, out_m, in_m, budget=420))
        rider = Rider(self.net, StubAttractors(), "errand")
        out_c, in_c = cost_table(self.fwd, 0, out_m), cost_table(self.rev, 2, in_m)
        factor, (nodes, ways, metres), t = sample_detour(self.net, adj, 0, 2, 420, out_m, in_m, rider, out_c, in_c,
                                                         400, random.Random(1), Bounded(4))
        self.assertEqual((nodes[0], nodes[-1], t), (0, 2, 4))
        self.assertIn(4, nodes)
        self.assertAlmostEqual(metres, 400)

    def test_plain_route_is_the_physically_shortest_path(self):
        out_m, in_m = metres_table(self.fwd, 0, 420), metres_table(self.rev, 4, 420)
        edges = corridor(self.fwd, out_m, in_m, budget=420)        # 0-1-4 at 200 m, or round the square at 400 m
        nodes, ways, metres = plain_route(edges, 0, 4)
        self.assertEqual(nodes, [0, 1, 4])
        self.assertAlmostEqual(metres, 200)

    def test_rider_attract_is_memoised(self):
        class Counting(StubAttractors):
            calls = 0

            def commercial(self, x, y):
                self.calls += 1
                return 0.5
        att = Counting()
        r = Rider(self.net, att, "errand")
        self.assertEqual(r.attract(1), r.attract(1))
        self.assertEqual(att.calls, 1)

    def test_bounded_memo_evicts_the_oldest(self):
        memo = Bounded(2)
        for k in range(3):
            memo.fetch(k, lambda k=k: k * 10)
        self.assertEqual(dict(memo), {1: 10, 2: 20})
        self.assertEqual(memo.fetch(2, lambda: "stale"), 20)


class CorridorsSampleTests(unittest.TestCase):
    def setUp(self):
        self.c = Corridors(StubNet(), StubAttractors())

    def test_sample_returns_the_requested_number_of_routes(self):
        routes = self.c.sample(0, 2, "member", metres=200, draws=8, seed=3)
        self.assertEqual(len(routes), 8)
        for nodes, ways, m in routes:
            self.assertEqual((nodes[0], nodes[-1]), (0, 2))
            self.assertTrue(170 <= m <= 210)

    def test_sample_is_reproducible(self):
        self.assertEqual(self.c.sample(0, 2, "member", 200, 8, seed=3), self.c.sample(0, 2, "member", 200, 8, seed=3))

    def test_sample_routes_a_long_hop_through_a_waypoint(self):
        routes = self.c.sample(0, 2, "member", metres=400, draws=4, seed=1)    # twice the direct distance
        self.assertEqual(len(routes), 4)
        for nodes, ways, m in routes:
            self.assertEqual((nodes[0], nodes[-1]), (0, 2))
            self.assertTrue(340 <= m <= 420)

    def test_sample_falls_back_to_the_plain_route_when_shakes_never_fit(self):
        with patch("corridors.sample_hop", side_effect=NoRoute("no shake fits")):
            routes = self.c.sample(0, 2, "member", metres=200, draws=4, seed=1)
        self.assertEqual(len(routes), 4)
        for nodes, ways, m in routes:
            self.assertEqual((nodes[0], nodes[-1]), (0, 2))
            self.assertAlmostEqual(m, 200)

    def test_round_trip_sample_returns_to_start(self):
        routes = self.c.sample(0, 0, "casual", metres=400, draws=8, seed=1)      # square perimeter is 400 m
        for nodes, ways, m in routes:
            self.assertEqual((nodes[0], nodes[-1]), (0, 0))
            self.assertTrue(340 <= m <= 420)

    def test_unreachable_pair_raises(self):
        with self.assertRaises(NoRoute):
            self.c.sample(0, 2, "member", metres=120, draws=8, seed=1)

    def test_round_trip_too_short_for_any_waypoint_raises_no_route(self):
        with self.assertRaises(NoRoute):                 # 50 m budget: no node is reachable and back
            self.c.sample(0, 0, "casual", metres=50, draws=8, seed=1)

    def test_in_tables_are_bounded(self):
        with patch.object(Corridors, "TABLE_CACHE", 2):
            for n in range(5):
                self.c.in_table(n, 400)
        self.assertEqual(len(self.c._in), 2)


if __name__ == "__main__":
    unittest.main()
