"""Offline NVR batch request, data minimization, and lifecycle boundaries."""
import asyncio
import base64
import hashlib
import hmac
import json
import unittest
import types
from unittest.mock import patch

from test_meari_session import load
from test_meari_inventory import FakeResponse, device_response, session_response


def batch_response(properties=None):
    return {"resultCode": "1001", "result": {"PRIVATE-SERIAL": properties if properties is not None else {
        "213": 16,
        "1015": json.dumps({"state": [
            {"channel": 1, "state": 1, "type": 3, "name": "PRIVATE-CHANNEL"},
            {"channel": 2, "state": 0, "type": 0},
        ]}),
        "67": json.dumps([json.dumps({"channel": 1, "caps": {"p2p": 2}})]),
        "token": "TOKEN-SECRET", "deviceName": "PRIVATE-NAME",
    }}}


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


class ChannelTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("meari_channels")
        cls.inventory_module = types.SimpleNamespace(**cls.module.build_vendor_request.__globals__)

    async def inspect(self, payload=None, inventory=None):
        response = FakeResponse(json.dumps(batch_response() if payload is None else payload).encode())
        session = FakeSession(response)
        public = await self.module.async_inspect_nvr_channels(
            session, session_response(), device_response() if inventory is None else inventory,
        )
        return public, session, response

    async def test_sdk_batch_get_signs_serial_property_map_and_path(self):
        with patch.object(self.inventory_module.time, "time", return_value=1700000000.123), patch.object(self.inventory_module.secrets, "randbelow", return_value=23456):
            _, session, response = await self.inspect()
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://api.example.invalid/v1/app/nvr/iot/model/get/batch")
        params, headers = kwargs["params"], kwargs["headers"]
        self.assertEqual(json.loads(params["snIdentifier"]), {"PRIVATE-SERIAL": "213,1015,67"})
        self.assertNotIn("funSwitch", params)
        self.assertNotIn("data", kwargs)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"].total, 20)
        self.assertFalse(kwargs["raise_for_status"])
        expected_query = "&".join(f"{key}={params[key]}" for key in sorted(params) if key != "signature")
        expected_header = "api=/ppstrongs//v1/app/nvr/iot/model/get/batch|X-Ca-Key=TOKEN-SECRET|X-Ca-Timestamp=1700000000123|X-Ca-Nonce=123456"
        for actual, message in ((params["signature"], expected_query), (headers["X-Ca-Sign"], expected_header)):
            digest = base64.b64encode(hmac.new(b"TOKEN-SECRET", message.encode(), hashlib.sha1).digest()).decode()
            self.assertEqual(actual, digest)
        self.assertEqual(params["signature"], "VeTG4yXuE/niMm5fMIvahH9ID/Q=")
        self.assertEqual(headers["X-Ca-Sign"], "ZgPjUMKlxOo7upAlyHjiqU92dlc=")
        self.assertTrue(response.closed)

    async def test_sdk_result_sn_keys_and_json_string_state_are_parsed(self):
        public, _, _ = await self.inspect()
        self.assertEqual(public["channel_stage"], "nvr_channels_received")
        self.assertEqual(public["channel_result_code"], 1001)
        self.assertTrue(public["channel_query_implemented"])
        row = public["nvrs"][0]
        self.assertEqual(row["index"], 1)
        self.assertEqual(row["maximum_channel_count"], 16)
        self.assertEqual(row["channel_count"], 2)
        self.assertEqual(row["channels"], [{"channel_id": 1, "capability_codes": {"p2p": 2, "nct": 8, "idt": 2}, "state": 1, "type": 3}, {"channel_id": 2, "capability_codes": {"p2p": 1, "nct": 8, "idt": 2}, "state": 0, "type": 0}])
        self.assertFalse(row["channels_truncated"])
        self.assertEqual(public["queried_nvr_count"], 1)
        for forbidden in ("PRIVATE", "SECRET", "example.invalid", "123456", "snNum", "hostKey", "deviceSignature", "deviceName"):
            self.assertNotIn(forbidden, json.dumps(public))

    async def test_public_index_matches_inventory_and_supports_result_wrapper(self):
        inventory = device_response()
        inventory["ipc"] = [{"devTypeID": 2}, "INVALID"]
        wrapped = {"resultCode": 1001, "result": {key: val for key, val in inventory.items() if key != "resultCode"}}
        public, _, _ = await self.inspect(inventory=wrapped)
        self.assertEqual(public["nvrs"][0]["index"], 2)

    async def test_unsupported_and_missing_serial_do_not_make_requests(self):
        for inventory, expected in (
            ({"resultCode": 1001, "ipc": [{"devTypeID": 2}]}, "no_nvr_devices"),
            ({"resultCode": 1001, "nvr-neutral": [{"devTypeID": 11}]}, "nvr_serial_required"),
            ({"resultCode": 1001, "nvr-neutral": [{"devTypeID": 11, "snNum": "bad\nsecret"}]}, "nvr_serial_required"),
            ({"resultCode": 1002, "nvr-neutral": []}, "channel_request_data_invalid"),
            ({"resultCode": 1001}, "channel_request_data_invalid"),
        ):
            with self.subTest(expected=expected):
                public, session, _ = await self.inspect(inventory=inventory)
                self.assertEqual(public["channel_stage"], expected)
                self.assertEqual(session.calls, [])

    async def test_maximum_channel_count_does_not_invent_real_channels(self):
        public, _, _ = await self.inspect(batch_response({"213": 32}))
        row = public["nvrs"][0]
        self.assertEqual(row["maximum_channel_count"], 32)
        self.assertEqual(row["channel_stage"], "channel_state_missing")
        self.assertNotIn("channel_count", row)
        self.assertNotIn("channels", row)

    async def test_empty_channel_state_is_distinguished_from_missing_or_invalid(self):
        for properties, stage in (({"1015": {"state": []}}, "channel_state_received"), ({"1015": "TOKEN-SECRET"}, "invalid_channel_state"), ({"1015": {}}, "invalid_channel_state")):
            public, _, _ = await self.inspect(batch_response(properties))
            self.assertEqual(public["nvrs"][0]["channel_stage"], stage)
        public, _, _ = await self.inspect({"resultCode": 1001, "result": {}})
        self.assertEqual(public["nvrs"][0]["channel_stage"], "nvr_result_missing")

    async def test_unknown_attributes_are_omitted_and_invalid_rows_are_counted(self):
        properties = {"213": True, "1015": {"state": [
            None, {"channel": True}, {"channel": -1}, {"channel": 70000},
            {"channel": 1, "state": "SECRET", "type": True},
            {"channel": 1, "state": 1}, {"channel": "2", "state": "2", "type": "3"},
        ]}}
        inventory = device_response()
        inventory["nvr-neutral"][0].pop("capability")
        public, _, _ = await self.inspect(batch_response(properties), inventory)
        row = public["nvrs"][0]
        self.assertEqual(row["channels"], [{"channel_id": 1}, {"channel_id": 2, "state": 2, "type": 3}])
        self.assertEqual(row["invalid_channel_rows"], 5)
        self.assertNotIn("maximum_channel_count", row)
        self.assertNotIn("SECRET", json.dumps(public))

    async def test_channel_capabilities_inherit_recorder_codes_and_preserve_zero_channel(self):
        inventory = device_response()
        inventory["nvr-neutral"][0]["capability"] = json.dumps({"caps": {"p2p": 2, "dpc": 1, "idt": 0}})
        properties = {"1015": {"state": [{"channel": 0, "state": 1, "type": 3}]}, "67": json.dumps([
            json.dumps({"channel": 0, "caps": {"p2p": 3, "vtk": 4, "dpc": 9, "idt": 9, "secret": "TOKEN-SECRET"}}),
            json.dumps({"channel": 9, "caps": {"p2p": 1}}),
        ])}
        public, _, _ = await self.inspect(batch_response(properties), inventory)
        row = public["nvrs"][0]
        self.assertEqual(row["channel_count"], 1)
        self.assertEqual(row["channels"], [{"channel_id": 0, "state": 1, "type": 3, "capability_codes": {"p2p": 3, "vtk": 4, "dpc": 1, "idt": 0}}])
        self.assertEqual(row["channel_capabilities_stage"], "received")
        self.assertEqual(row["channel_capability_count"], 2)
        self.assertNotIn("SECRET", json.dumps(public))

    async def test_capabilities_alone_never_invent_channels_and_bad_caps_are_bounded(self):
        for caps, stage in (("TOKEN-SECRET", "invalid"), ("{}", "invalid"), ("[]", "received"), (None, "missing"), (json.dumps([json.dumps({"channel": 5, "caps": {"p2p": 2}})]), "received")):
            public, _, _ = await self.inspect(batch_response({"67": caps}))
            row = public["nvrs"][0]
            self.assertEqual(row["channel_capabilities_stage"], stage)
            self.assertEqual(row["channel_stage"], "channel_state_missing")
            self.assertNotIn("channels", row)
            self.assertNotIn("channel_count", row)
            self.assertNotIn("SECRET", json.dumps(public))

    async def test_nvr_and_channel_output_are_bounded_with_total_counts(self):
        inventory = {"resultCode": 1001, "nvr-neutral": [
            {"devTypeID": 11, "snNum": f"PRIVATE-SERIAL-{index}"} for index in range(self.module.MAX_NVRS + 5)
        ]}
        properties = {"1015": {"state": [{"channel": index + 1, "state": 1} for index in range(self.module.MAX_CHANNELS + 5)]}, "67": [{"channel": index + 1, "caps": {"p2p": 2}} for index in range(self.module.MAX_CHANNELS + 5)]}
        payload = {"resultCode": 1001, "result": {device["snNum"]: properties for device in inventory["nvr-neutral"]}}
        public, session, _ = await self.inspect(payload, inventory)
        self.assertEqual(len(json.loads(session.calls[0][1]["params"]["snIdentifier"])), self.module.MAX_NVRS)
        self.assertEqual(public["nvr_count"], self.module.MAX_NVRS + 5)
        self.assertTrue(public["nvrs_truncated"])
        self.assertEqual(len(public["nvrs"]), self.module.MAX_NVRS)
        row = public["nvrs"][0]
        self.assertEqual(row["channel_count"], self.module.MAX_CHANNELS + 5)
        self.assertEqual(len(row["channels"]), self.module.MAX_CHANNELS)
        self.assertTrue(row["channels_truncated"])
        self.assertTrue(row["channel_capabilities_truncated"])
        self.assertEqual(row["channel_capability_count"], self.module.MAX_CHANNELS)

    async def test_duplicates_do_not_query_same_serial_twice(self):
        inventory = device_response()
        inventory["nvr-neutral"] *= 2
        public, session, _ = await self.inspect(inventory=inventory)
        self.assertEqual(public["queried_nvr_count"], 1)
        self.assertEqual(len(json.loads(session.calls[0][1]["params"]["snIdentifier"])), 1)

    async def test_bad_response_and_vendor_rejection_do_not_claim_channels(self):
        for payload, stage in (([], "invalid_channel_response"), ({"resultCode": True}, "invalid_channel_response"), ({"resultCode": 1001, "result": "SECRET"}, "invalid_channel_response"), ({"resultCode": 1002, "message": "TOKEN-SECRET"}, "channel_request_rejected")):
            public, _, response = await self.inspect(payload)
            self.assertEqual(public["channel_stage"], stage)
            self.assertNotIn("nvrs", public)
            self.assertNotIn("SECRET", json.dumps(public))
            self.assertTrue(response.closed)

    async def test_invalid_endpoint_is_rejected_before_io(self):
        raw = session_response()
        raw["miruiConfigResult"]["result"]["apiServer"] = "http://api.example.invalid"
        session = FakeSession()
        public = await self.module.async_inspect_nvr_channels(session, raw, device_response())
        self.assertEqual(public["channel_stage"], "channel_request_data_invalid")
        self.assertEqual(session.calls, [])

    async def test_http_errors_and_redirects_are_closed_without_following(self):
        for status in (301, 302, 401, 500):
            response = FakeResponse(b"TOKEN-SECRET", status)
            session = FakeSession(response)
            public = await self.module.async_inspect_nvr_channels(session, session_response(), device_response())
            self.assertEqual(public["channel_stage"], "channel_http_error")
            self.assertEqual(public["channel_http_status"], status)
            self.assertEqual(len(session.calls), 1)
            self.assertNotIn("SECRET", json.dumps(public))
            self.assertTrue(response.closed)

    async def test_large_response_and_invalid_json_close_response(self):
        for body, stages in ((b" " * (self.module.MAX_BODY_BYTES + 1), {"channel_response_too_large"}), (b"TOKEN-SECRET", {"channel_request_failed"}), (b"[" * 1200 + b"]" * 1200, {"channel_request_failed", "invalid_channel_response"})):
            response = FakeResponse(body)
            public = await self.module.async_inspect_nvr_channels(FakeSession(response), session_response(), device_response())
            self.assertIn(public["channel_stage"], stages)
            self.assertNotIn("SECRET", json.dumps(public))
            self.assertTrue(response.closed)

    async def test_network_failures_do_not_echo_private_exception_messages(self):
        for error in (self.module.aiohttp.ClientError("TOKEN-SECRET"), OSError("PRIVATE-URL"), asyncio.TimeoutError("TOKEN-SECRET")):
            public = await self.module.async_inspect_nvr_channels(FakeSession(error=error), session_response(), device_response())
            self.assertEqual(public["channel_stage"], "channel_request_failed")
            self.assertNotIn("SECRET", json.dumps(public))
            self.assertNotIn("PRIVATE", json.dumps(public))

    async def test_cancellation_propagates_and_closes_response(self):
        class CancelledResponse(FakeResponse):
            async def iter_chunked(self, size):
                raise asyncio.CancelledError()
                yield b""
        response = CancelledResponse(b"")
        with self.assertRaises(asyncio.CancelledError):
            await self.module.async_inspect_nvr_channels(FakeSession(response), session_response(), device_response())
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
