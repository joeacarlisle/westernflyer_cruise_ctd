@echo off
:: Move to the project root (up two levels from where this script is located/)
pushd "%~dp0..\.."

:: Activate the virtual environment
call .venv\Scripts\activate.bat

:: Clear old build logs to ensure a fresh audit trail
if exist "logs\wf_build.log" del "logs\wf_build.log"

:: Run the master pipeline for Baja 2025
echo Starting Baja 2025 Pipeline...
python main.py baja2025

:: Status Check
if %ERRORLEVEL% EQU 0 (
    echo.
    echo Pipeline Finished Successfully.
    echo Check 'logs\wf_build.log' for details.
) else (
    echo.
    echo Pipeline Failed. Check 'logs\wf_build.log' for errors.
)

popd
pause