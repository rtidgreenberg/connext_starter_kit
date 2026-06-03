"""DDS subscriber runtime for rti_view.

Owns DynamicData reader creation, field extraction, and bounded sample buffers.
"""

import asyncio
from collections import deque
from dataclasses import dataclass
import math
import time
from typing import Callable, Deque, Iterable, Optional, Tuple

import rti.connextdds as dds
import rti.asyncio

from .discovery import DiscoveryDiagnostic, DiscoveredEndpoint, create_participant, registry
from .fields import FieldDescriptor, enumerate_fields, get_field_value, is_numeric_value


@dataclass(frozen=True)
class ReaderSetupResult:
    """Result of creating a matched DynamicData reader."""

    reader: object = None
    subscriber: object = None
    diagnostic: Optional[DiscoveryDiagnostic] = None

    @property
    def ok(self) -> bool:
        return self.reader is not None and self.diagnostic is None


@dataclass(frozen=True)
class MessageRow:
    """One rendered message-data row."""

    timestamp: float
    value: object


@dataclass(frozen=True)
class PlotPoint:
    """One numeric plot point."""

    timestamp: float
    value: float


class FieldSampleBuffer:
    """Bounded buffers for one selected field."""

    def __init__(self, max_messages: int = 200, max_points: int = 2000) -> None:
        self._messages: Deque[MessageRow] = deque(maxlen=max(1, int(max_messages)))
        self._points: Deque[PlotPoint] = deque(maxlen=max(1, int(max_points)))
        self.skipped_invalid = 0
        self.skipped_non_numeric = 0

    def append(self, timestamp: float, value: object) -> None:
        self._messages.append(MessageRow(timestamp=float(timestamp), value=value))
        if _is_numeric(value):
            self._points.append(PlotPoint(timestamp=float(timestamp), value=float(value)))
        else:
            self.skipped_non_numeric += 1

    def append_invalid(self) -> None:
        self.skipped_invalid += 1

    @property
    def messages(self) -> Tuple[MessageRow, ...]:
        return tuple(self._messages)

    @property
    def points(self) -> Tuple[PlotPoint, ...]:
        return tuple(self._points)


def _is_numeric(value: object) -> bool:
    return is_numeric_value(value) and math.isfinite(float(value))


def setup_matched_reader(
        participant: dds.DomainParticipant,
        endpoint: DiscoveredEndpoint,
) -> ReaderSetupResult:
    """Create a DynamicData DataReader with QoS matched to the discovered writer."""
    if endpoint.dynamic_type is None:
        return ReaderSetupResult(diagnostic=DiscoveryDiagnostic(
            "type_unavailable",
            f"Topic '{endpoint.topic_name}' did not propagate a usable DynamicType.",
        ))

    try:
        dynamic_topic = dds.DynamicData.Topic(participant, endpoint.topic_name, endpoint.dynamic_type)

        subscriber_qos = dds.SubscriberQos()
        qos_set = False
        if endpoint.partition:
            subscriber_qos.partition.name = endpoint.partition.name
            qos_set = True
        if endpoint.presentation:
            subscriber_qos.presentation.access_scope = endpoint.presentation.access_scope
            subscriber_qos.presentation.coherent_access = endpoint.presentation.coherent_access
            subscriber_qos.presentation.ordered_access = endpoint.presentation.ordered_access
            qos_set = True
        subscriber = dds.Subscriber(participant, subscriber_qos) if qos_set else dds.Subscriber(participant)

        reader_qos = dds.DataReaderQos()
        if endpoint.reliability:
            reader_qos.reliability.kind = endpoint.reliability.kind
            max_blocking_time = getattr(endpoint.reliability, "max_blocking_time", None)
            if max_blocking_time is not None:
                reader_qos.reliability.max_blocking_time = max_blocking_time
        if endpoint.durability:
            reader_qos.durability.kind = endpoint.durability.kind
        if endpoint.deadline:
            reader_qos.deadline.period = endpoint.deadline.period
        if endpoint.ownership:
            reader_qos.ownership.kind = endpoint.ownership.kind

        reader = dds.DynamicData.DataReader(subscriber, dynamic_topic, reader_qos)
        return ReaderSetupResult(reader=reader, subscriber=subscriber)
    except Exception as exc:
        return ReaderSetupResult(diagnostic=DiscoveryDiagnostic(
            "reader_setup_failed",
            f"Failed to create DynamicData reader for topic '{endpoint.topic_name}': {exc}",
        ))


