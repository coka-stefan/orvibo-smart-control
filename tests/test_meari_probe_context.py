"""Offline checks for the private context used by an explicit NVR probe."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "custom_components/orvibo_smart_control/meari_probe_context.py"
spec = importlib.util.spec_from_file_location("orvibo_probe_context_test", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SERIAL = "0000PRIVATE-SERIAL"


def session_response():
    return {
        "status": 0, "thirdAppType": "1",
        "miruiConfigResult": {"result": {
            "partnerId": "345", "apiServer": "https://api.example.invalid",
            "pfApi": {"openapi": {"domain": "https://openapi.example.invalid/ppstrongs/"}},
        }},
        "miruiTokenResult": {"result": {
            "userID": "123456", "userToken": "PRIVATE-USER-TOKEN", "countryCode": "CN",
        }},
    }


def inventory_response():
    # Insertion order differs from the SDK's category order deliberately.
    return {"resultCode": 1001, "nvr-neutral": [{
        "snNum": SERIAL, "hostKey": "PRIVATE-HOST-KEY", "deviceID": "555",
        "iotType": 3, "devTypeID": 11,
        "capability": json.dumps({"ver": 2, "caps": {"p2p": 2, "dpc": 1, "idt": 0}}),
    }], "ipc": [None, {"snNum": "PRIVATE-IPC", "devTypeID": 2}, "INVALID"]}


def channel_response(channel=1, state=1):
    return {"resultCode": 1001, "result": {SERIAL: {
        "1015": json.dumps({"state": [{"channel": channel, "state": state, "name": "PRIVATE-NAME"}]}),
        "67": json.dumps([json.dumps({"channel": channel, "caps": {"p2p": 2, "vtk": 4, "dpc": 9, "idt": 9}})]),
    }}}


class ProbeContextTests(unittest.TestCase):
    def build(self, raw=None, inventory=None, **kwargs):
        return module.build_probe_context(
            session_response() if raw is None else raw,
            inventory_response() if inventory is None else inventory,
            device_index=kwargs.pop("device_index", 2), channel_id=kwargs.pop("channel_id", 1),
            **kwargs,
        )

    def assert_error(self, code, **kwargs):
        with self.assertRaises(ValueError) as caught:
            self.build(**kwargs)
        self.assertEqual(str(caught.exception), code)
        for secret in ("PRIVATE", "SECRET", SERIAL, "example.invalid"):
            self.assertNotIn(secret, str(caught.exception))

    def test_explicit_second_device_and_first_channel_preserve_real_account(self):
        context = self.build()
        self.assertEqual(context["channel_id"], 1)
        self.assertEqual(context["timeout_seconds"], 35.0)
        self.assertEqual(context["device"]["snNum"], SERIAL)
        self.assertEqual(context["device"]["nvrChannelId"], 1)
        self.assertEqual(context["device"]["_category"], "nvr-neutral")
        self.assertEqual(context["account"], {
            "user_id": "123456", "user_token": "PRIVATE-USER-TOKEN",
            "country_code": "CN", "phone_code": None, "brand": "345",
            "api_server": "https://api.example.invalid",
            "openapi_server": "https://openapi.example.invalid/ppstrongs",
            "platform_domain": None, "platform_signature": None, "client_id": None,
            "app_version": "5.2.6.307a13",
        })

    def test_default_host_key_auth_is_explicit_and_custom_password_is_not_guessed(self):
        self.assertEqual(self.build()["vvp_auth"], {"full_password":False,"include_licence":True})
        for key, value in (("isVideoSetPwd",1),("isVideoSetPwd","1"),("videoPwd","PRIVATE")):
            inventory = inventory_response()
            inventory["nvr-neutral"][0][key] = value
            self.assert_error("video_password_required", inventory=inventory)

    def test_ipc_requires_channel_zero_and_uses_same_xts_auth(self):
        inventory = inventory_response()
        inventory["ipc"] = [{**inventory["nvr-neutral"][0],"devTypeID":2}]
        context = self.build(inventory=inventory,device_index=1,channel_id=0)
        self.assertEqual(context["device"]["devTypeID"],2)
        self.assert_error("channel_invalid",inventory=inventory,device_index=1,channel_id=1)

    def test_json_encoded_responses_and_result_wrapper_keep_public_index(self):
        raw, inventory = session_response(), inventory_response()
        expected = self.build(raw=raw, inventory=inventory)
        raw["miruiConfigResult"] = json.dumps(raw["miruiConfigResult"])
        raw["miruiTokenResult"] = json.dumps(raw["miruiTokenResult"])
        wrapped = {"resultCode": "1001", "result": {k: v for k, v in inventory.items() if k != "resultCode"}}
        self.assertEqual(self.build(raw=json.dumps(raw), inventory=json.dumps(wrapped)), expected)

    def test_sdk_category_order_and_mapping_rows_determine_index(self):
        inventory = inventory_response()
        nvr = inventory.pop("nvr-neutral")
        inventory["nvr"] = [False, *nvr]
        context = self.build(inventory=inventory, device_index=1)
        self.assertEqual(context["device"]["_category"], "nvr")
        self.assert_error("unsupported_device", inventory=inventory, device_index=2)
        self.assert_error("device_not_found", inventory=inventory, device_index=3)

    def test_missing_country_uses_region_of_external_session_request(self):
        raw = session_response()
        del raw["miruiTokenResult"]["result"]["countryCode"]
        self.assertEqual(self.build(raw=raw)["account"]["country_code"], "CN")
        self.assertEqual(self.build(raw=raw, country_code="DE")["account"]["country_code"], "DE")
        raw["miruiTokenResult"]["result"]["countryCode"] = "US"
        self.assertEqual(self.build(raw=raw, country_code="DE")["account"]["country_code"], "US")
        raw["miruiTokenResult"]["result"]["countryCode"] = "PRIVATE-BAD-COUNTRY"
        self.assert_error("account_invalid", raw=raw, country_code="CN")

    def test_optional_platform_metadata_and_client_id_are_not_invented(self):
        raw = session_response()
        raw["miruiConfigResult"]["result"]["pfApi"]["platform"] = {
            "domain": "platform.example.invalid", "signature": "PRIVATE-SIGNATURE",
        }
        raw["miruiTokenResult"]["result"].update({"clientID": "PRIVATE-CLIENT", "phoneCode": "86"})
        account = self.build(raw=raw)["account"]
        self.assertEqual(account["platform_domain"], "platform.example.invalid")
        self.assertEqual(account["platform_signature"], "PRIVATE-SIGNATURE")
        self.assertEqual(account["client_id"], "PRIVATE-CLIENT")
        self.assertEqual(account["phone_code"], "86")

    def test_required_account_and_partner_fields_reject_invalid_values(self):
        for field, value in (
            ("userID", True), ("userID", 0), ("userID", "PRIVATE-USER"),
            ("userToken", None), ("userToken", "PRIVATE\nTOKEN"), ("userToken", ""),
            ("countryCode", "C"), ("countryCode", 86), ("phoneCode", 86),
            ("phoneCode", "PRIVATE"), ("clientId", "PRIVATE\nCLIENT"),
        ):
            with self.subTest(field=field, value=value):
                raw = session_response()
                raw["miruiTokenResult"]["result"][field] = value
                self.assert_error("account_invalid", raw=raw)
        for value in (None, True, "PRIVATE-PARTNER", -1):
            raw = session_response()
            raw["miruiConfigResult"]["result"]["partnerId"] = value
            self.assert_error("account_invalid", raw=raw)
        raw = session_response()
        raw["miruiTokenResult"]["result"].pop("countryCode")
        self.assert_error("account_invalid", raw=raw, country_code="PRIVATE")

    def test_endpoints_reject_non_https_credentials_ips_and_ambiguous_paths(self):
        for endpoint in (
            None, "", "http://api.example.invalid", "https://127.0.0.1",
            "https://api.local", "https://api.localhost", "https://api.internal",
            "https://PRIVATE:SECRET@api.example.invalid", "https://api.example.invalid:1234",
            "https://api.example.invalid/private", "https://api.example.invalid/?SECRET=1",
            "https://api.example.invalid/#SECRET", "https://api.example.invalid\n",
            "api.example.invalid", "https://api.example.invalid:PRIVATE",
        ):
            with self.subTest(endpoint=endpoint):
                raw = session_response()
                raw["miruiConfigResult"]["result"]["apiServer"] = endpoint
                self.assert_error("endpoint_invalid", raw=raw)
        raw = session_response()
        raw["miruiConfigResult"]["result"]["pfApi"].pop("openapi")
        self.assert_error("endpoint_invalid", raw=raw)

    def test_invalid_session_and_inventory_have_fixed_errors(self):
        for raw in ("PRIVATE-BAD-JSON", [], {}, {"status": True, "thirdAppType": "1"}, {"status": 3}, {"status": 0, "thirdAppType": "2"}):
            self.assert_error("session_invalid", raw=raw)
        for inventory in ("PRIVATE-BAD-JSON", [], {}, {"resultCode": True}, {"resultCode": 1002}, {"resultCode": 1001, "result": {}}):
            self.assert_error("inventory_invalid", inventory=inventory)
        self.assert_error("device_not_found", inventory={"resultCode": 1001, "nvr-neutral": []})

    def test_only_confirmed_iot3_device_types_and_p2p2_are_accepted(self):
        for field, value in (("iotType", 4), ("iotType", True), ("devTypeID", 1), ("devTypeID", 17)):
            inventory = inventory_response()
            inventory["nvr-neutral"][0][field] = value
            self.assert_error("unsupported_device", inventory=inventory)
        for p2p in (None, True, 1, 3, "PRIVATE"):
            inventory = inventory_response()
            inventory["nvr-neutral"][0]["capability"] = {"caps": {"p2p": p2p}}
            self.assert_error("unsupported_transport", inventory=inventory)

    def test_serial_and_host_key_fit_native_buffers_without_control_characters(self):
        for field, error in (("snNum", "serial_invalid"), ("hostKey", "host_key_invalid")):
            for value in (None, True, 123, "", "PRIVATE SECRET", "PRIVATE\nSECRET", "PRIVATE\x00SECRET", "x" * 64, "non-ASCII-é"):
                with self.subTest(field=field, value=value):
                    inventory = inventory_response()
                    inventory["nvr-neutral"][0][field] = value
                    self.assert_error(error, inventory=inventory)
            inventory = inventory_response()
            inventory["nvr-neutral"][0][field] = "x" * 63
            self.assertEqual(self.build(inventory=inventory)["device"][field], "x" * 63)
        for serial in ("123", "1234"):
            inventory = inventory_response()
            inventory["nvr-neutral"][0]["snNum"] = serial
            self.assert_error("serial_invalid", inventory=inventory)

    def test_sdk_serial_and_licence_format_vectors(self):
        for serial, formatted, licence in (
            ("", "", ""), ("123456789", "0000000123456789", "00000000000123456789"),
            ("ABCD1234567890123456", "1234567890123456", "ABCD1234567890123456"),
            ("1234", "", "1234"),
        ):
            self.assertEqual(module.format_sn(serial), formatted)
            self.assertEqual(module.format_licence_id(serial), licence)
        for serial in (None, True, 1, "abc"):
            with self.assertRaisesRegex(ValueError, "^serial_invalid$"):
                module.format_sn(serial)

    def test_selected_channel_capabilities_restore_recorder_level_codes(self):
        inventory = inventory_response()
        inventory["nvr-neutral"][0]["capability"] = {"ver": 2, "caps": {
            "p2p": 2, "dpc": 1, "gal": 3, "idt": 0, "idt2": 4, "nct": 8,
        }}
        channels = channel_response()
        channels["result"][SERIAL]["67"] = json.dumps([json.dumps({
            "channel": 1, "ver": 3, "caps": {
                "p2p": 2, "vtk": 4, "dpc": 9, "gal": 9, "idt": 9, "idt2": 9, "nct": 9,
            },
        })])
        caps = self.build(inventory=inventory, channel_payload=channels)["device"]["capability"]
        self.assertEqual(caps, {"ver": 3, "caps": {
            "p2p": 2, "vtk": 4, "dpc": 1, "gal": 3, "idt": 0, "idt2": 4, "nct": 8,
        }})
        self.assertEqual(self.build()["device"]["capability"], {"ver": 2, "caps": {"p2p": 2, "dpc": 1, "idt": 0}})

    def test_missing_parent_codes_do_not_take_channel_recorder_codes(self):
        inventory = inventory_response()
        inventory["nvr-neutral"][0]["capability"] = {"caps": {"p2p": 2}}
        caps = self.build(inventory=inventory, channel_payload=channel_response())["device"]["capability"]["caps"]
        self.assertEqual(caps, {"p2p": 2, "vtk": 4})

    def test_channel_zero_remains_zero_and_absent_capabilities_use_parent(self):
        channels = channel_response(channel=0)
        channels["result"][SERIAL].pop("67")
        context = self.build(channel_id=0, channel_payload=channels)
        self.assertEqual(context["device"]["nvrChannelId"], 0)
        self.assertEqual(context["channel_id"], 0)
        self.assertEqual(context["device"]["capability"]["caps"], {"p2p": 2, "dpc": 1, "idt": 0})

    def test_explicit_channel_must_be_present_unambiguous_and_have_valid_state(self):
        self.assert_error("channel_not_found", channel_payload=channel_response(channel=3))
        self.assert_error("channel_offline", channel_payload=channel_response(state=0))
        for state in (None, True, "PRIVATE"):
            self.assert_error("channel_response_invalid", channel_payload=channel_response(state=state))
        channels = channel_response()
        channels["result"][SERIAL]["1015"] = {"state": [{"channel": 1, "state": 1}, {"channel": 1, "state": 1}]}
        self.assert_error("channel_not_found", channel_payload=channels)
        for payload in ({}, "PRIVATE-BAD-JSON", {"resultCode": 1002}, {"resultCode": 1001, "result": {}}):
            self.assert_error("channel_response_invalid", channel_payload=payload)
        channels = channel_response()
        channels["result"][SERIAL]["67"] = [{"channel": 1, "caps": {"p2p": 1}}]
        self.assert_error("unsupported_transport", channel_payload=channels)

    def test_whitelist_and_deep_copy_keep_only_worker_inputs(self):
        raw, inventory = session_response(), inventory_response()
        raw["miruiTokenResult"]["result"]["otherSecret"] = "PRIVATE-OTHER"
        device = inventory["nvr-neutral"][0]
        device.update({"deviceName": "PRIVATE-NAME", "latitude": 1, "settings": {"password": "SECRET"},
                       "deviceID": 9876543210, "deviceSignature": "PRIVATE-SIGNATURE", "t": "1792012345678"})
        device["capability"] = {"ver": "2", "caps": {
            "p2p": "2", "dpc": True, "vtk": "4", "arbitrary": "PRIVATE-CAPABILITY",
            "bps2": {"1": "PROFILE", "2": "x" * 65, "PRIVATE": "SECRET"},
        }}
        original = deepcopy((raw, inventory))
        context = self.build(raw=raw, inventory=inventory)
        self.assertEqual((raw, inventory), original)
        output = context["device"]
        self.assertEqual(output["deviceID"], "9876543210")
        self.assertEqual(output["t"], 1792012345678)
        self.assertEqual(output["deviceSignature"], "PRIVATE-SIGNATURE")
        self.assertEqual(output["capability"], {"ver": 2, "caps": {"p2p": 2, "vtk": 4, "bps2": {"1": "PROFILE"}}})
        for key in ("deviceName", "latitude", "settings"):
            self.assertNotIn(key, output)
        self.assertNotIn("otherSecret", context["account"])
        context["device"]["capability"]["caps"]["bps2"]["1"] = "CHANGED"
        self.assertEqual((raw, inventory), original)

    def test_optional_device_fields_and_quality_profiles_are_bounded(self):
        for key, value in (("deviceID", True), ("deviceID", -1), ("hostKey1", "x" * 257),
                           ("deviceUUID", "PRIVATE\nUUID"), ("t", True), ("t", "x"),
                           ("t", "9223372036854775808"), ("protocolVersion", -1)):
            inventory = inventory_response()
            inventory["nvr-neutral"][0][key] = value
            self.assert_error("device_data_invalid", inventory=inventory)
        inventory = inventory_response()
        inventory["nvr-neutral"][0]["capability"] = {"caps": {"p2p": 2, "bps2": {str(i): "PROFILE" for i in range(256)}}}
        self.assertEqual(len(self.build(inventory=inventory)["device"]["capability"]["caps"]["bps2"]), 128)

    def test_explicit_selection_and_timeout_bounds_reject_booleans_and_nonfinite_values(self):
        for value in (True, False, "2", 0, -1, 513, 1.5):
            self.assert_error("device_index_invalid", device_index=value)
        for value in (True, False, "1", -1, 129, 1.5):
            self.assert_error("channel_invalid", channel_id=value)
        for value in (True, False, "30", 0, 9, -1, 60.1, float("nan"), float("inf")):
            self.assert_error("timeout_invalid", timeout_seconds=value)
        self.assertEqual(self.build(channel_id=128, timeout_seconds=10)["channel_id"], 128)
        self.assertEqual(self.build(timeout_seconds=35)["timeout_seconds"], 35.0)
        inventory = {"resultCode": 1001, "ipc": [{}] * 511, "nvr-neutral": inventory_response()["nvr-neutral"]}
        self.assertEqual(self.build(inventory=inventory, device_index=512)["device"]["snNum"], SERIAL)


if __name__ == "__main__":
    unittest.main()
