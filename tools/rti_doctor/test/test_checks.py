"""Unit tests for the check catalog, using fake discovery records.

Every check is a function over a CheckContext, so the whole catalog is testable
without a participant. These are the tests that would catch a check that fires on
a healthy system - the failure mode that makes a diagnostic tool useless.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import discovery, findings as f, probe, records, typewalk  # noqa: E402
from rti_doctor.checks import CheckContext, blind_spots, static_discovery  # noqa: E402
from rti_doctor.checks import probe_match, probe_payload  # noqa: E402
from rti_doctor.checks import qos_match, type_compat  # noqa: E402


# --- Fakes -------------------------------------------------------------------

class FakeProperty(dict):
  """Stands in for a PropertyQosPolicy, which behaves like a mapping."""


class FakeDiscovery:
  def __init__(self, initial_peers=(), accept_unknown_peers=True,
               multicast_receive_addresses=("239.255.0.1",)):
    self.initial_peers = list(initial_peers)
    self.accept_unknown_peers = accept_unknown_peers
    self.multicast_receive_addresses = list(multicast_receive_addresses)


class FakeDiscoveryConfig:
  def __init__(self, builtin_discovery_plugins=None):
    if builtin_discovery_plugins is not None:
      self.builtin_discovery_plugins = builtin_discovery_plugins


class FakePorts:
  def __init__(self, **overrides):
    defaults = {"port_base": 7400, "domain_id_gain": 250, "participant_id_gain": 2,
                "builtin_multicast_port_offset": 0, "builtin_unicast_port_offset": 10,
                "user_multicast_port_offset": 1, "user_unicast_port_offset": 11}
    defaults.update(overrides)
    for name, value in defaults.items():
      setattr(self, name, value)


class FakeWireProtocol:
  def __init__(self, ports=None):
    self.rtps_well_known_ports = ports or FakePorts()


class FakeQos:
  """Minimal stand-in for DomainParticipantQos."""

  def __init__(self, properties=None, discovery=None, discovery_config=None,
               wire_protocol=None):
    self.property = FakeProperty(properties or {})
    self.discovery = discovery or FakeDiscovery()
    self.discovery_config = discovery_config or FakeDiscoveryConfig()
    self.wire_protocol = wire_protocol or FakeWireProtocol()


class FakeVendorId:
  def __init__(self, octets):
    self.value = list(octets)


class FakeProtocolVersion:
  def __init__(self, major, minor):
    self.major_version = major
    self.minor_version = minor


class FakeLocator:
  def __init__(self, ip, port=7410, kind=1):
    self.address = [0] * 12 + [int(p) for p in ip.split(".")]
    self.port = port
    self.kind = kind


class FakeRegistry:
  def __init__(self, participants=None, endpoints=None):
    self.participants = {p.key: p for p in (participants or [])}
    self.endpoints = {e.key: e for e in (endpoints or [])}

  def endpoints_for(self, key):
    return [e for e in self.endpoints.values() if e.participant_key == key]

  def endpoints_on_topic(self, topic):
    return [e for e in self.endpoints.values() if e.topic_name == topic]

  def participant_for(self, endpoint):
    return self.participants.get(endpoint.participant_key)


def participant_record(**kwargs):
  defaults = dict(key="p1", name="peer", ip="10.0.0.9",
                  vendor_id=FakeVendorId((0x01, 0x0F)),
                  protocol_version=FakeProtocolVersion(2, 3),
                  default_unicast_locators=[FakeLocator("10.0.0.9")])
  defaults.update(kwargs)
  return records.ParticipantRecord(**defaults)


def endpoint_record(**kwargs):
  defaults = dict(key="e1", kind="Writer", participant_key="p1",
                  topic_name="T", type_name="MyType")
  defaults.update(kwargs)
  return records.EndpointRecord(**defaults)


def ids(result):
  return sorted({x.id for x in result})


# --- Blind spots -------------------------------------------------------------

class TestBlindSpots(unittest.TestCase):

  def test_clean_config_produces_no_blind_spot_errors(self):
    """The most important test here: a healthy config must stay silent."""
    context = CheckContext(own_qos=FakeQos(), registry=FakeRegistry([participant_record()]),
                           domain_id=1)
    result = [x for x in blind_spots.CHECKS for x in x(context)]
    errors = [x for x in result if x.severity >= f.Severity.ERROR]
    self.assertEqual(errors, [], f"healthy config produced {ids(errors)}")

  def test_domain_tag_fires(self):
    qos = FakeQos(properties={"dds.domain_participant.domain_tag": "prod"})
    result = blind_spots.check_domain_tag(CheckContext(own_qos=qos))
    self.assertEqual(ids(result), ["blind.domain_tag"])
    self.assertEqual(result[0].severity, f.Severity.ERROR)

  def test_empty_domain_tag_does_not_fire(self):
    qos = FakeQos(properties={"dds.domain_participant.domain_tag": ""})
    self.assertEqual(blind_spots.check_domain_tag(CheckContext(own_qos=qos)), [])

  def test_spdp2_fires(self):
    qos = FakeQos(discovery_config=FakeDiscoveryConfig("SPDP2_DISCOVERY"))
    result = blind_spots.check_spdp2(CheckContext(own_qos=qos))
    self.assertEqual(ids(result), ["blind.spdp2"])

  def test_standard_spdp_does_not_fire(self):
    qos = FakeQos(discovery_config=FakeDiscoveryConfig("SDP"))
    self.assertEqual(blind_spots.check_spdp2(CheckContext(own_qos=qos)), [])

  def test_missing_plugin_field_does_not_fire(self):
    """On a version without the field, SPDP2 cannot be enabled at all."""
    qos = FakeQos(discovery_config=FakeDiscoveryConfig(None))
    self.assertEqual(blind_spots.check_spdp2(CheckContext(own_qos=qos)), [])

  def test_accept_unknown_peers_disabled_fires(self):
    qos = FakeQos(discovery=FakeDiscovery(accept_unknown_peers=False))
    result = blind_spots.check_accept_unknown_peers(CheckContext(own_qos=qos))
    self.assertEqual(ids(result), ["blind.unknown_peers_rejected"])

  def test_nonstandard_ports_fire(self):
    qos = FakeQos(wire_protocol=FakeWireProtocol(FakePorts(port_base=8400)))
    result = blind_spots.check_nonstandard_ports(CheckContext(own_qos=qos))
    self.assertEqual(ids(result), ["blind.nonstandard_ports"])
    self.assertEqual(result[0].severity, f.Severity.WARN)
    self.assertIn("8400", result[0].observed)

  def test_default_ports_do_not_fire(self):
    result = blind_spots.check_nonstandard_ports(CheckContext(own_qos=FakeQos()))
    self.assertEqual(result, [])

  def test_local_multicast_defaults_are_not_diagnosed(self):
    """Our own multicast config says nothing about the deployed system.

    rti_doctor runs with multicast-enabled defaults, so a finding derived from
    its own participant QoS reported the tool's configuration as evidence
    about the peers it is there to diagnose. Remote reachability is not
    observable from local QoS at all.
    """
    qos = FakeQos(discovery=FakeDiscovery(multicast_receive_addresses=()))
    context = CheckContext(own_qos=qos, registry=FakeRegistry([participant_record()]),
                           domain_id=1)
    result = [x for check in blind_spots.CHECKS for x in check(context)]
    self.assertNotIn("blind.no_multicast_no_peers", ids(result))

  def test_empty_domain_fires_with_no_participants(self):
    context = CheckContext(registry=FakeRegistry([]), domain_id=7)
    result = blind_spots.check_empty_domain(context)
    self.assertEqual(ids(result), ["blind.empty_domain"])

  def test_empty_domain_silent_when_participants_exist(self):
    context = CheckContext(registry=FakeRegistry([participant_record()]), domain_id=7)
    self.assertEqual(blind_spots.check_empty_domain(context), [])

  def test_other_domain_active_fires_only_after_a_scan(self):
    registry = FakeRegistry([])
    unscanned = CheckContext(registry=registry, domain_id=1, active_domains={5},
                             domain_scan_ran=False)
    self.assertEqual(blind_spots.check_other_domain_active(unscanned), [])
    scanned = CheckContext(registry=registry, domain_id=1, active_domains={5},
                           domain_scan_ran=True)
    result = blind_spots.check_other_domain_active(scanned)
    self.assertEqual(ids(result), ["blind.other_domain_active"])
    self.assertIn("5", result[0].title)

  def test_other_domain_ignores_the_selected_domain(self):
    context = CheckContext(registry=FakeRegistry([]), domain_id=5,
                           active_domains={5}, domain_scan_ran=True)
    self.assertEqual(blind_spots.check_other_domain_active(context), [])


# --- Static discovery --------------------------------------------------------

class TestStaticDiscovery(unittest.TestCase):

  def test_healthy_writer_does_not_report_missing_multicast_locator(self):
    """Writer publication data does not advertise multicast locators."""
    result = [finding for check in static_discovery.CHECKS
              for finding in check(CheckContext(endpoint=endpoint_record()))]
    self.assertNotIn("locator.no_multicast", ids(result))

  def test_vendor_identified(self):
    context = CheckContext(participant_record=participant_record())
    result = static_discovery.check_vendor_identify(context)
    self.assertEqual(ids(result), ["vendor.identify"])
    self.assertIn("Fast DDS", result[0].title)

  def test_unrecognized_vendor_warns_and_does_not_guess(self):
    record = participant_record(vendor_id=FakeVendorId((0x09, 0x99)))
    result = static_discovery.check_vendor_identify(
        CheckContext(participant_record=record))
    self.assertEqual(result[0].severity, f.Severity.WARN)
    self.assertIn("unrecognized", result[0].observed.lower())

  def test_cyclone_notes_are_advisory_and_include_observer_limits(self):
    record = participant_record(vendor_id=FakeVendorId((0x01, 0x10)))
    result = static_discovery.check_vendor_notes(
        CheckContext(participant_record=record))
    self.assertEqual(ids(result), ["vendor.known_issues"])
    self.assertTrue(all(item.severity == f.Severity.INFO for item in result))
    observed = " ".join(item.observed for item in result)
    self.assertIn("TypeObject-v1-only", observed)
    self.assertIn("not carried in standard RTPS", observed)
    self.assertIn("not provide an authoritative Cyclone product version", observed)

  def test_shared_memory_locator_is_not_judged_as_an_ip(self):
    """Regression: a SHMEM locator carries 0.0.0.0 and must not be flagged."""
    record = participant_record(
        default_unicast_locators=[FakeLocator("203.0.113.9", kind=1),
                                  FakeLocator("0.0.0.0", kind=16777216)])
    result = static_discovery.check_locators(
        CheckContext(participant_record=record, endpoint=endpoint_record()))
    self.assertEqual(result, [], "SHMEM locator produced a false unroutable finding")

  def test_link_local_address_is_flagged(self):
    record = participant_record(
        default_unicast_locators=[FakeLocator("169.254.3.4", kind=1)])
    result = static_discovery.check_locators(
        CheckContext(participant_record=record, endpoint=endpoint_record()))
    self.assertEqual(ids(result), ["locator.unroutable"])
    self.assertIn("link-local", result[0].observed)

  def test_no_locators_at_all_is_flagged(self):
    record = participant_record(default_unicast_locators=[])
    result = static_discovery.check_locators(
        CheckContext(participant_record=record, endpoint=endpoint_record()))
    self.assertEqual(ids(result), ["locator.unroutable"])

  def test_participant_with_no_endpoints_is_flagged(self):
    record = participant_record()
    context = CheckContext(registry=FakeRegistry([record]), participant_record=record)
    result = static_discovery.check_no_endpoints(context)
    self.assertEqual(ids(result), ["endpoint.none"])

  def test_participant_with_endpoints_is_silent(self):
    record = participant_record()
    registry = FakeRegistry([record], [endpoint_record()])
    context = CheckContext(registry=registry, participant_record=record)
    self.assertEqual(static_discovery.check_no_endpoints(context), [])


# --- Type resolution ---------------------------------------------------------

class FakeDynamicType:
  """Only what the checks touch: a name and an assignability answer."""

  def __init__(self, name, assignable=True):
    self.name = name
    self._assignable = assignable
    self.extensibility_kind = None

  def is_assignable_from(self, other):
    return self._assignable

  def members(self):
    return []

  def is_aggregation_type(self):
    return True

  def is_collection_type(self):
    return False


class UnevaluableType(FakeDynamicType):
  """A resolved type whose binding offers no structural comparison.

  The cross-vendor case: the type is present and named, but nothing can be
  asked of it. Shadowing the method with a non-callable is what a binding that
  does not implement it looks like to `compat.get`.
  """

  def __init__(self, name):
    super().__init__(name)
    self.is_assignable_from = None


class RaisingType(FakeDynamicType):
  """A binding whose assignability call fails rather than answering."""

  def is_assignable_from(self, other):
    raise RuntimeError("binding refused the comparison")


class TestTypeState(unittest.TestCase):

  def test_pending_is_informational_not_an_error(self):
    """A type still resolving must not be reported as unavailable."""
    endpoint = endpoint_record(type_state=records.TYPE_PENDING)
    result = type_compat.check_type_state(
        CheckContext(endpoint=endpoint, type_wait=5.0))
    self.assertEqual(result[0].severity, f.Severity.INFO)
    self.assertIn("still in flight", result[0].title)

  def test_unavailable_is_an_error_and_lists_causes(self):
    endpoint = endpoint_record(type_state=records.TYPE_UNAVAILABLE)
    context = CheckContext(endpoint=endpoint, type_wait=5.0,
                           type_lookup_settings={"request_types_filter": "*"})
    result = type_compat.check_type_state(context)
    self.assertEqual(result[0].severity, f.Severity.ERROR)
    self.assertEqual(result[0].id, "type.no_type_info")
    self.assertIn("TypeLookup", result[0].root_cause)

  def test_fastdds_unavailable_recommends_upgrading_first(self):
    endpoint = endpoint_record(type_state=records.TYPE_UNAVAILABLE,
                               vendor_id=FakeVendorId((0x01, 0x0F)))
    result = type_compat.check_type_state(CheckContext(endpoint=endpoint))
    self.assertIn("upgrade that publisher to Fast DDS 3.6.2 or newer",
                  result[0].remedy)

  @mock.patch("rti_doctor.compat.connext_version", return_value="7.3.1")
  def test_fastdds_dynamic_type_on_connext_73_recommends_connext_77(self, _version):
    endpoint = endpoint_record(type_state=records.TYPE_UNAVAILABLE,
                               vendor_id=FakeVendorId((0x01, 0x0F)))
    finding = type_compat.check_type_state(CheckContext(
        endpoint=endpoint, type_information_observed=True))[0]
    self.assertIn("local Connext runtime to 7.7 or newer", finding.remedy)
    self.assertIn("Recording Service needs the runtime schema", finding.remedy)
    self.assertIn("PID_TYPE_INFORMATION", finding.remedy)

  @mock.patch("rti_doctor.compat.connext_version", return_value="7.3.1")
  def test_fastdds_without_type_information_has_no_connext_77_advice(self, _version):
    endpoint = endpoint_record(type_state=records.TYPE_UNAVAILABLE,
                               vendor_id=FakeVendorId((0x01, 0x0F)))
    finding = type_compat.check_type_state(CheckContext(endpoint=endpoint))[0]
    self.assertNotIn("local Connext runtime to 7.7 or newer", finding.remedy)

  @mock.patch("rti_doctor.compat.connext_version", return_value="7.7.0")
  def test_fastdds_dynamic_type_on_connext_77_has_no_upgrade_advice(self, _version):
    endpoint = endpoint_record(type_state=records.TYPE_UNAVAILABLE,
                               vendor_id=FakeVendorId((0x01, 0x0F)))
    finding = type_compat.check_type_state(CheckContext(
        endpoint=endpoint, type_information_observed=True))[0]
    self.assertNotIn("local Connext runtime to 7.7 or newer",
                     finding.remedy)

  def test_unavailable_type_on_a_writer_names_the_publisher(self):
    endpoint = endpoint_record(kind="Writer", type_state=records.TYPE_UNAVAILABLE)
    finding = type_compat.check_type_state(CheckContext(endpoint=endpoint))[0]
    self.assertEqual(finding.title, "No type information available for this writer")
    self.assertEqual(finding.evidence["endpoint_role"], "writer")
    self.assertIn("publisher that owns this writer", finding.remedy)
    self.assertNotIn("subscriber", finding.remedy)

  def test_unavailable_type_on_a_reader_names_the_subscriber(self):
    """The same check is reachable for either role from a focused run.

    Its ERROR used to be written exclusively for a writer, so targeting a
    DataReader whose schema never resolved sent the operator to a publisher
    that may be entirely healthy.
    """
    endpoint = endpoint_record(kind="Reader", type_state=records.TYPE_UNAVAILABLE)
    finding = type_compat.check_type_state(CheckContext(endpoint=endpoint))[0]
    self.assertEqual(finding.title, "No type information available for this reader")
    self.assertEqual(finding.evidence["endpoint_role"], "reader")
    self.assertIn("subscriber that owns this reader", finding.remedy)
    self.assertNotIn("publisher", finding.remedy)
    # The claim is about this endpoint's schema and no other.
    self.assertIn("other side of the topic", finding.root_cause)

  def test_fastdds_reader_upgrade_advice_names_the_subscriber(self):
    endpoint = endpoint_record(kind="Reader", type_state=records.TYPE_UNAVAILABLE,
                               vendor_id=FakeVendorId((0x01, 0x0F)))
    finding = type_compat.check_type_state(CheckContext(endpoint=endpoint))[0]
    self.assertIn("upgrade that subscriber to Fast DDS 3.6.2 or newer",
                  finding.remedy)

  def test_other_vendor_unavailable_does_not_get_fastdds_advice(self):
    endpoint = endpoint_record(type_state=records.TYPE_UNAVAILABLE,
                               vendor_id=FakeVendorId((0x01, 0x10)))
    result = type_compat.check_type_state(CheckContext(endpoint=endpoint))
    self.assertNotIn("Fast DDS 3.6.2", result[0].remedy)

  def test_our_own_filter_is_named_first_when_it_could_be_our_fault(self):
    endpoint = endpoint_record(type_state=records.TYPE_UNAVAILABLE)
    context = CheckContext(endpoint=endpoint, type_wait=5.0,
                           type_lookup_settings={"request_types_filter": "n/a"})
    result = type_compat.check_type_state(context)
    self.assertIn("on our side", result[0].root_cause)

  def test_resolved_is_ok(self):
    endpoint = endpoint_record(type_state=records.TYPE_RESOLVED)
    result = type_compat.check_type_state(CheckContext(endpoint=endpoint))
    self.assertEqual(result[0].severity, f.Severity.OK)

  def test_name_conflict_detected(self):
    a = endpoint_record(key="a", type_name="TypeA")
    b = endpoint_record(key="b", type_name="TypeB")
    context = CheckContext(endpoint=a, registry=FakeRegistry([], [a, b]))
    result = type_compat.check_type_name_conflict(context)
    self.assertEqual(ids(result), ["type.name_conflict"])

  def test_same_name_is_no_conflict(self):
    a = endpoint_record(key="a", type_name="Same")
    b = endpoint_record(key="b", type_name="Same")
    context = CheckContext(endpoint=a, registry=FakeRegistry([], [a, b]))
    self.assertEqual(type_compat.check_type_name_conflict(context), [])

  def test_name_conflict_names_every_endpoint_on_the_topic(self):
    """Topic scope must withhold identity from the key, not from the reader.

    The issue key is built from the singular identity fields; these plural
    ones are what the Health column and the `i` filter read, so the condition
    stays one issue and is still reachable from each row involved in it.
    """
    writer = endpoint_record(key="w1", kind="Writer", participant_key="pw",
                             type_name="Sensor")
    reader = endpoint_record(key="r1", kind="Reader", participant_key="pr",
                             type_name="sensors::Sensor")
    context = CheckContext(endpoint=writer,
                           registry=FakeRegistry([], [writer, reader]))
    evidence = type_compat.check_type_name_conflict(context)[0].evidence
    self.assertEqual(evidence["scope"], "topic")
    self.assertEqual(evidence["linked_writer_keys"], ["w1"])
    self.assertEqual(evidence["linked_reader_keys"], ["r1"])
    self.assertEqual(evidence["linked_participant_keys"], ["pr", "pw"])
    # Not under the names _issue_key reads, or one condition becomes one
    # issue per endpoint again.
    self.assertNotIn("writer_key", evidence)
    self.assertNotIn("endpoint_key", evidence)

  def test_assignability_failure_reported_directionally(self):
    writer = endpoint_record(key="writer", kind="Writer", type_name="WriterType",
                             type=FakeDynamicType("WriterType", assignable=True))
    reader = endpoint_record(key="reader", kind="Reader", type_name="ReaderType",
                             type=FakeDynamicType("ReaderType", assignable=False))
    context = CheckContext(endpoint=writer, registry=FakeRegistry([], [writer, reader]))
    result = type_compat.check_assignability(context)
    self.assertEqual(ids(result), ["type.assignability"])
    self.assertEqual(result[0].severity, f.Severity.ERROR)
    self.assertIn("ReaderType <- WriterType = False", result[0].observed)

  def test_assignable_writer_and_reader_are_confirmed(self):
    writer = endpoint_record(key="writer", kind="Writer",
                             type=FakeDynamicType("Writer", True))
    reader = endpoint_record(key="reader", kind="Reader",
                             type=FakeDynamicType("Reader", True))
    context = CheckContext(endpoint=writer, registry=FakeRegistry([], [writer, reader]))
    result = type_compat.check_assignability(context)
    self.assertEqual(ids(result), ["type.assignability"])
    self.assertEqual(result[0].severity, f.Severity.OK)

  def test_ok_separates_evaluated_readers_from_resolved_readers(self):
    """An all-clear must not report the evaluated count under a resolved label.

    Two of three resolved readers expose no is_assignable_from(), so only one
    was actually compared - and "every resolved reader accepts this writer
    (1 reader)" is an all-clear covering a third of the topic.
    """
    writer = endpoint_record(key="writer", kind="Writer", type_name="WriterType",
                             type=FakeDynamicType("WriterType", True))
    readers = [
        endpoint_record(key="r1", kind="Reader", type_name="Native",
                        type=FakeDynamicType("Native", True)),
        endpoint_record(key="r2", kind="Reader", type_name="Foreign",
                        type=UnevaluableType("Foreign")),
        endpoint_record(key="r3", kind="Reader", type_name="Broken",
                        type=RaisingType("Broken")),
    ]
    context = CheckContext(endpoint=writer,
                           registry=FakeRegistry([], [writer] + readers))
    finding = type_compat.check_assignability(context)[0]
    self.assertEqual(finding.severity, f.Severity.OK)
    self.assertEqual(finding.evidence["resolved_reader_count"], 3)
    self.assertEqual(finding.evidence["evaluated_reader_count"], 1)
    self.assertEqual(finding.evidence["unevaluable_reader_count"], 2)
    self.assertIn("1 of 3 resolved reader(s) evaluated", finding.observed)
    self.assertIn("Not evaluated (2 reader(s): Broken, Foreign)", finding.observed)
    reasons = {item["reader"]: item["reason"]
               for item in finding.evidence["readers_unevaluated"]}
    self.assertIn("no is_assignable_from()", reasons["Foreign"])
    self.assertIn("raised RuntimeError", reasons["Broken"])

  def test_wholly_unevaluable_readers_are_recorded_not_dropped(self):
    """No comparison at all must not look like a topic with no readers.

    Returning [] made "unknown" indistinguishable from "not applicable" on
    exactly the cross-vendor topic this tool exists to diagnose.
    """
    writer = endpoint_record(key="writer", kind="Writer", type_name="WriterType",
                             type=FakeDynamicType("WriterType", True))
    reader = endpoint_record(key="reader", kind="Reader", type_name="Foreign",
                             type=UnevaluableType("Foreign"))
    context = CheckContext(endpoint=writer,
                           registry=FakeRegistry([], [writer, reader]))
    finding = type_compat.check_assignability(context)[0]
    self.assertEqual(finding.id, "type.assignability")
    self.assertEqual(finding.severity, f.Severity.INFO)
    self.assertEqual(finding.evidence["evaluated_reader_count"], 0)
    self.assertEqual(finding.evidence["resolved_reader_count"], 1)
    # Topic-scoped: every writer on the topic faces the same unevaluable
    # readers, so the system census must not repeat it per writer.
    self.assertEqual(finding.evidence["scope"], "topic")

  def test_incompatible_verdict_still_discloses_what_it_could_not_read(self):
    writer = endpoint_record(key="writer", kind="Writer", type_name="WriterType",
                             type=FakeDynamicType("WriterType", True))
    readers = [
        endpoint_record(key="r1", kind="Reader", type_name="ReaderType",
                        type=FakeDynamicType("ReaderType", assignable=False)),
        endpoint_record(key="r2", kind="Reader", type_name="Foreign",
                        type=UnevaluableType("Foreign")),
    ]
    context = CheckContext(endpoint=writer,
                           registry=FakeRegistry([], [writer] + readers))
    finding = type_compat.check_assignability(context)[0]
    self.assertEqual(finding.severity, f.Severity.ERROR)
    self.assertIn("1 of 1 evaluated reader(s) reject this writer", finding.observed)
    self.assertIn("2 resolved on the topic", finding.observed)
    self.assertIn("Not evaluated (1 reader(s): Foreign)", finding.observed)
    self.assertEqual(finding.evidence["unevaluable_reader_count"], 1)

  def test_a_final_type_is_described_not_warned_about(self):
    """FINAL is a property of the IDL, not an observed failure.

    A WARN made is_problem True, so a type-design note entered the issue list
    and the nonzero exit path of a system whose every pair the tool had just
    confirmed assignable. The note itself is worth keeping in a targeted
    report; the severity was the overstatement.
    """
    endpoint = endpoint_record(key="w1", kind="Writer",
                               type=FakeDynamicType("Sensor"))
    context = CheckContext(endpoint=endpoint)
    with mock.patch.object(typewalk, "extensibility_map",
                           return_value={"Sensor": "FINAL"}):
      finding = type_compat.check_extensibility(context)[0]
    self.assertEqual(finding.id, "type.extensibility")
    self.assertEqual(finding.severity, f.Severity.INFO)
    self.assertFalse(finding.is_problem)
    self.assertIn("type.assignability", finding.root_cause)
    self.assertIn("not anything observed", finding.root_cause)

  def test_a_uniformly_extensible_type_stays_ok(self):
    endpoint = endpoint_record(key="w1", kind="Writer",
                               type=FakeDynamicType("Sensor"))
    context = CheckContext(endpoint=endpoint)
    with mock.patch.object(typewalk, "extensibility_map",
                           return_value={"Sensor": "APPENDABLE"}):
      finding = type_compat.check_extensibility(context)[0]
    self.assertEqual(finding.severity, f.Severity.OK)

  def test_reader_endpoint_does_not_duplicate_writer_monitoring(self):
    writer = endpoint_record(key="writer", kind="Writer",
                             type=FakeDynamicType("Writer", True))
    reader = endpoint_record(key="reader", kind="Reader",
                             type=FakeDynamicType("Reader", True))
    context = CheckContext(endpoint=reader, registry=FakeRegistry([], [writer, reader]))
    self.assertEqual(type_compat.check_assignability(context), [])

  def test_empty_representation_is_not_reported_as_incompatible(self):
    """A default-QoS writer advertises an empty sequence; that is not a fault.

    OK rather than INFO: the system scan turns every non-OK finding into an
    issue, and this fires for every default-QoS writer on the domain. OK keeps
    it in a targeted report - which renders OK findings - without putting one
    entry per writer into the issue list.
    """
    endpoint = endpoint_record(representation=None)
    result = type_compat.check_representation(CheckContext(endpoint=endpoint))
    self.assertEqual(ids(result), ["repr.not_advertised"])
    self.assertEqual(result[0].severity, f.Severity.OK)
    self.assertFalse(result[0].is_problem)

  def test_not_advertised_does_not_contradict_the_rxo_verdict(self):
    """Q3: two adjacent findings must not disagree about the same emptiness.

    Before 2026-08-12 this finding said the emptiness "says nothing about what
    the writer supports, so NO incompatibility should be inferred from it".
    Once `qos_match` began inferring XCDR1 and raising an ERROR for exactly
    that, a single report asserted both at once. The text is now vendor-
    dependent, and this pins both branches.
    """
    class VendorId:
      def __init__(self, high, low):
        self.value = [high, low]

    class Empty:
      value = []

    measured = type_compat.check_representation(CheckContext(
        endpoint=endpoint_record(representation=Empty(),
                                 vendor_id=VendorId(0x01, 0x0F))))[0]
    self.assertIs(measured.evidence["empty_means_xcdr1"], True)
    self.assertIn("XCDR1", measured.root_cause)
    self.assertNotIn("NO incompatibility", measured.root_cause)

    unmeasured = type_compat.check_representation(CheckContext(
        endpoint=endpoint_record(representation=Empty(),
                                 vendor_id=VendorId(0x01, 0x10))))[0]
    self.assertIs(unmeasured.evidence["empty_means_xcdr1"], False)
    self.assertIn("NO incompatibility", unmeasured.root_cause)
    # Both stay OK: the ERROR, when there is one, belongs to the pair check.
    for finding in (measured, unmeasured):
      self.assertEqual(finding.severity, f.Severity.OK)

  def test_an_unreadable_policy_is_not_an_advertised_empty_sequence(self):
    """`representation_ids` returns [] for both, and only one has a meaning.

    An absent policy object is unreadable input. Treating it as the measured
    empty advertisement would claim XCDR1 about an endpoint that said nothing
    readable at all - Q1 and Q2 in a new place - so it must decline whatever
    the vendor is.
    """
    class VendorId:
      value = [0x01, 0x0F]  # Fast DDS: measured, and still must not apply.

    finding = type_compat.check_representation(CheckContext(
        endpoint=endpoint_record(representation=None,
                                 vendor_id=VendorId())))[0]
    self.assertIs(finding.evidence["empty_means_xcdr1"], False)
    self.assertEqual(finding.evidence["representation"], "unreadable")
    self.assertIn("could not be read", finding.observed)
    self.assertIn("NO incompatibility", finding.root_cause)
    self.assertEqual(finding.severity, f.Severity.OK)


class TestDiscoveryLifecycle(unittest.TestCase):

  def test_removing_participant_also_removes_its_endpoints(self):
    participant = participant_record(key="p1")
    endpoint = endpoint_record(key="w1", participant_key="p1")
    registry = discovery.DiscoveryRegistry()
    registry.upsert_participant(participant)
    registry.upsert_endpoint(endpoint)
    registry.remove_participant("p1")
    self.assertEqual(registry.participant_list(), [])
    self.assertEqual(registry.endpoint_list(), [])

  def test_removing_disposed_endpoint_excludes_it_from_sweeps(self):
    registry = discovery.DiscoveryRegistry()
    registry.upsert_endpoint(endpoint_record(key="w1", kind="Writer"))
    registry.remove_endpoint("w1")
    self.assertEqual(registry.writers(), [])

  def test_publication_listener_removes_an_invalid_builtin_sample(self):
    class Value:
      value = "w1"
    class Data:
      key = Value()
    class Info:
      valid = False
    class Reader:
      def take(self):
        return [(Data(), Info())]

    registry = discovery.DiscoveryRegistry()
    registry.upsert_endpoint(endpoint_record(key="w1", kind="Writer"))
    discovery.PublicationListener(registry).on_data_available(Reader())
    self.assertEqual(registry.writers(), [])


# --- Payload -----------------------------------------------------------------

class FakeProbe:
  def __init__(self, **kwargs):
    self.attempted = True
    self.created = True
    self.create_error = None
    self.matched_count = 1
    self.samples_taken = 1
    self.walk = None
    self.protocol = {}
    self.cache = {}
    self.sample_lost = None
    self.sample_rejected = None
    self.requested_incompatible_qos = None
    self.subscription_matched = None
    self.inconsistent_topic_count = 0
    self.applied_reader_qos = {}
    self.elapsed = 1.0
    self.listener_events = []
    # Default to the well-correlated single-writer case: the probe identified
    # the selected writer and it was the only one the reader matched.
    self.correlated = True
    self.matched_other_count = 0
    self.matched_unreadable_count = 0
    self.samples_other = 0
    self.__dict__.update(kwargs)

  @property
  def matched(self):
    return self.matched_count > 0


class TestPayloadChecks(unittest.TestCase):

  def test_dropped_fragments_alone_are_not_an_error(self):
    """Regression: healthy large data showed fragments=6/reassembled=6/dropped=6."""
    probe = FakeProbe(samples_taken=1, protocol={
        "received_fragment_count": 6, "reassembled_sample_count": 6,
        "dropped_fragment_count": 6, "sent_nack_fragment_count": 0})
    result = probe_payload.check_fragmentation(CheckContext(probe=probe))
    self.assertEqual(result[0].severity, f.Severity.INFO)

  def test_no_sample_and_no_reassembly_is_an_error(self):
    probe = FakeProbe(samples_taken=0, protocol={
        "received_fragment_count": 12, "reassembled_sample_count": 0,
        "dropped_fragment_count": 4, "sent_nack_fragment_count": 9})
    result = probe_payload.check_fragmentation(CheckContext(probe=probe))
    self.assertEqual(result[0].severity, f.Severity.ERROR)

  def test_no_fragmentation_is_silent(self):
    probe = FakeProbe(protocol={"received_fragment_count": 0})
    self.assertEqual(probe_payload.check_fragmentation(CheckContext(probe=probe)), [])

  def test_silent_with_heartbeats_blames_the_writer_not_the_path(self):
    probe = FakeProbe(samples_taken=0, protocol={
        "received_heartbeat_count": 20, "received_sample_count": 0,
        "received_gap_count": 0})
    result = probe_payload.check_silent(CheckContext(probe=probe))
    self.assertEqual(ids(result), ["data.silent"])
    self.assertIn("Heartbeats are arriving", result[0].root_cause)

  def test_silent_with_nothing_blames_the_data_path(self):
    probe = FakeProbe(samples_taken=0, protocol={
        "received_heartbeat_count": 0, "received_sample_count": 0})
    result = probe_payload.check_silent(CheckContext(probe=probe))
    self.assertIn("Nothing arrived at all", result[0].root_cause)

  def test_silent_is_skipped_when_samples_arrived(self):
    probe = FakeProbe(samples_taken=3)
    self.assertEqual(probe_payload.check_silent(CheckContext(probe=probe)), [])


class TestOffSubnetIsNotAWarning(unittest.TestCase):
  """A peer on another subnet is normal in a routed network and must stay silent."""

  def test_remote_subnet_does_not_warn(self):
    record = participant_record(
        default_unicast_locators=[FakeLocator("203.0.113.7", kind=1)])
    result = static_discovery.check_locators(
        CheckContext(participant_record=record, endpoint=endpoint_record()))
    self.assertEqual(result, [], "off-subnet peer produced a false warning")


class TestRxO(unittest.TestCase):
  """RxO comparison between two DISCOVERED endpoints in a running system."""

  @staticmethod
  def _policy(kind_name):
    class Kind:
      name = kind_name
    class Policy:
      kind = Kind()
    return Policy()

  def _pair(self, writer_kwargs=None, reader_kwargs=None):
    writer = endpoint_record(key="w", kind="Writer", **(writer_kwargs or {}))
    reader = endpoint_record(key="r", kind="Reader", **(reader_kwargs or {}))
    registry = FakeRegistry([participant_record()], [writer, reader])
    return writer, reader, registry

  def test_reliable_reader_vs_best_effort_writer_is_incompatible(self):
    writer, reader, registry = self._pair(
        {"reliability": self._policy("BEST_EFFORT")},
        {"reliability": self._policy("RELIABLE")})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.rxo_mismatch"])
    self.assertIn("RELIABILITY", result[0].title)
    self.assertIn(qos_match.DOC_OMG_DDS_RTPS, result[0].refs)

  def test_best_effort_reader_vs_reliable_writer_is_fine(self):
    writer, reader, registry = self._pair(
        {"reliability": self._policy("RELIABLE")},
        {"reliability": self._policy("BEST_EFFORT")})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])

  @staticmethod
  def _presentation(scope):
    class Kind:
      name = scope
    class Presentation:
      access_scope = Kind()
      coherent_access = False
      ordered_access = False
    return Presentation()

  @staticmethod
  def _representation(ids_):
    class Representation:
      value = list(ids_)
    return Representation()

  def test_broader_reader_access_scope_is_incompatible(self):
    """Regression: the check read `kind`, which Presentation does not have."""
    writer, reader, registry = self._pair(
        {"presentation": self._presentation("INSTANCE")},
        {"presentation": self._presentation("GROUP")})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.rxo_mismatch"])
    self.assertEqual([m["policy"] for m in result[0].evidence["mismatches"]],
                     ["PRESENTATION access_scope"])

  def test_narrower_reader_access_scope_is_fine(self):
    writer, reader, registry = self._pair(
        {"presentation": self._presentation("GROUP")},
        {"presentation": self._presentation("INSTANCE")})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])

  def test_highest_offered_reader_matches_every_writer(self):
    """HIGHEST_OFFERED means "use what the Publisher offers", so it never fails."""
    for scope in ("INSTANCE", "TOPIC", "GROUP"):
      with self.subTest(writer_scope=scope):
        writer, reader, registry = self._pair(
            {"presentation": self._presentation(scope)},
            {"presentation": self._presentation("HIGHEST_OFFERED")})
        result = qos_match.check_rxo_pairs(
            CheckContext(endpoint=writer, registry=registry))
        self.assertEqual(ids(result), ["qos.compatible"])
        # Compatible, not unevaluable: nothing about this pair is missing.
        unevaluated = [item["policy"]
                       for item in result[0].evidence["policies_unevaluated"]]
        self.assertNotIn("PRESENTATION access_scope", unevaluated)

  def test_reader_must_accept_the_writers_first_representation(self):
    """Regression: set intersection called [XCDR1, XCDR2] -> [XCDR2] compatible."""
    writer, reader, registry = self._pair(
        {"representation": self._representation([0, 2])},
        {"representation": self._representation([2])})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.rxo_mismatch"])
    self.assertEqual([m["policy"] for m in result[0].evidence["mismatches"]],
                     ["DATA_REPRESENTATION"])

  def test_reader_accepting_the_writers_first_representation_is_fine(self):
    writer, reader, registry = self._pair(
        {"representation": self._representation([2, 0])},
        {"representation": self._representation([2])})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])

  @staticmethod
  def _vendor(high, low):
    class VendorId:
      value = [high, low]
    return VendorId()

  def test_a_non_advertising_writer_is_xcdr1_and_an_xcdr2_only_reader_rejects_it(self):
    """Q3, decided 2026-08-12. This exact pair used to report `qos.compatible`.

    Measured against live middleware for both vendors: a writer that never set
    DATA_REPRESENTATION advertises an empty sequence, and an XCDR2-only reader
    refuses it with `requested_incompatible_qos` naming DataRepresentation. The
    tool reported OK at exit 0 on the commonest configuration there is.
    """
    for vendor_name_, octets in (("RTI", (0x01, 0x01)), ("Fast DDS", (0x01, 0x0F))):
      with self.subTest(vendor=vendor_name_):
        writer, reader, registry = self._pair(
            {"representation": self._representation([]),
             "vendor_id": self._vendor(*octets)},
            {"representation": self._representation([2])})
        result = qos_match.check_rxo_pairs(
            CheckContext(endpoint=writer, registry=registry))
        self.assertEqual(ids(result), ["qos.rxo_mismatch"])
        mismatch, = [m for m in result[0].evidence["mismatches"]
                     if m["policy"] == "DATA_REPRESENTATION"]
        # The report must not claim the writer advertised XCDR1. It advertised
        # nothing; XCDR1 is what that means. Q1 and Q2 were the same mistake.
        self.assertIn("not advertised", mismatch["offered"])
        self.assertIn("XCDR1 in effect", mismatch["offered"])

  def test_a_non_advertising_writer_still_matches_a_reader_accepting_xcdr1(self):
    """The other half: resolving to XCDR1 must not invent a mismatch."""
    writer, reader, registry = self._pair(
        {"representation": self._representation([]),
         "vendor_id": self._vendor(0x01, 0x0F)},
        {"representation": self._representation([0])})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])

  def test_a_non_advertising_cyclone_writer_still_declines_the_comparison(self):
    """Cyclone is outside the measured scope and must not inherit RTI's meaning.

    Its README documents resolving an unspecified policy from the type's
    defaults, which can select XCDR2 - the opposite meaning from the same wire
    state. Until that is measured, this pair is unevaluated rather than an
    ERROR, because a wrong ERROR is the Q1/Q2 defect in the other direction.
    """
    writer, reader, registry = self._pair(
        {"representation": self._representation([]),
         "vendor_id": self._vendor(0x01, 0x10)},
        {"representation": self._representation([2])})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])
    unevaluated = [item["policy"]
                   for item in result[0].evidence["policies_unevaluated"]]
    self.assertIn("DATA_REPRESENTATION", unevaluated)

  def test_a_non_advertising_writer_of_an_unknown_vendor_declines_the_comparison(self):
    """An unrecognized vendor id must not default into RTI's semantics."""
    writer, reader, registry = self._pair(
        {"representation": self._representation([]),
         "vendor_id": self._vendor(0x7F, 0x7F)},
        {"representation": self._representation([2])})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])
    unevaluated = [item["policy"]
                   for item in result[0].evidence["policies_unevaluated"]]
    self.assertIn("DATA_REPRESENTATION", unevaluated)

  def test_an_unreadable_writer_representation_is_never_inferred_as_xcdr1(self):
    """The Q1/Q2 trap the Q3 fix could have walked into.

    `representation_ids` returns [] both for an advertised empty sequence and
    for a policy that could not be read, and only the first was measured. If
    the second is inferred as XCDR1 the tool converts unreadable input into a
    false ERROR - which is what Q1 and Q2 were, in a new place.
    """
    writer, reader, registry = self._pair(
        {"representation": None, "vendor_id": self._vendor(0x01, 0x0F)},
        {"representation": self._representation([2])})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])
    unevaluated = [item["policy"]
                   for item in result[0].evidence["policies_unevaluated"]]
    self.assertIn("DATA_REPRESENTATION", unevaluated)

  def test_an_unreadable_reader_representation_still_declines(self):
    """Reader-side emptiness is genuinely unread, and Q3 does not touch it.

    Measured: a default *reader* advertises XCDR1 concretely while a default
    writer advertises nothing, so an empty reader list means the policy could
    not be read - not that the reader accepts XCDR1.
    """
    writer, reader, registry = self._pair(
        {"representation": self._representation([0]),
         "vendor_id": self._vendor(0x01, 0x01)},
        {"representation": self._representation([])})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])
    unevaluated = [item["policy"]
                   for item in result[0].evidence["policies_unevaluated"]]
    self.assertIn("DATA_REPRESENTATION", unevaluated)

  def test_ownership_must_match_exactly(self):
    writer, reader, registry = self._pair(
        {"ownership": self._policy("SHARED")},
        {"ownership": self._policy("EXCLUSIVE")})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertIn("OWNERSHIP", result[0].title)

  def test_latency_budget_writer_slower_than_reader_is_incompatible(self):
    class Duration:
      def __init__(self, seconds):
        self.seconds = seconds
      def to_seconds(self):
        return self.seconds
    class Budget:
      def __init__(self, seconds):
        self.duration = Duration(seconds)
    writer, reader, registry = self._pair(
        {"latency_budget": Budget(2)}, {"latency_budget": Budget(1)})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertIn("LATENCY_BUDGET", result[0].title)

  def test_reader_presentation_requirement_must_be_offered(self):
    class Presentation:
      def __init__(self, coherent_access):
        self.coherent_access = coherent_access
        self.ordered_access = False
    writer, reader, registry = self._pair(
        {"presentation": Presentation(False)}, {"presentation": Presentation(True)})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertIn("PRESENTATION coherent_access", result[0].title)

  def test_unreadable_presentation_boolean_is_not_an_offer_of_false(self):
    """An absent PRESENTATION is no claim; false is a claim. Do not confuse them.

    The writer's Publisher may well have coherent_access=true - its policy
    simply did not survive discovery - so calling it false produced an ERROR,
    and exit 1, for a pair that matches.
    """
    class Presentation:
      def __init__(self, coherent_access=False, ordered_access=False):
        self.coherent_access = coherent_access
        self.ordered_access = ordered_access

    class Unreadable:
      @property
      def coherent_access(self):
        raise RuntimeError("policy not available on this Connext version")
      ordered_access = False

    for label, writer_kwargs, reader_kwargs in (
        ("writer policy absent", {}, {"presentation": Presentation(coherent_access=True)}),
        ("writer flag unreadable", {"presentation": Unreadable()},
         {"presentation": Presentation(coherent_access=True)}),
        ("reader flag unreadable", {"presentation": Presentation()},
         {"presentation": Unreadable()}),
    ):
      with self.subTest(case=label):
        writer, reader, registry = self._pair(writer_kwargs, reader_kwargs)
        result = qos_match.check_rxo_pairs(
            CheckContext(endpoint=writer, registry=registry))
        self.assertEqual(ids(result), ["qos.compatible"])
        unevaluated = [item["policy"]
                       for item in result[0].evidence["policies_unevaluated"]]
        self.assertIn("PRESENTATION coherent_access", unevaluated)

  def test_explicit_presentation_false_is_still_compared(self):
    """The fix must not silence the real offer of false."""
    class Presentation:
      def __init__(self, coherent_access, ordered_access=False):
        self.coherent_access = coherent_access
        self.ordered_access = ordered_access

    writer, reader, registry = self._pair(
        {"presentation": Presentation(False)}, {"presentation": Presentation(True)})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.rxo_mismatch"])
    unevaluated = [item["policy"]
                   for item in result[0].evidence["policies_unevaluated"]]
    self.assertNotIn("PRESENTATION coherent_access", unevaluated)

  def test_every_runtime_matrix_condition_has_a_named_diagnostic(self):
    class Duration:
      def __init__(self, seconds):
        self.seconds = seconds
      def to_seconds(self):
        return self.seconds

    class Policy:
      def __init__(self, kind=None, period=None, duration=None, lease_duration=None):
        self.kind = kind
        self.period = period
        self.duration = duration
        self.lease_duration = lease_duration

    class Kind:
      def __init__(self, name):
        self.name = name

    class Presentation:
      # PresentationQosPolicy names its enum access_scope, NOT kind. A fake with
      # a `kind` field silently passed while production read a field the real
      # binding does not have, so the access-scope comparison never ran.
      def __init__(self, scope, coherent_access=False, ordered_access=False):
        self.access_scope = Kind(scope)
        self.coherent_access = coherent_access
        self.ordered_access = ordered_access

    class Representation:
      def __init__(self, value):
        self.value = value

    class Partition:
      def __init__(self, names):
        self.name = names

    cases = (
        ("DURABILITY", {"durability": Policy(Kind("VOLATILE"))},
         {"durability": Policy(Kind("TRANSIENT_LOCAL"))}),
        ("LIVELINESS", {"liveliness": Policy(Kind("AUTOMATIC"), duration=Duration(2))},
         {"liveliness": Policy(Kind("MANUAL_BY_TOPIC"), duration=Duration(1))}),
        ("LIVELINESS lease_duration", {"liveliness": Policy(Kind("AUTOMATIC"), lease_duration=Duration(2))},
         {"liveliness": Policy(Kind("AUTOMATIC"), lease_duration=Duration(1))}),
        ("DESTINATION_ORDER", {"destination_order": Policy(Kind("BY_RECEPTION_TIMESTAMP"))},
         {"destination_order": Policy(Kind("BY_SOURCE_TIMESTAMP"))}),
        ("PRESENTATION access_scope", {"presentation": Presentation("INSTANCE")},
         {"presentation": Presentation("GROUP")}),
        ("PRESENTATION coherent_access", {"presentation": Presentation("INSTANCE")},
         {"presentation": Presentation("INSTANCE", coherent_access=True)}),
        ("PRESENTATION ordered_access", {"presentation": Presentation("INSTANCE")},
         {"presentation": Presentation("INSTANCE", ordered_access=True)}),
        ("DEADLINE", {"deadline": Policy(period=Duration(2))},
         {"deadline": Policy(period=Duration(1))}),
        ("LATENCY_BUDGET", {"latency_budget": Policy(duration=Duration(2))},
         {"latency_budget": Policy(duration=Duration(1))}),
        ("OWNERSHIP", {"ownership": Policy(Kind("SHARED"))},
         {"ownership": Policy(Kind("EXCLUSIVE"))}),
        ("DATA_REPRESENTATION", {"representation": Representation([0])},
         {"representation": Representation([2])}),
        ("PARTITION", {"partition": Partition(["writer"])},
         {"partition": Partition(["reader"])}),
    )
    for expected, writer_kwargs, reader_kwargs in cases:
      with self.subTest(policy=expected):
        writer, reader, registry = self._pair(writer_kwargs, reader_kwargs)
        result = qos_match.check_rxo_pairs(
            CheckContext(endpoint=writer, registry=registry))
        self.assertEqual(ids(result), ["qos.rxo_mismatch"])
        # Exact, not a title substring: "PRESENTATION" is a substring of
        # "DATA_REPRESENTATION", so a substring assertion can pass on the
        # wrong policy.
        self.assertEqual([m["policy"] for m in result[0].evidence["mismatches"]],
                         [expected])

  def test_stronger_reader_durability_is_incompatible(self):
    writer, reader, registry = self._pair(
        {"durability": self._policy("VOLATILE")},
        {"durability": self._policy("TRANSIENT_LOCAL")})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertIn("DURABILITY", result[0].title)

  def test_weaker_reader_durability_is_fine(self):
    writer, reader, registry = self._pair(
        {"durability": self._policy("TRANSIENT_LOCAL")},
        {"durability": self._policy("VOLATILE")})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])

  def test_unreadable_policies_produce_no_claim(self):
    """Missing QoS must never be reported as an incompatibility."""
    writer, reader, registry = self._pair()
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])

  @staticmethod
  def _partition(names):
    # `names` is stored as given: a real PartitionQosPolicy carries a sequence,
    # but a single string has to stay a single string here.
    class Partition:
      name = names
    return Partition()

  def test_a_single_string_partition_is_one_name(self):
    """A str is iterable, and iterating it made 'telemetry' nine partitions."""
    writer, reader, registry = self._pair(
        {"partition": self._partition("telemetry")},
        {"partition": self._partition(["telemetry"])})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.compatible"])

  def test_readable_partitions_are_reported_as_evaluated(self):
    """A policy that was compared must not appear in the incomplete list."""
    writer, reader, registry = self._pair(
        {"partition": self._partition(["telemetry"])},
        {"partition": self._partition(["telemetry"])})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    unevaluated = [item["policy"]
                   for item in result[0].evidence["policies_unevaluated"]]
    self.assertNotIn("PARTITION", unevaluated)

  def test_named_partitions_still_match_and_mismatch(self):
    for writer_names, reader_names, expected in (
        (["telemetry"], ["telemetry"], "qos.compatible"),
        (["telemetry"], ["control"], "qos.rxo_mismatch"),
        (["telem*"], ["telemetry"], "qos.compatible"),
        ([], [], "qos.compatible"),          # both explicitly default
        ([], ["telemetry"], "qos.rxo_mismatch"),
    ):
      with self.subTest(writer=writer_names, reader=reader_names):
        writer, reader, registry = self._pair(
            {"partition": self._partition(writer_names)},
            {"partition": self._partition(reader_names)})
        result = qos_match.check_rxo_pairs(
            CheckContext(endpoint=writer, registry=registry))
        self.assertEqual(ids(result), [expected])

  def test_unreadable_partition_is_not_a_mismatch(self):
    """An unreadable PARTITION is not a claim of the default partition.

    The writer really is in "telemetry"; its policy simply did not survive
    discovery. Treating that as the default partition produced an ERROR - and
    exit 1 - for a pair that is matched and communicating.
    """
    class Unreadable:
      @property
      def name(self):
        raise RuntimeError("policy not available on this Connext version")

    for label, writer_kwargs, reader_kwargs in (
        ("writer unreadable", {"partition": Unreadable()},
         {"partition": self._partition(["telemetry"])}),
        ("reader unreadable", {"partition": self._partition(["telemetry"])},
         {"partition": Unreadable()}),
        ("writer absent", {}, {"partition": self._partition(["telemetry"])}),
        ("reader absent", {"partition": self._partition(["telemetry"])}, {}),
    ):
      with self.subTest(case=label):
        writer, reader, registry = self._pair(writer_kwargs, reader_kwargs)
        result = qos_match.check_rxo_pairs(
            CheckContext(endpoint=writer, registry=registry))
        self.assertEqual(ids(result), ["qos.compatible"])
        # Not evaluated is not the same answer as compatible, and the report
        # has to say which one this was.
        unevaluated = [item["policy"]
                       for item in result[0].evidence["policies_unevaluated"]]
        self.assertIn("PARTITION", unevaluated)
        self.assertIn("PARTITION", result[0].observed)

  def test_incomplete_evidence_is_recorded_alongside_a_real_mismatch(self):
    writer, reader, registry = self._pair(
        {"reliability": self._policy("BEST_EFFORT")},
        {"reliability": self._policy("RELIABLE")})
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.rxo_mismatch"])
    self.assertEqual([m["policy"] for m in result[0].evidence["mismatches"]],
                     ["RELIABILITY"])
    unevaluated = [item["policy"]
                   for item in result[0].evidence["policies_unevaluated"]]
    self.assertIn("PARTITION", unevaluated)
    self.assertNotIn("RELIABILITY", unevaluated)
    self.assertIn("Not evaluated", result[0].observed)

  def test_no_counterpart_is_reported_as_info(self):
    writer = endpoint_record(key="w", kind="Writer")
    registry = FakeRegistry([participant_record()], [writer])
    result = qos_match.check_rxo_pairs(CheckContext(endpoint=writer, registry=registry))
    self.assertEqual(ids(result), ["qos.no_counterpart"])
    self.assertEqual(result[0].severity, f.Severity.INFO)


