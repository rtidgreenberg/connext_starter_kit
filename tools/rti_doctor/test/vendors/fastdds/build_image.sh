#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${RTI_DOCTOR_FASTDDS_IMAGE:-rti-doctor-fastdds-e2e:3.6.2}"

docker build --pull --tag "$IMAGE" "$SCRIPT_DIR"