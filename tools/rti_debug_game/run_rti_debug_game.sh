#!/bin/bash
# Run the DDS Debug Game with the repository Python environment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

python_env_init "rti_debug_game" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_rti_connext
python_env_sync_requirements "$SCRIPT_DIR/requirements.txt" \
    "rti.connextdds:RTI Connext DDS Python API" \
    "textual:Textual"
python_env_resolve_license_file

PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" python -m rti_debug_game "$@"
