#!/usr/bin/env python3
"""Pure unit tests for rs_gui field catalog models."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    FieldCatalog,
    FieldCatalogStatus,
    FieldCollectionKind,
    FieldDescriptor,
    FieldScalarKind,
    field_catalog_from_descriptors,
)


class TestFieldModels(unittest.TestCase):
    def test_descriptor_properties_and_round_trip(self):
        descriptor = FieldDescriptor(
            path="pose.position.x",
            name="x",
            type_name="float64",
            type_kind="float64",
            scalar_kind=FieldScalarKind.FLOAT,
            parent_path="pose.position",
            depth=2,
            optional=True,
        )

        self.assertTrue(descriptor.leaf)
        self.assertTrue(descriptor.numeric)
        self.assertTrue(descriptor.plottable)
        self.assertEqual(FieldDescriptor.from_dict(descriptor.to_dict()), descriptor)

    def test_collection_descriptor_is_not_plottable(self):
        descriptor = FieldDescriptor(
            path="ranges",
            name="ranges",
            type_name="float32",
            scalar_kind=FieldScalarKind.FLOAT,
            collection_kind=FieldCollectionKind.SEQUENCE,
            bounds=(128,),
        )

        self.assertTrue(descriptor.collection)
        self.assertFalse(descriptor.plottable)
        self.assertEqual(FieldDescriptor.from_dict(descriptor.to_dict()).bounds, (128,))

    def test_catalog_populates_children_and_filters_plottable_fields(self):
        catalog = field_catalog_from_descriptors(
            "Telemetry",
            (
                FieldDescriptor(
                    path="pose",
                    name="pose",
                    type_name="Pose",
                    scalar_kind=FieldScalarKind.STRUCT,
                ),
                FieldDescriptor(
                    path="pose.x",
                    name="x",
                    type_name="float32",
                    scalar_kind=FieldScalarKind.FLOAT,
                    parent_path="pose",
                    depth=1,
                ),
                FieldDescriptor(
                    path="label",
                    name="label",
                    type_name="string",
                    scalar_kind=FieldScalarKind.TEXT,
                    collection_kind=FieldCollectionKind.STRING,
                ),
            ),
        )

        self.assertTrue(catalog.available)
        self.assertEqual(catalog.descriptor("pose").children, ("pose.x",))
        self.assertEqual([field.path for field in catalog.leaf_fields()], ["pose.x", "label"])
        self.assertEqual([field.path for field in catalog.plottable_fields()], ["pose.x"])
        self.assertEqual(FieldCatalog.from_dict(catalog.to_dict()), catalog)

    def test_unavailable_catalog_round_trips(self):
        catalog = FieldCatalog(
            type_name="MissingType",
            status=FieldCatalogStatus.TYPE_UNAVAILABLE,
            message="type is not available",
        )

        self.assertFalse(catalog.available)
        self.assertIsNone(catalog.descriptor("x"))
        self.assertEqual(FieldCatalog.from_dict(catalog.to_dict()), catalog)


if __name__ == "__main__":
    unittest.main()