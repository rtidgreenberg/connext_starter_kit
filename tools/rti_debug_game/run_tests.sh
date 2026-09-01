#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"
python_env_init "rti_debug_game" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv

cd "$REPO_ROOT"
PYTHONPATH="tools/rti_debug_game${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_ENV_VENV_PYTHON" -m unittest tools.rti_debug_game.test.test_generator -v