"""Rung 3 checks: type resolution and type compatibility.

This is the weakest rung cross-vendor and the one that most often explains
"I can see the topic but nothing works". The distinction that matters most is
between "no type yet" and "no type ever", which is why type_state is a state
machine rather than a snapshot.
"""

from .. import compat, records, typewalk, vendors
from ..findings import RUNG_TYPE, Finding, Severity
from ..records import TYPE_PENDING, TYPE_RESOLVED

DOC_TYPELOOKUP = ("https://community.rti.com/static/documentation/connext-dds/7.7.0/"
                  "doc/manuals/connext_dds_professional/users_manual/users_manual/"
                  "TypeLookupService.htm")
DOC_TYPE_REPR = ("https://community.rti.com/static/documentation/connext-dds/7.7.0/"
                 "doc/manuals/connext_dds_professional/extensible_types_guide/"
                 "extensible_types/Type_Representation.htm")
DOC_ASSIGNABILITY = ("https://community.rti.com/static/documentation/connext-dds/7.7.0/"
                     "doc/manuals/connext_dds_professional/extensible_types_guide/"
                     "extensible_types/Verifying_Type_Consistency__Type_Assignabilit.htm")


def check_type_state(context):
  """The central rung-3 check: is there a usable schema, and if not, why not?"""
  endpoint = context.endpoint
  if endpoint is None:
    return []

  if endpoint.type_state == TYPE_RESOLVED:
    delay = endpoint.type_resolution_delay
    delay_text = f" {delay:.1f}s after first discovery" if delay is not None else ""
    return [Finding(
        id="type.resolved",
        rung=RUNG_TYPE,
        severity=Severity.OK,
        title="Type information resolved",
        observed=f"DynamicType for '{endpoint.type_name}' is available{delay_text}.",
        evidence={"type_name": endpoint.type_name,
                  "resolution_delay_seconds": delay},
    )]

  if endpoint.type_state == TYPE_PENDING:
    return [Finding(
        id="type.no_type_info",
        rung=RUNG_TYPE,
        severity=Severity.INFO,
        title="Type resolution still in flight",
        observed=(f"No DynamicType for '{endpoint.type_name}' yet; the "
                  f"{context.type_wait:.1f}s type-wait window has not elapsed."),
        root_cause=(
            "With TypeObject v2, endpoint discovery carries only a TypeIdentifier "
            "hash and Connext resolves the full TypeObject asynchronously through "
            "the TypeLookup service, re-delivering the discovery sample when it "
            "completes. An empty type this early is normal, not a fault."),
        remedy="Wait, or raise --type-wait, before concluding the type is unavailable.",
        evidence={"type_name": endpoint.type_name, "type_state": endpoint.type_state},
        refs=[DOC_TYPELOOKUP],
    )]

  # UNAVAILABLE: the wait elapsed with no type. Enumerate the real causes rather
  # than asserting one, and rule out the one cause that would be our own fault.
  request_filter = context.type_lookup_settings.get("request_types_filter")
  our_filter_ok = request_filter == "*"
  causes = [
      "the peer advertises TypeInformation but never answers TypeLookup requests "
      "(most common cross-vendor cause)",
      "the peer serves only a MINIMAL TypeObject, so member names are unavailable",
      "the peer propagates no type representation at all (some vendors make this "
      "opt-in, and it can be disabled outright)",
      "the peer's type propagation is disabled locally on its side, e.g. by "
      "setting type_object_max_serialized_length to 0, which disables both "
      "TypeObject v1 and v2",
  ]
  if not our_filter_ok:
    causes.insert(0, (
        "rti_doctor's own request_types_filter is not '*' on this Connext "
        f"version ({request_filter}), so Connext may never have requested the "
        "type - this cause is on our side and should be ruled out first"))

  remedy = (
      "A TypeIdentifier alone is an identifier, not a schema, so no reader can "
      "be created from it. Either enable full type propagation on the "
      "publisher, or supply the IDL locally and use a compile-time type "
      "instead of DynamicData.")
  if endpoint.vendor_name == vendors.FASTDDS:
    remedy += (
        " For Fast DDS, first upgrade the publisher to Fast DDS 3.6.2 or newer: "
        "the validated 3.6.2 fixture resolves a Connext DynamicType before "
        "investigating TypeLookup or TypeObject compatibility further.")

  return [Finding(
      id="type.no_type_info",
      rung=RUNG_TYPE,
      severity=Severity.ERROR,
      title="No type information available for this writer",
      observed=(f"Topic '{endpoint.topic_name}' type name '{endpoint.type_name}' is "
                f"visible, but no DynamicType arrived within "
                f"{context.type_wait:.1f}s. request_types_filter = {request_filter}."),
      root_cause=(
          "The topic and type NAME come from plain endpoint-discovery strings, but "
          "the schema comes from a separate request/reply service. Seeing the name "
          "without the schema is the single most common cross-vendor state. "
          "Possible causes: " + "; ".join(causes) + "."),
        remedy=remedy,
      evidence={"topic_name": endpoint.topic_name,
                "type_name": endpoint.type_name,
                "request_types_filter": request_filter,
                "type_wait_seconds": context.type_wait},
      refs=[DOC_TYPELOOKUP, DOC_TYPE_REPR],
  )]


