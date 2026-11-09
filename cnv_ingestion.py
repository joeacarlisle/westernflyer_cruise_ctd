"""Reader for Sea-Bird SeaSoft processed files (.cnv, with .asc fallback).

A processed file has already been through SeaSoft (filter, align, cell
thermal mass, loop edit, derive, bin average), so none of the raw-pipeline
steps (soak elimination, CTM, tau shift, loop edit, wild edit) are re-run.
Each file is converted straight to the same binned DataFrame that
``main.process_one_cast`` returns for a raw .hex cast, so the same
database writer and dashboard can use it.

Sources (folder ``cruises/<cruise_id>/cnv_<source>/``)
    downcast   one profile, written with cast_direction = 'down'
    upcast     one profile, written with cast_direction = 'up'
    fullcast   down and up in one file; split at the deepest scan.  The
               deepest bin belongs to the downcast.

Column mapping (SeaSoft name prefix, case-insensitive -> pipeline column)
    prdM        -> dbar_bin   (actual pressure of the bin, dbar)
    tv290C      -> in_situ_temp
    sal00       -> SP
    sbox0Mm/Kg  -> o2_final   (umol/kg)
    ph          -> ph_final
    flECO-AFL   -> chl_final  (mg/m^3 == ug/L)
    flag        -> qc_flag    (0 -> 1 good, else 3; 1 when there is no flag)
theta and rho are recomputed with the same EOS-80 functions the raw
pipeline uses, and depth_m is computed from pressure and latitude the same
way, so raw and processed rows are directly comparable.

Fullcast .asc files (SeaSoft ASCII output) have no header block, 10 columns
and a column-name line repeated every 60 rows; they are read when no .cnv
exists for the same cast.
"""

import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

import eos80_processing
from sbe19plus_ingestion import dm_to_decimal, resolve_cast_start_utc

CNV_SOURCES = ('downcast', 'upcast', 'fullcast')

# Output columns, in the order process_one_cast produces them.
OUTPUT_COLUMNS = [
    'station_id', 'station_name', 'sb_cast', 'wf_cast', 'dbar_bin', 'depth_m',
    'is_soak', 'time_iso', 'rho', 'SP', 'theta', 'o2_final', 'ph_final',
    'chl_final', 'in_situ_temp', 'lat', 'lon', 'qc_flag', 'cruise_id',
    'filename', 'data_source', 'cast_direction',
]

# Column-name prefixes (lower case): the SeaSoft names contain punctuation
# and, for sigma-theta, a non-UTF-8 byte, so match on prefixes.
_PREFIX_TO_KEY = [
    ('prdm', 'pres'), ('tv290c', 'temp'), ('sal00', 'sal'),
    ('sbox0mm/kg', 'o2'), ('ph', 'ph'), ('fleco', 'chl'), ('flag', 'flag'),
]


def file_key_from_cnv(path):
    """'20250916_Cabrillo_cast1_filter_..._downcast.cnv' -> '20250916_Cabrillo_cast1'.

    The cast key is everything before the first SeaSoft module suffix
    ('_filter'); if that suffix is absent the whole stem is used.
    """
    return re.split(r'_filter', Path(path).stem, maxsplit=1)[0]


def find_cnv_files(directory):
    """Returns the .cnv files in a folder, plus .asc files for casts with no .cnv."""
    directory = Path(directory)
    cnv = sorted(directory.glob('*.cnv'))
    have = {file_key_from_cnv(p) for p in cnv}
    asc = [p for p in sorted(directory.glob('*.asc')) if file_key_from_cnv(p) not in have]
    return sorted(cnv + asc, key=lambda p: p.name)


def _read_cnv(path):
    """Returns (DataFrame with SeaSoft column names, header start-time string)."""
    names, nvalues, start, bad_flag, n_hdr = {}, None, None, None, None
    with open(path, encoding='latin-1') as f:
        for i, line in enumerate(f):
            m = re.match(r'#\s*name\s+(\d+)\s*=\s*([^:]+):', line)
            if m:
                names[int(m.group(1))] = m.group(2).strip()
                continue
            m = re.match(r'#\s*nvalues\s*=\s*(\d+)', line)
            if m:
                nvalues = int(m.group(1))
                continue
            m = re.match(r'#\s*start_time\s*=\s*(.+?)\s*\[', line)
            if m:
                start = m.group(1).strip()
                continue
            m = re.match(r'#\s*bad_flag\s*=\s*(\S+)', line)
            if m:
                bad_flag = float(m.group(1))
                continue
            if line.startswith('*END*'):
                n_hdr = i + 1
                break
    if n_hdr is None:
        raise ValueError(f"{Path(path).name}: no *END* header terminator.")
    if not names:
        raise ValueError(f"{Path(path).name}: no '# name N =' lines in header.")
    cols = [names[i] for i in sorted(names)]
    raw = pd.read_csv(path, skiprows=n_hdr, sep=r'\s+', header=None, names=cols,
                      encoding='latin-1', engine='python')
    if nvalues is not None and len(raw) != nvalues:
        logging.warning("%s: header nvalues=%d but read %d rows.",
                        Path(path).name, nvalues, len(raw))
    if bad_flag is not None:
        raw = raw.mask(np.isclose(raw, bad_flag, rtol=1e-3))
    return raw, start


