"""RTPS vendor identification and per-vendor interop notes.

The vendor id table is normative (RTPS assigns these two-octet values). The
notes are advisory: each one is phrased as something to check, carries a source,
and is only worth trusting once observed against real traffic. Any note that
does not reproduce should be deleted rather than softened.

Vendor id is an implementation *hint*, not a capability declaration. In
particular ``product_version`` is an RTI extension and is meaningless for other
vendors, so it is only ever reported for RTI.
"""

from . import compat

RTI = "RTI Connext"
OPENSPLICE = "ADLINK/Vortex OpenSplice"
OPENDDS = "OpenDDS"
FASTDDS = "eProsima Fast DDS"
CYCLONE = "Eclipse Cyclone DDS"

#: Two-octet RTPS vendor id -> display name.
VENDOR_NAMES = {
    (0x01, 0x01): RTI,
    (0x01, 0x02): OPENSPLICE,
    (0x01, 0x03): OPENDDS,
    (0x01, 0x0F): FASTDDS,
    (0x01, 0x10): CYCLONE,
}

#: Vendors rti_doctor is validated against. Others are recognized but untested.
VALIDATED = (CYCLONE, FASTDDS)

#: Advisory notes, keyed by display name. Each entry is (severity_hint, text).
#: severity_hint is "info" or "warn"; checks decide the final Finding severity.
VENDOR_NOTES = {
    FASTDDS: [
        ("info",
         "Fast DDS type propagation is configurable. If this writer's type does "
         "not resolve, check whether the publisher enables TypeObject/"
         "TypeInformation propagation - a writer can be fully discoverable at "
         "the topic level while advertising no usable schema."),
        ("info",
         "Fast DDS is the ROS 2 default RMW, so a peer identified here may be a "
         "ROS 2 node. ROS 2 mangles topic names (rt/, rq/, rr/ prefixes) and "
         "uses its own type naming, which is expected, not a fault."),
    ],
    CYCLONE: [
        ("info",
          "RTPS vendor id 01.10 identifies the peer as Cyclone DDS, but does "
          "not provide an authoritative Cyclone product version. Treat any "
          "version-specific recommendation as a vendor-family hypothesis until "
          "the peer version is independently confirmed."),
         ("info",
          "Validated Cyclone-to-Connext control: if a Connext 7.7 reader sees "
          "this Cyclone writer but receives no user data, test TypeObject-v1-only "
          "participant propagation. Set a positive type_object_max_serialized_"
          "length, set type_code_max_serialized_length=0, and clear only the "
          "TYPE_LOOKUP_SERVICE builtin-channel bits from the Connext default QoS. "
          "This is advisory: prove the remedy from reciprocal user-data traffic."),
         ("info",
          "Inspect endpoint DataRepresentation and captured user-data "
          "encapsulation separately: discovery advertises what endpoints offer "
          "or request, while DATA encapsulation proves the selected XCDR/XCDR2 "
          "representation. The remote XTypes compliance mask is not carried in "
          "standard RTPS and cannot be recovered from discovery or one payload."),
    ],
    OPENDDS: [
        ("warn",
         "OpenDDS defaults to InfoRepo discovery, which emits no peer-to-peer "
         "RTPS SPDP at all. An OpenDDS participant is only discoverable here if "
         "it was explicitly configured for RTPS discovery. Untested by "
         "rti_doctor's own test suite."),
    ],
    OPENSPLICE: [
        ("info",
         "OpenSplice is recognized by vendor id but is not part of rti_doctor's "
         "validation matrix; treat findings against it as unverified."),
    ],
}


def vendor_octets(vendor_id):
  """Extract the two vendor octets, or None when unreadable.

  ``VendorId`` exposes ``value``; its length and element type have varied, so
  this normalizes defensively rather than indexing blindly.
  """
  raw = compat.get(vendor_id, "value", None)
  if raw is None:
    return None
  try:
    octets = [int(b) for b in raw]
  except TypeError:
    try:
      value = int(raw)
    except (TypeError, ValueError):
      return None
    octets = [(value >> 8) & 0xFF, value & 0xFF]
  except ValueError:
    return None

  if len(octets) < 2:
    return None
  # Some bindings expose a wider buffer; the vendor id is the first two octets.
  return (octets[0], octets[1])


def vendor_name(vendor_id):
  """Display name for a vendor id. Never guesses an unrecognized value."""
  octets = vendor_octets(vendor_id)
  if octets is None:
    return "unknown"
  name = VENDOR_NAMES.get(octets)
  if name:
    return name
  return f"unrecognized vendor ({octets[0]:02X}.{octets[1]:02X})"


def vendor_hex(vendor_id):
  octets = vendor_octets(vendor_id)
  if octets is None:
    return "unknown"
  return f"{octets[0]:02X}.{octets[1]:02X}"


def is_rti(vendor_id):
  return vendor_octets(vendor_id) == (0x01, 0x01)


def is_recognized(vendor_id):
  return vendor_octets(vendor_id) in VENDOR_NAMES


def is_validated(vendor_id):
  """True when rti_doctor's test suite actually covers this vendor."""
  return vendor_name(vendor_id) in VALIDATED


def notes_for(vendor_id):
  """Advisory notes for a vendor id; empty list when there are none."""
  return list(VENDOR_NOTES.get(vendor_name(vendor_id), ()))


def protocol_text(protocol_version):
  """Render an RTPS protocol version as "major.minor", or "unknown"."""
  major = compat.get_int(protocol_version, "major_version")
  minor = compat.get_int(protocol_version, "minor_version")
  if major is None or minor is None:
    return "unknown"
  return f"{major}.{minor}"


def product_text(product_version, vendor_id):
  """Product version, but only for RTI, where the field is meaningful."""
  if not is_rti(vendor_id):
    return None
  text = str(product_version) if product_version is not None else None
  return text or None
