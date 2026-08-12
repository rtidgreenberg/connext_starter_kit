"""Recursive DynamicType / DynamicData traversal - the deserialization verdict.

"Can the message be fully deserialized" is not "did take() throw". Connext can
hand back a sample where individual members are unreadable - typically because
the writer and reader disagree about encoding (XCDR1 vs XCDR2), extensibility,
or bounds - and the interesting output is *which field path* fails, not a
boolean.

This module walks the type, reads every member of a real sample, catches
per-member failures, and reports field paths. It never guesses a value: a member
that cannot be read is recorded as unreadable, never defaulted.
"""

import rti.connextdds as dds

from . import compat
from .findings import PAYLOAD_FAILED, PAYLOAD_FULL, PAYLOAD_PARTIAL

#: Hard ceilings so a hostile or corrupt sample cannot hang the walk.
MAX_ELEMENTS_PER_COLLECTION = 64
MAX_DEPTH = 12
MAX_MEMBERS = 4096


class MemberResult:
  """Outcome of reading one member. Either readable, absent, or failed."""

  READABLE = "readable"
  ABSENT = "absent"      # optional member legitimately not present
  FAILED = "failed"

  def __init__(self, path, status, kind="", detail="", value_repr=""):
    self.path = path
    self.status = status
    self.kind = kind
    self.detail = detail
    self.value_repr = value_repr

  @property
  def ok(self):
    return self.status in (MemberResult.READABLE, MemberResult.ABSENT)


class WalkReport:
  """Aggregate result of walking one sample."""

  def __init__(self):
    self.results = []
    self.truncated = False
    self.fatal = None  # set when the walk could not start at all

  def add(self, result):
    self.results.append(result)

  @property
  def leaf_results(self):
    """Results excluding container nodes, which are what "members" means here."""
    return [r for r in self.results if r.kind != "container"]

  @property
  def total(self):
    return len(self.leaf_results)

  @property
  def failed(self):
    return [r for r in self.leaf_results if r.status == MemberResult.FAILED]

  @property
  def absent(self):
    return [r for r in self.leaf_results if r.status == MemberResult.ABSENT]

  @property
  def failed_paths(self):
    return [r.path for r in self.failed]

  @property
  def verdict(self):
    if self.fatal is not None:
      return PAYLOAD_FAILED
    if not self.leaf_results:
      return PAYLOAD_FAILED
    if not self.failed:
      # FULL is a completeness claim. A walk stopped by MAX_DEPTH,
      # MAX_MEMBERS or MAX_ELEMENTS_PER_COLLECTION never visited the rest of
      # the sample, so it cannot make one.
      return PAYLOAD_PARTIAL if self.truncated else PAYLOAD_FULL
    if len(self.failed) == self.total:
      return PAYLOAD_FAILED
    return PAYLOAD_PARTIAL


# --- Type helpers ------------------------------------------------------------

def resolve_alias(dynamic_type):
  """Follow AliasType indirection to the underlying type."""
  seen = 0
  current = dynamic_type
  while current is not None and seen < MAX_DEPTH:
    kind = compat.get(current, "kind", None)
    if kind != _kind("ALIAS_TYPE"):
      return current
    nxt = compat.call(current, "resolve", compat.MISSING)
    if nxt is not compat.MISSING and nxt is not None:
      current = nxt
    else:
      current = compat.first(current, ("related_type", "resolve_type"), None)
    seen += 1
  return current


def _kind(name):
  return compat.get(getattr(dds, "TypeKind", None), name, None)


def kind_name(dynamic_type):
  """Readable type-kind name.

  Note: ``DynamicType.name`` *raises* for anonymous types such as sequences, so
  this uses ``kind`` (a plain property) rather than the type name.
  """
  if dynamic_type is None:
    return "unknown"
  kind = compat.get(dynamic_type, "kind", None)
  if kind is None:
    return "unknown"
  name = compat.get(kind, "name", None)
  return str(name) if name else str(kind)


def type_name(dynamic_type):
  """Type name, or a kind-based placeholder when the type is anonymous."""
  name = compat.get(dynamic_type, "name", None)
  if name:
    return str(name)
  return f"(anonymous {kind_name(dynamic_type)})"


def is_aggregation(dynamic_type):
  """True for structs and unions. ``is_aggregation_type`` is a METHOD."""
  return compat.call_bool(dynamic_type, "is_aggregation_type")


def is_string(dynamic_type):
  """True for string/wstring.

  DDS models strings as collections of characters, so ``is_collection_type()``
  returns True for them. For a field walk they are scalars - reporting a string
  as a container with per-character elements would be noise, not diagnosis.
  """
  kind = compat.get(dynamic_type, "kind", None)
  return kind in (_kind("STRING_TYPE"), _kind("WSTRING_TYPE"))


