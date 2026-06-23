"""RTI Connext DynamicType field catalog adapter for rs_gui."""

from dataclasses import dataclass
from typing import Any, List, Optional, Set, Tuple

from .fields import (
    FieldCatalog,
    FieldCatalogStatus,
    FieldCollectionKind,
    FieldDescriptor,
    FieldScalarKind,
    field_catalog_from_descriptors,
)
from .rti_types import RtiTypeRegistry


@dataclass(frozen=True)
class RtiFieldCatalogConfig:
    """Traversal options for building field catalogs from DynamicTypes."""

    max_depth: int = 8
    include_collection_content: bool = False


class RtiFieldCatalogClient:
    """Build DDS-free field catalogs from Connext DynamicTypes."""

    def __init__(
            self,
            type_registry: Optional[RtiTypeRegistry] = None,
            config: Optional[RtiFieldCatalogConfig] = None,
    ) -> None:
        self.type_registry = type_registry or RtiTypeRegistry()
        self.config = config or RtiFieldCatalogConfig()

    def catalog_for(self, type_name: str) -> FieldCatalog:
        lookup = self.type_registry.lookup(type_name)
        if not lookup.available:
            return FieldCatalog(
                type_name=str(type_name),
                status=FieldCatalogStatus.TYPE_UNAVAILABLE,
                message=lookup.resolution.message,
            )
        try:
            descriptors = dynamic_type_field_descriptors(
                lookup.dynamic_type,
                max_depth=self.config.max_depth,
                include_collection_content=self.config.include_collection_content,
            )
        except Exception as exc:
            return FieldCatalog(
                type_name=lookup.resolution.resolved_type_name,
                status=FieldCatalogStatus.ERROR,
                message=f"failed to build field catalog: {exc}",
            )
        return field_catalog_from_descriptors(
            lookup.resolution.resolved_type_name,
            descriptors,
        )


def dynamic_type_field_descriptors(
        dynamic_type: Any,
        max_depth: int = 8,
        include_collection_content: bool = False,
) -> Tuple[FieldDescriptor, ...]:
    """Walk a Connext DynamicType-like object into DDS-free field descriptors."""
    descriptors: List[FieldDescriptor] = []
    _walk_members(
        dynamic_type,
        parent_path="",
        parent_depth=-1,
        descriptors=descriptors,
        max_depth=max_depth,
        include_collection_content=include_collection_content,
        active_types=set(),
    )
    return tuple(descriptors)


def _walk_members(
        dynamic_type: Any,
        parent_path: str,
        parent_depth: int,
        descriptors: List[FieldDescriptor],
        max_depth: int,
        include_collection_content: bool,
        active_types: Set[str],
) -> None:
    member_count = _safe_int_attr(dynamic_type, "member_count")
    if member_count is None:
        return
    if parent_depth >= max_depth:
        return

    type_key = _type_key(dynamic_type)
    if type_key in active_types:
        return
    active_types.add(type_key)
    try:
        for index in range(member_count):
            member = dynamic_type.member(index)
            member_type = member.type
            name = str(member.name)
            path = f"{parent_path}.{name}" if parent_path else name
            depth = parent_depth + 1
            descriptor = _descriptor_for_member(
                member=member,
                member_type=member_type,
                path=path,
                parent_path=parent_path,
                depth=depth,
            )
            descriptors.append(descriptor)

            if _should_recurse(member_type, depth, max_depth, include_collection_content):
                next_type = _content_type(member_type) if descriptor.collection else member_type
                _walk_members(
                    next_type,
                    parent_path=path,
                    parent_depth=depth,
                    descriptors=descriptors,
                    max_depth=max_depth,
                    include_collection_content=include_collection_content,
                    active_types=set(active_types),
                )
    finally:
        active_types.discard(type_key)


