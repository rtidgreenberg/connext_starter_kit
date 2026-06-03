#!/usr/bin/env python3
"""Unit tests for the rs_gui_v2 RTI service monitoring adapter."""

import os
from types import SimpleNamespace
import sys
import tempfile
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core.services import MonitoringSnapshotKind, ServiceInstanceRef, ServiceKind
from app_core.services.rti_monitoring import (
    CONFIG_QOS_PROFILE,
    EVENT_QOS_PROFILE,
    MONITORING_CONFIG_TOPIC,
    MONITORING_EVENT_TOPIC,
    MONITORING_PERIODIC_TOPIC,
    PERIODIC_QOS_PROFILE,
    RESOURCE_RECORDING_SERVICE,
    RESOURCE_RECORDING_TOPIC,
    RtiServiceMonitoringClient,
    RtiServiceMonitoringConfig,
    normalize_monitoring_sample,
)


class FakeQosProvider:
    def __init__(self, path):
        self.path = path

    def type(self, type_name):
        return type_name

    def datareader_qos_from_profile(self, profile):
        return f"reader:{profile}"


class FakeParticipant:
    def __init__(self, domain_id):
        self.domain_id = domain_id
        self.closed = False
        self.closed_contained = False

    def close_contained_entities(self):
        self.closed_contained = True

    def close(self):
        self.closed = True


class FakeSubscriber:
    def __init__(self, participant):
        self.participant = participant
        self.closed = False

    def close(self):
        self.closed = True


class FakeTopic:
    def __init__(self, participant, name, type_name):
        self.participant = participant
        self.name = name
        self.type_name = type_name


class FakeDataReader:
    created = []
    samples_by_topic = {}

    def __init__(self, subscriber, topic, qos):
        self.subscriber = subscriber
        self.topic = topic
        self.qos = qos
        FakeDataReader.created.append(self)

    def take(self):
        samples = list(FakeDataReader.samples_by_topic.get(self.topic.name, ()))
        FakeDataReader.samples_by_topic[self.topic.name] = []
        return samples


class FakeDynamicData:
    Topic = FakeTopic
    DataReader = FakeDataReader


class FakeDdsModule:
    QosProvider = FakeQosProvider
    DomainParticipant = FakeParticipant
    Subscriber = FakeSubscriber
    DynamicData = FakeDynamicData


class FakeSample:
    def __init__(self, data, valid=True):
        self.data = data
        self.info = SimpleNamespace(valid=valid)


def metric(mean):
    return SimpleNamespace(publication_period_metrics=SimpleNamespace(mean=mean))


def sample_for(
        resource_kind,
        branch_name,
        branch_data,
        valid=True,
        object_guid=None,
        owner_guid=None,
):
    union = SimpleNamespace(
        discriminator=resource_kind,
        value=object(),
        **{branch_name: branch_data},
    )
    data = SimpleNamespace(value=union)
    if object_guid is not None:
        data.object_guid = SimpleNamespace(value=object_guid)
    if owner_guid is not None:
        data.owner_guid = SimpleNamespace(value=owner_guid)
    return FakeSample(data, valid=valid)


