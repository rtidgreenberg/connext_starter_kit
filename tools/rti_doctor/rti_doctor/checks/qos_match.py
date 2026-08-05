"""Rung 4 checks: RxO compatibility between DISCOVERED writers and readers.

This is the "match analysis" rung, and it is in scope precisely because
rti_doctor is inserted into a running system as an observer rather than as a
replacement for one side: both the writer's offered QoS and the reader's
requested QoS are read from discovery data, so nothing has to be supplied by the
user and nothing is assumed.

The RxO rules implemented here are the DDS requested/offered rules. The reader is
the constrained side: for each ordered policy the writer must offer at least what
the reader requests.
"""

from .. import compat, records
from ..findings import RUNG_MATCH, Finding, Severity

#: Ordered policy kinds. A writer must offer a value >= the reader's request.
#: Keyed by the trailing enum name so this stays version- and binding-agnostic.
RELIABILITY_ORDER = {"BEST_EFFORT": 0, "RELIABLE": 1}
DURABILITY_ORDER = {"VOLATILE": 0, "TRANSIENT_LOCAL": 1, "TRANSIENT": 2, "PERSISTENT": 3}
LIVELINESS_ORDER = {"AUTOMATIC": 0, "MANUAL_BY_PARTICIPANT": 1, "MANUAL_BY_TOPIC": 2}
DESTINATION_ORDER_ORDER = {"BY_RECEPTION_TIMESTAMP": 0, "BY_SOURCE_TIMESTAMP": 1}
#: HIGHEST_OFFERED is deliberately absent. It applies only to a Subscriber and
#: means "use whatever each remote Publisher offers", so it is compatible with
#: every writer. Leaving it unranked makes _ordered_rule decline to evaluate,
#: which is the correct answer; ranking it above GROUP would fail every writer.
PRESENTATION_ORDER = {"INSTANCE": 0, "TOPIC": 1, "GROUP": 2}


def _enum_name(value):
  """Trailing name of an enum value, e.g. "RELIABLE", or None."""
  if value is None:
    return None
  name = compat.get(value, "name", None) or str(value)
  return str(name).rsplit(".", 1)[-1].upper()


def _kind_name(policy, attributes=("kind",)):
  """Trailing name of a policy's kind enum, e.g. "RELIABLE", or None.

  Presentation names its enum `access_scope` rather than `kind`, so the
  attribute is a parameter: reading a field the policy does not have would
  silently disable the comparison.
  """
  return _enum_name(compat.first(policy, attributes, None))


def _rank(policy, order, attributes=("kind",)):
  name = _kind_name(policy, attributes)
  if name is None:
    return None, None
  return order.get(name), name


def _seconds(duration):
  """Duration in seconds, or None when unreadable.

  Connext represents infinity as sec/nanosec both at INT32_MAX, and to_seconds()
  reports it as a huge float, so ordinary numeric comparison already treats
  infinite as the loosest value - which is what the RxO rules want.
  """
  if duration is None:
    return None
  method = compat.get(duration, "to_seconds", None)
  if callable(method):
    try:
      return float(method())
    except Exception:
      pass
  sec = compat.get_int(duration, "sec")
  nanosec = compat.get_int(duration, "nanosec")
  if sec is None:
    return None
  return float(sec) + (float(nanosec or 0) / 1e9)


def _ordered_rule(label, writer_policy, reader_policy, order, explanation,
                  attributes=("kind",)):
  """Compare an ordered policy. Returns a mismatch dict or None."""
  offered, offered_name = _rank(writer_policy, order, attributes)
  requested, requested_name = _rank(reader_policy, order, attributes)
  if offered is None or requested is None:
    return None  # cannot evaluate; say nothing rather than guess
  if offered >= requested:
    return None
  return {
      "policy": label,
      "offered": offered_name,
      "requested": requested_name,
      "rule": explanation,
  }


def _duration_rule(label, writer_duration, reader_duration, explanation):
  """Writer's period/duration must be <= the reader's (writer at least as strict)."""
  offered = _seconds(writer_duration)
  requested = _seconds(reader_duration)
  if offered is None or requested is None:
    return None
  if offered <= requested:
    return None
  return {
      "policy": label,
      "offered": f"{offered:g}s",
      "requested": f"{requested:g}s",
      "rule": explanation,
  }


def _partition_names(policy):
  names = compat.get(policy, "name", None)
  try:
    return [str(n) for n in (names or ())]
  except TypeError:
    return []


