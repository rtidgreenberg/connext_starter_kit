#!/bin/bash
# Focused tests for source selection in scripts/python_env.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/python_env.sh"

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

python_env_installed_dist_version() {
    case "${1:?distribution required}" in
        rti.connext.activated)
            printf '%s\n' "${TEST_ACTIVATED_VERSION:-}"
            ;;
        rti.connext)
            printf '%s\n' "${TEST_PUBLIC_VERSION:-}"
            ;;
    esac
}

python_env_local_activated_wheel_path() {
    [[ "${TEST_BUNDLED_WHEEL:-0}" == "1" ]] || return 1
    printf '%s\n' "/tmp/rti_connext_activated.whl"
}

python_env_find_nddshome() {
    return 1
}

python_env_is_interactive() {
    [[ "${TEST_INTERACTIVE:-0}" == "1" ]]
}

reset_environment() {
    unset NDDSHOME RTI_PYTHON_WHEEL TEST_ACTIVATED_VERSION TEST_PUBLIC_VERSION TEST_BUNDLED_WHEEL TEST_INTERACTIVE
    RTI_PYTHON_SOURCE=auto
    python_env_init "test" "$SCRIPT_DIR/.."
}

reset_environment
TEST_ACTIVATED_VERSION="7.7.0"
python_env_select_rti_connext_source >/dev/null
assert_equals "installed" "$PYTHON_ENV_SELECTED_SOURCE" "matching activated package should be reused"
assert_equals "rti.connext.activated" "$PYTHON_ENV_INSTALLED_DISTRIBUTION" "activated package should be identified"

reset_environment
TEST_PUBLIC_VERSION="7.7.0"
python_env_select_rti_connext_source >/dev/null
assert_equals "installed" "$PYTHON_ENV_SELECTED_SOURCE" "matching PyPI package should be reused"
assert_equals "rti.connext" "$PYTHON_ENV_INSTALLED_DISTRIBUTION" "PyPI package should be identified"

reset_environment
RTI_PYTHON_WHEEL="/opt/rti/rti_connext_activated.whl"
python_env_select_rti_connext_source >/dev/null
assert_equals "activated-wheel" "$PYTHON_ENV_SELECTED_SOURCE" "explicit wheel should be selected in auto mode"

reset_environment
NDDSHOME="/opt/rti_connext_dds-7.7.0"
TEST_BUNDLED_WHEEL=1
python_env_select_rti_connext_source >/dev/null
assert_equals "activated-wheel" "$PYTHON_ENV_SELECTED_SOURCE" "bundled wheel should be selected in auto mode"

reset_environment
RTI_PYTHON_SOURCE=pypi
python_env_init "test" "$SCRIPT_DIR/.."
python_env_select_rti_connext_source >/dev/null
assert_equals "pypi" "$PYTHON_ENV_SELECTED_SOURCE" "explicit PyPI source should be selected"

reset_environment
RTI_PYTHON_SOURCE=unsupported
python_env_init "test" "$SCRIPT_DIR/.."
if python_env_select_rti_connext_source >/dev/null 2>&1; then
    fail "unsupported source should fail"
fi

reset_environment
if python_env_select_rti_connext_source >/dev/null 2>&1; then
    fail "non-interactive auto mode without a source should fail"
fi

reset_environment
python_env_resolve_nddshome >/dev/null
assert_equals "" "${NDDSHOME:-}" "missing native installation should not be a Python setup failure"

reset_environment
PYTHON_ENV_VENV_PYTHON="$(command -v python3)"
if python_env_ensure_versioned_types >/dev/null 2>&1; then
    fail "type initialization without native tooling should fail"
fi

reset_environment
temporary_home="$(mktemp -d)"
if HOME="$temporary_home" python_env_resolve_license_file >/dev/null 2>&1; then
    rm -rf "$temporary_home"
    fail "missing PyPI license should fail without NDDSHOME"
fi
rm -rf "$temporary_home"

echo "PASS: python_env source selection"