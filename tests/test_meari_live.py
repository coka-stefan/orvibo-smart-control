"""Stable identity, selected channel and private live bootstrap regressions."""
import asyncio
import copy
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).parents[1] / "custom_components" / "orvibo_smart_control"
PACKAGE = "orvibo_live_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
live = importlib.import_module(f"{PACKAGE}.meari_live")


def session_response():
    return {"status": 0, "thirdAppType": "1", "miruiConfigResult": {"result": {
        "apiServer": "https://api.example.invalid", "partnerId": "1",
        "pfApi": {"openapi": {"domain": "https://openapi.example.invalid"}},
    }}, "miruiTokenResult": {"result": {"userID": "123", "userToken": "TOKEN-SECRET"}}}


def inventory_response():
    return {"resultCode": 1001, "ipc": [{
        "deviceID": "ipc-vendor", "iotType": 3, "devTypeID": 2,
        "snNum": "123456789", "hostKey": "0123456789abcdef0123456789abcdef",
        "capability": {"caps": {"p2p": 2, "vtk": 4}},
    }], "nvr-neutral": [{
        "deviceID": "nvr-vendor", "iotType": 3, "devTypeID": 11,
        "snNum": "987654321", "hostKey": "0123456789abcdef0123456789abcdef",
        "capability": {"caps": {"p2p": 2, "dpc": 1}},
    }]}


def channels_response():
    return {"resultCode": 1001, "result": {"987654321": {
        "213": 8, "1015": json.dumps({"state": [
            {"channel": c, "state": int(c in (1, 3)), "type": 0} for c in range(1, 9)
        ]}), "67": [json.dumps({"channel": c, "caps": {"p2p": 2 if c in (1, 3) else 0, "vtk": 4}}) for c in range(1, 9)],
    }}}


SELECTED = {
    "orvibo-nvr": {"uid": "nvr-vendor", "device_name": "NVR"},
    "orvibo-ipc": {"uid": "ipc-vendor", "device_name": "Camera"},
}


class DescriptionTests(unittest.TestCase):
    def describe(self, inventory=None, channels=None, devices=None):
        return live.describe_live_cameras(
            session_response(), inventory if inventory is not None else inventory_response(),
            channels if channels is not None else channels_response(),
            devices if devices is not None else SELECTED,
        )

    def test_exact_uid_join_creates_online_channels_one_three_and_ipc_zero(self):
        descriptions = self.describe()
        self.assertEqual([(d.device_id, d.channel_id, d.is_nvr) for d in descriptions], [
            ("orvibo-nvr", 1, True), ("orvibo-nvr", 3, True), ("orvibo-ipc", 0, False),
        ])
        self.assertNotIn("nvr-vendor", repr(descriptions))

    def test_selection_and_missing_uid_never_guess_by_name_or_position(self):
        self.assertEqual(self.describe(devices={}), [])
        self.assertEqual(self.describe(devices={"a": {"device_name": "NVR"}}), [])
        self.assertEqual(self.describe(devices={"a": {"uid": "987654321", "device_name": "NVR"}}), [])
        self.assertEqual(len(self.describe(devices={"x": SELECTED["orvibo-ipc"]})), 1)

    def test_duplicate_vendor_identity_cannot_retarget_a_camera(self):
        inventory = inventory_response()
        inventory["nvr-neutral"].append(copy.deepcopy(inventory["nvr-neutral"][0]))
        self.assertEqual([d.device_id for d in self.describe(inventory=inventory)], ["orvibo-ipc"])

    def test_inventory_wrapping_preserves_identical_descriptions(self):
        inventory = inventory_response()
        wrapped = {"resultCode": 1001, "result": {k: v for k, v in inventory.items() if k != "resultCode"}}
        self.assertEqual(self.describe(inventory=wrapped), self.describe())

    def test_channel_offline_unsupported_transport_or_video_password_are_skipped(self):
        channels = channels_response()
        channels["result"]["987654321"]["67"] = [json.dumps({"channel": 1, "caps": {"p2p": 0}})]
        self.assertNotIn(1, [d.channel_id for d in self.describe(channels=channels)])
        for change in ({"isVideoSetPwd": 1}, {"iotType": 4}, {"devTypeID": 17}):
            inventory = inventory_response()
            inventory["nvr-neutral"][0].update(change)
            self.assertEqual([d.device_id for d in self.describe(inventory=inventory)], ["orvibo-ipc"])

    def test_unavailable_nvr_channels_do_not_invent_capacity_channels(self):
        channels = {"resultCode": 1001, "result": {"987654321": {"213": 8}}}
        self.assertEqual([d.device_id for d in self.describe(channels=channels)], ["orvibo-ipc"])


class BootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_resolves_vendor_id_again_after_inventory_reorder(self):
        bootstrap = live.LiveCameraBootstrap(object(), object())
        inventory = inventory_response()
        # A newly inserted IPC changes the old NVR's index from 2 to 3.
        other = copy.deepcopy(inventory["ipc"][0])
        other.update(deviceID="another-ipc", snNum="111222333")
        inventory["ipc"].insert(0, other)
        description = live.LiveCameraDescription("orvibo-nvr", "nvr-vendor", 3, True)
        with patch.object(bootstrap, "_inventory", AsyncMock(return_value=(session_response(), inventory))), patch.object(bootstrap, "_channels", AsyncMock(return_value=channels_response())):
            context = await bootstrap.context(description)
        self.assertEqual(context["device"]["snNum"], "987654321")
        self.assertEqual(context["channel_id"], 3)
        self.assertEqual(context["device"]["capability"]["caps"]["p2p"], 2)

    async def test_removed_device_or_new_offline_channel_fails_without_retargeting(self):
        bootstrap = live.LiveCameraBootstrap(object(), object())
        description = live.LiveCameraDescription("orvibo-nvr", "nvr-vendor", 1, True)
        with patch.object(bootstrap, "_inventory", AsyncMock(return_value=(session_response(), {"resultCode": 1001, "ipc": inventory_response()["ipc"]}))):
            with self.assertRaisesRegex(ValueError, "video_device_unavailable"):
                await bootstrap.context(description)
        with patch.object(bootstrap, "_inventory", AsyncMock(return_value=(session_response(), inventory_response()))), patch.object(bootstrap, "_channels", AsyncMock(return_value=channels_response())):
            with self.assertRaisesRegex(ValueError, "channel_offline"):
                await bootstrap.context(live.LiveCameraDescription("orvibo-nvr", "nvr-vendor", 2, True))

    async def test_discovery_queries_selected_recorders_only_and_refreshes_each_connection(self):
        bootstrap = live.LiveCameraBootstrap(object(), object())
        with patch.object(bootstrap, "_inventory", AsyncMock(return_value=(session_response(), inventory_response()))) as inventory, patch.object(bootstrap, "_channels", AsyncMock(return_value=channels_response())) as channels:
            descriptions = await bootstrap.discover({"a": SELECTED["orvibo-ipc"]})
            self.assertEqual(channels.call_args.args[1], [])
            await bootstrap.context(descriptions[0])
            await bootstrap.context(descriptions[0])
            self.assertEqual(inventory.await_count, 3)

    async def test_external_session_requests_are_serialized_and_cancel_releases_lock(self):
        bootstrap = live.LiveCameraBootstrap(object(), object())
        active = maximum = 0

        async def inventory():
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(0.03)
                return session_response(), inventory_response()
            finally:
                active -= 1

        description = live.LiveCameraDescription("orvibo-ipc", "ipc-vendor", 0, False)
        with patch.object(bootstrap, "_inventory", side_effect=inventory):
            await asyncio.gather(bootstrap.context(description), bootstrap.context(description))
            task = asyncio.create_task(bootstrap.context(description))
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bootstrap.context(description)
        self.assertEqual(maximum, 1)

    async def test_bootstrap_preserves_cloud_request_shape_and_releases_response(self):
        from test_meari_inventory import FakeResponse

        replies = [FakeResponse(json.dumps(inventory_response()).encode()), FakeResponse(json.dumps(channels_response()).encode())]
        http = types.SimpleNamespace(post=lambda *a, **k: replies[0], get=lambda *a, **k: replies[1])
        ssl = types.SimpleNamespace(connected=True, send_meari_session=AsyncMock(return_value=session_response()))
        descriptions = await live.LiveCameraBootstrap(types.SimpleNamespace(ssl_client=ssl), http).discover(SELECTED)
        self.assertEqual(len(descriptions), 3)
        self.assertTrue(all(response.closed for response in replies))
        ssl.send_meari_session.assert_awaited_once_with(country_code="CN", phone_code="86", language="zh")

    async def test_cloud_error_text_and_body_are_suppressed(self):
        from test_meari_inventory import FakeResponse

        for body, status in ((b"TOKEN-SECRET", 200), (b"TOKEN-SECRET", 403), (b"x" * 2000001, 200)):
            reply = FakeResponse(body, status=status)
            http = types.SimpleNamespace(post=lambda *a, **k: reply)
            with self.assertRaisesRegex(ValueError, "^video_cloud_unavailable$"):
                await live._request_json(http, "post", ("https://example.invalid", {}, {}))
            self.assertTrue(reply.closed)


if __name__ == "__main__":
    unittest.main()