def is_collection(dynamic_type):
  """True for sequences and arrays, excluding strings.

  ``is_collection_type`` is a METHOD on the bindings, not a property.
  """
  if is_string(dynamic_type):
    return False
  return compat.call_bool(dynamic_type, "is_collection_type")


def is_union(dynamic_type):
  return compat.get(dynamic_type, "kind", None) == _kind("UNION_TYPE")


def extensibility_text(dynamic_type):
  """FINAL / EXTENSIBLE(APPENDABLE) / MUTABLE, or None when not applicable."""
  value = compat.get(dynamic_type, "extensibility_kind", None)
  if value is None:
    return None
  name = compat.get(value, "name", None)
  return str(name or value)


def type_members(dynamic_type):
  """Member list for an aggregation type, or [] when unavailable.

  ``members`` is a method on the bindings, hence compat.call.
  """
  members = compat.call(dynamic_type, "members", None)
  if members is None:
    return []
  try:
    return list(members)
  except Exception:
    return []


def collection_bound(collection_type):
  """Declared capacity of a sequence or array, or None when unbounded/unknown.

  SequenceType exposes ``bounds``; ArrayType exposes ``total_element_count``
  instead and has no ``bounds`` at all.
  """
  bounds = compat.get_int(collection_type, "bounds")
  if bounds is not None:
    unbounded = compat.get_int(collection_type, "UNBOUNDED")
    if unbounded is not None and bounds >= unbounded:
      return None
    return bounds
  return compat.get_int(collection_type, "total_element_count")


def enum_ordinals(dynamic_type):
  """Set of declared ordinals for an enum, or None when unreadable."""
  members = type_members(dynamic_type)
  if not members:
    return None
  out = set()
  for member in members:
    ordinal = compat.get_int(member, "ordinal")
    if ordinal is not None:
      out.add(ordinal)
  return out or None


def idl_text(dynamic_type, indent=4):
  """IDL for a type, for the report appendix. Never raises."""
  if dynamic_type is None:
    return "(no type available)"
  prop_cls = getattr(dds, "DynamicTypePrintFormatProperty", None)
  if prop_cls is not None:
    try:
      return dynamic_type.to_string(prop_cls(indent=indent))
    except Exception:
      pass
  try:
    return dynamic_type.to_string()
  except Exception:
    pass
  try:
    return str(dynamic_type)
  except Exception:
    return "(type could not be rendered)"


def count_members(dynamic_type, depth=0):
  """Total leaf members a full walk would visit, for reporting denominators."""
  dynamic_type = resolve_alias(dynamic_type)
  if dynamic_type is None or depth > MAX_DEPTH:
    return 0
  if is_aggregation(dynamic_type):
    total = 0
    for member in type_members(dynamic_type):
      total += count_members(compat.get(member, "type", None), depth + 1) or 1
    return total
  return 1


# --- Value reading -----------------------------------------------------------

def _read_member(data, name):
  """Read one member by name, trying each access strategy the API offers.

  Returns (ok, value, detail). Different Connext versions and member kinds
  respond to different accessors, so this tries them in order rather than
  assuming one works.

  Deliberately does NOT use ``loan_value``. A loan holds a bind on the parent
  until ``return_loan()``, and an outstanding bind makes every subsequent read of
  a *sibling* member fail with "self has a member with member id N bound" - so a
  walker built on loans reports phantom failures for every member after the
  first aggregate one. Subscripting returns a detached copy with no bind, which
  is what a read-only walk wants.
  """
  errors = []
  for accessor in (
      lambda: data[name],
      lambda: data.get_value(name),
  ):
    try:
      return True, accessor(), ""
    except Exception as e:  # noqa: BLE001 - any failure means "try the next"
      errors.append(f"{type(e).__name__}: {e}")
  return False, None, errors[0] if errors else "unreadable"


def _member_info(data, name):
  try:
    return data.member_info(name)
  except Exception:
    return None


def _member_present(data, member, name):
  """Optional-member presence. Absent optionals are not errors.

  Returns (present, checked) - `checked` is False when this version cannot tell,
  in which case the caller must not treat absence as a failure.
  """
  optional = compat.get(member, "optional", None)
  if not optional:
    return True, True
  try:
    return bool(data.member_exists(name)), True
  except Exception:
    return True, False


def _collection_length(data, name, info):
  if info is not None:
    count = compat.get_int(info, "element_count")
    if count is not None:
      return count
  try:
    return len(data[name])
  except Exception:
    return None


# --- The walk ----------------------------------------------------------------

