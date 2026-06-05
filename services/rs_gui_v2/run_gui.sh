#!/bin/bash
# Launcher for rs_gui_v2.
# - Defaults to GUI mode
# - Uses repo virtualenv Python
# - Optional DDS XML type preparation via setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PYTHON="$REPO_ROOT/connext_dds_env/bin/python"
APP_ENTRY="$SCRIPT_DIR/rs_gui_v2_app.py"
PREFLIGHT_ENTRY="$SCRIPT_DIR/preflight.py"
PREPARE_DDS=false
SKIP_DIAGNOSTICS=false
DIAGNOSTICS_ONLY=false
REQUIRE_CONNEXT_DIAGNOSTICS=false

usage() {
    cat <<'EOF'
Usage: ./run_gui.sh [launcher-options] [app-mode]

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
./run_gui.sh
./run_gui.sh --mock-gui
./run_gui.sh --mock-gui-check
./run_gui.sh --headless-check
./run_gui.sh --prepare-dds --gui
./run_gui.sh --debug --prepare-dds --gui
./run_gui.sh --no-debug --gui
./run_gui.sh --diagnostics-only --gui
./run_gui.sh --skip-diagnostics --gui
EOF
}

APP_ARGS=()
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

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: Python interpreter not found: $VENV_PYTHON"
    echo "Run apps/python/install.sh first."
    exit 1
fi

export PYTHONNOUSERSITE=1
export PATH="$(dirname "$VENV_PYTHON"):$PATH"

# Pin NDDSHOME to 7.6.0 — the minimum version for RS GUI admin/monitoring.
export NDDSHOME="${NDDSHOME:-/home/rti/rti_connext_dds-7.6.0}"

# Work around VMware SVGA / Mesa driver issues that can cause GLFW segfaults
# when the hardware GL context fails to initialize properly.
if [[ -z "${LIBGL_ALWAYS_SOFTWARE:-}" ]]; then
    if lspci 2>/dev/null | grep -qi "VMware SVGA"; then
        export LIBGL_ALWAYS_SOFTWARE=1
    fi
fi

if [[ "$PREPARE_DDS" == true ]]; then
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
        echo "ERROR: Generated XML types validation failed. Rerun services/rs_gui_v2/setup.sh."
        exit 1
    fi
fi

if [[ "$SKIP_DIAGNOSTICS" != true ]]; then
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
    exit 0
fi

cd "$SCRIPT_DIR"
exec "$VENV_PYTHON" "$APP_ENTRY" "${APP_ARGS[@]}"
