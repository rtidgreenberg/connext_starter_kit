#!/usr/bin/env python3
"""Pure unit tests for rs_gui_v2 subscription models and sample cache."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    SampleCache,
    SampleEnvelope,
    SampleInfoSnapshot,
    SubscriptionStatus,
    TopicSubscriptionRequest,
    TopicSubscriptionState,
)


class TestSubscriptionModels(unittest.TestCase):
    def test_subscription_request_round_trips_and_builds_stable_key(self):
        request = TopicSubscriptionRequest(
            domain_id="12",
            topic_name="Telemetry",
            type_name="TelemetryType",
            selected_fields=["x", "y"],
            max_samples="3",
            created_at=10.0,
        )

        self.assertEqual(request.domain_id, 12)
        self.assertEqual(request.selected_fields, ("x", "y"))
        self.assertEqual(request.max_samples, 3)
        self.assertEqual(request.key, "12:Telemetry:TelemetryType")
        self.assertEqual(request.request_id, request.key)
        self.assertEqual(TopicSubscriptionRequest.from_dict(request.to_dict()), request)

    def test_sample_info_and_envelope_round_trip(self):
        info = SampleInfoSnapshot(
            valid="",
            source_timestamp="12.5",
            reception_timestamp=13.0,
            instance_state="ALIVE",
            rank="2",
            native={"handle": "abc"},
        )
        sample = SampleEnvelope(
            subscription_key="12:Telemetry:TelemetryType",
            domain_id=12,
            topic_name="Telemetry",
            type_name="TelemetryType",
            data={"x": 1},
            info=info,
            observed_at=14.0,
        )

        self.assertFalse(info.valid)
        self.assertFalse(sample.valid)
        with self.assertRaises(TypeError):
            info.native["new"] = "blocked"
        self.assertEqual(SampleEnvelope.from_dict(sample.to_dict()), sample)

    def test_subscription_state_counts_valid_invalid_and_dropped_samples(self):
        request = TopicSubscriptionRequest(0, "Telemetry", "TelemetryType")
        valid = SampleEnvelope(request.key, 0, "Telemetry", "TelemetryType")
        invalid = SampleEnvelope(
            request.key,
            0,
            "Telemetry",
            "TelemetryType",
            info=SampleInfoSnapshot(valid=False),
        )

        state = TopicSubscriptionState(request).with_samples([valid, invalid], dropped_samples=2)

        self.assertEqual(state.status, SubscriptionStatus.RECEIVING)
        self.assertEqual(state.received_samples, 1)
        self.assertEqual(state.invalid_samples, 1)
        self.assertEqual(state.dropped_samples, 2)
        self.assertEqual(TopicSubscriptionState.from_dict(state.to_dict()), state)


class TestSampleCache(unittest.TestCase):
    def test_sample_cache_bounds_samples_and_counts_drops(self):
        request = TopicSubscriptionRequest(0, "Telemetry", "TelemetryType", max_samples=2)
        cache = SampleCache(default_max_samples=4)
        cache.configure(request)

        samples = [
            SampleEnvelope(request.key, 0, "Telemetry", "TelemetryType", data={"index": index})
            for index in range(4)
        ]
        dropped = cache.extend(samples)

        self.assertEqual(dropped, 2)
        self.assertEqual(cache.dropped_count(request.key), 2)
        self.assertEqual([sample.data["index"] for sample in cache.snapshot(request.key)], [2, 3])

        cache.clear(request.key)
        self.assertEqual(cache.snapshot(request.key), ())
        self.assertEqual(cache.dropped_count(request.key), 0)


if __name__ == "__main__":
    unittest.main()