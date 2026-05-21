#!/usr/bin/env python3
# (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.

"""
Recording Service Monitoring Subscriber — DDS Reference Example

Subscribes to the three RTI Recording Service monitoring topics using
DynamicData types loaded from rtiddsgen-generated XML and RTI asyncio readers.

DDS API Patterns Demonstrated:
    - DynamicData Topic / DataReader with XML-loaded DynamicTypes
  - QosProvider for QoS profile selection
  - DomainParticipant, Subscriber, Topic, DataReader creation
    - rti.asyncio reader loops backed by WaitSet dispatch
  - Typed field access on received samples

The on_update callback receives plain dict updates on the monitor's private
asyncio thread. Callers are responsible for thread-safe consumption
(e.g. queue.put()).

Usage:
    from recording_service_monitor import RecordingServiceMonitor

    def handle(update):
        print(update)

    sub = RecordingServiceMonitor(
        domain_id=0,
        xml_types_dir="xml_types",
        qos_file="../../dds/qos/DDS_QOS_PROFILES.xml",
        on_update=handle,
    )
    # ... later ...
    sub.close()
"""

import asyncio
import concurrent.futures
import os
import threading

from recording_service_environment import (
    configure_recording_service_xtypes_policy,
    ensure_connext_python,
    ensure_rti_license,
    license_setup_message,
    validate_generated_types,
)

ensure_connext_python()

import rti.connextdds as dds
import rti.asyncio as rti_asyncio


# ---------------------------------------------------------------------------
# Well-known monitoring topic names
# ---------------------------------------------------------------------------
MONITORING_CONFIG_TOPIC = "rti/service/monitoring/config"
MONITORING_EVENT_TOPIC = "rti/service/monitoring/event"
MONITORING_PERIODIC_TOPIC = "rti/service/monitoring/periodic"

CONFIG_TYPE_NAME = "RTI::Service::Monitoring::Config"
EVENT_TYPE_NAME = "RTI::Service::Monitoring::Event"
PERIODIC_TYPE_NAME = "RTI::Service::Monitoring::Periodic"

RESOURCE_RECORDING_SERVICE = 20000
RESOURCE_RECORDING_TOPIC = 20003

ENTITY_STATE_NAMES = {
    0: "INVALID",
    1: "ENABLED",
    2: "DISABLED",
    3: "STARTED",
    4: "STOPPED",
    5: "RUNNING",
    6: "PAUSED",
}

_NO_DEFAULT = object()
_MISSING = object()
_FIELD_MISSING_ERRORS = (
    AttributeError,
    KeyError,
    IndexError,
    TypeError,
    dds.InvalidArgumentError,
)


def _field(obj, name: str, default=_NO_DEFAULT):
    """Return an attribute or DynamicData field without binding to one API."""
    if obj is None:
        if default is _NO_DEFAULT:
            raise AttributeError(name)
        return default
    try:
        return getattr(obj, name)
    except AttributeError:
        pass
    try:
        return obj[name]
    except _FIELD_MISSING_ERRORS:
        if default is _NO_DEFAULT:
            raise
        return default


def _to_int(value, default=0):
    try:
        if hasattr(value, "value"):
            return int(value.value)
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_int_required(value):
    try:
        if hasattr(value, "value"):
            value = value.value
        return int(value)
    except Exception as exc:
        raise ValueError(
            f"Unable to convert union discriminator {value!r} to int") from exc


def _to_text(value, default=""):
    if value is None or value is _MISSING:
        return default
    return str(value)


def _selected_union_value(union_value, branch_name: str):
    selected = _field(union_value, "value", _MISSING)
    if selected is None:
        raise ValueError(
            f"Union discriminator {_union_discriminator(union_value)} "
            "selects no member")
    return _field(union_value, branch_name)


def _union_discriminator(union_value):
    # XML-loaded monitoring samples in Connext Python 7.6 expose service union
    # discriminators here; the monitor depends on this to ignore unknown
    # service-family branches while parsing Recording Service branches.
    errors = []
    for attr in ("discriminator", "discriminator_value"):
        try:
            value = getattr(union_value, attr)
            if callable(value):
                value = value()
            return _to_int_required(value)
        except Exception as exc:
            errors.append(exc)
    try:
        return _to_int_required(_field(union_value, "discriminator"))
    except Exception as exc:
        errors.append(exc)
    raise ValueError("Unable to read union discriminator") from errors[-1]


