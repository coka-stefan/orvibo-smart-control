"""Vendor inventory boundaries and offline protocol vectors; no real account."""
import asyncio
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_meari_session import load, response


def session_response():
    raw = response()
    raw["miruiConfigResult"] = {"result": {"apiServer": "https://api.example.invalid", "partnerId": "1"}}
    return raw


def device_response():
    return {"resultCode": "1001", "nvr-neutral": [{
        "deviceID": "PRIVATE-DEVICE", "deviceName": "PRIVATE-NAME",
        "snNum": "PRIVATE-SERIAL", "deviceUUID": "PRIVATE-UUID", "hostKey": "HOST-SECRET",
        "hostKey1": "HOST1-SECRET", "deviceSignature": "DEVICE-SECRET", "awsThingName": "PRIVATE-THING",
        "iotType": 3, "devTypeID": 11, "deviceP2P": "ppcs",
        "capability": json.dumps({"caps": {"p2p": 1, "nct": 8, "idt": 2, "extra": "PRIVATE"}}),
        "nvrKey": "NVR-SECRET", "latitude": 99.99, "longitude": 66.66,
    }], "ipc": []}


class InventoryProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("meari_inventory")

    def test_rfc_2202_hmac_sha1_vector(self):
        self.assertEqual(self.module._hmac_sha1("what do ya want for nothing?", "Jefe"), "7/zfauXrL6LSdBbV8YTfnCWafHk=")

    def test_apk_request_with_independent_node_crypto_vectors(self):
        with patch.object(self.module.time, "time", return_value=1700000000.123), patch.object(self.module.secrets, "randbelow", return_value=23456):
            url, params, headers = self.module.build_inventory_request(session_response())
        self.assertEqual(url, "https://api.example.invalid/v1/app/device/info/get")
        self.assertEqual(params["timestamp"], "2023-11-14T22:13:20.123Z")
        self.assertEqual(params["phoneType"], "a")
        self.assertEqual(params["appVerCode"], "50206307")
        self.assertEqual(params["funSwitch"], "1")
        self.assertNotIn("userToken", params)
        self.assertNotIn("clientId", params)
        self.assertEqual(params["signature"], "0IsqG/i8GoZ1/Y5mJWgIzvTgd5A=")
        self.assertEqual(headers["X-Ca-Sign"], "lQnIORyQf1XQECBD/QoSMiyuSLU=")
        self.assertEqual(headers["X-Ca-Key"], "TOKEN-SECRET")

    def test_region_comes_from_external_account(self):
        raw = session_response()
        account = json.loads(raw["miruiTokenResult"])
        account["result"].update(countryCode="US", phoneCode="1")
        raw["miruiTokenResult"] = account
        _, params, _ = self.module.build_inventory_request(raw, country_code="CN", phone_code="86", language="en")
        self.assertEqual((params["countryCode"], params["phoneCode"], params["lngType"]), ("US", "1", "en"))

    def test_rejects_credential_redirect_endpoints_before_io(self):
        for endpoint in ("http://api.example.invalid", "https://a:b@api.example.invalid", "https://api.example.invalid/?token=x", "https://api.example.invalid/#x", "https://127.0.0.1", "https://[::1]", "https://localhost", "https://a.local", "https://api.example.invalid:8443", "https://api.example.invalid/other", "https://api.example.invalid/../", "https://api.example.invalid\n"):
            with self.subTest(endpoint=endpoint):
                raw = session_response()
                raw["miruiConfigResult"]["result"]["apiServer"] = endpoint
                with self.assertRaises(ValueError):
                    self.module.build_inventory_request(raw)

    def test_base_path_is_preserved(self):
        raw = session_response()
        raw["miruiConfigResult"]["result"]["apiServer"] += "/ppstrongs/"
        self.assertEqual(self.module.build_inventory_request(raw)[0], "https://api.example.invalid/ppstrongs/v1/app/device/info/get")

    def test_bad_credentials_fail_before_io(self):
        for token in (None, "", " ", "bad\r\nheader", "x" * 8193):
            raw = session_response()
            raw["miruiTokenResult"] = {"result": {"userID": 123456, "userToken": token}}
            with self.assertRaises(ValueError):
                self.module.build_inventory_request(raw)

    def test_sdk_root_response_is_summarized_without_private_data(self):
        raw = device_response()
        public = self.module.summarize_inventory(raw)
        self.assertEqual(public["vendor_stage"], "vendor_devices_received")
        self.assertEqual(public["inventory_shape"], "sdk_root")
        self.assertEqual(public["device_count"], 1)
        self.assertEqual(public["category_counts"], {"nvr-neutral": 1, "ipc": 0})
        self.assertFalse(public["channel_query_implemented"])
        self.assertEqual(public["devices"][0]["capability_codes"], {"p2p": 1, "nct": 8, "idt": 2})
        for value in ("PRIVATE", "SECRET", "99.99", "66.66", "extra"):
            self.assertNotIn(value, json.dumps(public))

    def test_result_wrapper_is_distinguished_from_sdk_root(self):
        raw = device_response()
        wrapped = {"resultCode": 1001, "result": {key: value for key, value in raw.items() if key != "resultCode"}}
        public = self.module.summarize_inventory(wrapped)
        self.assertEqual(public["inventory_shape"], "result_wrapper")
        self.assertEqual(public["device_count"], 1)

    def test_vendor_rejection_and_bad_shapes_do_not_claim_inventory(self):
        for raw in (None, [], {"resultCode": True}, {"resultCode": "PRIVATE"}, {"resultCode": 1001}, {"resultCode": 1001, "PRIVATE-GROUP": ["PRIVATE"]}):
            self.assertNotEqual(self.module.summarize_inventory(raw)["vendor_stage"], "vendor_devices_received")
        public = self.module.summarize_inventory({"resultCode": 1002, "message": "TOKEN-SECRET", "nvr": ["PRIVATE"]})
        self.assertEqual(public["vendor_stage"], "vendor_request_rejected")
        self.assertEqual(public["vendor_result_code"], 1002)
        self.assertNotIn("SECRET", json.dumps(public))

    def test_malformed_rows_and_untrusted_fields_are_not_copied(self):
        raw = {"resultCode": 1001, "ipc": [None, [], "PRIVATE", {"iotType": True, "devTypeID": "SECRET", "deviceP2P": "SECRET", "capability": "{", "hostKey": {"SECRET": "PRIVATE"}}]}
        public = self.module.summarize_inventory(raw)
        self.assertEqual(public["device_count"], 1)
        self.assertNotIn("SECRET", json.dumps(public))
        self.assertFalse(public["devices"][0]["host_key_present"])

    def test_output_is_bounded_but_total_is_retained(self):
        raw = {"resultCode": 1001, "ipc": [{}] * 600}
        public = self.module.summarize_inventory(raw)
        self.assertEqual(public["device_count"], 600)
        self.assertEqual(len(public["devices"]), 512)
        self.assertTrue(public["devices_truncated"])


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status = body, status
        self.content = self
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def iter_chunked(self, size):
        for index in range(0, len(self.body), size):
            yield self.body[index:index+size]


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


class InventoryRequestTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("meari_inventory")
        cls.session_module = load("meari_session")

    async def test_request_matches_sdk_post_and_closes_response(self):
        response = FakeResponse(json.dumps(device_response()).encode())
        session = FakeSession(response)
        public = await self.module.async_inspect_device_inventory(session, session_response())
        self.assertEqual(public["vendor_stage"], "vendor_devices_received")
        self.assertEqual(len(session.calls), 1)
        _, kwargs = session.calls[0]
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"].total, 20)
        self.assertFalse(kwargs["raise_for_status"])
        self.assertTrue(response.closed)

    async def test_invalid_endpoint_never_sends_token(self):
        session = FakeSession()
        raw = session_response()
        raw["miruiConfigResult"]["result"]["apiServer"] = "http://api.example.invalid"
        public = await self.module.async_inspect_device_inventory(session, raw)
        self.assertEqual(public["vendor_stage"], "inventory_request_data_invalid")
        self.assertEqual(session.calls, [])

    async def test_redirect_and_http_errors_are_not_followed(self):
        for status in (302, 401, 500):
            response = FakeResponse(b"PRIVATE", status)
            session = FakeSession(response)
            public = await self.module.async_inspect_device_inventory(session, session_response())
            self.assertEqual(public["vendor_http_status"], status)
            self.assertEqual(public["vendor_stage"], "vendor_http_error")
            self.assertEqual(len(session.calls), 1)
            self.assertTrue(response.closed)

    async def test_oversized_response_is_closed_and_rejected(self):
        response = FakeResponse(b" " * (self.module.MAX_BODY_BYTES + 1))
        public = await self.module.async_inspect_device_inventory(FakeSession(response), session_response())
        self.assertEqual(public["vendor_stage"], "vendor_response_too_large")
        self.assertTrue(response.closed)

    async def test_errors_do_not_echo_exception_credentials(self):
        for error in (self.module.aiohttp.ClientError("TOKEN-SECRET"), OSError("PRIVATE-URL"), asyncio.TimeoutError("TOKEN-SECRET")):
            public = await self.module.async_inspect_device_inventory(FakeSession(error=error), session_response())
            self.assertEqual(public["vendor_stage"], "vendor_request_failed")
            self.assertNotIn("PRIVATE", json.dumps(public))
            self.assertNotIn("SECRET", json.dumps(public))

    async def test_bad_json_and_deep_json_are_rejected_without_body_leak(self):
        cases = (
            (b"TOKEN-SECRET", {"vendor_request_failed"}),
            # Decoder recursion limits differ across Python releases. A decoded
            # array must still fail the vendor response structure check.
            (b"[" * 1200 + b"]" * 1200, {"vendor_request_failed", "invalid_device_response"}),
        )
        for body, stages in cases:
            response = FakeResponse(body)
            public = await self.module.async_inspect_device_inventory(FakeSession(response), session_response())
            self.assertIn(public["vendor_stage"], stages)
            self.assertNotIn("SECRET", json.dumps(public))
            self.assertNotIn("devices", public)
            self.assertTrue(response.closed)

    async def test_cancellation_is_propagated(self):
        with self.assertRaises(asyncio.CancelledError):
            await self.module.async_inspect_device_inventory(FakeSession(error=asyncio.CancelledError()), session_response())

    async def test_session_failure_does_not_query_vendor(self):
        client = types.SimpleNamespace(connected=True, send_meari_session=AsyncMock(return_value={"status": 1}))
        session = FakeSession()
        public = await self.session_module.async_inspect_video_session(types.SimpleNamespace(ssl_client=client), http_session=session)
        self.assertEqual(public["stage"], "session_rejected")
        self.assertEqual(session.calls, [])

    async def test_full_action_only_returns_sanitized_inventory(self):
        client = types.SimpleNamespace(connected=True, send_meari_session=AsyncMock(return_value=session_response()))
        session = FakeSession(FakeResponse(json.dumps(device_response()).encode()))
        public = await self.session_module.async_inspect_video_session(types.SimpleNamespace(ssl_client=client), http_session=session)
        self.assertEqual(public["stage"], "external_session_received")
        self.assertEqual(public["vendor_stage"], "vendor_devices_received")
        self.assertFalse(public["video_playback_implemented"])
        for secret in ("PRIVATE", "SECRET", "example.invalid", "123456"):
            self.assertNotIn(secret, json.dumps(public))

    async def test_service_registers_inventory_probe_with_shared_ha_session(self):
        handlers = load("service_handlers")
        registered = {}
        services = types.SimpleNamespace(async_register=lambda domain, name, fn, **kwargs: registered.setdefault(name, fn))
        coordinator = types.SimpleNamespace(ssl_client=None)
        hass = types.SimpleNamespace(bus=types.SimpleNamespace(async_listen_once=lambda *args: None), services=services, data={handlers.DOMAIN: {"entry": coordinator}})
        await handlers.async_register_services(hass)
        fake_http = types.ModuleType("homeassistant.helpers.aiohttp_client")
        fake_http.async_get_clientsession = lambda _: "HA-SESSION"
        with patch.dict(sys.modules, {"homeassistant.helpers.aiohttp_client": fake_http}), patch.object(handlers, "async_inspect_video_session", new_callable=AsyncMock) as probe:
            probe.return_value = {"stage": "external_session_received"}
            await registered[handlers.SERVICE_INSPECT_VIDEO_DEVICES](types.SimpleNamespace(data={}))
            probe.assert_awaited_once_with(coordinator, country_code="CN", phone_code="86", language="zh", http_session="HA-SESSION")


if __name__ == "__main__":
    unittest.main()
