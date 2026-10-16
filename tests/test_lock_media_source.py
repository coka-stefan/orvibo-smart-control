"""Archive media must resolve and serve only within the private integration root."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from test_meari_session import load


class MediaSourceContract:
    def __init__(self, domain):
        self.domain = domain


class MediaError(Exception):
    pass


class LockMediaSourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        source = types.ModuleType("homeassistant.components.media_source")
        source.MediaSource = MediaSourceContract
        source.BrowseMediaSource = lambda **kwargs: types.SimpleNamespace(**kwargs)
        source.PlayMedia = lambda url, mime_type: types.SimpleNamespace(url=url, mime_type=mime_type)
        source.Unresolvable = MediaError
        player = types.ModuleType("homeassistant.components.media_player")
        player.BrowseError = MediaError
        player.MediaClass = types.SimpleNamespace(DIRECTORY="directory", IMAGE="image", VIDEO="video")
        http = types.ModuleType("homeassistant.components.http")
        http.HomeAssistantView = object
        self.modules = patch.dict(sys.modules, {module.__name__: module for module in (source, player, http)})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.source_module = load("media_source")
        self.history = load("history")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media_root = Path(self.temp.name) / "config/media"
        self.hass = types.SimpleNamespace(
            config=types.SimpleNamespace(path=lambda name: str(self.media_root), media_dirs={"local": "/media"}),
            http=types.SimpleNamespace(register_view=MagicMock()),
            async_add_executor_job=asyncio.to_thread,
        )
        self.source = await self.source_module.async_get_media_source(self.hass)
        self.view = self.hass.http.register_view.call_args.args[0]

    def item(self, identifier):
        return types.SimpleNamespace(domain="orvibo_smart_control", identifier=identifier)

    def save_capture(self):
        archive = self.history.history_dir(self.media_root, "lock")
        return self.history.save_snapshot(archive, "ring", 100, b"saved-image")

    async def test_existing_captures_resolve_without_default_local_media_directory(self):
        capture = self.save_capture()
        event = self.history.list_history(self.media_root, "lock", media_type="image")[0]
        parsed = urlsplit(event["media_id"])
        resolved = await self.source.async_resolve_media(self.item(parsed.path.lstrip("/")))
        self.assertEqual(resolved.url, "/api/orvibo_smart_control/media/archive/lock/ring_100.jpg")
        self.assertEqual(resolved.mime_type, "image/jpeg")
        response = await self.view.get(None, parsed.path.lstrip("/"))
        self.assertEqual(response._path, capture.resolve())
        self.assertEqual(self.hass.config.media_dirs, {"local": "/media"})
        self.hass.http.register_view.assert_called_once()
        self.assertIs(self.view.source, self.source)
        self.assertTrue(self.view.requires_auth)

    async def test_only_private_archive_paths_can_be_resolved_or_served(self):
        self.save_capture()
        for identifier in ("local/lock/ring_100.jpg", "archive/../../private.jpg",
                           "archive/../private.jpg", "archive/lock\\ring_100.jpg"):
            with self.subTest(identifier=identifier):
                with self.assertRaises(MediaError):
                    await self.source.async_resolve_media(self.item(identifier))
                with self.assertRaises(web.HTTPNotFound):
                    await self.view.get(None, identifier)
        with self.assertRaises(MediaError):
            await self.source.async_resolve_media(types.SimpleNamespace(domain="other", identifier="archive"))
        for outside in (self.media_root / "other.jpg", self.media_root.parent / "private.jpg"):
            with self.assertRaises(ValueError):
                self.history.media_source_id(self.media_root, outside)

    async def test_missing_files_and_non_media_are_not_served(self):
        capture = self.save_capture()
        (capture.parent / "private.txt").write_text("private", encoding="utf-8")
        for identifier in ("archive/lock/missing.jpg", "archive/lock/private.txt", "archive/lock"):
            with self.assertRaises(MediaError):
                await self.source.async_resolve_media(self.item(identifier))
            with self.assertRaises(web.HTTPNotFound):
                await self.view.get(None, identifier)

    async def test_browser_lists_existing_media_and_handles_no_captures(self):
        empty = await self.source.async_browse_media(self.item(""))
        self.assertEqual(empty.children, [])
        capture = self.save_capture()
        (capture.parent / "ring_101.mp4").write_bytes(b"saved-video")
        (capture.parent / "private.txt").write_text("private", encoding="utf-8")
        (capture.parent / ".hidden.jpg").write_bytes(b"hidden")
        root = await self.source.async_browse_media(self.item(""))
        self.assertEqual([child.identifier for child in root.children], ["archive/lock"])
        folder = await self.source.async_browse_media(self.item("archive/lock"))
        self.assertEqual([child.title for child in folder.children], ["ring_100.jpg", "ring_101.mp4"])
        self.assertTrue(all(child.can_play for child in folder.children))
        self.assertEqual([child.media_class for child in folder.children], ["image", "video"])
        with self.assertRaises(MediaError):
            await self.source.async_browse_media(self.item("archive/../../private"))

    async def test_resolved_capture_url_serves_original_bytes_over_http(self):
        self.save_capture()
        app = web.Application()
        async def get(request):
            return await self.view.get(request, request.match_info["identifier"])
        app.router.add_get(self.view.url, get)
        async with TestClient(TestServer(app)) as client:
            resolved = await self.source.async_resolve_media(self.item("archive/lock/ring_100.jpg"))
            async with client.get(resolved.url) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.content_type, "image/jpeg")
                self.assertEqual(await response.read(), b"saved-image")
            async with client.get(self.source_module.URL_PREFIX + "/local/private.jpg") as response:
                self.assertEqual(response.status, 404)

    async def test_media_source_dependency_is_loaded_before_integration(self):
        component = Path(self.source_module.__file__).parent
        manifest = json.loads((component / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("media_source", manifest["dependencies"])
