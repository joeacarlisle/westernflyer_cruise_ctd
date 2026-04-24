# Western Flyer Foundation CTD Data Archive

This repository contains the processing pipeline and visualization suite for Sea-Bird CTD data.

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
    |       wf_build.log
    +---processed
    |       wf_ctd_eos80.duckdb
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
