import json
import unittest

from build_trip_types import render

DATA = {
    "trips": 10, "excluded": {"no odometer": 1}, "k": 2, "features": ["log_m"], "means": [1.0], "sds": [1.0],
    "centroids": [[1.0], [2.0]], "selection": [{"k": 2, "silhouette": 0.3, "inertia": 1.0}],
    "clusters": [{"n": 7, "share": 0.7, "median": {"distance_m": 2000, "duration_s": 600, "speed_kmh": 12, "directness": 0.8},
                  "mean": {"scenic_dep": 0.1, "scenic_ret": 0.1, "directness": 0.8}, "round_share": 0.0, "weekend_share": 0.2,
                  "ebike_share": 0.3, "casual_share": 0.1, "leisure_share": 0.0, "leisure_points": 1.0,
                  "hours": [0] * 24, "months": {"2026-07": 7}, "top_dep": [{"id": "A", "name": "Office </script>", "n": 7}], "top_ret": []},
                 {"n": 3, "share": 0.3, "median": {"distance_m": 9000, "duration_s": 3600, "speed_kmh": 9, "directness": 0.0},
                  "mean": {"scenic_dep": 1.0, "scenic_ret": 1.0, "directness": 0.0}, "round_share": 1.0, "weekend_share": 0.9,
                  "ebike_share": 0.3, "casual_share": 0.9, "leisure_share": 1.0, "leisure_points": 7.0,
                  "hours": [0] * 24, "months": {"2026-07": 3}, "top_dep": [{"id": "B", "name": "Park", "n": 3}], "top_ret": []}],
    "overall": {"n": 10, "hours": [0] * 24, "months": {"2026-07": 10}},
    "hist2d": [[[0] * 15 for _ in range(20)] for _ in range(2)], "stations": {},
}


class RenderTests(unittest.TestCase):
    def test_page_embeds_the_data_with_script_closers_escaped(self):
        page = render(DATA)
        self.assertIn("<title>Mobi trip types</title>", page)
        self.assertNotIn("Office </script>", page)
        self.assertIn("Office <\\/script>", page)
        start = page.index("const DATA = ") + len("const DATA = ")
        end = page.index(";\n", start)
        self.assertEqual(json.loads(page[start:end].replace("<\\/", "</")), DATA)

    def test_two_clusters_get_their_names_and_other_ks_fall_back_to_numbers(self):
        self.assertIn('"Getting there"', render(DATA))
        self.assertIn('"Out for a ride"', render(DATA))
        self.assertIn('const NAMES = ', render({**DATA, "k": 3}))

    def test_page_has_one_section_per_chart(self):
        page = render(DATA)
        for section in ("hours", "months", "directness", "selection", "composition"):
            self.assertIn(f'id="{section}"', page)


if __name__ == "__main__":
    unittest.main()
