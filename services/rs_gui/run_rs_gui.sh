#!/bin/bash
# Launcher for rs_gui.
# - Defaults to GUI mode
# - Ensures repo virtualenv Python exists
# - Synchronizes Python packages from requirements.txt
# - Auto-detects RTI license file
# - Optional DDS XML type preparation via setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$REPO_ROOT/connext_dds_env"
VENV_PYTHON="$REPO_ROOT/connext_dds_env/bin/python"
REQUIRED_PYTHON_BIN="python3.10"
REQUIRED_PYTHON_VERSION="3.10"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
APP_ENTRY="$SCRIPT_DIR/rs_gui_app.py"
PREFLIGHT_ENTRY="$SCRIPT_DIR/preflight.py"
PREPARE_DDS=false
SKIP_DIAGNOSTICS=false
DIAGNOSTICS_ONLY=false
REQUIRE_CONNEXT_DIAGNOSTICS=false
STEP_COUNTER=0

log_step() {
    STEP_COUNTER=$((STEP_COUNTER + 1))
    echo
    echo "[rs_gui][step ${STEP_COUNTER}] $*"
}

find_required_python() {
    if command -v "$REQUIRED_PYTHON_BIN" >/dev/null 2>&1; then
        command -v "$REQUIRED_PYTHON_BIN"
        return 0
    fi

    return 1
}

venv_python_version() {
    "$VENV_PYTHON" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
}

find_nddshome() {
    local preferred="$HOME/rti_connext_dds-7.7.0"
    local latest
    local dir

    if [[ -n "${NDDSHOME:-}" && -d "$NDDSHOME" ]]; then
        printf '%s\n' "$NDDSHOME"
        return 0
    fi

    if [[ -d "$preferred" ]]; then
        printf '%s\n' "$preferred"
        return 0
    fi

    latest=$(ls -d "$HOME"/rti_connext_dds-* 2>/dev/null | sort -V | tail -n 1 || true)
    if [[ -n "$latest" && -d "$latest" ]]; then
        printf '%s\n' "$latest"
        return 0
    fi

    for dir in /opt/rti_connext_dds-* /opt/rti/rti_connext_dds-*; do
        if [[ -d "$dir" ]]; then
            printf '%s\n' "$dir"
            return 0
        fi
    done

    return 1
}

ensure_venv() {
    log_step "Checking Python virtual environment"
    local required_python
    local current_version

    if ! required_python="$(find_required_python)"; then
        echo "ERROR: $REQUIRED_PYTHON_BIN is required to create $VENV_DIR."
        echo "Install Python $REQUIRED_PYTHON_VERSION and rerun the launcher."
        return 1
    fi

    if [[ ! -x "$VENV_PYTHON" ]]; then
        echo "Virtual environment not found at: $VENV_DIR"
        echo "Creating shared virtual environment with $REQUIRED_PYTHON_BIN..."
        "$required_python" -m venv "$VENV_DIR"
        echo "Created virtual environment: $VENV_DIR"
    else
        current_version="$(venv_python_version)"
        if [[ "$current_version" != "$REQUIRED_PYTHON_VERSION" ]]; then
            echo "Virtual environment uses Python $current_version; rebuilding with $REQUIRED_PYTHON_VERSION..."
            rm -rf "$VENV_DIR"
            "$required_python" -m venv "$VENV_DIR"
            echo "Rebuilt virtual environment: $VENV_DIR"
        else
            echo "Using virtual environment: $VENV_DIR"
        fi
    fi
}

ensure_connext_python() {
    log_step "Checking RTI Python package installation"
    local py_mm
    py_mm="$($VENV_PYTHON - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
    )"
    echo "Detected Python version: $py_mm"

    if [[ ! "$py_mm" =~ ^3\.(10|11|12|13)$ ]]; then
        echo "ERROR: Python $py_mm does not satisfy Connext 7.7 (requires >=3.10)."
        return 1
    fi

    echo "Synchronizing launcher dependencies from $REQUIREMENTS_FILE"
    "$VENV_PYTHON" -m pip install -v --progress-bar on -r "$REQUIREMENTS_FILE"

    set +e
    "$VENV_PYTHON" - <<'PY'
import sys

try:
    import rti.connextdds  # noqa: F401
except Exception:
    sys.exit(1)

sys.exit(0)
PY
    local status=$?
    set -e

    if [[ $status -ne 0 ]]; then
        echo "ERROR: Installed dependencies do not satisfy launcher requirements."
        return 1
    fi
}

resolve_license_file() {
    log_step "Resolving RTI license file"
    local candidate
    local dir

    if [[ -n "${RTI_LICENSE_FILE:-}" ]]; then
        if [[ -f "$RTI_LICENSE_FILE" ]]; then
            echo "Using RTI_LICENSE_FILE from environment: $RTI_LICENSE_FILE"
            return 0
        fi
        echo "WARNING: RTI_LICENSE_FILE is set but file is missing: $RTI_LICENSE_FILE"
    fi

    for candidate in \
        "$NDDSHOME/rti_license.dat" \
        "$NDDSHOME/rti_license.txt" \
        "$NDDSHOME/resource/rti_license.dat" \
        "$NDDSHOME/resource/licenses/rti_license.dat"; do
        if [[ -f "$candidate" ]]; then
            export RTI_LICENSE_FILE="$candidate"
            echo "Detected RTI license file: $RTI_LICENSE_FILE"
            return 0
        fi
    done

    for dir in "$HOME"/rti_connext_dds-* /opt/rti_connext_dds-* /opt/rti/rti_connext_dds-*; do
        if [[ -d "$dir" ]]; then
            for candidate in "$dir/rti_license.dat" "$dir/rti_license.txt"; do
                if [[ -f "$candidate" ]]; then
                    export RTI_LICENSE_FILE="$candidate"
                    echo "Detected RTI license file: $RTI_LICENSE_FILE"
                    return 0
                fi
            done
        fi
    done

    echo "ERROR: Unable to find an RTI license file automatically."
    echo "Please set RTI_LICENSE_FILE to a valid license file path and rerun."
    echo "Example: export RTI_LICENSE_FILE=/path/to/rti_license.dat"
    return 1
}

