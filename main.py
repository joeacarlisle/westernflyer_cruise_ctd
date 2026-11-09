"""Western Flyer CTD build orchestrator.

Usage:
    python main.py <cruise_id> [--bin-size 1.0] [--xmlcon PATH]
                               [--hex-dir PATH] [--db PATH] [--verbose]

The cruise_id maps to ``cruises/<cruise_id>/`` and is the authoritative
source of truth for the cruise.  Expected layout:

    cruises/<cruise_id>/
        calibration.csv       processing parameters (CTM, bin size, etc.)
        calibration.xmlcon    sensor calibration coefficients (from SeaSoft)
        cruise_log.csv        per-cast metadata (lat, lon, station, etc.)
        hex/                  raw .hex files — one per cast

Processing pipeline (per cast):
    read_hex_file             raw A/D counts via Sea-Bird Scientific toolkit
    convert_temperature       ITS-90 °C  (use_mv_r=True for SBE 19plus V2)
    convert_pressure          dbar
    convert_conductivity      S/m
    convert_sbe43_oxygen      ml/L → µmol/L
    convert_sbe18_ph          pH
    convert_eco               µg/L CHL
    apply_soak_elimination    flag surface-soak rows
    apply_ctm_correction      cell thermal mass (Sea-Bird Scientific)
    apply_tau_shift           O2 lag alignment (Sea-Bird Scientific)
    apply_loop_edit           pressure-reversal removal (Sea-Bird Scientific)
    apply_physics             SP, theta, rho, o2_final
    apply_chl_calibration     CHL calibration + filter
    apply_wild_edit           two-pass block-statistics spike removal
    apply_qc_flags            velocity-based QC

The pipeline writes into a single DuckDB file:
    processed/wf_ctd_eos80.duckdb
        ctd_data        - one row per (station, cast, depth bin)
        build_metadata  - one row per build, with SHA-256 of .xmlcon

Per-cruise records are replaced (not appended) inside a single
transaction, so a failed insert can't leave the database empty.
"""

import argparse
import datetime as dt
import hashlib
import logging
import pathlib
import subprocess
import sys

import duckdb
import numpy as np
import pandas as pd

import cnv_ingestion
import eos80_processing
import sbe19plus_ingestion
from sbe19plus_ingestion import parse_xmlcon, ingest_sbe_hex
from seabirdscientific.processing import FLAG_VALUE, get_downcast

BASE_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "processed" / "wf_ctd_eos80.duckdb"
LOG_DIR = BASE_DIR / "logs"

# Data sources: raw instrument .hex files, or SeaSoft-processed files in
# cruises/<cruise_id>/cnv_<source>/.  'all' builds every source that has input.
SOURCES = ["raw", "downcast", "upcast", "fullcast", "all"]
SOURCE_ORDER = ("raw", "downcast", "upcast", "fullcast")


def setup_logging(cruise_id, verbose=False):
    """Sets up logging with a per-build, timestamped log file."""
    LOG_DIR.mkdir(exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"wf_build_{cruise_id}_{timestamp}.log"
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path, mode='w'),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


