#!/bin/bash
# Run script for rti_view.
# Handles environment setup and executes the Dear PyGui application.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$REPO_ROOT/connext_dds_env"

echo "=== rti_view ==="
echo

if [ -z "$NDDSHOME" ]; then
    echo "NDDSHOME not set. Searching for RTI Connext installation..."
    LATEST_RTI=$(ls -d ~/rti_connext_dds-* 2>/dev/null | sort -V | tail -n 1)
    if [ -n "$LATEST_RTI" ] && [ -d "$LATEST_RTI" ]; then
        export NDDSHOME="$LATEST_RTI"
        echo "Found RTI installation: $NDDSHOME"
    else
        echo "ERROR: NDDSHOME not set and no RTI installation found in ~/rti_connext_dds-*"
        exit 1
    fi
else
    echo "NDDSHOME: $NDDSHOME"
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found at: $VENV_DIR"
    echo "Creating shared virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate" 2>/dev/null || true
export PATH="$VENV_DIR/bin:$PATH"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

if ! python -c "import dearpygui.dearpygui; import rti.connextdds" 2>/dev/null; then
    echo "Installing rti_view dependencies..."
    pip install -r "$SCRIPT_DIR/requirements.txt"
fi

echo "Starting rti_view..."
python -m rti_view "$@"
