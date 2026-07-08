#!/bin/bash
# Common Python environment bootstrap helpers for repository launchers.

python_env_init() {
    PYTHON_ENV_LABEL="${1:?python_env_init requires a label}"
    PYTHON_ENV_REPO_ROOT="${2:?python_env_init requires a repo root}"
    PYTHON_ENV_REQUIRED_PYTHON_BIN="${3:-python3.10}"
    PYTHON_ENV_REQUIRED_PYTHON_VERSION="${4:-3.10}"
    PYTHON_ENV_VENV_DIR="${PYTHON_ENV_REPO_ROOT}/connext_dds_env"
    PYTHON_ENV_VENV_PYTHON="${PYTHON_ENV_VENV_DIR}/bin/python"
    PYTHON_ENV_STEP_COUNTER=0
}

python_env_log_step() {
    PYTHON_ENV_STEP_COUNTER=$((PYTHON_ENV_STEP_COUNTER + 1))
    echo
    echo "[${PYTHON_ENV_LABEL}][step ${PYTHON_ENV_STEP_COUNTER}] $*"
}

python_env_find_required_python() {
    if command -v "$PYTHON_ENV_REQUIRED_PYTHON_BIN" >/dev/null 2>&1; then
        command -v "$PYTHON_ENV_REQUIRED_PYTHON_BIN"
        return 0
    fi

    return 1
}

python_env_venv_python_version() {
    "$PYTHON_ENV_VENV_PYTHON" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
}

python_env_find_nddshome() {
    local preferred="$HOME/rti_connext_dds-7.7.0"
    local latest
    local dir

    if [[ -n "${NDDSHOME:-}" && -d "$NDDSHOME" ]]; then
        printf '%s\n' "$NDDSHOME"
        return 0
    fi

    if [[ -d "$preferred" ]]; then
        printf '%s\n' "$preferred"
        return 0
    fi

    latest=$(ls -d "$HOME"/rti_connext_dds-* 2>/dev/null | sort -V | tail -n 1 || true)
    if [[ -n "$latest" && -d "$latest" ]]; then
        printf '%s\n' "$latest"
        return 0
    fi

    for dir in /opt/rti_connext_dds-* /opt/rti/rti_connext_dds-*; do
        if [[ -d "$dir" ]]; then
            printf '%s\n' "$dir"
            return 0
        fi
    done

    return 1
}

python_env_resolve_nddshome() {
    python_env_log_step "Resolving NDDSHOME"
    local detected_nddshome
    if ! detected_nddshome="$(python_env_find_nddshome)"; then
        echo "ERROR: NDDSHOME is not set and no RTI Connext installation was found."
        echo "Install RTI Connext 7.7 and/or set NDDSHOME before launching ${PYTHON_ENV_LABEL}."
        return 1
    fi

    export NDDSHOME="$detected_nddshome"
    echo "NDDSHOME: $NDDSHOME"
}

python_env_ensure_venv() {
    python_env_log_step "Checking Python virtual environment"
    local required_python
    local current_version

    if ! required_python="$(python_env_find_required_python)"; then
        echo "ERROR: $PYTHON_ENV_REQUIRED_PYTHON_BIN is required to create $PYTHON_ENV_VENV_DIR."
        echo "Install Python $PYTHON_ENV_REQUIRED_PYTHON_VERSION and rerun the launcher."
        return 1
    fi

    if [[ ! -x "$PYTHON_ENV_VENV_PYTHON" ]]; then
        echo "Virtual environment not found at: $PYTHON_ENV_VENV_DIR"
        echo "Creating shared virtual environment with $PYTHON_ENV_REQUIRED_PYTHON_BIN..."
        "$required_python" -m venv "$PYTHON_ENV_VENV_DIR"
        echo "Created virtual environment: $PYTHON_ENV_VENV_DIR"
    else
        current_version="$(python_env_venv_python_version)"
        if [[ "$current_version" != "$PYTHON_ENV_REQUIRED_PYTHON_VERSION" ]]; then
            echo "Virtual environment uses Python $current_version; rebuilding with $PYTHON_ENV_REQUIRED_PYTHON_VERSION..."
            rm -rf "$PYTHON_ENV_VENV_DIR"
            "$required_python" -m venv "$PYTHON_ENV_VENV_DIR"
            echo "Rebuilt virtual environment: $PYTHON_ENV_VENV_DIR"
        else
            echo "Using virtual environment: $PYTHON_ENV_VENV_DIR"
        fi
    fi
}

