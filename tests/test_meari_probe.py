"""Real child-process cleanup and HA service boundaries; no real devices."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_meari_session import load
from test_meari_inventory import FakeResponse, FakeSession, device_response, session_response


class ProbeProcessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load("meari_probe")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.script = Path(self.tmp.name) / "fake_worker.py"
        self.processes = []
        self.arguments = []
        self.real_spawn = asyncio.create_subprocess_exec

    async def spawn(self, *args, **kwargs):
        self.arguments.append((args, kwargs))
        process = await self.real_spawn(*args, **kwargs)
        self.processes.append(process)
        return process

    async def run_probe(self, code, timeout=2):
        self.script.write_text(code, encoding="utf-8")
        with patch.object(self.module.asyncio, "create_subprocess_exec", side_effect=self.spawn):
            return await self.module.async_run_video_probe(
                {"secret": "HOST-SECRET"}, timeout_seconds=timeout, _worker_path=self.script,
            )

    def assert_reaped(self):
        self.assertTrue(self.processes)
        for process in self.processes:
            self.assertIsNotNone(process.returncode)

    async def test_first_encoded_frame_stops_child_and_cannot_claim_decoded_playback(self):
        result = await self.run_probe('''import sys,json,time
request=json.loads(sys.stdin.readline())
print(request['secret'],file=sys.stderr,flush=True)
print(json.dumps({"probe_stage":"kcp_connect", "raw":request}),flush=True)
print(json.dumps({"probe_stage":"video_keyframe_received", "final":True,
    "codec":"h264", "video_frames":1, "video_bytes":1024,
    "keyframe_received":True, "parameter_sets_received":True,
    "decoded":True,"video_playback_implemented":True,"secret":request}),flush=True)
time.sleep(60)
''')
        self.assertEqual(result["probe_stage"], "video_keyframe_received")
        self.assertTrue(result["encoded_video_verified"])
        self.assertFalse(result["decoded"])
        self.assertTrue(result["video_playback_implemented"])
        self.assertFalse(result["real_device_video_verified"])
        self.assertTrue(result["worker_stopped"])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("HOST-SECRET", repr(self.arguments))
        self.assertEqual(self.arguments[0][0][1:3], ("-I", "-u"))
        self.assert_reaped()

    async def test_timeout_kills_actual_sleeping_child_and_retains_last_stage(self):
        start = time.monotonic()
        result = await self.run_probe('''import time
print('{"probe_stage":"turn_allocate"}',flush=True)
time.sleep(60)
''', timeout=0.8)
        self.assertEqual(result["probe_stage"], "probe_timeout")
        self.assertEqual(result["last_probe_stage"], "turn_allocate")
        self.assertLess(time.monotonic() - start, 3)
        self.assert_reaped()

    async def test_cancellation_during_spawn_reaps_child_before_propagating(self):
        self.script.write_text("import time;time.sleep(60)", encoding="utf-8")
        spawned = asyncio.Event()

        async def delayed_spawn(*args, **kwargs):
            process = await self.spawn(*args, **kwargs)
            spawned.set()
            await asyncio.sleep(0.15)
            return process

        with patch.object(self.module.asyncio, "create_subprocess_exec", side_effect=delayed_spawn):
            task = asyncio.create_task(self.module.async_run_video_probe(
                {}, timeout_seconds=2, _worker_path=self.script,
            ))
            await spawned.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assert_reaped()

    async def test_repeated_cancellation_during_cleanup_cannot_abandon_child(self):
        self.script.write_text("import time;time.sleep(60)", encoding="utf-8")
        cleanup_started = asyncio.Event()
        real_reap = self.module._reap

        async def delayed_reap(process):
            cleanup_started.set()
            await asyncio.sleep(0.15)
            await real_reap(process)

        with patch.object(self.module.asyncio, "create_subprocess_exec", side_effect=self.spawn), patch.object(self.module, "_reap", side_effect=delayed_reap):
            task = asyncio.create_task(self.module.async_run_video_probe(
                {}, timeout_seconds=0.2, _worker_path=self.script,
            ))
            await cleanup_started.wait()
            task.cancel()
            await asyncio.sleep(0.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assert_reaped()

    async def test_oversized_stdout_fails_and_drains_full_pipe_when_killing(self):
        result = await self.run_probe('''import sys,time
sys.stdout.write('PRIVATE-SECRET'*100000)
sys.stdout.flush()
time.sleep(60)
''')
        self.assertEqual(result["probe_stage"], "probe_failed")
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assert_reaped()

    async def test_invalid_stage_and_no_final_never_verify_video(self):
        for code in (
            "print('{\"probe_stage\":[],\"secret\":\"HOST-SECRET\"}',flush=True)",
            "print('{\"probe_stage\":\"video_keyframe_received\",\"keyframe_received\":true}',flush=True)",
        ):
            result = await self.run_probe(code)
            self.assertEqual(result["probe_stage"], "probe_failed")
            self.assertFalse(result["encoded_video_verified"])
            self.assert_reaped()

    async def test_keyframe_requires_parameters_codec_and_nonzero_counters(self):
        result = await self.run_probe("print('{\"probe_stage\":\"video_keyframe_received\",\"final\":true,\"video_frames\":true,\"video_bytes\":2048,\"codec\":\"SECRET\",\"keyframe_received\":true}',flush=True)")
        self.assertFalse(result["encoded_video_verified"])
        self.assertNotIn("video_frames", result)
        self.assertNotIn("codec", result)
        self.assert_reaped()

    async def test_oversized_private_input_is_rejected_before_spawn(self):
        with patch.object(self.module.asyncio, "create_subprocess_exec", side_effect=AssertionError):
            result = await self.module.async_run_video_probe({"secret":"X"*65536})
        self.assertEqual(result["probe_stage"], "invalid_context")


class ProbeActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_action_uses_fresh_private_session_and_releases_http_before_media(self):
        session_module = load("meari_session")
        probe_module = load("meari_probe")
        response = FakeResponse(json.dumps(device_response()).encode())
        http = FakeSession(response)
        raw = session_response()
        coordinator = types.SimpleNamespace(ssl_client=types.SimpleNamespace(
            connected=True, send_meari_session=AsyncMock(return_value=raw),
        ))

        async def probe(session, inventory, **kwargs):
            self.assertTrue(response.closed)
            self.assertIs(session, raw)
            self.assertEqual(inventory, device_response())
            self.assertEqual(kwargs, {"device_index":1,"channel_id":3,"timeout_seconds":35})
            return {"probe_stage":"device_unavailable","worker_stopped":True}

        package = session_module.__package__
        with patch.dict(sys.modules, {f"{package}.meari_probe":probe_module}), patch.object(probe_module, "async_probe_inventory", side_effect=probe):
            public = await session_module.async_inspect_video_session(
                coordinator, http_session=http,
                probe_options={"device_index":1,"channel_id":3,"timeout_seconds":35},
            )
        self.assertEqual(public["probe_stage"], "device_unavailable")
        self.assertNotIn("SECRET", json.dumps(public))

    async def test_duplicate_probe_is_rejected_and_unload_waits_for_cleanup(self):
        module = load("meari_probe")
        session_module = load("meari_session")
        coordinator = object()
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def blocked(*args, **kwargs):
            started.set()
            try:
                await asyncio.Future()
            finally:
                await asyncio.sleep(0.01)
                stopped.set()

        with patch.dict(sys.modules, {f"{module.__package__}.meari_session":session_module}), patch.object(session_module,"async_inspect_video_session",side_effect=blocked):
            task = asyncio.create_task(module.async_probe_video_stream(
                coordinator,http_session=None,device_index=2,channel_id=1,
            ))
            await started.wait()
            duplicate = await module.async_probe_video_stream(
                coordinator,http_session=None,device_index=2,channel_id=1,
            )
            self.assertEqual(duplicate["probe_stage"],"probe_in_progress")
            await module.async_cancel_video_probes(coordinator)
            self.assertTrue(stopped.is_set())
            self.assertTrue(task.cancelled())
            self.assertNotIn(id(coordinator),module._ACTIVE)

    async def test_service_requires_explicit_device_and_channel_and_validates_without_io(self):
        handlers = load("service_handlers")
        registered = {}
        listeners = {}
        coordinator = object()
        hass = types.SimpleNamespace(
            data={handlers.DOMAIN:{"entry":coordinator}},
            services=types.SimpleNamespace(async_register=lambda domain,name,fn,**kw:registered.setdefault(name,fn)),
            bus=types.SimpleNamespace(async_listen_once=lambda event,fn:listeners.setdefault(event,fn)),
        )
        await handlers.async_register_services(hass)
        fn = registered[handlers.SERVICE_PROBE_VIDEO_STREAM]
        fake_http = types.ModuleType("homeassistant.helpers.aiohttp_client")
        fake_http.async_get_clientsession = lambda _: "HA-SESSION"
        with patch.dict(sys.modules,{"homeassistant.helpers.aiohttp_client":fake_http}),patch.object(handlers,"async_probe_video_stream",new_callable=AsyncMock) as probe:
            for data in ({},{"device_index":2},{"device_index":True,"channel_id":1},{"device_index":2,"channel_id":-1},{"device_index":2,"channel_id":1,"timeout_seconds":600}):
                result = await fn(types.SimpleNamespace(data=data))
                self.assertEqual(result["probe_stage"],"invalid_probe_parameters")
            probe.assert_not_awaited()
            await fn(types.SimpleNamespace(data={"device_index":2,"channel_id":3}))
            probe.assert_awaited_once_with(coordinator,http_session="HA-SESSION",device_index=2,channel_id=3,timeout_seconds=35,country_code="CN",phone_code="86",language="zh")
        with patch.object(handlers,"async_cancel_video_probes",new_callable=AsyncMock) as cancel:
            await listeners["homeassistant_stop"](None)
            cancel.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
