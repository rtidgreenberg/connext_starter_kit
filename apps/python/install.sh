#!/bin/bash
# Installation script for Connext DDS Python Applications
# Sets up virtual environment and installs dependencies

set -e  # Exit on any error

echo "=== Connext DDS Python Application Setup ==="
echo

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
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

# Verify RTI installation
echo
echo "Verifying RTI Python API installation..."
if python -c "import rti.connextdds" 2>/dev/null; then
    echo "✓ RTI Python API verification successful"
else
    echo "⚠️  WARNING: RTI Python API verification failed"
    echo "   The API was installed but may not be working correctly"
fi

# --- Generate Python Bindings if Missing ---
echo
BINDINGS_FILE="$REPO_ROOT/build/dds/python_gen/ExampleTypes.py"
if [ ! -f "$BINDINGS_FILE" ]; then
    echo "Python bindings not found. Running top-level cmake build..."
    echo ""
    
    mkdir -p "$REPO_ROOT/build"
    cd "$REPO_ROOT/build"
    cmake ..
    cmake --build .
    cd "$SCRIPT_DIR"
    
    if [ ! -f "$BINDINGS_FILE" ]; then
        echo "⚠️  WARNING: Failed to generate Python bindings."
        echo "   Please check cmake build output for errors."
        echo "   You may need to set CONNEXTDDS_ARCH for C++ builds."
    else
        echo "✓ Python bindings generated successfully"
    fi
else
    echo "✓ Python bindings already exist"
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
    echo "   Python applications require a license file to run."
    echo "   Please either:"
    echo "     1. Set RTI_LICENSE_FILE environment variable"
    echo "     2. Place rti_license.dat in $NDDSHOME/"
fi

echo
echo "=== Installation Complete ==="
echo
echo "To run Python applications, use the run.sh script in each app directory:"
echo ""
echo "  Example I/O App:"
echo "    cd $SCRIPT_DIR/example_io_app"
echo "    ./run.sh --domain_id 1"
echo ""
echo "  Large Data App:"
echo "    cd $SCRIPT_DIR/large_data_app"
echo "    ./run.sh --domain_id 1"
echo ""
echo "  Downsampled Reader:"
echo "    cd $SCRIPT_DIR/downsampled_reader"
echo "    ./run.sh --domain_id 1"
echo ""
echo "The run.sh scripts will automatically:"
echo "  - Detect NDDSHOME if not set"
echo "  - Validate license file"
echo "  - Activate the virtual environment"
echo "  - Build Python bindings if missing"
echo