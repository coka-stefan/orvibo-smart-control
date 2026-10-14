"""Boundary and request-lifecycle tests; these do not validate real video."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).parents[1] / "custom_components" / "orvibo_smart_control"
PACKAGE = "orvibo_meari_session_tests"


def load(name):
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules.setdefault(PACKAGE, package)
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.ServiceCall = object
    core.SupportsResponse = types.SimpleNamespace(OPTIONAL="optional")
    with patch.dict(sys.modules, {"homeassistant.core": core}):
        return importlib.import_module(f"{PACKAGE}.{name}")


def response():
    return {
        "cmd": 148, "status": 0, "thirdAppType": "1",
        "miruiConfigResult": json.dumps({"result": {
            "apiServer": "https://api.example.invalid/?secret=CONFIG-SECRET",
            "partnerId": "1", "pfApi": {"platform": {
                "domain": "https://platform.example.invalid", "signature": "PLATFORM-SECRET",
            }},
        }}),
        "miruiTokenResult": json.dumps({"result": {
            "userID": 123456, "userToken": "TOKEN-SECRET", "userAccount": "PRIVATE-ACCOUNT",
            "clientId": "PRIVATE-CLIENT", "iot": {"pfKey": {"accesskey": "IOT-SECRET"}},
        }}),
        "message": "PRIVATE-MESSAGE", "familyId": "PRIVATE-FAMILY",
    }


class SessionBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("meari_session")

    def test_apk_request_constants_and_family(self):
        payload = self.module.build_session_request("chosen-family")
        self.assertEqual({k: payload[k] for k in (
            "cmd", "familyId", "thirdAppType", "clientType", "countryCode", "phoneCode", "iotType", "lngType",
        )}, {"cmd": 148, "familyId": "chosen-family", "thirdAppType": "1", "clientType": 1,
             "countryCode": "CN", "phoneCode": "86", "iotType": "4", "lngType": "zh"})
        with self.assertRaises(ValueError):
            self.module.build_session_request("")

    def test_public_result_never_contains_replayable_data(self):
        raw = response()
        public = self.module.summarize_session_response(raw)
        self.assertEqual(public["stage"], "external_session_received")
        self.assertFalse(public["video_playback_implemented"])
        self.assertFalse(public["real_device_video_verified"])
        encoded = json.dumps(public)
        for secret in ("SECRET", "PRIVATE", "123456", "example.invalid"):
            self.assertNotIn(secret, encoded)
        self.assertIsInstance(raw["miruiTokenResult"], str)

    def test_mapping_and_json_responses_are_equivalent(self):
        raw = response()
        expected = self.module.summarize_session_response(raw)
        for key in ("miruiConfigResult", "miruiTokenResult"):
            raw[key] = json.loads(raw[key])
        self.assertEqual(self.module.summarize_session_response(raw), expected)

    def test_rejected_and_unrelated_response_cannot_be_ready(self):
        raw = response()
        for status in (1, -1, True, "0", None):
            raw["status"] = status
            self.assertNotEqual(self.module.summarize_session_response(raw)["stage"], "external_session_received")
        raw["status"] = 0
        raw["thirdAppType"] = "other"
        self.assertEqual(self.module.summarize_session_response(raw)["stage"], "unexpected_vendor")

    def test_corrupt_and_oversized_data_are_bounded(self):
        for value in (None, [], "{", "[]", "x" * 512001):
            raw = response()
            raw["miruiTokenResult"] = value
            self.assertEqual(self.module.summarize_session_response(raw)["stage"], "external_session_incomplete")

    def test_user_id_and_api_must_be_valid(self):
        for uid in (None, 0, "0", False, {}):
            raw = response()
            raw["miruiTokenResult"] = {"result": {"userID": uid, "userToken": "TOKEN-SECRET"}}
            self.assertEqual(self.module.summarize_session_response(raw)["stage"], "external_session_incomplete")
        raw = response()
        raw["miruiConfigResult"] = {"result": {"apiServer": "https://user:secret@example.invalid"}}
        self.assertEqual(self.module.summarize_session_response(raw)["stage"], "external_session_incomplete")


class SessionRequestTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("ssl_client")
        cls.session = load("meari_session")

    def client(self):
        client = self.module.SSLClient(object(), "cloud.invalid", 10002, "test-user", "A" * 32,
                                     "chosen-family", lambda _: None, lambda *_: None)
        client.connected = True
        client.session_key = b"0123456789abcdef"
        return client

    async def test_matching_response_and_stale_packet_isolation(self):
        client = self.client()

        async def send(payload, _key):
            stale = response() | {"serial": payload["serial"] + 1}
            client._handle_meari_session_response(stale)
            self.assertFalse(client._pending_requests.get("meari_session").done())
            valid = response() | {k: payload[k] for k in ("serial", "uniSerial", "familyId")}
            client._handle_meari_session_response(valid)

        client._send_packet = AsyncMock(side_effect=send)
        result = await client.send_meari_session(timeout=0.1)
        self.assertEqual(result["status"], 0)
        self.assertIsNone(client._meari_request_identity)
        self.assertIsNone(client._pending_requests.get("meari_session"))

    async def test_timeout_does_not_block_next_request(self):
        client = self.client()
        client._send_packet = AsyncMock()
        self.assertIsNone(await client.send_meari_session(timeout=0.001))
        self.assertIsNone(await client.send_meari_session(timeout=0.001))
        self.assertEqual(client._send_packet.await_count, 2)
        self.assertIsNone(client._pending_requests.get("meari_session"))

    async def test_failed_write_releases_only_its_request(self):
        client = self.client()
        other = client._pending_requests.register("cos_auth")
        client._send_packet = AsyncMock(side_effect=ConnectionError("failed"))
        with self.assertRaises(ConnectionError):
            await client.send_meari_session()
        self.assertFalse(other.done())
        self.assertIsNone(client._pending_requests.get("meari_session"))
        client._pending_requests.cancel_all()

    async def test_cancellation_releases_pending_session(self):
        client = self.client()
        started = asyncio.Event()

        async def send(*_):
            started.set()
            await asyncio.Future()

        client._send_packet = AsyncMock(side_effect=send)
        task = asyncio.create_task(client.send_meari_session())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(client._pending_requests.get("meari_session"))
        self.assertIsNone(client._meari_request_identity)

    async def test_existing_request_identity_is_not_overwritten(self):
        client = self.client()
        expected = {"serial": 7, "uniSerial": 8, "familyId": "chosen-family"}
        client._meari_request_identity = expected
        future = client._pending_requests.register("meari_session")
        with self.assertRaises(RuntimeError):
            await client.send_meari_session()
        self.assertIs(client._meari_request_identity, expected)
        client._pending_requests.discard("meari_session", future)

    async def test_service_never_starts_cloud_connection(self):
        client = self.client()
        client.connected = False
        client.send_meari_session = AsyncMock()
        result = await self.session.async_inspect_video_session(types.SimpleNamespace(ssl_client=client))
        self.assertEqual(result["stage"], "cloud_connection_required")
        client.send_meari_session.assert_not_awaited()

    async def test_listener_routes_credentials_without_raw_logging(self):
        client = self.client()
        payload = self.session.build_session_request("chosen-family")
        client._meari_request_identity = payload
        future = client._pending_requests.register("meari_session")
        raw = response() | {k: payload[k] for k in ("serial", "uniSerial", "familyId")}
        packet = types.SimpleNamespace(session_id=b"s" * 32, json_payload=raw)
        client.transport.readexactly = AsyncMock(side_effect=[b"h", b"b", asyncio.CancelledError()])
        with patch.object(self.module, "HomematePacket") as parser:
            parser.parse_length.return_value = 43
            parser.return_value = packet
            with self.assertLogs(self.module._LOGGER, level="DEBUG") as log:
                await client._listen_loop()
        self.assertIs(future.result(), raw)
        self.assertNotIn("TOKEN-SECRET", " ".join(log.output))
        self.assertNotIn("PRIVATE-ACCOUNT", " ".join(log.output))
        client._pending_requests.discard("meari_session", future)


class SessionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_requires_one_entry_and_valid_region(self):
        handlers = load("service_handlers")
        registered = {}
        services = types.SimpleNamespace(async_register=lambda domain, name, fn, **kwargs: registered.setdefault(name, fn))
        first = types.SimpleNamespace(ssl_client=None)
        hass = types.SimpleNamespace(services=services, data={handlers.DOMAIN: {"a": first, "b": first}})
        await handlers.async_register_services(hass)
        fn = registered[handlers.SERVICE_INSPECT_VIDEO_SESSION]
        self.assertEqual((await fn(types.SimpleNamespace(data={})))["stage"], "select_one_entry")
        with patch.object(handlers, "async_inspect_video_session", new_callable=AsyncMock) as probe:
            probe.return_value = {"stage": "external_session_received"}
            result = await fn(types.SimpleNamespace(data={"entry_id": "a"}))
            self.assertEqual(result["stage"], "external_session_received")
            probe.assert_awaited_once_with(first, country_code="CN", phone_code="86", language="zh")
            await fn(types.SimpleNamespace(data={"entry_id": "a", "phone_code": "SECRET"}))
            self.assertEqual(probe.await_count, 1)


if __name__ == "__main__":
    unittest.main()
