"""Compare two data sources for one cruise (for example raw vs downcast).

Usage:  python compare_sources.py <cruise_id> [--a raw] [--b downcast] [--db PATH]

For every station present in both sources the profiles are averaged into
1 m pressure bins and compared.  Printed per station: the mean difference
(a - b) and the largest absolute difference for each variable.  Use it to
see how far the raw .hex pipeline is from SeaSoft's processed output; the
usual causes of a gap are calibration coefficients (xmlcon vs the SeaSoft
sensor block) and processing options.
"""
import argparse
import pathlib
import sys

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "processed" / "wf_ctd_eos80.duckdb"
VARS = ['SP', 'theta', 'in_situ_temp', 'o2_final', 'ph_final', 'chl_final']


def load(con, cruise, source, direction='down'):
    return con.execute(
        "SELECT * FROM ctd_data WHERE cruise_id = ? AND data_source = ? "
        "AND cast_direction = ? AND NOT is_soak", [cruise, source, direction]).df()


def compare(a, b):
    """Per-station difference table between two long-format frames."""
    rows = []
    for sid in sorted(set(a['station_id']) & set(b['station_id'])):
        x = a[a.station_id == sid].assign(k=lambda d: d.dbar_bin.round()).groupby('k')[VARS].mean()
        y = b[b.station_id == sid].assign(k=lambda d: d.dbar_bin.round()).groupby('k')[VARS].mean()
        both = x.join(y, lsuffix='_a', rsuffix='_b', how='inner')
        row = {'station_id': sid, 'bins': len(both)}
        for v in VARS:
            d = both[v + '_a'] - both[v + '_b']
            row[v + ' mean'] = round(float(d.mean()), 4) if len(d) else np.nan
            row[v + ' max'] = round(float(d.abs().max()), 4) if len(d) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('cruise_id')
    p.add_argument('--a', default='raw')
    p.add_argument('--b', default='downcast')
    p.add_argument('--db', type=pathlib.Path, default=DEFAULT_DB)
    args = p.parse_args(argv)
    direction_b = 'up' if args.b == 'upcast' else 'down'
    with duckdb.connect(str(args.db), read_only=True) as con:
        a = load(con, args.cruise_id, args.a)
        b = load(con, args.cruise_id, args.b, direction_b)
    if a.empty or b.empty:
        print(f"No rows for {args.a} ({len(a)}) or {args.b} ({len(b)}) in {args.cruise_id}.")
        sys.exit(1)
    out = compare(a, b)
    if out.empty:
        print("The two sources share no station_id.")
        sys.exit(1)
    pd.set_option('display.width', 250, 'display.max_columns', 40)
    print(f"{args.cruise_id}: {args.a} minus {args.b}")
    print(out.to_string(index=False))


if __name__ == '__main__':
    main()
