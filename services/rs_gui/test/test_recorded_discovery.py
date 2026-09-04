"""Unit tests for the supported Recording Service 7.7 discovery reader."""

import os
import sqlite3
import sys
import tempfile
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core.recorded_discovery import RecordedDiscoverySchemaError, load_recorded_discovery


class TestRecordedDiscovery(unittest.TestCase):
    def _recording_directory(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = os.path.join(directory.name, "discovery.db")
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE DCPSParticipant (
                SampleInfo_reception_timestamp INTEGER, SampleInfo_valid_data INTEGER,
                ParticipantData_key BLOB, ParticipantData_participant_name STRING,
                ParticipantData_domain_id INTEGER, ParticipantData_property STRING
            );
            CREATE TABLE DCPSPublication AS SELECT
                0 AS SampleInfo_reception_timestamp, 0 AS SampleInfo_valid_data,
                X'' AS PublicationData_key, X'' AS PublicationData_participant_key,
                '' AS PublicationData_topic_name, '' AS PublicationData_type_name,
                0 AS PublicationData_reliability_kind, 0 AS PublicationData_durability_kind,
                0 AS PublicationData_deadline_period, 0 AS PublicationData_latency_budget_duration,
                0 AS PublicationData_liveliness_kind, 0 AS PublicationData_liveliness_lease_duration,
                0 AS PublicationData_ownership_kind, 0 AS PublicationData_destination_order_kind,
                0 AS PublicationData_presentation_access_scope, 0 AS PublicationData_presentation_coherent_access,
                0 AS PublicationData_presentation_ordered_access, '' AS PublicationData_partition,
                X'' AS PublicationData_rtps_vendor_id;
            CREATE TABLE DCPSSubscription AS SELECT
                0 AS SampleInfo_reception_timestamp, 0 AS SampleInfo_valid_data,
                X'' AS SubscriptionData_key, X'' AS SubscriptionData_participant_key,
                '' AS SubscriptionData_topic_name, '' AS SubscriptionData_type_name,
                0 AS SubscriptionData_reliability_kind, 0 AS SubscriptionData_durability_kind,
                0 AS SubscriptionData_deadline_period, 0 AS SubscriptionData_latency_budget_duration,
                0 AS SubscriptionData_liveliness_kind, 0 AS SubscriptionData_liveliness_lease_duration,
                0 AS SubscriptionData_ownership_kind, 0 AS SubscriptionData_destination_order_kind,
                0 AS SubscriptionData_presentation_access_scope, 0 AS SubscriptionData_presentation_coherent_access,
                0 AS SubscriptionData_presentation_ordered_access, '' AS SubscriptionData_partition,
                X'' AS SubscriptionData_rtps_vendor_id;
        """)
        connection.execute("INSERT INTO DCPSParticipant VALUES (?, ?, ?, ?, ?, ?)", (1, 1, b'participant', 'writer-app', 42, 'host=dev'))
        connection.execute("INSERT INTO DCPSPublication SELECT ?, ?, ?, ?, ?, ?, 1, 1, 10, 0, 0, 0, 1, 0, 0, 0, 0, '', X'0101'", (2, 1, b'writer', b'participant', 'Example', 'ExampleType'))
        connection.execute("INSERT INTO DCPSPublication SELECT ?, ?, ?, ?, ?, ?, 1, 1, 15, 0, 0, 0, 1, 0, 0, 0, 0, '', X'0101'", (5, 1, b'writer', b'participant', 'Example', 'ExampleType'))
        connection.execute("INSERT INTO DCPSPublication SELECT ?, ?, ?, ?, ?, ?, 1, 1, 10, 0, 0, 0, 1, 0, 0, 0, 0, '', X'0101'", (8, 0, b'writer', b'participant', 'Example', 'ExampleType'))
        connection.commit()
        connection.close()
        return directory.name

    def test_reconstructs_endpoint_lifetime_and_participant_metadata(self):
        discovery = load_recorded_discovery(self._recording_directory())

        self.assertEqual(discovery.domains, (42,))
        self.assertEqual(len(discovery.endpoints), 1)
        endpoint = discovery.endpoints[0]
        self.assertEqual(endpoint.key, "777269746572")
        self.assertEqual(endpoint.kind, "Writer")
        self.assertEqual(endpoint.domain_id, 42)
        self.assertEqual((endpoint.started_at_ns, endpoint.ended_at_ns), (2, 8))
        self.assertEqual(dict(endpoint.qos)["deadline_period"], 15)
        self.assertEqual(discovery.active_endpoints_at(7), (endpoint,))
        self.assertEqual(discovery.active_endpoints_at(8), ())

    def test_rejects_recording_without_supported_discovery_schema(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        sqlite3.connect(os.path.join(directory.name, "discovery.db")).close()

        with self.assertRaisesRegex(RecordedDiscoverySchemaError, "DCPSParticipant"):
            load_recorded_discovery(directory.name)


if __name__ == "__main__":
    unittest.main()