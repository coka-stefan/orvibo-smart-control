"""Offline readtable and partial-update regressions; payloads are synthetic."""

from __future__ import annotations

import copy
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "orvibo_smart_control"
PACKAGE_NAME = "orvibo_readtable_loading_test"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(COMPONENT_PATH)]
sys.modules[PACKAGE_NAME] = package
protocol = importlib.import_module(f"{PACKAGE_NAME}.protocol")
https = importlib.import_module(f"{PACKAGE_NAME}.https_client")
inventory = importlib.import_module(f"{PACKAGE_NAME}.device_inventory")
dispatcher_module = importlib.import_module(f"{PACKAGE_NAME}.status_dispatcher")
store_module = importlib.import_module(f"{PACKAGE_NAME}.state_store")
parsers = importlib.import_module(f"{PACKAGE_NAME}.parsers")
categories = importlib.import_module(f"{PACKAGE_NAME}.device_types").DeviceCategory


class ReadtableLoadingTests(unittest.TestCase):
    def setUp(self):
        self.client = https.HttpsClient("offline", "0" * 32)

    def test_list_and_keyed_tables_keep_identical_joined_metadata(self):
        device = {"deviceId": "lamp", "deviceType": "503", "subDeviceType": "461",
                  "uid": "gateway", "roomId": "room", "statusId": "status",
                  "properties": {"brightness": {"min": 1}}, "ui": {"model": "lamp-ui"}}
        status = {"deviceId": "lamp", "online": "1", "value1": "0", "value2": "32",
                  "properties": {"brightness": {"percent": 32}}}
        room = {"roomId": "room", "roomName": "Living room"}
        expected = self.client.parse_device_status_list({
            "device": [device], "deviceStatus": [status], "room": [room]})
        keyed = {"device": {"lamp": {k: v for k, v in device.items() if k != "deviceId"}},
                 "deviceStatus": {"lamp": {k: v for k, v in status.items() if k != "deviceId"}},
                 "room": {"room": {"roomName": "Living room"}}}
        before = copy.deepcopy(keyed)
        self.assertEqual(self.client.parse_device_status_list(keyed), expected)
        self.assertEqual(keyed, before)
        row = expected[0]
        self.assertEqual((row["room_id"], row["room_name"], row["value2"]),
                         ("room", "Living room", 32))
        self.assertTrue(row["online"])
        self.assertEqual(row["properties"]["brightness"], {"min": 1, "percent": 32})

    def test_device_values_and_embedded_status_are_preserved(self):
        for table in ([{"deviceId": "lamp", "deviceType": 38, "value1": 1,
                        "value2": 40, "status": {"value3": 3500, "online": 1}}],
                      {"lamp": {"deviceType": 38, "value1": 1, "value2": 40,
                                "status": {"value3": 3500, "online": 1}}}):
            with self.subTest(table=table):
                row = self.client.parse_device_status_list({"device": table})[0]
                self.assertEqual((row["value1"], row["value2"], row["value3"]), (1, 40, 3500))
                self.assertFalse(row["state"])
                self.assertTrue(row["online"])

    def test_deleted_status_cannot_supply_properties_or_values(self):
        for statuses in ([{"deviceId": "lamp", "delFlag": "1", "value1": 0,
                           "properties": {"onoff": {"status": "on"}}}],
                         {"lamp": {"delFlag": 1, "properties": {"onoff": {"status": "on"}}}}):
            row = self.client.parse_device_status_list({
                "device": [{"deviceId": "lamp", "deviceType": 501,
                            "properties": {"onoff": {"status": "off"}}}],
                "deviceStatus": statuses})[0]
            self.assertEqual(row["properties"]["onoff"]["status"], "off")
            self.assertEqual(row["status"], {})

    def test_property_table_populates_initial_light_state(self):
        data = {"device": [{"deviceId": "lamp", "deviceType": 503, "subDeviceType": 461}],
                "devicePropertyStatus": [
                    {"deviceId": "lamp", "property": "onoff", "value": '{"status":"on"}'},
                    {"deviceId": "lamp", "property": "brightness", "value": {"percent": 45}},
                    {"deviceId": "lamp", "property": "colorTemp", "value": '{"value":3500}'},
                ]}
        before = copy.deepcopy(data)
        rows = self.client.parse_device_status_list(data)
        devices, states = {}, {}
        inventory.DeviceInventory(None, devices, states, store_module.StateStore(states),
                                  lambda _: None).initialize(rows)
        self.assertTrue(states["lamp"]["state"])
        self.assertEqual((states["lamp"]["brightness"], states["lamp"]["color_temp"]), (45, 3500))
        self.assertEqual(data, before)

    def test_property_table_uses_device_id_and_preserves_raw_types(self):
        data = {"device": [{"deviceId": "lamp", "deviceType": 501}],
                "devicePropertyStatus": [
                    {"deviceId": "other", "property": "onoff", "value": {"status": "on"}},
                    {"deviceId": "lamp", "devicePropertyStatusId": "other",
                     "property": "onoff_status", "value": "on"},
                    {"deviceId": "lamp", "property": "test", "value": [1, True, None]},
                    {"deviceId": "lamp", "property": "number", "value": 2},
                    {"deviceId": "lamp", "property": "bad_json", "value": "{invalid}"},
                    None, {"deviceId": "lamp", "property": []},
                    {"property": "missing_device", "value": 1}]}
        props = self.client.parse_device_status_list(data)[0]["properties"]
        self.assertEqual(props, {"onoff_status": "on", "test": [1, True, None],
                                 "number": 2, "bad_json": "{invalid}"})

    def test_property_times_and_tombstones_do_not_resurrect_stale_values(self):
        data = {"device": [{"deviceId": "lamp", "deviceType": 501}],
                "deviceStatus": [{"deviceId": "lamp", "updateTimeSec": 20,
                                  "properties": {"onoff": {"status": "off"}}}],
                "devicePropertyStatus": [
                    {"deviceId": "lamp", "property": "onoff", "updateTime": "19000",
                     "value": {"status": "on"}},
                    {"deviceId": "lamp", "property": "brightness", "updateTimeSec": 21,
                     "value": {"percent": 50}},
                    {"deviceId": "lamp", "property": "brightness", "updateTimeSec": 22,
                     "delFlag": 1},
                    {"deviceId": "lamp", "property": "brightness", "updateTimeSec": 21,
                     "value": {"percent": 99}},
                ]}
        props = self.client.parse_device_status_list(data)[0]["properties"]
        self.assertEqual(props, {"onoff": {"status": "off"}})

    def test_stale_inline_properties_cannot_lower_the_time_baseline(self):
        data = {"device": [{"deviceId": "lamp", "deviceType": 503,
                            "updateTimeSec": 30,
                            "properties": {"onoff": {"status": "on"}}}],
                "deviceStatus": [{"deviceId": "lamp", "updateTimeSec": 20,
                                  "properties": {"onoff": {"status": "off"},
                                                 "brightness": {"percent": 20}}}],
                "devicePropertyStatus": [
                    {"deviceId": "lamp", "property": "onoff", "updateTime": "25000",
                     "value": {"status": "off"}}]}
        props = self.client.parse_device_status_list(data)[0]["properties"]
        self.assertEqual(props, {"onoff": {"status": "on"}, "brightness": {"percent": 20}})
        data["devicePropertyStatus"][0]["updateTimeSec"] = 31
        props = self.client.parse_device_status_list(data)[0]["properties"]
        self.assertEqual(props["onoff"], {"status": "off"})

    def test_malformed_tables_and_rows_are_ignored(self):
        data = {"device": [None, 3, {"deviceId": "deleted", "delFlag": 1},
                           {"deviceId": "lamp", "deviceType": 501}],
                "room": {"bad": None}, "deviceStatus": {"bad": 2},
                "devicePropertyStatus": "invalid"}
        self.assertEqual([d["device_id"] for d in self.client.parse_device_status_list(data)], ["lamp"])

    def test_keyed_parent_switch_without_properties_is_filtered(self):
        self.assertEqual(self.client.parse_device_status_list({
            "device": {"parent": {"deviceType": 135}}}), [])

    def test_homepage_preserves_unknown_inventory_and_identifiers(self):
        rows = self.client.parse_device_list({"deviceList": [
            {"deviceId": "unknown", "deviceType": 19999012, "subDeviceType": 1,
             "statusId": "alias", "ui": {"model": "special-ui"}},
            {"deviceId": "deleted", "deviceType": 501, "delFlag": 1}, None]})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["device_type"], rows[0]["status_id"], rows[0]["ui_model"]),
                         ("unknown", "alias", "special-ui"))

    def test_gateway_ips_accept_string_types_and_ignore_deleted_or_invalid_rows(self):
        data = {"device": {"mixpad": {"deviceType": "114", "uid": "gateway"},
                           "deleted": {"deviceType": 114, "uid": "deleted", "delFlag": 1},
                           "bad": None},
                "gateway": [{"uid": "gateway", "localStaticIP": "192.0.2.2:10001"},
                            None, {"uid": "deleted", "ip": "192.0.2.3"},
                            {"uid": "gateway", "ip": "192.0.2.4", "delFlag": 1}]}
        self.assertEqual(self.client._extract_gateway_ips(data), {"gateway": "192.0.2.2"})


