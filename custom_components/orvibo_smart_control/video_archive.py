"""Lock event video archive: download .h264 event recordings and remux them to MP4.

For event recordings (tampering, away alerts, etc.), videoUrl is a COS object key that can be downloaded using a presigned URL.
The URL includes x-cos-security-token. Browsers and HA cannot play raw H.264
directly, so ffmpeg remuxes it losslessly (-c copy, no re-encoding) to MP4 and saves it in
the standard HA media directory for use by the media browser and notifications.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Event video object keys look like /uid/videoPicklockEvent/picklockEvent_<ts>.h264
_EVENT_PATTERN = re.compile(
    r"/(?:video|picture)([A-Za-z]+)Event/(?:[A-Za-z]+)_(\d+)\.\w+$"
)


def _sanitize(name: str) -> str:
    """Sanitize filenames by keeping only alphanumeric characters, underscores, and hyphens."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name) or "device"


def _event_dir(media_root: Path, device_id: str) -> Path:
    """Event archive directory, matching history.history_dir."""
    d = Path(media_root) / "orvibo_smart_control" / _sanitize(device_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def infer_event_name(object_key: str) -> Optional[tuple[str, str]]:
    """Infer the event name and timestamp from an object key, e.g. ('picklock', '1785652830')."""
    m = _EVENT_PATTERN.search(object_key.replace("\\", "/"))
    if not m:
        return None
    return m.group(1).lower(), m.group(2)


def normalize_event_object_key(object_key: str) -> Optional[str]:
    """Validate a COS event key and return a canonical absolute object path."""
    value = str(object_key or "").strip()
    if (
        not value
        or len(value) > 1024
        or "\x00" in value
        or "\\" in value
        or "?" in value
        or "#" in value
        or "://" in value
    ):
        return None
    normalized = "/" + value.lstrip("/")
    if any(part in {"", ".", ".."} for part in normalized.split("/")[1:]):
        return None
    if infer_event_name(normalized) is None:
        return None
    return normalized


def build_media_paths(
    media_root: Path,
    device_id: str,
    object_key: str,
) -> Optional[tuple[Path, Path]]:
    """Return the (raw h264 path, target mp4 path), or None if the event name cannot be inferred."""
    object_key = normalize_event_object_key(object_key) or ""
    info = infer_event_name(object_key)
    if not info:
        return None
    kind, ts = info
    device_dir = media_root / "orvibo_smart_control" / _sanitize(device_id)
    base = device_dir / f"{kind}_{ts}"
    return base.with_suffix(".h264"), base.with_suffix(".mp4")


def find_ffmpeg() -> Optional[str]:
    """Find the ffmpeg executable (usually included in HA environments)."""
    return shutil.which("ffmpeg")


def download(url: str, dest: Path, timeout: int = 60) -> bool:
    """Download a presigned URL to the target path (blocking; callers should use an executor)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "orvibo_smart_control"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        tmp.replace(dest)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            _LOGGER.warning(
                "Video object does not exist (it may have expired or not finished uploading): %s", dest.name
            )
        else:
            _LOGGER.warning(
                "Video download HTTP %s: %s",
                e.code,
                e.read(300).decode("utf-8", "replace")[:200],
            )
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    except (urllib.error.URLError, OSError) as e:
        _LOGGER.warning("Video download failed: %s", e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def transcode_to_mp4(src: Path, dest: Path, ffmpeg: Optional[str]) -> bool:
    """Losslessly remux h264 to mp4 with ffmpeg -c copy; return False when ffmpeg is unavailable.

    Delete the original h264 after successful remux to avoid duplicate storage; keep it for manual handling on failure.
    """
    if not ffmpeg or not src.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _LOGGER.warning("ffmpeg remux failed: %s", e)
        return False
    if proc.returncode != 0 or not tmp.exists():
        _LOGGER.warning("ffmpeg remux returned %s: %s", proc.returncode, proc.stderr.strip()[:300])
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    tmp.replace(dest)
    try:
        src.unlink(missing_ok=True)
    except OSError:
        pass
    return True


class VideoArchiver:
    """Download, remux, and manage event video files."""

    def __init__(
        self,
        media_root: Path,
        ffmpeg: Optional[str] = None,
    ) -> None:
        self._media_root = Path(media_root)
        self._ffmpeg = ffmpeg if ffmpeg else find_ffmpeg()

    @property
    def ffmpeg_available(self) -> bool:
        return self._ffmpeg is not None

    def paths_for(self, device_id: str, object_key: str) -> Optional[tuple[Path, Path]]:
        """Calculate deterministic file paths from the object key (raw h264 and target mp4)."""
        return build_media_paths(self._media_root, device_id, object_key)

    def event_paths(
        self, device_id: str, kind: str, ts: int | str
    ) -> tuple[Path, Path]:
        """Calculate paths from event type and timestamp, matching snapshot history naming."""
        kind = re.sub(r"[^A-Za-z0-9_]", "_", str(kind)) or "event"
        base = _event_dir(self._media_root, device_id) / f"{kind}_{ts}"
        return base.with_suffix(".h264"), base.with_suffix(".mp4")

    def media_source_id(self, mp4_path: Path) -> str:
        """Reference the same private archive source as snapshot history."""
        archive = self._media_root / "orvibo_smart_control"
        rel = mp4_path.resolve().relative_to(archive.resolve())
        return f"media-source://orvibo_smart_control/archive/{rel.as_posix()}"

    def archive(
        self,
        device_id: str,
        object_key: str,
        url: str,
    ) -> Optional[dict[str, str]]:
        """Download and remux a recording; return {h264_file, mp4_file, media_id} or None."""
        paths = self.paths_for(device_id, object_key)
        if paths is None:
            return None
        h264_path, mp4_path = paths
        if mp4_path.exists() and mp4_path.stat().st_size > 0:
            # Already archived; deduplicate the same event
            return self._result(h264_path, mp4_path)
        if not download(url, h264_path):
            return None
        transcode_to_mp4(h264_path, mp4_path, self._ffmpeg)
        return self._result(h264_path, mp4_path)

    def archive_event(
        self,
        device_id: str,
        kind: str,
        ts: int | str,
        url: str,
    ) -> Optional[dict[str, str]]:
        """Archive the recording by event type and timestamp using consistent history naming."""
        h264_path, mp4_path = self.event_paths(device_id, kind, ts)
        if mp4_path.exists() and mp4_path.stat().st_size > 0:
            return self._result(h264_path, mp4_path)
        if not download(url, h264_path):
            return None
        transcode_to_mp4(h264_path, mp4_path, self._ffmpeg)
        return self._result(h264_path, mp4_path)

    def _result(self, h264_path: Path, mp4_path: Path) -> dict[str, str]:
        video_file = str(mp4_path if mp4_path.exists() else h264_path)
        media_id = (
            self.media_source_id(mp4_path)
            if mp4_path.exists()
            else ""
        )
        return {
            "h264_file": str(h264_path),
            "mp4_file": str(mp4_path),
            "video_file": video_file,
            "media_id": media_id,
        }
