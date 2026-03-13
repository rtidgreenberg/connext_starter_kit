#!/bin/bash
# Setup script for Python Recording Service Remote Control
# Converts RTI IDL type definitions to XML for use with Python DynamicData
#
# This script uses rtiddsgen to convert the ServiceAdmin, ServiceCommon,
# and RecordingServiceTypes IDL files (included with RTI Connext DDS)
# into XML format so they can be loaded by the Python API's QosProvider.
#
# Reference: https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/code_generator/users_manual/code_generator/users_manual/CommandLineArgs.htm

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XML_OUT_DIR="$SCRIPT_DIR/xml_types"

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

# --- Verify rtiddsgen ---
RTIDDSGEN="$NDDSHOME/bin/rtiddsgen"
if [ ! -f "$RTIDDSGEN" ]; then
    echo "ERROR: rtiddsgen not found at $RTIDDSGEN"
    exit 1
fi
echo "✓ rtiddsgen: $RTIDDSGEN"

# --- Verify source IDL files ---
IDL_DIR="$NDDSHOME/resource/idl"
IDL_FILES=("ServiceCommon.idl" "ServiceAdmin.idl" "RecordingServiceTypes.idl")

for idl in "${IDL_FILES[@]}"; do
    if [ ! -f "$IDL_DIR/$idl" ]; then
        echo "ERROR: IDL file not found: $IDL_DIR/$idl"
        exit 1
    fi
done
echo "✓ Source IDL files found in: $IDL_DIR"

# --- Install sqlite3 (needed by rtirecordingservice_list_tags) ---
if ! command -v sqlite3 &>/dev/null; then
    echo
    echo "Installing sqlite3 (required by rtirecordingservice_list_tags)..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y sqlite3
    elif command -v yum &>/dev/null; then
        sudo yum install -y sqlite
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y sqlite
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm sqlite
    else
        echo "WARNING: Could not detect package manager. Please install sqlite3 manually."
    fi

    if command -v sqlite3 &>/dev/null; then
        echo "✓ sqlite3 installed: $(sqlite3 --version)"
    else
        echo "WARNING: sqlite3 installation may have failed. rtirecordingservice_list_tags may not work."
    fi
else
    echo "✓ sqlite3 already installed: $(sqlite3 --version)"
fi

# --- Convert IDL to XML ---
mkdir -p "$XML_OUT_DIR"
echo
echo "Converting IDL files to XML..."

for idl in "${IDL_FILES[@]}"; do
    echo "  Converting $idl..."
    "$RTIDDSGEN" -convertToXML -d "$XML_OUT_DIR" -I "$IDL_DIR" "$IDL_DIR/$idl" 2>&1
done

echo
echo "✓ XML type files generated in: $XML_OUT_DIR"
ls -la "$XML_OUT_DIR"/*.xml

echo
echo "=== Setup complete ==="
echo "You can now run: python3 recording_service_control.py --help"