class TestProbeMatchPolicyRules(unittest.TestCase):
  """Every RXO_RULES key must resolve to its own rule.

  _policy_rule matches on substring because Connext decorates last_policy with a
  version-dependent prefix or suffix. Substring matching means keys can overlap:
  PRESENTATION is contained in DATAREPRESENTATION, and first-match order
  explained a data representation mismatch with the presentation rule.
  """

  def test_each_key_resolves_to_its_own_rule(self):
    for name, rule in probe_match.RXO_RULES.items():
      with self.subTest(policy=name):
        self.assertEqual(probe_match._policy_rule(name), rule)

  def test_decorated_policy_names_still_resolve(self):
    for text, expected in (
        ("DATA_REPRESENTATION", "DATAREPRESENTATION"),
        ("QosPolicyId.DATA_REPRESENTATION_QOS_POLICY_ID", "DATAREPRESENTATION"),
        ("data representation", "DATAREPRESENTATION"),
        ("PRESENTATION", "PRESENTATION"),
        ("QosPolicyId.PRESENTATION_QOS_POLICY_ID", "PRESENTATION"),
        ("DESTINATION_ORDER", "DESTINATIONORDER"),
        ("LATENCY_BUDGET", "LATENCYBUDGET"),
    ):
      with self.subTest(policy_text=text):
        self.assertEqual(probe_match._policy_rule(text),
                         probe_match.RXO_RULES[expected])

  def test_unknown_policy_has_no_rule(self):
    self.assertIsNone(probe_match._policy_rule("SOME_FUTURE_POLICY"))


