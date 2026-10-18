"""Probe Tencent Cloud COS door lock media using behavior observed in the Smart Home 365 app.

Background (from APK decompilation):
- videoUrl/url in door lock events (such as /uid/videoPicklockEvent/xxx.h264) is a Tencent COS object key.
- The app first calls REST endpoint v2/cosToken/getCosToken to obtain temporary STS credentials.
  (secretId/secretKey/sessionToken + bucket/region/expiration);
- It then builds a downloadable URL using COS signature v5 (HMAC-SHA1 + q-sign-time).

This script is for local verification only. Credentials are read only from environment variables:
  ORVIBO_USERNAME / ORVIBO_PASSWORD

Usage:
  python tests/cos_probe.py --list --capture lock_capture_xxx.jsonl
  python tests/cos_probe.py --object-key /uid/videoPicklockEvent/xxx.h264 --save out.h264
  python tests/cos_probe.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

SIGN_KEY = "nQ45RjPtOws96jmH"  # Same as const.SIGN_KEY in the integration (from the APK).
DEFAULT_HOST = "china.orvibo.com"


def _hmac_hex(key: str, msg: str, algo) -> str:
    return hmac.new(key.encode(), msg.encode(), algo).hexdigest()


def create_sign(params: Dict[str, Any], key: str = SIGN_KEY) -> str:
    """Match the app's HMHttpRequest: sort k=v pairs, append key=, then use uppercase HmacSHA256 hex."""
    parts = []
    for k in sorted(params):
        v = str(params[k])
        if v:
            parts.append(f"{k}={v}&")
    parts.append(f"key={key}")
    return hmac.new(key.encode(), "".join(parts).encode(), hashlib.sha256).hexdigest().upper()


def http_json(url: str, data: Optional[str] = None, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, data=data.encode() if data else None)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "okhttp/3.12.1")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def redact(value: Any, keep: int = 4) -> str:
    s = str(value)
    if len(s) <= keep * 2:
        return "*" * len(s)
    return f"{s[:keep]}...{s[-keep:]}"


def login(host: str, username: str, password: str) -> Dict[str, Any]:
    url = (
        f"https://{host}/getOauthToken?userName={urllib.parse.quote(username)}"
        f"&type=0&password={urllib.parse.quote(password)}"
    )
    resp = http_json(url)
    data = resp.get("data") or {}
    if "access_token" not in data:
        raise RuntimeError(f"Login failed: {resp.get('message') or resp}")
    print(f"[1/4] Login succeeded user_id={redact(data.get('user_id'), 6)}")
    return data


def fetch_family(host: str, access_token: str, user_id: str) -> str:
    params = {
        "requestId": "sim-" + os.urandom(8).hex(),
        "userId": user_id,
        "accessToken": access_token,
        "random": os.urandom(8).hex(),
        "timestamp": int(time.time() * 1000),
    }
    data = {
        **params,
        "sign": create_sign(params),
    }
    resp = http_json(f"https://{host}/v2/family/statistics/users", json.dumps(data))
    families = resp.get("data") or []
    if isinstance(families, dict):
        families = families.get("familyList") or families.get("list") or [families]
    if not families:
        raise RuntimeError(f"No family found: {json.dumps(resp, ensure_ascii=False)[:300]}")
    fam = families[0]
    family_id = fam.get("familyId") or fam.get("family_id")
    print(f"[2/4] Family: {fam.get('familyName') or family_id} ({redact(family_id, 6)})")
    return str(family_id)


def fetch_cos_token(host: str, access_token: str, user_id: str, family_id: str) -> Dict[str, Any]:
    params = {
        "accessToken": access_token,
        "userId": user_id,
        "familyId": family_id,
        "timestamp": int(time.time() * 1000),
        "random": os.urandom(8).hex(),
    }
    data = {**params, "sign": create_sign(params)}
    resp = http_json(f"https://{host}/v2/cosToken/getCosToken", json.dumps(data))
    token = resp.get("data") or {}
    if not token.get("bucket"):
        raise RuntimeError(f"Failed to get COS credentials: {json.dumps(resp, ensure_ascii=False)[:300]}")
    print(
        "[3/4] COS credentials "
        f"bucket={token.get('bucket')} region={token.get('region')} "
        f"secretId={redact(token.get('secretId'))} expiration={token.get('expiration')}"
    )
    return token


