#!/bin/bash
# Installation script for RTI Spy Tool
# Sets up virtual environment and installs dependencies

set -e  # Exit on any error

echo "=== RTI Spy Tool Setup ==="
echo

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/rtispy_env"

# Check if virtual environment already exists
if [ -d "$VENV_DIR" ]; then
    echo "Virtual environment already exists at: $VENV_DIR"
    read -p "Remove and recreate? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing existing virtual environment..."
        rm -rf "$VENV_DIR"
    else
        echo "Using existing virtual environment"
    fi
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "✓ Virtual environment created at: $VENV_DIR"
fi

# Activate virtual environment
echo
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"
echo "✓ Virtual environment activated"

# Check if NDDSHOME is set
echo
if [ -z "$NDDSHOME" ]; then
    echo "⚠️  WARNING: NDDSHOME environment variable not set"
    echo "   RTI Connext DDS environment should be set up before running rtispy."
    echo ""
    echo "   To set up the RTI Connext environment, run:"
    echo "     source <path_to_connext>/resource/scripts/rtisetenv_<architecture>.bash"
    echo ""
    echo "   Example:"
    echo "     source /opt/rti_connext_dds-7.3.0/resource/scripts/rtisetenv_x64Linux4gcc7.3.0.bash"
    echo ""
    echo "   This script will set NDDSHOME, update PATH, and configure LD_LIBRARY_PATH."
    echo
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled. Please set up RTI Connext environment first."
        exit 1
    fi
else
    echo "✓ NDDSHOME: $NDDSHOME"
fi

# Upgrade pip
echo
echo "Upgrading pip..."
pip install --upgrade pip

# Install RTI Python API
echo
echo "Installing RTI Connext Python API..."
pip install rti.connext==7.3.0
echo "✓ RTI Python API installed successfully"

# Install Textual and dependencies
echo
echo "Installing Textual UI framework..."
pip install textual textual-dev
echo "✓ Textual installed successfully"

# Verify installation
echo
echo "Verifying installations..."
if python -c "import rti.connextdds; print('RTI API version:', rti.connextdds.__version__)" 2>/dev/null; then
    echo "✓ RTI Python API verification successful"
else
    echo "⚠️  WARNING: RTI Python API verification failed"
    echo "   The API was installed but may not be working correctly"
fi

if python -c "import textual; print('Textual version:', textual.__version__)" 2>/dev/null; then
    echo "✓ Textual verification successful"
else
    echo "⚠️  WARNING: Textual verification failed"
fi

# Check for RTI license file
echo
echo "Checking for RTI license file..."
if [ -f "$SCRIPT_DIR/rti_license.dat" ]; then
    echo "✓ Found rti_license.dat in tools directory"
elif [ -n "$RTI_LICENSE_FILE" ] && [ -f "$RTI_LICENSE_FILE" ]; then
    echo "✓ RTI_LICENSE_FILE environment variable set: $RTI_LICENSE_FILE"
else
    echo "⚠️  WARNING: No rti_license.dat found"
    echo ""
    echo "   If your RTI installation requires a license file, you have two options:"
    echo ""
    echo "   Option 1: Copy license file to this directory"
    echo "     cp /path/to/your/rti_license.dat $SCRIPT_DIR/rti_license.dat"
    echo ""
    echo "   Option 2: Set RTI_LICENSE_FILE environment variable"
    echo "     export RTI_LICENSE_FILE=/path/to/your/rti_license.dat"
    echo ""
fi

echo
echo "=== Installation Complete ==="
echo
echo "To run RTI Spy:"
echo "  source $VENV_DIR/bin/activate"
if [ -n "$NDDSHOME" ]; then
    echo "  source \$NDDSHOME/resource/scripts/rtisetenv_<architecture>.bash"
fi
echo "  python $SCRIPT_DIR/rtispy.py --domain 1"
echo
echo "Or use the provided run script:"
echo "  ./run_rtispy.sh --domain 1"
echo
