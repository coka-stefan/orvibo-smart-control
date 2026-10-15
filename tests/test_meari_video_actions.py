"""Exercise the channel action across Orvibo session, vendor list, and batch API."""
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_meari_session import load
from test_meari_inventory import FakeResponse, device_response, session_response
from test_meari_channels import batch_response


class CombinedSession:
    def __init__(self, inventory=None):
        self.inventory = device_response() if inventory is None else inventory
        self.calls = []
        self.responses = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        response = FakeResponse(json.dumps(self.inventory).encode())
        self.responses.append(response)
        return response

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        response = FakeResponse(json.dumps(batch_response()).encode())
        self.responses.append(response)
        return response


class VideoActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_channel_action_reuses_one_session_and_returns_no_secrets(self):
        session_module = load("meari_session")
        client = types.SimpleNamespace(connected=True, send_meari_session=AsyncMock(return_value=session_response()))
        http = CombinedSession()
        public = await session_module.async_inspect_video_session(
            types.SimpleNamespace(ssl_client=client), http_session=http, include_channels=True,
        )
        client.send_meari_session.assert_awaited_once()
        self.assertEqual([call[0] for call in http.calls], ["POST", "GET"])
        self.assertTrue(all(response.closed for response in http.responses))
        self.assertEqual(public["vendor_stage"], "vendor_devices_received")
        self.assertEqual(public["channel_stage"], "nvr_channels_received")
        self.assertEqual(public["nvrs"][0]["channel_count"], 2)
        self.assertTrue(public["channel_query_implemented"])
        self.assertFalse(public["video_playback_implemented"])
        self.assertFalse(public["real_device_video_verified"])
        for forbidden in ("PRIVATE", "SECRET", "example.invalid", "123456"):
            self.assertNotIn(forbidden, json.dumps(public))

    async def test_existing_device_action_does_not_query_channels(self):
        module = load("meari_inventory")
        http = CombinedSession()
        public = await module.async_inspect_device_inventory(http, session_response())
        self.assertEqual([call[0] for call in http.calls], ["POST"])
        self.assertFalse(public["channel_query_implemented"])
        self.assertNotIn("nvrs", public)

    async def test_rejected_inventory_prevents_channel_request(self):
        module = load("meari_inventory")
        http = CombinedSession({"resultCode": 1002, "error": "TOKEN-SECRET"})
        public = await module.async_inspect_device_inventory(http, session_response(), include_channels=True)
        self.assertEqual([call[0] for call in http.calls], ["POST"])
        self.assertEqual(public["vendor_stage"], "vendor_request_rejected")
        self.assertNotIn("SECRET", json.dumps(public))

    async def test_channel_action_uses_shared_ha_http_session_and_validates_target(self):
        handlers = load("service_handlers")
        registered = {}
        services = types.SimpleNamespace(async_register=lambda domain, name, fn, **kwargs: registered.setdefault(name, fn))
        coordinator = types.SimpleNamespace(ssl_client=None)
        hass = types.SimpleNamespace(services=services, data={handlers.DOMAIN: {"entry": coordinator}})
        await handlers.async_register_services(hass)
        handler = registered[handlers.SERVICE_INSPECT_VIDEO_CHANNELS]
        fake_http = types.ModuleType("homeassistant.helpers.aiohttp_client")
        fake_http.async_get_clientsession = lambda _: "HA-SESSION"
        with patch.dict(sys.modules, {"homeassistant.helpers.aiohttp_client": fake_http}), patch.object(handlers, "async_inspect_video_session", new_callable=AsyncMock) as probe:
            probe.return_value = {"stage": "external_session_received"}
            await handler(types.SimpleNamespace(data={}))
            probe.assert_awaited_once_with(coordinator, country_code="CN", phone_code="86", language="zh", http_session="HA-SESSION", include_channels=True)
            self.assertEqual((await handler(types.SimpleNamespace(data={"entry_id": "unknown"})))["stage"], "select_one_entry")
            self.assertEqual((await handler(types.SimpleNamespace(data={"language": "invalid"})))["stage"], "invalid_region")
            self.assertEqual(probe.await_count, 1)

    async def test_shared_signer_cannot_override_identity_or_target_arbitrary_api(self):
        module = load("meari_inventory")
        for extra in ({"userID": "evil"}, {"signature": "evil"}, {"userToken": 1}, {"snIdentifier": "x" * 16385}):
            with self.subTest(extra_key=next(iter(extra))), self.assertRaises(ValueError):
                module.build_vendor_request(session_response(), module.DEVICE_LIST_PATH, extra)
        with self.assertRaises(ValueError):
            module.build_vendor_request(session_response(), "/v1/app/device/delete", {})


if __name__ == "__main__":
    unittest.main()
