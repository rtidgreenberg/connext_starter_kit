"""Version compatibility layer for Connext 6.1.2 / 7.3.x / 7.7.x.

rti_doctor reads a lot of QoS fields, discovery fields, and status counters, and
the available set differs across the three supported Connext versions. Rather
than sprinkle try/except around every access, every version-sensitive read goes
through this module.

The rule the whole tool follows: a field that does not exist on this Connext
version renders as "n/a (not available on <version>)" - never silently omitted,
and never replaced by an assumed value. A diagnostic that quietly invents a zero
is worse than one that admits it cannot see.

Known differences that matter (verified against 7.7.0 and 7.3.1 locally; 6.1.2
handled by feature detection only, as it was not available to test against):

- ``ParticipantBuiltinTopicData.partial_configuration`` is SPDP2-era (7.x).
- ``DiscoveryConfig.builtin_discovery_plugins`` only exists where SPDP2 does.
- ``DiscoveryConfig.request_types_filter`` is not present on older versions.
- ``DiscoveryConfig.endpoint_type_object_lb_serialization_threshold`` likewise.
- ``available_builtin_endpoints_ext`` / ``vendor_builtin_endpoints`` are newer.
- ``DataReaderCacheStatus`` gained many counters over time.
- ``SubscriptionBuiltinTopicData`` has NO ``type_consistency`` field on any of
  the three versions, despite what some documentation suggests - a reader's
  type-consistency requirement is not readable from discovery data here.
"""

import glob
import os
import platform
import sys

import rti.connextdds as dds

#: Sentinel distinguishing "field absent on this version" from a real ``None``.
MISSING = object()


# --- Version detection -------------------------------------------------------

def connext_version():
  """Best-effort Connext version string.

  ``rti.connextdds`` exposes no ``__version__``, so this parses NDDSHOME, which
  is how the launcher already selects the interpreter and wheel. Returns
  ``"unknown"`` rather than guessing when it cannot be determined.
  """
  ndds_home = os.environ.get("NDDSHOME", "")
  base = os.path.basename(ndds_home.rstrip("/"))
  prefix = "rti_connext_dds-"
  if base.startswith(prefix):
    return base[len(prefix):]
  return "unknown"


def version_tuple():
  """(major, minor, patch) ints, or None when the version is unknown."""
  raw = connext_version()
  if raw == "unknown":
    return None
  parts = raw.split(".")
  try:
    return tuple(int(p) for p in parts[:3])
  except ValueError:
    return None


def at_least(major, minor):
  """True when the detected version is >= major.minor. False when unknown.

  Callers must not use this to decide whether a field exists - use ``has()``
  for that. This is only for behavioral notes in reports.
  """
  ver = version_tuple()
  if ver is None:
    return False
  return (ver[0], ver[1]) >= (major, minor)


def na_text():
  """The exact string used wherever a counter is unavailable."""
  return f"n/a (not available on Connext {connext_version()})"


# --- Safe access -------------------------------------------------------------

def get(obj, name, default=MISSING):
  """Read ``obj.name``, returning ``default`` when absent or unreadable.

  Property access on the Connext Python bindings can raise (not just return
  None) when a field is unsupported for the entity's state, so this catches
  broadly on purpose.
  """
  if obj is None:
    return default
  try:
    value = getattr(obj, name)
  except Exception:
    return default
  return value


def first(obj, names, default=MISSING):
  """Return the first readable attribute among ``names``.

  Used where a field was renamed across versions.
  """
  for name in names:
    value = get(obj, name, MISSING)
    if value is not MISSING:
      return value
  return default


def has(obj, name):
  """True when ``obj.name`` is readable on this version."""
  return get(obj, name, MISSING) is not MISSING


def call(obj, name, default=MISSING, *args):
  """Read ``obj.name``, calling it when it is a method.

  Necessary because the DynamicType predicates (``is_aggregation_type``,
  ``is_collection_type``, ``is_keyed``, ``members``, ...) are *methods* on the
  Python bindings, not properties. Reading them without calling yields a bound
  method, which is always truthy - a subtle way to misclassify every member of
  every type.
  """
  value = get(obj, name, MISSING)
  if value is MISSING:
    return default
  if callable(value):
    try:
      return value(*args)
    except Exception:
      return default
  return value


def call_bool(obj, name):
  """Boolean form of :func:`call`, defaulting to False when unavailable."""
  value = call(obj, name, MISSING)
  if value is MISSING or value is None:
    return False
  return bool(value)


def to_int(value):
  """Coerce a Connext counter value to an int, or None if it is not numeric.

  Several status counters are not plain ints:

  * ``EventCount32``/``EventCount64`` wrap a ``total`` and a ``change`` - these
    are the *cumulative* counters, and ``total`` is the one a report wants.
  * ``SequenceNumber`` wraps a ``value``.

  Without this, ``int()`` raises on those wrappers and the counter renders as
  "not available on this version" even though the value is right there - a
  diagnostic claiming blindness it does not have.
  """
  if value is None or value is MISSING:
    return None
  if isinstance(value, bool):
    return int(value)
  try:
    return int(value)
  except (TypeError, ValueError):
    pass
  for attr in ("total", "value"):
    inner = get(value, attr, MISSING)
    if inner is not MISSING and inner is not None and inner is not value:
      try:
        return int(inner)
      except (TypeError, ValueError):
        continue
  return None


def get_int(obj, name):
  """Read an integer counter. Returns None only when genuinely unavailable."""
  value = get(obj, name, MISSING)
  if value is MISSING:
    return None
  return to_int(value)


