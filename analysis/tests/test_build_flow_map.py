import unittest

from build_flow_map import render
from flows import SLICES


def data(**over):
    d = {"month": "2026-07", "slices": SLICES, "slice_trips": [1] * 24, "trips": 10, "routed": 10,
         "unrouted_groups": 0, "settings": "abc", "stations": [{"name": "Bute & Barclay", "ll": [49.2849, -123.1287]}],
         "segments": [{"ll": [[49.28, -123.12], [49.281, -123.121]], "name": "Haro Street",
                       "kind": "local street", "n": {"0": 1.5}}]}
    d.update(over)
    return d


class RenderTests(unittest.TestCase):
    def test_render_embeds_the_data_and_controls(self):
        html = render(data())
        self.assertIn("July 2026", html)
        for word in ("member", "casual", "weekday", "weekend", "07:00-10:00", "Haro Street", "Bute & Barclay"):
            self.assertIn(word, html)

    def test_render_keeps_a_script_tag_in_a_name_from_closing_the_data_block(self):
        html = render(data(stations=[{"name": "x</script><b>y", "ll": [49.28, -123.12]}]))
        self.assertNotIn("</script><b>y", html)
        self.assertIn("<\\/script>", html)

    def test_render_guards_the_max_before_dividing(self):
        self.assertIn("Math.max(1e-9", render(data()))


if __name__ == "__main__":
    unittest.main()
