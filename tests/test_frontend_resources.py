"""Dashboard registration and real static HTTP resources for bundled cards."""
import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientSession, web
from test_meari_session import load


class ResourceCollection:
    def __init__(self, items=()):
        self.stored = [dict(row) for row in items]
        self.items = []
        self.loaded = False
        self.creates = []
        self.updates = []

    async def async_get_info(self):
        if not self.loaded:
            self.items = self.stored
            self.loaded = True

    def async_items(self):
        if not self.loaded:
            raise AssertionError("read before collection loaded")
        return self.items

    async def async_create_item(self, values):
        self.creates.append(values)
        self.items.append({"id":str(len(self.items)), "url":values["url"], "type":values["res_type"]})

    async def async_update_item(self, identifier, values):
        self.updates.append((identifier, values))
        row = next(row for row in self.items if row["id"] == identifier)
        row.update(url=values["url"], type=values["res_type"])


@dataclass
class StaticPathConfig:
    url_path: str
    path: str
    cache_headers: bool


class FrontendResourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load("frontend_resources")
        self.frontend = types.ModuleType("homeassistant.components.frontend")
        self.frontend.add_extra_js_url = MagicMock()
        self.http_module = types.ModuleType("homeassistant.components.http")
        self.http_module.StaticPathConfig = StaticPathConfig
        components = types.ModuleType("homeassistant.components")
        components.frontend = self.frontend
        self.modules = patch.dict(sys.modules, {"homeassistant.components":components,
            "homeassistant.components.frontend":self.frontend, "homeassistant.components.http":self.http_module})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.collection = ResourceCollection()
        self.hass = types.SimpleNamespace(data={"lovelace":types.SimpleNamespace(resource_mode="storage", resources=self.collection)},
            http=types.SimpleNamespace(async_register_static_paths=AsyncMock()), is_running=False,
            bus=types.SimpleNamespace(async_listen_once=MagicMock()))
        async def executor(fn, *args):
            return fn(*args)
        self.hass.async_add_executor_job = executor

    async def test_fresh_setup_registers_both_modules_and_second_setup_is_idempotent(self):
        await self.module.async_register_card_resources(self.hass)
        await self.module.async_register_card_resources(self.hass)
        self.assertEqual(len(self.collection.creates), 2)
        self.assertTrue(all(row["res_type"] == "module" for row in self.collection.creates))
        self.hass.http.async_register_static_paths.assert_awaited_once()
        nvr = self.collection.items[1]
        self.assertIn("orvibo-smart-control-nvr-card.js?v=", nvr["url"])
        path = Path(self.module.__file__).parent / "www/orvibo-smart-control-nvr-card.js"
        self.assertTrue(nvr["url"].endswith(hashlib.sha256(path.read_bytes()).hexdigest()[:16]))

    async def test_lazily_loads_and_updates_manual_old_url_preserving_unrelated_resources(self):
        self.collection.stored = [
            {"id":"old","url":self.module.BASE_URL + "/orvibo-smart-control-nvr-card.js?v=old","type":"js"},
            {"id":"user","url":"/local/my-card.js","type":"module"}]
        await self.module.async_register_card_resources(self.hass)
        self.assertEqual(len(self.collection.creates), 1)
        self.assertEqual(self.collection.updates[0][0], "old")
        self.assertEqual(self.collection.stored[0]["type"], "module")
        self.assertEqual(self.collection.stored[1]["url"], "/local/my-card.js")

    async def test_frontend_registration_failure_does_not_skip_nvr_or_storage(self):
        self.frontend.add_extra_js_url.side_effect = [RuntimeError("door failure"), None]
        with self.assertLogs(self.module.__name__, "ERROR"):
            await self.module.async_register_card_resources(self.hass)
        self.assertEqual(self.frontend.add_extra_js_url.call_count, 2)
        self.assertEqual(len(self.collection.creates), 2)

    async def test_dictionary_lovelace_data_and_legacy_http_api(self):
        self.hass.data["lovelace"] = {"mode":"storage", "resources":self.collection}
        self.hass.http = types.SimpleNamespace(register_static_path=MagicMock())
        await self.module.async_register_card_resources(self.hass)
        self.assertEqual(len(self.collection.creates), 2)
        self.hass.http.register_static_path.assert_called_once()

    async def test_yaml_resources_remain_owned_by_user_and_global_modules_registered(self):
        self.hass.data["lovelace"] = types.SimpleNamespace(resource_mode="yaml", resources=object())
        await self.module.async_register_card_resources(self.hass)
        self.assertEqual(self.frontend.add_extra_js_url.call_count, 2)
        self.assertEqual(self.collection.creates, [])
        self.hass.bus.async_listen_once.assert_not_called()

    async def test_late_dashboard_setup_retries_once_after_start_without_duplicate_route(self):
        self.hass.data.pop("lovelace")
        await self.module.async_register_card_resources(self.hass)
        await self.module.async_register_card_resources(self.hass)
        self.hass.bus.async_listen_once.assert_called_once()
        event, callback = self.hass.bus.async_listen_once.call_args.args
        self.assertEqual(event, "homeassistant_started")
        self.hass.data["lovelace"] = types.SimpleNamespace(resource_mode="storage", resources=self.collection)
        await callback(None)
        self.assertEqual(len(self.collection.creates), 2)
        self.hass.http.async_register_static_paths.assert_awaited_once()

    async def test_static_route_serves_actual_nvr_script_with_javascript_mime_and_version(self):
        app = web.Application()
        async def register(configs):
            for config in configs:
                app.router.add_static(config.url_path, config.path)
        self.hass.http.async_register_static_paths.side_effect = register
        await self.module.async_register_card_resources(self.hass)
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            origin = f"http://127.0.0.1:{runner.addresses[0][1]}"
            async with ClientSession() as client:
                async with client.get(origin + self.collection.items[1]["url"]) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(response.content_type, ("application/javascript", "text/javascript"))
                    body = await response.read()
                    self.assertEqual(body, (Path(self.module.__file__).parent / "www/orvibo-smart-control-nvr-card.js").read_bytes())
        finally:
            await runner.cleanup()