def check_type_name_conflict(context):
  """Same topic advertised with different type names."""
  endpoint = context.endpoint
  if endpoint is None or context.registry is None:
    return []

  peers = context.registry.endpoints_on_topic(endpoint.topic_name)
  names = {}
  for peer in peers:
    if peer.type_name:
      names.setdefault(peer.type_name, []).append(peer)
  if len(names) < 2:
    return []

  detail = "; ".join(
      f"'{name}' ({len(items)} endpoint(s): "
      f"{', '.join(sorted({i.kind for i in items}))})"
      for name, items in sorted(names.items()))
  return [Finding(
      id="type.name_conflict",
      rung=RUNG_TYPE,
      # WARN, not ERROR. A name difference is not proof of incompatibility: the
      # reader's TypeConsistencyEnforcement is not published in discovery, and
      # a reader that ignores the type name matches anyway. Asserting ERROR here
      # contradicted this tool's own type.assignability finding, which compares
      # the actual schemas, whenever the two disagreed.
      severity=Severity.WARN,
      title=f"Topic '{endpoint.topic_name}' is advertised with {len(names)} different type names",
      observed=detail,
      root_cause=(
          "DDS matches a reader to a writer on topic name, and then requires the "
          "types to be compatible. Cross-vendor this is often an IDL "
          "module/namespace difference rather than a genuinely different type - "
          "for example 'Sensor' versus 'sensors::Sensor' - and a reader "
          "configured to ignore the type name still matches. Check the "
          "type.assignability finding, which compares the schemas themselves, "
          "before treating this as the cause of a match failure."),
      remedy=("Align the type names, or configure type-consistency enforcement to "
              "ignore the name difference if the structures really are compatible."),
      # Topic-scoped: the condition belongs to the topic, not to whichever
      # endpoint on it the caller happened to be iterating.
      evidence={"scope": "topic", "topic_name": endpoint.topic_name,
                "type_names": sorted(names)},
      refs=[DOC_ASSIGNABILITY],
  )]


def check_assignability(context):
  """Externally verify whether discovered readers can accept this writer's type."""
  endpoint = context.endpoint
  if (endpoint is None or not endpoint.is_writer or endpoint.type is None
      or context.registry is None):
    return []

  readers = [e for e in context.registry.endpoints_on_topic(endpoint.topic_name)
             if not e.is_writer and e.type is not None]
  if not readers:
    return []

  results = []
  for reader in readers:
    assignable = _assignable(reader.type, endpoint.type)
    if assignable is None:
      continue
    results.append((reader, assignable))

  if not results:
    return []

  incompatible = [(reader, value) for reader, value in results if not value]
  if incompatible:
    reader, _ = incompatible[0]
    return [Finding(
        id="type.assignability",
        rung=RUNG_TYPE,
        severity=Severity.ERROR,
      title=f"External assignability check fails on '{endpoint.topic_name}'",
        observed=(f"is_assignable_from: {reader.type_name} <- {endpoint.type_name} = "
                  f"False ({len(incompatible)} of {len(results)} resolved reader(s) "
                  "reject this writer)."),
        root_cause=(
            "Connext's external TypeObject assignability check compares the "
            "writer's schema with each discovered reader schema. It found a "
          "reader type that rejects this writer under the standard assignability "
          "rules. The remote reader's TypeConsistencyEnforcement QoS is not "
          "published in discovery, so this result cannot state whether that "
          "reader enforces or relaxes the check while matching."),
        remedy=("Compare the two IDL definitions in appendix A. Where they should "
                "be the same type, align the definitions; where evolution is "
                "intended, make the base type APPENDABLE or MUTABLE rather than "
                "FINAL."),
        evidence={
            "topic_name": endpoint.topic_name,
            "writer_type": endpoint.type_name,
            "reader_type": reader.type_name,
            "reader_accepts_writer": False,
            "resolved_reader_count": len(results),
            "incompatible_reader_count": len(incompatible),
        },
        refs=[DOC_ASSIGNABILITY],
    )]

  return [Finding(
      id="type.assignability",
      rung=RUNG_TYPE,
      severity=Severity.OK,
      title=f"Writer type is assignable to discovered readers on '{endpoint.topic_name}'",
      observed=(f"is_assignable_from: every resolved reader type <- "
                f"{endpoint.type_name} = True ({len(results)} reader(s))."),
      evidence={
          "topic_name": endpoint.topic_name,
          "writer_type": endpoint.type_name,
          "resolved_reader_count": len(results),
          "reader_accepts_writer": True,
      },
      refs=[DOC_ASSIGNABILITY],
  )]