def file_sha256(path):
    """Returns the hex SHA-256 of a file (used for calibration provenance)."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def git_commit():
    """Returns the current git commit hash, or 'unknown' if not a repo."""
    try:
        out = subprocess.check_output(
            ['git', '-C', str(BASE_DIR), 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'unknown'


def process_one_cast(file_path, cruise_log, config, cruise_id, output_res, sensor_coefs):
    """Runs the full per-cast pipeline and returns the binned DataFrame."""
    df = ingest_sbe_hex(file_path, cruise_log=cruise_log, config=config,
                        sensor_coefs=sensor_coefs)

    df = eos80_processing.apply_soak_elimination(df, config)
    df = eos80_processing.apply_ctm_correction(df, config)
    df = eos80_processing.apply_tau_shift(df, config)
    df = eos80_processing.apply_loop_edit(df, config)
    df = eos80_processing.apply_physics(df, config)
    df = eos80_processing.apply_chl_calibration(df, config)
    df = eos80_processing.apply_wild_edit(df, config)
    df = eos80_processing.apply_qc_flags(df, config)

    df = get_downcast(df, 'pres_raw')

    # Replace Wild Edit sentinel values with NaN so they don't contaminate
    # bin averages in the groupby below.
    df = df.replace(FLAG_VALUE, np.nan)

    df['dbar_bin'] = (df['pres_raw'] / output_res).round() * output_res
    df['depth_m'] = eos80_processing.calculate_depth_eos80(
        df['dbar_bin'].to_numpy(), df['lat'].to_numpy()
    )

    agg_config = {
        'time_iso': 'min',
        'rho': 'mean', 'SP': 'mean', 'theta': 'mean',
        'o2_final': 'mean', 'ph_final': 'mean', 'chl_final': 'mean',
        'in_situ_temp': 'mean',
        'lat': 'first', 'lon': 'first',
        'qc_flag': 'max',
    }
    agg_config = {k: v for k, v in agg_config.items() if k in df.columns}

    # is_soak is a groupby key so soak and non-soak scans bin into separate
    # rows.  This prevents soak artifacts from contaminating non-soak bin
    # averages while keeping soak data in DuckDB for the dashboard toggle.
    groupby_cols = ['station_id', 'station_name', 'sb_cast', 'wf_cast', 'dbar_bin', 'depth_m']
    if 'is_soak' in df.columns:
        groupby_cols.append('is_soak')

    df_binned = (df.groupby(groupby_cols).agg(agg_config).reset_index())

    df_binned['cruise_id'] = cruise_id
    df_binned['filename'] = file_path.name
    df_binned['data_source'] = 'raw'
    df_binned['cast_direction'] = 'down'   # raw casts keep the downcast only
    return df_binned


def files_sha256(paths):
    """SHA-256 over several files (sorted by name); provenance for processed builds."""
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: x.name):
        h.update(p.name.encode())
        h.update(file_sha256(p).encode())
    return h.hexdigest()


def _columns(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()]


def migrate_schema(con):
    """Adds data_source / cast_direction to databases built before processed sources.

    Existing rows are raw downcasts, so they are labelled 'raw' / 'down'.
    """
    cols = _columns(con, 'ctd_data')
    if 'data_source' not in cols:
        con.execute("ALTER TABLE ctd_data ADD COLUMN data_source VARCHAR")
        con.execute("UPDATE ctd_data SET data_source = 'raw'")
        logging.info("Migrated ctd_data: added data_source (existing rows set to 'raw').")
    if 'cast_direction' not in cols:
        con.execute("ALTER TABLE ctd_data ADD COLUMN cast_direction VARCHAR")
        con.execute("UPDATE ctd_data SET cast_direction = 'down'")
        logging.info("Migrated ctd_data: added cast_direction (existing rows set to 'down').")
    if 'data_source' not in _columns(con, 'build_metadata'):
        con.execute("ALTER TABLE build_metadata ADD COLUMN data_source VARCHAR")
        con.execute("UPDATE build_metadata SET data_source = 'raw'")
        logging.info("Migrated build_metadata: added data_source.")


def commit_to_duckdb(full_df, cruise_id, db_path, calibration_path, build_started,
                     cal_hash=None, data_source='raw'):
    """Replaces the cruise's rows for one data source atomically and records provenance.

    Rows are replaced per (cruise_id, data_source), so building downcast
    never touches the raw rows and vice versa.  ``cal_hash`` overrides the
    hash of ``calibration_path`` (processed builds hash the input files).
    """
    db_path.parent.mkdir(exist_ok=True)
    if cal_hash is None:
        cal_hash = file_sha256(calibration_path)
    commit = git_commit()

    with duckdb.connect(str(db_path)) as con:
        con.register('df_view', full_df)
        con.execute("CREATE TABLE IF NOT EXISTS ctd_data AS SELECT * FROM df_view WHERE 1=0")
        con.execute("""
            CREATE TABLE IF NOT EXISTS build_metadata (
                cruise_id        VARCHAR,
                build_started_ts TIMESTAMP,
                build_finished_ts TIMESTAMP,
                calibration_sha256 VARCHAR,
                git_commit       VARCHAR,
                rows_written     BIGINT,
                data_source      VARCHAR
            )
        """)
        migrate_schema(con)
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("DELETE FROM ctd_data WHERE cruise_id = ? AND data_source = ?",
                        [cruise_id, data_source])
            con.execute("INSERT INTO ctd_data BY NAME SELECT * FROM df_view")
            con.execute("DELETE FROM build_metadata WHERE cruise_id = ? AND data_source = ?",
                        [cruise_id, data_source])
            con.execute(
                "INSERT INTO build_metadata (cruise_id, build_started_ts, build_finished_ts, "
                "calibration_sha256, git_commit, rows_written, data_source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [cruise_id, build_started, dt.datetime.now(), cal_hash, commit,
                 len(full_df), data_source],
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build the Western Flyer CTD DuckDB for one cruise.")
    parser.add_argument("cruise_id", help="Cruise directory name under cruises/, e.g. baja2025")
    parser.add_argument("--source", choices=SOURCES, default="raw",
                        help="Data source: raw (.hex files, default), downcast, upcast or "
                             "fullcast (SeaSoft-processed files in cruises/<id>/cnv_<source>/), "
                             "or all (every source that has input files).")
    parser.add_argument("--bin-size", type=float, default=None,
                        help="Override BIN_SIZE_METERS from config.toml (m); raw source only")
    parser.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB_PATH,
                        help=f"DuckDB output path (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--xmlcon", type=pathlib.Path, default=None,
                        help="Path to .xmlcon calibration file "
                             "(default: cruises/<cruise_id>/calibration.xmlcon); raw source only")
    parser.add_argument("--hex-dir", type=pathlib.Path, default=None,
                        help="Directory containing raw .hex files "
                             "(default: cruises/<cruise_id>/hex/)")
    parser.add_argument("--cnv-dir", type=pathlib.Path, default=None,
                        help="Directory of processed files "
                             "(default: cruises/<cruise_id>/cnv_<source>/); one source only")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable DEBUG-level logging")
    return parser.parse_args(argv)


def _source_input_dir(source, cruise_dir, args):
    if source == "raw":
        return args.hex_dir if args.hex_dir else cruise_dir / "hex"
    return args.cnv_dir if args.cnv_dir else cruise_dir / f"cnv_{source}"


def _input_files(source, directory):
    if source == "raw":
        return sorted(directory.glob("*.hex"))
    return cnv_ingestion.find_cnv_files(directory)


def build_source(source, files, args, cruise_id, cruise_dir, config, cruise_log,
                 calibration_path, build_started):
    """Processes one source's files and commits them.  Returns the failure count,
    or None if nothing could be processed (the database was not updated)."""
    output_res = float(args.bin_size if args.bin_size is not None
                       else config.get('BIN_SIZE_METERS', 1.0))
    cal_hash = None
    sensor_coefs = None
    xmlcon_path = calibration_path
    if source == "raw":
        # Resolve .xmlcon path (default: cruises/<cruise_id>/calibration.xmlcon)
        xmlcon_path = args.xmlcon if args.xmlcon else cruise_dir / 'calibration.xmlcon'
        if not xmlcon_path.exists():
            logging.error(f"Calibration .xmlcon not found: {xmlcon_path}")
            sys.exit(1)
        sensor_coefs = parse_xmlcon(xmlcon_path)
    elif files:
        cal_hash = files_sha256(files)

    processed_data = []
    failures = []
    for file_path in files:
        logging.info(f"[{source}] Processing: {file_path.name}")
        try:
            if source == "raw":
                df_binned = process_one_cast(
                    file_path, cruise_log, config, cruise_id, output_res, sensor_coefs
                )
            else:
                df_binned = cnv_ingestion.ingest_cnv(
                    file_path, cruise_log, config, cruise_id, source
                )
            processed_data.append(df_binned)
        except Exception as exc:
            logging.error(f"Failed to process {file_path.name}: {exc}")
            logging.debug("Traceback for %s", file_path.name, exc_info=True)
            failures.append((file_path.name, str(exc)))
            continue

    if not processed_data:
        logging.warning(f"[{source}] No data processed; database not updated.")
        if failures:
            logging.warning(f"All {len(failures)} casts failed:")
            for name, reason in failures:
                logging.warning(f"  {name}: {reason}")
        return None

    full_df = pd.concat(processed_data, ignore_index=True)
    logging.info(f"[{source}] Committing {len(full_df)} binned records to {args.db}")
    commit_to_duckdb(full_df, cruise_id, args.db, xmlcon_path, build_started,
                     cal_hash=cal_hash, data_source=source)

    if failures:
        logging.warning(f"[{source}] Finished with {len(failures)} failed casts:")
        for name, reason in failures:
            logging.warning(f"  {name}: {reason}")
    else:
        logging.info(f"[{source}] Finished successfully.")
    return len(failures)


def main(argv=None):
    args = parse_args(argv)
    cruise_id = args.cruise_id
    cruise_dir = BASE_DIR / "cruises" / cruise_id

    (BASE_DIR / "processed").mkdir(exist_ok=True)
    log_path = setup_logging(cruise_id, verbose=args.verbose)

    if not cruise_dir.exists():
        logging.error(f"Cruise directory '{cruise_dir}' not found.")
        sys.exit(1)

    if args.source == "all" and args.cnv_dir is not None:
        logging.error("--cnv-dir cannot be combined with --source all.")
        sys.exit(2)

    build_started = dt.datetime.now()
    logging.info(f"--- STARTING PIPELINE FOR {cruise_id.upper()} (source: {args.source}) ---")
    logging.info(f"Build log: {log_path}")

    calibration_path = cruise_dir / 'config.toml'
    config = sbe19plus_ingestion.load_config(calibration_path)
    cruise_log = sbe19plus_ingestion.load_cruise_log(cruise_dir / 'stations.csv')

    config['CRUISE_ID'] = cruise_id
    eos80_processing.validate_config(config)

    # Work out which sources to build and their input files.
    plan = []
    if args.source == "all":
        for source in SOURCE_ORDER:
            directory = _source_input_dir(source, cruise_dir, args)
            files = _input_files(source, directory) if directory.exists() else []
            if files:
                plan.append((source, files))
            else:
                logging.info(f"[{source}] No input files in {directory}; skipped.")
        if not plan:
            logging.error("--source all found no input files for any source.")
            sys.exit(1)
    else:
        source = args.source
        directory = _source_input_dir(source, cruise_dir, args)
        if not directory.exists():
            kind = "Hex" if source == "raw" else "CNV"
            logging.error(f"{kind} directory not found: {directory}")
            sys.exit(1)
        files = _input_files(source, directory)
        if not files:
            logging.warning(f"No input files found in {directory}")
        plan.append((source, files))

    results = {}
    for source, files in plan:
        results[source] = build_source(source, files, args, cruise_id, cruise_dir, config,
                                       cruise_log, calibration_path, build_started)

    # Exit code: nonzero only if a source with input produced nothing because every cast failed.
    all_failed = [s for s, r in results.items() if r is None and dict(plan)[s]]
    if all_failed:
        logging.error(f"No data written for: {', '.join(all_failed)}")
        sys.exit(1)
    logging.info("Pipeline finished.")


if __name__ == "__main__":
    main()
