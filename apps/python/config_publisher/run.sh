#!/bin/bash
# Run script for Config Publisher Application (Python)
# Publishes an AppConfig sample once on startup using ParameterQoS

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "=== Config Publisher (Python) ==="
echo

# --- NDDSHOME Auto-Detection ---
if [ -z "$NDDSHOME" ]; then
    LATEST_RTI=$(ls -d ~/rti_connext_dds-* 2>/dev/null | sort -V | tail -n 1)
    if [ -n "$LATEST_RTI" ] && [ -d "$LATEST_RTI" ]; then
        export NDDSHOME="$LATEST_RTI"
        echo "Found RTI installation: $NDDSHOME"
    else
        echo "ERROR: NDDSHOME not set and no RTI installation found."
        exit 1
    fi
fi

# --- Virtual Environment ---
VENV_DIR="$REPO_ROOT/connext_dds_env"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo "Activated virtual environment: $VENV_DIR"
else
    echo "WARNING: Virtual environment not found at $VENV_DIR"
    echo "Run apps/python/install.sh first."
    exit 1
fi

# --- Generate Python types if needed ---
PYTHON_GEN_DIR="$REPO_ROOT/dds/datamodel/python_gen"
if [ ! -d "$PYTHON_GEN_DIR/ExampleTypes" ]; then
    echo "Generating Python type support..."
    cd "$REPO_ROOT/dds/datamodel"
    rtiddsgen -language python -d python_gen/ idl/ExampleTypes.idl -replace
    rtiddsgen -language python -d python_gen/ idl/Definitions.idl -replace
    cd "$SCRIPT_DIR"
fi

# --- Run ---
echo "Starting config_publisher..."
python3 "$SCRIPT_DIR/config_publisher.py" "$@"
