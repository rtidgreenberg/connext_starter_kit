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
  #
  # Everything below is phrased for the role of the endpoint being diagnosed.
  # Targeted diagnosis accepts either role, and a reader whose schema never
  # resolved used to be reported as a writer fault - sending the operator to a
  # publisher that may be entirely healthy.
  role = "writer" if endpoint.is_writer else "reader"
  peer_side = "publisher" if endpoint.is_writer else "subscriber"
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
      f"be created from it. Either enable full type propagation on the "
      f"{peer_side} that owns this {role}, or supply the IDL locally and use a "
      "compile-time type instead of DynamicData.")
  if endpoint.vendor_name == vendors.FASTDDS:
    remedy += (
        f" For Fast DDS, first upgrade that {peer_side} to Fast DDS 3.6.2 or "
        "newer: the validated 3.6.2 fixture resolves a Connext DynamicType "
        "before investigating TypeLookup or TypeObject compatibility further.")
    connext_version = compat.version_tuple()
    if (context.type_information_observed
        and connext_version is not None and connext_version < (7, 7)):
      remedy += (
          " The capture observed PID_TYPE_INFORMATION from this Fast DDS "
          f"participant, but Connext {compat.connext_version()} did not resolve "
          "a DynamicType. Recording Service needs the runtime schema; upgrade "
          "the local Connext runtime to 7.7 or newer before diagnosing the "
          "Fast DDS TypeLookup exchange further.")

  scope_note = (
      "This is the schema of the endpoint named above and of no other: an "
      f"unresolved {role} type says nothing about the health of the endpoints "
      "on the other side of the topic.")

  return [Finding(
      id="type.no_type_info",
      rung=RUNG_TYPE,
      severity=Severity.ERROR,
      title=f"No type information available for this {role}",
      observed=(f"Topic '{endpoint.topic_name}' type name '{endpoint.type_name}' is "
                f"visible on this {role}, but no DynamicType arrived within "
                f"{context.type_wait:.1f}s. request_types_filter = {request_filter}."),
      root_cause=(
          "The topic and type NAME come from plain endpoint-discovery strings, but "
          "the schema comes from a separate request/reply service. Seeing the name "
          "without the schema is the single most common cross-vendor state. " +
          scope_note + " Possible causes: " + "; ".join(causes) + "."),
        remedy=remedy,
      evidence={"topic_name": endpoint.topic_name,
                "type_name": endpoint.type_name,
                "endpoint_role": role,
                "request_types_filter": request_filter,
                "type_information_observed": context.type_information_observed,
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
      # endpoint on it the caller happened to be iterating. The `linked_*` keys
      # name every endpoint involved without entering the issue key, so the
      # Health column and the `i` filter can find this issue from any of them
      # while it stays one issue. Identity under its own name is what would
      # split it back into one issue per endpoint - see system_scan._issue_key.
      evidence={"scope": "topic", "topic_name": endpoint.topic_name,
                "type_names": sorted(names),
                "linked_writer_keys": sorted(
                    peer.key for peer in peers if peer.is_writer),
                "linked_reader_keys": sorted(
                    peer.key for peer in peers if not peer.is_writer),
                "linked_participant_keys": sorted(
                    {peer.participant_key for peer in peers
                     if peer.participant_key})},
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

  # `readers` are all resolved - that is the filter above. Whether each one can
  # actually be compared is a second question, and the two counts must not be
  # reported as one: "every resolved reader accepts this writer (1 reader)" over
  # three resolved readers is an all-clear covering a third of the topic.
  results = []
  unevaluable = []
  for reader in readers:
    assignable, reason = _assignable(reader.type, endpoint.type)
    if assignable is None:
      unevaluable.append(_unevaluable(reader, reason))
      continue
    results.append((reader, assignable))

  if not results:
    return [Finding(
        id="type.assignability",
        rung=RUNG_TYPE,
        # INFO, not OK: nothing was compared. Returning [] here made a topic
        # whose readers cannot be evaluated indistinguishable from a topic with
        # no readers at all - the absence of the finding read as "not
        # applicable" when it meant "not knowable".
        severity=Severity.INFO,
        title=f"Assignability could not be evaluated on '{endpoint.topic_name}'",
        observed=(f"{len(readers)} resolved reader type(s) on this topic, none of "
                  f"which could be compared with '{endpoint.type_name}'."
                  + _unevaluable_text(unevaluable)),
        root_cause=(
            "Connext's external assignability check runs on the reader's own "
            "type binding. A type representation that exposes no "
            "is_assignable_from(), or a call that fails, leaves the structural "
            "comparison unavailable - which is neither compatible nor "
            "incompatible. Cross-vendor and non-native type representations are "
            "the usual reason."),
        remedy=("Compare the two IDL definitions in appendix A by hand; this "
                "tool could not do it for you on this topic."),
        # Topic-scoped: every writer on the topic faces the same unevaluable
        # readers, so this is one condition, not one per writer.
        evidence={"scope": "topic",
                  "topic_name": endpoint.topic_name,
                  "writer_type": endpoint.type_name,
                  "resolved_reader_count": len(readers),
                  "evaluated_reader_count": 0,
                  "unevaluable_reader_count": len(unevaluable),
                  "readers_unevaluated": unevaluable},
        refs=[DOC_ASSIGNABILITY],
    )]

  incompatible = [(reader, value) for reader, value in results if not value]
  if incompatible:
    reader, _ = incompatible[0]
    return [Finding(
        id="type.assignability",
        rung=RUNG_TYPE,
        severity=Severity.ERROR,
      title=f"External assignability check fails on '{endpoint.topic_name}'",
        observed=(f"is_assignable_from: {reader.type_name} <- {endpoint.type_name} = "
                  f"False ({len(incompatible)} of {len(results)} evaluated "
                  f"reader(s) reject this writer; {len(readers)} resolved on the "
                  "topic)." + _unevaluable_text(unevaluable)),
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
            "resolved_reader_count": len(readers),
            "evaluated_reader_count": len(results),
            "unevaluable_reader_count": len(unevaluable),
            "readers_unevaluated": unevaluable,
            "incompatible_reader_count": len(incompatible),
        },
        refs=[DOC_ASSIGNABILITY],
    )]

  return [Finding(
      id="type.assignability",
      rung=RUNG_TYPE,
      severity=Severity.OK,
      title=f"Writer type is assignable to discovered readers on '{endpoint.topic_name}'",
      observed=(f"is_assignable_from: every evaluated reader type <- "
                f"{endpoint.type_name} = True ({len(results)} of {len(readers)} "
                "resolved reader(s) evaluated)."
                + _unevaluable_text(unevaluable)),
      evidence={
          "topic_name": endpoint.topic_name,
          "writer_type": endpoint.type_name,
          "resolved_reader_count": len(readers),
          "evaluated_reader_count": len(results),
          "unevaluable_reader_count": len(unevaluable),
          "readers_unevaluated": unevaluable,
          "reader_accepts_writer": True,
      },
      refs=[DOC_ASSIGNABILITY],
  )]


def _assignable(target, source):
  """`(target.is_assignable_from(source), None)`, or `(None, reason)`.

  Two different failures used to collapse into one bare `None`: a binding that
  offers no structural comparison at all, and a comparison that was attempted
  and raised. Both leave the pair unevaluated, and an operator reading the
  report needs to know which.
  """
  method = compat.get(target, "is_assignable_from", None)
  if not callable(method):
    return None, ("this type binding exposes no is_assignable_from(), so no "
                  "structural comparison could be attempted")
  try:
    return bool(method(source)), None
  except Exception as error:  # noqa: BLE001 - an unevaluable reader, not a crash
    return None, f"is_assignable_from() raised {type(error).__name__}: {error}"


def _unevaluable(reader, reason):
  """One reader that could not be compared, and why.

  `{policy, reason}` is the incomplete-evidence shape the QoS rules already
  use; `reader`/`reader_key` name which of several readers this record is
  about, which a per-policy record has no need for.
  """
  return {"policy": "type assignability",
          "reader": reader.type_name or reader.key,
          "reader_key": reader.key,
          "reason": reason}


def _unevaluable_text(unevaluable):
  """Sentence naming the readers that were not compared, or an empty string.

  Appended to the `observed` line of every assignability verdict: an operator
  reading "every evaluated reader accepts this writer" needs to know when a
  reader was skipped for want of a usable binding rather than found compatible.
  """
  if not unevaluable:
    return ""
  names = ", ".join(sorted({item["reader"] for item in unevaluable}))
  return (f" Not evaluated ({len(unevaluable)} reader(s): {names}): these were "
          "neither confirmed compatible nor found incompatible.")


def check_extensibility(context):
  """Describe the type's declared extensibility. Targeted diagnosis only.

  This reads the IDL declaration, not the system: it says how the type is
  allowed to evolve, never that anything has gone wrong. `type.assignability`
  is the check that compares real schemas against real readers, and it is what
  an operator should act on. Deliberately not in the system census - one
  descriptive note about a type shared by 96 endpoints put 96 byte-identical
  entries in the issue list.
  """
  endpoint = context.endpoint
  if endpoint is None or endpoint.type is None:
    return []

  mapping = typewalk.extensibility_map(endpoint.type)
  if not mapping:
    return []

  finals = [name for name, kind in mapping.items() if "FINAL" in str(kind).upper()]
  mixed = len({str(k).upper().split(".")[-1] for k in mapping.values()}) > 1
  observed = "; ".join(f"{n} = {k}" for n, k in sorted(mapping.items()))

  if not finals and not mixed:
    return [Finding(
        id="type.extensibility",
        rung=RUNG_TYPE,
        severity=Severity.OK,
        title="Type extensibility",
        observed=observed,
        evidence=mapping,
    )]

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
  root.append(
      "This describes how the type is declared, not anything observed on this "
      "system: no reader has been found to reject this writer here. Read it "
      "alongside type.assignability, which compares the actual schemas.")

  return [Finding(
      id="type.extensibility",
      rung=RUNG_TYPE,
      # INFO, not WARN. A declared extensibility kind is a property of the IDL
      # and a risk to future changes; calling it a warning put a type-design
      # note into the issue list and the nonzero exit path of a system whose
      # every pair the tool had just confirmed assignable.
      severity=Severity.INFO,
      title="Type extensibility limits how this type can evolve",
      observed=observed,
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
    # Same distinction `qos_match` makes: an absent policy object is unreadable,
    # not an advertised empty sequence, and only the latter has a measured
    # meaning. The observed line below claims the sequence was "readable", so
    # saying `empty_means_xcdr1` here for an unreadable policy would contradict
    # it and licence an inference nothing measured.
    advertised_empty = endpoint.representation is not None
    known = advertised_empty and vendors.empty_representation_means_xcdr1(
        endpoint.vendor_id)
    # Q3, decided 2026-08-12. This finding used to say the emptiness "says
    # nothing about what the writer supports, so NO incompatibility should be
    # inferred from it" - which, once `qos_match` started inferring XCDR1 and
    # raising an ERROR for it, made the report contradict itself in two
    # adjacent findings. What the emptiness means now depends on the vendor,
    # and this text says which.
    if known:
      root_cause = (
          "A writer using the default DataRepresentationQosPolicy advertises an "
          "empty sequence. For this vendor that emptiness has been measured "
          "against live middleware to mean XCDR1: a writer configured "
          "explicitly [XCDR1] advertises the same empty sequence, the pair "
          "matches an XCDR1 reader and delivers, and an XCDR2-only reader "
          "refuses it naming DataRepresentation. So the RxO comparison treats "
          "this writer as XCDR1 rather than declining, and any resulting "
          "qos.rxo_mismatch above is the middleware's own verdict. This is "
          "recorded separately so the wire fact - that nothing was advertised - "
          "stays visible behind the inference drawn from it.")
    elif advertised_empty:
      root_cause = (
          "A writer using the default DataRepresentationQosPolicy advertises an "
          "empty sequence. What that means has not been measured for this "
          "vendor, and it is not the same for all of them - Cyclone documents "
          "resolving an unspecified policy from the type's defaults, which can "
          "select XCDR2, the opposite of what RTI and Fast DDS were measured to "
          "mean by the identical wire state. So NO incompatibility is inferred "
          "from it here, and the RxO comparison declines DATA_REPRESENTATION "
          "rather than guessing.")
    else:
      root_cause = (
          "The DataRepresentation policy could not be read from this endpoint's "
          "discovery data at all. That is not the same as a writer advertising "
          "an empty sequence, and it carries none of the meaning measured for "
          "one: NO incompatibility is inferred from it, and the RxO comparison "
          "declines DATA_REPRESENTATION. An unreadable policy is not evidence "
          "about what the writer offers, in either direction.")
    return [Finding(
        id="repr.not_advertised",
        rung=RUNG_TYPE,
        # OK either way: this finding records a wire fact. When the emptiness is
        # meaningful the ERROR belongs to qos.rxo_mismatch, which compares the
        # pair; when it is not, there is nothing to report. Neither case is an
        # issue in its own right.
        severity=Severity.OK,
        title=("Writer advertises no explicit data representation"
               if advertised_empty else
               "Writer data representation could not be read"),
        observed=("PublicationBuiltinTopicData.representation is an empty "
                  "sequence (readable, but carrying no representation ids)."
                  if advertised_empty else
                  "PublicationBuiltinTopicData.representation could not be read."),
        root_cause=root_cause,
        remedy="",
        evidence={"representation": "not advertised" if advertised_empty
                                    else "unreadable",
                  "empty_means_xcdr1": known},
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
