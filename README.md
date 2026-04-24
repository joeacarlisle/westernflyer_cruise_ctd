# Western Flyer Foundation CTD Data Archive

This repository contains the processing pipeline and visualization suite for Sea-Bird CTD data.

## Feature Summary

The Western Flyer Foundation CTD Data Archive is a modular, automated processing pipeline designed for Sea-Bird SBE 19plus CTD instrumentation. It provides a standardized framework for data ingestion, physical correction, and interactive visualization.

* **Modular Cruise Architecture:** The repository utilizes a scalable directory structure where each expedition is isolated (e.g., `cruises/baja2025`). Adding a new cruise requires only the creation of a corresponding directory containing the raw `.cnv` files and metadata.
* **Sidecar Data Integration:** The pipeline implements a strict sidecar approach to metadata management. It automatically joins raw CTD measurements with local `calibration.csv` (sensor coefficients) and `cruise_log.csv` (station location and event metadata) files to ensure high data integrity during processing.
* **Automated EOS-80 Physics Pipeline:** The system automates core oceanographic correction logic, including:
    * Soak elimination and tau-shift correction.
    * Cell thermal mass (CTM) correction.
    * Savitzky-Golay Smoothing: Applied during the physics processing phase to reduce sensor noise while preserving the integrity of the signal shape and peak values.
    * EOS-80 density, salinity, and potential temperature calculations.
    * Automated binning based on configurable depth intervals.
* **Virtual Environment Management:** The project utilizes Python virtual environments (`venv`) to ensure project isolation, manage deterministic dependency resolution via `requirements.txt`, and guarantee reproducible research environments across different hardware setups.
* **Pipeline Orchestration Scripts:** The repository includes a `scripts/` directory containing cross-platform automation (batch files for Windows, shell scripts for Linux/macOS). These provide a streamlined entry point for executing build processes and launching the visualization dashboard with a single command.
* **Interactive Dashboard Suite:** A built-in visualization suite powered by the HoloViz ecosystem (Panel, HoloViews, Bokeh) renders interactive dashboards. This suite supports multi-variable vertical profiling, physics DNA (T-S diagrams), and spatial mapping for mission review.
* **Idempotent Data Storage:** Processed datasets are managed via DuckDB, allowing for efficient local storage and rapid query performance. The pipeline is designed to be idempotent; re-running the build for a specific cruise ID replaces existing records rather than duplicating them.
* **System-Agnostic Setup:** The repository maintains standardized configurations for Windows, macOS, and Linux, ensuring consistent environment replication across different research workstations and field equipment.

## Root Directory Notes
The project’s root directory can be named anything you prefer (e.g., `wf_cruise_ctd`).

To avoid Windows permission issues when running scripts or creating virtual environments, place the entire root folder inside your Windows user directory, such as: 
`C:\Users\<your_username>\wf_cruise_ctd`

This ensures you have full read/write/execute permissions for all pipeline operations.

## Python Installation Requirements
This project requires **Python 3.12.10**.

### Windows
When installing, the installer will ask: “Add Python to PATH?” **Select NO.**
You will point to the installation directory explicitly during setup.

* **Typical path:** `C:\Users\<your_username>\AppData\Local\Programs\Python\Python312\`

### macOS (Homebrew)
    brew install python@3.12

### Linux (Ubuntu / Debian)
    sudo add-apt-repository ppa:deadsnakes/ppa
    sudo apt update
    sudo apt install python3.12 python3.12-venv

## Project Structure
*Note: The logs and processed directories are automatically created when the database build pipeline is executed.*

    C:.
    |   ctd_holoviews.py
    |   eos80_processing.py
    |   main.py
    |   requirements.txt
    |   sbe19plus_ingestion.py
    +---cruises
    |   \---baja2025
    |       |   calibration.csv
    |       |   cruise_log.csv
    |       |
    |       \---cnv
    |               20250416_cast1.cnv
    |               ... (etc)
    +---logs
    +---processed
    \---scripts
        +---linux_mac
        |       baja2025_ctd_build.sh
        |       launch_holoviews.sh
        |
        \---windows
                baja2025_ctd_build.bat
                launch_holoviews.bat

## File Descriptions
* **main.py**: The master orchestration script. It triggers the processing pipeline and manages data flow.
* **sbe19plus_ingestion.py**: Logic for parsing raw cnv data from Sea-Bird SBE 19plus instruments.
* **eos80_processing.py**: Core oceanographic data processing (EOS‑80 coefficient application, salinity, density).
* **ctd_holoviews.py**: Visualization suite using Panel, Holoviews, and Bokeh.
* **requirements.txt**: Python dependencies.
* **calibration.csv**: Sensor calibration parameters.
* **cruise_log.csv**: Station metadata, coordinates, and event logs.

## Setup: Virtual Environment
*Run these commands from the project root directory.*

### Windows (Command Prompt)
    "C:\Users\<your_username>\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

### macOS / Linux
    python3.12 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

## Running the Pipeline (baja2025_ctd_build)
*Note: If on macOS or Linux, you must first make the scripts executable:*
    chmod +x scripts/linux_mac/baja2025_ctd_build.sh
    chmod +x scripts/linux_mac/launch_holoviews.sh

* **Windows:** Navigate to `scripts/windows` and run: `baja2025_ctd_build.bat`
* **Linux / macOS:** Navigate to `scripts/linux_mac` and run: `./baja2025_ctd_build.sh`

## Running the Dashboard (launch_holoviews)
* **Windows:** Navigate to `scripts/windows` and run: `launch_holoviews.bat`
* **Linux / macOS:** Navigate to `scripts/linux_mac` and run: `./launch_holoviews.sh`

## Contact
For questions regarding this data archive or the Western Flyer Foundation, please contact **joeacarlisle@gmail.com**
