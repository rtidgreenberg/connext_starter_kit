"""DDS-free type availability catalog for rs_gui discovery."""

from dataclasses import dataclass, field
from enum import Enum
import os
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple
import xml.etree.ElementTree as ET


TYPE_DECLARATION_TAGS = frozenset((
    "struct",
    "enum",
    "union",
    "typedef",
    "bitset",
    "bitmask",
    "valuetype",
))


class TypeAvailabilityStatus(str, Enum):
    """Local ability to create DynamicData entities for a discovered type."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class TypeSource:
    """DDS-free source record for a type declared in local XML."""

    type_name: str
    source: str
    kind: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "type_name", str(self.type_name))
        object.__setattr__(self, "source", str(self.source))
        object.__setattr__(self, "kind", str(self.kind))

    @property
    def short_name(self) -> str:
        return self.type_name.split("::")[-1]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type_name": self.type_name,
            "source": self.source,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TypeSource":
        return cls(
            type_name=str(data.get("type_name", "")),
            source=str(data.get("source", "")),
            kind=str(data.get("kind", "")),
        )


@dataclass(frozen=True)
class TypeResolution:
    """Result of resolving a DDS type name against locally available types."""

    type_name: str
    status: TypeAvailabilityStatus = TypeAvailabilityStatus.UNKNOWN
    source: str = ""
    kind: str = ""
    candidates: Tuple[str, ...] = field(default_factory=tuple)
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, TypeAvailabilityStatus):
            object.__setattr__(self, "status", TypeAvailabilityStatus(self.status))
        object.__setattr__(self, "type_name", str(self.type_name))
        object.__setattr__(self, "candidates", tuple(str(item) for item in self.candidates))

    @property
    def available(self) -> bool:
        return self.status == TypeAvailabilityStatus.AVAILABLE

    @property
    def resolved_type_name(self) -> str:
        if self.available and len(self.candidates) == 1:
            return self.candidates[0]
        return self.type_name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type_name": self.type_name,
            "status": self.status.value,
            "source": self.source,
            "kind": self.kind,
            "candidates": list(self.candidates),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TypeResolution":
        return cls(
            type_name=str(data.get("type_name", "")),
            status=TypeAvailabilityStatus(data.get("status", TypeAvailabilityStatus.UNKNOWN.value)),
            source=str(data.get("source", "")),
            kind=str(data.get("kind", "")),
            candidates=tuple(data.get("candidates", ())),
            message=str(data.get("message", "")),
        )


class TypeCatalog:
    """In-memory catalog of locally available DDS DynamicData type names."""

    def __init__(self, resolutions: Optional[Iterable[TypeResolution]] = None) -> None:
        self._resolutions: Dict[str, TypeResolution] = {}
        self._sources: Dict[str, TypeSource] = {}
        for resolution in resolutions or ():
            self.register_resolution(resolution)

    def register_type(self, type_name: str, source: str = "", kind: str = "") -> TypeResolution:
        self.register_source(TypeSource(type_name=type_name, source=source, kind=kind))
        return self._resolutions[type_name]

    def register_source(self, source: TypeSource) -> TypeResolution:
        self._sources[source.type_name] = source
        resolution = TypeResolution(
            type_name=source.type_name,
            status=TypeAvailabilityStatus.AVAILABLE,
            source=source.source,
            kind=source.kind,
            candidates=(source.type_name,),
        )
        self.register_resolution(resolution)
        return resolution

    def register_resolution(self, resolution: TypeResolution) -> None:
        self._resolutions[resolution.type_name] = resolution
        if resolution.source:
            self._sources[resolution.type_name] = TypeSource(
                type_name=resolution.type_name,
                source=resolution.source,
                kind=resolution.kind,
            )

    def resolve(self, type_name: str) -> TypeResolution:
        type_name = str(type_name)
        if not type_name:
            return TypeResolution(
                type_name="",
                status=TypeAvailabilityStatus.MISSING,
                message="discovered endpoint did not include a type name",
            )
        resolution = self._resolutions.get(type_name)
        if resolution is not None:
            return resolution
        candidates = tuple(
            candidate for candidate in self._resolutions
            if candidate.endswith(f"::{type_name}") or candidate.split("::")[-1] == type_name
        )
        if len(candidates) > 1:
            return TypeResolution(
                type_name=type_name,
                status=TypeAvailabilityStatus.AMBIGUOUS,
                candidates=candidates,
                message="multiple local types match discovered type name",
            )
        if len(candidates) == 1:
            matched = self._resolutions[candidates[0]]
            return TypeResolution(
                type_name=type_name,
                status=matched.status,
                source=matched.source,
                kind=matched.kind,
                candidates=candidates,
                message=matched.message,
            )
        return TypeResolution(
            type_name=type_name,
            status=TypeAvailabilityStatus.MISSING,
            message="type is not available in the local catalog",
        )

    def source_for(self, type_name: str) -> Optional[TypeSource]:
        resolution = self.resolve(type_name)
        if not resolution.available:
            return None
        return self._sources.get(resolution.resolved_type_name)

    def registered_types(self) -> Tuple[TypeSource, ...]:
        return tuple(
            self._sources[key]
            for key in sorted(self._sources)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sources": [
                self._sources[key].to_dict()
                for key in sorted(self._sources)
            ],
            "resolutions": [
                self._resolutions[key].to_dict()
                for key in sorted(self._resolutions)
            ]
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TypeCatalog":
        catalog = cls()
        for item in data.get("sources", ()):
            catalog.register_source(TypeSource.from_dict(item))
        for item in data.get("resolutions", ()):
            catalog.register_resolution(TypeResolution.from_dict(item))
        return catalog


def catalog_from_xml_files(xml_paths: Iterable[str]) -> TypeCatalog:
    """Build a DDS-free type catalog from generated XML type files."""
    catalog = TypeCatalog()
    for xml_path in xml_paths:
        for source in type_sources_from_xml_file(xml_path):
            catalog.register_source(source)
    return catalog


def type_sources_from_xml_file(xml_path: str) -> Tuple[TypeSource, ...]:
    tree = ET.parse(xml_path)
    return type_sources_from_xml_root(tree.getroot(), source=os.path.abspath(xml_path))


def type_sources_from_xml_text(xml_text: str, source: str = "") -> Tuple[TypeSource, ...]:
    return type_sources_from_xml_root(ET.fromstring(xml_text), source=source)


def type_sources_from_xml_root(root: ET.Element, source: str = "") -> Tuple[TypeSource, ...]:
    sources = []

    def walk(element: ET.Element, modules: Tuple[str, ...]) -> None:
        tag = _local_name(element.tag)
        name = element.attrib.get("name", "").strip()
        if tag == "module" and name:
            modules = modules + (name,)
        elif tag in TYPE_DECLARATION_TAGS and name:
            type_name = "::".join(modules + (name,)) if modules else name
            sources.append(TypeSource(type_name=type_name, source=source, kind=tag))
        for child in list(element):
            walk(child, modules)

    walk(root, ())
    return tuple(sources)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


EMPTY_TYPE_CATALOG = TypeCatalog()