def _metric_mean(metric, default=-1.0):
    try:
        metrics = _field(metric, "publication_period_metrics")
        return float(_field(metrics, "mean"))
    except _FIELD_MISSING_ERRORS + (ValueError,):
        return default


def _sample_data_and_info(sample):
    try:
        return sample.data, sample.info
    except AttributeError:
        data, info = sample
        return data, info


# ---------------------------------------------------------------------------
# RecordingServiceMonitor
# ---------------------------------------------------------------------------

class RecordingServiceMonitor:
    """
    Subscribes to RTI Recording Service monitoring topics using RTI asyncio.

    Creates a DomainParticipant with three typed DataReaders (config, event,
    periodic).  A private asyncio loop processes each reader with
    ``reader.take_async()`` so parsing and callbacks do not run on DDS listener
    threads.

    Uses XML DynamicTypes produced by ``rtiddsgen -convertToXML``. This avoids
    the Python generated type identity mismatch observed with the built-in
    Recording Service monitoring writers in older Connext versions.

    Args:
        domain_id: DDS domain for monitoring (must match the service's
                   administration domain).
        xml_types_dir: Path to directory containing generated XML type files
                   (ServiceCommon.xml, ServiceMonitoring.xml, etc.)
                   produced by setup.sh.
        qos_file: Path to QoS XML file containing the
                   RecordingServiceMonitorProfiles library
                   (default: dds/qos/DDS_QOS_PROFILES.xml).
        on_update: Callback receiving parsed update dicts.  Called on the
               monitor thread — use a queue for thread-safe GUI updates.
    """

    def __init__(self, domain_id: int, xml_types_dir: str = None,
                 qos_file: str = None, on_update=None):
        self._on_update = on_update or (lambda _update: None)
        self._closed = False
        self._participant = None
        self._subscriber = None
        self._config_reader = None
        self._event_reader = None
        self._periodic_reader = None
        self._reader_tasks = []
        self._loop = None
        self._thread = None
        self._startup_complete = threading.Event()
        self._startup_error = None

        script_dir = os.path.dirname(os.path.abspath(__file__))

        if xml_types_dir is None:
            xml_types_dir = os.path.join(script_dir, "xml_types")

        if qos_file is None:
            qos_file = os.path.normpath(os.path.join(
                script_dir, "..", "..", "dds", "qos",
                "DDS_QOS_PROFILES.xml"))

        nddshome = os.environ.get("NDDSHOME")
        ensure_rti_license(nddshome)
        configure_recording_service_xtypes_policy()

        service_monitoring_xml = os.path.join(
            xml_types_dir, "ServiceMonitoring.xml")
        if not os.path.isfile(service_monitoring_xml):
            raise FileNotFoundError(
                f"Required monitoring XML not found: {service_monitoring_xml}\n"
                "Run setup.sh first to generate XML type files."
            )
        validate_generated_types(xml_types_dir, nddshome)

        self._domain_id = domain_id
        self._qos_file = qos_file
        self._service_monitoring_xml = service_monitoring_xml

        self._thread = threading.Thread(
            target=self._thread_main,
            name=f"RecordingServiceMonitor-{domain_id}",
            daemon=True,
        )
        self._thread.start()
        self._startup_complete.wait()
        if self._startup_error is not None:
            self.close()
            raise self._startup_error

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        loop.create_task(self._start_async())
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop)
                       if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _start_async(self):
        try:
            self._create_dds_entities()
            self._reader_tasks = [
                asyncio.create_task(
                    self._reader_loop("config", self._config_reader),
                    name="recording-monitor-config"),
                asyncio.create_task(
                    self._reader_loop("event", self._event_reader),
                    name="recording-monitor-event"),
                asyncio.create_task(
                    self._reader_loop("periodic", self._periodic_reader),
                    name="recording-monitor-periodic"),
            ]
            self._startup_complete.set()
        except Exception as exc:
            self._startup_error = exc
            self._startup_complete.set()
            try:
                self._close_dds_entities()
            finally:
                if self._loop is not None:
                    self._loop.call_soon(self._loop.stop)

    def _create_dds_entities(self):
        # -- Load XML DynamicTypes and QoS profiles --
        type_provider = dds.QosProvider(self._service_monitoring_xml)
        config_type = type_provider.type(CONFIG_TYPE_NAME)
        event_type = type_provider.type(EVENT_TYPE_NAME)
        periodic_type = type_provider.type(PERIODIC_TYPE_NAME)

        qos_provider = dds.QosProvider(self._qos_file)

        # -- Create DomainParticipant --
        try:
            self._participant = dds.DomainParticipant(self._domain_id)
        except Exception as exc:
            raise RuntimeError(
                "Failed to create DDS DomainParticipant on domain "
                f"{self._domain_id}. "
                f"{license_setup_message(os.environ.get('NDDSHOME'))}") from exc

        # -- Create DynamicData Topics --
        config_topic = dds.DynamicData.Topic(
            self._participant, MONITORING_CONFIG_TOPIC, config_type)
        event_topic = dds.DynamicData.Topic(
            self._participant, MONITORING_EVENT_TOPIC, event_type)
        periodic_topic = dds.DynamicData.Topic(
            self._participant, MONITORING_PERIODIC_TOPIC, periodic_type)

        # -- Create Subscriber --
        self._subscriber = dds.Subscriber(self._participant)

        # -- Create DataReaders with QoS from profiles --
        config_qos = qos_provider.datareader_qos_from_profile(
            "RecordingServiceMonitorProfiles::config_Profile")
        event_qos = qos_provider.datareader_qos_from_profile(
            "RecordingServiceMonitorProfiles::event_Profile")
        periodic_qos = qos_provider.datareader_qos_from_profile(
            "RecordingServiceMonitorProfiles::periodic_Profile")

        self._config_reader = dds.DynamicData.DataReader(
            self._subscriber, config_topic, config_qos)
        self._event_reader = dds.DynamicData.DataReader(
            self._subscriber, event_topic, event_qos)
        self._periodic_reader = dds.DynamicData.DataReader(
            self._subscriber, periodic_topic, periodic_qos)

    # ----- Async reader callbacks (run on the monitor thread) --------------

    async def _reader_loop(self, reader_kind: str, reader):
        """Process one monitoring reader using RTI asyncio."""
        try:
            async for sample in reader.take_async():
                if self._closed:
                    return
                self._process_sample(reader_kind, sample)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._closed:
                self._emit({"kind": "error", "error": str(e)})

    def _process_sample(self, reader_kind: str, sample):
        """Parse one SampleInfo/Data pair and emit any resulting update."""
        data, info = _sample_data_and_info(sample)
        if not info.valid:
            return
        try:
            if reader_kind == "config":
                update = self._parse_config_sample(data)
            elif reader_kind == "event":
                update = self._parse_event_sample(data)
            else:
                update = self._parse_periodic_sample(data)

            if update is not None:
                self._emit(update)
        except Exception as e:
            self._emit({
                "kind": "error",
                "error": f"{reader_kind} parse error: {e}",
            })

    def _emit(self, update: dict):
        """Send an update to the callback, swallowing any exceptions."""
        try:
            self._on_update(update)
        except Exception:
            pass

    # ----- Sample parsing (typed Python objects → plain dict) --------------
    #
    # Each monitoring topic uses a discriminated union keyed by ResourceKind.
    # We only extract fields relevant to Recording Service resources.

    def _parse_config_sample(self, data) -> dict:
        """Parse a Config monitoring sample into an update dict (or None)."""
        union_value = _field(data, "value")
        kind = _union_discriminator(union_value)

        if kind == RESOURCE_RECORDING_SERVICE:
            svc = _selected_union_value(union_value, "recording_service")
            update = {
                "kind": "config",
                "service_detected": True,
                "service_name": _to_text(
                    _field(svc, "application_name", "")),
                "db_directory": "",
                "topics": [],
            }
            sqlite = _field(svc, "builtin_sqlite", None)
            if sqlite is not None:
                update["db_directory"] = _to_text(
                    _field(sqlite, "db_directory", ""))
            return update

        if kind == RESOURCE_RECORDING_TOPIC:
            topic = _selected_union_value(union_value, "recording_topic")
            return {
                "kind": "config",
                "service_detected": True,
                "service_name": "",
                "db_directory": "",
                "topics": [_to_text(_field(topic, "topic_name", ""))],
            }

        return None

    def _parse_event_sample(self, data) -> dict:
        """Parse an Event monitoring sample into an update dict (or None)."""
        union_value = _field(data, "value")
        kind = _union_discriminator(union_value)
        if kind != RESOURCE_RECORDING_SERVICE:
            return None

        svc_event = _selected_union_value(union_value, "recording_service")
        state = _field(svc_event, "state")
        state_int = _to_int(state)
        state_name = (state.name if hasattr(state, 'name')
                      else ENTITY_STATE_NAMES.get(state_int, str(state)))
        update = {
            "kind": "event",
            "service_detected": True,
            "state_int": state_int,
            "rollover_count": -1,
            "events": [f"Service state: {state_name}"],
        }
        sqlite = _field(svc_event, "builtin_sqlite", None)
        if sqlite is not None:
            rc = _field(sqlite, "rollover_count", None)
            if rc is not None:
                update["rollover_count"] = _to_int(rc, -1)

        return update

    def _parse_periodic_sample(self, data) -> dict:
        """Parse a Periodic monitoring sample into an update dict (or None)."""
        union_value = _field(data, "value")
        kind = _union_discriminator(union_value)
        if kind != RESOURCE_RECORDING_SERVICE:
            return None

        svc = _selected_union_value(union_value, "recording_service")
        update = {
            "kind": "periodic",
            "service_detected": True,
            "uptime": -1,
            "cpu": -1.0,
            "memory_kb": -1.0,
            "db_file": "",
            "db_file_size": -1,
        }

        process = _field(svc, "process", None)
        host = _field(svc, "host", None)
        if process is not None:
            update["uptime"] = _to_int(_field(process, "uptime_sec", -1), -1)
            cpu = _field(process, "cpu_usage_percentage", None)
            if cpu is not None:
                update["cpu"] = _metric_mean(cpu)
            memory = _field(process, "physical_memory_kb", None)
            if memory is not None:
                update["memory_kb"] = _metric_mean(memory)
        if host is not None:
            if update["uptime"] < 0:
                update["uptime"] = _to_int(
                    _field(host, "uptime_sec", -1), -1)
            if update["cpu"] < 0:
                update["cpu"] = _metric_mean(
                    _field(host, "cpu_usage_percentage", None))
            if update["memory_kb"] < 0:
                update["memory_kb"] = _metric_mean(
                    _field(host, "free_memory_kb", None))

        sqlite = _field(svc, "builtin_sqlite", None)
        if sqlite is not None:
            current_file = _field(sqlite, "current_file", None)
            if current_file is not None:
                update["db_file"] = _to_text(current_file)
            file_size = _field(sqlite, "current_file_size", None)
            if file_size is not None:
                update["db_file_size"] = _to_int(file_size, -1)

        return update

    # ----- Lifecycle -------------------------------------------------------

    def close(self):
        """Stop async reader tasks and release all DDS resources."""
        if self._closed:
            return
        self._closed = True

        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._shutdown_async(), loop)
                future.result(timeout=5.0)
            except concurrent.futures.TimeoutError:
                pass
            except Exception:
                pass
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        else:
            self._close_dds_entities()

        if (self._thread is not None
                and self._thread is not threading.current_thread()):
            self._thread.join(timeout=5.0)

    async def _shutdown_async(self):
        tasks = list(self._reader_tasks)
        self._reader_tasks = []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await rti_asyncio.close()
        except Exception:
            pass
        self._close_dds_entities()

    def _close_dds_entities(self):
        participant = self._participant
        self._config_reader = None
        self._event_reader = None
        self._periodic_reader = None
        self._subscriber = None
        self._participant = None
        if participant is None:
            return
        try:
            if hasattr(participant, "close_contained_entities"):
                participant.close_contained_entities()
        except Exception:
            pass
        try:
            participant.close()
        except Exception:
            pass
