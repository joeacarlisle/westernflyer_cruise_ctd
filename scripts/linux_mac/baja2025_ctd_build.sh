#!/bin/bash

# Run 'chmod +x baja2025_ctd_build' to make this executable.

# Move to the project root (up two levels from where this script is located)
cd "$(dirname "$0")/../.."

# Activate the virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "[WARNING] Virtual environment not found at .venv/bin/activate"
fi

# Clear old build logs to ensure a fresh audit trail
if [ -f "logs/wf_build.log" ]; then
    rm "logs/wf_build.log"
fi

# Run the CTD build for Baja 2025
echo "Starting Baja 2025 CTD Build..."
python main.py baja2025

# Status Check
if [ $? -eq 0 ]; then
    echo ""
    echo "Build Finished Successfully."
    echo "Check 'logs/wf_build.log' for details."
else
    echo ""
    echo "Build Failed. Check 'logs/wf_build.log' for errors."
fi

# Keep the window open
read -p "Press any key to continue..."