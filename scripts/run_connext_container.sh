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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LICENSE_SOURCE="${RTI_LICENSE_HOST_PATH:-$HOME/rti_license.dat}"

if [[ ! -r "$LICENSE_SOURCE" ]]; then
    echo "ERROR: RTI license file is not readable: $LICENSE_SOURCE" >&2
    echo "Set RTI_LICENSE_HOST_PATH to the path of your rti_license.dat file." >&2
    exit 1
fi

cd "$REPO_ROOT"
mkdir -p shared
install -m 600 "$LICENSE_SOURCE" shared/rti_license.dat

docker compose -f docker-compose.connext-7.7.yml build
exec docker compose -f docker-compose.connext-7.7.yml run --rm connext "$@"