#!/bin/bash
# Run script for Config Publisher Application (Python).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

echo "=== Config Publisher (Python) ==="
echo
python_env_init "config_publisher" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_requirements "$REPO_ROOT/apps/python/requirements.txt" "rti.connextdds:RTI Connext DDS Python API"
python_env_resolve_license_file

# --- Generate Python types if needed ---
PYTHON_GEN_DIR="$REPO_ROOT/dds/datamodel/python_gen"
if [ ! -d "$PYTHON_GEN_DIR/ExampleTypes" ]; then
    echo "Generating Python type support..."
    cd "$REPO_ROOT/dds/datamodel"
    rtiddsgen -language python -d python_gen/ idl/ExampleTypes.idl -replace
    rtiddsgen -language python -d python_gen/ idl/Definitions.idl -replace
    cd "$SCRIPT_DIR"
fi

# --- Run ---
echo "Starting config_publisher..."
python "$SCRIPT_DIR/config_publisher.py" "$@"
