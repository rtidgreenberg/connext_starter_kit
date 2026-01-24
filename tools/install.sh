#!/bin/bash
# Installation script for RTI Spy Tool
# Sets up virtual environment and installs dependencies

set -e  # Exit on any error

echo "=== RTI Spy Tool Setup ==="
echo

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_ROOT/connext_dds_env"

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

# --- Virtual Environment Setup ---
echo
if [ -d "$VENV_DIR" ]; then
    echo "✓ Virtual environment already exists at: $VENV_DIR"
else
    echo "Creating virtual environment at repository root..."
    python3 -m venv "$VENV_DIR"
    echo "✓ Virtual environment created at: $VENV_DIR"
fi

# Activate virtual environment
echo
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate" 2>/dev/null || true
export PATH="$VENV_DIR/bin:$PATH"
echo "✓ Virtual environment activated"

# Upgrade pip
echo
echo "Upgrading pip..."
pip install --upgrade pip

# --- Install Dependencies ---
echo
echo "Installing dependencies from requirements.txt..."
pip install -r "$SCRIPT_DIR/requirements.txt"
echo "✓ Dependencies installed successfully"

# Verify installations
echo
echo "Verifying installations..."
if python -c "import rti.connextdds" 2>/dev/null; then
    echo "✓ RTI Python API verification successful"
else
    echo "⚠️  WARNING: RTI Python API verification failed"
fi

if python -c "import textual; print('Textual version:', textual.__version__)" 2>/dev/null; then
    echo "✓ Textual verification successful"
else
    echo "⚠️  WARNING: Textual verification failed"
fi

# --- License File Check ---
echo
echo "Checking for RTI license file..."
if [ -n "$RTI_LICENSE_FILE" ] && [ -f "$RTI_LICENSE_FILE" ]; then
    echo "✓ RTI_LICENSE_FILE is set: $RTI_LICENSE_FILE"
elif [ -f "$NDDSHOME/rti_license.dat" ]; then
    echo "✓ Found license file at: $NDDSHOME/rti_license.dat"
else
    echo "⚠️  WARNING: No RTI license file found"
    echo ""
    echo "   RTI Spy requires a license file to run."
    echo "   Please either:"
    echo "     1. Set RTI_LICENSE_FILE environment variable"
    echo "     2. Place rti_license.dat in $NDDSHOME/"
fi

echo
echo "=== Installation Complete ==="
echo
echo "To run RTI Spy:"
echo "  ./run_rtispy.sh --domain 1"
echo ""
echo "The run script will automatically:"
echo "  - Detect NDDSHOME if not set"
echo "  - Validate license file"
echo "  - Activate the virtual environment"
echo
