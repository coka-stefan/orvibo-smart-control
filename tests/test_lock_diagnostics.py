"""Regressions for complete, redacted lock diagnostics in large homes."""

from __future__ import annotations

import copy
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "orvibo_smart_control"
PACKAGE_NAME = "orvibo_smart_control_diagnostics_test"


class LockDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(COMPONENT_PATH)]
        sys.modules[PACKAGE_NAME] = package
        modules = {}
        for name, attr in (("homeassistant.config_entries", "ConfigEntry"),
                           ("homeassistant.core", "HomeAssistant"),
                           ("homeassistant.helpers.device_registry", "DeviceEntry")):
            module = types.ModuleType(name)
            setattr(module, attr, object)
            modules[name] = module
        with patch.dict(sys.modules, modules):
            cls.diagnostics = importlib.import_module(f"{PACKAGE_NAME}.diagnostics")
        cls.redact = importlib.import_module(f"{PACKAGE_NAME}.redact")

    def setUp(self):
        self.salt = b"lock-diagnostic-test"
        self.entry = types.SimpleNamespace(entry_id="entry")
        self.lock_id = "w-private-lock"
        self.lock = {
            "device_id": self.lock_id, "device_name": "Lock",
            "device_type_raw": 522, "sub_device_type": 463,
            "class_id": 463, "model": "test-lock-model", "uid": "private-uid",
            "value1": 1, "value2": 0, "value3": 0, "value4": 60,
            "properties": {"battery_power": 60, "token": "private-token"},
        }
        self.state = {
            "raw_value4": 60, "dry_battery_level": None,
            "properties": {
                "batteryManager": {"level": 59, "isSetupBattery": "on"},
                "batteryManager1_level": 0,
                "batteryManager1_isSetupBattery": "off",
                "sessionKey": "private-key", "userId": "private-user",
            },
        }
        self.coordinator = types.SimpleNamespace(
            devices={self.lock_id: self.lock}, device_states={self.lock_id: self.state},
            _cmd42_log=[], _redaction_salt=self.salt,
        )
        self.hass = types.SimpleNamespace(
            data={"orvibo_smart_control": {"entry": self.coordinator}})

    async def test_large_home_keeps_lock_after_fiftieth_device(self):
        devices = {f"lamp-{i}": {"device_type_raw": 1} for i in range(85)}
        devices[self.lock_id] = self.lock
        self.coordinator.devices = devices
        self.coordinator.device_states = {key: {} for key in devices}
        self.coordinator.device_states[self.lock_id] = self.state
        result = await self.diagnostics.async_get_config_entry_diagnostics(self.hass, self.entry)
        self.assertEqual(result["device_count"], 86)
        self.assertEqual(len(result["devices"]), 86)
        self.assertEqual(len(result["states"]), 86)
        key = next(iter(self.redact.redact_packet({self.lock_id: {}}, self.salt, strict=False)))
        self.assertIn(key, result["devices"])
        self.assertIn(key, result["states"])
        self.assertNotIn("<truncated>", result["devices"])

    async def test_config_diagnostics_keep_inventory_and_live_lock_properties(self):
        result = await self.diagnostics.async_get_config_entry_diagnostics(self.hass, self.entry)
        details = next(iter(result["devices"].values()))["lock_diagnostics"]
        self.assertEqual(details["sub_device_type"], 463)
        self.assertEqual(details["class_id"], 463)
        self.assertEqual(details["inventory_values"]["value4"], 60)
        self.assertEqual(details["state_values"]["raw_value4"], 60)
        self.assertEqual(details["device_properties"]["battery_power"], 60)
        self.assertEqual(details["state_properties"]["batteryManager"]["level"], 59)

    async def test_device_diagnostics_keep_live_properties_without_mutating_state(self):
        before = copy.deepcopy(self.coordinator.device_states)
        device = types.SimpleNamespace(identifiers={("orvibo_smart_control", self.lock_id)})
        result = await self.diagnostics.async_get_device_diagnostics(self.hass, self.entry, device)
        self.assertEqual(result["lock_diagnostics"]["state_properties"]["batteryManager"]["level"], 59)
        self.assertEqual(result["lock_diagnostics"]["device_properties"]["battery_power"], 60)
        self.assertEqual(self.coordinator.device_states, before)

    async def test_added_lock_properties_remain_redacted(self):
        device = types.SimpleNamespace(identifiers={("orvibo_smart_control", self.lock_id)})
        for result in (
            await self.diagnostics.async_get_config_entry_diagnostics(self.hass, self.entry),
            await self.diagnostics.async_get_device_diagnostics(self.hass, self.entry, device),
        ):
            with self.subTest(kind="config" if "devices" in result else "device"):
                self.assertIn("<redacted>", repr(result))
                for secret in ("private-token", "private-key", "private-user", "private-uid"):
                    self.assertNotIn(secret, repr(result))

    async def test_non_lock_diagnostics_do_not_export_lock_properties(self):
        self.coordinator.devices = {"lamp": {"device_type_raw": 1}}
        self.coordinator.device_states = {"lamp": {"properties": {"value": 20}}}
        result = await self.diagnostics.async_get_config_entry_diagnostics(self.hass, self.entry)
        self.assertNotIn("lock_diagnostics", next(iter(result["devices"].values())))
        self.assertNotIn("properties", next(iter(result["states"].values())))

    async def test_missing_coordinator_reports_error(self):
        self.hass.data.clear()
        result = await self.diagnostics.async_get_config_entry_diagnostics(self.hass, self.entry)
        self.assertEqual(result, {"error": "coordinator not found"})


if __name__ == "__main__":
    unittest.main()
