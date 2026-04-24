# Western Flyer Foundation CTD Data Archive

This repository contains the processing pipeline and visualization suite for Sea-Bird CTD data.

## Root Directory Notes
The project’s root directory can be named anything you prefer. 
For example: `wf_cruise_ctd`

To avoid Windows permission issues when running scripts or creating virtual environments, place the entire root folder inside your Windows user directory, such as:
`C:\Users\<your_username>\wf_cruise_ctd`

This ensures you have full read/write/execute permissions for all pipeline operations.

## Python Installation Requirements
This project requires Python 3.12.10.

### Windows Python Installation Notes
When installing Python 3.12.10 on Windows:
* The installer will ask: “Add Python to PATH?” → **Select NO**
* This is intentional. You will explicitly point to the Python installation directory when creating the virtual environment.
* Typical installation path: `C:\Users\<your_username>\AppData\Local\Programs\Python\Python312\`

### macOS Python Installation (Homebrew)
Install Python 3.12 using Homebrew:
```bash
brew install python@3.12
Then create your virtual environment:

Bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
Linux Python Installation (Ubuntu / Debian)
Install Python 3.12 using the deadsnakes PPA:

Bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.12 python3.12-venv
Then create your virtual environment:

Bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
Project Structure
Note: The logs and processed directories are automatically created when the database build pipeline is executed.

Plaintext
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
File Descriptions
main.py — The master orchestration script. It triggers the processing pipeline for specified expeditions (e.g., baja2025) and manages the flow of data.

sbe19plus_ingestion.py — Contains the logic for parsing and ingesting raw hex data from Sea-Bird SBE 19plus instruments.

eos80_processing.py — Handles the core oceanographic data processing, including EOS‑80 coefficient application, salinity, and density calculations.

ctd_holoviews.py — The visualization suite. Uses Panel, Holoviews, and Bokeh to render interactive dashboards for vertical profiles and T‑S diagrams.

requirements.txt — Lists all Python dependencies required to run the environment.

calibration.csv — Contains sensor calibration parameters for the CTD build process.

cruise_log.csv — Contains station metadata including latitude, longitude, and cruise event logs.

Setup: Virtual Environment & Dependencies
Important: All setup commands must be run from the project root directory.

Windows (Command Prompt)
When creating the virtual environment, explicitly point to your Python 3.12.10 installation:

Bash
"C:\Users\<your_username>\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
macOS
Bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
Linux
Bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
Running the Pipeline (baja2025_ctd_build)
Windows: Navigate to scripts/windows and run: baja2025_ctd_build.bat
Linux / macOS: Navigate to scripts/linux_mac and run: ./baja2025_ctd_build

Running the Dashboard (launch_holoviews)
Windows: Navigate to scripts/windows and run: launch_holoviews.bat
Linux / macOS: Navigate to scripts/linux_mac and run: ./launch_holoviews

Contact
For questions regarding this data archive or the Western Flyer Foundation, please contact joeacarlisle@gmail.com