#!/bin/bash
# Common Python environment bootstrap helpers for repository launchers.

python_env_init() {
    PYTHON_ENV_LABEL="${1:?python_env_init requires a label}"
    PYTHON_ENV_REPO_ROOT="${2:?python_env_init requires a repo root}"
    if [[ -n "${3:-}" || -n "${4:-}" ]]; then
        # Caller pinned an explicit interpreter; skip Connext-version auto-detection.
        PYTHON_ENV_REQUIRED_PYTHON_BIN="${3:-python3.10}"
        PYTHON_ENV_REQUIRED_PYTHON_VERSION="${4:-3.10}"
        PYTHON_ENV_VERSION_EXPLICIT=1
    else
        PYTHON_ENV_REQUIRED_PYTHON_BIN="python3.10"
        PYTHON_ENV_REQUIRED_PYTHON_VERSION="3.10"
        PYTHON_ENV_VERSION_EXPLICIT=0
    fi
    PYTHON_ENV_CONNEXT_VERSION=""
    PYTHON_ENV_RTI_CONNEXT_PIP_VERSION="7.7.0"
    PYTHON_ENV_VENV_DIR="${PYTHON_ENV_REPO_ROOT}/connext_dds_env"
    PYTHON_ENV_VENV_PYTHON="${PYTHON_ENV_VENV_DIR}/bin/python"
    PYTHON_ENV_STEP_COUNTER=0
}

