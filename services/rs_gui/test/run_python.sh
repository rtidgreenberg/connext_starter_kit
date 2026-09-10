#!/bin/bash
# Run an rs_gui Python script with the repository's resolved Connext 7.7 environment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/../.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

python_env_init "rs_gui tests" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv

export PYTHONNOUSERSITE=1
exec "$PYTHON_ENV_VENV_PYTHON" "$@"