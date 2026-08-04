#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${RTI_DOCTOR_FASTDDS_IMAGE:-rti-doctor-fastdds-e2e:2.14.6}"

docker build --pull --tag "$IMAGE" "$SCRIPT_DIR"