python_env_activate_venv() {
    source "$PYTHON_ENV_VENV_DIR/bin/activate" 2>/dev/null || true
    export PATH="$PYTHON_ENV_VENV_DIR/bin:$PATH"
    export PYTHONNOUSERSITE=1
    echo "Using Python interpreter: $PYTHON_ENV_VENV_PYTHON"
}

python_env_sync_requirements() {
    local requirements_file="${1:?python_env_sync_requirements requires requirements.txt path}"
    shift

    python_env_log_step "Checking Python dependencies"
    echo "Synchronizing launcher dependencies from $requirements_file"
    "$PYTHON_ENV_VENV_PYTHON" -m pip install -v --progress-bar on -r "$requirements_file"

    if [[ $# -eq 0 ]]; then
        return 0
    fi

    set +e
    "$PYTHON_ENV_VENV_PYTHON" - "$@" <<'PY'
import importlib
import sys
import traceback


def require_import(module_name: str, package_label: str) -> None:
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        print(f"ERROR: Failed to import {package_label}: {exc}", file=sys.stderr)
        if package_label == "Dear PyGui" and "GLIBCXX_" in str(exc):
            print(
                "ERROR: The installed Dear PyGui wheel requires a newer libstdc++ runtime than this host provides.",
                file=sys.stderr,
            )
            print(
                "ERROR: Upgrade the system libstdc++/compiler runtime or install a Dear PyGui wheel compatible with this host.",
                file=sys.stderr,
            )
        traceback.print_exc()
        sys.exit(1)


for raw_spec in sys.argv[1:]:
    module_name, package_label = raw_spec.split(":", 1)
    require_import(module_name, package_label)
PY
    local status=$?
    set -e

    if [[ $status -ne 0 ]]; then
        echo "ERROR: Installed dependencies do not satisfy launcher requirements. See the import error above for details."
        return 1
    fi
}

python_env_detect_rti_python_version() {
    "$PYTHON_ENV_VENV_PYTHON" - <<'PY'
import importlib.metadata

print(importlib.metadata.version("rti-connext"))
PY
}

python_env_generated_rtiddsgen_version() {
    local gen_file="${1:?python_env_generated_rtiddsgen_version requires a generated file path}"
    if [[ -f "$gen_file" ]]; then
        grep -oP 'rtiddsgen\) version \K[0-9]+\.[0-9]+\.[0-9]+' "$gen_file" 2>/dev/null || true
    fi
}

python_env_ensure_versioned_types() {
    python_env_log_step "Checking versioned Python type support"

    local rti_python_version
    local types_cache_dir
    local versioned_dir
    local idl_dir
    local rtiddsgen
    local xtypes_mask
    local idl_file
    local idl_basename
    local generated_version

    if ! rti_python_version="$(python_env_detect_rti_python_version)" || [[ -z "$rti_python_version" ]]; then
        echo "ERROR: Cannot detect rti.connext version. Is the package installed?"
        echo "  pip install rti.connext"
        return 1
    fi
    echo "Detected rti.connext version: $rti_python_version"

    types_cache_dir="$PYTHON_ENV_REPO_ROOT/build/dds/python_types"
    versioned_dir="$types_cache_dir/$rti_python_version/python_gen"
    idl_dir="$PYTHON_ENV_REPO_ROOT/dds/datamodel/idl"

    if [[ -f "$versioned_dir/ExampleTypes.py" ]]; then
        generated_version="$(python_env_generated_rtiddsgen_version "$versioned_dir/ExampleTypes.py")"
        echo "Using cached Python types: $versioned_dir"
        if [[ -n "$generated_version" ]]; then
            echo "Generated by rtiddsgen $generated_version"
        fi
    else
        echo "Generating Python type support for rti.connext $rti_python_version..."

        rtiddsgen="$NDDSHOME/bin/rtiddsgen"
        if [[ ! -x "$rtiddsgen" ]]; then
            echo "ERROR: rtiddsgen not found at $rtiddsgen"
            echo "Ensure NDDSHOME points to a valid Connext installation."
            return 1
        fi

        mkdir -p "$versioned_dir"
        xtypes_mask=$("$PYTHON_ENV_VENV_PYTHON" -c "import rti.connextdds as dds; print(hex(int(dds.compliance.get_xtypes_mask())))" 2>/dev/null || true)

        for idl_file in "$idl_dir"/*.idl; do
            idl_basename=$(basename "$idl_file" .idl)
            echo "  Generating: $idl_basename..."
            if [[ -n "$xtypes_mask" ]]; then
                "$rtiddsgen" -language Python -d "$versioned_dir" \
                    -I "$idl_dir" -xTypesComplianceMask "$xtypes_mask" \
                    "$idl_file" -replace 2>&1 | grep -v "^$" || true
            else
                "$rtiddsgen" -language Python -d "$versioned_dir" \
                    -I "$idl_dir" "$idl_file" -replace 2>&1 | grep -v "^$" || true
            fi
        done

        if [[ ! -f "$versioned_dir/__init__.py" ]]; then
            touch "$versioned_dir/__init__.py"
        fi

        if [[ ! -f "$versioned_dir/ExampleTypes.py" ]]; then
            echo "ERROR: Type generation failed. ExampleTypes.py not created."
            return 1
        fi

        generated_version="$(python_env_generated_rtiddsgen_version "$versioned_dir/ExampleTypes.py")"
        echo "Generated Python types at: $versioned_dir"
        if [[ -n "$generated_version" ]]; then
            echo "Generated by rtiddsgen $generated_version"
        fi
    fi

    export DDS_PYTHON_GEN_DIR="$types_cache_dir/$rti_python_version"
    export PYTHONPATH="$DDS_PYTHON_GEN_DIR${PYTHONPATH:+:$PYTHONPATH}"
    echo "DDS_PYTHON_GEN_DIR: $DDS_PYTHON_GEN_DIR"
}

python_env_resolve_license_file() {
    python_env_log_step "Resolving RTI license file"
    local candidate
    local dir

    if [[ -n "${RTI_LICENSE_FILE:-}" ]]; then
        if [[ -f "$RTI_LICENSE_FILE" ]]; then
            echo "Using RTI_LICENSE_FILE from environment: $RTI_LICENSE_FILE"
            return 0
        fi
        echo "WARNING: RTI_LICENSE_FILE is set but file is missing: $RTI_LICENSE_FILE"
    fi

    for candidate in \
        "$NDDSHOME/rti_license.dat" \
        "$NDDSHOME/rti_license.txt" \
        "$NDDSHOME/resource/rti_license.dat" \
        "$NDDSHOME/resource/licenses/rti_license.dat"; do
        if [[ -f "$candidate" ]]; then
            export RTI_LICENSE_FILE="$candidate"
            echo "Detected RTI license file: $RTI_LICENSE_FILE"
            return 0
        fi
    done

    for dir in "$HOME"/rti_connext_dds-* /opt/rti_connext_dds-* /opt/rti/rti_connext_dds-*; do
        if [[ -d "$dir" ]]; then
            for candidate in "$dir/rti_license.dat" "$dir/rti_license.txt"; do
                if [[ -f "$candidate" ]]; then
                    export RTI_LICENSE_FILE="$candidate"
                    echo "Detected RTI license file: $RTI_LICENSE_FILE"
                    return 0
                fi
            done
        fi
    done

    echo "ERROR: Unable to find an RTI license file automatically."
    echo "Please set RTI_LICENSE_FILE to a valid license file path and rerun."
    echo "Example: export RTI_LICENSE_FILE=/path/to/rti_license.dat"
    return 1
}