# --- Probe writer-identity correlation (H2) ----------------------------------

class FakeMatchedPublicationReader:
  """A reader that can report which publications it matched.

  Maps an instance handle to the builtin key of the writer behind it. A None key
  stands for a publication whose data could not be read.
  """

  def __init__(self, keys_by_handle):
    self.matched_publications = list(keys_by_handle)
    self._keys = keys_by_handle

  def matched_publication_data(self, handle):
    value = self._keys[handle]
    if value is None:
      raise RuntimeError("matched_publication_data unavailable")
    class Key:
      pass
    class Data:
      pass
    key, data = Key(), Data()
    key.value = value
    data.key = key
    return data


class FakeUncorrelatableReader:
  """A binding that does not expose matched publications at all."""


class FakeSampleInfo:
  def __init__(self, publication_handle=None):
    if publication_handle is not None:
      self.publication_handle = publication_handle


class FakeSample:
  def __init__(self, publication_handle=None):
    self.info = FakeSampleInfo(publication_handle)


class TestProbeCorrelation(unittest.TestCase):
  """The probe's reader is topic-scoped; findings must not claim otherwise."""

  def _correlate(self, reader, key="w1"):
    result = probe.ProbeResult()
    endpoint = endpoint_record(key=key, kind="Writer")
    return probe._correlate(reader, endpoint, result), result

  def test_selected_writer_is_identified_among_its_peers(self):
    reader = FakeMatchedPublicationReader({"h1": "w1", "h2": "w2", "h3": "w3"})
    target, result = self._correlate(reader)
    self.assertEqual(target, {"h1"})
    self.assertTrue(result.correlated)
    self.assertEqual(result.matched_other_count, 2)

  def test_sole_matched_writer_reports_no_others(self):
    reader = FakeMatchedPublicationReader({"h1": "w1"})
    target, result = self._correlate(reader)
    self.assertEqual(target, {"h1"})
    self.assertEqual(result.matched_other_count, 0)

  def test_matching_only_another_writer_is_a_conclusion_not_a_failure(self):
    """An empty target set means the selected writer did NOT match."""
    reader = FakeMatchedPublicationReader({"h2": "w2"})
    target, result = self._correlate(reader)
    self.assertEqual(target, set())
    self.assertTrue(result.correlated)
    self.assertEqual(result.matched_other_count, 1)

  def test_matching_nothing_is_correlated(self):
    target, result = self._correlate(FakeMatchedPublicationReader({}))
    self.assertEqual(target, set())
    self.assertTrue(result.correlated)

  def test_binding_without_matched_publications_is_not_correlated(self):
    target, result = self._correlate(FakeUncorrelatableReader())
    self.assertIsNone(target)
    self.assertFalse(result.correlated)

  def test_unreadable_publication_data_is_not_correlated(self):
    """Never claim correlation when no matched publication could be resolved."""
    reader = FakeMatchedPublicationReader({"h1": None, "h2": None})
    target, result = self._correlate(reader)
    self.assertIsNone(target)
    self.assertFalse(result.correlated)

  def test_sample_from_the_target_handle_is_attributed(self):
    self.assertTrue(probe._sample_is_target(FakeSample("h1"), {"h1"}, False))

  def test_sample_from_another_writer_is_not_attributed(self):
    self.assertFalse(probe._sample_is_target(FakeSample("h2"), {"h1"}, False))

  def test_unattributable_sample_counts_only_when_target_is_exclusive(self):
    """With other writers matched, an unreadable handle must not be credited."""
    self.assertTrue(probe._sample_is_target(FakeSample(None), {"h1"}, True))
    self.assertFalse(probe._sample_is_target(FakeSample(None), {"h1"}, False))


