#!/bin/bash
# Run script for Downsampled Reader Application (Python)
# Handles environment setup and executes the application

set -e  # Exit on any error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "=== Downsampled Reader Application (Python) ==="
echo

# --- NDDSHOME Auto-Detection ---
if [ -z "$NDDSHOME" ]; then
    echo "NDDSHOME not set. Searching for RTI Connext installation..."
    
    # Find latest version in ~/rti_connext_dds-*
    LATEST_RTI=$(ls -d ~/rti_connext_dds-* 2>/dev/null | sort -V | tail -n 1)
    
    if [ -n "$LATEST_RTI" ] && [ -d "$LATEST_RTI" ]; then
        export NDDSHOME="$LATEST_RTI"
        echo "✓ Found RTI installation: $NDDSHOME"
    else
        echo "ERROR: NDDSHOME not set and no RTI installation found in ~/rti_connext_dds-*"
        echo ""
        echo "Please either:"
        echo "  1. Set NDDSHOME environment variable:"
        echo "     export NDDSHOME=/path/to/rti_connext_dds-x.x.x"
        echo ""
        echo "  2. Install RTI Connext DDS in your home directory"
        echo ""
        exit 1
    fi
else
    echo "✓ NDDSHOME: $NDDSHOME"
fi

# --- License File Validation (Required for Python) ---
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
    echo ""
    echo "Please either:"
    echo "  1. Set RTI_LICENSE_FILE environment variable:"
    echo "     export RTI_LICENSE_FILE=/path/to/rti_license.dat"
    echo ""
    echo "  2. Place rti_license.dat in \$NDDSHOME:"
    echo "     cp /path/to/rti_license.dat $NDDSHOME/"
    echo ""
    exit 1
fi

# --- Virtual Environment Activation ---
echo
VENV_DIR="$REPO_ROOT/connext_dds_env"
if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Running install script..."
    echo ""
    
    "$REPO_ROOT/apps/python/install.sh"
    
    if [ ! -d "$VENV_DIR" ]; then
        echo "ERROR: Failed to create virtual environment."
        echo "Please check install script output for errors."
        exit 1
    fi
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate" 2>/dev/null || true
export PATH="$VENV_DIR/bin:$PATH"
echo "✓ Virtual environment activated"

# --- Check for Python Bindings ---
echo
BINDINGS_FILE="$REPO_ROOT/dds/build/python_gen/ExampleTypes.py"
if [ ! -f "$BINDINGS_FILE" ]; then
    echo "Python bindings not found. Running install script..."
    echo ""
    
    "$REPO_ROOT/apps/python/install.sh"
    
    if [ ! -f "$BINDINGS_FILE" ]; then
        echo "ERROR: Failed to generate Python bindings."
        echo "Please check install script output for errors."
        exit 1
    fi
else
    echo "✓ Python bindings found"
fi

# --- Run Application ---
echo
echo "Starting Downsampled Reader Application..."
echo "------------------------------------------"
export PYTHONPATH="$REPO_ROOT/dds/build:$PYTHONPATH"
cd "$SCRIPT_DIR"
python downsampled_reader.py "$@"
