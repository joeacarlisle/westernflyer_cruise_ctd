# Project Components and Architecture

This document describes the functional components that comprise the Western Flyer CTD processing pipeline and provides guidelines for AI agents interacting with this repository.

## Functional Components

The codebase is organized into modular components, each responsible for a distinct stage of the data lifecycle.

### 1. Ingestion Component (`sbe19plus_ingestion.py`)
**Role:** Raw Data Interface & Calibration
- **Responsibilities:**
    - Parses Sea-Bird SBE 19plus V2 `.hex` files (raw A/D counts).
    - Extracts sensor calibration coefficients from `.xmlcon` files.
    - Loads cruise-specific station metadata from `stations.csv`.
    - Converts raw counts to initial engineering units (T, C, P, O2, pH, CHL) using the official Sea-Bird Scientific Python toolkit.
- **Key Interface:** `ingest_sbe_hex()`

### 2. Physics Component (`eos80_processing.py`)
**Role:** Oceanographic Correction & Property Derivation
- **Responsibilities:**
    - Performs physical corrections: Soak elimination, Cell Thermal Mass (CTM) correction, O2 tau-shift alignment, and Loop Edit (pressure reversal removal).
    - Derives EOS-80 physical properties: Practical Salinity (PSS-78), potential temperature ($\theta$), and in-situ density ($\rho$).
    - Applies secondary calibrations and quality control (QC) flags based on descent velocity and statistical spike removal (Wild Edit).
- **Key Interface:** `apply_physics()` and the `apply_*` pipeline functions.

### 2b. Processed-data Component (`cnv_ingestion.py`)
**Role:** SeaSoft-processed Data Interface
- **Responsibilities:**
    - Reads SeaSoft `.cnv` (and fullcast `.asc`) files for the `downcast`, `upcast` and `fullcast` data sources.
    - Maps SeaSoft columns to the pipeline's binned schema; recomputes theta, density and depth with the EOS-80 functions.
    - Splits fullcast files into down and up at the deepest bin.
- **Key Interface:** `ingest_cnv()`, `find_cnv_files()`

### 3. Orchestrator Component (`main.py`)
**Role:** Workflow Manager & Persistence
- **Responsibilities:**
    - Orchestrates the end-to-end pipeline for a specific cruise.
    - Manages CLI arguments, logging, and directory resolution.
    - Ensures atomic and idempotent database commits to DuckDB.
    - Records build provenance (git commit hash, calibration file SHA-256, and timestamps) for auditability.
- Selects the data source with `--source raw|downcast|upcast|fullcast|all` (default `raw`). Rows are replaced per `(cruise_id, data_source)`; `migrate_schema()` upgrades older databases.
- **Key Interface:** `main()` entry point, `build_source()` and `process_one_cast()`.

### 3b. Section Gridding (`section_grid.py`)
**Role:** ODV-style weighted-average gridding for the Vertical Section tab (numpy only).
- **Key Interface:** `weighted_average_grid()`, `effective_horizontal_scale()`

### 4. Analysis Component (`ctd_holoviews.py`)
**Role:** Interactive Visualization & Export
- **Responsibilities:**
    - Serves a Panel-based dashboard for interactive data exploration.
    - Renders vertical profiles, T-S analysis, and vertical sections with isopycnal contours.
    - Calculates real-time analytics: Apparent Oxygen Utilization (AOU), Mixed Layer Depth (MLD), and the Metabolic Index ($\Phi$).
    - Facilitates tabular data export for external analysis.
    - Hides the first N seconds of every raw cast with the **Soak time hidden (s)** slider (default 0 s, i.e. nothing extra hidden; Sea-Bird's `PumpDelay=60` profiling example suggests 60 s). It is applied through `_T_soak()` and is disabled for processed sources.
- **Key Interface:** `dashboard.servable()`

### 5. Infrastructure Component (Scripts)
**Role:** Environment-Specific Automation
- **Linux/macOS (`scripts/linux_mac/`):** Bash scripts for building the database and launching the dashboard.
- **Windows (`scripts/windows/`):** Batch files for equivalent operations in a CMD environment.

---

## AI Agent Interaction Guidelines

When an AI agent (like Junie or others) interacts with this repository, it should adhere to the following operational patterns:

### Adding a New Cruise
1. **Directory Structure:** Create `cruises/<cruise_id>/`.
2. **Raw Data:** Place `.hex` files in `cruises/<cruise_id>/hex/`. Optional processed data goes in `cnv_downcast/`, `cnv_upcast/`, `cnv_fullcast/`.
3. **Calibration:** Ensure `calibration.xmlcon` and `config.toml` are present in the cruise root.
4. **Metadata:** Populate `stations.csv` with mappings from `station_id` (the cast file name without extension) to decimal-degree `lat`/`lon` (negative south/west) and cast numbers. The column names `station_id`, `lat`, `lon` match the echogram project's `stations.csv`.

### Modifying the Pipeline
- **Physics Changes:** All oceanographic logic should reside in `eos80_processing.py`. Use the `seabirdscientific` toolkit wherever possible to maintain parity with official Sea-Bird standards.
- **Ingestion Changes:** Add new sensors or change A/D conversion logic in `sbe19plus_ingestion.py`.
- **Database Schema:** If adding columns, update the aggregation configuration in `main.py`, `cnv_ingestion.OUTPUT_COLUMNS` and the query logic in `ctd_holoviews.py`. All dashboard queries read through `_T()`, which filters by the selected data source and cast direction.

### Execution and Verification
- **Run the Build:** Use `python main.py <cruise_id>` to process data.
- **Logs:** Monitor `logs/wf_build_<cruise_id>_<timestamp>.log` for detailed processing diagnostics.
- **Database:** Verify output in `processed/wf_ctd_eos80.duckdb`. The `build_metadata` table should be checked to confirm successful persistence and provenance.

### Dependencies
- This project requires **Python 3.13**.
- Other dependencies are listed in `pyproject.toml`.
