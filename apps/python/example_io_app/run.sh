#!/bin/bash
# Run script for Example I/O Application (Python).

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

echo "=== Example I/O Application (Python) ==="
echo
python_env_init "example_io_app" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_requirements "$REPO_ROOT/apps/python/requirements.txt" "rti.connextdds:RTI Connext DDS Python API"
python_env_resolve_license_file
python_env_ensure_versioned_types

# --- Run Application ---
echo
echo "Starting Example I/O Application..."
echo "-----------------------------------"
cd "$SCRIPT_DIR"
python example_io_app.py "$@"
