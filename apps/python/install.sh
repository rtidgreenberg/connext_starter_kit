#!/bin/bash
# Installation script for Connext DDS Python Applications.

set -euo pipefail

echo "=== Connext DDS Python Application Setup ==="
echo

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$REPO_ROOT/connext_dds_env"
source "$REPO_ROOT/scripts/python_env.sh"

python_env_init "apps_python_install" "$REPO_ROOT"
python_env_resolve_nddshome
python_env_ensure_venv
python_env_activate_venv
python_env_sync_requirements "$SCRIPT_DIR/requirements.txt" "rti.connextdds:RTI Connext DDS Python API"

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
if ! python_env_resolve_license_file; then
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