def _descriptor_for_member(member: Any, member_type: Any, path: str, parent_path: str, depth: int) -> FieldDescriptor:
    return FieldDescriptor(
        path=path,
        name=str(member.name),
        type_name=_type_name(member_type),
        type_kind=_type_kind(member_type),
        scalar_kind=_scalar_kind(member_type),
        collection_kind=_collection_kind(member_type),
        parent_path=parent_path,
        depth=depth,
        optional=bool(_safe_attr(member, "optional", False)),
        key=bool(_safe_attr(member, "is_key", False)),
        bounds=_bounds(member_type),
    )


def _should_recurse(
        dynamic_type: Any,
        depth: int,
        max_depth: int,
        include_collection_content: bool,
) -> bool:
    if depth >= max_depth:
        return False
    if _collection_kind(dynamic_type) != FieldCollectionKind.NONE:
        if _collection_kind(dynamic_type) == FieldCollectionKind.STRING:
            return False
        if not include_collection_content:
            return False
        dynamic_type = _content_type(dynamic_type)
        if dynamic_type is None:
            return False
    scalar_kind = _scalar_kind(dynamic_type)
    return scalar_kind in (FieldScalarKind.STRUCT, FieldScalarKind.UNION)


def _scalar_kind(dynamic_type: Any) -> FieldScalarKind:
    kind = _type_kind(dynamic_type).upper()
    class_name = type(dynamic_type).__name__.upper()
    combined = f"{kind} {class_name}"
    if "BOOLEAN" in combined or "BOOL" in combined:
        return FieldScalarKind.BOOLEAN
    if "OCTET" in combined or "BYTE" in combined:
        return FieldScalarKind.OCTET
    if "STRING" in combined or "WSTRING" in combined or "CHAR" in combined:
        return FieldScalarKind.TEXT
    if "ENUM" in combined:
        return FieldScalarKind.ENUM
    if "FLOAT" in combined or "DOUBLE" in combined:
        return FieldScalarKind.FLOAT
    if "INT" in combined or "UINT" in combined or "LONG" in combined or "SHORT" in combined:
        return FieldScalarKind.INTEGER
    if "STRUCT" in combined:
        return FieldScalarKind.STRUCT
    if "UNION" in combined:
        return FieldScalarKind.UNION
    return FieldScalarKind.OTHER


def _collection_kind(dynamic_type: Any) -> FieldCollectionKind:
    kind = _type_kind(dynamic_type).upper()
    class_name = type(dynamic_type).__name__.upper()
    combined = f"{kind} {class_name}"
    if "STRING" in combined or "WSTRING" in combined:
        return FieldCollectionKind.STRING
    if "SEQUENCE" in combined:
        return FieldCollectionKind.SEQUENCE
    if "ARRAY" in combined:
        return FieldCollectionKind.ARRAY
    if "MAP" in combined:
        return FieldCollectionKind.MAP
    return FieldCollectionKind.NONE


def _content_type(dynamic_type: Any) -> Any:
    return _safe_attr(dynamic_type, "content_type")


def _bounds(dynamic_type: Any) -> Tuple[int, ...]:
    value = _safe_attr(dynamic_type, "bounds")
    if value is None:
        return ()
    if isinstance(value, int):
        return (value,)
    try:
        return tuple(int(item) for item in value)
    except TypeError:
        return ()


def _type_name(dynamic_type: Any) -> str:
    name = _safe_attr(dynamic_type, "name")
    if name:
        return str(name)
    return _type_kind(dynamic_type).lower()


def _type_kind(dynamic_type: Any) -> str:
    kind = _safe_attr(dynamic_type, "kind")
    if kind is None:
        return type(dynamic_type).__name__
    text = str(kind)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    if text.endswith("_TYPE"):
        text = text[:-5]
    return text.lower()


def _type_key(dynamic_type: Any) -> str:
    return _type_name(dynamic_type) or f"{type(dynamic_type).__name__}:{id(dynamic_type)}"


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    if callable(value):
        try:
            return value()
        except TypeError:
            return default
        except Exception:
            return default
    return value


def _safe_int_attr(obj: Any, name: str) -> Optional[int]:
    value = _safe_attr(obj, name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None