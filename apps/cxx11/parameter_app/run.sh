#!/bin/bash

# Run script for parameter_app
# This script runs the parameter application from the repository root

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"

# Change to repository root for correct relative paths
cd "$REPO_ROOT"

# Run the application
exec ./build/apps/cxx11/parameter_app/parameter_app "$@"
