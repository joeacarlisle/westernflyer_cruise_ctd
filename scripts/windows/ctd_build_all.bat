@echo off
setlocal EnableDelayedExpansion
REM Rebuild every cruise under cruises\ into the DuckDB database, one after another.
REM Usage:   ctd_build_all.bat [extra args forwarded to main.py, e.g. --bin-size 0.5]
REM Builds with --source all: raw .hex data plus any SeaSoft-processed folders
REM (cnv_downcast, cnv_upcast, cnv_fullcast) that a cruise has. Cruises without
REM processed folders build raw only. Pass --source raw to build raw data only.
REM Each cruise is a folder under cruises\ whose name is the cruise ID.
REM Add a new cruise by creating its folder; no edit to this script is needed.

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\.."

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [WARNING] Virtual environment not found at .venv\Scripts\activate.bat
)

set "FAILED="
for /d %%C in (cruises\*) do (
    echo.
    echo ===== Building %%~nxC =====
    python main.py %%~nxC --source all %*
    if errorlevel 1 set "FAILED=!FAILED! %%~nxC"
)

echo.
if defined FAILED (
    echo Build finished with failures:!FAILED!
    echo Check the newest files in logs\.
) else (
    echo All cruises built successfully.
)

popd
pause