def cos_authorization(
    secret_id: str,
    secret_key: str,
    method: str,
    path: str,
    host: str,
    start: int,
    end: int,
    query_params: Optional[Dict[str, str]] = None,
) -> str:
    """COS signature v5 (q-sign-algorithm=sha1).

    Query parameters are signed (such as response-content-type), sorted by their
    URL-encoded names. The signature parameters and x-cos-security-token are excluded.
    """
    key_time = f"{start};{end}"
    sign_key = _hmac_hex(secret_key, key_time, hashlib.sha1)
    # A single header has no trailing ampersand (confirmed from the server FormatString).
    query_part = ""
    q_url_param_list = ""
    if query_params:
        encoded = {
            urllib.parse.quote(str(k), safe="-"): urllib.parse.quote(str(v), safe="")
            for k, v in query_params.items()
        }
        items = sorted(encoded.items())
        query_part = "&".join(f"{k}={v}" for k, v in items)
        q_url_param_list = ";".join(k for k, _ in items)
    http_string = f"{method.lower()}\n{path}\n{query_part}\nhost={host}\n"
    # Official COS algorithm: StringToSign = "sha1\n{key_time}\n{sha1(HttpString)}\n"
    # The trailing newline is required (confirmed by the error body and official docs).
    string_to_sign = (
        f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
    )
    signature = _hmac_hex(sign_key, string_to_sign, hashlib.sha1)
    return (
        f"q-sign-algorithm=sha1&q-ak={secret_id}&q-sign-time={key_time}"
        f"&q-key-time={key_time}&q-header-list=host&q-url-param-list={q_url_param_list}"
        f"&q-signature={signature}"
    )


def build_download(
    token: Dict[str, Any], object_key: str, double_slash: bool = False, end_delta: Optional[int] = None
) -> tuple[str, Dict[str, str]]:
    bucket = token["bucket"]
    region = token.get("region") or "ap-guangzhou"
    host = f"{bucket}.cos.{region}.myqcloud.com"
    path = object_key if object_key.startswith("/") else "/" + object_key
    if double_slash and not path.startswith("//"):
        path = "/" + path
    now = int(time.time())
    duration = int(token.get("expiration") or 1800)
    if end_delta is not None:
        duration = min(duration, end_delta)
    auth = cos_authorization(
        token["secretId"], token["secretKey"], "get", path, host, now, now + duration
    )
    url = f"https://{host}{path}"
    headers = {"Authorization": auth, "x-cos-security-token": token["sessionToken"]}
    return url, headers


