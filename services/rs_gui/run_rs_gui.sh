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
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
APP_ENTRY="$SCRIPT_DIR/rs_gui_app.py"
PREFLIGHT_ENTRY="$SCRIPT_DIR/preflight.py"
PREPARE_DDS=false
SKIP_DIAGNOSTICS=false
DIAGNOSTICS_ONLY=false
REQUIRE_CONNEXT_DIAGNOSTICS=false
source "$REPO_ROOT/scripts/python_env.sh"

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
python_env_init "rs_gui" "$REPO_ROOT"
python_env_log_step "Parsing launcher arguments"
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

python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_requirements "$REQUIREMENTS_FILE" "rti.connextdds:RTI Connext DDS Python API"

export PYTHONNOUSERSITE=1
export PATH="$PYTHON_ENV_VENV_DIR/bin:$PATH"
echo "Using NDDSHOME: $NDDSHOME"

if ! python_env_resolve_license_file; then
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
    python_env_log_step "Preparing DDS XML type artifacts"
    echo "Preparing DDS XML types using setup.sh..."
    bash "$SCRIPT_DIR/setup.sh"
    REQUIRE_CONNEXT_DIAGNOSTICS=true

    # Validate generated types metadata against the active NDDSHOME.
    if ! (cd "$SCRIPT_DIR" && "$PYTHON_ENV_VENV_PYTHON" - <<'PY'
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
    python_env_log_step "Running startup diagnostics"
    PREFLIGHT_ARGS=()
    if [[ "$REQUIRE_CONNEXT_DIAGNOSTICS" == true ]]; then
        PREFLIGHT_ARGS+=(--require-connext)
    fi
    echo "Running startup diagnostics..."
    if ! "$PYTHON_ENV_VENV_PYTHON" "$PREFLIGHT_ENTRY" "${PREFLIGHT_ARGS[@]}"; then
        echo
        echo "ERROR: Startup diagnostics failed."
        echo "Use --skip-diagnostics to bypass checks temporarily."
        exit 1
    fi
fi

if [[ "$DIAGNOSTICS_ONLY" == true ]]; then
    python_env_log_step "Diagnostics-only mode complete"
    exit 0
fi

python_env_log_step "Launching rs_gui application"
cd "$SCRIPT_DIR"
exec "$PYTHON_ENV_VENV_PYTHON" "$APP_ENTRY" "${APP_ARGS[@]}"
