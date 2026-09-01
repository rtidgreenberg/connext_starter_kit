"""Render package-owned scenarios as editable per-process Python modules."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import SCENARIO_DOMAIN
from .levels import Scenario


def game_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_root() -> Path:
    return game_root() / "run"


def endpoint_stem(topic: str) -> str:
    """Convert a DDS topic name to the generated QoS factory name."""
    return "".join(f"_{character.lower()}" if character.isupper() else character
                   for character in topic).lstrip("_")


def _participant_source(scenario: Scenario, participant) -> str:
    writes = repr(participant.writes)
    reads = repr(participant.reads)
    stem = endpoint_stem(scenario.topic)
    broken_reliability = (scenario.fault == "reliability"
                          and participant.process_id == scenario.expected_writer)
    reliability = "dds.ReliabilityKind.BEST_EFFORT" if broken_reliability else "dds.ReliabilityKind.RELIABLE"
    topic_name = (f"{scenario.topic}Outbound" if scenario.fault == "topic_name"
                  and participant.process_id == scenario.expected_writer else scenario.topic)
    publisher_partition = ("alerts" if scenario.fault == "partition"
                           and participant.process_id == scenario.expected_writer else "operations")
    subscriber_partition = ("telemetry" if scenario.fault == "partition"
                            and participant.process_id == scenario.expected_reader else "operations")
    return f'''"""Editable configuration for {participant.name}."""

import rti.connextdds as dds

PROCESS_ID = {participant.process_id!r}
PARTICIPANT_NAME = {participant.name!r}
WRITES = {writes}
READS = {reads}
TOPIC_NAME = {topic_name!r}


class ParticipantQos:
    """Participant-level QoS. Domain {SCENARIO_DOMAIN} is game-owned."""

    @staticmethod
    def make() -> dds.DomainParticipantQos:
        qos = dds.DomainParticipantQos()
        qos.participant_name.name = PARTICIPANT_NAME
        return qos


class EndpointQos:
    """QoS factories for this process's Publisher, Subscriber, and endpoints."""

    @staticmethod
    def publisher() -> dds.PublisherQos:
        qos = dds.PublisherQos()
        qos.partition.name = [{publisher_partition!r}]
        return qos

    @staticmethod
    def subscriber() -> dds.SubscriberQos:
        qos = dds.SubscriberQos()
        qos.partition.name = [{subscriber_partition!r}]
        return qos

    @staticmethod
    def {stem}_topic() -> dds.TopicQos:
        return dds.TopicQos()

    @staticmethod
    def {stem}_writer() -> dds.DataWriterQos:
        qos = dds.DataWriterQos()
        qos.reliability.kind = {reliability}
        qos.history.depth = 20
        return qos

    @staticmethod
    def {stem}_reader() -> dds.DataReaderQos:
        qos = dds.DataReaderQos()
        qos.reliability.kind = dds.ReliabilityKind.RELIABLE
        return qos


class DataModel:
    """Type metadata. The shared runtime owns the fixed DynamicData fields."""

    registered_type_name = {scenario.type_name!r}
    extensibility = dds.ExtensibilityKind.EXTENSIBLE
'''


def generate(scenario: Scenario, reset: bool = False) -> Path:
    root = run_root()
    expected_path = root / "expected.json"
    if root.exists() and expected_path.exists() and not reset:
        previous = json.loads(expected_path.read_text(encoding="ascii"))
        reset = previous.get("level") != scenario.level_id
    if root.exists() and reset:
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for participant in scenario.participants:
        path = root / f"participant_{participant.process_id}.py"
        if reset or not path.exists():
            path.write_text(_participant_source(scenario, participant), encoding="ascii")
    expected = {
        "level": scenario.level_id,
        "domain": SCENARIO_DOMAIN,
        "topic": scenario.topic,
        "reader": scenario.expected_reader,
        "writer": scenario.expected_writer,
        "samples_per_round": scenario.samples_per_round,
    }
    (root / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="ascii")
    readme = f"""DDS Debug Game {scenario.level_id}: {scenario.title}

Scenario domain: {SCENARIO_DOMAIN}
Open domain {SCENARIO_DOMAIN} in RTI Admin Console.
Participants: {', '.join(item.name for item in scenario.participants)}
Topic: {scenario.topic}
Registered type: {scenario.type_name}

Mission Contract: {scenario.expected_reader} must receive sequences 1-{scenario.samples_per_round}
from {scenario.expected_writer} on {scenario.topic}.

Edit only participant_*.py. Use --run to recreate DDS entities with your edits.
Use --reset --level {scenario.level_id} to regenerate the initial broken scripts.
"""
    (root / "README.txt").write_text(readme, encoding="ascii")
    return root