def walk_sample(data, dynamic_type=None):
  """Walk every member of `data`, returning a WalkReport.

  `data` is a DynamicData sample. `dynamic_type` defaults to the sample's own
  type; pass the discovered writer type explicitly when they may differ.
  """
  report = WalkReport()
  sample_type = dynamic_type if dynamic_type is not None else compat.get(data, "type", None)
  sample_type = resolve_alias(sample_type)

  if sample_type is None:
    report.fatal = "no type available for the sample"
    return report
  if not is_aggregation(sample_type):
    report.fatal = f"top-level type is not an aggregation ({kind_name(sample_type)})"
    return report

  _walk_aggregate(data, sample_type, "", report, depth=0)
  return report


def _walk_aggregate(data, dynamic_type, prefix, report, depth):
  if depth > MAX_DEPTH:
    report.truncated = True
    return
  if len(report.results) >= MAX_MEMBERS:
    report.truncated = True
    return

  if is_union(dynamic_type):
    _walk_union(data, dynamic_type, prefix, report, depth)
    return

  for member in type_members(dynamic_type):
    if len(report.results) >= MAX_MEMBERS:
      report.truncated = True
      return
    _walk_member(data, member, prefix, report, depth)


def _walk_union(data, dynamic_type, prefix, report, depth):
  """Read the discriminator, then only the active member.

  Reading inactive union members is meaningless and would produce false
  failures, so the walk follows the discriminator.
  """
  disc_path = f"{prefix}_d" if prefix else "_d"
  disc_value = None
  try:
    disc_value = compat.first(data, ("discriminator_value",), compat.MISSING)
    if disc_value is compat.MISSING:
      disc_value = data.discriminator
    report.add(MemberResult(disc_path, MemberResult.READABLE, "discriminator",
                            value_repr=str(disc_value)))
  except Exception as e:
    report.add(MemberResult(disc_path, MemberResult.FAILED, "discriminator",
                            detail=f"{type(e).__name__}: {e}"))
    return

  # Find the member whose labels include the discriminator value; fall back to
  # the default member when no label matches.
  active = None
  default_member = None
  for member in type_members(dynamic_type):
    labels = compat.get(member, "labels", None) or ()
    try:
      label_values = [int(l) for l in labels]
    except (TypeError, ValueError):
      label_values = []
    if not label_values:
      default_member = default_member or member
    try:
      if disc_value is not None and int(disc_value) in label_values:
        active = member
        break
    except (TypeError, ValueError):
      continue

  member = active or default_member
  if member is None:
    report.add(MemberResult(f"{prefix}(active member)", MemberResult.FAILED, "union",
                            detail=f"no union member matches discriminator {disc_value}"))
    return
  _walk_member(data, member, prefix, report, depth)


def _walk_member(data, member, prefix, report, depth):
  name = compat.get(member, "name", None)
  if not name:
    return
  path = f"{prefix}{name}" if not prefix else f"{prefix}.{name}"
  member_type = resolve_alias(compat.get(member, "type", None))
  kind = kind_name(member_type)

  present, checked = _member_present(data, member, name)
  if not present:
    report.add(MemberResult(path, MemberResult.ABSENT, kind,
                            detail="optional member not present"))
    return

  info = _member_info(data, name)

  if is_collection(member_type):
    _walk_collection(data, member, member_type, path, report, depth, info)
    return

  ok, value, detail = _read_member(data, name)
  if not ok:
    hint = "" if checked else " (optional presence not checkable on this version)"
    report.add(MemberResult(path, MemberResult.FAILED, kind, detail=detail + hint))
    return

  if is_aggregation(member_type):
    if value is None:
      report.add(MemberResult(path, MemberResult.FAILED, kind,
                              detail="aggregate member read as None"))
      return
    report.add(MemberResult(path, MemberResult.READABLE, "container"))
    _walk_aggregate(value, member_type, path, report, depth + 1)
    return

  extra = _enum_sanity(member_type, value)
  report.add(MemberResult(path, MemberResult.READABLE, kind, detail=extra,
                          value_repr=_short_repr(value)))


