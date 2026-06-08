#!/usr/bin/env python3
"""Fake-Connext tests for the rs_gui_v2 DynamicType field catalog adapter."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    FieldCatalogStatus,
    FieldCollectionKind,
    FieldScalarKind,
    TypeAvailabilityStatus,
    TypeResolution,
)
from app_core.rti_fields import RtiFieldCatalogClient, RtiFieldCatalogConfig


class FakeLookup:
    def __init__(self, resolution, dynamic_type=None):
        self.resolution = resolution
        self.dynamic_type = dynamic_type

    @property
    def available(self):
        return self.resolution.available and self.dynamic_type is not None


class FakeTypeRegistry:
    def __init__(self, lookups):
        self.lookups = dict(lookups)
        self.requests = []

    def lookup(self, type_name):
        self.requests.append(type_name)
        return self.lookups.get(type_name, FakeLookup(TypeResolution(
            type_name=type_name,
            status=TypeAvailabilityStatus.MISSING,
            message="missing type",
        )))


class FakeMember:
    def __init__(self, name, member_type, optional=False, is_key=False):
        self.name = name
        self.type = member_type
        self.optional = optional
        self.is_key = is_key


class FakeType:
    def __init__(
            self,
            kind,
            name="",
            members=(),
            bounds=None,
            content_type=None,
    ):
        self.kind = kind
        self._name = name
        self._members = tuple(members)
        self._bounds = bounds
        self._content_type = content_type

    @property
    def name(self):
        if not self._name:
            raise RuntimeError("primitive types do not expose names")
        return self._name

    @property
    def member_count(self):
        return len(self._members)

    def member(self, index):
        return self._members[index]

    @property
    def bounds(self):
        if self._bounds is None:
            raise RuntimeError("bounds are not available")
        return self._bounds

    @property
    def content_type(self):
        if self._content_type is None:
            raise RuntimeError("content type is not available")
        return self._content_type


class TestRtiFieldCatalogClient(unittest.TestCase):
    def test_catalog_walks_nested_dynamic_type_members(self):
        telemetry_type = self._telemetry_type()
        client = RtiFieldCatalogClient(type_registry=FakeTypeRegistry({
            "Telemetry": FakeLookup(TypeResolution(
                type_name="Telemetry",
                status=TypeAvailabilityStatus.AVAILABLE,
                candidates=("Telemetry",),
            ), telemetry_type),
        }))

        catalog = client.catalog_for("Telemetry")

        self.assertTrue(catalog.available)
        self.assertEqual(catalog.type_name, "Telemetry")
        self.assertEqual([field.path for field in catalog.plottable_fields()], [
            "id",
            "pose.position.x",
            "pose.position.y",
        ])
        self.assertEqual(catalog.descriptor("pose").children, ("pose.position", "pose.valid"))
        self.assertEqual(catalog.descriptor("label").collection_kind, FieldCollectionKind.STRING)
        self.assertEqual(catalog.descriptor("label").bounds, (64,))
        self.assertEqual(catalog.descriptor("status").scalar_kind, FieldScalarKind.ENUM)
        self.assertEqual(catalog.descriptor("ranges").collection_kind, FieldCollectionKind.SEQUENCE)
        self.assertFalse(catalog.descriptor("ranges").plottable)

    def test_catalog_walks_union_members_as_inspectable_variants(self):
        union_type = FakeType("UNION_TYPE", "Mode", (
            FakeMember("manual", FakeType("STRUCTURE_TYPE", "ManualMode", (
                FakeMember("speed", FakeType("FLOAT_32_TYPE")),
            ))),
            FakeMember("automatic", FakeType("STRUCTURE_TYPE", "AutoMode", (
                FakeMember("enabled", FakeType("BOOLEAN_TYPE")),
            ))),
        ))
        client = RtiFieldCatalogClient(type_registry=self._registry_for("Mode", union_type))

        catalog = client.catalog_for("Mode")

        self.assertEqual([field.path for field in catalog.fields], [
            "manual",
            "manual.speed",
            "automatic",
            "automatic.enabled",
        ])
        self.assertEqual([field.path for field in catalog.plottable_fields()], ["manual.speed"])

    def test_unresolved_type_returns_unavailable_catalog(self):
        client = RtiFieldCatalogClient(type_registry=FakeTypeRegistry({}))

        catalog = client.catalog_for("Missing")

        self.assertEqual(catalog.status, FieldCatalogStatus.TYPE_UNAVAILABLE)
        self.assertIn("missing type", catalog.message)
        self.assertEqual(catalog.fields, ())

    def test_depth_limit_keeps_parent_without_deep_children(self):
        client = RtiFieldCatalogClient(
            type_registry=self._registry_for("Telemetry", self._telemetry_type()),
            config=RtiFieldCatalogConfig(max_depth=1),
        )

        catalog = client.catalog_for("Telemetry")

        self.assertIsNotNone(catalog.descriptor("pose.position"))
        self.assertIsNone(catalog.descriptor("pose.position.x"))

    def test_collection_content_traversal_is_explicit(self):
        point_type = FakeType("STRUCTURE_TYPE", "Point", (
            FakeMember("x", FakeType("FLOAT_64_TYPE")),
        ))
        cloud_type = FakeType("STRUCTURE_TYPE", "Cloud", (
            FakeMember("points", FakeType("SEQUENCE_TYPE", bounds=16, content_type=point_type)),
        ))

        default_catalog = RtiFieldCatalogClient(type_registry=self._registry_for("Cloud", cloud_type)).catalog_for("Cloud")
        expanded_catalog = RtiFieldCatalogClient(
            type_registry=self._registry_for("Cloud", cloud_type),
            config=RtiFieldCatalogConfig(include_collection_content=True),
        ).catalog_for("Cloud")

        self.assertIsNone(default_catalog.descriptor("points.x"))
        self.assertIsNotNone(expanded_catalog.descriptor("points.x"))
        self.assertFalse(expanded_catalog.descriptor("points").plottable)

    def _registry_for(self, type_name, dynamic_type):
        return FakeTypeRegistry({
            type_name: FakeLookup(TypeResolution(
                type_name=type_name,
                status=TypeAvailabilityStatus.AVAILABLE,
                candidates=(type_name,),
            ), dynamic_type),
        })

    def _telemetry_type(self):
        position_type = FakeType("STRUCTURE_TYPE", "Position", (
            FakeMember("x", FakeType("FLOAT_64_TYPE")),
            FakeMember("y", FakeType("FLOAT_64_TYPE")),
        ))
        pose_type = FakeType("STRUCTURE_TYPE", "Pose", (
            FakeMember("position", position_type),
            FakeMember("valid", FakeType("BOOLEAN_TYPE"), optional=True),
        ))
        return FakeType("STRUCTURE_TYPE", "Telemetry", (
            FakeMember("id", FakeType("INT_32_TYPE"), is_key=True),
            FakeMember("label", FakeType("STRING_TYPE", bounds=64)),
            FakeMember("pose", pose_type),
            FakeMember("status", FakeType("ENUMERATION_TYPE", "Status")),
            FakeMember("ranges", FakeType(
                "SEQUENCE_TYPE",
                bounds=256,
                content_type=FakeType("FLOAT_32_TYPE"),
            )),
        ))


if __name__ == "__main__":
    unittest.main()