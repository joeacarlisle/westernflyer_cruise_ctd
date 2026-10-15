#!/bin/bash
# Convenience wrapper for the 2026_PNW cruise (Pacific Northwest 2026).
# Other cruises: ./ctd_build.sh <cruise_id>
exec "$(dirname "$0")/ctd_build.sh" 2026_PNW "$@"
