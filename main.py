import sys
import pathlib
import duckdb
import pandas as pd
import logging
import sbe19plus_ingestion
import eos80_processing

# Define Data Paths
BASE_DIR = pathlib.Path(__file__).parent
DB_PATH = BASE_DIR / "processed" / "wf_ctd_eos80.duckdb"
LOG_DIR = BASE_DIR / "logs"

def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_DIR / "wf_build.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

def main():
    # Ensure necessary directories exist
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    (BASE_DIR / "processed").mkdir(exist_ok=True)

    if len(sys.argv) < 2:
        print("Usage: python main.py <cruise_id>")
        sys.exit(1)
        
    cruise_id = sys.argv[1]
    cruise_dir = BASE_DIR / "cruises" / cruise_id
    
    if not cruise_dir.exists():
        print(f"Error: Cruise directory '{cruise_dir}' not found.")
        sys.exit(1)

    setup_logging()
    logging.info(f"--- STARTING PIPELINE FOR {cruise_id.upper()} ---")
    
    # 1. Load Metadata and Config
    config = sbe19plus_ingestion.load_config_csv(cruise_dir / 'calibration.csv')
    cruise_log = sbe19plus_ingestion.load_cruise_log(cruise_dir / 'cruise_log.csv')
    
    # 2. Processing Loop
    cnv_dir = cruise_dir / 'cnv'
    files = list(cnv_dir.glob("*.cnv"))
    processed_data = []
    
    for file_path in files:
        logging.info(f"Processing: {file_path.name}")
        try:
            # A. Ingestion
            df = sbe19plus_ingestion.ingest_sbe_cnv(file_path, cruise_log=cruise_log, config=config)
            
            # B. Physics & Corrections
            df = eos80_processing.apply_soak_elimination(df, config)
            df = eos80_processing.apply_tau_shift(df, config)
            df = eos80_processing.apply_ctm_correction(df, config)
            df = eos80_processing.apply_physics(df, config)
            df = eos80_processing.apply_surgical_chl(df, config)
            df = eos80_processing.apply_qc_flags(df, config)
            
            # C. Binning & Aggregation
            OUTPUT_RES = float(config.get('BIN_SIZE_METERS', 1.0))
            df['dbar_bin'] = (df['pres_raw'] / OUTPUT_RES).round() * OUTPUT_RES
            df['depth_m'] = df.apply(lambda r: eos80_processing.calculate_depth_eos80(r['dbar_bin'], r['lat']), axis=1)
            
            agg_config = {
                'time_iso': 'min', 
                'rho': 'mean', 'SP': 'mean', 'theta': 'mean',
                'o2_final': 'mean', 'ph_final': 'mean', 'chl_final': 'mean', 
                'lat': 'first', 'lon': 'first', 'qc_flag': 'min'
            }
            
            df_binned = df.groupby(['station_id', 'station_name', 'sb_cast', 'wf_cast', 'dbar_bin', 'depth_m']).agg(agg_config).reset_index()
            
            # D. Metadata Injection
            df_binned['cruise_id'] = cruise_id
            df_binned['filename'] = file_path.name
            
            processed_data.append(df_binned)
            
        except Exception as e:
            logging.error(f"Failed to process {file_path.name}: {e}")
            continue

    # 3. Database Commit (Idempotent)
    if processed_data:
        full_df = pd.concat(processed_data, ignore_index=True)
        logging.info(f"Committing {len(full_df)} binned records to DuckDB.")
        
        with duckdb.connect(str(DB_PATH)) as con:
            con.register('df_view', full_df)
            con.execute("CREATE TABLE IF NOT EXISTS ctd_data AS SELECT * FROM df_view WHERE 1=0")
            con.execute(f"DELETE FROM ctd_data WHERE cruise_id = '{cruise_id}'")
            con.execute("INSERT INTO ctd_data SELECT * FROM df_view")
            
        logging.info("Pipeline Finished Successfully.")
    else:
        logging.warning("No data processed, database not updated.")

if __name__ == "__main__":
    main()
