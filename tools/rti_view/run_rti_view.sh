#!/bin/bash
# Run script for rti_view.
# Handles environment setup and executes the Dear PyGui application.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
source "$REPO_ROOT/scripts/python_env.sh"

echo "=== rti_view ==="
echo

python_env_init "rti_view" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
python_env_sync_requirements "$REQUIREMENTS_FILE" \
    "rti.connextdds:RTI Connext DDS Python API" \
    "dearpygui.dearpygui:Dear PyGui"
python_env_resolve_license_file

python_env_log_step "Launching rti_view"
echo "Starting rti_view..."
python -m rti_view "$@"
