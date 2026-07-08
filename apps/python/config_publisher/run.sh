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
python_env_ensure_versioned_types

# --- Run ---
echo "Starting config_publisher..."
python "$SCRIPT_DIR/config_publisher.py" "$@"
