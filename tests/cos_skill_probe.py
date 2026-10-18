"""Probe door lock media Skill authorization (protocol cmd=313 and COS signed downloads).

Background (confirmed by decompiling the APK):
- REST endpoint v2/cosToken/getCosToken issues credentials only for the log-upload bucket (applog-*).
  Using those credentials for door lock media returns 403 AccessDenied (previously confirmed).
- Door lock media downloads use Skill.GetCOSAuthorization (protocol cmd=313). The request body is
  {"request": "<inner JSON string>"}; the inner JSON contains namespace/requestId/version/
  userId/deviceId/familyId/uid/type=lock;
- The QueryTxAuthResponse.security response contains bucketName/region/endpoint/
  accessKeyId/accessKeySecret/securityToken/systemCurrentTime/expiration;
- After receiving credentials, download the object using a COS v5 (HMAC-SHA1) Authorization header.

This script reuses the REST login and SSL persistent-connection code in tests/orvibo_probe.py.
Credentials are read only from ORVIBO_USERNAME and ORVIBO_PASSWORD environment variables.

Usage:
  python tests/cos_skill_probe.py --list
  python tests/cos_skill_probe.py --object-key /uid/picturePicklockEvent/x.jpg --save out.jpg
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orvibo_probe import Https, Ssl, _is_lock_device  # noqa: E402
from orvibo_smart_control.const import (  # noqa: E402
    CMD_HEARTBEAT,
    CMD_HELLO,
    CMD_HANDSHAKE,
    CMD_LOGIN,
    DEFAULT_KEY,
    DEBUG_INFO,
    SOFTWARE_VER,
)
from orvibo_smart_control.functions import (  # noqa: E402
    generate_serial,
    generate_uuid,
)
from orvibo_smart_control.packet import HomematePacket  # noqa: E402

from cos_probe import cos_authorization, redact  # noqa: E402

LOGGER = logging.getLogger("cos_skill_probe")
CMD_COS_AUTH = 313


class CosSsl(Ssl):
    """Add a cmd=313 authorization request and single-response wait to the existing Ssl client."""

    async def request_cos_auth(
        self,
        user_id: str,
        device_id: str,
        device_uid: str,
        timeout: float = 20.0,
    ) -> Optional[Dict[str, Any]]:
        inner = {
            "namespace": "Skill.GetCOSAuthorization",
            "requestId": generate_uuid(),
            "version": 1,
            "userId": user_id,
            "deviceId": device_id,
            "familyId": self.family_id,
            "uid": device_uid,
            "type": "lock",
        }
        payload = {
            "request": json.dumps(inner, separators=(",", ":")),
            "cmd": CMD_COS_AUTH,
            "serial": generate_serial(),
            "clientType": 1,
            "uniSerial": generate_serial(use_time=True),
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        LOGGER.info("cmd=313 sent: deviceId=%s uid=%s", device_id, device_uid)
        await self._send(payload, self.key)

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                hdr = await asyncio.wait_for(self.r.readexactly(42), timeout=5)
                ln = HomematePacket.parse_length(hdr)
                body = await asyncio.wait_for(self.r.readexactly(ln - 42), timeout=10)
            except asyncio.TimeoutError:
                continue
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                LOGGER.error("SSL connection interrupted")
                return None
            try:
                pkt = HomematePacket(
                    hdr + body, {(self.sid or ""): self.key or DEFAULT_KEY.encode()}
                )
            except Exception:
                continue
            d = pkt.json_payload
            if not isinstance(d, dict):
                continue
            cmd = d.get("cmd")
            if cmd == CMD_HELLO:
                kv = d.get("key")
                if kv:
                    self.key, self.sid = str(kv).encode(), bytes(pkt.session_id).decode()
                continue
            if cmd in (CMD_LOGIN, CMD_HEARTBEAT, CMD_HANDSHAKE):
                continue
            if cmd == CMD_COS_AUTH:
                LOGGER.info("cmd=313 response received")
                return d
            LOGGER.debug("Ignoring intermediate packet cmd=%s", cmd)
        LOGGER.error("Timed out waiting for cmd=313 response")
        return None


def build_cos_token(security: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize QueryTxAuthResponse.Security to the token structure used by cos_probe."""
    if not security:
        raise RuntimeError("security is empty")
    return {
        "secretId": security.get("accessKeyId") or "",
        "secretKey": security.get("accessKeySecret") or "",
        "sessionToken": security.get("securityToken") or "",
        "bucket": security.get("bucketName") or "",
        "region": security.get("region") or "ap-guangzhou",
        "expiration": security.get("expiration") or 1800,
        "systemCurrentTime": security.get("systemCurrentTime"),
        "endpoint": security.get("endpoint") or "",
    }


