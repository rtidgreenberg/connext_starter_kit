#!/bin/bash
# Installation script for RTI Spy Tool.

set -euo pipefail

echo "=== RTI Spy Tool Setup ==="
echo

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$REPO_ROOT/connext_dds_env"
source "$REPO_ROOT/scripts/python_env.sh"

python_env_init "rti_spy_install" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_requirements "$SCRIPT_DIR/requirements.txt" \
    "rti.connextdds:RTI Connext DDS Python API" \
    "textual:Textual"

# --- License File Check ---
if ! python_env_resolve_license_file; then
    echo "⚠️  WARNING: No RTI license file found"
    echo ""
    echo "   RTI Spy requires a license file to run."
    echo "   Please either:"
    echo "     1. Set RTI_LICENSE_FILE environment variable"
    echo "     2. Place rti_license.dat in $NDDSHOME/"
fi

echo
echo "=== Installation Complete ==="
echo
echo "To run RTI Spy:"
echo "  ./tools/rti_spy/run_rtispy.sh --domain 1"
echo ""
echo "The run script will automatically:"
echo "  - Detect NDDSHOME if not set"
echo "  - Validate license file"
echo "  - Activate the virtual environment"
echo
