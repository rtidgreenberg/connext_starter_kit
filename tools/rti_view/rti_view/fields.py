"""DynamicType field introspection utilities.

Recursively enumerate fields from a discovered DynamicType so the user can select
one field to display or plot.
"""

from dataclasses import dataclass
from typing import List, Set

import rti.connextdds as dds


@dataclass
class FieldDescriptor:
    """A leaf-level field that can be displayed or plotted."""

    path: str          # Dot-separated path, e.g. "position.x"
    name: str          # Leaf name, e.g. "x"
    type_kind: str     # DDS type kind string
    plottable: bool    # True for numeric scalars


def is_scalar_numeric(type_kind) -> bool:
    """Check if a type kind represents a plottable numeric scalar."""
    kind = str(type_kind).upper()
    return any(token in kind for token in (
        "FLOAT",
        "DOUBLE",
        "INT",
        "UINT",
        "LONG",
        "SHORT",
        "BYTE",
        "OCTET",
    ))


def is_numeric_value(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def enumerate_fields(dynamic_type: dds.DynamicType, prefix: str = "") -> List[FieldDescriptor]:
    """Recursively enumerate all leaf fields from a DynamicType.

    Returns a flat list of FieldDescriptors with dot-separated paths.
    Struct members are recursed into; sequences/arrays are noted but not expanded.
    """
    return _enumerate_fields(dynamic_type, prefix=prefix, active_types=set())


def _enumerate_fields(dynamic_type, prefix: str, active_types: Set[str]) -> List[FieldDescriptor]:
    fields: List[FieldDescriptor] = []
    type_key = f"{type(dynamic_type).__name__}:{_safe_type_name(dynamic_type)}:{id(dynamic_type)}"
    if type_key in active_types:
        return fields
    active_types.add(type_key)

    try:
        # Enumerate inherited (parent) fields first
        if getattr(dynamic_type, "has_parent", False):
            parent = getattr(dynamic_type, "parent", None)
            if parent is not None:
                fields.extend(_enumerate_fields(parent, prefix=prefix, active_types=set(active_types)))

        for member in _iter_members(dynamic_type):
            member_name = str(member.name)
            path = f"{prefix}.{member_name}" if prefix else member_name
            member_type = member.type
            kind = getattr(member_type, "kind", "")

            if _is_struct(kind):
                fields.extend(_enumerate_fields(member_type, prefix=path, active_types=set(active_types)))
            else:
                fields.append(FieldDescriptor(
                    path=path,
                    name=member_name,
                    type_kind=str(kind),
                    plottable=is_scalar_numeric(kind) and not _is_collection(kind),
                ))
    finally:
        active_types.discard(type_key)

    return fields


def _iter_members(dynamic_type):
    """Yield DynamicType members using the API exposed by Connext Python types."""
    members = getattr(dynamic_type, "members", None)
    if callable(members):
        yield from members()
        return

    member_count = int(getattr(dynamic_type, "member_count", 0))
    member = getattr(dynamic_type, "member")
    for index in range(member_count):
        yield member(index)


def _safe_type_name(dynamic_type) -> str:
    try:
        return str(getattr(dynamic_type, "name", ""))
    except Exception:
        return ""


def _is_struct(type_kind) -> bool:
    return "STRUCT" in str(type_kind).upper()


def _is_collection(type_kind) -> bool:
    kind = str(type_kind).upper()
    return "SEQUENCE" in kind or "ARRAY" in kind


def get_field_value(sample, field_path: str):
    """Extract a field value from a DynamicData sample using dot-path notation.

    For nested fields like 'position.x', uses bracket access with dot notation
    which DynamicData supports: sample["position.x"]
    """
    get_value = getattr(sample, "get_value", None)
    if callable(get_value):
        return get_value(field_path)
    return sample[field_path]


def enumerate_sample_fields(sample, prefix: str = "") -> List[FieldDescriptor]:
    """Enumerate visible fields from a DynamicData sample using sample.items()."""
    fields: List[FieldDescriptor] = []
    items = getattr(sample, "items", None)
    if not callable(items):
        return fields
    for name, value in items():
        path = f"{prefix}.{name}" if prefix else str(name)
        value_items = getattr(value, "items", None)
        if callable(value_items):
            nested_fields = enumerate_sample_fields(value, path)
            if nested_fields:
                fields.extend(nested_fields)
                continue
        if _is_indexed_collection(value):
            nested_fields = _enumerate_collection_fields(value, path)
            if nested_fields:
                fields.extend(nested_fields)
                continue
        fields.append(FieldDescriptor(
            path=path,
            name=str(name),
            type_kind=type(value).__name__,
            plottable=is_numeric_value(value),
        ))
    return fields


def format_sample_items(sample, prefix: str = "") -> List[str]:
    """Format top-level and nested DynamicData sample items for display."""
    lines: List[str] = []
    items = getattr(sample, "items", None)
    if not callable(items):
        return lines
    for name, value in items():
        path = f"{prefix}.{name}" if prefix else str(name)
        value_items = getattr(value, "items", None)
        if callable(value_items):
            lines.append(f"{path}:")
            lines.extend(format_sample_items(value, path))
        elif _is_indexed_collection(value):
            lines.append(f"{path}:")
            lines.extend(_format_collection_items(value, path))
        else:
            lines.append(f"{path} = {value!r}")
    return lines


def _is_indexed_collection(value: object) -> bool:
    return isinstance(value, (list, tuple))


def _enumerate_collection_fields(values, prefix: str) -> List[FieldDescriptor]:
    fields: List[FieldDescriptor] = []
    for index, element in enumerate(values):
        path = f"{prefix}[{index}]"
        element_items = getattr(element, "items", None)
        if callable(element_items):
            nested_fields = enumerate_sample_fields(element, path)
            if nested_fields:
                fields.extend(nested_fields)
                continue
        if _is_indexed_collection(element):
            nested_fields = _enumerate_collection_fields(element, path)
            if nested_fields:
                fields.extend(nested_fields)
                continue
        fields.append(FieldDescriptor(
            path=path,
            name=f"[{index}]",
            type_kind=type(element).__name__,
            plottable=is_numeric_value(element),
        ))
    return fields


def _format_collection_items(values, prefix: str) -> List[str]:
    lines: List[str] = []
    for index, element in enumerate(values):
        path = f"{prefix}[{index}]"
        element_items = getattr(element, "items", None)
        if callable(element_items):
            lines.append(f"{path}:")
            lines.extend(format_sample_items(element, path))
        elif _is_indexed_collection(element):
            lines.append(f"{path}:")
            lines.extend(_format_collection_items(element, path))
        else:
            lines.append(f"{path} = {element!r}")
    return lines