def create_matched_reader(participant: dds.DomainParticipant, endpoint: DiscoveredEndpoint) -> dds.DynamicData.DataReader:
    """Compatibility wrapper returning a reader or raising RuntimeError."""
    result = setup_matched_reader(participant, endpoint)
    if not result.ok:
        message = result.diagnostic.message if result.diagnostic else "reader setup failed"
        raise RuntimeError(message)
    return result.reader


async def wait_for_topic(
        topic_name: str,
        timeout: float = 10.0,
        poll_interval: float = 0.2,
        target_registry=registry,
) -> Optional[DiscoveredEndpoint]:
    """Wait until a writer for the named topic is discovered, or timeout."""
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        endpoint, diagnostics = target_registry.select_writer_for_topic(topic_name)
        if endpoint and not any(diag.code == "type_unavailable" for diag in diagnostics):
            return endpoint
        await asyncio.sleep(poll_interval)
    return None


def _sample_items(reader) -> Iterable[Tuple[object, object]]:
    for item in reader.take():
        if isinstance(item, tuple) and len(item) == 2:
            yield item[0], item[1]
        else:
            yield getattr(item, "data", None), getattr(item, "info", None)


def pump_reader_once(
        reader,
        field_path: str,
        buffer: FieldSampleBuffer,
        clock: Callable[[], float] = time.time,
) -> int:
    """Take available samples once and append selected field values to the buffer."""
    accepted = 0
    for data, info in _sample_items(reader):
        if not getattr(info, "valid", False):
            buffer.append_invalid()
            continue
        try:
            value = get_field_value(data, field_path)
        except Exception:
            buffer.append_invalid()
            continue
        buffer.append(clock(), value)
        accepted += 1
    return accepted


async def stream_field(
        reader: dds.DynamicData.DataReader,
        field_path: str,
        callback: Callable,
):
    """Continuously read samples and deliver field values via callback."""
    buffer = FieldSampleBuffer()
    while True:
        before = len(buffer.messages)
        pump_reader_once(reader, field_path, buffer)
        for row in buffer.messages[before:]:
            callback(row.timestamp, row.value)
        await asyncio.sleep(0.05)


def find_field(endpoint: DiscoveredEndpoint, field_path: str) -> Optional[FieldDescriptor]:
    if endpoint.dynamic_type is None:
        return None
    return next((field for field in enumerate_fields(endpoint.dynamic_type) if field.path == field_path), None)


def field_exists(endpoint: DiscoveredEndpoint, field_path: str) -> bool:
    return find_field(endpoint, field_path) is not None


def run_direct_view(
        domain_id: int,
        topic_name: str,
        field_path: str,
        mode: str = "text",
        history_seconds: int = 30,
        timeout: float = 10.0,
):
    """Run direct view mode: discover topic, subscribe, and render."""

    async def _run():
        participant = create_participant(domain_id)

        endpoint = await wait_for_topic(topic_name, timeout=timeout)
        if endpoint is None:
            print(f"ERROR: Topic '{topic_name}' not discovered within {timeout}s on domain {domain_id}")
            return
        field = find_field(endpoint, field_path)
        if field is None:
            print(f"ERROR: Field '{field_path}' was not found in topic '{topic_name}'")
            return
        if mode == "plot" and not field.plottable:
            print(f"ERROR: Field '{field_path}' is not numeric and cannot be plotted")
            return

        reader = create_matched_reader(participant, endpoint)
        if mode == "text":
            def print_value(ts, value):
                print(f"[{ts:.3f}] {topic_name}.{field_path} = {value}")
            await stream_field(reader, field_path, print_value)
        else:
            from .views.plot_view import run_plot
            await run_plot(reader, field_path, topic_name, history_seconds)

    asyncio.run(_run())
