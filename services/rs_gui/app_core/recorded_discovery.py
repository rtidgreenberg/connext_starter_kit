"""Read the Connext 7.7 Recording Service discovery database safely."""

from __future__ import annotations

from dataclasses import dataclass
import os
import sqlite3
from typing import Dict, Iterable, Optional, Tuple


class RecordedDiscoverySchemaError(ValueError):
    """The selected recording does not expose the supported discovery schema."""


@dataclass(frozen=True)
class RecordedParticipant:
    """Latest participant metadata available at an endpoint observation."""

    key: str
    name: str
    domain_id: Optional[int]
    properties: str


@dataclass(frozen=True)
class RecordedEndpointLifetime:
    """One interval during which a discovered endpoint was valid."""

    key: str
    kind: str
    participant_key: str
    topic_name: str
    type_name: str
    domain_id: Optional[int]
    started_at_ns: int
    ended_at_ns: Optional[int]
    qos: Tuple[Tuple[str, object], ...]

    @property
    def is_open(self) -> bool:
        return self.ended_at_ns is None

    def is_active_at(self, timestamp_ns: int) -> bool:
        return self.started_at_ns <= timestamp_ns and (
            self.ended_at_ns is None or timestamp_ns < self.ended_at_ns
        )


@dataclass(frozen=True)
class RecordedDiscovery:
    """Immutable historical discovery data extracted from one recording."""

    participants: Tuple[RecordedParticipant, ...]
    endpoints: Tuple[RecordedEndpointLifetime, ...]

    @property
    def domains(self) -> Tuple[int, ...]:
        return tuple(sorted({item.domain_id for item in self.participants if item.domain_id is not None}))

    def active_endpoints_at(self, timestamp_ns: int) -> Tuple[RecordedEndpointLifetime, ...]:
        return tuple(item for item in self.endpoints if item.is_active_at(timestamp_ns))


_TABLE_COLUMNS = {
    "DCPSParticipant": {
        "SampleInfo_reception_timestamp",
        "SampleInfo_valid_data",
        "ParticipantData_key",
        "ParticipantData_participant_name",
        "ParticipantData_domain_id",
        "ParticipantData_property",
    },
    "DCPSPublication": {
        "SampleInfo_reception_timestamp",
        "SampleInfo_valid_data",
        "PublicationData_key",
        "PublicationData_participant_key",
        "PublicationData_topic_name",
        "PublicationData_type_name",
        "PublicationData_reliability_kind",
        "PublicationData_durability_kind",
        "PublicationData_deadline_period",
        "PublicationData_latency_budget_duration",
        "PublicationData_liveliness_kind",
        "PublicationData_liveliness_lease_duration",
        "PublicationData_ownership_kind",
        "PublicationData_destination_order_kind",
        "PublicationData_presentation_access_scope",
        "PublicationData_presentation_coherent_access",
        "PublicationData_presentation_ordered_access",
        "PublicationData_partition",
        "PublicationData_rtps_vendor_id",
    },
    "DCPSSubscription": {
        "SampleInfo_reception_timestamp",
        "SampleInfo_valid_data",
        "SubscriptionData_key",
        "SubscriptionData_participant_key",
        "SubscriptionData_topic_name",
        "SubscriptionData_type_name",
        "SubscriptionData_reliability_kind",
        "SubscriptionData_durability_kind",
        "SubscriptionData_deadline_period",
        "SubscriptionData_latency_budget_duration",
        "SubscriptionData_liveliness_kind",
        "SubscriptionData_liveliness_lease_duration",
        "SubscriptionData_ownership_kind",
        "SubscriptionData_destination_order_kind",
        "SubscriptionData_presentation_access_scope",
        "SubscriptionData_presentation_coherent_access",
        "SubscriptionData_presentation_ordered_access",
        "SubscriptionData_partition",
        "SubscriptionData_rtps_vendor_id",
    },
}


