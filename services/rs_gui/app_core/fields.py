"""DDS-free field catalog models for rs_gui topic inspection."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple


class FieldCatalogStatus(str, Enum):
    """Availability of a field catalog for a topic type."""

    AVAILABLE = "available"
    TYPE_UNAVAILABLE = "type_unavailable"
    UNSUPPORTED_TYPE = "unsupported_type"
    ERROR = "error"


class FieldScalarKind(str, Enum):
    """Scalar classification used by field pickers and plotting code."""

    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    TEXT = "text"
    ENUM = "enum"
    OCTET = "octet"
    STRUCT = "struct"
    UNION = "union"
    OTHER = "other"


class FieldCollectionKind(str, Enum):
    """Collection shape for a field descriptor."""

    NONE = "none"
    STRING = "string"
    SEQUENCE = "sequence"
    ARRAY = "array"
    MAP = "map"


@dataclass(frozen=True)
class FieldDescriptor:
    """One declared field path in a DDS-free field catalog."""

    path: str
    name: str
    type_name: str = ""
    type_kind: str = ""
    scalar_kind: FieldScalarKind = FieldScalarKind.OTHER
    collection_kind: FieldCollectionKind = FieldCollectionKind.NONE
    parent_path: str = ""
    depth: int = 0
    optional: bool = False
    key: bool = False
    bounds: Tuple[int, ...] = field(default_factory=tuple)
    children: Tuple[str, ...] = field(default_factory=tuple)
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.scalar_kind, FieldScalarKind):
            object.__setattr__(self, "scalar_kind", FieldScalarKind(self.scalar_kind))
        if not isinstance(self.collection_kind, FieldCollectionKind):
            object.__setattr__(self, "collection_kind", FieldCollectionKind(self.collection_kind))
        object.__setattr__(self, "path", str(self.path))
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "type_name", str(self.type_name))
        object.__setattr__(self, "type_kind", str(self.type_kind))
        object.__setattr__(self, "parent_path", str(self.parent_path))
        object.__setattr__(self, "depth", int(self.depth))
        object.__setattr__(self, "bounds", tuple(int(bound) for bound in self.bounds))
        object.__setattr__(self, "children", tuple(str(child) for child in self.children))

    @property
    def leaf(self) -> bool:
        return not self.children

    @property
    def collection(self) -> bool:
        return self.collection_kind != FieldCollectionKind.NONE

    @property
    def numeric(self) -> bool:
        return self.scalar_kind in (FieldScalarKind.INTEGER, FieldScalarKind.FLOAT)

    @property
    def plottable(self) -> bool:
        return self.leaf and self.numeric and not self.collection

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "type_name": self.type_name,
            "type_kind": self.type_kind,
            "scalar_kind": self.scalar_kind.value,
            "collection_kind": self.collection_kind.value,
            "parent_path": self.parent_path,
            "depth": self.depth,
            "optional": self.optional,
            "key": self.key,
            "bounds": list(self.bounds),
            "children": list(self.children),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldDescriptor":
        return cls(
            path=str(data.get("path", "")),
            name=str(data.get("name", "")),
            type_name=str(data.get("type_name", "")),
            type_kind=str(data.get("type_kind", "")),
            scalar_kind=FieldScalarKind(data.get("scalar_kind", FieldScalarKind.OTHER.value)),
            collection_kind=FieldCollectionKind(data.get(
                "collection_kind",
                FieldCollectionKind.NONE.value,
            )),
            parent_path=str(data.get("parent_path", "")),
            depth=int(data.get("depth", 0)),
            optional=bool(data.get("optional", False)),
            key=bool(data.get("key", False)),
            bounds=tuple(data.get("bounds", ())),
            children=tuple(data.get("children", ())),
            message=str(data.get("message", "")),
        )


@dataclass(frozen=True)
class FieldCatalog:
    """Field descriptors for one locally available DDS type."""

    type_name: str
    status: FieldCatalogStatus = FieldCatalogStatus.AVAILABLE
    fields: Tuple[FieldDescriptor, ...] = field(default_factory=tuple)
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, FieldCatalogStatus):
            object.__setattr__(self, "status", FieldCatalogStatus(self.status))
        object.__setattr__(self, "type_name", str(self.type_name))
        object.__setattr__(self, "fields", tuple(self.fields))

    @property
    def available(self) -> bool:
        return self.status == FieldCatalogStatus.AVAILABLE

    def descriptor(self, path: str) -> Optional[FieldDescriptor]:
        path = str(path)
        for descriptor in self.fields:
            if descriptor.path == path:
                return descriptor
        return None

    def leaf_fields(self) -> Tuple[FieldDescriptor, ...]:
        return tuple(descriptor for descriptor in self.fields if descriptor.leaf)

    def plottable_fields(self) -> Tuple[FieldDescriptor, ...]:
        return tuple(descriptor for descriptor in self.fields if descriptor.plottable)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type_name": self.type_name,
            "status": self.status.value,
            "fields": [descriptor.to_dict() for descriptor in self.fields],
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldCatalog":
        return cls(
            type_name=str(data.get("type_name", "")),
            status=FieldCatalogStatus(data.get("status", FieldCatalogStatus.AVAILABLE.value)),
            fields=tuple(FieldDescriptor.from_dict(item) for item in data.get("fields", ())),
            message=str(data.get("message", "")),
        )


def field_catalog_from_descriptors(
        type_name: str,
        descriptors: Iterable[FieldDescriptor],
        status: FieldCatalogStatus = FieldCatalogStatus.AVAILABLE,
        message: str = "",
) -> FieldCatalog:
    """Build a catalog and populate parent descriptors with child path lists."""
    by_path: Dict[str, FieldDescriptor] = {}
    child_paths: Dict[str, Tuple[str, ...]] = {}
    ordered = tuple(descriptors)
    for descriptor in ordered:
        by_path[descriptor.path] = descriptor
        if descriptor.parent_path:
            child_paths[descriptor.parent_path] = child_paths.get(descriptor.parent_path, ()) + (descriptor.path,)

    fields = []
    for descriptor in ordered:
        children = child_paths.get(descriptor.path, ())
        if children != descriptor.children:
            descriptor = FieldDescriptor(
                path=descriptor.path,
                name=descriptor.name,
                type_name=descriptor.type_name,
                type_kind=descriptor.type_kind,
                scalar_kind=descriptor.scalar_kind,
                collection_kind=descriptor.collection_kind,
                parent_path=descriptor.parent_path,
                depth=descriptor.depth,
                optional=descriptor.optional,
                key=descriptor.key,
                bounds=descriptor.bounds,
                children=children,
                message=descriptor.message,
            )
        fields.append(descriptor)
    return FieldCatalog(type_name=type_name, status=status, fields=tuple(fields), message=message)