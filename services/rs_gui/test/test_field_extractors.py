#!/usr/bin/env python3
"""Pure unit tests for rs_gui field-path extraction."""

import os
import sys
import unittest
import math


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    FieldExtraction,
    FieldExtractionStatus,
    FieldPath,
    FieldValueKind,
    SampleEnvelope,
    SampleInfoSnapshot,
    extract_field,
    extract_fields,
)


class ObjectSample:
    def __init__(self):
        self.pose = ObjectValue(position=ObjectValue(x=1.25, y=-2.5))
        self.label = "robot-a"


class ObjectValue:
    def __init__(self, **values):
        self.__dict__.update(values)


class DynamicLike:
    def __init__(self, values):
        self._values = dict(values)

    def __getitem__(self, key):
        return self._values[key]


class TestFieldPath(unittest.TestCase):
    def test_field_path_parses_nested_members_and_indexes(self):
        path = FieldPath.parse("tracks[2].position.x")

        self.assertEqual([step.to_text() for step in path.steps], ["tracks[2]", "position", "x"])
        self.assertEqual(FieldPath.from_dict(path.to_dict()), path)

    def test_invalid_path_returns_invalid_result(self):
        for path in ("", "pose..x", "tracks[].x", "[0]", "track[0]id"):
            with self.subTest(path=path):
                result = extract_field({"x": 1}, path)

                self.assertEqual(result.status, FieldExtractionStatus.INVALID_PATH)
                self.assertTrue(result.message)


class TestExtractField(unittest.TestCase):
    def test_extracts_nested_mapping_and_classifies_numeric_text_and_bool(self):
        data = {
            "pose": {"position": {"x": 1.5}, "valid": True},
            "label": "robot-a",
        }

        numeric = extract_field(data, "pose.position.x")
        boolean = extract_field(data, "pose.valid")
        text = extract_field(data, "label")

        self.assertEqual(numeric.value, 1.5)
        self.assertEqual(numeric.kind, FieldValueKind.NUMERIC)
        self.assertTrue(numeric.numeric)
        self.assertEqual(boolean.kind, FieldValueKind.BOOLEAN)
        self.assertFalse(boolean.numeric)
        self.assertEqual(text.kind, FieldValueKind.TEXT)

    def test_extracts_object_attributes(self):
        result = extract_field(ObjectSample(), "pose.position.y")

        self.assertTrue(result.found)
        self.assertEqual(result.value, -2.5)
        self.assertEqual(result.kind, FieldValueKind.NUMERIC)

    def test_extracts_dynamic_data_like_items(self):
        sample = DynamicLike({
            "pose": DynamicLike({
                "position": DynamicLike({"x": 7}),
            }),
        })

        result = extract_field(sample, "pose.position.x")

        self.assertEqual(result.value, 7)
        self.assertEqual(result.kind, FieldValueKind.NUMERIC)

    def test_extracts_sequence_index_and_classifies_sequence(self):
        data = {"tracks": [{"id": 1}, {"id": 2}], "ranges": [1.0, 2.0]}

        indexed = extract_field(data, "tracks[1].id")
        sequence = extract_field(data, "ranges")

        self.assertEqual(indexed.value, 2)
        self.assertEqual(indexed.kind, FieldValueKind.NUMERIC)
        self.assertEqual(sequence.kind, FieldValueKind.SEQUENCE)
        self.assertFalse(sequence.numeric)

    def test_missing_and_null_fields_are_distinct(self):
        data = {"optional": None}

        null = extract_field(data, "optional")
        missing = extract_field(data, "missing")

        self.assertEqual(null.status, FieldExtractionStatus.FOUND)
        self.assertEqual(null.kind, FieldValueKind.NULL)
        self.assertEqual(missing.status, FieldExtractionStatus.MISSING)
        self.assertEqual(missing.kind, FieldValueKind.MISSING)

    def test_non_finite_float_is_not_numeric(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                result = extract_field({"x": value}, "x")

                self.assertTrue(result.found)
                self.assertEqual(result.kind, FieldValueKind.OBJECT)
                self.assertFalse(result.numeric)

    def test_round_trip_extraction_result(self):
        result = extract_field({"x": 3}, "x")

        self.assertEqual(FieldExtraction.from_dict(result.to_dict()), result)


class TestExtractFieldsFromEnvelope(unittest.TestCase):
    def test_extracts_multiple_fields_from_valid_envelope(self):
        sample = SampleEnvelope(
            subscription_key="0:Telemetry:TelemetryType",
            domain_id=0,
            topic_name="Telemetry",
            type_name="TelemetryType",
            data={"pose": {"x": 1, "y": 2}, "label": "alpha"},
        )

        results = extract_fields(sample, ("pose.x", "pose.y", "label"))

        self.assertEqual([result.value for result in results], [1, 2, "alpha"])
        self.assertEqual([result.kind for result in results], [
            FieldValueKind.NUMERIC,
            FieldValueKind.NUMERIC,
            FieldValueKind.TEXT,
        ])

    def test_invalid_sample_returns_invalid_for_each_selected_field(self):
        sample = SampleEnvelope(
            subscription_key="0:Telemetry:TelemetryType",
            domain_id=0,
            topic_name="Telemetry",
            type_name="TelemetryType",
            data={"pose": {"x": 1}},
            info=SampleInfoSnapshot(valid=False),
        )

        results = extract_fields(sample, ("pose.x", "pose.y"))

        self.assertEqual([result.status for result in results], [
            FieldExtractionStatus.INVALID_SAMPLE,
            FieldExtractionStatus.INVALID_SAMPLE,
        ])
        self.assertEqual([result.message for result in results], [
            "sample is invalid",
            "sample is invalid",
        ])


if __name__ == "__main__":
    unittest.main()