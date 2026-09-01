"""Immutable DDS telemetry for Debug Game coordination on its private domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

import rti.connextdds as dds

from . import CONTROL_DOMAIN

CONTROL_TOPIC = "GameParticipantState"
CONTROL_TYPE = "rti_debug_game::GameParticipantState"


@dataclass(frozen=True)
class ParticipantState:
    process_id: str
    run_id: str
    lifecycle: str
    matched_count: int = 0
    received_count: int = 0
    error_detail: str = ""


def build_type():
    dynamic_type = dds.StructType(CONTROL_TYPE)
    dynamic_type.add_member(dds.Member("process_id", dds.StringType(64), is_key=True))
    dynamic_type.add_member(dds.Member("run_id", dds.StringType(64)))
    dynamic_type.add_member(dds.Member("lifecycle", dds.StringType(32)))
    dynamic_type.add_member(dds.Member("matched_count", dds.Int32Type()))
    dynamic_type.add_member(dds.Member("received_count", dds.Int32Type()))
    dynamic_type.add_member(dds.Member("error_detail", dds.StringType(256)))
    return dynamic_type


def summarize(states: Iterable[ParticipantState]) -> Dict[str, Dict[str, object]]:
    """Return the last reported state for each process, suitable for result JSON."""
    return {
        state.process_id: {
            "lifecycle": state.lifecycle,
            "matched_count": state.matched_count,
            "received_count": state.received_count,
            "error_detail": state.error_detail,
        }
        for state in states
    }


class ControlReporter:
    """Fixed control-domain writer owned by the shared participant runtime."""

    def __init__(self, process_id: str, run_id: str):
        self.process_id = process_id
        self.run_id = run_id
        self.dynamic_type = build_type()
        qos = dds.DomainParticipantQos()
        qos.participant_name.name = f"DebugGameControl-{process_id}"
        self.participant = dds.DomainParticipant(CONTROL_DOMAIN, qos=qos)
        self.publisher = dds.Publisher(self.participant)
        self.topic = dds.DynamicData.Topic(self.participant, CONTROL_TOPIC, self.dynamic_type)
        self.writer = dds.DynamicData.DataWriter(self.publisher, self.topic)

    def publish(self, lifecycle: str, matched_count: int = 0, received_count: int = 0,
                error_detail: str = "") -> ParticipantState:
        state = ParticipantState(self.process_id, self.run_id, lifecycle,
                                 matched_count, received_count, error_detail)
        sample = dds.DynamicData(self.dynamic_type)
        sample["process_id"] = state.process_id
        sample["run_id"] = state.run_id
        sample["lifecycle"] = state.lifecycle
        sample["matched_count"] = state.matched_count
        sample["received_count"] = state.received_count
        sample["error_detail"] = state.error_detail
        self.writer.write(sample)
        return state

    def close(self):
        self.writer.close()
        self.topic.close()
        self.publisher.close()
        self.participant.close()