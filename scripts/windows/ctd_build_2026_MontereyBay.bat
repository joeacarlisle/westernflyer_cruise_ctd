@echo off
REM Convenience wrapper for the 2026_MontereyBay cruise (Monterey Bay 2026).
REM Builds with --source all (raw plus any cnv_* folders), set in ctd_build; add --source raw for raw only.
REM Other cruises: ctd_build.bat ^<cruise_id^>
call "%~dp0ctd_build.bat" 2026_MontereyBay %*
