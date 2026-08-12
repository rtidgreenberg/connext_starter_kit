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

from .. import compat, records, vendors
from ..findings import RUNG_MATCH, Finding, Severity

#: XCDR1's DATA_REPRESENTATION id, per XTypes. The effective representation of a
#: writer that advertised an empty sequence, for the vendors where that has been
#: measured - see the Q3 comment in `_policy_mismatches`.
XCDR1_ID = 0

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
DOC_OMG_DDS_RTPS = "https://github.com/omg-dds/dds-rtps"


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


def _unevaluated(label, reason):
  """A record that one policy was not compared, and why.

  Distinguished from a mismatch dict by the `reason` key. Every rule that
  declines returns one of these rather than None, so that the absence of an
  incompatibility never has to stand in for two different answers.
  """
  return {"policy": label, "reason": reason}


def _sort_unevaluated(result, mismatches, unevaluated):
  """File a rule's outcome under the mismatch or the incomplete-evidence list."""
  if result is None:
    return
  if "reason" in result:
    unevaluated.append(result)
  else:
    mismatches.append(result)


def _ordered_rule(label, writer_policy, reader_policy, order, explanation,
                  attributes=("kind",), reader_accepts_any=()):
  """Compare an ordered policy. Returns a mismatch, an unevaluated record, or None.

  ``reader_accepts_any`` names reader kinds that are compatible with every
  writer, so there is nothing to compare and nothing missing either - unlike
  a kind that is simply absent from ``order``.
  """
  offered, offered_name = _rank(writer_policy, order, attributes)
  requested, requested_name = _rank(reader_policy, order, attributes)
  unreadable = [side for side, name in (("writer", offered_name),
                                        ("reader", requested_name))
                if name is None]
  if unreadable:
    return _unevaluated(label, f"The {label} kind was not readable in the "
                               f"discovery data of the {' and '.join(unreadable)}.")
  if requested_name in reader_accepts_any:
    return None
  if offered is None or requested is None:
    # Readable, but outside the ordered kinds - PRESENTATION HIGHEST_OFFERED is
    # the intended case. Not a gap in the data, but still not a comparison.
    unranked = " and ".join(
        f"{side} {name}" for side, name, rank in
        (("writer", offered_name, offered), ("reader", requested_name, requested))
        if rank is None)
    return _unevaluated(label, f"No requested/offered ordering applies to "
                               f"{unranked}, so this policy was not compared.")
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
  unreadable = [side for side, value in (("writer", offered), ("reader", requested))
                if value is None]
  if unreadable:
    return _unevaluated(label, f"The {label} value was not readable in the "
                               f"discovery data of the {' and '.join(unreadable)}.")
  if offered <= requested:
    return None
  return {
      "policy": label,
      "offered": f"{offered:g}s",
      "requested": f"{requested:g}s",
      "rule": explanation,
  }


#: Distinguishes "the binding returned None" from "the attribute was absent or
#: raised". Both are unreadable here, but the sentinel keeps that a deliberate
#: decision rather than an accident of compat.get's default.
_UNREADABLE = object()


def _partition_names(policy):
  """``(names, readable)`` for a PARTITION policy.

  ``([], True)`` is the explicit default partition - the endpoint really did
  assert the single empty-string partition. ``([], False)`` means the policy
  could not be read at all, which is not a partition claim and must never be
  compared: the endpoint may well be in "telemetry".
  """
  if policy is None:
    return [], False
  names = compat.get(policy, "name", _UNREADABLE)
  if names is _UNREADABLE or names is None:
    return [], False
  # A bare string is one partition name, not a sequence of one-character names.
  # Iterating it produced "t, e, l, e, m, ..." and a false PARTITION mismatch.
  if isinstance(names, str):
    return [names], True
  try:
    return [str(name) for name in names], True
  except TypeError:
    return [], False


