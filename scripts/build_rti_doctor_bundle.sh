#!/bin/bash
# Build an RTI Doctor PyInstaller folder bundle from a prepared local Python environment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_DIR="$REPO_ROOT/tools/rti_doctor"
source "$SCRIPT_DIR/rti_doctor_bundle_common.sh"

usage() {
    cat <<'EOF'
Usage: ./scripts/build_rti_doctor_bundle.sh

Builds a compressed RTI Doctor PyInstaller folder from the environment prepared
by prepare_rti_doctor_bundle_env.sh. This command never downloads Python packages.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            usage
            exit 0
            ;;
        *)
            rti_doctor_bundle_die "unknown argument: $1"
            usage
            exit 2
            ;;
    esac
done

prepared_wheel_path="$REPO_ROOT/build/rti_doctor_bundle/prepared-wheel-path"
[[ -f "$prepared_wheel_path" ]] || {
    rti_doctor_bundle_die "no prepared wheel found. Run ./scripts/prepare_rti_doctor_bundle_env.sh --wheel PATH first."
    exit 1
}
wheel_path="$(<"$prepared_wheel_path")"
[[ -n "$wheel_path" ]] || {
    rti_doctor_bundle_die "no prepared wheel found. Run ./scripts/prepare_rti_doctor_bundle_env.sh --wheel PATH first."
    exit 1
}

rti_doctor_bundle_parse_wheel "$wheel_path"
venv_dir="$REPO_ROOT/build/rti_doctor_bundle/venv-${RTI_DOCTOR_BUNDLE_PYTHON_TAG}"
venv_python="$venv_dir/bin/python"
[[ -x "$venv_python" ]] || {
    rti_doctor_bundle_die "prepared environment missing: $venv_dir. Run ./scripts/prepare_rti_doctor_bundle_env.sh --wheel $RTI_DOCTOR_BUNDLE_WHEEL_PATH first."
    exit 1
}

"$venv_python" - "$RTI_DOCTOR_BUNDLE_CONNEXT_VERSION" <<'PY'
import importlib
import importlib.metadata as metadata
import sys

expected_version = sys.argv[1]
try:
    installed_version = metadata.version("rti-connext-activated")
except metadata.PackageNotFoundError as exc:
    raise SystemExit("rti.connext.activated is not installed in the prepared environment") from exc
if installed_version != expected_version:
    raise SystemExit(
        f"prepared environment has rti.connext.activated=={installed_version}, expected {expected_version}"
    )
for module_name in ("PyInstaller", "rti.connextdds", "rich", "textual"):
    importlib.import_module(module_name)
PY

artifact_base="rti_doctor-connext-${RTI_DOCTOR_BUNDLE_CONNEXT_VERSION}-${RTI_DOCTOR_BUNDLE_PYTHON_TAG}-$(uname -m)"
work_dir="$REPO_ROOT/build/rti_doctor_bundle/work/$artifact_base"
dist_dir="$REPO_ROOT/build/rti_doctor_bundle/dist/$artifact_base"
rm -rf "$work_dir" "$dist_dir"
mkdir -p "$work_dir" "$dist_dir"

"$venv_python" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --name rti_doctor \
    --distpath "$dist_dir" \
    --workpath "$work_dir/pyinstaller" \
    --specpath "$work_dir" \
    --paths "$TOOLS_DIR" \
    --additional-hooks-dir "$TOOLS_DIR/pyinstaller" \
    --hidden-import rti.asyncio \
    --hidden-import rti.connextdds \
    --hidden-import rti.idl \
    --hidden-import rti.idl_impl \
    --hidden-import rti.libnddsc \
    --hidden-import rti.libnddscore \
    --hidden-import rti.libnddscpp2 \
    --hidden-import rti.logging \
    --hidden-import rti.request \
    --hidden-import rti.rpc \
    --hidden-import rti.types \
    "$TOOLS_DIR/rti_doctor_bundle_entry.py"

tar -C "$dist_dir" -czf "$REPO_ROOT/build/rti_doctor_bundle/${artifact_base}.tar.gz" rti_doctor

echo "Created RTI Doctor deployment bundle under $REPO_ROOT/build/rti_doctor_bundle"