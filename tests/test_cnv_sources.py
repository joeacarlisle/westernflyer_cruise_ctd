"""Tests for processed-source ingestion, start-time handling and DB writes.

Run from the project root:   python -m unittest discover -s tests -v
Uses small synthetic files only, so no cruise data is needed.
"""
import datetime as dt
import logging
import pathlib
import sys
import tempfile
import unittest

import duckdb
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cnv_ingestion      # noqa: E402
import main as ctd_main   # noqa: E402
from sbe19plus_ingestion import resolve_cast_start_utc  # noqa: E402

HEADER = """* Sea-Bird SBE19plus  Data File:
# nquan = 12
# nvalues = {n}
# name 0 = prdM: Pressure, Strain Gauge [db]
# name 1 = tv290C: Temperature [ITS-90, deg C]
# name 2 = c0uS/cm: Conductivity [uS/cm]
# name 3 = sbeox0V: Oxygen raw, SBE 43 [V]
# name 4 = flECO-AFL: Fluorescence [mg/m^3]
# name 5 = ph: pH
# name 6 = depSM: Depth [salt water, m], lat = 36.8
# name 7 = sal00: Salinity, Practical [PSU]
# name 8 = sbox0Mm/Kg: Oxygen, SBE 43 [umol/kg], WS = 2
# name 9 = sbeox0ML/L: Oxygen, SBE 43 [ml/l], WS = 2
# name 10 = sigma-\xe9 00: Density [sigma-theta, kg/m^3]
# name 11 = flag: flag
# start_time = Sep 16 2025 08:47:10 [Instrument's time stamp, header]
# bad_flag = -9.990e-29
*END*
"""
PRESSURES = [1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0, 1.0]   # down to 5 dbar, then up

CRUISE_LOG = {'cast1': {'lat': '36-47.82N', 'lon': '121-50.82W', 'station_name': 'Cab',
                        'sb_cast': 56, 'wf_cast': 11, 'start_utc': '2025-09-16 15:47:00'}}


def write_cnv(path, pressures):
    lines = [HEADER.format(n=len(pressures))]
    for p in pressures:
        lines.append(f"{p:10.3f} {10.0 - p * 0.1:10.4f} 4.0e+04 1.0 0.5 8.0 {p:9.3f} "
                     f"{33.5 + p * 0.01:9.4f} {200 - p:9.3f} 5.0 24.5 0.0e+00\n")
    pathlib.Path(path).write_bytes(''.join(lines).encode('latin-1'))


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.cfg = {}

    def test_file_key(self):
        self.assertEqual(cnv_ingestion.file_key_from_cnv('a/20250916_Cab_cast1_filter_align_downcast.cnv'),
                         '20250916_Cab_cast1')
        self.assertEqual(cnv_ingestion.file_key_from_cnv('plain.cnv'), 'plain')

    def test_downcast_and_upcast_direction(self):
        f = self.tmp / 'cast1_filter_x_downcast.cnv'
        write_cnv(f, PRESSURES[:5])
        df = cnv_ingestion.ingest_cnv(f, CRUISE_LOG, self.cfg, 'C', 'downcast')
        self.assertEqual(list(df.columns), cnv_ingestion.OUTPUT_COLUMNS)
        self.assertEqual(set(df.cast_direction), {'down'})
        self.assertEqual(set(df.data_source), {'downcast'})
        df = cnv_ingestion.ingest_cnv(f, CRUISE_LOG, self.cfg, 'C', 'upcast')
        self.assertEqual(set(df.cast_direction), {'up'})

    def test_fullcast_split_at_deepest(self):
        f = self.tmp / 'cast1_filter_x_fullcast.cnv'
        write_cnv(f, PRESSURES)
        df = cnv_ingestion.ingest_cnv(f, CRUISE_LOG, self.cfg, 'C', 'fullcast')
        down, up = df[df.cast_direction == 'down'], df[df.cast_direction == 'up']
        self.assertEqual(len(down), 5)          # 1..5, deepest bin is the downcast
        self.assertEqual(len(up), 4)
        self.assertEqual(down.dbar_bin.max(), 5.0)

    def test_asc_fallback_with_repeated_header(self):
        asc = self.tmp / 'cast1_filter_x_fullcast_ASCII.asc'
        hdr = "   PrdM  Tv290C C0uS/cm Sbeox0V FlECO-AFL Ph DepSM Sal00 Sbox0Mm/Kg Sbeox0ML/L\n"
        body = [f"{p} 10 4e4 1 0.5 8.0 {p} 33.5 200 5\n" for p in PRESSURES]
        asc.write_text(hdr + ''.join(body[:4]) + hdr + ''.join(body[4:]))
        df = cnv_ingestion.ingest_cnv(asc, CRUISE_LOG, self.cfg, 'C', 'fullcast')
        self.assertEqual(len(df), len(PRESSURES))
        self.assertTrue((df.qc_flag == 1).all())   # no flag column
        # a .cnv for the same cast wins over the .asc
        write_cnv(self.tmp / 'cast1_filter_x_fullcast.cnv', PRESSURES)
        names = [p.name for p in cnv_ingestion.find_cnv_files(self.tmp)]
        self.assertEqual(names, ['cast1_filter_x_fullcast.cnv'])

    def test_unknown_station_raises(self):
        f = self.tmp / 'nope_filter_x.cnv'
        write_cnv(f, PRESSURES[:5])
        with self.assertRaises(ValueError):
            cnv_ingestion.ingest_cnv(f, CRUISE_LOG, self.cfg, 'C', 'downcast')


