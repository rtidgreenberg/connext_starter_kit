#!/bin/bash
# Focused tests for RTI Doctor deployment bundle validation helpers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/rti_doctor_bundle_common.sh"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_equals() {
    local expected="${1-}"
    local actual="${2-}"
    local message="${3:?message required}"
    [[ "$expected" == "$actual" ]] || fail "$message (expected '$expected', got '$actual')"
}

temporary_dir="$(mktemp -d)"
trap 'rm -rf "$temporary_dir"' EXIT
wheel_path="$temporary_dir/rti_connext_activated-7.3.1-cp39-cp39-manylinux_2_17_x86_64.whl"

python3 - "$wheel_path" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1], "w") as archive:
    archive.writestr(
        "rti_connext_activated-7.3.1.dist-info/METADATA",
        "Metadata-Version: 2.1\nName: rti.connext.activated\nVersion: 7.3.1\n",
    )
    archive.writestr(
        "rti_connext_activated-7.3.1.dist-info/WHEEL",
        "Wheel-Version: 1.0\nTag: cp39-cp39-manylinux_2_17_x86_64\n",
    )
PY

rti_doctor_bundle_parse_wheel "$wheel_path"
assert_equals "7.3.1" "$RTI_DOCTOR_BUNDLE_CONNEXT_VERSION" "wheel version should be parsed"
assert_equals "cp39" "$RTI_DOCTOR_BUNDLE_PYTHON_TAG" "wheel Python tag should be parsed"
assert_equals "3.9" "$RTI_DOCTOR_BUNDLE_PYTHON_VERSION" "wheel Python version should be derived"

echo "PASS: rti_doctor bundle validation"