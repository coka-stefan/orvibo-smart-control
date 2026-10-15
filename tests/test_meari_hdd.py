"""Real child boundaries for finite recording queries, no actual recorder."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_meari_session import load


class HddQueryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load("meari_hdd")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worker = Path(self.tmp.name) / "worker.py"
        self.children = []
        self.real_spawn = asyncio.create_subprocess_exec

    async def spawn(self, *args, **kwargs):
        self.assertNotIn("PRIVATE", repr(args))
        child = await self.real_spawn(*args, **kwargs)
        self.children.append(child)
        return child

    async def query(self, code, operation="day", date="20261015", timeout=2):
        self.worker.write_text(code, encoding="utf-8")
        with patch.object(self.module.asyncio, "create_subprocess_exec", side_effect=self.spawn):
            result = await self.module.async_query_hdd(
                {"secret": "PRIVATE", "hdd": {"operation": operation, "date": date}},
                timeout_seconds=timeout, _worker_path=self.worker,
            )
        self.assertTrue(self.children)
        self.assertTrue(all(child.returncode is not None for child in self.children))
        return result

    async def test_large_valid_reply_is_returned_without_private_fields_and_child_reaped(self):
        result = await self.query('''import json,sys,time
json.loads(sys.stdin.readline())
print(json.dumps({"probe_stage":"hdd_search_start"}),flush=True)
print(json.dumps({"probe_stage":"hdd_search_received","hdd_operation":"day", "calendar_date":"20261015",
"final":True,"secret":"PRIVATE", "recording_count":256,"fragments_truncated":False,
"fragments":[{"start":"20261015090000","end":"20261015100000","secret":"PRIVATE"}]*256}),flush=True)
time.sleep(30)
''')
        self.assertEqual(result["stage"], "hdd_search_received")
        self.assertEqual(len(result["fragments"]), 256)
        self.assertNotIn("PRIVATE", json.dumps(result))

    async def test_malformed_dates_cross_day_and_duplicate_days_rejected(self):
        for rows in ([{"start":"20261016000000", "end":"20261016010000"}],
                     [{"start":"20261015250000", "end":"20261015260000"}],
                     [{"start":"20261015100000", "end":"20261015090000"}]):
            value = {"probe_stage":"hdd_search_received", "hdd_operation":"day", "calendar_date":"20261015",
                     "final": True, "fragments":rows,"recording_count":1,"fragments_truncated":False}
            result = await self.query("print(" + repr(json.dumps(value)) + ",flush=True)")
            self.assertEqual(result["stage"], "hdd_query_failed")
        with self.assertRaises(ValueError):
            self.module._public_search({"probe_stage":"hdd_search_received", "hdd_operation":"month",
                "calendar_date":"202610", "recording_days":["20261001", "20261001"]}, {"operation":"month","date":"202610"})

    async def test_timeout_and_unknown_stage_are_fixed_public_errors(self):
        result = await self.query("import time;print('{\"probe_stage\":\"turn_allocate\"}',flush=True);time.sleep(30)", timeout=.3)
        self.assertEqual(result, {"stage":"hdd_query_timeout", "last_worker_stage":"turn_allocate"})
        result = await self.query("print('{\"probe_stage\":\"PRIVATE\"}',flush=True)")
        self.assertEqual(result["stage"], "hdd_query_failed")
        self.assertNotIn("PRIVATE", repr(result))

    async def test_cancellation_while_spawning_waits_for_child_cleanup(self):
        self.worker.write_text("import time;time.sleep(30)", encoding="utf-8")
        ready = asyncio.Event()
        async def delayed(*args, **kwargs):
            child = await self.spawn(*args, **kwargs)
            ready.set()
            await asyncio.sleep(.05)
            return child
        with patch.object(self.module.asyncio, "create_subprocess_exec", side_effect=delayed):
            task = asyncio.create_task(self.module.async_query_hdd(
                {"hdd":{"operation":"day", "date":"20261015"}}, _worker_path=self.worker,
            ))
            await ready.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(self.children[0].returncode)

    async def test_output_flood_is_killed_without_returning_bytes(self):
        result = await self.query("import sys,time;sys.stdout.write('PRIVATE'*100000);sys.stdout.flush();time.sleep(30)")
        self.assertEqual(result["stage"], "hdd_query_failed")
        self.assertNotIn("PRIVATE", repr(result))