def build_download(
    token: Dict[str, Any],
    object_key: str,
    end_delta: Optional[int] = None,
) -> tuple[str, Dict[str, str]]:
    """Build a COS GET request using virtual-host style: {bucket}.cos.{region}.myqcloud.com.

    The server returns a regional endpoint (such as cos.ap-guangzhou.myqcloud.com).
    Accessing it directly is rejected by COS (Missing required header Appid). Bucket
    p20-doorlock-1251222210 already includes the app ID, so it is also the virtual host name.
    """
    region = token["region"]
    host = f"{token['bucket']}.cos.{region}.myqcloud.com"
    path = object_key if object_key.startswith("/") else "/" + object_key

    sys_time = token.get("systemCurrentTime")
    start = int(sys_time / 1000) if sys_time else int(time.time())
    duration = int(token.get("expiration") or 1800)
    if end_delta is not None:
        duration = min(duration, end_delta)
    # If local and system clocks differ, start from the later time so the signature stays in-window.
    start = max(start, int(time.time()))
    auth = cos_authorization(
        token["secretId"], token["secretKey"], "get", path, host, start, start + duration
    )
    url = f"https://{host}{path}"
    headers = {"Authorization": auth, "x-cos-security-token": token["sessionToken"]}
    return url, headers


_CONTENT_TYPE_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".h264": "video/h264",
    ".mp4": "video/mp4",
}


def build_signed_url(token: Dict[str, Any], object_key: str, ttl: int = 600) -> str:
    """Build a pre-signed URL that a browser can open directly (including x-cos-security-token).

    This uses the same algorithm as the integration's cos_media.signed_media_url. STS credentials
    must be included in the URL. COS may store Content-Type as text/html, so override it with
    response-content-type; that parameter is part of the signature.
    """
    host = f"{token['bucket']}.cos.{token['region']}.myqcloud.com"
    path = object_key if object_key.startswith("/") else "/" + object_key
    sys_time = token.get("systemCurrentTime")
    now = max(int(time.time()), int(sys_time / 1000) if sys_time else 0)
    dot = object_key.rfind(".")
    content_type = _CONTENT_TYPE_BY_EXT.get(object_key[dot:].lower()) if dot >= 0 else None
    query_params: Dict[str, str] = {}
    if content_type:
        query_params["response-content-type"] = content_type
    auth = cos_authorization(
        token["secretId"],
        token["secretKey"],
        "get",
        path,
        host,
        now,
        now + ttl,
        query_params=query_params or None,
    )
    query_prefix = ""
    if query_params:
        encoded = {
            quote(str(k), safe="-"): quote(str(v), safe="")
            for k, v in query_params.items()
        }
        query_prefix = "&".join(f"{k}={v}" for k, v in sorted(encoded.items())) + "&"
    token_part = f"&x-cos-security-token={quote(token['sessionToken'], safe='')}"
    return f"https://{host}{path}?{query_prefix}{auth}{token_part}"


def download_url(url: str, timeout: int = 30) -> bytes:
    """Simulate direct browser access without custom headers."""
    print(f"      Trying [direct browser access] {url[:120]}...")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        print(
            f"      Content-Type: {resp.headers.get('Content-Type')} | "
            f"Content-Length: {resp.headers.get('Content-Length')} | "
            f"Content-Disposition: {resp.headers.get('Content-Disposition') or '-'}"
        )
        return body


def download(token: Dict[str, Any], object_key: str, save: str) -> None:
    print(f"[5/5] Downloading {object_key}")
    variants = [
        ("Original", build_download(token, object_key)),
        ("Shorter signature window", build_download(token, object_key, end_delta=600)),
    ]
    body: bytes = b""
    for label, (url, headers) in variants:
        print(f"      Trying [{label}] {url}")
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
            print(f"      [{label}] succeeded: {len(body)} bytes")
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "replace")
            print(f"      [{label}] HTTP {e.code}: {err_body[:400]}")
            if e.code != 403:
                raise
    else:
        raise SystemExit("All variants were rejected; see the errors above")
    with open(save, "wb") as f:
        f.write(body)
    print(
        f"      Saved {len(body)} bytes -> {save} "
        f"(magic={body[:8].hex() if body else 'empty'})"
    )


