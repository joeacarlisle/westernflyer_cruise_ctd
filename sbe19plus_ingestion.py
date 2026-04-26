_version__ = "1.0.0"

import pandas as pd
import re
import logging
from pathlib import Path

def dm_to_decimal(dm_str):
    """Converts DD-MM.MM compass format to decimal degrees."""
    try:
        if isinstance(dm_str, (int, float)): return float(dm_str)
        match = re.match(r"(\d+)-(\d+\.\d+)([NSEW])", str(dm_str).strip())
        if not match: return None
        deg, mins, direction = match.groups()
        decimal = float(deg) + (float(mins) / 60)
        if direction in ['S', 'W']: decimal *= -1
        return decimal
    except: return None

def load_config_csv(file_path):
    """Loads calibration offsets and constants from CSV."""
    logging.info(f"Loading configuration: {file_path}")
    # Retaining the comment='#' fix for your CSV category headers
    return pd.read_csv(file_path, index_col=0, comment='#').to_dict()['value']

def load_cruise_log(file_path):
    """Loads cruise metadata CSV."""
    logging.info(f"Loading cruise log: {file_path}")
    df = pd.read_csv(file_path)
    return df.set_index('file_key').to_dict('index')

def ingest_sbe_cnv(file_path, cruise_log, config):
    """Parses SBE .cnv header and data with full metadata and time-sync."""
    try:
        file_stem = file_path.stem
        
        # 1. Define Defaults for safety
        default_meta = {
            'lat': 24.5, 'lon': -110.2, 'station_name': "Unknown", 
            'sb_cast': 0, 'wf_cast': 0, 'start_utc': "2025-01-01 00:00:00"
        }
        meta = cruise_log.get(file_stem, default_meta)
        
        columns = []
        data_start_line = 0
        header_start_time = None
        
        # 2. Parse Header
        with open(file_path, 'r', errors='ignore') as f:
            lines = f.readlines()
            
        for idx, line in enumerate(lines):
            # Capture start time for ISO timestamp calculation
            if "# start_time =" in line:
                ts_str = line.split('=')[-1].split('[')[0].strip()
                header_start_time = pd.to_datetime(ts_str, errors='coerce')
            
            # Label Mapping
            if line.startswith("# name"):
                label = line.split('=')[1].split(':')[0].strip()
                if re.search(r'tv290C', label, re.I): columns.append('temp_raw')
                elif re.search(r'c0S/m', label, re.I): columns.append('cond_raw')
                elif re.search(r'prdM', label, re.I): columns.append('pres_raw')
                elif re.search(r'sbeox0Mm/L', label, re.I): columns.append('o2_umol_l')
                elif re.search(r'flECO-AFL', label, re.I): columns.append('chl_raw')
                elif re.search(r'ph', label, re.I): columns.append('ph_raw')
                elif re.search(r'sal00', label, re.I): columns.append('sal_raw')
                elif re.search(r'timeS', label, re.I): columns.append('time_elapsed')
                else: columns.append(label)
            
            if "*END*" in line:
                data_start_line = idx + 1
                break
        
        # 3. Parse Data
        df = pd.read_csv(file_path, skiprows=data_start_line, sep=r'\s+', names=columns, engine='python')
        
        # 4. Apply Metadata (with conversion)
        df['lat'] = dm_to_decimal(meta.get('lat', default_meta['lat']))
        df['lon'] = dm_to_decimal(meta.get('lon', default_meta['lon']))
        df['station_name'] = meta.get('station_name', 'Unknown')
        df['sb_cast'], df['wf_cast'] = meta.get('sb_cast', 0), meta.get('wf_cast', 0)
        df['station_id'] = f"{df['station_name'].iloc[0]}_Cast{df['wf_cast'].iloc[0]}"
        df['cruise_id'] = config['CRUISE_ID']
        
        # 5. Generate ISO Timestamp (with fallback)
        anchor = header_start_time if pd.notnull(header_start_time) else pd.to_datetime(meta.get('start_utc', default_meta['start_utc']))
        df['time_iso'] = anchor + pd.to_timedelta(df['time_elapsed'], unit='s')
        
        logging.info(f"Successfully ingested: {file_path.name}")
        return df
        
    except Exception as e:
        logging.error(f"Failed to ingest {file_path.name}: {e}")
        return None
