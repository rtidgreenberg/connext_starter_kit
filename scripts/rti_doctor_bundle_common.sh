#!/bin/bash
# Shared validation helpers for the RTI Doctor deployment scripts.

rti_doctor_bundle_die() {
    echo "ERROR: $*" >&2
    return 1
}

rti_doctor_bundle_parse_wheel() {
    local wheel_path="${1:?wheel path required}"
    local wheel_info

    [[ -f "$wheel_path" && "$wheel_path" == *.whl ]] || {
        rti_doctor_bundle_die "--wheel must point to an existing .whl file: $wheel_path"
        return 1
    }

    wheel_info="$(python3 - "$wheel_path" <<'PY'
import email
import sys
import zipfile

wheel_path = sys.argv[1]
with zipfile.ZipFile(wheel_path) as archive:
    metadata_path = next(
        (name for name in archive.namelist() if name.endswith('.dist-info/METADATA')),
        None,
    )
    wheel_metadata_path = next(
        (name for name in archive.namelist() if name.endswith('.dist-info/WHEEL')),
        None,
    )
    if metadata_path is None or wheel_metadata_path is None:
        raise SystemExit('wheel is missing required dist-info metadata')

    metadata = email.message_from_bytes(archive.read(metadata_path))
    wheel_metadata = email.message_from_bytes(archive.read(wheel_metadata_path))
    package_name = (metadata.get('Name') or '').replace('-', '.').lower()
    if package_name != 'rti.connext.activated':
        raise SystemExit(f'wheel package is {metadata.get("Name")!r}, not rti.connext.activated')

    for tag in wheel_metadata.get_all('Tag', []):
        python_tag, _abi_tag, platform_tag = tag.split('-', 2)
        if python_tag.startswith('cp3'):
            print(f'{metadata["Version"]}\t{python_tag}\t{platform_tag}')
            break
    else:
        raise SystemExit('wheel has no supported CPython 3 tag')
PY
)" || {
        rti_doctor_bundle_die "could not read RTI Python wheel metadata from $wheel_path"
        return 1
    }

    IFS=$'\t' read -r RTI_DOCTOR_BUNDLE_CONNEXT_VERSION RTI_DOCTOR_BUNDLE_PYTHON_TAG RTI_DOCTOR_BUNDLE_PLATFORM_TAG <<<"$wheel_info"
    if [[ ! "$RTI_DOCTOR_BUNDLE_PYTHON_TAG" =~ ^cp3([0-9]+)$ ]]; then
        rti_doctor_bundle_die "unsupported Python tag '$RTI_DOCTOR_BUNDLE_PYTHON_TAG' in $wheel_path"
        return 1
    fi

    RTI_DOCTOR_BUNDLE_PYTHON_VERSION="3.${BASH_REMATCH[1]}"
    RTI_DOCTOR_BUNDLE_WHEEL_PATH="$(cd "$(dirname "$wheel_path")" && pwd)/$(basename "$wheel_path")"
}

rti_doctor_bundle_find_python() {
    local interpreter="python${RTI_DOCTOR_BUNDLE_PYTHON_VERSION}"
    local resolved

    resolved="$(command -v "$interpreter" 2>/dev/null || true)"
    [[ -n "$resolved" ]] || {
        rti_doctor_bundle_die "$interpreter is required by $RTI_DOCTOR_BUNDLE_PYTHON_TAG; install it and rerun."
        return 1
    }
    printf '%s\n' "$resolved"
}