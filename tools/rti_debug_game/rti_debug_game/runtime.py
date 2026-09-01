"""Shared DDS runtime for generated Debug Game participant modules."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import rti.connextdds as dds

from . import SCENARIO_DOMAIN
from .levels import Scenario


def load_player_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _build_type(type_name: str):
    dynamic_type = dds.StructType(type_name)
    dynamic_type.add_member(dds.Member("writer_id", dds.StringType(64)))
    dynamic_type.add_member(dds.Member("sequence", dds.Int32Type()))
    dynamic_type.add_member(dds.Member("instance_key", dds.Int32Type(), is_key=True))
    dynamic_type.add_member(dds.Member("region", dds.StringType(16)))
    return dynamic_type


def run_once(scenario: Scenario, run_directory: Path, duration: float = 4.0) -> dict:
    """Run a finite headless round; interactive TUI lifetime comes in the next slice."""
    entities = []
    readers = []
    writers = []
    try:
        for participant_spec in scenario.participants:
            module = load_player_module(run_directory / f"participant_{participant_spec.process_id}.py")
            participant = dds.DomainParticipant(SCENARIO_DOMAIN, qos=module.ParticipantQos.make())
            publisher = dds.Publisher(participant, qos=module.EndpointQos.publisher())
            subscriber = dds.Subscriber(participant, qos=module.EndpointQos.subscriber())
            dynamic_type = _build_type(module.DataModel.registered_type_name)
            topic = dds.DynamicData.Topic(participant, scenario.topic, dynamic_type,
                                          module.EndpointQos.vehicle_command_topic())
            entities.extend((participant, publisher, subscriber, topic))
            if scenario.topic in module.WRITES:
                writer = dds.DynamicData.DataWriter(
                    publisher, topic, module.EndpointQos.vehicle_command_writer())
                writers.append((participant_spec.process_id, writer, dynamic_type))
                entities.append(writer)
            if scenario.topic in module.READS:
                reader = dds.DynamicData.DataReader(
                    subscriber, topic, module.EndpointQos.vehicle_command_reader())
                readers.append((participant_spec.process_id, reader))
                entities.append(reader)
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline and any(writer.publication_matched_status.current_count == 0
                                                   for _, writer, _ in writers):
            time.sleep(0.05)
        received = {reader_id: set() for reader_id, _ in readers}

        def collect_receipts():
            for reader_id, reader in readers:
                for sample in reader.take():
                    if sample.info.valid:
                        received[reader_id].add((sample.data["writer_id"], sample.data["sequence"]))

        for writer_id, writer, dynamic_type in writers:
            for sequence in range(1, scenario.samples_per_round + 1):
                sample = dds.DynamicData(dynamic_type)
                sample["writer_id"] = writer_id
                sample["sequence"] = sequence
                sample["instance_key"] = 1
                sample["region"] = "west"
                writer.write(sample)
                time.sleep(0.05)
                collect_receipts()
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            collect_receipts()
            expected = {(scenario.expected_writer, sequence) for sequence in range(1, scenario.samples_per_round + 1)}
            if expected.issubset(received.get(scenario.expected_reader, set())):
                return {"passed": True, "received": {key: sorted(value) for key, value in received.items()}}
            time.sleep(0.05)
        return {"passed": False, "received": {key: sorted(value) for key, value in received.items()}}
    finally:
        for entity in reversed(entities):
            try:
                entity.close()
            except Exception:
                pass