def counter_text(obj, name):
  """Render a counter for a report: its value, or the n/a marker."""
  value = get_int(obj, name)
  return na_text() if value is None else str(value)


def snapshot(obj, names):
  """Read many counters at once into {name: int-or-None}.

  Preserves the requested order so report output is stable.
  """
  return {name: get_int(obj, name) for name in names}


# --- Bitmask-style status reasons -------------------------------------------

def reason_matches(reason, flag):
  """Test a SampleLostState / SampleRejectedState against a flag.

  These are bitset-like objects exposing ``test``/``test_any``, but they also
  support ``&`` and ``==`` depending on version, so try each in turn rather
  than assuming one works.
  """
  if reason is None or flag is None:
    return False
  try:
    return bool(reason & flag)
  except Exception:
    pass
  try:
    return bool(reason.test_any(flag))
  except Exception:
    pass
  try:
    return reason == flag
  except Exception:
    return False


def lost_reason_flag(name):
  """Look up a SampleLostState flag by name, or None if this version lacks it."""
  state = getattr(dds, "SampleLostState", None)
  return get(state, name, None)


def rejected_reason_flag(name):
  state = getattr(dds, "SampleRejectedState", None)
  return get(state, name, None)


def reason_text(reason):
  """Human-readable reason, falling back to repr rather than inventing a name."""
  if reason is None:
    return "unknown"
  for attr in ("name", "value"):
    value = get(reason, attr, MISSING)
    if value is not MISSING and value is not None:
      return str(value)
  return str(reason)


# --- Environment -------------------------------------------------------------

def configure_rti_environment():
  """Populate NDDSHOME and RTI_LICENSE_FILE when discoverable locally.

  Same behavior as rti_spy's configure_rti_environment(), so both tools resolve
  an install the same way.
  """
  ndds_home = os.environ.get("NDDSHOME", "")
  if not ndds_home:
    installs = sorted(glob.glob(os.path.expanduser("~/rti_connext_dds-*")))
    if installs:
      ndds_home = installs[-1]
      os.environ["NDDSHOME"] = ndds_home

  if not os.environ.get("RTI_LICENSE_FILE") and ndds_home:
    license_path = os.path.join(ndds_home, "rti_license.dat")
    if os.path.isfile(license_path):
      os.environ["RTI_LICENSE_FILE"] = license_path


def environment_info():
  """Facts for the shareable report's header. Everything here is observed."""
  return {
      "host": platform.node() or "unknown",
      "os": f"{platform.system()} {platform.release()}",
      "machine": platform.machine(),
      "python": platform.python_version(),
      "connext": connext_version(),
      "nddshome": os.environ.get("NDDSHOME", "unset"),
      "license_file": os.environ.get("RTI_LICENSE_FILE", "unset"),
      "argv": " ".join(sys.argv),
  }


# --- XTypes compliance mask --------------------------------------------------
#
# Connext's DEFAULT XTypes compliance mask (0x18C on 7.7.0) is deliberately NOT
# fully OMG XTypes 1.3 compliant: it preserves selected legacy Connext encoding
# behavior. RTI's own cross-vendor guidance is to use the VENDOR mask (0x1A9)
# when interoperating with implementations like Cyclone DDS and Fast DDS, either
# via NDDS_XTYPES_COMPLIANCE_MASK=0x000001a9 or the compliance API.
#
# rti_doctor sets the VENDOR mask for its own process before creating any entity,
# because a diagnostic must not fail to decode a peer for a reason that is its own
# configuration. The mask actually in force is recorded in every report, so a
# finding can always be judged against how it was measured.
#
# Caveat established by testing: setting the vendor mask did NOT by itself fix an
# observed Cyclone DDS case where no user data arrived. The compliance mask
# governs serialization/deserialization, not whether a peer decides to match, so
# it should not be presented as a cure for "matched but no data".

def _xtypes_mask_module():
  return getattr(dds, "compliance", None)


def xtypes_mask_text():
  """The mask currently in force, as hex, or an explanation when unreadable."""
  module = _xtypes_mask_module()
  if module is None:
    return f"n/a (compliance API not available on Connext {connext_version()})"
  getter = get(module, "get_xtypes_mask", None)
  if not callable(getter):
    return f"n/a (no mask getter on Connext {connext_version()})"
  try:
    return hex(int(getter()))
  except Exception as e:
    return f"unreadable ({type(e).__name__})"


def set_vendor_xtypes_mask():
  """Apply the standards-compliant VENDOR XTypes mask. Returns a report dict.

  Must be called BEFORE any participant, topic, or endpoint is created: the mask
  affects entities created after it is set.
  """
  module = _xtypes_mask_module()
  result = {"requested": "VENDOR", "before": xtypes_mask_text(), "applied": False}

  if module is None:
    result["note"] = (f"compliance API not available on Connext "
                      f"{connext_version()}; set NDDS_XTYPES_COMPLIANCE_MASK="
                      f"0x000001a9 in the environment instead")
    return result

  mask_class = get(module, "XTypesMask", None)
  vendor = get(mask_class, "VENDOR", None)
  setter = get(module, "set_xtypes_mask", None)
  if vendor is None or not callable(setter):
    result["note"] = "VENDOR mask or setter unavailable on this version"
    return result

  try:
    setter(vendor)
    result["applied"] = True
  except Exception as e:
    result["note"] = f"could not set mask: {type(e).__name__}: {e}"
    return result

  result["after"] = xtypes_mask_text()
  return result
