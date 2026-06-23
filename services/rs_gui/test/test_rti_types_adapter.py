#!/usr/bin/env python3
"""Fake-Connext tests for the rs_gui RTI type registry adapter."""

import os
import shutil
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
TEST_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "test_output", "rti_types")
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import TypeAvailabilityStatus
from app_core.rti_types import RtiTypeRegistry, RtiTypeRegistryConfig


class FakeDynamicType:
    def __init__(self, name):
        self.name = name


class FakeProvider:
    def __init__(self, path, type_map, failures):
        self.path = os.path.abspath(path)
        self.type_map = type_map
        self.failures = failures
        self.lookups = []

    def type(self, type_name):
        self.lookups.append(type_name)
        if type_name in self.failures:
            raise RuntimeError(f"cannot load {type_name}")
        try:
            return self.type_map[self.path][type_name]
        except KeyError as exc:
            raise RuntimeError(f"missing {type_name}") from exc


class FakeDdsModule:
    def __init__(self, type_map, failures=()):
        self.type_map = type_map
        self.failures = set(failures)
        self.providers = []

    def QosProvider(self, path):
        provider = FakeProvider(path, self.type_map, self.failures)
        self.providers.append(provider)
        return provider


class TestRtiTypeRegistry(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TEST_OUTPUT_DIR, ignore_errors=True)
        os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)
        self.service_xml = os.path.join(TEST_OUTPUT_DIR, "ServiceAdmin.xml")
        self.monitoring_xml = os.path.join(TEST_OUTPUT_DIR, "ServiceMonitoring.xml")
        self._write_xml(self.service_xml, """
        <dds>
          <types>
            <module name="RTI">
              <module name="Service">
                <module name="Admin">
                  <struct name="CommandRequest"/>
                  <struct name="CommandReply"/>
                </module>
              </module>
            </module>
          </types>
        </dds>
        """)
        self._write_xml(self.monitoring_xml, """
        <dds>
          <types>
            <module name="RTI">
              <module name="Service">
                <module name="Monitoring">
                  <struct name="Periodic"/>
                </module>
              </module>
            </module>
          </types>
        </dds>
        """)

    def tearDown(self):
        shutil.rmtree(TEST_OUTPUT_DIR, ignore_errors=True)

    def test_catalog_loads_sources_from_configured_xml_files(self):
        registry = self._registry()

        catalog = registry.catalog()

        self.assertEqual(
            [source.type_name for source in catalog.registered_types()],
            [
                "RTI::Service::Admin::CommandReply",
                "RTI::Service::Admin::CommandRequest",
                "RTI::Service::Monitoring::Periodic",
            ],
        )
        self.assertEqual(catalog.resolve("CommandRequest").source,
                         os.path.abspath(self.service_xml))

    def test_lookup_returns_dynamic_type_for_exact_and_short_names(self):
        command_type = FakeDynamicType("RTI::Service::Admin::CommandRequest")
        periodic_type = FakeDynamicType("RTI::Service::Monitoring::Periodic")
        dds = FakeDdsModule({
            os.path.abspath(self.service_xml): {
                "RTI::Service::Admin::CommandRequest": command_type,
            },
            os.path.abspath(self.monitoring_xml): {
                "RTI::Service::Monitoring::Periodic": periodic_type,
            },
        })
        registry = self._registry(dds)

        exact = registry.lookup("RTI::Service::Admin::CommandRequest")
        short = registry.lookup("Periodic")

        self.assertTrue(exact.available)
        self.assertIs(exact.dynamic_type, command_type)
        self.assertTrue(short.available)
        self.assertIs(short.dynamic_type, periodic_type)
        self.assertEqual(short.resolution.resolved_type_name,
                         "RTI::Service::Monitoring::Periodic")

    def test_lookup_reports_missing_catalog_type_without_creating_provider(self):
        dds = FakeDdsModule({})
        registry = self._registry(dds)

        lookup = registry.lookup("MissingType")

        self.assertFalse(lookup.available)
        self.assertEqual(lookup.resolution.status, TypeAvailabilityStatus.MISSING)
        self.assertEqual(dds.providers, [])

    def test_lookup_reports_provider_load_failure(self):
        dds = FakeDdsModule({
            os.path.abspath(self.service_xml): {},
            os.path.abspath(self.monitoring_xml): {},
        }, failures={"RTI::Service::Admin::CommandRequest"})
        registry = self._registry(dds)

        lookup = registry.lookup("CommandRequest")

        self.assertFalse(lookup.available)
        self.assertEqual(lookup.resolution.status, TypeAvailabilityStatus.MISSING)
        self.assertIn("Connext failed to load DynamicType", lookup.resolution.message)

    def test_missing_configured_xml_file_is_reported(self):
        registry = RtiTypeRegistry(
            config=RtiTypeRegistryConfig(
                xml_types_dir=TEST_OUTPUT_DIR,
                xml_files=("Missing.xml",),
            ),
            dds_module=FakeDdsModule({}),
        )

        with self.assertRaises(FileNotFoundError):
            registry.catalog()

    def _registry(self, dds_module=None):
        return RtiTypeRegistry(
            config=RtiTypeRegistryConfig(
                xml_types_dir=TEST_OUTPUT_DIR,
                xml_files=("ServiceAdmin.xml", "ServiceMonitoring.xml"),
            ),
            dds_module=dds_module or FakeDdsModule({}),
        )

    @staticmethod
    def _write_xml(path, text):
        with open(path, "w", encoding="utf-8") as xml_file:
            xml_file.write(text)


if __name__ == "__main__":
    unittest.main()