def load_recorded_discovery(recording_directory: str) -> RecordedDiscovery:
    """Load `discovery.db` from a recording directory without modifying it."""

    database_path = os.path.join(str(recording_directory), "discovery.db")
    if not os.path.isfile(database_path):
        raise RecordedDiscoverySchemaError("Recording does not contain discovery.db")
    connection = sqlite3.connect(f"file:{os.path.abspath(database_path)}?mode=ro", uri=True)
    try:
        _validate_schema(connection)
        participants = _load_participants(connection)
        endpoints = _load_endpoint_lifetimes(connection, "DCPSPublication", "PublicationData", "Writer", participants)
        endpoints += _load_endpoint_lifetimes(connection, "DCPSSubscription", "SubscriptionData", "Reader", participants)
        return RecordedDiscovery(tuple(participants.values()), tuple(sorted(endpoints, key=_endpoint_sort_key)))
    finally:
        connection.close()


def _validate_schema(connection: sqlite3.Connection) -> None:
    for table_name, required_columns in _TABLE_COLUMNS.items():
        available_columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info([{table_name}])")
        }
        missing = sorted(required_columns - available_columns)
        if missing:
            raise RecordedDiscoverySchemaError(
                f"Unsupported discovery.db schema: {table_name} is missing {', '.join(missing)}"
            )


def _load_participants(connection: sqlite3.Connection) -> Dict[str, RecordedParticipant]:
    participants: Dict[str, RecordedParticipant] = {}
    query = """
        SELECT SampleInfo_reception_timestamp, SampleInfo_valid_data,
               ParticipantData_key, ParticipantData_participant_name,
               ParticipantData_domain_id, ParticipantData_property
        FROM DCPSParticipant
        ORDER BY SampleInfo_reception_timestamp
    """
    for _, valid, key, name, domain_id, properties in connection.execute(query):
        if not valid or key is None:
            continue
        participants[_key_text(key)] = RecordedParticipant(
            key=_key_text(key),
            name=str(name or ""),
            domain_id=int(domain_id) if domain_id is not None else None,
            properties=str(properties or ""),
        )
    return participants


def _load_endpoint_lifetimes(
        connection: sqlite3.Connection,
        table_name: str,
        prefix: str,
        kind: str,
        participants: Dict[str, RecordedParticipant],
) -> Tuple[RecordedEndpointLifetime, ...]:
    columns = sorted(_TABLE_COLUMNS[table_name])
    query = f"SELECT {', '.join(f'[{column}]' for column in columns)} FROM [{table_name}] ORDER BY [SampleInfo_reception_timestamp]"
    open_lifetimes: Dict[str, RecordedEndpointLifetime] = {}
    completed = []
    for row in connection.execute(query):
        values = dict(zip(columns, row))
        key = _key_text(values[f"{prefix}_key"])
        timestamp = int(values["SampleInfo_reception_timestamp"])
        if values["SampleInfo_valid_data"]:
            participant_key = _key_text(values[f"{prefix}_participant_key"])
            participant = participants.get(participant_key)
            previous = open_lifetimes.get(key)
            open_lifetimes[key] = RecordedEndpointLifetime(
                key=key,
                kind=kind,
                participant_key=participant_key,
                topic_name=str(values[f"{prefix}_topic_name"] or ""),
                type_name=str(values[f"{prefix}_type_name"] or ""),
                domain_id=participant.domain_id if participant is not None else None,
                started_at_ns=previous.started_at_ns if previous is not None else timestamp,
                ended_at_ns=None,
                qos=tuple(sorted((column.removeprefix(f"{prefix}_"), value) for column, value in values.items() if column.startswith(f"{prefix}_") and column not in {f"{prefix}_key", f"{prefix}_participant_key", f"{prefix}_topic_name", f"{prefix}_type_name"})),
            )
        elif key in open_lifetimes:
            opened = open_lifetimes.pop(key)
            completed.append(RecordedEndpointLifetime(**{**opened.__dict__, "ended_at_ns": timestamp}))
    completed.extend(open_lifetimes.values())
    return tuple(completed)


def _key_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.hex().upper()
    return str(value or "")


def _endpoint_sort_key(item: RecordedEndpointLifetime) -> tuple:
    return (item.domain_id if item.domain_id is not None else -1, item.topic_name, item.kind, item.key, item.started_at_ns)