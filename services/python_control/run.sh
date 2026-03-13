#!/bin/bash
# Run script for Recording Service Remote Control (Python)
# Handles environment setup and executes the control application

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Recording Service Remote Control (Python) ==="
echo

# --- NDDSHOME Auto-Detection ---
if [ -z "$NDDSHOME" ]; then
    echo "NDDSHOME not set. Searching for RTI Connext installation..."
    LATEST_RTI=$(ls -d ~/rti_connext_dds-* 2>/dev/null | sort -V | tail -n 1)

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
fi

if [ "$LICENSE_FOUND" = false ]; then
    echo "ERROR: RTI license file not found."
    echo "Please set RTI_LICENSE_FILE or place rti_license.dat in \$NDDSHOME"
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
echo "✓ Virtual environment activated"

# --- Check XML type files ---
echo
XML_DIR="$SCRIPT_DIR/xml_types"
if [ ! -f "$XML_DIR/ServiceAdmin.xml" ] || [ ! -f "$XML_DIR/RecordingServiceTypes.xml" ]; then
    echo "XML type files not found. Running setup.sh..."
    echo
    bash "$SCRIPT_DIR/setup.sh"
    echo
fi
echo "✓ XML type files found"

# --- Run ---
echo
echo "Starting Recording Service Remote Control..."
echo "----------------------------------------------"
cd "$SCRIPT_DIR"
python3 recording_service_control.py "$@"
