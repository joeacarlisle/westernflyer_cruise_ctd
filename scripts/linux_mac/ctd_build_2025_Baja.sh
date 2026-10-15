#!/bin/bash
# Convenience wrapper for the 2025_Baja cruise (Baja California 2025).
# Other cruises: ./ctd_build.sh <cruise_id>
exec "$(dirname "$0")/ctd_build.sh" 2025_Baja "$@"
