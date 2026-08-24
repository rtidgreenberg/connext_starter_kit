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
RTI_MICRO = "RTI Connext DDS Micro"
OPENSPLICE = "ADLINK/Vortex OpenSplice"
OPENDDS = "OpenDDS"
FASTDDS = "eProsima Fast DDS"
CYCLONE = "Eclipse Cyclone DDS"

#: Two-octet RTPS vendor id -> display name.
VENDOR_NAMES = {
    (0x01, 0x01): RTI,
    (0x01, 0x02): OPENSPLICE,
    (0x01, 0x0A): RTI_MICRO,
    (0x01, 0x03): OPENDDS,
    (0x01, 0x0F): FASTDDS,
    (0x01, 0x10): CYCLONE,
}

#: Vendors rti_doctor is validated against. Others are recognized but untested.
#: Micro is deliberately absent: recognizing its vendor id is not the same as
#: having measured against it.
VALIDATED = (CYCLONE, FASTDDS)

#: Every RTPS vendor id belonging to an RTI product. `is_rti` stays 01.01 alone
#: because what it gates - reporting `product_version`, an RTI Core discovery
#: extension - is true of Core and not established for Micro. What must cover
#: the whole family is `is_foreign`: it drives an action, and offering a
#: "cross-vendor" TypeObject matrix against RTI Connext Micro would be running
#: a cross-vendor experiment against RTI. `docs/CODE_REVIEW_2026-08-04.md`
#: recorded 01.0A as unmapped while it was only a naming gap; a gate inverted it
#: into a wrong answer.
RTI_VENDOR_IDS = ((0x01, 0x01), (0x01, 0x0A))

#: RTPS VENDORID_UNKNOWN: the wire saying "not stated". Not a vendor.
VENDORID_UNKNOWN = (0x00, 0x00)

#: Vendors for which an empty DATA_REPRESENTATION advertisement from a *writer*
#: has been measured to mean XCDR1, rather than "said nothing".
#:
#: This list is the scope of the Q3 decision and must not be widened by
#: inference. Both entries were measured against live middleware, writer by
#: writer: a writer that never sets the policy advertises an empty sequence,
#: that pair matches an XCDR1 reader and delivers, and an XCDR2-only reader
#: refuses it with `requested_incompatible_qos` naming DataRepresentation.
#: RTI in `test/test_data_representation_spike.py`, Fast DDS in
#: `test/test_fastdds_representation_spike.py`.
#:
#: Cyclone is deliberately absent. Its README documents resolving an unspecified
#: policy from the type's defaults, which can select **XCDR2** - the opposite
#: meaning from the identical wire state - and that has not been measured here.
#: A Cyclone writer therefore still declines the comparison rather than being
#: assumed to match RTI's semantics. See Q3 in `docs/DESIGN_DECISIONS.md` and
#: backlog `REP-1`.
EMPTY_REPRESENTATION_MEANS_XCDR1 = (RTI, FASTDDS)

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


def is_fastdds(vendor_id):
  """True for an eProsima Fast DDS peer.

  The product version read from packets is a Fast DDS vendor-specific discovery
  PID, so this is what decides whether that evidence describes a given peer at
  all. An unreadable vendor id returns False: attributing a version to a peer
  whose vendor could not be determined is the misattribution this guards.
  """
  return vendor_octets(vendor_id) == (0x01, 0x0F)


def is_rti_family(vendor_id):
  """True for any RTI product's vendor id, Core or Micro.

  Separate from `is_rti` on purpose - see `RTI_VENDOR_IDS`.
  """
  return vendor_octets(vendor_id) in RTI_VENDOR_IDS


def is_foreign(vendor_id):
  """True for a peer whose vendor id is readable and belongs to no RTI product.

  What the cross-vendor experiments turn on. They are about a Connext observer
  reading another implementation's type metadata, so the question is "not us",
  not which vendor it is - the runner behind them applies XTypes and TypeObject
  profiles to this participant and does nothing vendor-specific.

  An unreadable vendor id returns False, the same misattribution guard
  `is_fastdds` carries: offering a cross-vendor experiment on the strength of a
  vendor that could not be determined claims more than the evidence supports.
  RTPS `VENDORID_UNKNOWN` (00.00) is refused for that same reason and not
  because it is unrecognized - it is the wire saying "not stated", which is a
  vendor we do not know rather than a vendor that is not RTI.
  """
  octets = vendor_octets(vendor_id)
  if octets is None or octets == VENDORID_UNKNOWN:
    return False
  return octets not in RTI_VENDOR_IDS


def is_recognized(vendor_id):
  return vendor_octets(vendor_id) in VENDOR_NAMES


def is_validated(vendor_id):
  """True when rti_doctor's test suite actually covers this vendor."""
  return vendor_name(vendor_id) in VALIDATED


def empty_representation_means_xcdr1(vendor_id):
  """True when this vendor's empty writer advertisement is known to mean XCDR1.

  False for an unrecognized vendor id as well as for Cyclone, so an unknown peer
  declines the comparison rather than inheriting RTI's semantics by default.
  """
  return vendor_name(vendor_id) in EMPTY_REPRESENTATION_MEANS_XCDR1


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
