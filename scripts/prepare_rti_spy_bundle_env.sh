#!/bin/bash
# Prepare the connected build environment used by build_rti_spy_bundle.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/rti_spy_bundle_common.sh"

usage() {
    cat <<'EOF'
Usage: ./scripts/prepare_rti_spy_bundle_env.sh --wheel PATH

Creates a Python environment for building the RTI Spy PyInstaller bundle. This command
requires network access for PyPI dependencies. The supplied RTI Python wheel is
installed locally and is never downloaded from PyPI.
EOF
}

wheel_path=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --wheel)
            wheel_path="${2:-}"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            rti_spy_bundle_die "unknown argument: $1"
            usage
            exit 2
            ;;
    esac
done

if [[ -z "$wheel_path" && -t 0 ]]; then
    read -r -p "Path to RTI Python wheel: " wheel_path
fi
[[ -n "$wheel_path" ]] || {
    usage
    exit 2
}

rti_spy_bundle_parse_wheel "$wheel_path"
python_bin="$(rti_spy_bundle_find_python)"
"$python_bin" - <<'PY' || {
import ctypes
import ctypes.util
import sys

library_name = ctypes.util.find_library(f"python{sys.version_info.major}.{sys.version_info.minor}")
if not library_name:
    raise SystemExit(1)
ctypes.CDLL(library_name)
PY
    rti_spy_bundle_die "PyInstaller requires the shared library for Python $RTI_SPY_BUNDLE_PYTHON_VERSION. Install the matching libpython package (for example: sudo apt install libpython3.9) and rerun."
    exit 1
}
venv_dir="$REPO_ROOT/build/rti_spy_bundle/venv-${RTI_SPY_BUNDLE_PYTHON_TAG}"
venv_python="$venv_dir/bin/python"

if [[ ! -x "$venv_python" ]]; then
    "$python_bin" -m venv "$venv_dir"
fi

"$venv_python" -m pip install --upgrade pip
"$venv_python" -m pip install -r "$REPO_ROOT/tools/rti_spy/requirements.txt" PyInstaller
"$venv_python" -m pip install --no-deps "$RTI_SPY_BUNDLE_WHEEL_PATH"

mkdir -p "$REPO_ROOT/build/rti_spy_bundle"
printf '%s\n' "$RTI_SPY_BUNDLE_WHEEL_PATH" > "$REPO_ROOT/build/rti_spy_bundle/prepared-wheel-path"

echo "Prepared RTI Spy bundle environment: $venv_dir"
echo "Connext: $RTI_SPY_BUNDLE_CONNEXT_VERSION; Python: $RTI_SPY_BUNDLE_PYTHON_VERSION"