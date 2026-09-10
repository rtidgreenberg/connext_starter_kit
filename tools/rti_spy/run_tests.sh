#!/bin/bash
# Run RTI Spy tests with the repository's resolved Connext 7.7 environment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$REPO_ROOT/scripts/python_env.sh"

python_env_init "rti_spy tests" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_rti_connext
python_env_sync_requirements "$SCRIPT_DIR/requirements.txt" "rti.connextdds:RTI Connext DDS Python API"

export PYTHONNOUSERSITE=1
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

case "${1:-all}" in
	startup)
		pattern="test_startup_live.py"
		;;
	live)
		pattern="test_live_e2e_integration.py"
		;;
	all)
		pattern="test_*.py"
		;;
	*)
		echo "Usage: $0 [startup|live|all]" >&2
		exit 2
		;;
esac

exec "$PYTHON_ENV_VENV_PYTHON" -m unittest discover -s "$SCRIPT_DIR/test" -p "$pattern"