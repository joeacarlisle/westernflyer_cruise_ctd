"""Weighted-average gridding for vertical sections (ODV-style).

Every grid value is a weighted average of the nearby measurements,

    value = sum(w_i * z_i) / sum(w_i),   w_i = exp(-r_i**2),
    r_i**2 = (dx_i / Lx)**2 + (dy_i / Ly)**2

where dx, dy are the horizontal and vertical distances to measurement i and
Lx, Ly are the scale lengths.  Measurements farther than a few scale lengths
count for nothing, and grid cells with no data nearby are left blank
(``blank_beyond``, in scale lengths), like the quality limit in Ocean Data
View.

Speed: the weight is a product of an x term and a y term, so the average over
all measurements is computed with two small matrix products instead of
comparing every cell with every measurement.  Measurements are first averaged
into the rows of the output grid (one value per station and grid row), so the
cost no longer depends on how many raw rows there are.
"""
import numpy as np


def effective_horizontal_scale(station_x, x_range, pct, min_spacing_factor=0.8):
    """Horizontal scale length Lx: ``pct`` percent of the x range, but never narrower than
    ``min_spacing_factor`` times the typical spacing between neighbouring stations, so that
    cells between neighbouring stations are never left blank."""
    lx = max(float(x_range) * float(pct) / 100.0, 1e-9)
    xs = np.unique(np.asarray(station_x, dtype=float))
    if len(xs) > 1:
        gaps = np.diff(xs)
        gaps = gaps[gaps > 0]
        if len(gaps):
            lx = max(lx, min_spacing_factor * float(np.median(gaps)))
    return lx


def weighted_average_grid(station_x, row_station, row_y, row_z, xi, yi, lx, ly,
                          blank_beyond=2.0):
    """Grid scattered section data by weighted averaging.

    Parameters
    ----------
    station_x   : (ns,) x position of each station.
    row_station : (n,) station index (0..ns-1) of each measurement.
    row_y       : (n,) depth of each measurement.
    row_z       : (n,) value; NaN rows are ignored.
    xi, yi      : 1-D output grid coordinates (yi regularly spaced).
    lx, ly      : scale lengths, in the units of x and y.
    blank_beyond: cells whose summed weight is below exp(-blank_beyond**2)
                  (roughly: no data within that many scale lengths) are NaN.

    Returns an array of shape (len(yi), len(xi)).
    """
    station_x = np.asarray(station_x, dtype=float)
    row_station = np.asarray(row_station, dtype=int)
    row_y = np.asarray(row_y, dtype=float)
    row_z = np.asarray(row_z, dtype=float)
    xi = np.asarray(xi, dtype=float)
    yi = np.asarray(yi, dtype=float)
    ns, ny = len(station_x), len(yi)
    if ny < 2:
        raise ValueError("yi needs at least two levels")
    dy = (yi[-1] - yi[0]) / (ny - 1)

    # One averaged value per (station, grid row).
    iy = np.rint((row_y - yi[0]) / dy).astype(int)
    ok = np.isfinite(row_z) & np.isfinite(row_y) & (iy >= 0) & (iy < ny) \
        & (row_station >= 0) & (row_station < ns)
    flat = row_station[ok] * ny + iy[ok]
    sums = np.bincount(flat, weights=row_z[ok], minlength=ns * ny).reshape(ns, ny)
    cnt = np.bincount(flat, minlength=ns * ny).reshape(ns, ny)
    has = cnt > 0
    mean = np.divide(sums, cnt, out=np.zeros_like(sums), where=has)
    valid = has.astype(float)

    wx = np.exp(-((xi[:, None] - station_x[None, :]) / lx) ** 2)      # (nx, ns)
    wy = np.exp(-((yi[:, None] - yi[None, :]) / ly) ** 2)             # (ny_out, ny_data)
    num = wx @ (mean * valid) @ wy.T                                  # (nx, ny_out)
    den = wx @ valid @ wy.T
    with np.errstate(invalid='ignore', divide='ignore'):
        out = num / den
    out[den < np.exp(-float(blank_beyond) ** 2)] = np.nan
    return out.T