usage() {
    cat <<'EOF'
Usage: ./run_rs_gui.sh [launcher-options] [app-mode]

Launcher options:
    --prepare-dds        Run setup.sh before launch and require Connext checks
    --diagnostics-only   Run startup diagnostics, then exit
    --skip-diagnostics   Launch without startup diagnostics
    --debug              Keep debug logging enabled explicitly (default)
    --no-debug           Disable debug logging for this run

App modes:
    --gui                Launch the Tk Record/Replay shell (default)
    --mock-gui           Launch the Tk shell with explicit mock/demo data
    --mock-gui-check     Build mock GUI session-backed data, then exit
    --headless-check     Start and stop app core only, then exit

Examples:
./run_rs_gui.sh
./run_rs_gui.sh --mock-gui
./run_rs_gui.sh --mock-gui-check
./run_rs_gui.sh --headless-check
./run_rs_gui.sh --prepare-dds --gui
./run_rs_gui.sh --debug --prepare-dds --gui
./run_rs_gui.sh --no-debug --gui
./run_rs_gui.sh --diagnostics-only --gui
./run_rs_gui.sh --skip-diagnostics --gui
EOF
}

APP_ARGS=()
log_step "Parsing launcher arguments"
for arg in "$@"; do
    case "$arg" in
        --prepare-dds)
            PREPARE_DDS=true
            ;;
        --skip-diagnostics)
            SKIP_DIAGNOSTICS=true
            ;;
        --diagnostics-only)
            DIAGNOSTICS_ONLY=true
            ;;
        --debug)
            export RS_GUI_DEBUG=1
            ;;
        --no-debug)
            export RS_GUI_DEBUG=0
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            APP_ARGS+=("$arg")
            ;;
    esac
done

if [[ ${#APP_ARGS[@]} -eq 0 ]]; then
    APP_ARGS=(--gui)
fi

ensure_venv
ensure_connext_python

export PYTHONNOUSERSITE=1
export PATH="$(dirname "$VENV_PYTHON"):$PATH"

log_step "Resolving NDDSHOME"
if ! DETECTED_NDDSHOME="$(find_nddshome)"; then
    echo "ERROR: NDDSHOME is not set and no RTI Connext installation was found."
    echo "Install RTI Connext 7.7 and/or set NDDSHOME before launching rs_gui."
    exit 1
fi
export NDDSHOME="$DETECTED_NDDSHOME"
echo "Using NDDSHOME: $NDDSHOME"

if ! resolve_license_file; then
    exit 1
fi

# Work around VMware SVGA / Mesa driver issues that can cause GLFW segfaults
# when the hardware GL context fails to initialize properly.
if [[ -z "${LIBGL_ALWAYS_SOFTWARE:-}" ]]; then
    if lspci 2>/dev/null | grep -qi "VMware SVGA"; then
        export LIBGL_ALWAYS_SOFTWARE=1
    fi
fi

if [[ "$PREPARE_DDS" == true ]]; then
    log_step "Preparing DDS XML type artifacts"
    echo "Preparing DDS XML types using setup.sh..."
    bash "$SCRIPT_DIR/setup.sh"
    REQUIRE_CONNEXT_DIAGNOSTICS=true

    # Validate generated types metadata against the active NDDSHOME.
    if ! (cd "$SCRIPT_DIR" && "$VENV_PYTHON" - <<'PY'
import os
from app_core.connext_environment import detect_nddshome, validate_generated_types

xml_dir = os.path.join(os.getcwd(), "xml_types")
validate_generated_types(xml_dir, detect_nddshome())
print("DDS XML type metadata OK")
PY
    ); then
        echo "ERROR: Generated XML types validation failed. Rerun services/rs_gui/setup.sh."
        exit 1
    fi
fi

if [[ "$SKIP_DIAGNOSTICS" != true ]]; then
    log_step "Running startup diagnostics"
    PREFLIGHT_ARGS=()
    if [[ "$REQUIRE_CONNEXT_DIAGNOSTICS" == true ]]; then
        PREFLIGHT_ARGS+=(--require-connext)
    fi
    echo "Running startup diagnostics..."
    if ! "$VENV_PYTHON" "$PREFLIGHT_ENTRY" "${PREFLIGHT_ARGS[@]}"; then
        echo
        echo "ERROR: Startup diagnostics failed."
        echo "Use --skip-diagnostics to bypass checks temporarily."
        exit 1
    fi
fi

if [[ "$DIAGNOSTICS_ONLY" == true ]]; then
    log_step "Diagnostics-only mode complete"
    exit 0
fi

log_step "Launching rs_gui application"
cd "$SCRIPT_DIR"
exec "$VENV_PYTHON" "$APP_ENTRY" "${APP_ARGS[@]}"
