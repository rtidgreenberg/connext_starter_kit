"""Shared DDS runtime for generated Debug Game participant modules."""

from __future__ import annotations

import importlib.util
import time
import uuid
from pathlib import Path

import rti.connextdds as dds

from . import SCENARIO_DOMAIN
from .control import ControlReporter, summarize
from .generator import endpoint_stem
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
    control_reporters = []
    states = []
    run_id = uuid.uuid4().hex
    endpoint_name = endpoint_stem(scenario.topic)
    try:
        for participant_spec in scenario.participants:
            module = load_player_module(run_directory / f"participant_{participant_spec.process_id}.py")
            participant = dds.DomainParticipant(SCENARIO_DOMAIN, qos=module.ParticipantQos.make())
            control_reporter = ControlReporter(participant_spec.process_id, run_id)
            control_reporters.append(control_reporter)
            states.append(control_reporter.publish("created"))
            publisher = dds.Publisher(participant, qos=module.EndpointQos.publisher())
            subscriber = dds.Subscriber(participant, qos=module.EndpointQos.subscriber())
            dynamic_type = _build_type(module.DataModel.registered_type_name)
            topic = dds.DynamicData.Topic(participant, module.TOPIC_NAME, dynamic_type,
                                          getattr(module.EndpointQos, f"{endpoint_name}_topic")())
            entities.extend((participant, publisher, subscriber, topic))
            if scenario.topic in module.WRITES:
                writer = dds.DynamicData.DataWriter(
                    publisher, topic, getattr(module.EndpointQos, f"{endpoint_name}_writer")())
                writers.append((participant_spec.process_id, writer, dynamic_type))
                entities.append(writer)
            if scenario.topic in module.READS:
                reader = dds.DynamicData.DataReader(
                    subscriber, topic, getattr(module.EndpointQos, f"{endpoint_name}_reader")())
                readers.append((participant_spec.process_id, reader))
                entities.append(reader)
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline and any(writer.publication_matched_status.current_count == 0
                                                   for _, writer, _ in writers):
            time.sleep(0.05)
        for process_id, writer, _ in writers:
            reporter = next(item for item in control_reporters if item.process_id == process_id)
            states.append(reporter.publish("matched", writer.publication_matched_status.current_count))
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
                for reporter in control_reporters:
                    states.append(reporter.publish("passed", received_count=len(received.get(reporter.process_id, ()))))
                return {"passed": True, "run_id": run_id,
                        "received": {key: sorted(value) for key, value in received.items()},
                        "control": summarize(states)}
            time.sleep(0.05)
        for reporter in control_reporters:
            states.append(reporter.publish("waiting_for_fix", received_count=len(received.get(reporter.process_id, ()))))
        return {"passed": False, "run_id": run_id,
                "received": {key: sorted(value) for key, value in received.items()},
                "control": summarize(states)}
    finally:
        for entity in reversed(entities):
            try:
                entity.close()
            except Exception:
                pass
        for reporter in reversed(control_reporters):
            try:
                reporter.close()
            except Exception:
                pass