def _partitions_overlap(writer_endpoint, reader_endpoint):
  """DDS partition matching, including the empty-default and wildcard cases.

  The overlap is ``None`` when either side's policy was unreadable, so callers
  can decline to evaluate rather than convert missing data into a mismatch.
  """
  import fnmatch

  writer_names, writer_readable = _partition_names(writer_endpoint.partition)
  reader_names, reader_readable = _partition_names(reader_endpoint.partition)
  if not (writer_readable and reader_readable):
    return None, writer_names, reader_names

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

  Returns ``(mismatches, unevaluated)``. A mismatch dict is an observed
  incompatibility; an unevaluated dict names a policy whose discovery data was
  not readable on one or both sides. Discovery data that could not be read is
  never converted into an incompatibility claim - but it is not silently
  dropped either, because "no mismatch" and "nothing to compare" are different
  answers and the operator ships on the first one.

  An empty ``mismatches`` means "no incompatibility observable from discovery
  data" - not a guarantee of matching, since type assignability and security
  are checked elsewhere.
  """
  mismatches = []
  unevaluated = []

  rule = _ordered_rule(
      "RELIABILITY", writer.reliability, reader.reliability, RELIABILITY_ORDER,
      "A RELIABLE reader cannot match a BEST_EFFORT writer. The reader may "
      "request BEST_EFFORT from a RELIABLE writer, but not the reverse.")
  _sort_unevaluated(rule, mismatches, unevaluated)

  rule = _ordered_rule(
      "DURABILITY", writer.durability, reader.durability, DURABILITY_ORDER,
      "The writer must offer durability at least as strong as the reader "
      "requests: VOLATILE < TRANSIENT_LOCAL < TRANSIENT < PERSISTENT.")
  _sort_unevaluated(rule, mismatches, unevaluated)

  rule = _ordered_rule(
      "LIVELINESS", writer.liveliness, reader.liveliness, LIVELINESS_ORDER,
      "The writer's liveliness kind must be at least as strong as the reader's: "
      "AUTOMATIC < MANUAL_BY_PARTICIPANT < MANUAL_BY_TOPIC.")
  _sort_unevaluated(rule, mismatches, unevaluated)

  rule = _ordered_rule(
      "DESTINATION_ORDER", writer.destination_order, reader.destination_order,
      DESTINATION_ORDER_ORDER,
      "The writer's destination order must be at least as strong as the "
      "reader's: BY_RECEPTION_TIMESTAMP < BY_SOURCE_TIMESTAMP.")
  _sort_unevaluated(rule, mismatches, unevaluated)

  rule = _ordered_rule(
      "PRESENTATION access_scope", writer.presentation, reader.presentation,
      PRESENTATION_ORDER,
      "The writer's presentation access scope must be at least as broad as the "
      "reader's: INSTANCE < TOPIC < GROUP.",
      attributes=("access_scope", "kind"),
      # HIGHEST_OFFERED means "use whatever each remote Publisher offers", so
      # it matches every writer. That is an answer, not a gap in the evidence.
      reader_accepts_any=("HIGHEST_OFFERED",))
  _sort_unevaluated(rule, mismatches, unevaluated)

  rule = _duration_rule(
      "DEADLINE", compat.get(writer.deadline, "period", None),
      compat.get(reader.deadline, "period", None),
      "The writer's deadline period must be less than or equal to the reader's, "
      "so the writer promises updates at least as often as the reader requires.")
  _sort_unevaluated(rule, mismatches, unevaluated)

  rule = _duration_rule(
      "LATENCY_BUDGET", compat.get(writer.latency_budget, "duration", None),
      compat.get(reader.latency_budget, "duration", None),
      "The writer's latency budget duration must be less than or equal to the "
      "reader's.")
  _sort_unevaluated(rule, mismatches, unevaluated)

  rule = _duration_rule(
      "LIVELINESS lease_duration",
      compat.get(writer.liveliness, "lease_duration", None),
      compat.get(reader.liveliness, "lease_duration", None),
      "The writer's liveliness lease duration must be less than or equal to the "
      "reader's.")
  _sort_unevaluated(rule, mismatches, unevaluated)

  for name in ("coherent_access", "ordered_access"):
    label = f"PRESENTATION {name}"
    writer_value = compat.get(writer.presentation, name, _UNREADABLE)
    reader_value = compat.get(reader.presentation, name, _UNREADABLE)
    # An unreadable flag is not an offer of false. Reading it as one made a
    # writer whose PRESENTATION never survived discovery fail against every
    # reader that requests coherent or ordered access - the same false ERROR
    # the sibling access_scope rule already declines to make.
    unreadable = [side for side, value in (("writer", writer_value),
                                           ("reader", reader_value))
                  if value is _UNREADABLE or value is None]
    if unreadable:
      unevaluated.append(_unevaluated(
          label, f"The {name} flag was not readable in the discovery data of "
                 f"the {' and '.join(unreadable)}, so it is neither an offer "
                 f"nor a request."))
    elif reader_value and not writer_value:
      mismatches.append({
          "policy": label,
          "offered": str(bool(writer_value)),
          "requested": str(bool(reader_value)),
          "rule": f"A writer must offer {name}=true when the reader requests it.",
      })

  # OWNERSHIP is not ordered - the kinds must be identical.
  writer_ownership = _kind_name(writer.ownership)
  reader_ownership = _kind_name(reader.ownership)
  unreadable = [side for side, name in (("writer", writer_ownership),
                                        ("reader", reader_ownership)) if not name]
  if unreadable:
    unevaluated.append(_unevaluated(
        "OWNERSHIP", f"The OWNERSHIP kind was not readable in the discovery "
                     f"data of the {' and '.join(unreadable)}."))
  elif writer_ownership != reader_ownership:
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
  #
  # Measured 2026-08-11 (`test/test_data_representation_spike.py`): a *Connext*
  # writer cannot produce a multi-value list at all - the QoS is rejected locally
  # with "Writer can't have more than one" - so the list reasoning above only
  # ever applies to a foreign vendor. The branch below is still correct; it is
  # narrower in reach than it looks.
  #
  # Q3, decided 2026-08-12. An empty *writer* advertisement is not "said
  # nothing": for every vendor where it has been measured it means XCDR1, and
  # such a writer really is refused by an XCDR2-only reader with
  # `requested_incompatible_qos` naming DataRepresentation. Declining to compare
  # it reported that genuinely broken pair as `qos.compatible` at exit 0 - on
  # the most common configuration there is, a writer that never set the policy.
  #
  # So the emptiness is resolved to XCDR1 and compared, but only for the vendors
  # in `vendors.EMPTY_REPRESENTATION_MEANS_XCDR1`, which is the measured scope
  # and not a spec reading. A Cyclone or unrecognized writer still declines,
  # because Cyclone documents resolving an unspecified policy to XCDR2 - the
  # opposite meaning from the same wire state.
  #
  # Reader-side emptiness is untouched and still declines. That asymmetry is
  # measured too: a default reader advertises XCDR1 concretely while a default
  # writer advertises nothing, so an empty *reader* list is genuinely unread
  # rather than meaningful.
  writer_ids = records.representation_ids(writer.representation)
  reader_ids = records.representation_ids(reader.representation)
  writer_representation_inferred = False
  # `representation_ids` returns [] for BOTH an advertised empty sequence and a
  # policy that could not be read at all, and only the first was measured to
  # mean XCDR1. Inferring from the second would convert unreadable input into a
  # positive claim and a false ERROR - which is precisely Q1 and Q2, in a new
  # place. The presence of the policy object is what separates them.
  if (not writer_ids and reader_ids
      and writer.representation is not None
      and vendors.empty_representation_means_xcdr1(
          getattr(writer, "vendor_id", None))):
    writer_ids = [XCDR1_ID]
    writer_representation_inferred = True
  # An empty list is "could not read" (records.representation_ids says so), and
  # AUTO leaves the effective representation undetermined from discovery alone.
  if not (writer_ids and reader_ids):
    empty = [side for side, ids_ in (("writer", writer_ids), ("reader", reader_ids))
             if not ids_]
    unevaluated.append(_unevaluated(
        "DATA_REPRESENTATION",
        f"The {' and '.join(empty)} advertised no data representation in "
        f"discovery, so the writer's effective representation could not be "
        f"compared against what the reader accepts."))
  elif -1 in writer_ids or -1 in reader_ids:
    auto = [side for side, ids_ in (("writer", writer_ids), ("reader", reader_ids))
            if -1 in ids_]
    unevaluated.append(_unevaluated(
        "DATA_REPRESENTATION",
        f"The {' and '.join(auto)} advertised AUTO, whose effective "
        f"representation is not determinable from discovery data."))
  elif writer_ids[0] not in set(reader_ids):
    # Report what was on the wire, then what it means. Rendering an inferred
    # XCDR1 as though the writer had advertised it would be a positive claim
    # about discovery data that does not exist - the mistake Q1 and Q2 were.
    offered = records.representation_text(writer.representation)
    rule = ("The reader must accept the writer's effective data "
            "representation, which is the first entry in the writer's list "
            "(XCDR1/XCDR2).")
    if writer_representation_inferred:
      offered = f"{offered} (XCDR1 in effect)"
      rule = ("A writer that advertises no data representation is using XCDR1, "
              "measured for this vendor against live middleware, and the reader "
              "does not accept XCDR1. The middleware refuses this pair with "
              "requested_incompatible_qos naming DataRepresentation.")
    mismatches.append({
        "policy": "DATA_REPRESENTATION",
        "offered": offered,
        "requested": records.representation_text(reader.representation),
        "rule": rule,
    })

  overlap, writer_partitions, reader_partitions = _partitions_overlap(writer, reader)
  if overlap is None:
    unevaluated.append(_unevaluated(
        "PARTITION",
        "The PARTITION policy was not readable in the discovery data of one or "
        "both endpoints, so no partition claim can be made for either side. An "
        "unreadable policy is not the default partition."))
  elif not overlap:
    mismatches.append({
        "policy": "PARTITION",
        "offered": ", ".join(writer_partitions) or "(default)",
        "requested": ", ".join(reader_partitions) or "(default)",
        "rule": "Reader and writer must share at least one partition name. "
                "Partitions are matched as strings, with wildcards allowed.",
    })

  return mismatches, unevaluated


def _unevaluated_text(unevaluated):
  """Sentence naming the policies that were not compared, or an empty string.

  Appended to the `observed` line of both QoS verdicts: an operator reading
  "no observable QoS mismatch" needs to know when a policy was skipped for
  want of data rather than found compatible.
  """
  if not unevaluated:
    return ""
  policies = ", ".join(item["policy"] for item in unevaluated)
  return (f" Not evaluated ({policies}): this pair was neither confirmed "
          f"compatible nor found incompatible on these policies.")


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
          refs=[DOC_OMG_DDS_RTPS],
      )]
    return []

  out = []
  for peer in peers:
    writer = endpoint if endpoint.is_writer else peer
    reader = peer if endpoint.is_writer else endpoint
    mismatches, unevaluated = compare_endpoints(writer, reader)

    writer_participant = context.registry.participant_for(writer)
    reader_participant = context.registry.participant_for(reader)
    writer_label = _label(writer, writer_participant)
    reader_label = _label(reader, reader_participant)
    evidence = {"writer": writer_label, "reader": reader_label,
                "writer_key": writer.key, "reader_key": reader.key,
                "writer_participant_key": writer.participant_key,
                "reader_participant_key": reader.participant_key,
                "topic_name": writer.topic_name}
    if unevaluated:
      evidence["policies_unevaluated"] = unevaluated

    if not mismatches:
      out.append(Finding(
          id="qos.compatible",
          rung=RUNG_MATCH,
          severity=Severity.OK,
          title=f"No observable QoS mismatch: {writer_label} -> {reader_label}",
          observed=("No requested/offered incompatibility was observed in the "
                    "discovery QoS available for this pair." +
                    _unevaluated_text(unevaluated)),
          evidence=evidence,
            refs=[DOC_OMG_DDS_RTPS],
      ))
      continue

    detail = "; ".join(
        f"{m['policy']}: writer offers {m['offered']}, reader requests {m['requested']}"
        for m in mismatches)
    rules = " ".join(m["rule"] for m in mismatches)
    policies = ", ".join(m["policy"] for m in mismatches)

    evidence["mismatches"] = mismatches
    out.append(Finding(
        id="qos.rxo_mismatch",
        rung=RUNG_MATCH,
        severity=Severity.ERROR,
        title=f"QoS incompatible ({policies}): {writer_label} -> {reader_label}",
        observed=detail + "." + _unevaluated_text(unevaluated),
        root_cause=(
            "These two endpoints are both live in the system and will never "
            "communicate: DDS only matches a reader to a writer when every "
            "requested/offered policy is compatible. " + rules),
        remedy=(f"Change {policies} on one side. The reader is the constrained "
                f"side - it must request no more than the writer offers."),
        evidence=evidence,
          refs=[DOC_OMG_DDS_RTPS],
    ))
  return out


def _label(endpoint, participant):
  who = participant.name if participant is not None and participant.name else "?"
  vendor = participant.vendor_name if participant is not None else "unknown vendor"
  return f"{endpoint.kind} in '{who}' ({vendor})"


CHECKS = (check_rxo_pairs,)