def _partitions_overlap(writer_endpoint, reader_endpoint):
  """DDS partition matching, including the empty-default and wildcard cases."""
  import fnmatch

  writer_names = _partition_names(writer_endpoint.partition)
  reader_names = _partition_names(reader_endpoint.partition)

  # An empty partition list means the single default (empty-string) partition.
  writer_effective = writer_names or [""]
  reader_effective = reader_names or [""]

  for w in writer_effective:
    for r in reader_effective:
      if w == r:
        return True, writer_names, reader_names
      # Wildcards are permitted on one side; test both directions.
      if fnmatch.fnmatchcase(r, w) or fnmatch.fnmatchcase(w, r):
        return True, writer_names, reader_names
  return False, writer_names, reader_names


def compare_endpoints(writer, reader):
  """Every RxO incompatibility between a discovered writer and reader.

  Returns a list of mismatch dicts. Empty means "no incompatibility observable
  from discovery data" - not a guarantee of matching, since type assignability
  and security are checked elsewhere.
  """
  mismatches = []

  rule = _ordered_rule(
      "RELIABILITY", writer.reliability, reader.reliability, RELIABILITY_ORDER,
      "A RELIABLE reader cannot match a BEST_EFFORT writer. The reader may "
      "request BEST_EFFORT from a RELIABLE writer, but not the reverse.")
  if rule:
    mismatches.append(rule)

  rule = _ordered_rule(
      "DURABILITY", writer.durability, reader.durability, DURABILITY_ORDER,
      "The writer must offer durability at least as strong as the reader "
      "requests: VOLATILE < TRANSIENT_LOCAL < TRANSIENT < PERSISTENT.")
  if rule:
    mismatches.append(rule)

  rule = _ordered_rule(
      "LIVELINESS", writer.liveliness, reader.liveliness, LIVELINESS_ORDER,
      "The writer's liveliness kind must be at least as strong as the reader's: "
      "AUTOMATIC < MANUAL_BY_PARTICIPANT < MANUAL_BY_TOPIC.")
  if rule:
    mismatches.append(rule)

  rule = _ordered_rule(
      "DESTINATION_ORDER", writer.destination_order, reader.destination_order,
      DESTINATION_ORDER_ORDER,
      "The writer's destination order must be at least as strong as the "
      "reader's: BY_RECEPTION_TIMESTAMP < BY_SOURCE_TIMESTAMP.")
  if rule:
    mismatches.append(rule)

  rule = _ordered_rule(
      "PRESENTATION access_scope", writer.presentation, reader.presentation,
      PRESENTATION_ORDER,
      "The writer's presentation access scope must be at least as broad as the "
      "reader's: INSTANCE < TOPIC < GROUP.",
      attributes=("access_scope", "kind"))
  if rule:
    mismatches.append(rule)

  rule = _duration_rule(
      "DEADLINE", compat.get(writer.deadline, "period", None),
      compat.get(reader.deadline, "period", None),
      "The writer's deadline period must be less than or equal to the reader's, "
      "so the writer promises updates at least as often as the reader requires.")
  if rule:
    mismatches.append(rule)

  rule = _duration_rule(
      "LATENCY_BUDGET", compat.get(writer.latency_budget, "duration", None),
      compat.get(reader.latency_budget, "duration", None),
      "The writer's latency budget duration must be less than or equal to the "
      "reader's.")
  if rule:
    mismatches.append(rule)

  rule = _duration_rule(
      "LIVELINESS lease_duration",
      compat.get(writer.liveliness, "lease_duration", None),
      compat.get(reader.liveliness, "lease_duration", None),
      "The writer's liveliness lease duration must be less than or equal to the "
      "reader's.")
  if rule:
    mismatches.append(rule)

  for name in ("coherent_access", "ordered_access"):
    writer_value = compat.get(writer.presentation, name, None)
    reader_value = compat.get(reader.presentation, name, None)
    if reader_value and not writer_value:
      mismatches.append({
          "policy": f"PRESENTATION {name}",
          "offered": str(bool(writer_value)),
          "requested": str(bool(reader_value)),
          "rule": f"A writer must offer {name}=true when the reader requests it.",
      })

  # OWNERSHIP is not ordered - the kinds must be identical.
  writer_ownership = _kind_name(writer.ownership)
  reader_ownership = _kind_name(reader.ownership)
  if writer_ownership and reader_ownership and writer_ownership != reader_ownership:
    mismatches.append({
        "policy": "OWNERSHIP",
        "offered": writer_ownership,
        "requested": reader_ownership,
        "rule": "Ownership kind must match exactly; SHARED and EXCLUSIVE never mix.",
    })

  # DATA_REPRESENTATION is directional, not a set intersection. A writer offers
  # exactly one effective representation - the first in its list - while the
  # reader's list is the set it will accept. Writer [XCDR1, XCDR2] against reader
  # [XCDR2] intersects, but the writer serializes XCDR1 and the reader rejects it.
  writer_ids = records.representation_ids(writer.representation)
  reader_ids = records.representation_ids(reader.representation)
  if writer_ids and reader_ids and -1 not in writer_ids and -1 not in reader_ids:
    if writer_ids[0] not in set(reader_ids):
      mismatches.append({
          "policy": "DATA_REPRESENTATION",
          "offered": records.representation_text(writer.representation),
          "requested": records.representation_text(reader.representation),
          "rule": "The reader must accept the writer's effective data "
                  "representation, which is the first entry in the writer's list "
                  "(XCDR1/XCDR2).",
      })

  overlap, writer_partitions, reader_partitions = _partitions_overlap(writer, reader)
  if not overlap:
    mismatches.append({
        "policy": "PARTITION",
        "offered": ", ".join(writer_partitions) or "(default)",
        "requested": ", ".join(reader_partitions) or "(default)",
        "rule": "Reader and writer must share at least one partition name. "
                "Partitions are matched as strings, with wildcards allowed.",
    })

  return mismatches


