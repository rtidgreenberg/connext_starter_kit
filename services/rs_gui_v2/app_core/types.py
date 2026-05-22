"""DDS-free type availability catalog for rs_gui_v2 discovery."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple


class TypeAvailabilityStatus(str, Enum):
    """Local ability to create DynamicData entities for a discovered type."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class TypeResolution:
    """Result of resolving a DDS type name against locally available types."""

    type_name: str
    status: TypeAvailabilityStatus = TypeAvailabilityStatus.UNKNOWN
    source: str = ""
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type_name": self.type_name,
            "status": self.status.value,
            "source": self.source,
            "candidates": list(self.candidates),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TypeResolution":
        return cls(
            type_name=str(data.get("type_name", "")),
            status=TypeAvailabilityStatus(data.get("status", TypeAvailabilityStatus.UNKNOWN.value)),
            source=str(data.get("source", "")),
            candidates=tuple(data.get("candidates", ())),
            message=str(data.get("message", "")),
        )


class TypeCatalog:
    """In-memory catalog of locally available DDS DynamicData type names."""

    def __init__(self, resolutions: Optional[Iterable[TypeResolution]] = None) -> None:
        self._resolutions: Dict[str, TypeResolution] = {}
        for resolution in resolutions or ():
            self.register_resolution(resolution)

    def register_type(self, type_name: str, source: str = "") -> TypeResolution:
        resolution = TypeResolution(
            type_name=type_name,
            status=TypeAvailabilityStatus.AVAILABLE,
            source=source,
        )
        self.register_resolution(resolution)
        return resolution

    def register_resolution(self, resolution: TypeResolution) -> None:
        self._resolutions[resolution.type_name] = resolution

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
                candidates=candidates,
                message=matched.message,
            )
        return TypeResolution(
            type_name=type_name,
            status=TypeAvailabilityStatus.MISSING,
            message="type is not available in the local catalog",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolutions": [
                self._resolutions[key].to_dict()
                for key in sorted(self._resolutions)
            ]
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TypeCatalog":
        return cls(
            TypeResolution.from_dict(item)
            for item in data.get("resolutions", ())
        )


EMPTY_TYPE_CATALOG = TypeCatalog()