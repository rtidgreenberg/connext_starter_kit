#!/bin/bash
# Prepare the connected build environment used by build_rti_doctor_bundle.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/rti_doctor_bundle_common.sh"

usage() {
    cat <<'EOF'
Usage: ./scripts/prepare_rti_doctor_bundle_env.sh --wheel PATH

Creates a Python environment for building the RTI Doctor PyInstaller bundle.
This command requires network access for PyPI dependencies. The supplied RTI
Python wheel is installed locally and is never downloaded from PyPI.
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
            rti_doctor_bundle_die "unknown argument: $1"
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

rti_doctor_bundle_parse_wheel "$wheel_path"
python_bin="$(rti_doctor_bundle_find_python)"
"$python_bin" - <<'PY' || {
import ctypes
import ctypes.util
import sys

library_name = ctypes.util.find_library(f"python{sys.version_info.major}.{sys.version_info.minor}")
if not library_name:
    raise SystemExit(1)
ctypes.CDLL(library_name)
PY
    rti_doctor_bundle_die "PyInstaller requires the shared library for Python $RTI_DOCTOR_BUNDLE_PYTHON_VERSION. Install the matching libpython package and rerun."
    exit 1
}

venv_dir="$REPO_ROOT/build/rti_doctor_bundle/venv-${RTI_DOCTOR_BUNDLE_PYTHON_TAG}"
venv_python="$venv_dir/bin/python"
if [[ ! -x "$venv_python" ]]; then
    "$python_bin" -m venv "$venv_dir"
fi

"$venv_python" -m pip install --upgrade pip
"$venv_python" -m pip install -r "$REPO_ROOT/tools/rti_doctor/requirements.txt" PyInstaller
"$venv_python" -m pip install --no-deps "$RTI_DOCTOR_BUNDLE_WHEEL_PATH"

mkdir -p "$REPO_ROOT/build/rti_doctor_bundle"
printf '%s\n' "$RTI_DOCTOR_BUNDLE_WHEEL_PATH" > "$REPO_ROOT/build/rti_doctor_bundle/prepared-wheel-path"

echo "Prepared RTI Doctor bundle environment: $venv_dir"
echo "Connext: $RTI_DOCTOR_BUNDLE_CONNEXT_VERSION; Python: $RTI_DOCTOR_BUNDLE_PYTHON_VERSION"