#!/bin/bash
# Convenience wrapper for the 2026_MontereyBay cruise (Monterey Bay 2026).
# Builds with --source all (raw plus any cnv_* folders), set in ctd_build; add --source raw for raw only.
# Other cruises: ./ctd_build.sh <cruise_id>
exec "$(dirname "$0")/ctd_build.sh" 2026_MontereyBay "$@"