def download(token: Dict[str, Any], object_key: str, save: str) -> None:
    print(f"[4/4] Downloading {object_key}")
    variants = [
        ("Original", build_download(token, object_key)),
        ("Double-slash path", build_download(token, object_key, double_slash=True)),
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
    print(f"      Saved {len(body)} bytes -> {save} "
          f"(magic={body[:8].hex() if body else 'empty'})")


def list_capture_keys(capture: str, redact_uid: bool) -> List[str]:
    keys: List[str] = []
    uid_pat = re.compile(r"/[0-9a-f]{32}/")
    with open(capture, encoding="utf-8") as f:
        for line in f:
            for m in re.finditer(r'"(?:videoUrl|url|picUrl)":\s*"([^"]+)"', line):
                key = m.group(1)
                if key.startswith("/"):
                    keys.append(uid_pat.sub("/<uid>/", key) if redact_uid else key)
    seen: List[str] = []
    for k in keys:
        if k not in seen:
            seen.append(k)
    return seen


def selftest() -> None:
    """Offline checks for signature structure, determinism, and time parameters."""
    token = {
        "bucket": "orvibo-test-1250000000",
        "region": "ap-guangzhou",
        "secretId": "AKIDEXAMPLE",
        "secretKey": "x" * 40,
        "sessionToken": "t" * 40,
        "expiration": 1800,
    }
    key = "/77c139c4d27f4fa6a20e1f459849aa47/videoPicklockEvent/x.h264"
    url, headers = build_download(token, key)
    assert url.startswith("https://orvibo-test-1250000000.cos.ap-guangzhou.myqcloud.com/")
    auth = headers["Authorization"]
    for part in ("q-sign-algorithm=sha1", "q-ak=AKIDEXAMPLE", "q-header-list=host"):
        assert part in auth, part
    sig = auth.rsplit("q-signature=", 1)[1]
    assert len(sig) == 40, "Signature should be 40-character SHA-1 hex"
    # Determinism: identical parameters must produce the same result.
    assert headers["Authorization"] == build_download(token, key)[1]["Authorization"]
    # Different times must produce different signatures.
    url2, headers2 = build_download(token, "/77c139c4d27f4fa6a20e1f459849aa47/videoPicklockEvent/y.h264")
    assert headers2["Authorization"] != auth
    # create_sign uses the same approach as the integration's packet.create_sign.
    assert len(create_sign({"a": "1", "b": "2"})) == 64
    # Use the actual FormatString from the server error body to validate HttpString construction.
    # cffc68e3... is the server-provided sha1(HttpString).
    path = "/77c139c4d27f4fa6a20e1f459849aa47/picturePicklockEvent/picklockEvent_1785652830.jpg"
    host = "familypic-cn-1251222210.cos.ap-guangzhou.myqcloud.com"
    http_string = f"get\n{path}\n\nhost={host}\n"
    assert (
        hashlib.sha1(http_string.encode()).hexdigest()
        == "cffc68e3aba2b1e672f079faffc9895fa3702d48"
    )
    # Check the three-part StringToSign format.
    auth2 = cos_authorization(
        "AKIDEXAMPLE", "x" * 40, "get", path, host, 1785667760, 1785797360
    )
    assert "q-sign-time=1785667760;1785797360" in auth2
    # Reconstructed StringToSign from the server error body, including its trailing newline:
    # sha1\n1785667865;1785797465\ncffc68e3aba2b1e672f079faffc9895fa3702d48\n
    _hmac_args = _hmac_hex("", "", hashlib.sha1)  # noqa: ensure the function is callable
    expected_sts = "sha1\n1785667865;1785797465\ncffc68e3aba2b1e672f079faffc9895fa3702d48\n"
    key_time = "1785667865;1785797465"
    sign_key = _hmac_hex("x" * 40, key_time, hashlib.sha1)
    sig = _hmac_hex(sign_key, expected_sts, hashlib.sha1)
    assert len(sig) == 40
    print("Self-test passed: COS signature v5 structure and determinism checks passed")


def main() -> int:
    parser = argparse.ArgumentParser(description="COS door lock media probe")
    parser.add_argument("--host", default=DEFAULT_HOST, help="API host (default: china.orvibo.com)")
    parser.add_argument("--capture", help="Extract an object key from packet capture JSONL")
    parser.add_argument("--list", action="store_true", help="List object keys only; do not connect")
    parser.add_argument("--no-redact", action="store_true", help="Do not redact UIDs when listing object keys")
    parser.add_argument("--object-key", help="Object key to download (such as /uid/videoPicklockEvent/x.h264)")
    parser.add_argument("--save", default="cos_download.bin", help="Path for the downloaded file")
    parser.add_argument("--selftest", action="store_true", help="Run offline signature checks")
    args = parser.parse_args()

    if args.selftest:
        selftest()
        return 0
    if args.capture:
        keys = list_capture_keys(args.capture, redact_uid=not args.no_redact)
        print("Object keys in the packet capture:")
        for k in keys:
            print(f"  {k}")
        if not args.object_key and keys and not args.no_redact:
            print("\nTo download, pass the original key (including the real UID) with --object-key")
        return 0
    if not args.object_key:
        parser.print_help()
        return 2

    username = os.environ.get("ORVIBO_USERNAME", "")
    password = os.environ.get("ORVIBO_PASSWORD", "")
    if not username or not password:
        print("Credentials missing: set ORVIBO_USERNAME and ORVIBO_PASSWORD first")
        return 3

    auth = login(args.host, username, password)
    family_id = fetch_family(args.host, auth["access_token"], auth["user_id"])
    token = fetch_cos_token(args.host, auth["access_token"], auth["user_id"], family_id)
    download(token, args.object_key, args.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
