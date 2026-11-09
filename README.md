# Western Flyer CTD Data

This repository contains the processing pipeline and visualization suite for Sea-Bird CTD data collected aboard the R/V Western Flyer.

## Feature Summary

The Western Flyer CTD codebase is a modular, automated processing pipeline designed for Sea-Bird SBE 19plus V2 CTD instrumentation. It provides a standardized framework for raw hex data conversion, physical correction, and interactive visualization.

* **Raw .hex Processing (default):** The pipeline starts from raw instrument `.hex` files. Calibration coefficients are read directly from the instrument's `.xmlcon` configuration file, giving you full provenance over every conversion step.
* **SeaSoft-processed data (optional):** Files already processed in SeaSoft (`.cnv`, or fullcast `.asc`) can be loaded as a separate data source: downcast, upcast or fullcast. They are stored next to the raw rows in the same database and the dashboard has a **Data source** selector. See [Processed data sources](#processed-data-sources-cnv).
* **Sea-Bird Scientific Toolkit:** All sensor conversion and correction routines delegate to the official [Sea-Bird Scientific Python toolkit](https://github.com/Sea-Bird-Scientific/seabirdscientific). This includes temperature/pressure/conductivity conversion, O2 tau and hysteresis corrections, cell-thermal-mass correction, Sea-Bird Low-Pass Filter, O2 tau-shift alignment, loop edit, Wild Edit spike removal, and downcast extraction.
* **Modular Cruise Architecture:** Each expedition is isolated under `cruises/<cruise_id>/`. Adding a new cruise requires only creating a directory with the raw `.hex` files and metadata; the directory name is the cruise ID.
* **Sidecar Data Integration:** The pipeline joins raw CTD measurements with `config.toml` (processing parameters), `calibration.xmlcon` (sensor coefficients), and `stations.csv` (station metadata) automatically.
* **Automated EOS-80 Physics Pipeline:** Core oceanographic correction logic runs in this fixed order: soak elimination → cell-thermal-mass (CTM) conductivity correction → O2 tau-shift alignment → loop edit → EOS-80 physics (Practical Salinity from CTM-corrected conductivity via PSS-78, then potential temperature and density) → chlorophyll calibration (`apply_chl_calibration`) → Wild Edit spike removal → velocity-based QC → downcast extraction → 1 m bin averaging.
* **Atomic, Idempotent Storage:** Processed data is managed via DuckDB. Per-cruise records are replaced atomically inside a single transaction. A `build_metadata` table records the SHA-256 of the `.xmlcon` file and the git commit for every build, so every row in `ctd_data` is traceable to the exact calibration that produced it.
* **Per-Build Audit Logging:** Each invocation writes a fresh, timestamped log file (`logs/wf_build_<cruise>_<timestamp>.log`).
* **Interactive Dashboard Suite:** A built-in visualization suite powered by the HoloViz ecosystem (Panel, HoloViews, Bokeh) renders interactive dashboards. Supports multi-variable vertical profiling, T-S analysis, vertical section plots with isopycnal (σθ) contours, AOU, MLD/stability, the metabolic index Φ, an ocean (bathymetry) map of the station positions, and tabular export.

## Root Directory Notes

The project root can be named anything (e.g., `westernflyer_cruise_ctd`).

To avoid Windows permission issues, place the root folder inside your Windows user directory:
`C:\Users\<your_username>\westernflyer_cruise_ctd`

## Python Installation Requirements

This project requires **Python 3.13**.

### Windows

Install Python 3.13 from python.org (not from the Microsoft Store, which puts it in a different folder than the instructions below assume).

1. If you installed Python 3.13 from the Microsoft Store, remove it first: Windows Settings, Apps, "Python 3.13", Uninstall.
2. Download the "Windows installer (64-bit)" for Python 3.13 from https://www.python.org/downloads/windows/.
3. Run it and choose **Install Now**. Leave **"Install for all users"** unticked, so it installs for your user only. Leave the **py launcher** ticked.
4. When the installer asks to **"Add python.exe to PATH"**, select **No** (leave it unticked).
5. Python installs to `C:\Users\<your_username>\AppData\Local\Programs\Python\Python313\`.
6. Check it in Command Prompt: `py -0p` should list `Python313` under `AppData\Local\Programs\Python`.

### macOS (Homebrew)
    brew install python@3.13

### Linux (Ubuntu / Debian) using apt install
    sudo add-apt-repository ppa:deadsnakes/ppa
    sudo apt update
    sudo apt install python3.13 python3.13-venv

### Linux (Ubuntu / Debian) using pyenv

This has the advantage of not requiring root privileges, and it does not install Python 3.13 system wide.

    # Install pyenv:
    curl -fsSL https://pyenv.run | bash
    # Install Python 3.13:
    pyenv install 3.13
    # Set Python 3.13 as the global default:
    pyenv global 3.13

## Project Structure

*`logs/` and `processed/` are created automatically on first run.*

    .
    |   cnv_ingestion.py
    |   compare_sources.py
    |   ctd_holoviews.py
    |   eos80_processing.py
    |   main.py
    |   pyproject.toml
    |   sbe19plus_ingestion.py
    +---cruises
    |   +---2025_Baja
    |   |   |   config.toml           processing parameters
    |   |   |   calibration.xmlcon    sensor calibration (from SeaSoft)
    |   |   |   stations.csv          station metadata
    |   |   |
    |   |   \---hex
    |   |           20250416_cast1.hex
    |   |           20250416_cast2.hex
    |   |           ... (etc)
    |   |
    |   +---2025_MontereyBay
    |   |   |   config.toml           processing parameters
    |   |   |   calibration.xmlcon    sensor calibration (from SeaSoft)
    |   |   |   stations.csv          station metadata
    |   |   |
    |   |   \---hex
    |   |           20250714_NPS_cast1.hex
    |   |           20250714_NPS_cast2.hex
    |   |           ... (etc)
    |   |
    |   +---2026_MontereyBay
    |   |   |   config.toml           processing parameters
    |   |   |   calibration.xmlcon    sensor calibration (from SeaSoft)
    |   |   |   stations.csv          station metadata
    |   |   |
    |   |   \---hex
    |   |           20260401_cast1.hex
    |   |           20260401_cast2.hex
    |   |           ... (etc)
    |   |
    |   \---2026_PNW
    |       |   config.toml           processing parameters
    |       |   calibration.xmlcon    sensor calibration (from SeaSoft)
    |       |   stations.csv          station metadata
    |       |
    |       \---hex
    |               20260516_cast1.hex
    |               20260516_cast2.hex
    |               ... (etc)
    +---logs
    +---processed
    \---scripts
        +---linux_mac
        |       ctd_build.sh                     (generic; takes <cruise_id>)
        |       ctd_build_all.sh                 (builds every cruise under cruises/)
        |       ctd_build_2025_Baja.sh           (wrapper around ctd_build.sh 2025_Baja)
        |       ctd_build_2025_MontereyBay.sh    (wrapper for 2025_MontereyBay)
        |       ctd_build_2026_MontereyBay.sh    (wrapper for 2026_MontereyBay)
        |       ctd_build_2026_PNW.sh            (wrapper for 2026_PNW)
        |       ctd_dashboard.sh
        |
        \---windows
                ctd_build.bat                    (generic; takes <cruise_id>)
                ctd_build_all.bat                (builds every cruise under cruises\)
                ctd_build_2025_Baja.bat          (wrapper around ctd_build.bat 2025_Baja)
                ctd_build_2025_MontereyBay.bat   (wrapper for 2025_MontereyBay)
                ctd_build_2026_MontereyBay.bat   (wrapper for 2026_MontereyBay)
                ctd_build_2026_PNW.bat           (wrapper for 2026_PNW)
                ctd_dashboard.bat

## Cruises

| Cruise ID | Dates | Casts | calibration.xmlcon | Notes |
|---|---|---|---|---|
| `2025_Baja` | Apr 16 - May 6, 2025 | 26 | Jan 2026 master config (SBE19plus V2 S/N 8289; pH cal 02-Feb-26) | |
| `2025_MontereyBay` | Jul 14 - Sep 25, 2025 | 15 | Jan 2026 master config (same as Baja) | Positions in `stations.csv` are real positions from the cruise logs (previously a placeholder of 36.800, -121.950). The deck-test cast `20250909_SoCo_0051` was removed from `hex/` because it never goes into the water and always failed; its row remains in `stations.csv` with no position. |
| `2026_MontereyBay` | Apr 1 - Oct 8, 2026 | 9 | June 2026 master config (pH cal 12-Jun-26) | The April 1 and April 17 casts use the June file, but its pH calibration dates from after those casts. They could be split out and run with the March master config (pH cal 30-Mar-26); only the pH slope and offset change. `20260417_cast2` uses the same position as `20260417_cast1` (`36-47.82N, 121-50.82W`). Position and station name are still missing for `20260730` (max pressure about 91 dbar, about 90 m), so that cast is dropped from the database until they are filled in. `sb_cast` 10 appears twice. `20260818_cast_null` is listed in `stations.csv` but has no `.hex` file. `C1` (`SBE19plus_01908289_2026_10_08`) and `MossLandingCanyon` share the same position, so their map markers overlap. |
| `2026_PNW` | May 16 - Jun 5, 2026 | 5 | May 2026 master config (pH cal 02-May-26) | Latest calibration before both cast dates. `MIN_DEPTH_FLOOR = 1.0` because the casts are shallow. |

## File Descriptions

* **main.py** — Orchestrator. Parses CLI args, loads the `.xmlcon` calibration, runs the per-cast pipeline, writes the DuckDB atomically, and stamps build provenance.
* **sbe19plus_ingestion.py** — Hex ingestion and calibration. Reads raw `.hex` files via `read_hex_file`, applies temperature/pressure/conductivity/O2 (with tau and hysteresis corrections)/pH/CHL conversions from the Sea-Bird Scientific toolkit, and attaches cruise-log metadata.
* **eos80_processing.py** — EOS-80 physics pipeline. CTM correction, O2 tau-shift, loop edit, Sea-Bird Low-Pass Filter, Wild Edit spike removal, and depth/theta/density calculations all delegate to the Sea-Bird Scientific toolkit. Salinity is derived from CTM-corrected conductivity via `gsw.SP_from_C`.
* **cnv_ingestion.py** — Reader for SeaSoft-processed `.cnv` / `.asc` files (downcast, upcast, fullcast). Produces the same binned rows as the raw pipeline.
* **section_grid.py** — Weighted-average gridding used by the Vertical Section tab (ODV-style); numpy only.
* **compare_sources.py** — Prints per-station differences between two data sources of a cruise (for example raw minus downcast).
* **ctd_holoviews.py** — Read-only Panel dashboard. Reactive widgets update all tabs when cruise or station selection changes.
* **pyproject.toml** — Package definition. Enables `pip install -e .` to install the project and all dependencies in one step.
* **config.toml** — Processing constants per cruise (CTM coefficients, bin size, QC thresholds, Wild Edit parameters). See schema below.
* **calibration.xmlcon** — Sensor calibration file exported from SeaSoft. Contains T/C/P/O2/pH/CHL coefficients. Use the xmlcon whose calibration dates match the cruise. The pH sensor was recalibrated several times in 2026, so choose the most recent calibration before the casts, and for a cruise spanning a recalibration run the casts in batches with the matching file.
* **stations.csv** — Per-cast metadata: station name, lat/lon, cast numbers, start time.

## Prerequisites

**Git** must be installed to download the software from GitHub (`git clone`). Download it from [git-scm.com](https://git-scm.com/downloads) and confirm with `git --version`.

Python 3.13 is required (see above). The **Sea-Bird Scientific Python Toolkit** is declared as a dependency in `pyproject.toml` and is installed automatically from PyPI when you run `pip install -e .` — no manual download required.

## Getting Started

    git clone https://github.com/joeacarlisle/westernflyer_cruise_ctd.git
    cd westernflyer_cruise_ctd

Then follow the **Prerequisites** and **Setup** sections below to install Python 3.13 and the project dependencies.

## Setup: Virtual Environment and Installation

*Run from the project root directory.*

### Windows (Command Prompt)

    "C:\Users\<your_username>\AppData\Local\Programs\Python\Python313\python.exe" -m venv .venv
    .venv\Scripts\activate
    pip install -e .

### macOS / Linux

    python3.13 -m venv .venv
    source .venv/bin/activate
    pip install -e .

`pip install -e .` reads `pyproject.toml` and installs all dependencies in one step, including the Sea-Bird Scientific toolkit pulled from PyPI.

The `-e` (editable) flag means source changes are picked up immediately without reinstalling.

## Preparing a New Cruise

1. Create a cruise directory: `cruises/<cruise_id>/`
2. Place raw `.hex` files in `cruises/<cruise_id>/hex/`
3. Copy the sensor calibration file from SeaSoft to `cruises/<cruise_id>/calibration.xmlcon`
4. Create `cruises/<cruise_id>/config.toml` (see schema below)
5. Create `cruises/<cruise_id>/stations.csv` (see schema below)
6. Optional: place SeaSoft-processed files in `cnv_downcast/`, `cnv_upcast/` and/or `cnv_fullcast/` (see [Processed data sources](#processed-data-sources-cnv)). Cruises without these folders build exactly as before.

### stations.csv schema

| Column         | Description                                                            |
|----------------|------------------------------------------------------------------------|
| `station_id`   | Required, unique. Hex filename stem (e.g. `20250416_cast1` for `20250416_cast1.hex`) |
| `lat`          | Latitude in signed decimal degrees, north positive (e.g. `25.51817`)   |
| `lon`          | Longitude in signed decimal degrees, west negative (e.g. `-110.98733`) |
| `station_name` | Station identifier (e.g. `9`, `SC1`, `MarrowstoneIsland`)              |
| `sb_cast`      | Sea-Bird instrument cast number                                        |
| `wf_cast`      | Western Flyer expedition cast number                                   |
| `start_utc`    | Cast start time in UTC (`YYYY-MM-DD HH:MM:SS`). Used when the file header has no time, and to flag a header time that disagrees with it by more than 15 minutes. See [Cast start time](#cast-start-time). |

## Running the Pipeline

**Activate the virtual environment first.** Required every time you open a new terminal.

### Windows (Command Prompt)
    cd C:\Users\<your_username>\westernflyer_cruise_ctd
    .venv\Scripts\activate

You should see `(.venv)` at the start of your prompt.

### macOS / Linux
    cd /path/to/westernflyer_cruise_ctd
    source .venv/bin/activate

Make the scripts executable once (first time only):

    chmod +x scripts/linux_mac/*.sh

---

Run the build with the cruise ID as the argument:

* **Windows:** `scripts\windows\ctd_build.bat <cruise_id>`
* **Linux / macOS:** `./scripts/linux_mac/ctd_build.sh <cruise_id>`

Each cruise also has a shortcut script with the cruise ID filled in, for example `scripts\windows\ctd_build_2026_PNW.bat`. All build scripts (`ctd_build`, the cruise shortcuts and `ctd_build_all`, on Windows and Linux / macOS) build with `--source all`; add `--source raw` for raw data only. Calling `main.py` directly still defaults to raw. To rebuild every cruise under `cruises/` one after another, run:

* **Windows:** `scripts\windows\ctd_build_all.bat`
* **Linux / macOS:** `./scripts/linux_mac/ctd_build_all.sh`

The build scripts use `--source all`, so they also load the SeaSoft-processed sources (downcast, upcast, fullcast) for every cruise that has them; cruises without processed folders build raw only.
Extra arguments (such as `--bin-size 0.5`) are passed on to `main.py`. A cruise's rows in the database are replaced each time it is built, so cruises renamed after an earlier build leave their old rows behind. To remove those, delete `processed/wf_ctd_eos80.duckdb` and rebuild.

Alternatively, call `main.py` directly for full control. The following are example invocations — run only the one that fits your needs:

    # Basic build
    python main.py 2025_Baja

    # Override bin size or enable verbose logging
    python main.py 2025_Baja --bin-size 0.5 --verbose

    # Write output to a custom DuckDB path
    python main.py 2025_Baja --db /path/to/custom.duckdb

    # Override the xmlcon or hex directory locations
    python main.py 2025_Baja --xmlcon /path/to/custom.xmlcon
    python main.py 2025_Baja --hex-dir /path/to/hex_files/

    # Build from SeaSoft-processed files instead of raw (see below)
    python main.py 2025_MontereyBay --source downcast
    python main.py 2025_MontereyBay --source all

### CLI arguments

| Argument           | Default                           | Description                            |
|--------------------|-----------------------------------|----------------------------------------|
| `cruise_id`        | *(required)*                      | Cruise directory name under `cruises/` |
| `--source`         | `raw`                             | `raw`, `downcast`, `upcast`, `fullcast`, or `all` (every source that has input files) |
| `--bin-size`       | From `config.toml`                | Vertical bin size in meters (raw only) |
| `--xmlcon`         | `cruises/<id>/calibration.xmlcon` | Path to sensor calibration file        |
| `--hex-dir`        | `cruises/<id>/hex/`               | Directory containing raw `.hex` files  |
| `--cnv-dir`        | `cruises/<id>/cnv_<source>/`      | Directory of processed files (one source only) |
| `--db`             | `processed/wf_ctd_eos80.duckdb`   | DuckDB output path                     |
| `--verbose` / `-v` | Off                               | Enable DEBUG-level logging             |

### Processed data sources (.cnv)

Besides raw `.hex` files, a cruise can hold casts already processed in SeaSoft. Put them in these folders next to `hex/`; the file names are free-form apart from the cast key:

| Folder                | `--source` | Stored as                                   |
|-----------------------|------------|---------------------------------------------|
| `hex/`                | `raw`      | `data_source = raw`, `cast_direction = down` |
| `cnv_downcast/`       | `downcast` | `downcast` / `down`                         |
| `cnv_upcast/`         | `upcast`   | `upcast` / `up`                             |
| `cnv_fullcast/`       | `fullcast` | `fullcast` / `down` and `up` (split at the deepest bin; the deepest bin is the downcast) |

* **One script, one option.** `raw` is the default, so existing builds and the `ctd_build*.bat/.sh` scripts behave as before. `--source all` builds every source whose folder has files and skips the rest, which makes `ctd_build_all` safe for cruises that have no processed data (for example `ctd_build_all.sh --source all`). An explicit source whose folder is missing is an error.
* **Cast key.** The text of the file name before `_filter` must equal a `station_id` in `stations.csv` (`20250916_Cabrillo_cast1_filter_align_cell_loop_derive_downcast.cnv` matches `20250916_Cabrillo_cast1`). A file name without `_filter` uses its whole stem. Position and station come from `stations.csv` because `.cnv` files have no usable position.
* **Fullcast files.** A `.cnv` is preferred; a SeaSoft ASCII export (`.asc`, no header block, column names repeated every 60 rows) is read only when no `.cnv` exists for the same cast.
* **What is recomputed.** Salinity, temperature, oxygen (umol/kg), pH and chlorophyll are taken from SeaSoft's output. Potential temperature, density and depth are recomputed with the same EOS-80 functions as the raw pipeline. The raw processing steps (soak, CTM, tau shift, loop edit, Wild Edit) are not repeated. The pressure of each SeaSoft bin is kept (for example 61.463 dbar), so processed bins are not on whole-dbar boundaries like raw bins.
* **Limits.** Processed files have no per-scan time, so every bin carries the cast start time; the `.cnv` flag column gives `qc_flag` (0 = 1, otherwise 3), and `.asc` has none (all 1). Calibration comes from SeaSoft, not from `calibration.xmlcon`; `build_metadata.calibration_sha256` for a processed build is a hash of the input files.
* **Replacing rows.** Rows are replaced per cruise **and** data source, so rebuilding `downcast` never touches `raw`. An existing database from an earlier version is upgraded automatically on the next build (existing rows are labelled `raw` / `down`).
* **Dashboard.** The sidebar gets a **Data source** selector (and a **Cast direction** selector when a source holds both directions, as fullcast does). Every tab follows the selection. A database without these columns shows no selector.
* **Comparing sources.** `python compare_sources.py 2025_MontereyBay --a raw --b downcast` prints, per station and variable, the mean and largest difference in 1 m bins. On the sample Cabrillo cast, raw and SeaSoft salinity and temperature agree to about 0.01 PSU / 0.01 °C on average, while oxygen differs by about 25 umol/kg and pH by 0.04. These come from the calibration coefficients: SeaSoft's sensor block can carry different calibration dates than the `.xmlcon`, and the raw pipeline always uses the `.xmlcon`.

### Cast start time

The SBE 19plus clock on every cruise so far is Pacific local time, so the header time is exactly 7 hours behind `start_utc` in `stations.csv`. The pipeline converts the header time (second precision) to UTC using `INSTRUMENT_TZ` (default `America/Los_Angeles`; set `INSTRUMENT_TZ = "UTC"` in a cruise's `config.toml` if its clock was set to UTC). `start_utc` is the fallback when a file has no header time, and a difference of more than 15 minutes from the converted header time is logged as a warning. `time_iso` in the database is therefore UTC; databases built before this change stored the local header time, so rebuild cruises to update it.

### Failed casts

If a cast cannot be processed, the build logs one error line with the reason (for example, a cast that never gets deeper than `MIN_DEPTH_FLOOR`), skips that cast, and continues with the rest. The log ends with a list of failed casts and their reasons. Full tracebacks are written only with `--verbose`. Casts that processed successfully are still written to the database.

## Running the Dashboard

* **Windows:** `scripts\windows\ctd_dashboard.bat`
* **Linux / macOS:** `./scripts/linux_mac/ctd_dashboard.sh`

The CTD dashboard starts on port 5006 (Panel's default) at `http://localhost:5006`. The flow-through dashboard in [westernflyer_cruise_flowthru](../westernflyer_cruise_flowthru) starts on port 5007, so the two applications can run side by side.

### Soak time

The sidebar has a **Soak time hidden (s)** slider (0 to 600 s, default **0**, which hides nothing extra). It hides the first N seconds of every raw cast, counted from the cast's first scan, in every tab, the table and the CSV export. Sea-Bird's SBE 19plus V2 manual gives no fixed soak time: its profiling example says to let the instrument soak at least the time needed for the pump to turn on (`PumpDelay=60`, 60 seconds), so 60 s is a sensible value to choose. Data logged before the pump has been running is not trusted: the conductivity cell is not yet flushed and the oxygen sensor has not yet equilibrated.

* It is separate from **Show Soak Data (Surface)**, which shows or hides the rows the build flagged as soak (shallow rows before the descent is detected). Both filters apply.
* It applies to the raw source only. Processed (`.cnv`) files have one start time for every bin and SeaSoft has already removed the soak, so the slider is disabled for them.
* A value longer than a cast's record, or longer than its calculated soak, hides the top of the profile or the whole cast (the tabs then show "Data Pending..."). Lower the slider to see it.

### Vertical Section tab

The section is a vertical slice through the stations you choose, drawn in the style of Ocean Data View. Controls above the plot:

* **Name contains / From date / To date:** narrow a long station list. Type part of a station name or ID and press Enter, and/or pick a date range (UTC, from each station's first scan). Only the matching stations are listed and they are all selected. A new cruise or data source clears the filters.
* **Stations in section:** a list of the cruise's stations. Select the ones that lie along one line (hold Ctrl or Shift for several); **All** and **None** set them all. Choosing a new cruise selects every station again. At least two are needed. The section loads only the chosen stations from the database and keeps the last few selections in memory, so changing the variable, axis or gap setting does not query again.
* **Gridding:** *Weighted average (ODV-style)* (default) estimates every grid value as a weighted average of the nearby data, with weights `exp(-r²)` and `r² = (dx/Lx)² + (dy/Ly)²`, and leaves cells blank when no data lie within about two scale lengths. It gives smooth fields and stays fast even with many stations. *Linear triangulation* is the earlier method: it passes exactly through every measurement and fills the whole triangle between stations, but is slow with many stations and can look streaky. The **Horizontal scale** (percent of the x range) and **Depth scale** (percent of the depth range) sliders, shown for the weighted average, set the scale lengths Lx and Ly. A measurement has weight 1 at the grid point, 0.37 one scale length away, and almost none beyond two, so larger values smooth more and fill wider gaps, and smaller values keep more detail but leave more blank. The white areas between station clusters are cells more than about two scale lengths from any data; raise the horizontal scale to fill them. The horizontal length is never made narrower than about 0.8 times the typical station spacing, so cells between neighbouring stations are not blanked.
* **X axis:** *Distance along section (km)* (default) projects the chosen stations onto the straight line that fits them best, measured from the southern (or western) end. *Longitude* and *Latitude* order the stations by that coordinate. *Time (days since first station)* spaces them by when they were sampled. *Distance Along Track (km)* is the earlier view: stations in time order with the distances between consecutive stations added up.
* **Blank gaps wider than (km):** the shading is not drawn between two neighbouring stations that are farther apart than this (default 100 km). Set it to 0 to grid across every gap.
* **Section map (right of the plot):** shows every station of the cruise in grey, the chosen stations in orange, the first station of the section in green, and the line joining the chosen stations in the order the section draws them in red. It uses the same Esri Ocean Base map as the Map tab (internet needed) and updates when you change the stations or the X axis.
* Triangles and dashed lines mark the stations, and the black contours are density (σθ) every 0.5 kg/m³.

A cruise that is not one transect (for example 2025_Baja, which visits several areas) gives a misleading section if every station is used, because the colours between distant stations are interpolated across water that was not sampled. Select only stations on one line.

## config.toml Schema

`config.toml` uses TOML format with named sections (e.g. `[processing]`, `[wild_edit]`). The cruise ID is **not** stored here — it comes from the directory name.

### Calibration Offsets

| Parameter        | Description                                                                                                                                                                                                                       |
|------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `CTD_SERIAL`     | Instrument serial number (informational; not read by pipeline)                                                                                                                                                                    |
| `SAL_OFFSET`     | Additive offset applied to recomputed Practical Salinity (PSU). Use to match bottle salinity samples.                                                                                                                             |
| `PH_DRIFT`       | Additive offset for pH. Use to correct for sensor drift between calibrations.                                                                                                                                                     |
| `O2_BOOST_RATIO` | Multiplicative gain applied to oxygen before density normalization. Use to match Winkler titration values.                                                                                                                        |
| `CHL_SLOPE`      | Multiplicative secondary gain for chlorophyll (default 1.0). The xmlcon ScaleFactor is applied during ingestion; use this only when a post-deployment fluorometer calibration against extracted chlorophyll samples is available. |
| `CHL_OFFSET`     | Additive offset for chlorophyll (µg/L).                                                                                                                                                                                           |

### SBE Processing Constants

An optional `INSTRUMENT_TZ` key (any IANA time zone name, default `America/Los_Angeles`) sets the time zone of the instrument clock used to convert header times to UTC. See [Cast start time](#cast-start-time).

| Parameter           | Description                                                                                                                                                                                                                                           |
|---------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `T68_CONVERSION`    | Scale factor converting ITS-90 temperature to IPTS-68 (default 1.00024). EOS-80 equations require IPTS-68.                                                                                                                                            |
| `CTM_ALPHA`         | Cell-thermal-mass amplitude α (default 0.04). SBE 19plus default. Passed to `cell_thermal_mass()`.                                                                                                                                                    |
| `CTM_TAU`           | Cell-thermal-mass time constant τ in seconds (default 8.0). SBE 19plus default. Passed to `cell_thermal_mass()`.                                                                                                                                      |
| `ALIGN_OXY_SHIFT`   | Samples to advance oxygen data to correct for SBE 43 electrochemical lag. At 4 Hz, 20 samples = 5 s ≈ 5 m at 1 m/s. Passed to `align_ctd()`.                                                                                                          |
| `LPF_TIME_CONSTANT` | Sea-Bird Low-Pass Filter time constant in seconds. Applied to conductivity before CTM, to temperature before PSS-78, and to all derived physics variables. Default 0.5 s (matches SeaSoft default for 4 Hz profiling). Passed to `low_pass_filter()`. |

### Wild Edit Parameters

| Parameter               | Description                                                                                         |
|-------------------------|-----------------------------------------------------------------------------------------------------|
| `WILD_STD_PASS1`        | First-pass spike rejection threshold (standard deviations from block mean). Default 2.0.            |
| `WILD_STD_PASS2`        | Second-pass spike rejection threshold (standard deviations). Default 20.0.                          |
| `WILD_SCANS_PER_BLOCK`  | Number of scans per statistics block. Default 100 (25 s at 4 Hz). A cast with fewer scans left after Loop Edit is treated as one block. |
| `WILD_DISTANCE_TO_MEAN` | Minimum absolute distance from block mean before a scan can be flagged (0 = no floor). Default 0.0. |

### Soak Detection Parameters

| Parameter           | Description                                                                                |
|---------------------|--------------------------------------------------------------------------------------------|
| `MIN_DEPTH_FLOOR`   | Minimum depth before soak detection begins, and the deepest point at which Loop Edit may start the downcast. Default 10.0. Must be less than the cast's maximum depth, or the cast fails with an error; lower it for shallow casts. |
| `LOOP_MIN_VELOCITY` | Minimum descent velocity (m/s) for soak detection and loop edit. Default 0.25.             |
| `SOAK_WINDOW_SIZE`  | Consecutive samples that must satisfy descent criteria to end the soak period. Default 20. |

### QC and Resolution Thresholds

| Parameter         | Description                                                                           |
|-------------------|---------------------------------------------------------------------------------------|
| `QC_VELOCITY`     | Descent speed (m/s) above which a scan is flagged QC=3. Default 1.2.                  |
| `BIN_SIZE_METERS` | Vertical bin resolution in the database (m). Default 1.0. Override with `--bin-size`. |

## Dashboard stops responding

The dashboard stops responding after a period of inactivity and needs to be refreshed (press F5 or reload the page). This is the browser's tab-sleeping setting, on Windows and on Mac: Edge puts an inactive tab to sleep (15 minutes on the Windows machine this was tested on; the time is configurable), and Chrome's Memory Saver can do the same. Either one cuts the tab's link to the dashboard server. In Edge, add the dashboard address to Settings > System and performance > Performance > "Always keep these sites active" (for example `localhost`), or turn off "Automatically put tabs to sleep". In Chrome, use Settings > Performance > "Always keep these sites active", or turn off Memory Saver.

## Acknowledgements

The Vertical Section tab is modelled on the sections in Ocean Data View (ODV). Its weighted-average gridding follows the approach described by R. Schlitzer for ODV (https://odv.awi.de). The implementation in `section_grid.py` is original code written for this project and is not affiliated with or endorsed by ODV or the Alfred Wegener Institute; its results are similar to, but not identical with, ODV's.

## Contact

For questions regarding this data archive or the Western Flyer Foundation, please contact **joeacarlisle@gmail.com**