class TestProbeMatchScoping(unittest.TestCase):
  """Rung-4 findings must state, and respect, what they actually observed."""

  @staticmethod
  def _status(policy):
    class Status:
      total_count = 1
      last_policy = policy
      policies = ()
    return Status()

  def test_incompatible_qos_is_an_error_only_when_attributable(self):
    probe_result = FakeProbe(requested_incompatible_qos=self._status("DATA_REPRESENTATION"),
                             correlated=True, matched_other_count=0)
    result = probe_match.check_incompatible_qos(CheckContext(probe=probe_result))
    self.assertEqual(ids(result), ["match.incompatible_qos"])
    self.assertEqual(result[0].severity, f.Severity.ERROR)

  def test_incompatible_qos_with_other_writers_is_a_topic_warning(self):
    """The status is reader-side and does not name the writer that caused it."""
    probe_result = FakeProbe(requested_incompatible_qos=self._status("RELIABILITY"),
                             correlated=True, matched_other_count=2)
    result = probe_match.check_incompatible_qos(CheckContext(probe=probe_result))
    self.assertEqual(ids(result), ["match.incompatible_qos_topic"])
    self.assertEqual(result[0].severity, f.Severity.WARN)

  def test_incompatible_qos_without_correlation_is_a_topic_warning(self):
    probe_result = FakeProbe(requested_incompatible_qos=self._status("RELIABILITY"),
                             correlated=False, matched_other_count=0)
    result = probe_match.check_incompatible_qos(CheckContext(probe=probe_result))
    self.assertEqual(ids(result), ["match.incompatible_qos_topic"])

  def test_topic_scoped_rejection_is_not_offered_as_a_cause(self):
    """A maybe must not be presented as the explanation for a real symptom.

    This no longer hides anything - causal links only annotate - but naming an
    unattributable topic-wide rejection as the cause of this pair's silence
    would still send the operator after the wrong writer.
    """
    self.assertNotIn("match.incompatible_qos_topic",
                     f.CAUSAL_EXPLAINERS.get("data.silent", ()))
    self.assertNotIn("match.incompatible_qos_topic",
                     f.CAUSAL_EXPLAINERS.get("match.none", ()))

  def test_match_ok_says_so_when_the_writer_was_not_identified(self):
    correlated = probe_match.check_matched(
        CheckContext(probe=FakeProbe(correlated=True)))
    uncorrelated = probe_match.check_matched(
        CheckContext(probe=FakeProbe(correlated=False)))
    self.assertEqual(ids(correlated), ["match.ok"])
    self.assertEqual(ids(uncorrelated), ["match.ok"])
    self.assertIn("matched the writer", correlated[0].title)
    self.assertIn("a writer on this topic", uncorrelated[0].title)
    self.assertIn("topic-wide", uncorrelated[0].observed)

  def test_match_ok_discloses_other_matched_writers(self):
    result = probe_match.check_matched(
        CheckContext(probe=FakeProbe(correlated=True, matched_other_count=3)))
    self.assertIn("3 other writer(s)", result[0].observed)


