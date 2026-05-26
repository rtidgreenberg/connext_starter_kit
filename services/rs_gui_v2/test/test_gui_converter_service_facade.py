#!/usr/bin/env python3
"""Tests for live Converter Service facade integration."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core.services import ServiceInstanceRef, ServiceKind
from gui.tabs.convert_service_facade import ConverterServiceFacade, ConverterServiceConfig
from gui.tabs.convert_controller import ConvertTabController, ConvertTabControllerConfig
from gui.tabs.convert_tab import ConvertPresetView


class TestConverterServiceFacade(unittest.TestCase):
    def test_facade_initializes_without_service(self):
        facade = ConverterServiceFacade()

        self.assertIsNone(facade.service)

    def test_facade_accepts_optional_service_ref(self):
        service_ref = ServiceInstanceRef(
            kind=ServiceKind.CONVERTER,
            name="ConverterService_0",
            admin_domain_id=0,
            monitoring_domain_id=1,
        )
        config = ConverterServiceConfig(service=service_ref)
        facade = ConverterServiceFacade(config=config)

        self.assertEqual(facade.service.name, "ConverterService_0")
        self.assertEqual(facade.service.admin_domain_id, 0)

    async def test_service_ready_returns_false_without_facade(self):
        config = ConverterServiceConfig(
            service=ServiceInstanceRef(
                kind=ServiceKind.CONVERTER,
                name="test",
                admin_domain_id=0,
                monitoring_domain_id=1,
            ),
        )
        facade = ConverterServiceFacade(config=config)

        ready = await facade.is_service_ready()

        self.assertFalse(ready)

    async def test_monitoring_snapshot_returns_none_without_facade(self):
        config = ConverterServiceConfig(
            service=ServiceInstanceRef(
                kind=ServiceKind.CONVERTER,
                name="test",
                admin_domain_id=0,
                monitoring_domain_id=1,
            ),
        )
        facade = ConverterServiceFacade(config=config)

        snapshot = await facade.get_monitoring_snapshot()

        self.assertIsNone(snapshot)


class TestConvertTabControllerWithService(unittest.IsolatedAsyncioTestCase):
    async def test_controller_from_service_accepts_service_ref(self):
        service_ref = ServiceInstanceRef(
            kind=ServiceKind.CONVERTER,
            name="ConverterService_0",
            admin_domain_id=0,
            monitoring_domain_id=1,
        )
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON Export",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )
        config = ConvertTabControllerConfig(
            selected_preset_id="json",
            input_storage_path="/data/input",
            output_storage_path="/data/output",
        )

        controller = ConvertTabController.from_service(
            service=service_ref,
            presets=(preset,),
            config=config,
        )

        self.assertEqual(controller._config.service.name, "ConverterService_0")
        self.assertEqual(controller.selected_preset_id, "json")

    async def test_service_available_is_false_without_facade(self):
        service_ref = ServiceInstanceRef(
            kind=ServiceKind.CONVERTER,
            name="ConverterService_0",
            admin_domain_id=0,
            monitoring_domain_id=1,
        )
        controller = ConvertTabController.from_service(service=service_ref)

        self.assertFalse(controller.is_service_available)

    async def test_refresh_view_includes_service_diagnostics(self):
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON Export",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )
        service_ref = ServiceInstanceRef(
            kind=ServiceKind.CONVERTER,
            name="ConverterService_0",
            admin_domain_id=0,
            monitoring_domain_id=1,
        )
        facade = ConverterServiceFacade(config=ConverterServiceConfig(service=service_ref))
        controller = ConvertTabController(
            presets=(preset,),
            service_facade=facade,
            config=ConvertTabControllerConfig(
                input_storage_path="/data/input",
                output_storage_path="/data/output",
            ),
        )

        view = await controller.refresh_view()

        # Should include diagnostic about service not being ready (no real facades)
        self.assertTrue(any("Converter Service" in d for d in view.diagnostics))

    async def test_mock_controller_is_independent_of_service(self):
        """Verify mock() factory doesn't require service or facade."""
        controller = ConvertTabController.mock()
        view = await controller.refresh_view()

        self.assertEqual(view.selected_preset_id, "sqlite_to_json")
        self.assertTrue(len(view.jobs) > 0)


if __name__ == "__main__":
    unittest.main()