class TestMonitoringSampleNormalization(unittest.TestCase):
    def setUp(self):
        self.service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy", monitoring_domain_id=54)

    def test_config_service_sample_normalizes_details(self):
        branch = SimpleNamespace(
            application_name="deploy",
            application_guid=SimpleNamespace(value=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]),
            process=SimpleNamespace(id=4321),
            host=SimpleNamespace(name="dev-host", id=7, target="x64Linux4gcc7.3.0"),
            builtin_sqlite=SimpleNamespace(db_directory="/tmp/recordings"),
        )
        snapshot = normalize_monitoring_sample(
            self.service,
            MonitoringSnapshotKind.CONFIG,
            sample_for(RESOURCE_RECORDING_SERVICE, "recording_service", branch),
        )

        self.assertEqual(snapshot.kind, MonitoringSnapshotKind.CONFIG)
        self.assertEqual(snapshot.state, "configured")
        self.assertEqual(snapshot.details["service_name"], "deploy")
        self.assertEqual(snapshot.details["application_guid"], "000102030405060708090a0b0c0d0e0f")
        self.assertEqual(snapshot.details["process_id"], 4321)
        self.assertEqual(snapshot.details["host_name"], "dev-host")
        self.assertEqual(snapshot.details["host_id"], 7)
        self.assertEqual(snapshot.details["host_target"], "x64Linux4gcc7.3.0")
        self.assertEqual(snapshot.details["db_directory"], "/tmp/recordings")

    def test_config_topic_sample_normalizes_topic_name(self):
        branch = SimpleNamespace(topic_name="Position")
        snapshot = normalize_monitoring_sample(
            self.service,
            MonitoringSnapshotKind.CONFIG,
            sample_for(RESOURCE_RECORDING_TOPIC, "recording_topic", branch),
        )

        self.assertEqual(snapshot.details["topics"], ["Position"])

    def test_event_sample_normalizes_state_and_rollover(self):
        branch = SimpleNamespace(
            state=SimpleNamespace(value=6, name="PAUSED"),
            builtin_sqlite=SimpleNamespace(
                current_db_directory="/tmp/recordings/run_1",
                current_file="data_0.db",
                rollover_count=2,
            ),
        )
        snapshot = normalize_monitoring_sample(
            self.service,
            MonitoringSnapshotKind.EVENT,
            sample_for(RESOURCE_RECORDING_SERVICE, "recording_service", branch),
        )

        self.assertEqual(snapshot.state, "PAUSED")
        self.assertEqual(snapshot.details["state_int"], 6)
        self.assertEqual(snapshot.metrics["rollover_count"], 2)
        self.assertEqual(snapshot.details["current_db_directory"], "/tmp/recordings/run_1")
        self.assertEqual(snapshot.details["db_file"], "data_0.db")
        self.assertEqual(snapshot.details["current_file"], "/tmp/recordings/run_1/data_0.db")

    def test_event_sample_keeps_directory_qualified_relative_current_file(self):
        branch = SimpleNamespace(
            state=SimpleNamespace(value=5, name="RUNNING"),
            builtin_sqlite=SimpleNamespace(
                current_db_directory="log_dir/recording_1780055124",
                current_file="log_dir/recording_1780055124/data_0.db",
                rollover_count=0,
            ),
        )
        snapshot = normalize_monitoring_sample(
            self.service,
            MonitoringSnapshotKind.EVENT,
            sample_for(RESOURCE_RECORDING_SERVICE, "recording_service", branch),
        )

        self.assertEqual(snapshot.state, "RUNNING")
        self.assertEqual(snapshot.details["db_file"], "log_dir/recording_1780055124/data_0.db")
        self.assertEqual(snapshot.details["current_file"], "log_dir/recording_1780055124/data_0.db")

    def test_periodic_sample_normalizes_metrics(self):
        branch = SimpleNamespace(
            process=SimpleNamespace(
                uptime_sec=10,
                cpu_usage_percentage=metric(1.5),
                physical_memory_kb=metric(2048),
            ),
            builtin_sqlite=SimpleNamespace(
                current_file="data_0.dat",
                current_file_size=4096,
            ),
        )
        snapshot = normalize_monitoring_sample(
            self.service,
            MonitoringSnapshotKind.PERIODIC,
            sample_for(RESOURCE_RECORDING_SERVICE, "recording_service", branch),
        )

        self.assertEqual(snapshot.state, "observed")
        self.assertEqual(snapshot.metrics["uptime_sec"], 10)
        self.assertEqual(snapshot.metrics["cpu_percent"], 1.5)
        self.assertEqual(snapshot.metrics["memory_kb"], 2048)
        self.assertEqual(snapshot.metrics["db_file_size"], 4096)
        self.assertEqual(snapshot.details["db_file"], "data_0.dat")

    def test_invalid_sample_is_ignored(self):
        branch = SimpleNamespace(application_name="deploy")
        snapshot = normalize_monitoring_sample(
            self.service,
            MonitoringSnapshotKind.CONFIG,
            sample_for(RESOURCE_RECORDING_SERVICE, "recording_service", branch, valid=False),
        )

        self.assertIsNone(snapshot)


class TestRtiServiceMonitoringClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeDataReader.created = []
        FakeDataReader.samples_by_topic = {}
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        open(os.path.join(self.temp_dir.name, "ServiceMonitoring.xml"), "w", encoding="utf-8").close()
        self.qos_file = os.path.join(self.temp_dir.name, "DDS_QOS_PROFILES.xml")
        open(self.qos_file, "w", encoding="utf-8").close()
        self.config = RtiServiceMonitoringConfig(
            xml_types_dir=self.temp_dir.name,
            qos_file=self.qos_file,
            poll_interval_sec=0.01,
        )
        self.service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy", monitoring_domain_id=54)

    async def test_take_available_creates_three_monitoring_readers(self):
        client = RtiServiceMonitoringClient(self.config, FakeDdsModule)

        snapshots = await client.take_available(self.service)

        self.assertEqual(snapshots, [])
        self.assertEqual([reader.topic.name for reader in FakeDataReader.created], [
            MONITORING_CONFIG_TOPIC,
            MONITORING_EVENT_TOPIC,
            MONITORING_PERIODIC_TOPIC,
        ])
        self.assertEqual([reader.qos for reader in FakeDataReader.created], [
            f"reader:{CONFIG_QOS_PROFILE}",
            f"reader:{EVENT_QOS_PROFILE}",
            f"reader:{PERIODIC_QOS_PROFILE}",
        ])

    async def test_latest_snapshot_returns_last_available_snapshot(self):
        config_branch = SimpleNamespace(application_name="deploy")
        event_branch = SimpleNamespace(state=SimpleNamespace(value=5, name="RUNNING"))
        FakeDataReader.samples_by_topic = {
            MONITORING_CONFIG_TOPIC: [
                sample_for(RESOURCE_RECORDING_SERVICE, "recording_service", config_branch)
            ],
            MONITORING_EVENT_TOPIC: [
                sample_for(RESOURCE_RECORDING_SERVICE, "recording_service", event_branch)
            ],
        }
        client = RtiServiceMonitoringClient(self.config, FakeDdsModule)

        snapshot = await client.latest_snapshot(self.service)

        self.assertEqual(snapshot.kind, MonitoringSnapshotKind.EVENT)
        self.assertEqual(snapshot.state, "RUNNING")

    async def test_take_available_routes_drained_samples_to_matching_services(self):
        service_a = ServiceInstanceRef(ServiceKind.RECORDING, "recording_a", monitoring_domain_id=54)
        service_b = ServiceInstanceRef(ServiceKind.RECORDING, "recording_b", monitoring_domain_id=54)
        guid_a = [1] * 16
        guid_b = [2] * 16
        config_a = SimpleNamespace(
            application_name="recording_a",
            application_guid=SimpleNamespace(value=guid_a),
        )
        config_b = SimpleNamespace(
            application_name="recording_b",
            application_guid=SimpleNamespace(value=guid_b),
        )
        periodic_a = SimpleNamespace(
            builtin_sqlite=SimpleNamespace(current_file="a_0.db", current_file_size=10),
        )
        periodic_b = SimpleNamespace(
            builtin_sqlite=SimpleNamespace(current_file="b_0.db", current_file_size=20),
        )
        FakeDataReader.samples_by_topic = {
            MONITORING_CONFIG_TOPIC: [
                sample_for(
                    RESOURCE_RECORDING_SERVICE,
                    "recording_service",
                    config_a,
                    object_guid=guid_a,
                ),
                sample_for(
                    RESOURCE_RECORDING_SERVICE,
                    "recording_service",
                    config_b,
                    object_guid=guid_b,
                ),
            ],
            MONITORING_PERIODIC_TOPIC: [
                sample_for(
                    RESOURCE_RECORDING_SERVICE,
                    "recording_service",
                    periodic_a,
                    object_guid=guid_a,
                ),
                sample_for(
                    RESOURCE_RECORDING_SERVICE,
                    "recording_service",
                    periodic_b,
                    object_guid=guid_b,
                ),
            ],
        }
        client = RtiServiceMonitoringClient(self.config, FakeDdsModule)

        snapshots_a = await client.take_available(service_a)
        snapshots_b = await client.take_available(service_b)

        self.assertEqual([snapshot.service.name for snapshot in snapshots_a], ["recording_a", "recording_a"])
        self.assertEqual([snapshot.service.name for snapshot in snapshots_b], ["recording_b", "recording_b"])
        self.assertEqual(snapshots_a[-1].details["db_file"], "a_0.db")
        self.assertEqual(snapshots_b[-1].details["db_file"], "b_0.db")

    async def test_snapshots_yields_available_snapshots_in_reader_order(self):
        config_branch = SimpleNamespace(application_name="deploy")
        event_branch = SimpleNamespace(state=SimpleNamespace(value=6, name="PAUSED"))
        FakeDataReader.samples_by_topic = {
            MONITORING_CONFIG_TOPIC: [
                sample_for(RESOURCE_RECORDING_SERVICE, "recording_service", config_branch)
            ],
            MONITORING_EVENT_TOPIC: [
                sample_for(RESOURCE_RECORDING_SERVICE, "recording_service", event_branch)
            ],
        }
        client = RtiServiceMonitoringClient(self.config, FakeDdsModule)

        observed = []
        async for snapshot in client.snapshots(self.service):
            observed.append(snapshot)
            if len(observed) == 2:
                break

        self.assertEqual([snapshot.kind for snapshot in observed], [
            MonitoringSnapshotKind.CONFIG,
            MonitoringSnapshotKind.EVENT,
        ])

    async def test_close_releases_subscriber_and_participant(self):
        client = RtiServiceMonitoringClient(self.config, FakeDdsModule)

        await client.take_available(self.service)
        session = client._sessions[self.service.monitoring_domain_id]
        await client.close()

        self.assertTrue(session.subscriber.closed)
        self.assertTrue(session.participant.closed_contained)
        self.assertTrue(session.participant.closed)
        self.assertEqual(client._sessions, {})


if __name__ == "__main__":
    unittest.main()