# --- Discovery lifecycle and merge (H4, M5, M6) ------------------------------

def _builtin_key(value):
  """An object shaped like PublicationBuiltinTopicData: .key.value."""
  class Key:
    pass
  class Holder:
    pass
  key, holder = Key(), Holder()
  key.value = value
  holder.key = key
  return holder


class TestDisposalKeyRecovery(unittest.TestCase):
  """A departed endpoint must actually leave the registry (H4)."""

  class _Info:
    valid = False
    instance_handle = "ih1"

  def test_key_is_recovered_from_the_reader_when_the_sample_is_unpopulated(self):
    """key_value() returns the DATA type, so the key is at .key.value."""
    class Reader:
      def key_value(self, handle):
        return _builtin_key("w1")

    registry = discovery.DiscoveryRegistry()
    registry.upsert_endpoint(endpoint_record(key="w1", kind="Writer"))
    key = discovery._sample_key(_builtin_key("[0, 0, 0, 0]"), self._Info(), Reader())
    registry.remove_endpoint(key)
    self.assertEqual(key, "w1")
    self.assertEqual(registry.writers(), [])

  def test_all_zero_key_is_not_treated_as_an_identity(self):
    class Reader:
      def key_value(self, handle):
        return _builtin_key("[0, 0, 0, 0]")

    key = discovery._sample_key(_builtin_key("[0, 0, 0, 0]"), self._Info(), Reader())
    self.assertEqual(key, "")

  def test_unreadable_key_does_not_raise(self):
    class Reader:
      def key_value(self, handle):
        raise RuntimeError("no key for this handle")

    key = discovery._sample_key(_builtin_key(None), self._Info(), Reader())
    self.assertEqual(key, "")

  def test_populated_sample_key_is_used_directly(self):
    class Reader:
      def key_value(self, handle):
        raise AssertionError("must not consult the reader when data carries the key")

    key = discovery._sample_key(_builtin_key("w1"), self._Info(), Reader())
    self.assertEqual(key, "w1")


