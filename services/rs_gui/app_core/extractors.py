"""DDS-free field-path parsing and sample value extraction for rs_gui."""

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .subscriptions import SampleEnvelope


_PATH_TOKEN_RE = re.compile(r"([^\.\[\]]+)|(\[(\d+)\])")
_MISSING = object()


class FieldExtractionStatus(str, Enum):
    """Result category for extracting one selected field path."""

    FOUND = "found"
    MISSING = "missing"
    INVALID_SAMPLE = "invalid_sample"
    INVALID_PATH = "invalid_path"
    ERROR = "error"


class FieldValueKind(str, Enum):
    """Simple UI-facing classification for extracted values."""

    NULL = "null"
    BOOLEAN = "boolean"
    NUMERIC = "numeric"
    TEXT = "text"
    SEQUENCE = "sequence"
    MAPPING = "mapping"
    OBJECT = "object"
    MISSING = "missing"


@dataclass(frozen=True)
class FieldPathStep:
    """One member name and optional zero-based sequence index in a field path."""

    name: str = ""
    index: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        if self.index is not None:
            object.__setattr__(self, "index", int(self.index))

    def to_text(self) -> str:
        if self.name and self.index is not None:
            return f"{self.name}[{self.index}]"
        if self.index is not None:
            return f"[{self.index}]"
        return self.name

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "index": self.index}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldPathStep":
        return cls(name=str(data.get("name", "")), index=data.get("index"))


@dataclass(frozen=True)
class FieldPath:
    """Parsed field path such as `pose.position.x` or `ranges[0]`."""

    text: str
    steps: Tuple[FieldPathStep, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", str(self.text))
        object.__setattr__(self, "steps", tuple(self.steps))

    @classmethod
    def parse(cls, text: str) -> "FieldPath":
        text = str(text).strip()
        if not text:
            raise ValueError("field path cannot be empty")
        return cls(text=text, steps=_parse_steps(text))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldPath":
        return cls(
            text=str(data.get("text", "")),
            steps=tuple(FieldPathStep.from_dict(step) for step in data.get("steps", ())),
        )


@dataclass(frozen=True)
class FieldExtraction:
    """Result of extracting a field path from one sample envelope."""

    path: FieldPath
    status: FieldExtractionStatus
    value: Any = None
    kind: FieldValueKind = FieldValueKind.MISSING
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, FieldExtractionStatus):
            object.__setattr__(self, "status", FieldExtractionStatus(self.status))
        if not isinstance(self.kind, FieldValueKind):
            object.__setattr__(self, "kind", FieldValueKind(self.kind))
        if not isinstance(self.path, FieldPath):
            object.__setattr__(self, "path", FieldPath.parse(str(self.path)))

    @property
    def found(self) -> bool:
        return self.status == FieldExtractionStatus.FOUND

    @property
    def numeric(self) -> bool:
        return self.kind == FieldValueKind.NUMERIC

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path.to_dict(),
            "status": self.status.value,
            "value": self.value,
            "kind": self.kind.value,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FieldExtraction":
        return cls(
            path=FieldPath.from_dict(data["path"]),
            status=FieldExtractionStatus(data.get("status", FieldExtractionStatus.MISSING.value)),
            value=data.get("value"),
            kind=FieldValueKind(data.get("kind", FieldValueKind.MISSING.value)),
            message=str(data.get("message", "")),
        )


def extract_fields(
        sample: SampleEnvelope,
        field_paths: Iterable[str],
) -> Tuple[FieldExtraction, ...]:
    """Extract selected field paths from a sample envelope."""
    paths = tuple(field_paths)
    if not sample.valid:
        return tuple(_invalid_sample_result(path) for path in paths)
    return tuple(extract_field(sample.data, path) for path in paths)


def extract_field(data: Any, field_path: str) -> FieldExtraction:
    """Extract one field path from a mapping/object/DynamicData-like value."""
    try:
        path = FieldPath.parse(field_path)
    except ValueError as exc:
        return FieldExtraction(
            path=FieldPath(text=str(field_path), steps=()),
            status=FieldExtractionStatus.INVALID_PATH,
            message=str(exc),
        )

    current = data
    for step in path.steps:
        current = _read_step(current, step)
        if current is _MISSING:
            return FieldExtraction(
                path=path,
                status=FieldExtractionStatus.MISSING,
                kind=FieldValueKind.MISSING,
                message=f"field path not found: {path.text}",
            )

    return FieldExtraction(
        path=path,
        status=FieldExtractionStatus.FOUND,
        value=current,
        kind=classify_value(current),
    )


def classify_value(value: Any) -> FieldValueKind:
    """Classify a value for sample inspection and plotting eligibility."""
    if value is None:
        return FieldValueKind.NULL
    if isinstance(value, bool):
        return FieldValueKind.BOOLEAN
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return FieldValueKind.OBJECT
        return FieldValueKind.NUMERIC
    if isinstance(value, str):
        return FieldValueKind.TEXT
    if isinstance(value, Mapping):
        return FieldValueKind.MAPPING
    if isinstance(value, (list, tuple)):
        return FieldValueKind.SEQUENCE
    return FieldValueKind.OBJECT


def _parse_steps(text: str) -> Tuple[FieldPathStep, ...]:
    steps = []
    for part in text.split("."):
        if not part:
            raise ValueError(f"invalid field path: {text}")
        position = 0
        current_name = ""
        saw_index = False
        for match in _PATH_TOKEN_RE.finditer(part):
            if match.start() != position:
                raise ValueError(f"invalid field path: {text}")
            name_token = match.group(1)
            index_token = match.group(3)
            if name_token is not None:
                if current_name or saw_index:
                    raise ValueError(f"invalid field path: {text}")
                current_name = name_token
            elif index_token is not None:
                if not current_name:
                    raise ValueError(f"invalid field path: {text}")
                steps.append(FieldPathStep(name=current_name, index=int(index_token)))
                current_name = ""
                saw_index = True
            position = match.end()
        if position != len(part):
            raise ValueError(f"invalid field path: {text}")
        if current_name:
            steps.append(FieldPathStep(name=current_name))
    if not steps:
        raise ValueError(f"invalid field path: {text}")
    return tuple(steps)


def _read_step(value: Any, step: FieldPathStep) -> Any:
    current = _read_member(value, step.name)
    if current is _MISSING:
        return _MISSING
    if step.index is not None:
        return _read_index(current, step.index)
    return current


def _read_member(value: Any, name: str) -> Any:
    if value is None:
        return _MISSING
    if isinstance(value, Mapping):
        return value.get(name, _MISSING)
    try:
        return getattr(value, name)
    except Exception:
        pass
    try:
        return value[name]
    except Exception:
        return _MISSING


def _read_index(value: Any, index: int) -> Any:
    if value is None:
        return _MISSING
    try:
        return value[index]
    except Exception:
        return _MISSING


def _invalid_sample_result(field_path: str) -> FieldExtraction:
    try:
        path = FieldPath.parse(field_path)
    except ValueError:
        path = FieldPath(text=str(field_path), steps=())
    return FieldExtraction(
        path=path,
        status=FieldExtractionStatus.INVALID_SAMPLE,
        kind=FieldValueKind.MISSING,
        message="sample is invalid",
    )