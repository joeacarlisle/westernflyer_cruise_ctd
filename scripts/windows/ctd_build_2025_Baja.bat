@echo off
REM Convenience wrapper for the 2025_Baja cruise (Baja California 2025).
REM Builds with --source all (raw plus any cnv_* folders), set in ctd_build; add --source raw for raw only.
REM Other cruises: ctd_build.bat ^<cruise_id^>
call "%~dp0ctd_build.bat" 2025_Baja %*