# Extracts the full Connext version (major.minor.patch) from an NDDSHOME path,
# e.g. "/home/rti/rti_connext_dds-7.3.1" -> "7.3.1". Returns non-zero if it
# can't be parsed.
python_env_connext_full_version_from_path() {
    local path="${1:?python_env_connext_full_version_from_path requires a path}"
    local base
    base="$(basename "$path")"
    if [[ "$base" =~ rti_connext_dds-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}

# Looks for a Connext-bundled "rti.connext.activated" wheel matching the given
# full Connext version and Python tag (e.g. "39" for cp39) under
# $NDDSHOME/resource/python_api/. This wheel is pre-activated (no separate
# license file needed) and ships with every native Connext install, so prefer
# it over downloading the public rti.connext package from PyPI. Prints the
# matched wheel path and returns 0 if found, otherwise returns 1.
python_env_local_activated_wheel_path() {
    local version="${1:?python_env_local_activated_wheel_path requires a Connext version}"
    local pytag="${2:?python_env_local_activated_wheel_path requires a python tag (e.g. 39)}"
    local wheel_dir="${NDDSHOME:-}/resource/python_api"
    local candidate

    if [[ ! -d "$wheel_dir" ]]; then
        return 1
    fi

    candidate=$(ls "$wheel_dir"/rti_connext_activated-"$version"-cp"$pytag"-*.whl 2>/dev/null | head -n 1 || true)
    if [[ -n "$candidate" && -f "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi
    return 1
}

# Selects the Python interpreter, venv directory, and rti.connext pip version
# to use based on the detected NDDSHOME Connext version, so that Connext 7.3.x
# (Python 3.9) and Connext 7.7.x (Python 3.10) can both be supported without
# manually reconfiguring or rebuilding a shared venv every time NDDSHOME changes.
python_env_configure_for_connext_version() {
    local nddshome="${1:?python_env_configure_for_connext_version requires an NDDSHOME path}"
    local full_version
    local version_mm

    if [[ "${PYTHON_ENV_VERSION_EXPLICIT:-0}" == "1" ]]; then
        return 0
    fi

    full_version="$(python_env_connext_full_version_from_path "$nddshome" 2>/dev/null || true)"
    version_mm="${full_version%.*}"
    PYTHON_ENV_CONNEXT_VERSION="$version_mm"

    case "$version_mm" in
        7.3)
            PYTHON_ENV_REQUIRED_PYTHON_BIN="python3.9"
            PYTHON_ENV_REQUIRED_PYTHON_VERSION="3.9"
            PYTHON_ENV_RTI_CONNEXT_PIP_VERSION="7.3.1"
            PYTHON_ENV_VENV_DIR="${PYTHON_ENV_REPO_ROOT}/connext_dds_env_7.3"
            ;;
        *)
            PYTHON_ENV_REQUIRED_PYTHON_BIN="python3.10"
            PYTHON_ENV_REQUIRED_PYTHON_VERSION="3.10"
            PYTHON_ENV_RTI_CONNEXT_PIP_VERSION="7.7.0"
            PYTHON_ENV_VENV_DIR="${PYTHON_ENV_REPO_ROOT}/connext_dds_env"
            ;;
    esac

    # Prefer the exact patch version reported by NDDSHOME itself over the
    # hardcoded per-bucket default above, so the fallback PyPI install and the
    # local bundled-wheel lookup both target the version the user actually
    # has installed rather than an assumed patch release.
    if [[ -n "$full_version" ]]; then
        PYTHON_ENV_RTI_CONNEXT_PIP_VERSION="$full_version"
    fi
    PYTHON_ENV_VENV_PYTHON="${PYTHON_ENV_VENV_DIR}/bin/python"
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

    python_env_configure_for_connext_version "$NDDSHOME"
    if [[ -n "$PYTHON_ENV_CONNEXT_VERSION" ]]; then
        echo "Detected Connext version: $PYTHON_ENV_CONNEXT_VERSION"
    else
        echo "Could not detect Connext version from NDDSHOME; defaulting to Connext 7.7.x settings."
    fi
    echo "Target Python: $PYTHON_ENV_REQUIRED_PYTHON_BIN (rti.connext==$PYTHON_ENV_RTI_CONNEXT_PIP_VERSION)"
    echo "Virtual environment: $PYTHON_ENV_VENV_DIR"
}

python_env_ensure_venv() {
    python_env_log_step "Checking Python virtual environment"
    local required_python
    local current_version

    if ! required_python="$(python_env_find_required_python)"; then
        echo "ERROR: $PYTHON_ENV_REQUIRED_PYTHON_BIN is required to create $PYTHON_ENV_VENV_DIR."
        echo "Install Python $PYTHON_ENV_REQUIRED_PYTHON_VERSION and rerun the launcher."
        if [[ "$PYTHON_ENV_REQUIRED_PYTHON_BIN" == "python3.9" ]]; then
            echo "  sudo apt install python3.9 python3.9-venv"
        fi
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

# Removes stale dist-info metadata for the "other" rti.connext distribution
# (the one we are NOT about to install), so switching between the PyPI
# "rti.connext" package and the bundled "rti.connext.activated" wheel across
# runs doesn't leave two conflicting dist-info directories installed side by
# side. `pip uninstall` is unreliable here: rti.connext's dotted name isn't
# always matched by pip's uninstall name resolution (observed: `pip show
# rti.connext` finds it, but `pip uninstall -y rti.connext` reports "not
# installed" and leaves the dist-info directory on disk), so remove the
# metadata directory directly via importlib.metadata instead.
python_env_remove_other_rti_connext_dist_info() {
    local keep_name="${1:?python_env_remove_other_rti_connext_dist_info requires the distribution name to keep}"
    "$PYTHON_ENV_VENV_PYTHON" - "$keep_name" <<'PY'
import importlib.metadata as metadata
import shutil
import sys


def canon(name):
    return name.replace(".", "-").replace("_", "-").lower()


keep = canon(sys.argv[1])
targets = {"rti-connext", "rti-connext-activated"} - {keep}

for dist in metadata.distributions():
    name = dist.metadata.get("Name") or ""
    if canon(name) in targets:
        path = getattr(dist, "_path", None)
        if path is not None:
            print(f"Removing stale distribution metadata: {name} ({path})")
            shutil.rmtree(str(path), ignore_errors=True)
PY
}

# Prints the installed version of the given distribution (matched by
# canonicalized name, so dots/dashes/underscores are treated as equivalent),
# or nothing if it isn't installed. Used to fast-skip reinstalling the local
# activated wheel: `pip install /path/to/local.whl` re-hashes the whole wheel
# file on every invocation to verify "already satisfied" (unlike a version-
# pinned PyPI requirement, which pip can confirm from metadata alone), which
# is slow for RTI's large native wheels and was adding multiple seconds to
# every single launcher invocation.
python_env_installed_dist_version() {
    local dist_name="${1:?python_env_installed_dist_version requires a distribution name}"
    "$PYTHON_ENV_VENV_PYTHON" - "$dist_name" <<'PY'
import importlib.metadata as metadata
import sys


def canon(name):
    return name.replace(".", "-").replace("_", "-").lower()


target = canon(sys.argv[1])
for dist in metadata.distributions():
    name = dist.metadata.get("Name") or ""
    if canon(name) == target:
        print(dist.version)
        break
PY
}

# Installs the rti.connext Python API version matching the detected NDDSHOME
# Connext version (set by python_env_configure_for_connext_version). Call this
# after python_env_activate_venv so both Connext 7.3.x (Python 3.9) and
# Connext 7.7.x (Python 3.10) get the correct wheel automatically.
#
# Prefers the "rti.connext.activated" wheel bundled with the local NDDSHOME
# install (under $NDDSHOME/resource/python_api/) since it is pre-activated
# (no separate license file needed) and requires no network access. Falls
# back to downloading the public "rti.connext" package from PyPI only if no
# matching bundled wheel is found.
python_env_sync_rti_connext() {
    local pytag="${PYTHON_ENV_REQUIRED_PYTHON_VERSION//./}"
    local local_wheel
    local installed_version

    python_env_log_step "Synchronizing rti.connext (Connext ${PYTHON_ENV_CONNEXT_VERSION:-7.7} -> $PYTHON_ENV_RTI_CONNEXT_PIP_VERSION, cp$pytag)"

    if local_wheel="$(python_env_local_activated_wheel_path "$PYTHON_ENV_RTI_CONNEXT_PIP_VERSION" "$pytag")"; then
        echo "Found bundled rti.connext.activated wheel: $local_wheel"
        installed_version="$(python_env_installed_dist_version rti.connext.activated)"
        if [[ "$installed_version" == "$PYTHON_ENV_RTI_CONNEXT_PIP_VERSION" ]]; then
            echo "rti.connext.activated==$PYTHON_ENV_RTI_CONNEXT_PIP_VERSION already installed; skipping reinstall."
        else
            echo "Installing from local wheel (no PyPI download required)."
            # Both distributions install into the same "rti" namespace package, so
            # remove the other one's stale dist-info first (see helper above).
            python_env_remove_other_rti_connext_dist_info "rti.connext.activated"
            "$PYTHON_ENV_VENV_PYTHON" -m pip install -v --progress-bar on "$local_wheel"
        fi
    else
        echo "No bundled rti.connext.activated wheel found for cp$pytag under \$NDDSHOME/resource/python_api."
        installed_version="$(python_env_installed_dist_version rti.connext)"
        if [[ "$installed_version" == "$PYTHON_ENV_RTI_CONNEXT_PIP_VERSION" ]]; then
            echo "rti.connext==$PYTHON_ENV_RTI_CONNEXT_PIP_VERSION already installed; skipping PyPI download."
        else
            echo "Falling back to downloading rti.connext==$PYTHON_ENV_RTI_CONNEXT_PIP_VERSION from PyPI."
            python_env_remove_other_rti_connext_dist_info "rti.connext"
            "$PYTHON_ENV_VENV_PYTHON" -m pip install -v --progress-bar on "rti.connext==$PYTHON_ENV_RTI_CONNEXT_PIP_VERSION"
        fi
    fi
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