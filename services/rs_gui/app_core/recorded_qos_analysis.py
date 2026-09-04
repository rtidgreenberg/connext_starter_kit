"""DDS-free compatibility analysis for Recording Service discovery QoS."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import fnmatch
import re
from typing import Dict, Iterable, Optional, Tuple

from app_core.recorded_discovery import RecordedEndpointLifetime


class QosCompatibilityStatus(str, Enum):
    """Whether a policy is compatible, incompatible, or cannot be evaluated."""

    COMPATIBLE = "compatible"
    MISMATCH = "mismatch"
    UNEVALUATED = "unevaluated"


@dataclass(frozen=True)
class QosPolicyResult:
    """The recorded values and result for one QoS compatibility rule."""

    name: str
    status: QosCompatibilityStatus
    writer_value: object
    reader_value: object
    reason: str


@dataclass(frozen=True)
class RecordedQosComparison:
    """Immutable compatibility result for one recorded writer and reader."""

    writer_key: str
    reader_key: str
    status: QosCompatibilityStatus
    policies: Tuple[QosPolicyResult, ...]

    @property
    def is_compatible(self) -> bool:
        return self.status is QosCompatibilityStatus.COMPATIBLE


def compare_recorded_endpoints(
        writer: RecordedEndpointLifetime,
        reader: RecordedEndpointLifetime,
) -> RecordedQosComparison:
    """Compare flattened Recording Service 7.7 writer and reader QoS values."""

    writer_qos = dict(writer.qos)
    reader_qos = dict(reader.qos)
    policies = []
    if writer.type_name != reader.type_name:
        policies.append(_result("type", False, writer.type_name, reader.type_name, "writer type == reader type"))
    policies.extend((
        _ordered_policy("reliability", writer_qos, reader_qos, "reliability_kind", (0, 1), "writer >= reader"),
        _ordered_policy("durability", writer_qos, reader_qos, "durability_kind", (0, 1, 2, 3), "writer >= reader"),
        _ordered_policy("deadline", writer_qos, reader_qos, "deadline_period", None, "writer <= reader"),
        _ordered_policy("latency_budget", writer_qos, reader_qos, "latency_budget_duration", None, "writer <= reader"),
        _liveliness_policy(writer_qos, reader_qos),
        _exact_policy("ownership", writer_qos, reader_qos, "ownership_kind", (0, 1)),
        _exact_policy("destination_order", writer_qos, reader_qos, "destination_order_kind", (0, 1)),
        _presentation_policy(writer_qos, reader_qos),
        _partition_policy(writer_qos, reader_qos),
    ))
    return RecordedQosComparison(
        writer_key=writer.key,
        reader_key=reader.key,
        status=_overall_status(policies),
        policies=tuple(policies),
    )


def _ordered_policy(
        name: str,
        writer_qos: Dict[str, object],
        reader_qos: Dict[str, object],
        field: str,
        allowed_values: Optional[Iterable[int]],
        rule: str,
) -> QosPolicyResult:
    writer_value, reader_value, issue = _integer_values(writer_qos, reader_qos, (field,), allowed_values)
    if issue:
        return _unevaluated(name, writer_value, reader_value, issue)
    compatible = writer_value >= reader_value if rule == "writer >= reader" else writer_value <= reader_value
    return _result(name, compatible, writer_value, reader_value, rule)


def _exact_policy(
        name: str,
        writer_qos: Dict[str, object],
        reader_qos: Dict[str, object],
        field: str,
        allowed_values: Iterable[int],
) -> QosPolicyResult:
    writer_value, reader_value, issue = _integer_values(writer_qos, reader_qos, (field,), allowed_values)
    if issue:
        return _unevaluated(name, writer_value, reader_value, issue)
    return _result(name, writer_value == reader_value, writer_value, reader_value, "writer == reader")


def _liveliness_policy(writer_qos: Dict[str, object], reader_qos: Dict[str, object]) -> QosPolicyResult:
    fields = ("liveliness_kind", "liveliness_lease_duration")
    writer_values, reader_values, issue = _integer_values(
        writer_qos, reader_qos, fields, (0, 1, 2), allowed_by_field={"liveliness_lease_duration": None}
    )
    if issue:
        return _unevaluated("liveliness", writer_values, reader_values, issue)
    compatible = writer_values[0] >= reader_values[0] and writer_values[1] <= reader_values[1]
    return _result(
        "liveliness",
        compatible,
        writer_values,
        reader_values,
        "writer kind >= reader kind and writer lease <= reader lease",
    )


def _presentation_policy(writer_qos: Dict[str, object], reader_qos: Dict[str, object]) -> QosPolicyResult:
    fields = (
        "presentation_access_scope",
        "presentation_coherent_access",
        "presentation_ordered_access",
    )
    writer_values, reader_values, issue = _integer_values(
        writer_qos,
        reader_qos,
        fields,
        (0, 1, 2),
        allowed_by_field={
            "presentation_coherent_access": (0, 1),
            "presentation_ordered_access": (0, 1),
        },
    )
    if issue:
        return _unevaluated("presentation", writer_values, reader_values, issue)
    compatible = (
        writer_values[0] >= reader_values[0]
        and writer_values[1] >= reader_values[1]
        and writer_values[2] >= reader_values[2]
    )
    return _result(
        "presentation",
        compatible,
        writer_values,
        reader_values,
        "writer scope >= reader scope and writer flags satisfy reader flags",
    )


def _partition_policy(writer_qos: Dict[str, object], reader_qos: Dict[str, object]) -> QosPolicyResult:
    writer_value, reader_value, issue = _string_values(writer_qos, reader_qos, "partition")
    if issue:
        return _unevaluated("partition", writer_value, reader_value, issue)
    writer_names = _partition_names(writer_value)
    reader_names = _partition_names(reader_value)
    compatible = any(_partition_matches(offered, requested) for offered in writer_names for requested in reader_names)
    return _result("partition", compatible, writer_value, reader_value, "at least one partition name overlaps")


def _integer_values(
        writer_qos: Dict[str, object],
        reader_qos: Dict[str, object],
        fields: Tuple[str, ...],
        allowed_values: Optional[Iterable[int]],
        allowed_by_field: Optional[Dict[str, Optional[Iterable[int]]]] = None,
):
    writer_values = []
    reader_values = []
    for field in fields:
        field_allowed = allowed_by_field.get(field) if allowed_by_field else allowed_values
        writer_value, reader_value, issue = _integer_value_pair(writer_qos, reader_qos, field, field_allowed)
        if issue:
            return _shape_values(writer_values, writer_value, len(fields)), _shape_values(reader_values, reader_value, len(fields)), issue
        writer_values.append(writer_value)
        reader_values.append(reader_value)
    if len(fields) == 1:
        return writer_values[0], reader_values[0], ""
    return tuple(writer_values), tuple(reader_values), ""


def _shape_values(values, current_value, field_count):
    values = values + [current_value]
    return values[0] if field_count == 1 else tuple(values)


def _integer_value_pair(writer_qos, reader_qos, field, allowed_values):
    writer_value = writer_qos.get(field)
    reader_value = reader_qos.get(field)
    issues = _missing_values(writer_qos, reader_qos, field)
    for side, value, qos in (("writer", writer_value, writer_qos), ("reader", reader_value, reader_qos)):
        if field not in qos:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append("invalid {} value for {}".format(side, field))
        elif allowed_values is not None and value not in allowed_values:
            issues.append("unsupported {} value for {}".format(side, field))
    return writer_value, reader_value, "; ".join(issues)


def _string_values(writer_qos, reader_qos, field):
    writer_value = writer_qos.get(field)
    reader_value = reader_qos.get(field)
    issues = _missing_values(writer_qos, reader_qos, field)
    for side, value, qos in (("writer", writer_value, writer_qos), ("reader", reader_value, reader_qos)):
        if field not in qos:
            continue
        if not isinstance(value, str):
            issues.append("invalid {} value for {}".format(side, field))
    return writer_value, reader_value, "; ".join(issues)


def _missing_values(writer_qos, reader_qos, field):
    missing = []
    if field not in writer_qos:
        missing.append("missing writer value for {}".format(field))
    if field not in reader_qos:
        missing.append("missing reader value for {}".format(field))
    return missing


def _partition_names(value: str) -> Tuple[str, ...]:
    names = tuple(name.strip() for name in re.split(r"[;,]", value) if name.strip())
    return names or ("",)


def _partition_matches(writer_name: str, reader_name: str) -> bool:
    return fnmatch.fnmatchcase(writer_name, reader_name) or fnmatch.fnmatchcase(reader_name, writer_name)


def _result(name, compatible, writer_value, reader_value, rule):
    status = QosCompatibilityStatus.COMPATIBLE if compatible else QosCompatibilityStatus.MISMATCH
    return QosPolicyResult(name, status, writer_value, reader_value, rule)


def _unevaluated(name, writer_value, reader_value, reason):
    return QosPolicyResult(name, QosCompatibilityStatus.UNEVALUATED, writer_value, reader_value, reason)


def _overall_status(policies: Tuple[QosPolicyResult, ...]) -> QosCompatibilityStatus:
    statuses = {policy.status for policy in policies}
    if QosCompatibilityStatus.MISMATCH in statuses:
        return QosCompatibilityStatus.MISMATCH
    if QosCompatibilityStatus.UNEVALUATED in statuses:
        return QosCompatibilityStatus.UNEVALUATED
    return QosCompatibilityStatus.COMPATIBLE