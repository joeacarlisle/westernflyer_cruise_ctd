"""Tests for the ODV-style weighted-average section gridding (numpy only).

Run from the project root:   python -m unittest discover -s tests -v
"""
import pathlib
import sys
import unittest

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import section_grid as sg  # noqa: E402


def make_profiles(station_x, depths, func):
    sx, st, y, z = [], [], [], []
    for i, x in enumerate(station_x):
        for d in depths:
            st.append(i)
            y.append(d)
            z.append(func(x, d))
    return np.array(st), np.array(y, float), np.array(z, float)


class WeightedAverageTests(unittest.TestCase):
    def setUp(self):
        self.sx = np.array([0.0, 10.0, 20.0, 30.0])
        self.depths = np.arange(0.0, 101.0, 5.0)
        self.xi = np.linspace(0, 30, 61)
        self.yi = np.linspace(0, 100, 21)

    def test_constant_field_is_reproduced(self):
        st, y, z = make_profiles(self.sx, self.depths, lambda x, d: 7.5)
        g = sg.weighted_average_grid(self.sx, st, y, z, self.xi, self.yi, 6.0, 12.0)
        self.assertEqual(g.shape, (len(self.yi), len(self.xi)))
        self.assertTrue(np.allclose(g[np.isfinite(g)], 7.5))
        self.assertTrue(np.isfinite(g).all())          # data everywhere -> nothing blanked

    def test_matches_brute_force_gaussian_average(self):
        rng = np.random.default_rng(1)
        st, y, z = make_profiles(self.sx, self.depths, lambda x, d: rng.normal())
        lx, ly = 8.0, 15.0
        g = sg.weighted_average_grid(self.sx, st, y, z, self.xi, self.yi, lx, ly, blank_beyond=99)
        px = self.sx[st]
        for iy, ix in [(3, 10), (10, 30), (18, 55)]:
            w = np.exp(-(((self.xi[ix] - px) / lx) ** 2 + ((self.yi[iy] - y) / ly) ** 2))
            self.assertAlmostEqual(g[iy, ix], (w * z).sum() / w.sum(), places=9)

    def test_far_cells_are_blank(self):
        st, y, z = make_profiles(np.array([0.0, 1.0]), self.depths, lambda x, d: 1.0)
        xi = np.linspace(0, 50, 51)
        g = sg.weighted_average_grid(np.array([0.0, 1.0]), st, y, z, xi, self.yi, 2.0, 20.0)
        self.assertTrue(np.isfinite(g[:, 0]).all())
        self.assertTrue(np.isnan(g[:, -1]).all())       # 49 units away = 24 scale lengths

    def test_nan_values_and_missing_depths_are_ignored(self):
        st, y, z = make_profiles(self.sx, self.depths, lambda x, d: 3.0)
        z[::7] = np.nan
        keep = y < 60                                    # no data below 60
        g = sg.weighted_average_grid(self.sx, st[keep], y[keep], z[keep], self.xi, self.yi, 6.0, 8.0)
        self.assertTrue(np.allclose(g[np.isfinite(g)], 3.0))
        self.assertTrue(np.isnan(g[-1, :]).all())        # 100 m: far below the data

    def test_horizontal_scale_never_narrower_than_station_spacing(self):
        lx = sg.effective_horizontal_scale([0, 10, 20, 30], x_range=30, pct=1)
        self.assertAlmostEqual(lx, 8.0)                  # 0.8 * median spacing 10
        lx = sg.effective_horizontal_scale([0, 10, 20, 30], x_range=30, pct=50)
        self.assertAlmostEqual(lx, 15.0)                 # the slider wins when larger


if __name__ == '__main__':
    unittest.main()