def check_rxo_pairs(context):
  """Compare the focused endpoint against every counterpart on its topic."""
  endpoint = context.endpoint
  if endpoint is None or context.registry is None:
    return []

  peers = [e for e in context.registry.endpoints_on_topic(endpoint.topic_name)
           if e.is_writer != endpoint.is_writer]
  if not peers:
    if endpoint.is_writer:
      return [Finding(
          id="qos.no_counterpart",
          rung=RUNG_MATCH,
          severity=Severity.INFO,
          title=f"No DataReader discovered on topic '{endpoint.topic_name}'",
          observed="This writer has no counterpart in the system to compare against.",
          root_cause=("Nothing is subscribing to this topic, so no requested/"
                      "offered comparison is possible. rti_doctor's own probe "
                      "reader is not counted, since it deliberately mirrors the "
                      "writer and would always match."),
          remedy="",
      )]
    return []

  out = []
  for peer in peers:
    writer = endpoint if endpoint.is_writer else peer
    reader = peer if endpoint.is_writer else endpoint
    mismatches = compare_endpoints(writer, reader)

    writer_participant = context.registry.participant_for(writer)
    reader_participant = context.registry.participant_for(reader)
    writer_label = _label(writer, writer_participant)
    reader_label = _label(reader, reader_participant)

    if not mismatches:
      out.append(Finding(
          id="qos.compatible",
          rung=RUNG_MATCH,
          severity=Severity.OK,
          title=f"No observable QoS mismatch: {writer_label} -> {reader_label}",
          observed=("No requested/offered incompatibility was observed in the "
                    "discovery QoS available for this pair."),
          evidence={"writer": writer_label, "reader": reader_label,
              "writer_key": writer.key, "reader_key": reader.key,
              "writer_participant_key": writer.participant_key,
              "reader_participant_key": reader.participant_key,
              "topic_name": writer.topic_name},
      ))
      continue

    detail = "; ".join(
        f"{m['policy']}: writer offers {m['offered']}, reader requests {m['requested']}"
        for m in mismatches)
    rules = " ".join(m["rule"] for m in mismatches)
    policies = ", ".join(m["policy"] for m in mismatches)

    out.append(Finding(
        id="qos.rxo_mismatch",
        rung=RUNG_MATCH,
        severity=Severity.ERROR,
        title=f"QoS incompatible ({policies}): {writer_label} -> {reader_label}",
        observed=detail,
        root_cause=(
            "These two endpoints are both live in the system and will never "
            "communicate: DDS only matches a reader to a writer when every "
            "requested/offered policy is compatible. " + rules),
        remedy=(f"Change {policies} on one side. The reader is the constrained "
                f"side - it must request no more than the writer offers."),
        evidence={"writer": writer_label, "reader": reader_label,
            "writer_key": writer.key, "reader_key": reader.key,
            "writer_participant_key": writer.participant_key,
            "reader_participant_key": reader.participant_key,
            "topic_name": writer.topic_name,
                  "mismatches": mismatches},
    ))
  return out


def _label(endpoint, participant):
  who = participant.name if participant is not None and participant.name else "?"
  vendor = participant.vendor_name if participant is not None else "unknown vendor"
  return f"{endpoint.kind} in '{who}' ({vendor})"


CHECKS = (check_rxo_pairs,)