def _walk_collection(data, member, member_type, path, report, depth, info):
  """Walk a sequence or array: length, then each element up to the cap."""
  name = compat.get(member, "name", None)
  length = _collection_length(data, name, info)

  if length is None:
    ok, value, detail = _read_member(data, name)
    if not ok:
      report.add(MemberResult(path, MemberResult.FAILED, "collection", detail=detail))
      return
    report.add(MemberResult(path, MemberResult.READABLE, "collection",
                            detail="length not reported by this version",
                            value_repr=_short_repr(value)))
    return

  bounds = collection_bound(member_type)
  detail = f"length={length}"
  if bounds is not None and bounds >= 0 and length > bounds:
    # A length beyond the declared bound is strong evidence of an encoding or
    # type-definition disagreement, so this is a failure, not a note.
    report.add(MemberResult(
        path, MemberResult.FAILED, "collection",
        detail=f"length {length} exceeds declared bound {bounds}"))
    return

  report.add(MemberResult(path, MemberResult.READABLE, "container", detail=detail))

  element_type = resolve_alias(compat.get(member_type, "content_type", None))
  limit = min(length, MAX_ELEMENTS_PER_COLLECTION)

  # Aggregate elements must be walked individually. Reading them in bulk is not
  # attempted at all, because loaning a complex element and then a bulk read of
  # the same member conflicts in the core (it reports an already-bound member).
  # Only this branch can actually skip elements, so only this branch truncates -
  # the bulk read below covers every element however long the collection is.
  if element_type is not None and is_aggregation(element_type):
    if limit < length:
      report.truncated = True
    for index in range(limit):
      element_path = f"{path}[{index}]"
      element = _read_element(data, name, index)
      if element is None:
        report.add(MemberResult(element_path, MemberResult.FAILED, "element",
                                detail="element could not be loaned"))
        continue
      report.add(MemberResult(element_path, MemberResult.READABLE, "container"))
      _walk_aggregate(element, element_type, element_path, report, depth + 1)
    return

  # Primitive/string collections: one bulk read covers every element, and
  # avoids per-element loans that the core rejects for primitive kinds.
  bulk_ok, bulk_value, bulk_detail = _read_member(data, name)
  if bulk_ok:
    report.add(MemberResult(f"{path}[*]", MemberResult.READABLE,
                            kind_name(element_type),
                            detail=f"{length} element(s) read",
                            value_repr=_short_repr(bulk_value)))
    return

  report.add(MemberResult(f"{path}[*]", MemberResult.FAILED, kind_name(element_type),
                          detail=bulk_detail or "collection elements unreadable"))


def _read_element(data, name, index):
  """Read collection element `index`, 0-based.

  Python subscripting on DynamicData is 0-based (verified against 7.7.0), even
  though the underlying C API indexes collections from 1. As in _read_member,
  loans are avoided so that reading one element cannot break the next.
  """
  path = f"{name}[{index}]"
  for accessor in (
      lambda: data[path],
      lambda: data.get_value(path),
      lambda: data[name][index],
  ):
    try:
      return accessor()
    except Exception:
      continue
  return None


def _enum_sanity(member_type, value):
  """Flag an enum value outside the declared set - a bit-bound smell."""
  if compat.get(member_type, "kind", None) != _kind("ENUMERATION_TYPE"):
    return ""
  ordinals = enum_ordinals(member_type)
  if not ordinals:
    return ""
  try:
    numeric = int(value)
  except (TypeError, ValueError):
    return ""
  if numeric not in ordinals:
    return (f"value {numeric} is not a declared enumerator "
            f"(declared: {sorted(ordinals)})")
  return ""


def _short_repr(value, limit=60):
  try:
    text = str(value)
  except Exception:
    return "(unrepresentable)"
  text = text.replace("\n", " ")
  return text if len(text) <= limit else text[: limit - 3] + "..."


def key_member_paths(dynamic_type, prefix="", depth=0):
  """Field paths of key members, for the report."""
  dynamic_type = resolve_alias(dynamic_type)
  if dynamic_type is None or depth > MAX_DEPTH or not is_aggregation(dynamic_type):
    return []
  out = []
  for member in type_members(dynamic_type):
    name = compat.get(member, "name", None)
    if not name:
      continue
    path = f"{prefix}{name}" if not prefix else f"{prefix}.{name}"
    if compat.get(member, "is_key", None):
      out.append(path)
    member_type = resolve_alias(compat.get(member, "type", None))
    if is_aggregation(member_type):
      out.extend(key_member_paths(member_type, path, depth + 1))
  return out


def extensibility_map(dynamic_type, prefix="", depth=0):
  """{type name: extensibility} for the type and its nested aggregates."""
  dynamic_type = resolve_alias(dynamic_type)
  if dynamic_type is None or depth > MAX_DEPTH or not is_aggregation(dynamic_type):
    return {}
  out = {}
  ext = extensibility_text(dynamic_type)
  if ext:
    out[type_name(dynamic_type)] = ext
  for member in type_members(dynamic_type):
    member_type = resolve_alias(compat.get(member, "type", None))
    if is_collection(member_type):
      member_type = resolve_alias(compat.get(member_type, "content_type", None))
    if is_aggregation(member_type):
      out.update(extensibility_map(member_type, prefix, depth + 1))
  return out