class TestListenerBatchIsolation(unittest.TestCase):
  """One bad sample must not discard its siblings (M6)."""

  def test_a_failing_sample_does_not_drop_the_rest_of_the_batch(self):
    class GoodInfo:
      valid = True
    class ExplodingInfo:
      @property
      def valid(self):
        raise RuntimeError("this vendor's SEDP field will not read")

    def data(key):
      class Key:
        pass
      class Data:
        pass
      k, d = Key(), Data()
      k.value = key
      d.key = k
      d.topic_name = "T"
      d.type_name = "MyType"
      d.participant_key = k
      return d

    class Reader:
      def take(self):
        return [(data("w1"), GoodInfo()),
                (data("w2"), ExplodingInfo()),
                (data("w3"), GoodInfo())]

    registry = discovery.DiscoveryRegistry()
    discovery.PublicationListener(registry).on_data_available(Reader())
    self.assertEqual(sorted(e.key for e in registry.writers()), ["w1", "w3"])

  def test_a_failing_take_is_contained(self):
    class Reader:
      def take(self):
        raise RuntimeError("reader unusable")

    registry = discovery.DiscoveryRegistry()
    discovery.PublicationListener(registry).on_data_available(Reader())
    self.assertEqual(registry.writers(), [])


class TestParticipantMerge(unittest.TestCase):
  """False and 0 are values, not absences (M5)."""

  def test_partial_configuration_can_be_cleared_by_a_later_sample(self):
    registry = discovery.DiscoveryRegistry()
    registry.upsert_participant(participant_record(key="p1", partial_configuration=True))
    registry.upsert_participant(participant_record(key="p1", partial_configuration=False))
    self.assertIs(registry.participants["p1"].partial_configuration, False)

  def test_domain_zero_is_applied(self):
    registry = discovery.DiscoveryRegistry()
    registry.upsert_participant(participant_record(key="p1", domain_id=None))
    registry.upsert_participant(participant_record(key="p1", domain_id=0))
    self.assertEqual(registry.participants["p1"].domain_id, 0)

  def test_absent_fields_still_do_not_erase_what_is_known(self):
    registry = discovery.DiscoveryRegistry()
    registry.upsert_participant(participant_record(key="p1", name="peer"))
    registry.upsert_participant(participant_record(key="p1", name=None))
    self.assertEqual(registry.participants["p1"].name, "peer")


