"""Aggregate QoS compatibility results from a recorded discovery database."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Tuple

from .recorded_discovery import RecordedDiscovery, RecordedEndpointLifetime, load_recorded_discovery
from .recorded_qos_analysis import QosCompatibilityStatus, QosPolicyResult, compare_recorded_endpoints


@dataclass(frozen=True)
class HistoricalQosIssue:
    """One observed incompatibility between overlapping recorded endpoints."""

    domain_id: int | None
    topic_name: str
    type_name: str
    writer_key: str
    reader_key: str
    writer_participant_name: str
    reader_participant_name: str
    writer_process: str
    reader_process: str
    overlap_started_at_ns: int
    overlap_ended_at_ns: int | None
    mismatches: Tuple[QosPolicyResult, ...]
    unevaluated: Tuple[QosPolicyResult, ...]


@dataclass(frozen=True)
class HistoricalQosAnalysis:
    """Read-only analysis result suitable for the Replay view model."""

    endpoint_count: int
    comparison_count: int
    issues: Tuple[HistoricalQosIssue, ...]


def analyze_recorded_discovery(recording_directory: str) -> HistoricalQosAnalysis:
    """Load and compare writer-reader pairs that were live at the same time."""

    return analyze_discovery(load_recorded_discovery(recording_directory))


def analyze_discovery(discovery: RecordedDiscovery) -> HistoricalQosAnalysis:
    """Compare compatible-kind endpoint pairs only while their lifetimes overlap."""

    writers = tuple(item for item in discovery.endpoints if item.kind == "Writer")
    readers = tuple(item for item in discovery.endpoints if item.kind == "Reader")
    participants = {item.key: item for item in discovery.participants}
    issues = []
    comparison_count = 0
    for writer in writers:
        for reader in readers:
            if not _same_stream(writer, reader) or not _lifetimes_overlap(writer, reader):
                continue
            comparison_count += 1
            comparison = compare_recorded_endpoints(writer, reader)
            mismatches = tuple(item for item in comparison.policies if item.status is QosCompatibilityStatus.MISMATCH)
            unevaluated = tuple(item for item in comparison.policies if item.status is QosCompatibilityStatus.UNEVALUATED)
            if mismatches or unevaluated:
                writer_participant = participants.get(writer.participant_key)
                reader_participant = participants.get(reader.participant_key)
                issues.append(HistoricalQosIssue(
                    domain_id=writer.domain_id,
                    topic_name=writer.topic_name,
                    type_name=writer.type_name,
                    writer_key=writer.key,
                    reader_key=reader.key,
                    writer_participant_name=writer_participant.name if writer_participant else "unknown participant",
                    reader_participant_name=reader_participant.name if reader_participant else "unknown participant",
                    writer_process=_process_label(writer_participant.properties if writer_participant else ""),
                    reader_process=_process_label(reader_participant.properties if reader_participant else ""),
                    overlap_started_at_ns=max(writer.started_at_ns, reader.started_at_ns),
                    overlap_ended_at_ns=_overlap_end(writer.ended_at_ns, reader.ended_at_ns),
                    mismatches=mismatches,
                    unevaluated=unevaluated,
                ))
    return HistoricalQosAnalysis(len(discovery.endpoints), comparison_count, tuple(issues))


def _same_stream(writer: RecordedEndpointLifetime, reader: RecordedEndpointLifetime) -> bool:
    return (
        writer.domain_id == reader.domain_id
        and writer.topic_name == reader.topic_name
    )


def _lifetimes_overlap(writer: RecordedEndpointLifetime, reader: RecordedEndpointLifetime) -> bool:
    return (
        (reader.ended_at_ns is None or writer.started_at_ns < reader.ended_at_ns)
        and (writer.ended_at_ns is None or reader.started_at_ns < writer.ended_at_ns)
    )


def _overlap_end(writer_end: int | None, reader_end: int | None) -> int | None:
    if writer_end is None:
        return reader_end
    if reader_end is None:
        return writer_end
    return min(writer_end, reader_end)


def _process_label(properties: str) -> str:
    """Use the recorded process property when available, without guessing."""

    values = {}
    for item in str(properties or "").split("\x1e"):
        parts = item.split("\x1f")
        if len(parts) >= 2:
            values[parts[0].strip()] = parts[1].strip()
    executable = values.get("dds.sys_info.executable_filepath", "")
    process_id = values.get("dds.sys_info.process_id", "")
    hostname = values.get("dds.sys_info.hostname", "")
    if executable or process_id or hostname:
        label = os.path.basename(executable) or executable or "process"
        details = " ".join(part for part in (
            f"pid {process_id}" if process_id else "",
            f"on {hostname}" if hostname else "",
        ) if part)
        return f"{label} ({details})" if details else label
    for item in str(properties or "").replace("\n", ";").split(";"):
        key, separator, value = item.partition("=")
        if separator and key.strip().lower() in {"process", "process_name", "executable", "application"}:
            return value.strip() or "unknown process"
    return "unknown process"