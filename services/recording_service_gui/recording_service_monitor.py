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
generated Python type modules (requires rti.connext >= 7.3.1) and
DDS DataReaderListeners.

DDS API Patterns Demonstrated:
  - Typed Topic / DataReader with generated Python IDL types
  - QosProvider for QoS profile selection
  - DomainParticipant, Subscriber, Topic, DataReader creation
  - DataReaderListener with on_data_available callback
  - Typed field access on received samples

The on_update callback receives plain dict updates on a DDS listener thread.
Callers are responsible for thread-safe consumption (e.g. queue.put()).

Usage:
    from recording_service_monitor import RecordingServiceMonitor

    def handle(update):
        print(update)

    sub = RecordingServiceMonitor(
        domain_id=0,
        python_types_dir="python_types",
        qos_file="../../dds/qos/DDS_QOS_PROFILES.xml",
        on_update=handle,
    )
    # ... later ...
    sub.close()
"""

import os
import sys
import rti.connextdds as dds


# ---------------------------------------------------------------------------
# Well-known monitoring topic names
# ---------------------------------------------------------------------------
MONITORING_CONFIG_TOPIC = "rti/service/monitoring/config"
MONITORING_EVENT_TOPIC = "rti/service/monitoring/event"
MONITORING_PERIODIC_TOPIC = "rti/service/monitoring/periodic"


# ---------------------------------------------------------------------------
# RecordingServiceMonitor
# ---------------------------------------------------------------------------

class RecordingServiceMonitor:
    """
    Subscribes to RTI Recording Service monitoring topics using DDS listeners.

    Creates a DomainParticipant with three typed DataReaders (config, event,
    periodic) and attaches a DataReaderListener to each.  When data arrives,
    the listener parses the typed sample and calls on_update(dict).

    Uses generated Python type modules produced by ``rtiddsgen -language Python``
    (requires rti.connext >= 7.3.1 for idl.xtypes_compliance support).

    Args:
        domain_id: DDS domain for monitoring (must match the service's
                   administration domain).
        python_types_dir: Path to directory containing generated Python type
                          modules (ServiceCommon.py, ServiceMonitoring.py, etc.)
                          produced by setup.sh.
        qos_file: Path to QoS XML file containing the
                   RecordingServiceMonitorProfiles library
                   (default: dds/qos/DDS_QOS_PROFILES.xml).
        on_update: Callback receiving parsed update dicts.  Called on a DDS
                   listener thread — use a queue for thread-safe GUI updates.
    """

    def __init__(self, domain_id: int, python_types_dir: str = None,
                 qos_file: str = None, on_update=None):
        self._on_update = on_update or (lambda _update: None)

        script_dir = os.path.dirname(os.path.abspath(__file__))

        if python_types_dir is None:
            python_types_dir = os.path.join(script_dir, "python_types")

        if qos_file is None:
            qos_file = os.path.normpath(os.path.join(
                script_dir, "..", "..", "dds", "qos",
                "DDS_QOS_PROFILES.xml"))

        # -- Import generated Python types --
        # Add the python_types directory to sys.path so the generated
        # modules can be imported directly.
        abs_types_dir = os.path.abspath(python_types_dir)
        if abs_types_dir not in sys.path:
            sys.path.insert(0, abs_types_dir)

        import importlib
        ServiceCommon = importlib.import_module("ServiceCommon")
        importlib.import_module("RecordingServiceMonitoring")
        importlib.import_module("RoutingServiceMonitoring")
        importlib.import_module("ServiceMonitoring")

        RTI = ServiceCommon.RTI

        # Stash references for use in parsing callbacks
        self._RTI = RTI
        self._ResourceKind = RTI.Service.Monitoring.ResourceKind
        self._EntityStateKind = RTI.Service.EntityStateKind

        # Type aliases for topic registration
        ConfigType = RTI.Service.Monitoring.Config
        EventType = RTI.Service.Monitoring.Event
        PeriodicType = RTI.Service.Monitoring.Periodic

        # -- Define the listener class --
        class _ReaderListener(dds.NoOpDataReaderListener):
            def __init__(listener_self, owner, reader_kind: str):
                super().__init__()
                listener_self._owner = owner
                listener_self._reader_kind = reader_kind

            def on_data_available(listener_self, reader):
                listener_self._owner._on_data_available(
                    listener_self._reader_kind, reader)

        # -- Load QoS profiles --
        qos_provider = dds.QosProvider(qos_file)

        # -- Create DomainParticipant --
        self._participant = dds.DomainParticipant(domain_id)

        # -- Create typed Topics --
        config_topic = dds.Topic(
            self._participant, MONITORING_CONFIG_TOPIC, ConfigType)
        event_topic = dds.Topic(
            self._participant, MONITORING_EVENT_TOPIC, EventType)
        periodic_topic = dds.Topic(
            self._participant, MONITORING_PERIODIC_TOPIC, PeriodicType)

        # -- Create Subscriber --
        subscriber = dds.Subscriber(self._participant)

        # -- Create DataReaders with QoS from profiles --
        config_qos = qos_provider.datareader_qos_from_profile(
            "RecordingServiceMonitorProfiles::config_Profile")
        event_qos = qos_provider.datareader_qos_from_profile(
            "RecordingServiceMonitorProfiles::event_Profile")
        periodic_qos = qos_provider.datareader_qos_from_profile(
            "RecordingServiceMonitorProfiles::periodic_Profile")

        self._config_reader = dds.DataReader(
            subscriber, config_topic, config_qos)
        self._event_reader = dds.DataReader(
            subscriber, event_topic, event_qos)
        self._periodic_reader = dds.DataReader(
            subscriber, periodic_topic, periodic_qos)

        # -- Attach listeners --
        self._config_listener = _ReaderListener(self, "config")
        self._event_listener = _ReaderListener(self, "event")
        self._periodic_listener = _ReaderListener(self, "periodic")

        self._config_reader.set_listener(
            self._config_listener, dds.StatusMask.DATA_AVAILABLE)
        self._event_reader.set_listener(
            self._event_listener, dds.StatusMask.DATA_AVAILABLE)
        self._periodic_reader.set_listener(
            self._periodic_listener, dds.StatusMask.DATA_AVAILABLE)

    # ----- Listener callback (runs on DDS thread) --------------------------

    def _on_data_available(self, reader_kind: str, reader):
        """Called by the DDS listener when new data arrives on a reader."""
        try:
            samples = reader.take()
        except Exception as e:
            self._emit({"kind": "error", "error": str(e)})
            return

        for sample in samples:
            if not sample.info.valid:
                continue
            try:
                if reader_kind == "config":
                    update = self._parse_config_sample(sample.data)
                elif reader_kind == "event":
                    update = self._parse_event_sample(sample.data)
                else:
                    update = self._parse_periodic_sample(sample.data)

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
        RK = self._ResourceKind
        kind = data.value.discriminator

        if kind == RK.RECORDING_SERVICE:
            svc = data.value.recording_service
            update = {
                "kind": "config",
                "service_detected": True,
                "service_name": str(svc.application_name),
                "db_directory": "",
                "topics": [],
            }
            try:
                if svc.builtin_sqlite is not None:
                    update["db_directory"] = str(svc.builtin_sqlite.db_directory)
            except Exception:
                pass
            return update

        if kind == RK.RECORDING_TOPIC:
            topic = data.value.recording_topic
            return {
                "kind": "config",
                "service_detected": True,
                "service_name": "",
                "db_directory": "",
                "topics": [str(topic.topic_name)],
            }

        return None

    def _parse_event_sample(self, data) -> dict:
        """Parse an Event monitoring sample into an update dict (or None)."""
        RK = self._ResourceKind
        kind = data.value.discriminator
        if kind != RK.RECORDING_SERVICE:
            return None

        svc_event = data.value.recording_service
        state = svc_event.state
        state_name = state.name if hasattr(state, 'name') else str(state)
        update = {
            "kind": "event",
            "service_detected": True,
            "state_int": state.value if hasattr(state, 'value') else int(state),
            "rollover_count": -1,
            "events": [f"Service state: {state_name}"],
        }
        try:
            if svc_event.builtin_sqlite is not None:
                rc = svc_event.builtin_sqlite.rollover_count
                if rc is not None:
                    update["rollover_count"] = int(rc)
        except Exception:
            pass

        return update

    def _parse_periodic_sample(self, data) -> dict:
        """Parse a Periodic monitoring sample into an update dict (or None)."""
        RK = self._ResourceKind
        kind = data.value.discriminator
        if kind != RK.RECORDING_SERVICE:
            return None

        svc = data.value.recording_service
        update = {
            "kind": "periodic",
            "service_detected": True,
            "uptime": -1,
            "cpu": -1.0,
            "memory_kb": -1.0,
            "db_file": "",
            "db_file_size": -1,
        }

        try:
            if svc.process is not None:
                update["uptime"] = int(svc.process.uptime_sec)
                try:
                    if svc.process.cpu_usage_percentage is not None:
                        update["cpu"] = float(
                            svc.process.cpu_usage_percentage
                            .publication_period_metrics.mean)
                except Exception:
                    pass
                try:
                    if svc.process.physical_memory_kb is not None:
                        update["memory_kb"] = float(
                            svc.process.physical_memory_kb
                            .publication_period_metrics.mean)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if svc.builtin_sqlite is not None:
                try:
                    if svc.builtin_sqlite.current_file is not None:
                        update["db_file"] = str(svc.builtin_sqlite.current_file)
                except Exception:
                    pass
                try:
                    if svc.builtin_sqlite.current_file_size is not None:
                        update["db_file_size"] = int(
                            svc.builtin_sqlite.current_file_size)
                except Exception:
                    pass
        except Exception:
            pass

        return update

    # ----- Lifecycle -------------------------------------------------------

    def close(self):
        """Close the DomainParticipant and release all DDS resources."""
        try:
            self._participant.close()
        except Exception:
            pass
