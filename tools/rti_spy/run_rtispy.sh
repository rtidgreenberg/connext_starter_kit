#!/bin/bash
# Run script for RTI Spy Tool.

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TOOLS_DIR/.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

echo "=== RTI Spy Tool ==="
echo
python_env_init "rti_spy" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_requirements "$SCRIPT_DIR/requirements.txt" \
    "rti.connextdds:RTI Connext DDS Python API" \
    "textual:Textual"
python_env_resolve_license_file

# --- Run Application ---
echo
echo "Starting RTI Spy..."
echo "-------------------"
python "$SCRIPT_DIR/rtispy.py" "$@"