class StartTimeTests(unittest.TestCase):
    hdr = pd.Timestamp('2025-09-16 08:47:10')

    def test_pacific_header_to_utc(self):
        got = resolve_cast_start_utc(self.hdr, CRUISE_LOG['cast1'], {}, 'f')
        self.assertEqual(got, pd.Timestamp('2025-09-16 15:47:10'))

    def test_utc_override(self):
        got = resolve_cast_start_utc(self.hdr, None, {'INSTRUMENT_TZ': 'UTC'}, 'f')
        self.assertEqual(got, self.hdr)

    def test_fallback_to_stations_csv(self):
        got = resolve_cast_start_utc(pd.NaT, CRUISE_LOG['cast1'], {}, 'f')
        self.assertEqual(got, pd.Timestamp('2025-09-16 15:47:00'))

    def test_mismatch_warns_and_uses_header(self):
        bad = dict(CRUISE_LOG['cast1'], start_utc='2025-09-17 00:55:00')
        with self.assertLogs(level=logging.WARNING) as cm:
            got = resolve_cast_start_utc(self.hdr, bad, {}, 'f')
        self.assertEqual(got, pd.Timestamp('2025-09-16 15:47:10'))
        self.assertTrue(any('differs' in m for m in cm.output))


class DatabaseTests(unittest.TestCase):
    def frame(self, source, direction, cruise='C', n=3):
        return pd.DataFrame({
            'station_id': 'S_Cast1', 'dbar_bin': [float(i) for i in range(n)],
            'cruise_id': cruise, 'is_soak': False, 'qc_flag': 1,
            'data_source': source, 'cast_direction': direction})

    def test_replace_is_per_source(self):
        db = pathlib.Path(tempfile.mkdtemp()) / 't.duckdb'
        cal = db.parent / 'cal.txt'
        cal.write_text('x')
        start = dt.datetime.now()
        ctd_main.commit_to_duckdb(self.frame('raw', 'down', n=3), 'C', db, cal, start, data_source='raw')
        ctd_main.commit_to_duckdb(self.frame('downcast', 'down', n=2), 'C', db, cal, start, data_source='downcast')
        ctd_main.commit_to_duckdb(self.frame('downcast', 'down', n=4), 'C', db, cal, start, data_source='downcast')
        with duckdb.connect(str(db), read_only=True) as con:
            got = dict(con.execute("SELECT data_source, count(*) FROM ctd_data GROUP BY 1").fetchall())
            meta = dict(con.execute("SELECT data_source, rows_written FROM build_metadata").fetchall())
        self.assertEqual(got, {'raw': 3, 'downcast': 4})
        self.assertEqual(meta, {'raw': 3, 'downcast': 4})

    def test_migration_of_legacy_database(self):
        db = pathlib.Path(tempfile.mkdtemp()) / 'old.duckdb'
        with duckdb.connect(str(db)) as con:
            con.execute("CREATE TABLE ctd_data (station_id VARCHAR, dbar_bin DOUBLE, cruise_id VARCHAR, "
                        "is_soak BOOLEAN, qc_flag INTEGER)")
            con.execute("INSERT INTO ctd_data VALUES ('S_Cast1', 1.0, 'C', false, 1)")
            con.execute("CREATE TABLE build_metadata (cruise_id VARCHAR, build_started_ts TIMESTAMP, "
                        "build_finished_ts TIMESTAMP, calibration_sha256 VARCHAR, git_commit VARCHAR, "
                        "rows_written BIGINT)")
            ctd_main.migrate_schema(con)
            row = con.execute("SELECT data_source, cast_direction FROM ctd_data").fetchall()
            cols = [r[1] for r in con.execute("PRAGMA table_info('build_metadata')").fetchall()]
        self.assertEqual(row, [('raw', 'down')])
        self.assertIn('data_source', cols)


if __name__ == '__main__':
    unittest.main()
