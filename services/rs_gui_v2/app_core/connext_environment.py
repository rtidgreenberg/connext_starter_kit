"""Connext environment helpers owned by rs_gui_v2."""

import glob
import os
import re


PREFERRED_CONNEXT_VERSION = "7.6.0"
LICENSE_ENV_VAR = "RTI_LICENSE_FILE"
GENERATED_TYPES_STAMP = ".generated_from_nddshome"


def detect_nddshome() -> str:
    """Find an RTI Connext installation, preferring the supported version."""
    env = os.environ.get("NDDSHOME")
    if env and os.path.isdir(env):
        return env

    preferred = os.path.expanduser(f"~/rti_connext_dds-{PREFERRED_CONNEXT_VERSION}")
    if os.path.isdir(preferred):
        return preferred

    candidates = sorted(glob.glob(os.path.expanduser("~/rti_connext_dds-*")))
    if candidates:
        return candidates[-1]
    return ""


def detect_rti_license(nddshome: str = "") -> str:
    """Return the configured or discoverable RTI license file path."""
    env = os.environ.get(LICENSE_ENV_VAR)
    if env:
        return env

    candidates = []
    if nddshome:
        candidates.append(os.path.join(nddshome, "rti_license.dat"))
    detected = detect_nddshome()
    if detected and detected != nddshome:
        candidates.append(os.path.join(detected, "rti_license.dat"))
    candidates.extend((
        os.path.expanduser("~/.rti/rti_license.dat"),
        os.path.expanduser("~/rti_license.dat"),
    ))

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def ensure_rti_license(nddshome: str = "") -> str:
    """Set RTI_LICENSE_FILE from a discoverable license file when possible."""
    license_file = detect_rti_license(nddshome)
    if license_file and not os.environ.get(LICENSE_ENV_VAR):
        os.environ[LICENSE_ENV_VAR] = license_file
    return license_file


def connext_version_from_nddshome(nddshome: str) -> str:
    """Extract a Connext version from a conventional NDDSHOME path."""
    match = re.search(r"rti_connext_dds-([0-9]+(?:\.[0-9]+){1,3})", nddshome or "")
    return match.group(1) if match else ""


def validate_generated_types(xml_types_dir: str, nddshome: str = "") -> None:
    """Validate generated XML metadata when a stamp file is present."""
    stamp_path = os.path.join(xml_types_dir, GENERATED_TYPES_STAMP)
    if not os.path.isfile(stamp_path):
        return

    metadata = {}
    with open(stamp_path, "r", encoding="utf-8") as stamp_file:
        for line in stamp_file:
            key, sep, value = line.strip().partition("=")
            if sep:
                metadata[key] = value

    nddshome = nddshome or detect_nddshome()
    expected_home = os.path.realpath(nddshome)
    actual_home = os.path.realpath(metadata.get("nddshome", ""))
    if expected_home and actual_home != expected_home:
        raise RuntimeError(
            "Generated XML type files were created from a different Connext "
            f"install. Expected NDDSHOME {expected_home}, stamp has "
            f"{actual_home or '<missing>'}. Rerun services/rs_gui_v2/setup.sh."
        )

    expected_version = connext_version_from_nddshome(nddshome)
    actual_version = metadata.get("version", "")
    if expected_version and actual_version and actual_version != expected_version:
        raise RuntimeError(
            "Generated XML type files were created from Connext "
            f"{actual_version}, but active NDDSHOME is {expected_version}. "
            "Rerun services/rs_gui_v2/setup.sh."
        )


def license_setup_message(nddshome: str = "") -> str:
    install_hint = f" or place rti_license.dat at {nddshome}/rti_license.dat" if nddshome else ""
    return (
        "RTI license source not found. Set RTI_LICENSE_FILE to your "
        f"rti_license.dat path{install_hint}."
    )