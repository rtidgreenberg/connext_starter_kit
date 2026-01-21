#!/bin/bash
# Run script for dynamic_partition_qos
# Executes the binary from the top-level build directory

cd /home/rti/connext_starter_kit || exit 1

# Check if binary exists, build if needed
BINARY="./build/apps/cxx11/dynamic_partition_qos/dynamic_partition_qos"
if [ ! -f "$BINARY" ]; then
    echo "Binary not found. Building project..."
    cd ./build && cmake --build . || exit 1
    cd ..
fi

"$BINARY" "$@"
