#!/bin/bash
# Run script for burst_subscriber
# Executes the binary from the top-level build directory

cd /home/rti/connext_starter_kit || exit 1

# Check if binary exists, build if needed
BINARY="./build/apps/cxx11/burst_large_data_app/burst_subscriber"
if [ ! -f "$BINARY" ]; then
    echo "Binary not found. Building project..."
    cd ./build && cmake --build . || exit 1
    cd ..
fi

"$BINARY" "$@"
