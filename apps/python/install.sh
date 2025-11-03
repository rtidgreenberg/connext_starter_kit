#!/bin/bash
# Installation script for Connext DDS Python Application
# Handles RTI Python API installation and package setup

set -e  # Exit on any error

echo "=== Connext DDS Python Application Setup ==="
echo

# Check if we're in a virtual environment and warn if not
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "⚠️  WARNING: No virtual environment detected"
    echo "   It's recommended to use a virtual environment to avoid package conflicts."
    echo "   To set up a virtual environment:"
    echo "     python3 -m venv connext_dds_env"
    echo "     source connext_dds_env/bin/activate"
    echo "     ./install.sh"
    echo
    read -p "Continue without virtual environment? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled. Please set up a virtual environment first."
        exit 1
    fi
else
    echo "✓ Virtual environment detected: $VIRTUAL_ENV"
fi

echo

# Check if NDDSHOME is set
if [ -z "$NDDSHOME" ]; then
    echo "ERROR: NDDSHOME environment variable not set"
    echo "Please set NDDSHOME to your RTI Connext DDS installation directory:"
    echo "  export NDDSHOME=/path/to/rti_connext_dds-7.3.0"
    exit 1
fi

echo "✓ NDDSHOME: $NDDSHOME"

# Check for RTI license file
echo
echo "Checking for RTI license file..."
if [ -f "rti_license.dat" ]; then
    echo "✓ Found rti_license.dat in current directory"
    echo "  RTI Connext DDS will automatically use this license file"
elif [ -n "$RTI_LICENSE_FILE" ] && [ -f "$RTI_LICENSE_FILE" ]; then
    echo "✓ RTI_LICENSE_FILE environment variable set: $RTI_LICENSE_FILE"
    if [ -f "$RTI_LICENSE_FILE" ]; then
        echo "  License file exists and will be used"
    else
        echo "⚠️  WARNING: RTI_LICENSE_FILE points to non-existent file: $RTI_LICENSE_FILE"
    fi
else
    echo "⚠️  WARNING: No rti_license.dat found in current directory"
    echo "   If your RTI installation requires a license file, copy it here:"
    echo "     cp /path/to/your/rti_license.dat ./rti_license.dat"
    echo "   Alternatively, set RTI_LICENSE_FILE environment variable:"
    echo "     export RTI_LICENSE_FILE=/path/to/your/rti_license.dat"
    echo "   If RTI is properly licensed system-wide, you can ignore this warning."
    echo
    read -p "Continue without license file in working directory? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled. Please copy your license file and run the script again."
        exit 1
    fi
fi

# Install RTI Python API
echo
echo "Installing RTI Connext Python API..."
pip install rti.connext==7.3.0
echo "✓ RTI Python API installed successfully"

# Verify installation
echo
echo "Verifying RTI Python API installation..."
if python -c "import rti.connextdds; print('RTI API version:', rti.connextdds.__version__)" 2>/dev/null; then
    echo "✓ RTI Python API verification successful"
else
    echo "WARNING: RTI Python API verification failed"
    echo "The API was installed but may not be working correctly"
fi

# Generate DDS bindings
echo
echo "Generating Python DDS bindings..."
make codegen
echo "✓ DDS bindings generated successfully"

# Install the package
echo
echo "Installing Python package in development mode..."
pip install -e .
echo "✓ Package installed successfully"

echo
echo "=== Installation Complete ==="
echo

echo "✓ Installation completed"
echo
echo "To run the example I/O application:"
echo "  cd example_io_app"
echo "  python example_io_app.py --domain_id 1 --verbosity 2"
echo
echo "Other useful commands:"
echo "  make run        - Run the application"
echo "  make clean      - Clean build artifacts"
echo "  make help       - Show all available commands"
echo