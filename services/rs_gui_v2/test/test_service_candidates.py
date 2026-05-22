#!/usr/bin/env python3
"""Pure unit tests for composing service process candidates."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core.discovery import DiscoveredEndpoint, EndpointDirection
from app_core.services import (
    MonitoringSnapshot,
    MonitoringSnapshotKind,
    ServiceCandidateSource,
    ServiceControlIdentity,
    ServiceInstanceRef,
    ServiceKind,
    ServiceLaunchIntent,
    build_service_candidate_selection,
    candidate_from_control_identity,
    candidate_from_monitoring_snapshot,
    candidates_from_discovered_endpoints,
)


class TestCandidateComposition(unittest.TestCase):
    def test_control_identity_builds_owned_launch_candidate(self):
        identity = ServiceControlIdentity(
            intent=ServiceLaunchIntent(ServiceKind.RECORDING, "Record Main"),
            session_guid="11111111-2222-3333-4444-555555555555",
            created_at=1.0,
        )

        candidate = candidate_from_control_identity(
            identity,
            launch_id="launch-1",
            pid=100,
            hostname="dev-host",
            observed_state="STARTING",
        )

        self.assertEqual(candidate.candidate_id, "launch-1")
        self.assertEqual(candidate.service.name, "record_main_11111111")
        self.assertEqual(candidate.source, ServiceCandidateSource.GUI_LAUNCH)
        self.assertEqual(candidate.pid, 100)
        self.assertEqual(candidate.hostname, "dev-host")
        self.assertTrue(candidate.owns_process)
        self.assertEqual(candidate.details["session_guid"], identity.session_guid)

    def test_monitoring_snapshot_builds_candidate_with_process_identity(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "record_main_11111111")
        snapshot = MonitoringSnapshot(
            service=service,
            kind=MonitoringSnapshotKind.CONFIG,
            state="RUNNING",
            metrics={"cpu_percent": 2.0},
            details={
                "application_guid": "app-guid-1",
                "process_id": 100,
                "host_name": "dev-host",
            },
            observed_at=20.0,
        )

        candidate = candidate_from_monitoring_snapshot(snapshot, display_label="Record Main")

        self.assertTrue(candidate.candidate_id.startswith("monitoring:recording:"))
        self.assertEqual(candidate.source, ServiceCandidateSource.MONITORING)
        self.assertEqual(candidate.display_label, "Record Main")
        self.assertEqual(candidate.pid, 100)
        self.assertEqual(candidate.hostname, "dev-host")
        self.assertEqual(candidate.application_guid, "app-guid-1")
        self.assertEqual(candidate.observed_state, "RUNNING")
        self.assertEqual(candidate.metrics["cpu_percent"], 2.0)

    def test_discovery_endpoints_are_grouped_by_participant(self):
        service = ServiceInstanceRef(ServiceKind.REPLAY, "replay_aaaaaaaa")
        endpoints = (
            DiscoveredEndpoint(
                domain_id=0,
                topic_name="TopicA",
                type_name="A",
                direction=EndpointDirection.WRITER,
                endpoint_key="endpoint-1",
                participant_key="participant-1",
                participant_name="ReplayParticipant",
                participant_properties={
                    "dds.sys_info.hostname": "dev-host",
                    "dds.sys_info.process_id": "200",
                },
                observed_at=10.0,
            ),
            DiscoveredEndpoint(
                domain_id=0,
                topic_name="TopicB",
                type_name="B",
                direction=EndpointDirection.WRITER,
                endpoint_key="endpoint-2",
                participant_key="participant-1",
                participant_name="ReplayParticipant",
                participant_properties={
                    "dds.sys_info.hostname": "dev-host",
                    "dds.sys_info.process_id": "200",
                },
                observed_at=12.0,
            ),
        )

        candidates = candidates_from_discovered_endpoints(service, endpoints, display_label="Replay")

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.source, ServiceCandidateSource.DISCOVERY)
        self.assertEqual(candidate.pid, 200)
        self.assertEqual(candidate.hostname, "dev-host")
        self.assertEqual(candidate.participant_key, "participant-1")
        self.assertEqual(candidate.participant_name, "ReplayParticipant")
        self.assertEqual(candidate.details["endpoint_count"], 2)
        self.assertEqual(candidate.details["topic_names"], ["TopicA", "TopicB"])
        self.assertEqual(candidate.last_seen_at, 12.0)

    def test_selection_merges_launch_monitoring_and_discovery_by_host_pid(self):
        identity = ServiceControlIdentity(
            intent=ServiceLaunchIntent(ServiceKind.RECORDING, "Record Main"),
            session_guid="11111111-2222-3333-4444-555555555555",
            created_at=1.0,
        )
        launch_candidate = candidate_from_control_identity(
            identity,
            launch_id="launch-1",
            pid=100,
            hostname="dev-host",
            observed_state="STARTING",
            observed_at=1.0,
        )
        snapshot = MonitoringSnapshot(
            service=identity.service_ref,
            kind=MonitoringSnapshotKind.CONFIG,
            state="RUNNING",
            metrics={"memory_kb": 2048},
            details={
                "application_guid": "app-guid-1",
                "process_id": 100,
                "host_name": "dev-host",
            },
            observed_at=20.0,
        )
        endpoint = DiscoveredEndpoint(
            domain_id=0,
            topic_name="TopicA",
            type_name="A",
            direction=EndpointDirection.WRITER,
            endpoint_key="endpoint-1",
            participant_key="participant-1",
            participant_name="RecordingParticipant",
            participant_properties={
                "dds.sys_info.hostname": "dev-host",
                "dds.sys_info.process_id": "100",
            },
            observed_at=21.0,
        )

        selection = build_service_candidate_selection(
            identity.service_ref,
            launch_candidates=(launch_candidate,),
            monitoring_snapshots=(snapshot,),
            discovery_endpoints=(endpoint,),
            display_label="Record Main",
        )

        self.assertEqual(len(selection.candidates), 1)
        candidate = selection.selected_candidate
        self.assertEqual(candidate.candidate_id, "launch-1")
        self.assertEqual(candidate.observed_state, "discovered")
        self.assertEqual(candidate.metrics["memory_kb"], 2048)
        self.assertEqual(candidate.application_guid, "app-guid-1")
        self.assertEqual(candidate.participant_key, "participant-1")
        self.assertTrue(candidate.owns_process)
        self.assertEqual(candidate.details["evidence_sources"], [
            "discovery",
            "gui_launch",
            "monitoring",
        ])

    def test_unrelated_monitoring_snapshot_is_ignored(self):
        target = ServiceInstanceRef(ServiceKind.RECORDING, "record_main", admin_domain_id=0)
        other = ServiceInstanceRef(ServiceKind.RECORDING, "other", admin_domain_id=0)
        snapshot = MonitoringSnapshot(
            service=other,
            kind=MonitoringSnapshotKind.CONFIG,
            state="RUNNING",
            details={"process_id": 100, "host_name": "dev-host"},
        )

        selection = build_service_candidate_selection(target, monitoring_snapshots=(snapshot,))

        self.assertEqual(selection.candidates, ())


if __name__ == "__main__":
    unittest.main()
