"""HDD service targeting is limited to registered recorder playback entities."""
import types
import unittest
from unittest.mock import AsyncMock
from test_service_handlers import _load_module


class HddServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = _load_module()
        self.handlers = {}
        def register(domain, name, handler, **kwargs):
            self.handlers[name] = handler
        self.entity = types.SimpleNamespace(entity_id="camera.hdd3",
            async_search_recordings=AsyncMock(return_value={"stage":"hdd_search_received", "fragments":[]}),
            async_select_recording=AsyncMock(), async_stop_recording=AsyncMock())
        self.hass = types.SimpleNamespace(data={"orvibo_smart_control_hdd":{"camera.hdd3":self.entity}},
            bus=types.SimpleNamespace(async_listen_once=lambda *args:None),
            services=types.SimpleNamespace(async_register=register))
        await self.module.async_register_services(self.hass)

    async def call(self, name, **data):
        return await self.handlers[name](types.SimpleNamespace(data=data))

    async def test_live_or_unknown_camera_cannot_trigger_hdd_commands(self):
        result = await self.call("start_hdd_playback", entity_id="camera.live", date="20261015090000")
        self.assertEqual(result["stage"], "hdd_playback_failed")
        self.entity.async_select_recording.assert_not_called()

    async def test_search_start_stop_use_same_registered_entity(self):
        result = await self.call("search_hdd_recordings", entity_id="camera.hdd3", date="20261015")
        self.assertEqual(result["entity_id"], "camera.hdd3")
        self.entity.async_search_recordings.assert_awaited_once_with("day", "20261015")
        result = await self.call("start_hdd_playback", entity_id="camera.hdd3", date="20261015090000")
        self.assertEqual(result["stage"], "playback_selected")
        self.entity.async_select_recording.assert_awaited_once_with("20261015090000")
        result = await self.call("stop_hdd_playback", entity_id="camera.hdd3")
        self.assertEqual(result["stage"], "playback_stopped")
        self.entity.async_stop_recording.assert_awaited_once()

    async def test_private_exception_never_escapes_service_response(self):
        self.entity.async_search_recordings.side_effect = ValueError("PRIVATE-TOKEN")
        result = await self.call("search_hdd_recordings", entity_id="camera.hdd3", date="invalid")
        self.assertNotIn("PRIVATE", repr(result))
        self.assertEqual(result["stage"], "hdd_query_failed")
