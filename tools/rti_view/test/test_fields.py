#!/usr/bin/env python3
"""Field catalog tests for rti_view."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
if TEST_DIR not in sys.path:
    sys.path.insert(0, TEST_DIR)

import rti.connextdds as dds

from rti_view.fields import enumerate_fields, enumerate_sample_fields, format_sample_items, get_field_value, is_scalar_numeric
from fakes import FakeDynamicType, FakeMember


class FakeSample:
    def __init__(self, values):
        self._values = dict(values)

    def __getitem__(self, field_path):
        return self.get_value(field_path)

    def get_value(self, field_path):
        value = self
        for part in field_path.split("."):
            value = value._values[part] if isinstance(value, FakeSample) else value[part]
        return value

    def items(self):
        return self._values.items()


class TestFields(unittest.TestCase):
    def test_enumerates_nested_fake_type(self):
        position = FakeDynamicType("STRUCTURE_TYPE", "Position", (
            FakeMember("x", FakeDynamicType("FLOAT_64_TYPE")),
            FakeMember("y", FakeDynamicType("FLOAT_64_TYPE")),
        ))
        telemetry = FakeDynamicType("STRUCTURE_TYPE", "Telemetry", (
            FakeMember("position", position),
            FakeMember("label", FakeDynamicType("STRING_TYPE")),
        ))

        fields = enumerate_fields(telemetry)

        self.assertEqual([field.path for field in fields], ["position.x", "position.y", "label"])
        self.assertEqual([field.path for field in fields if field.plottable], ["position.x", "position.y"])

    def test_constructed_connext_type_and_dot_path_read(self):
        position = dds.StructType("Position")
        position.add_member(dds.Member("x", dds.Float64Type()))
        position.add_member(dds.Member("y", dds.Float64Type()))
        telemetry = dds.StructType("Telemetry")
        telemetry.add_member(dds.Member("position", position))
        telemetry.add_member(dds.Member("id", dds.Int32Type()))

        fields = enumerate_fields(telemetry)
        sample = dds.DynamicData(telemetry)
        sample["position.x"] = 1.25
        sample["id"] = 7

        self.assertEqual([field.path for field in fields], ["position.x", "position.y", "id"])
        self.assertEqual(get_field_value(sample, "position.x"), 1.25)
        self.assertEqual(get_field_value(sample, "id"), 7)

    def test_plottability(self):
        self.assertTrue(is_scalar_numeric("TypeKind.FLOAT_64_TYPE"))
        self.assertTrue(is_scalar_numeric("TypeKind.INT_32_TYPE"))
        self.assertFalse(is_scalar_numeric("TypeKind.STRING_TYPE"))
        self.assertFalse(is_scalar_numeric("TypeKind.ENUMERATION_TYPE"))

    def test_enumerates_fields_from_sample_items(self):
        sample = FakeSample({
            "x": 42,
            "label": "active",
            "pose": FakeSample({"y": 9.5}),
        })

        fields = enumerate_sample_fields(sample)

        self.assertEqual([field.path for field in fields], ["x", "label", "pose.y"])
        self.assertEqual([field.path for field in fields if field.plottable], ["x", "pose.y"])
        self.assertEqual(get_field_value(sample, "pose.y"), 9.5)
        self.assertEqual(format_sample_items(sample), ["x = 42", "label = 'active'", "pose:", "pose.y = 9.5"])

    def test_enumerates_collection_fields_from_sample_items(self):
        sample = FakeSample({
            "samples": [
                FakeSample({"value": 1.25}),
                FakeSample({"value": 2.5}),
            ],
            "counts": [3, 4],
        })

        fields = enumerate_sample_fields(sample)

        self.assertEqual(
            [field.path for field in fields],
            ["samples[0].value", "samples[1].value", "counts[0]", "counts[1]"],
        )
        self.assertEqual(
            format_sample_items(sample),
            [
                "samples:",
                "samples[0]:",
                "samples[0].value = 1.25",
                "samples[1]:",
                "samples[1].value = 2.5",
                "counts:",
                "counts[0] = 3",
                "counts[1] = 4",
            ],
        )


if __name__ == "__main__":
    unittest.main()
