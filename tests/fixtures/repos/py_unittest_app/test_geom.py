"""Tests for geom."""

import unittest

from geom import clamp


class TestClamp(unittest.TestCase):
    def test_clamp_inside_range(self):
        self.assertEqual(clamp(5, 0, 10), 5)

    def test_clamp_below_range(self):
        self.assertEqual(clamp(-3, 0, 10), 0)


if __name__ == "__main__":
    unittest.main()
