#!/bin/bash
# Run script for Recording Service GUI
# Handles environment setup and launches the GUI application

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PREFERRED_CONNEXT_VERSION="${PREFERRED_CONNEXT_VERSION:-7.6.0}"

echo "=== Recording Service GUI ==="
echo

# --- NDDSHOME Auto-Detection ---
if [ -z "$NDDSHOME" ]; then
    echo "NDDSHOME not set. Searching for RTI Connext installation..."
    PREFERRED_RTI="$HOME/rti_connext_dds-$PREFERRED_CONNEXT_VERSION"
    if [ -d "$PREFERRED_RTI" ]; then
        LATEST_RTI="$PREFERRED_RTI"
    else
        LATEST_RTI=$(ls -d ~/rti_connext_dds-* 2>/dev/null | sort -V | tail -n 1)
    fi

    if [ -n "$LATEST_RTI" ] && [ -d "$LATEST_RTI" ]; then
        export NDDSHOME="$LATEST_RTI"
        echo "✓ Found RTI installation: $NDDSHOME"
    else
        echo "ERROR: NDDSHOME not set and no RTI installation found in ~/rti_connext_dds-*"
        exit 1
    fi
else
    echo "✓ NDDSHOME: $NDDSHOME"
fi

# --- License File Validation ---
echo
echo "Checking for RTI license file..."
LICENSE_FOUND=false

if [ -n "$RTI_LICENSE_FILE" ] && [ -f "$RTI_LICENSE_FILE" ]; then
    echo "✓ Using license from RTI_LICENSE_FILE: $RTI_LICENSE_FILE"
    LICENSE_FOUND=true
elif [ -f "$NDDSHOME/rti_license.dat" ]; then
    export RTI_LICENSE_FILE="$NDDSHOME/rti_license.dat"
    echo "✓ Using license from NDDSHOME: $RTI_LICENSE_FILE"
    LICENSE_FOUND=true
elif [ -f "$HOME/.rti/rti_license.dat" ]; then
    export RTI_LICENSE_FILE="$HOME/.rti/rti_license.dat"
    echo "✓ Using license from ~/.rti: $RTI_LICENSE_FILE"
    LICENSE_FOUND=true
elif [ -f "$HOME/rti_license.dat" ]; then
    export RTI_LICENSE_FILE="$HOME/rti_license.dat"
    echo "✓ Using license from home directory: $RTI_LICENSE_FILE"
    LICENSE_FOUND=true
fi

if [ "$LICENSE_FOUND" = false ]; then
    echo "ERROR: RTI license file not found."
    echo "Please set RTI_LICENSE_FILE or place rti_license.dat in \$NDDSHOME, ~/.rti, or your home directory."
    exit 1
fi

# --- Virtual Environment ---
echo
VENV_DIR="$REPO_ROOT/connext_dds_env"
if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Run apps/python/install.sh first."
    exit 1
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate" 2>/dev/null || true
export PATH="$VENV_DIR/bin:$PATH"
export PYTHONNOUSERSITE=1
PYTHON_BIN="$VENV_DIR/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    echo "ERROR: Python interpreter not found: $PYTHON_BIN"
    exit 1
fi
echo "✓ Virtual environment activated"

# --- Check generated type files ---
echo
XML_DIR="$SCRIPT_DIR/xml_types"
NEED_SETUP=false
if [ ! -f "$XML_DIR/ServiceAdmin.xml" ] || [ ! -f "$XML_DIR/RecordingServiceTypes.xml" ] || \
    [ ! -f "$XML_DIR/ServiceMonitoring.xml" ] || [ ! -f "$XML_DIR/.generated_from_nddshome" ]; then
    NEED_SETUP=true
elif ! SCRIPT_DIR="$SCRIPT_DIR" PYTHONPATH="$SCRIPT_DIR" "$PYTHON_BIN" - <<'PY'
import os
import sys
from recording_service_environment import validate_generated_types
try:
    validate_generated_types(os.path.join(os.environ["SCRIPT_DIR"], "xml_types"))
except Exception:
    sys.exit(1)
PY
then
    NEED_SETUP=true
fi

if [ "$NEED_SETUP" = true ]; then
    echo "Generated type files missing or stale. Running setup.sh..."
    echo
    bash "$SCRIPT_DIR/setup.sh"
    echo
fi
echo "✓ Generated type files found"

# --- Run GUI ---
echo
echo "Starting Recording Service GUI..."
echo "-----------------------------------"
cd "$SCRIPT_DIR"
"$PYTHON_BIN" recording_service_gui.py "$@"
