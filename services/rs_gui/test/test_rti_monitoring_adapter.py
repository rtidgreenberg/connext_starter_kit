#!/usr/bin/env python3
"""Unit tests for the rs_gui RTI service monitoring adapter."""

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
    RESOURCE_REPLAY_SERVICE,
    RESOURCE_REPLAY_TOPIC,
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
            resource_id="/recording_services/deploy",
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
        self.assertEqual(snapshot.details["resource_id"], "/recording_services/deploy")
        self.assertEqual(snapshot.details["admin_resource_name"], "deploy")

    def test_replay_config_service_sample_normalizes_details(self):
        service = ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_replay_1234", monitoring_domain_id=54)
        branch = SimpleNamespace(
            resource_id="/replay_services/xcdr",
            application_name="rs_gui_replay_1234",
            application_guid=SimpleNamespace(value=[15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]),
            process=SimpleNamespace(id=7007),
            host=SimpleNamespace(name="dev-host", id=7, target="x64Linux4gcc8.5.0"),
            builtin_sqlite=SimpleNamespace(db_directory="log_dir/recording_1780085154"),
        )
        snapshot = normalize_monitoring_sample(
            service,
            MonitoringSnapshotKind.CONFIG,
            sample_for(RESOURCE_REPLAY_SERVICE, "recording_service", branch),
        )

        self.assertEqual(snapshot.service.kind, ServiceKind.REPLAY)
        self.assertEqual(snapshot.kind, MonitoringSnapshotKind.CONFIG)
        self.assertEqual(snapshot.state, "configured")
        self.assertEqual(snapshot.details["service_name"], "rs_gui_replay_1234")
        self.assertEqual(snapshot.details["admin_resource_name"], "xcdr")
        self.assertEqual(snapshot.details["resource_id"], "/replay_services/xcdr")
        self.assertEqual(snapshot.details["process_id"], 7007)
        self.assertEqual(snapshot.details["db_directory"], "log_dir/recording_1780085154")

    def test_config_topic_sample_normalizes_topic_name(self):
        branch = SimpleNamespace(resource_id="/recording_services/deploy/sessions/Default/topics/Position", topic_name="Position")
        snapshot = normalize_monitoring_sample(
            self.service,
            MonitoringSnapshotKind.CONFIG,
            sample_for(RESOURCE_RECORDING_TOPIC, "recording_topic", branch),
        )

        self.assertEqual(snapshot.details["topics"], ["Position"])
        self.assertEqual(snapshot.details["resource_id"], "/recording_services/deploy/sessions/Default/topics/Position")

    def test_replay_config_topic_sample_normalizes_topic_name(self):
        service = ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_replay_1234", monitoring_domain_id=54)
        branch = SimpleNamespace(
            resource_id="/replay_services/xcdr/sessions/DefaultSession/topics/DefaultTopicGroup@Square",
            topic_name="Square",
        )
        snapshot = normalize_monitoring_sample(
            service,
            MonitoringSnapshotKind.CONFIG,
            sample_for(RESOURCE_REPLAY_TOPIC, "recording_topic", branch),
        )

        self.assertEqual(snapshot.service.kind, ServiceKind.REPLAY)
        self.assertEqual(snapshot.details["topics"], ["Square"])
        self.assertEqual(snapshot.details["admin_resource_name"], "xcdr")

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

    def test_replay_event_sample_normalizes_state(self):
        service = ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_replay_1234", monitoring_domain_id=54)
        branch = SimpleNamespace(
            state=SimpleNamespace(value=3, name="STARTED"),
            builtin_sqlite=SimpleNamespace(
                current_db_directory=None,
                current_file=None,
                rollover_count=None,
            ),
        )
        snapshot = normalize_monitoring_sample(
            service,
            MonitoringSnapshotKind.EVENT,
            sample_for(RESOURCE_REPLAY_SERVICE, "recording_service", branch),
        )

        self.assertEqual(snapshot.service.kind, ServiceKind.REPLAY)
        self.assertEqual(snapshot.state, "STARTED")
        self.assertEqual(snapshot.details["state_int"], 3)

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

    def test_replay_periodic_sample_normalizes_metrics(self):
        service = ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_replay_1234", monitoring_domain_id=54)
        branch = SimpleNamespace(
            process=SimpleNamespace(
                uptime_sec=2,
                cpu_usage_percentage=metric(82.8),
                physical_memory_kb=metric(72536),
            ),
            builtin_sqlite=SimpleNamespace(
                current_file=None,
                current_file_size=None,
            ),
        )
        snapshot = normalize_monitoring_sample(
            service,
            MonitoringSnapshotKind.PERIODIC,
            sample_for(RESOURCE_REPLAY_SERVICE, "recording_service", branch),
        )

        self.assertEqual(snapshot.service.kind, ServiceKind.REPLAY)
        self.assertEqual(snapshot.state, "observed")
        self.assertEqual(snapshot.metrics["uptime_sec"], 2)
        self.assertEqual(snapshot.metrics["cpu_percent"], 82.8)
        self.assertEqual(snapshot.metrics["memory_kb"], 72536)

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

    async def test_take_available_routes_replay_samples_to_matching_services(self):
        service_a = ServiceInstanceRef(ServiceKind.REPLAY, "replay_a", monitoring_domain_id=54)
        service_b = ServiceInstanceRef(ServiceKind.REPLAY, "replay_b", monitoring_domain_id=54)
        guid_a = [3] * 16
        guid_b = [4] * 16
        config_a = SimpleNamespace(
            resource_id="/replay_services/xcdr",
            application_name="replay_a",
            application_guid=SimpleNamespace(value=guid_a),
        )
        config_b = SimpleNamespace(
            resource_id="/replay_services/json",
            application_name="replay_b",
            application_guid=SimpleNamespace(value=guid_b),
        )
        periodic_a = SimpleNamespace(
            builtin_sqlite=SimpleNamespace(current_file="", current_file_size=10),
        )
        periodic_b = SimpleNamespace(
            builtin_sqlite=SimpleNamespace(current_file="", current_file_size=20),
        )
        FakeDataReader.samples_by_topic = {
            MONITORING_CONFIG_TOPIC: [
                sample_for(
                    RESOURCE_REPLAY_SERVICE,
                    "recording_service",
                    config_a,
                    object_guid=guid_a,
                ),
                sample_for(
                    RESOURCE_REPLAY_SERVICE,
                    "recording_service",
                    config_b,
                    object_guid=guid_b,
                ),
            ],
            MONITORING_PERIODIC_TOPIC: [
                sample_for(
                    RESOURCE_REPLAY_SERVICE,
                    "recording_service",
                    periodic_a,
                    object_guid=guid_a,
                ),
                sample_for(
                    RESOURCE_REPLAY_SERVICE,
                    "recording_service",
                    periodic_b,
                    object_guid=guid_b,
                ),
            ],
        }
        client = RtiServiceMonitoringClient(self.config, FakeDdsModule)

        snapshots_a = await client.take_available(service_a)
        snapshots_b = await client.take_available(service_b)

        self.assertEqual([snapshot.service.name for snapshot in snapshots_a], ["replay_a", "replay_a"])
        self.assertEqual([snapshot.service.name for snapshot in snapshots_b], ["replay_b", "replay_b"])
        self.assertEqual(snapshots_a[0].details["admin_resource_name"], "xcdr")
        self.assertEqual(snapshots_b[0].details["admin_resource_name"], "json")
        self.assertEqual(snapshots_a[-1].metrics["db_file_size"], 10)
        self.assertEqual(snapshots_b[-1].metrics["db_file_size"], 20)

    async def test_take_available_does_not_drain_replay_samples_into_recording_probe(self):
        recording_probe = ServiceInstanceRef(ServiceKind.RECORDING, "", monitoring_domain_id=54)
        replay_service = ServiceInstanceRef(ServiceKind.REPLAY, "replay_a", monitoring_domain_id=54)
        guid = [7] * 16
        config_branch = SimpleNamespace(
            resource_id="/replay_services/xcdr",
            application_name="replay_a",
            application_guid=SimpleNamespace(value=guid),
        )
        periodic_branch = SimpleNamespace(
            builtin_sqlite=SimpleNamespace(current_file="", current_file_size=10),
        )
        FakeDataReader.samples_by_topic = {
            MONITORING_CONFIG_TOPIC: [
                sample_for(
                    RESOURCE_REPLAY_SERVICE,
                    "recording_service",
                    config_branch,
                    object_guid=guid,
                ),
            ],
            MONITORING_PERIODIC_TOPIC: [
                sample_for(
                    RESOURCE_REPLAY_SERVICE,
                    "recording_service",
                    periodic_branch,
                    object_guid=guid,
                ),
            ],
        }
        client = RtiServiceMonitoringClient(self.config, FakeDdsModule)

        recording_snapshots = await client.take_available(recording_probe)
        replay_snapshots = await client.take_available(replay_service)

        self.assertEqual(recording_snapshots, [])
        self.assertEqual([snapshot.service.kind for snapshot in replay_snapshots], [ServiceKind.REPLAY, ServiceKind.REPLAY])
        self.assertEqual([snapshot.service.name for snapshot in replay_snapshots], ["replay_a", "replay_a"])
        self.assertEqual(replay_snapshots[0].details["admin_resource_name"], "xcdr")

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