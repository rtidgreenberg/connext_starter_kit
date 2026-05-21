#!/usr/bin/env python3
"""Environment helpers for the Recording Service GUI tools."""

import glob
import importlib.metadata
import os
import re
import sys

PREFERRED_CONNEXT_VERSION = "7.6.0"
LICENSE_ENV_VAR = "RTI_LICENSE_FILE"
PYTHON_PACKAGE_NAME = "rti.connext"
PYTHON_DISTRIBUTION_NAMES = (
    PYTHON_PACKAGE_NAME,
    "rti-connext",
    "rti_connext",
)
GENERATED_TYPES_STAMP = ".generated_from_nddshome"


def detect_nddshome() -> str:
    """Auto-detect NDDSHOME, preferring the Connext version used by this GUI."""
    env = os.environ.get("NDDSHOME")
    if env and os.path.isdir(env):
        return env

    preferred = os.path.expanduser(
        f"~/rti_connext_dds-{PREFERRED_CONNEXT_VERSION}")
    if os.path.isdir(preferred):
        return preferred

    candidates = sorted(glob.glob(os.path.expanduser("~/rti_connext_dds-*")))
    if candidates:
        return candidates[-1]
    return ""


def _license_candidates(nddshome: str = None):
    if nddshome:
        yield os.path.join(nddshome, "rti_license.dat")

    detected_nddshome = detect_nddshome()
    if detected_nddshome and detected_nddshome != nddshome:
        yield os.path.join(detected_nddshome, "rti_license.dat")

    yield os.path.expanduser("~/.rti/rti_license.dat")
    yield os.path.expanduser("~/rti_license.dat")


def detect_rti_license(nddshome: str = None) -> str:
    """Return the active or discovered RTI license source, if any."""
    env = os.environ.get(LICENSE_ENV_VAR)
    if env:
        return env

    for candidate in _license_candidates(nddshome):
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def ensure_rti_license(nddshome: str = None) -> str:
    """Set RTI_LICENSE_FILE from a detected license file when possible."""
    license_source = detect_rti_license(nddshome)
    if license_source and not os.environ.get(LICENSE_ENV_VAR):
        os.environ[LICENSE_ENV_VAR] = license_source
    return license_source


def detect_connext_python_version() -> str:
    """Return the installed rti.connext package version, if available."""
    for distribution_name in PYTHON_DISTRIBUTION_NAMES:
        try:
            return importlib.metadata.version(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return ""


def connext_version_from_nddshome(nddshome: str) -> str:
    """Return the Connext version encoded in an NDDSHOME path, if present."""
    if not nddshome:
        return ""
    match = re.search(r"rti_connext_dds-([0-9]+(?:\.[0-9]+){1,3})", nddshome)
    return match.group(1) if match else ""


def write_generated_types_stamp(xml_types_dir: str, nddshome: str,
                                version: str = None) -> str:
    """Write metadata tying generated XML artifacts to a Connext install."""
    os.makedirs(xml_types_dir, exist_ok=True)
    version = version or connext_version_from_nddshome(nddshome)
    stamp_path = os.path.join(xml_types_dir, GENERATED_TYPES_STAMP)
    with open(stamp_path, "w", encoding="utf-8") as stamp:
        stamp.write(f"nddshome={os.path.realpath(nddshome)}\n")
        stamp.write(f"version={version}\n")
    return stamp_path


def read_generated_types_stamp(xml_types_dir: str) -> dict:
    """Read generated XML metadata written by setup.sh."""
    stamp_path = os.path.join(xml_types_dir, GENERATED_TYPES_STAMP)
    metadata = {}
    with open(stamp_path, "r", encoding="utf-8") as stamp:
        for line in stamp:
            key, sep, value = line.strip().partition("=")
            if sep:
                metadata[key] = value
    return metadata


def validate_generated_types(xml_types_dir: str, nddshome: str = None) -> dict:
    """Ensure generated XML types came from the active Connext install."""
    nddshome = nddshome or os.environ.get("NDDSHOME") or detect_nddshome()
    stamp_path = os.path.join(xml_types_dir, GENERATED_TYPES_STAMP)
    if not os.path.isfile(stamp_path):
        raise RuntimeError(
            f"Generated XML type metadata not found: {stamp_path}. "
            "Run services/recording_service_gui/setup.sh with the active "
            "NDDSHOME to regenerate xml_types/.")

    metadata = read_generated_types_stamp(xml_types_dir)
    expected_home = os.path.realpath(nddshome)
    actual_home = os.path.realpath(metadata.get("nddshome", ""))
    if actual_home != expected_home:
        raise RuntimeError(
            "Generated XML type files were created from a different Connext "
            f"install. Expected NDDSHOME {expected_home}, stamp has "
            f"{actual_home or '<missing>'}. Rerun "
            "services/recording_service_gui/setup.sh.")

    expected_version = connext_version_from_nddshome(nddshome)
    actual_version = metadata.get("version", "")
    if expected_version and actual_version and actual_version != expected_version:
        raise RuntimeError(
            "Generated XML type files were created from Connext "
            f"{actual_version}, but active NDDSHOME is {expected_version}. "
            "Rerun services/recording_service_gui/setup.sh.")

    return metadata


def configure_recording_service_xtypes_policy():
    """Configure the process-wide XTypes policy used by the GUI tools.

    The Connext XTypes compliance mask is process-wide, not reader-scoped.
    Recording Service monitoring uses evolved union types, so the GUI process
    accepts samples with unknown union discriminators and preserves the unknown
    discriminator instead of selecting a default branch.  Compatible
    ServiceAdmin request/reply traffic is unaffected by these bits.

    This helper is idempotent and intentionally does not restore the previous
    mask; call it during startup before creating DDS entities.
    """
    import rti.connextdds.compliance as compliance

    mask = compliance.get_xtypes_mask()
    mask = mask | compliance.XTypesMask.ACCEPT_UNKNOWN_DISCRIMINATOR_BIT
    mask = mask & compliance.XTypesMask.SELECT_DEFAULT_DISCRIMINATOR_BIT.flip()
    compliance.set_xtypes_mask(mask)
    return mask


def ensure_connext_python() -> str:
    """Validate that Python is using the expected Connext package version."""
    version = detect_connext_python_version()
    if not version:
        raise RuntimeError(
            f"Python package {PYTHON_PACKAGE_NAME} is not installed. "
            "Run connext_dds_env/bin/python -m pip install "
            f"{PYTHON_PACKAGE_NAME}=={PREFERRED_CONNEXT_VERSION}.")
    if not version.startswith(PREFERRED_CONNEXT_VERSION):
        raise RuntimeError(
            f"Expected {PYTHON_PACKAGE_NAME} {PREFERRED_CONNEXT_VERSION}, "
            f"but Python is using {version} from {sys.executable}. "
            "Run with connext_dds_env/bin/python or reactivate the venv.")
    return version


def license_setup_message(nddshome: str = None) -> str:
    """Return a concise setup hint for missing RTI license configuration."""
    install_hint = ""
    if nddshome:
        install_hint = f" or place rti_license.dat at {nddshome}/rti_license.dat"
    return (
        "RTI license source not found. Set RTI_LICENSE_FILE to your "
        f"rti_license.dat path{install_hint}."
    )
