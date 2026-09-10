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
python_env_sync_rti_connext
python_env_sync_requirements "$SCRIPT_DIR/requirements.txt" \
    "rti.connextdds:RTI Connext DDS Python API" \
    "textual:Textual"
python_env_resolve_license_file

# --- Run Application ---
echo
echo "Starting RTI Spy..."
echo "-------------------"
python "$SCRIPT_DIR/rtispy.py" "$@"