class TestCorrelationDoesNotOverclaim(unittest.TestCase):
  """Regressions on the writer-correlation fix itself.

  Correlation exists to stop the probe attributing topic-wide evidence to one
  writer. These guard against it acquiring the same failure mode in new form.
  """

  def _correlate(self, reader, key="w1"):
    result = probe.ProbeResult()
    endpoint = endpoint_record(key=key, kind="Writer")
    return probe._correlate(reader, endpoint, result), result

  def test_unreadable_publication_blocks_the_never_matched_conclusion(self):
    """An unreadable key could BE the target; "did not match" is not provable."""
    reader = FakeMatchedPublicationReader({"h1": None, "h2": "w2"})
    target, result = self._correlate(reader)
    self.assertIsNone(target)
    self.assertFalse(result.correlated)

  def test_unreadable_publication_alongside_a_found_target_is_disclosed(self):
    reader = FakeMatchedPublicationReader({"h1": "w1", "h2": None})
    target, result = self._correlate(reader)
    self.assertEqual(target, {"h1"})
    self.assertTrue(result.correlated)
    self.assertEqual(result.matched_unreadable_count, 1)

  def test_other_writer_count_is_current_not_a_running_peak(self):
    """A departed writer must not permanently downgrade later verdicts."""
    result = probe.ProbeResult()
    endpoint = endpoint_record(key="w1", kind="Writer")
    probe._correlate(FakeMatchedPublicationReader({"h1": "w1", "h2": "w2"}),
                     endpoint, result)
    self.assertEqual(result.matched_other_count, 1)
    probe._correlate(FakeMatchedPublicationReader({"h1": "w1"}), endpoint, result)
    self.assertEqual(result.matched_other_count, 0)

  def test_transient_neighbour_does_not_downgrade_a_real_incompatibility(self):
    """The end state is what counts: exit code 1 must survive a transient."""
    class Status:
      total_count = 1
      last_policy = "RELIABILITY"
      policies = ()
    probe_result = FakeProbe(requested_incompatible_qos=Status(),
                             correlated=True, matched_other_count=0)
    result = probe_match.check_incompatible_qos(CheckContext(probe=probe_result))
    self.assertEqual(ids(result), ["match.incompatible_qos"])
    self.assertEqual(result[0].severity, f.Severity.ERROR)

  def test_unresolvable_publication_also_blocks_attribution(self):
    class Status:
      total_count = 1
      last_policy = "RELIABILITY"
      policies = ()
    probe_result = FakeProbe(requested_incompatible_qos=Status(),
                             correlated=True, matched_unreadable_count=1)
    result = probe_match.check_incompatible_qos(CheckContext(probe=probe_result))
    self.assertEqual(ids(result), ["match.incompatible_qos_topic"])

  def test_unattributable_sample_is_not_credited_when_a_publication_is_unresolved(self):
    self.assertFalse(probe._sample_is_target(FakeSample(None), {"h1"}, False))

  def test_silence_names_the_neighbour_instead_of_inventing_a_drop(self):
    """samples_taken is writer-scoped; received_sample_count is topic-wide."""
    probe_result = FakeProbe(samples_taken=0, samples_other=100,
                             protocol={"received_sample_count": 100,
                                       "received_heartbeat_count": 5,
                                       "received_gap_count": 0})
    result = probe_payload.check_silent(CheckContext(probe=probe_result))
    self.assertEqual(ids(result), ["data.silent"])
    self.assertIn("OTHER writers", result[0].observed)
    self.assertIn("none came from the selected writer", result[0].root_cause)
    self.assertNotIn("dropped between reception", result[0].root_cause)


class TestCorrelationIsNotALatch(unittest.TestCase):
  """`correlated` and the other/unreadable counts must describe one reading.

  `correlated` used to be set True on success and never cleared, so a later
  poll that could not resolve a publication left a writer-scoped claim standing
  over a topic-wide count - and could promote a topic-level WARN into a
  writer-scoped ERROR.
  """

  def test_a_later_uncorrelatable_read_clears_every_correlation_field(self):
    result = probe.ProbeResult()
    endpoint = endpoint_record(key="w1", kind="Writer")

    good = FakeMatchedPublicationReader({"h1": "w1", "h2": "w2"})
    self.assertEqual(probe._correlate(good, endpoint, result), {"h1"})
    self.assertTrue(result.correlated)
    self.assertEqual(result.matched_other_count, 1)

    # The binding stops reporting matched publications.
    self.assertIsNone(probe._correlate(FakeUncorrelatableReader(), endpoint, result))
    self.assertFalse(result.correlated)
    self.assertEqual(result.matched_other_count, 0)
    self.assertEqual(result.matched_unreadable_count, 0)

  def test_an_unreadable_publication_clears_it_too(self):
    result = probe.ProbeResult()
    endpoint = endpoint_record(key="w1", kind="Writer")
    probe._correlate(FakeMatchedPublicationReader({"h1": "w1"}), endpoint, result)
    self.assertTrue(result.correlated)

    # "w1" is gone and one publication will not read: it could have been w1.
    probe._correlate(FakeMatchedPublicationReader({"h2": None}), endpoint, result)
    self.assertFalse(result.correlated)


class TestProbeIncompleteRun(unittest.TestCase):

  def test_a_failure_after_reader_creation_is_reported(self):
    probe_result = FakeProbe()
    probe_result.error = "RuntimeError: status read failed"
    result = probe_match.check_probe_incomplete(CheckContext(probe=probe_result))
    self.assertEqual(ids(result), ["probe.incomplete"])
    self.assertEqual(result[0].severity, f.Severity.WARN)

  def test_a_clean_probe_reports_nothing(self):
    self.assertEqual(
        probe_match.check_probe_incomplete(CheckContext(probe=FakeProbe())), [])


class TestParticipantDepartureSweep(unittest.TestCase):
  """One unreadable sample must not evict a live peer and all its endpoints."""

  class FakeParticipant:
    def __init__(self, readable):
      self._readable = readable
    def discovered_participants(self):
      return ["h1", "h2"]
    def discovered_participant_data(self, handle):
      if handle not in self._readable:
        raise RuntimeError("this vendor's SPDP field will not read")
      class Key:
        value = handle
      class Name:
        name = handle
      class Data:
        key = Key()
        participant_name = Name()
      return Data()

  def _registry(self):
    registry = discovery.DiscoveryRegistry()
    registry.participants = {"h1": records.ParticipantRecord(key="h1"),
                             "h2": records.ParticipantRecord(key="h2")}
    registry.endpoints = {
        "e1": records.EndpointRecord(key="e1", kind="Writer", participant_key="h2")}
    return registry

  def test_an_unreadable_participant_does_not_evict_the_peer(self):
    registry = self._registry()
    discovery.refresh_participants(self.FakeParticipant({"h1"}), registry)
    self.assertEqual(set(registry.participants), {"h1", "h2"})
    self.assertEqual(set(registry.endpoints), {"e1"})

  def test_a_genuinely_departed_participant_is_still_removed(self):
    registry = self._registry()
    registry.participants["gone"] = records.ParticipantRecord(key="gone")
    discovery.refresh_participants(self.FakeParticipant({"h1", "h2"}), registry)
    self.assertEqual(set(registry.participants), {"h1", "h2"})