def _assignable(target, source):
  """target.is_assignable_from(source), or None when it cannot be evaluated."""
  method = compat.get(target, "is_assignable_from", None)
  if not callable(method):
    return None
  try:
    return bool(method(source))
  except Exception:
    return None


def check_extensibility(context):
  """Report extensibility kinds, and flag FINAL types as evolution hazards."""
  endpoint = context.endpoint
  if endpoint is None or endpoint.type is None:
    return []

  mapping = typewalk.extensibility_map(endpoint.type)
  if not mapping:
    return []

  finals = [name for name, kind in mapping.items() if "FINAL" in str(kind).upper()]
  mixed = len({str(k).upper().split(".")[-1] for k in mapping.values()}) > 1

  if not finals and not mixed:
    return [Finding(
        id="type.extensibility",
        rung=RUNG_TYPE,
        # OK, not INFO: nothing here is wrong, and the system scan lists every
        # non-OK finding as an issue. One note per endpoint about a type shared
        # by all of them put 96 identical entries in the issue list of a healthy
        # 96-endpoint domain. A targeted report still shows OK findings.
        severity=Severity.OK,
        title="Type extensibility",
        observed="; ".join(f"{n} = {k}" for n, k in sorted(mapping.items())),
        evidence=mapping,
    )]

  severity = Severity.WARN if finals else Severity.INFO
  root = []
  if finals:
    root.append(
        "A FINAL type must match bit-for-bit on both sides: no member may be "
        "added, removed, or reordered, which makes it the extensibility kind most "
        "likely to break between independently-built applications.")
  if mixed:
    root.append(
        "Nested types use more than one extensibility kind, so a change that is "
        "safe in one part of the type can be fatal in another.")

  return [Finding(
      id="type.extensibility",
      rung=RUNG_TYPE,
      severity=severity,
      title="Type extensibility may limit interoperability",
      observed="; ".join(f"{n} = {k}" for n, k in sorted(mapping.items())),
      root_cause=" ".join(root),
      remedy=("If the two sides are built from separate IDL copies, prefer "
              "APPENDABLE or MUTABLE over FINAL."),
      evidence=mapping,
      refs=[DOC_TYPE_REPR],
  )]


def check_representation(context):
  """XCDR1 vs XCDR2: does the writer offer anything our reader can decode?"""
  endpoint = context.endpoint
  if endpoint is None or not endpoint.is_writer:
    return []

  ids = records.representation_ids(endpoint.representation)
  if not ids:
    return [Finding(
        id="repr.not_advertised",
        rung=RUNG_TYPE,
        # OK: the finding's own text says no incompatibility may be inferred
        # from it and that it exists only so its absence is not mistaken for an
        # oversight. That is a statement for a targeted report, not an issue.
        severity=Severity.OK,
        title="Writer advertises no explicit data representation",
        observed=("PublicationBuiltinTopicData.representation is an empty sequence "
                  "(readable, but carrying no representation ids)."),
        root_cause=(
            "A writer using the default DataRepresentationQosPolicy advertises an "
            "empty sequence, which is what a Connext writer with default QoS looks "
            "like. This says nothing about what the writer supports, so NO "
            "incompatibility should be inferred from it - it is recorded here only "
            "so that its absence from the report is not mistaken for an oversight."),
        remedy="",
        evidence={"representation": "not advertised"},
        refs=[DOC_TYPE_REPR],
    )]

  text = records.representation_text(endpoint.representation)
  # The probe mirrors the writer's representation, so a mismatch can only arise
  # for a reader that does not. Report what was offered and flag XCDR2-only,
  # which is the combination that breaks older or conservatively-configured
  # readers.
  if ids == [2]:
    return [Finding(
        id="repr.no_common",
        rung=RUNG_TYPE,
        severity=Severity.WARN,
        title="Writer offers XCDR2 only",
        observed=f"writer data representation = {text}",
        root_cause=(
            "A reader that requests XCDR1 only - the default in some older "
            "profiles and in other vendors' conservative configurations - has no "
            "representation in common with this writer and will not match. Where "
            "it does match with a mismatched extent, trailing members of an "
            "APPENDABLE struct can silently fail to decode."),
        remedy=("Add XCDR2 to the reader's DataRepresentationQosPolicy, or have "
                "the writer offer XCDR1 as well."),
        evidence={"representation": text, "representation_ids": ids},
        refs=[DOC_TYPE_REPR],
    )]

  return [Finding(
      id="repr.offered",
      rung=RUNG_TYPE,
      severity=Severity.OK,  # context for a report, not a domain-wide issue
      title="Writer data representation",
      observed=f"writer offers {text}",
      evidence={"representation": text, "representation_ids": ids},
  )]


CHECKS = (
    check_type_state,
    check_type_name_conflict,
    check_assignability,
    check_extensibility,
    check_representation,
)
