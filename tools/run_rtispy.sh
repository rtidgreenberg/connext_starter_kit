#!/bin/bash
# Convenience script to run RTI Spy with proper environment setup

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/rtispy_env"

# Check if virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found at: $VENV_DIR"
    echo "Running install.sh to set up the environment..."
    echo
    
    # Run the install script
    if [ -x "$SCRIPT_DIR/install.sh" ]; then
        "$SCRIPT_DIR/install.sh"
    else
        echo "ERROR: install.sh not found or not executable"
        echo "Please ensure install.sh exists in $SCRIPT_DIR and is executable:"
        echo "  chmod +x $SCRIPT_DIR/install.sh"
        exit 1
    fi
    
    # Check if installation was successful
    if [ ! -d "$VENV_DIR" ]; then
        echo "ERROR: Installation failed. Virtual environment was not created."
        exit 1
    fi
    
    echo
    echo "Installation complete. Starting RTI Spy..."
    echo
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Check if NDDSHOME is set
if [ -z "$NDDSHOME" ]; then
    echo "⚠️  WARNING: NDDSHOME environment variable not set"
    echo "   Please source the RTI Connext environment script first:"
    echo "     source <path_to_connext>/resource/scripts/rtisetenv_<architecture>.bash"
    echo
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled. Please set up RTI Connext environment first."
        exit 1
    fi
fi

# Run rtispy with all arguments passed to this script
python "$SCRIPT_DIR/rtispy.py" "$@"
