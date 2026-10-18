"""Tests for dependency-free video archive helpers."""

from __future__ import annotations

import http.server
import importlib.util
from pathlib import Path
import socketserver
import sys
import tempfile
import threading
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "orvibo_smart_control"
    / "video_archive.py"
)
SPEC = importlib.util.spec_from_file_location(
    "orvibo_smart_control_video_archive", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
video_archive = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = video_archive
SPEC.loader.exec_module(video_archive)


class InferEventNameTests(unittest.TestCase):
    def test_picklock(self) -> None:
        key = (
            "/77c139c4d27f4fa6a20e1f459849aa47/"
            "videoPicklockEvent/picklockEvent_1785652830.h264"
        )
        self.assertEqual(
            video_archive.infer_event_name(key), ("picklock", "1785652830")
        )

    def test_leave_home(self) -> None:
        key = "/uid/videoleaveHomeEvent/leaveHomeEvent_1785652883.h264"
        self.assertEqual(
            video_archive.infer_event_name(key), ("leavehome", "1785652883")
        )

    def test_picture_ring(self) -> None:
        # Doorbell images (pictureUploadRing) are not video objects and should not be classified as video events.
        key = "/uid/pictureUploadRing/ring_1785652287.jpg"
        self.assertIsNone(video_archive.infer_event_name(key))

    def test_unmatched(self) -> None:
        self.assertIsNone(video_archive.infer_event_name("/uid/random/file.bin"))

    def test_object_key_rejects_url_traversal_and_query(self) -> None:
        valid = "/uid/videoPicklockEvent/picklockEvent_1785652830.h264"
        self.assertEqual(video_archive.normalize_event_object_key(valid), valid)
        for unsafe in (
            "https://example.com/uid/videoPicklockEvent/picklockEvent_1.h264",
            "/uid/../videoPicklockEvent/picklockEvent_1.h264",
            "/uid/videoPicklockEvent/picklockEvent_1.h264?token=secret",
            "\\uid\\videoPicklockEvent\\picklockEvent_1.h264",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertIsNone(
                    video_archive.normalize_event_object_key(unsafe)
                )


class BuildMediaPathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_paths(self) -> None:
        key = (
            "/77c139c4d27f4fa6a20e1f459849aa47/"
            "videoPicklockEvent/picklockEvent_1785652830.h264"
        )
        paths = video_archive.build_media_paths(
            self.root, "w-test-door-lock-id", key
        )
        assert paths is not None
        h264, mp4 = paths
        self.assertEqual(
            h264,
            self.root
            / "orvibo_smart_control"
            / "w-test-door-lock-id"
            / "picklock_1785652830.h264",
        )
        self.assertEqual(mp4.suffix, ".mp4")

    def test_cached_video_uses_the_integration_archive_source(self) -> None:
        archiver = video_archive.VideoArchiver(self.root, None)
        key = "/uid/videoPicklockEvent/picklockEvent_1785652830.h264"
        h264, mp4 = archiver.paths_for("lock", key)
        mp4.parent.mkdir(parents=True, exist_ok=True)
        mp4.write_bytes(b"saved-video")
        result = archiver.archive("lock", key, "https://unused.invalid/video")
        self.assertEqual(result["media_id"],
                         "media-source://orvibo_smart_control/archive/lock/picklock_1785652830.mp4")
        self.assertEqual(result["video_file"], str(mp4))
        with self.assertRaises(ValueError):
            archiver.media_source_id(self.root / "private.mp4")

    def test_unmatched_returns_none(self) -> None:
        self.assertIsNone(
            video_archive.build_media_paths(self.root, "w-x", "/a/b.bin")
        )


class DownloadTests(unittest.TestCase):
    def test_download_from_http(self) -> None:
        payload = b"\x00\x01\x02JFIF-test-data" * 100

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # noqa: A003
                pass

        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as httpd:
            port = httpd.server_address[1]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                with tempfile.TemporaryDirectory() as td:
                    dest = Path(td) / "sub" / "out.h264"
                    ok = video_archive.download(
                        f"http://127.0.0.1:{port}/test.h264", dest
                    )
                    self.assertTrue(ok)
                    self.assertEqual(dest.read_bytes(), payload)
            finally:
                httpd.shutdown()


class TranscodeTests(unittest.TestCase):
    def test_no_ffmpeg_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.h264"
            dst = Path(td) / "out.mp4"
            src.write_bytes(b"fake")
            self.assertFalse(video_archive.transcode_to_mp4(src, dst, None))
            self.assertFalse(dst.exists())

    def test_ffmpeg_missing_binary_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.h264"
            dst = Path(td) / "out.mp4"
            src.write_bytes(b"fake")
            self.assertFalse(
                video_archive.transcode_to_mp4(
                    src, dst, "/nonexistent/ffmpeg-xyz"
                )
            )


if __name__ == "__main__":
    unittest.main()
