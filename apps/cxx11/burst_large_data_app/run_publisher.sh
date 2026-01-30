#!/bin/bash
# Run script for burst_publisher
# Executes the binary from the top-level build directory

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

cd "$PROJECT_ROOT" || exit 1

# Check if binary exists, build if needed
BINARY="./build/apps/cxx11/burst_large_data_app/burst_publisher"
if [ ! -f "$BINARY" ]; then
    echo "Binary not found. Building project..."
    cd ./build && cmake --build . || exit 1
    cd ..
fi

# QoS profiles file
QOS_FILE="${PROJECT_ROOT}/dds/qos/DDS_QOS_PROFILES.xml"

# Print execution details
echo "========================================"
echo "Running: burst_publisher"
echo "========================================"
echo "Executable: ${BINARY}"
echo "QoS File:   ${QOS_FILE}"
echo "Arguments:  $@"
echo "========================================"
echo "Full command:"
echo "  ${BINARY} --qos-file ${QOS_FILE} $@"
echo "========================================"
echo ""

"$BINARY" --qos-file "$QOS_FILE" "$@"
