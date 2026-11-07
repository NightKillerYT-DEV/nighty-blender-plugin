# SPDX-License-Identifier: GPL-3.0-or-later
import unittest

import _load  # noqa: F401

_load.io()

from nighty_io import looks  # noqa: E402


class Looks(unittest.TestCase):
    def test_metal_only_where_the_color_can_be_metal(self):
        self.assertFalse(looks.metal_ok((0.4, 0.22, 0.1), 1.0), "wood is never metal")
        self.assertFalse(looks.metal_ok((0.1, 0.2, 0.8), 1.0), "strong blue is paint")
        self.assertTrue(looks.metal_ok((0.7, 0.7, 0.72), 0.9))
        self.assertTrue(looks.metal_ok((0.78, 0.62, 0.3), 0.8), "brass")
        self.assertFalse(looks.metal_ok((0.7, 0.7, 0.72), 0.2), "the AI said not metal")

    def test_pick_material(self):
        self.assertEqual(looks.pick_material((0.4, 0.22, 0.1), False)[0], "wood")
        self.assertEqual(looks.pick_material((0.7, 0.58, 0.3), True)[0], "brass")
        self.assertEqual(looks.pick_material((0.4, 0.22, 0.1), False, ["wood", "brass"])[0], "wood")
        self.assertEqual(looks.pick_material((0.62, 0.5, 0.3), True, ["brass", "wood"])[0], "brass")
        name, paint, _ = looks.pick_material((0.9, 0.9, 0.9), False, ["plastic", "steel"])
        self.assertEqual((name, paint), ("plastic", "#e6e6e6"))
        self.assertEqual(looks.rgb_hex(looks.hex_rgb("#b8964f")), "#b8964f")


if __name__ == "__main__":
    unittest.main()