def _read_asc(path):
    """Reads a SeaSoft ASCII export: column-name line repeated every N rows."""
    cols, rows = None, []
    with open(path, encoding='latin-1') as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            try:
                vals = [float(p) for p in parts]
            except ValueError:
                if cols is None:
                    cols = parts
                continue
            rows.append(vals)
    if cols is None:
        raise ValueError(f"{Path(path).name}: no column-name line found.")
    raw = pd.DataFrame(rows, columns=cols)
    return raw, None   # .asc carries no start time


def _find_col(cols, prefix):
    low = [c.lower() for c in cols]
    for i, c in enumerate(low):
        if c == prefix:
            return i
    for i, c in enumerate(low):
        if c.startswith(prefix):
            return i
    return None


def ingest_cnv(file_path, cruise_log, config, cruise_id, source):
    """Reads one processed cast file and returns the binned pipeline DataFrame.

    For source 'fullcast' the result holds both directions (cast_direction
    'down' then 'up'); otherwise every row has the source's direction.
    """
    if source not in CNV_SOURCES:
        raise ValueError(f"Unknown processed source '{source}'")
    file_path = Path(file_path)
    if file_path.suffix.lower() == '.asc':
        raw, header_start = _read_asc(file_path)
    else:
        raw, header_start = _read_cnv(file_path)
    cols = list(raw.columns)

    idx = {key: _find_col(cols, pref) for pref, key in _PREFIX_TO_KEY}
    for key in ('pres', 'temp', 'sal'):
        if idx[key] is None:
            raise ValueError(f"{file_path.name}: required column '{key}' not found in {cols}")

    def col(key):
        i = idx[key]
        return raw.iloc[:, i].to_numpy(dtype=float) if i is not None \
            else np.full(len(raw), np.nan)

    pres, temp, sal = col('pres'), col('temp'), col('sal')
    if len(raw) == 0:
        raise ValueError(f"{file_path.name}: no data rows.")

    # --- station metadata (same lookup the raw path uses) ---
    key = file_key_from_cnv(file_path)
    meta = cruise_log.get(key)
    if meta is None:
        raise ValueError(
            f"{file_path.name}: file key '{key}' not found in stations.csv "
            f"(file_key must equal the text before '_filter').")
    lat = dm_to_decimal(meta.get('lat'))
    lon = dm_to_decimal(meta.get('lon'))
    if lat is None or lon is None:
        raise ValueError(f"{file_path.name}: no lat/lon in stations.csv for '{key}'.")

    station_name = meta.get('station_name', 'Unknown')
    sb_cast = meta.get('sb_cast', 0)
    wf_cast = meta.get('wf_cast', 0)

    header_ts = pd.NaT
    if header_start:
        header_ts = pd.to_datetime(header_start, format='%b %d %Y %H:%M:%S',
                                   errors='coerce')
    start = resolve_cast_start_utc(header_ts, meta, config, file_path.name)

    # --- derived physics, same EOS-80 functions as the raw path ---
    t68 = temp * float(config.get('T68_CONVERSION', 1.00024))
    theta = eos80_processing.calculate_theta_eos80(sal, t68, pres)
    rho = eos80_processing.calculate_density_eos80(sal, t68, pres)
    depth = eos80_processing.calculate_depth_eos80(pres, lat)

    if idx['flag'] is not None:
        qc = np.where(np.nan_to_num(col('flag'), nan=0.0) == 0, 1, 3)
    else:
        qc = np.ones(len(raw), dtype=int)

    n = len(raw)
    if source == 'fullcast':
        turn = int(np.nanargmax(pres))
        direction = np.where(np.arange(n) <= turn, 'down', 'up')
    else:
        direction = np.full(n, 'down' if source == 'downcast' else 'up')

    df = pd.DataFrame({
        'station_id': f"{station_name}_Cast{wf_cast}",
        'station_name': station_name,
        'sb_cast': sb_cast,
        'wf_cast': wf_cast,
        'dbar_bin': pres,
        'depth_m': depth,
        # A processed cast has no soak: SeaSoft already removed it.
        'is_soak': np.zeros(n, dtype=bool),
        # Processed files carry no per-scan time: every bin gets the cast start.
        'time_iso': start,
        'rho': rho,
        'SP': sal,
        'theta': theta,
        'o2_final': col('o2'),
        'ph_final': col('ph'),
        'chl_final': col('chl'),
        'in_situ_temp': temp,
        'lat': lat,
        'lon': lon,
        'qc_flag': qc,
        'cruise_id': cruise_id,
        'filename': file_path.name,
        'data_source': source,
        'cast_direction': direction,
    })[OUTPUT_COLUMNS]

    logging.info("Ingested %s: %d bins (%s), P %.1f-%.1f dbar, start %s UTC",
                 file_path.name, n, source, np.nanmin(pres), np.nanmax(pres), start)
    return df
