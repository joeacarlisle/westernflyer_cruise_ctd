@echo off
REM Convenience wrapper for the 2026_PNW cruise (Pacific Northwest 2026).
REM Other cruises: ctd_build.bat ^<cruise_id^>
call "%~dp0ctd_build.bat" 2026_PNW %*
