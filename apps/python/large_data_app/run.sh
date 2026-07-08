#!/bin/bash
# Run script for Large Data Application (Python).

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

echo "=== Large Data Application (Python) ==="
echo
python_env_init "large_data_app" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_requirements "$REPO_ROOT/apps/python/requirements.txt" "rti.connextdds:RTI Connext DDS Python API"
python_env_resolve_license_file

# --- Check for Python Bindings ---
echo
BINDINGS_FILE="$REPO_ROOT/build/dds/python_gen/ExampleTypes.py"
if [ ! -f "$BINDINGS_FILE" ]; then
    echo "Python bindings not found. Running install script..."
    echo ""
    
    "$REPO_ROOT/apps/python/install.sh"
    
    if [ ! -f "$BINDINGS_FILE" ]; then
        echo "ERROR: Failed to generate Python bindings."
        echo "Please check install script output for errors."
        exit 1
    fi
else
    echo "✓ Python bindings found"
fi

# --- Run Application ---
echo
echo "Starting Large Data Application..."
echo "----------------------------------"
export PYTHONPATH="$REPO_ROOT/build/dds${PYTHONPATH:+:$PYTHONPATH}"
cd "$SCRIPT_DIR"
python large_data_app.py "$@"
