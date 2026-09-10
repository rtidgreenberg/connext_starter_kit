#!/bin/bash
# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
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
python_env_sync_rti_connext
python_env_sync_requirements "$REQUIREMENTS_FILE" \
    "rti.connextdds:RTI Connext DDS Python API" \
    "dearpygui.dearpygui:Dear PyGui"
python_env_resolve_license_file

python_env_log_step "Launching rti_view"
echo "Starting rti_view..."
python -m rti_view "$@"