def pick_lock_device(devs: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    locks = [d for d in devs if _is_lock_device(d)]
    if not locks:
        return None
    return locks[0]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Door lock media Skill authorization and COS download probe")
    parser.add_argument("--object-key", help="COS object key to download (such as /uid/picturePicklockEvent/x.jpg)")
    parser.add_argument("--save", default="cos_download.bin", help="Path for the downloaded file")
    parser.add_argument("--family-id", help="Family ID (uses the first family by default)")
    parser.add_argument("--device-id", help="Door lock deviceId (w- prefix; auto-detected by default)")
    parser.add_argument("--device-uid", help="Door lock uid (without w- prefix; auto-detected by default)")
    parser.add_argument("--list", action="store_true", help="List door locks only; do not download")
    parser.add_argument(
        "--url", action="store_true", help="Build and test a browser-ready pre-signed URL without saving a file"
    )
    args = parser.parse_args()

    username = os.environ.get("ORVIBO_USERNAME") or ""
    password = os.environ.get("ORVIBO_PASSWORD") or ""
    if not username or not password:
        print("❌ Set ORVIBO_USERNAME and ORVIBO_PASSWORD environment variables")
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    api = Https(username, password)
    if not await api.login():
        print("❌ Login failed")
        return 1
    print(f"[1/5] Login succeeded user_id={redact(api.uid, 6)}")

    fs = await api.families()
    if not fs:
        print("❌ No families found for this account")
        return 1
    if args.family_id:
        fam = next((f for f in fs if f.get("familyId") == args.family_id), None)
        if not fam:
            print(f"❌ Family not found: {args.family_id}")
            return 1
    else:
        fam = fs[0]
    fid = fam.get("familyId", "")
    fname = fam.get("familyName", "?")
    print(f"[2/5] Family: {fname} ({redact(fid, 6)})")

    devs = await api.devices(fid)
    if args.device_id and args.device_uid:
        dev = {"deviceId": args.device_id, "uid": args.device_uid}
        print(f"[3/5] Using specified door lock: deviceId={dev['deviceId']} uid={dev['uid']}")
    else:
        dev = pick_lock_device(devs)
        if not dev:
            print("❌ No door lock identified; specify --device-id or --device-uid")
            return 1
        print(f"[3/5] Door lock: {dev.get('deviceName', '?')} deviceId={dev.get('deviceId')} uid={dev.get('uid')}")
    if args.list:
        print(json.dumps(dev, ensure_ascii=False, default=str))
        return 0
    if not args.object_key:
        print("❌ Specify an object key with --object-key, or use --list to list devices only")
        return 2

    sslc = CosSsl(api.username, api.password, fid)
    if not await sslc.connect():
        print("❌ SSL connection or login failed")
        await api.close()
        return 1

    resp = await sslc.request_cos_auth(
        api.uid, dev.get("deviceId", ""), dev.get("uid", "")
    )
    await sslc.close()
    await api.close()
    if not resp:
        print("❌ Did not receive a cmd=313 response")
        return 1

    print(f"[4/5] cmd=313 response: {json.dumps(resp, ensure_ascii=False)[:500]}")
    response_json = resp.get("response")
    if isinstance(response_json, str):
        try:
            q = json.loads(response_json)
        except json.JSONDecodeError:
            q = None
    elif isinstance(response_json, dict):
        q = response_json
    else:
        q = None
    if not q:
        print(f"❌ Response is missing the response field: status={resp.get('status')} errorCode={resp.get('errorCode')}")
        return 1
    if q.get("namespace") != "Skill.GetCOSAuthorization":
        print(f"❌ Namespace mismatch: {q.get('namespace')}")
        return 1
    if q.get("status") not in (None, 0, "0"):
        print(f"❌ Authorization failed status={q.get('status')} errorCode={q.get('errorCode')}")
        return 1

    security = q.get("security") or {}
    token = build_cos_token(security)
    print(
        "[4/5] COS credentials "
        f"bucket={token['bucket']} region={token['region']} "
        f"endpoint={token['endpoint'] or '-'} "
        f"secretId={redact(token['secretId'])} expiration={token['expiration']}"
    )
    if not token["secretId"] or not token["bucket"]:
        print("❌ The security field is incomplete")
        return 1

    if args.url:
        signed = build_signed_url(token, args.object_key)
        print(f"[5/5] Pre-signed URL (opens directly in a browser):\n{signed}")
        body = download_url(signed)
        print(f"      Direct access succeeded: {len(body)} bytes (magic={body[:8].hex()})")
        return 0

    download(token, args.object_key, args.save)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