class PartialUpdateTests(unittest.TestCase):
    def dispatcher(self, device=None):
        states = {"lamp": {"state": False, "brightness": 10, "color_temp": 3500}}
        store = store_module.StateStore(states)
        dispatcher = dispatcher_module.StatusUpdateDispatcher(
            {"lamp": device or {"device_type_raw": 503, "sub_device_type": 461}},
            states, store, {}, [], on_motion=lambda *_: None, on_emergency=lambda *_: None,
            on_lock_transient=lambda *_: None, on_lock_message=lambda *_: None,
            on_lock_event=lambda *_: None, on_updated=lambda: None)
        return dispatcher, store, states

    def test_onoff_push_does_not_guard_an_unreported_brightness(self):
        for source in (store_module.StateSource.LAN, store_module.StateSource.SSL):
            with self.subTest(source=source):
                dispatcher, store, states = self.dispatcher()
                with patch.object(store_module.time, "monotonic", return_value=100):
                    dispatcher.dispatch("lamp", {"properties": {"onoff": {"status": "on"}}}, source)
                store.merge("lamp", {"brightness": 50, "color_temp": 4000},
                            store_module.StateSource.CLOUD, now=101)
                self.assertEqual((states["lamp"]["brightness"], states["lamp"]["color_temp"]), (50, 4000))
                self.assertTrue(states["lamp"]["state"])

    def test_explicit_unchanged_brightness_still_refreshes_guard(self):
        dispatcher, store, states = self.dispatcher()
        with patch.object(store_module.time, "monotonic", return_value=100):
            dispatcher.dispatch("lamp", {"properties": {"brightness": {"percent": 10}}},
                                store_module.StateSource.LAN)
        store.merge("lamp", {"brightness": 50}, store_module.StateSource.CLOUD, now=101)
        self.assertEqual(states["lamp"]["brightness"], 10)
        store.merge("lamp", {"brightness": 50}, store_module.StateSource.CLOUD, now=131)
        self.assertEqual(states["lamp"]["brightness"], 50)

    def test_generic_partial_push_preserves_other_fields(self):
        dispatcher, _, states = self.dispatcher({"device_type_raw": 19999012})
        dispatcher.dispatch("lamp", {"value2": 25})
        self.assertEqual((states["lamp"]["state"], states["lamp"]["color_temp"]), (False, 3500))
        self.assertEqual(states["lamp"]["brightness"], 25)
        self.assertNotIn("position", states["lamp"])

    def test_missing_switch_state_produces_no_patch(self):
        for name in ("parse_light", "parse_switch", "parse_dim_color_light"):
            parser = getattr(importlib.import_module(f"{PACKAGE_NAME}.parsers.light"), name)
            with self.subTest(parser=name):
                self.assertEqual(parser({"state": True}, {}).values, {})

    def test_clothes_horse_partial_push_preserves_missing_fields(self):
        parser = parsers.get_state_parser(categories.CLOTHES_HORSE)
        self.assertEqual(parser({"position": 70, "heat_drying_state": True},
                                {"lighting_state": "on"}).values, {"lighting_state": True})


if __name__ == "__main__":
    unittest.main()
