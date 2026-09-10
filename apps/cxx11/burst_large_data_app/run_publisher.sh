#!/bin/bash
# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
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
    mkdir -p ./build
    cd ./build
    cmake .. || exit 1
    cmake --build . || exit 1
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