class TestWriterSelectionIsDeterministic(unittest.TestCase):

  def test_find_writer_does_not_depend_on_discovery_order(self):
    """Dict order is arrival order; an unsorted pick changed the verdict per run."""
    keys = ["w-c", "w-a", "w-b"]
    chosen = set()
    for order in (keys, list(reversed(keys))):
      registry = discovery.DiscoveryRegistry()
      for key in order:
        registry.endpoints[key] = records.EndpointRecord(
            key=key, kind="Writer", topic_name="Telemetry")
      chosen.add(registry.find_writer("Telemetry").key)
    self.assertEqual(chosen, {"w-a"})


class FakeSequence:
  """A Connext sequence-like whose iteration can be made to raise.

  The binding's sequences are C++ objects behind __bool__/__len__/__iter__, and
  `compat.get` cannot protect a caller that then iterates the value it returned.
  """

  def __init__(self, items=(), raises=None):
    self._items = list(items)
    self._raises = raises

  def __iter__(self):
    if self._raises is not None:
      raise self._raises
    return iter(self._items)

  def __len__(self):
    if self._raises is not None:
      raise self._raises
    return len(self._items)


class FakeParticipantData:
  """A realistic ParticipantBuiltinTopicData, by the binding's field names.

  Named attributes rather than a Mock: `compat.get` swallows every exception and
  returns its default, so a Mock - which answers to any name - cannot fail when
  the mapper asks for a field the binding does not actually have. That tolerance
  is correct at runtime and useless in a test, which is why this fake only
  answers to the names the real binding uses.
  """

  def __init__(self, key=(1, 2, 3, 4), name="peer-app", **overrides):
    self.key = type("Key", (), {"value": list(key)})()
    self.participant_name = type("Name", (), {"name": name})()
    self.domain_id = 7
    self.rtps_vendor_id = type("Vendor", (), {"value": [1, 1]})()
    self.rtps_protocol_version = type("Protocol", (), {"major": 2, "minor": 5})()
    self.product_version = type("Product", (), {"major": 7})()
    self.default_unicast_locators = FakeSequence([FakeLocator("10.0.0.7")])
    self.transport_info = FakeSequence([object()])
    self.dds_builtin_endpoints = 3135
    self.available_builtin_endpoints_ext = 12
    self.vendor_builtin_endpoints = 4
    self.partial_configuration = False
    for field, value in overrides.items():
      setattr(self, field, value)


class FakeEndpointData:
  """A realistic Publication/SubscriptionBuiltinTopicData, same discipline."""

  def __init__(self, key=(1, 2, 3, 5), participant_key=(1, 2, 3, 4), **overrides):
    self.key = type("Key", (), {"value": list(key)})()
    self.participant_key = type("Key", (), {"value": list(participant_key)})()
    self.topic_name = "Telemetry"
    self.type_name = "TelemetryType"
    self.type = object()
    self.rtps_vendor_id = type("Vendor", (), {"value": [1, 1]})()
    self.rtps_protocol_version = type("Protocol", (), {"major": 2, "minor": 5})()
    self.reliability = type("Reliability", (), {"kind": "RELIABLE"})()
    self.durability = type("Durability", (), {"kind": "TRANSIENT_LOCAL"})()
    self.latency_budget = type("Latency", (), {"duration": 0})()
    self.deadline = type("Deadline", (), {"period": 1})()
    self.liveliness = type("Liveliness", (), {"kind": "AUTOMATIC"})()
    self.ownership = type("Ownership", (), {"kind": "SHARED"})()
    self.destination_order = type("Order", (), {"kind": "BY_RECEPTION_TIMESTAMP"})()
    self.presentation = type("Presentation", (), {"access_scope": "INSTANCE"})()
    self.partition = type("Partition", (), {"name": ["telemetry"]})()
    self.representation = type("Repr", (), {"value": [0]})()
    self.unicast_locators = FakeSequence([FakeLocator("10.0.0.7")])
    self.multicast_locators = FakeSequence([FakeLocator("239.255.0.1", port=7400)])
    for field, value in overrides.items():
      setattr(self, field, value)


class TestDiscoveryFieldMapping(unittest.TestCase):
  """S2: the mapper's binding field names are asserted by nothing else.

  Every other test in this file builds `EndpointRecord`/`ParticipantRecord`
  directly, so `_endpoint_from_data` and `_participant_from_data` were reached
  only by fakes carrying three or four fields. `compat.get` returns its default
  for a name the object does not have, by design, which makes a renamed or
  mistyped field indistinguishable from a genuinely absent one: changing
  `rtps_vendor_id` to any wrong name turns every peer's vendor unknown and every
  RxO policy unreadable, with the whole suite still green.

  These assert that each mapped field arrives non-default from a fake that
  answers only to the real binding names.
  """

  #: (record attribute, expected value or predicate) for every endpoint field
  #: the mapper is responsible for.
  ENDPOINT_FIELDS = (
      ("key", "[1, 2, 3, 5]"),
      ("participant_key", "[1, 2, 3, 4]"),
      ("topic_name", "Telemetry"),
      ("type_name", "TelemetryType"),
      ("type", None),
      ("vendor_id", None),
      ("protocol_version", None),
      ("reliability", None),
      ("durability", None),
      ("latency_budget", None),
      ("deadline", None),
      ("liveliness", None),
      ("ownership", None),
      ("destination_order", None),
      ("presentation", None),
      ("partition", None),
      ("representation", None),
      ("unicast_locators", None),
      ("multicast_locators", None),
  )

  PARTICIPANT_FIELDS = (
      ("key", "[1, 2, 3, 4]"),
      ("name", "peer-app"),
      ("ip", "10.0.0.7"),
      ("domain_id", 7),
      ("vendor_id", None),
      ("protocol_version", None),
      ("product_version", None),
      ("default_unicast_locators", None),
      ("transport_info", None),
      ("dds_builtin_endpoints", 3135),
      ("available_builtin_endpoints_ext", 12),
      ("vendor_builtin_endpoints", 4),
      ("rtps_host_id", 1),
      ("rtps_app_id", 2),
  )

  def test_every_endpoint_field_arrives(self):
    record = discovery._endpoint_from_data(FakeEndpointData(), "Writer")
    self.assertEqual(record.kind, "Writer")
    for field, expected in self.ENDPOINT_FIELDS:
      with self.subTest(field=field):
        value = getattr(record, field)
        self.assertIsNotNone(value, f"{field} did not arrive from discovery")
        if expected is not None:
          self.assertEqual(value, expected)
    # Not merely non-None: an empty list is what an unreadable sequence yields.
    self.assertEqual(len(record.unicast_locators), 1)
    self.assertEqual(len(record.multicast_locators), 1)

  def test_every_participant_field_arrives(self):
    record = discovery._participant_from_data(FakeParticipantData())
    for field, expected in self.PARTICIPANT_FIELDS:
      with self.subTest(field=field):
        value = getattr(record, field)
        self.assertIsNotNone(value, f"{field} did not arrive from discovery")
        if expected is not None:
          self.assertEqual(value, expected)
    self.assertIs(record.partial_configuration, False)
    self.assertEqual(len(record.default_unicast_locators), 1)
    self.assertEqual(len(record.transport_info), 1)

  def test_a_renamed_endpoint_field_is_caught(self):
    """Guards the guard: the fake must not answer to a name the binding lacks.

    A Mock, or a fake with __getattr__, would pass the two tests above no matter
    what the mapper asked for - which is the exact hole S2 describes.
    """
    data = FakeEndpointData()
    del data.reliability
    record = discovery._endpoint_from_data(data, "Writer")
    self.assertIsNone(record.reliability)

  def test_a_renamed_participant_field_is_caught(self):
    data = FakeParticipantData()
    del data.rtps_vendor_id
    record = discovery._participant_from_data(data)
    self.assertIsNone(record.vendor_id)


class TestOneBadParticipantDoesNotDropTheRest(unittest.TestCase):
  """H10: the guard covered the sample fetch, not the field reads after it."""

  class FakeParticipant:
    def __init__(self, failing):
      self.failing = failing

    def discovered_participants(self):
      return ["h1", "h2", "h3"]

    def discovered_participant_data(self, handle):
      if handle == self.failing:
        # Not a fetch failure: the sample reads, and iterating one of its
        # sequences is what raises. Every field read after the fetch used to
        # sit outside the try, so this left refresh_participants entirely.
        return FakeParticipantData(
            key=(9, 9, 9, 9), name=f"peer-{handle}",
            transport_info=FakeSequence(raises=RuntimeError(
                "transport_info sequence will not iterate")))
      index = int(handle[1:])
      return FakeParticipantData(key=(index,) * 4, name=f"peer-{handle}")

  def _refresh(self, failing):
    registry = discovery.DiscoveryRegistry()
    with mock.patch.object(discovery.logging, "debug"), \
         mock.patch.object(discovery.logging, "warning"):
      discovery.refresh_participants(self.FakeParticipant(failing), registry)
    return registry

  def test_a_later_participant_is_still_registered(self):
    registry = self._refresh("h2")
    self.assertIn("[3, 3, 3, 3]", registry.participants)
    self.assertIn("[1, 1, 1, 1]", registry.participants)

  def test_the_unreadable_participant_contributes_no_guessed_record(self):
    """A partial record from unreadable data would be a fabricated peer."""
    registry = self._refresh("h2")
    self.assertNotIn("[9, 9, 9, 9]", registry.participants)
    self.assertEqual(len(registry.participants), 2)

  def test_the_departure_sweep_is_still_skipped_for_that_cycle(self):
    """An unreadable handle is live, so nothing may be evicted on its account."""
    registry = discovery.DiscoveryRegistry()
    registry.participants["stale"] = records.ParticipantRecord(key="stale")
    with mock.patch.object(discovery.logging, "debug"), \
         mock.patch.object(discovery.logging, "warning"):
      discovery.refresh_participants(self.FakeParticipant("h2"), registry)
    self.assertIn("stale", registry.participants)

  def test_a_clean_cycle_still_sweeps(self):
    """Guards the guard: the skip must not become permanent."""
    registry = discovery.DiscoveryRegistry()
    registry.participants["stale"] = records.ParticipantRecord(key="stale")
    discovery.refresh_participants(self.FakeParticipant(None), registry)
    self.assertNotIn("stale", registry.participants)
    self.assertEqual(len(registry.participants), 3)


if __name__ == "__main__":
  # At the end of the file, not mid-way through it: 13 of the 20 classes below
  # the old position - the whole TestRxO matrix, TestProbeCorrelation,
  # TestParticipantMerge, TestParticipantDepartureSweep - were never collected
  # by `python test/test_checks.py`, which ran 7 classes and printed OK. CI was
  # unaffected because run_tests.sh uses -m unittest, so a developer verifying
  # an RxO change the obvious way got a green run that touched no RxO test.
  unittest.main()
