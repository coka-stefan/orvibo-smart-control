"""Lock media COS credential management: exchange credentials with cmd=313 and sign object keys into temporary URLs.

Background (APK reverse engineering and hardware verification):
- Lock events (tampering alerts/doorbell) provide Tencent Cloud COS object keys in videoUrl/picUrl
  (e.g. /uid/picturePicklockEvent/xxx.jpg);
- The REST endpoint v2/cosToken/getCosToken issues credentials for the log bucket only; reading lock media returns
  AccessDenied (confirmed on hardware). The correct path is to send cmd=313 over the persistent SSL connection
  (Skill.GetCOSAuthorization), which returns credentials for the lock-specific bucket (e.g.
  p20-doorlock-1251222210);
- Use COS Signature v5 to sign the object key into a temporary URL (the Authorization parameter
  is appended directly to the query, matching the official presigned URL format).
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Mapping, Optional
from urllib.parse import quote

_LOGGER = logging.getLogger(__name__)

# Refresh buffer before credentials expire (seconds)
_RENEW_LEAD_TIME = 300


def _hmac_hex(key: str, msg: str, algo) -> str:
    return hmac.new(key.encode(), msg.encode(), algo).hexdigest()


def cos_authorization(
    secret_id: str,
    secret_key: str,
    method: str,
    path: str,
    host: str,
    start: int,
    end: int,
    query_params: Optional[Mapping[str, str]] = None,
) -> str:
    """COS Signature v5, using the same algorithm as tests/cos_probe.py and verified on hardware.

    query_params are included in the signature (e.g. response-content-type) and sorted by their URL-encoded
    names. The signature parameters and x-cos-security-token are excluded from the calculation.
    """
    key_time = f"{start};{end}"
    sign_key = _hmac_hex(secret_key, key_time, hashlib.sha1)
    query_part = ""
    q_url_param_list = ""
    if query_params:
        encoded = {
            quote(str(k), safe="-"): quote(str(v), safe="")
            for k, v in query_params.items()
        }
        items = sorted(encoded.items())
        query_part = "&".join(f"{k}={v}" for k, v in items)
        q_url_param_list = ";".join(k for k, _ in items)
    http_string = f"{method.lower()}\n{path}\n{query_part}\nhost={host}\n"
    string_to_sign = (
        f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
    )
    signature = _hmac_hex(sign_key, string_to_sign, hashlib.sha1)
    return (
        f"q-sign-algorithm=sha1&q-ak={secret_id}&q-sign-time={key_time}"
        f"&q-key-time={key_time}&q-header-list=host&q-url-param-list={q_url_param_list}"
        f"&q-signature={signature}"
    )


@dataclasses.dataclass(slots=True)
class CosCredentials:
    """Normalized lock COS STS credentials."""

    secret_id: str
    secret_key: str
    session_token: str
    bucket: str
    region: str
    expires_at: float  # Local timestamp in seconds
    system_time_ms: Optional[int] = None

    @property
    def valid(self) -> bool:
        return time.time() < self.expires_at - _RENEW_LEAD_TIME


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


def _infer_content_type(object_key: str) -> Optional[str]:
    """Infer Content-Type from the object key extension for the response-content-type override."""
    dot = object_key.rfind(".")
    if dot < 0:
        return None
    return _CONTENT_TYPE_BY_EXT.get(object_key[dot:].lower())


def parse_cos_response(resp: Mapping[str, Any]) -> Optional[CosCredentials]:
    """Parse the cmd=313 response and return normalized credentials, or None if the format is invalid."""
    if not isinstance(resp, Mapping):
        return None
    response_json = resp.get("response")
    try:
        if isinstance(response_json, str):
            q = json.loads(response_json)
        elif isinstance(response_json, Mapping):
            q = response_json
        else:
            return None
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(q, Mapping):
        return None
    if q.get("namespace") != "Skill.GetCOSAuthorization":
        return None
    status = q.get("status")
    if status not in (None, 0, "0"):
        return None
    security = q.get("security") or {}
    if not isinstance(security, Mapping):
        return None
    secret_id = security.get("accessKeyId") or ""
    secret_key = security.get("accessKeySecret") or ""
    session_token = security.get("securityToken") or ""
    bucket = security.get("bucketName") or ""
    if not secret_id or not secret_key or not session_token or not bucket:
        return None
    region = security.get("region") or "ap-guangzhou"
    expiration = int(security.get("expiration") or 1800)
    system_time_ms = security.get("systemCurrentTime")
    base = int(system_time_ms / 1000) if system_time_ms else int(time.time())
    return CosCredentials(
        secret_id=secret_id,
        secret_key=secret_key,
        session_token=session_token,
        bucket=bucket,
        region=region,
        expires_at=base + expiration,
        system_time_ms=int(system_time_ms) if system_time_ms else None,
    )


def signed_media_url(
    creds: CosCredentials,
    object_key: str,
    ttl: int = 600,
    content_type: Optional[str] = None,
) -> str:
    """Sign a COS object key into a temporary accessible URL (presigned URL format).

    STS temporary credentials require x-cos-security-token in the URL query (browsers cannot send
    custom headers), or direct access returns AccessDenied. This parameter is excluded from signing.
    COS may store Content-Type as text/html (observed), causing browsers to render an image
    as text. Override the response header with response-content-type (included in signing).
    """
    host = f"{creds.bucket}.cos.{creds.region}.myqcloud.com"
    path = object_key if object_key.startswith("/") else "/" + object_key
    now = max(int(time.time()), int(creds.system_time_ms / 1000) if creds.system_time_ms else 0)
    duration = min(ttl, max(1, int(creds.expires_at - now - _RENEW_LEAD_TIME)))
    content_type = content_type or _infer_content_type(object_key)
    query_params: dict[str, str] = {}
    if content_type:
        query_params["response-content-type"] = content_type
    auth = cos_authorization(
        creds.secret_id,
        creds.secret_key,
        "get",
        path,
        host,
        now,
        now + duration,
        query_params=query_params or None,
    )
    query_prefix = ""
    if query_params:
        encoded = {
            quote(str(k), safe="-"): quote(str(v), safe="")
            for k, v in query_params.items()
        }
        query_prefix = "&".join(f"{k}={v}" for k, v in sorted(encoded.items())) + "&"
    token_part = f"&x-cos-security-token={quote(creds.session_token, safe='')}"
    return f"https://{host}{path}?{query_prefix}{auth}{token_part}"


class CosMediaManager:
    """Cache COS credentials by lock device and sign object keys into temporary URLs.

    Credentials are obtained with cmd=313 over the persistent SSL connection (valid for 36 hours) and cached by device_id;
    they are renewed before expiry. Events for the same lock share credentials.
    """

    def __init__(self, ssl_client, user_id: str, family_id: str) -> None:
        self._ssl = ssl_client
        self._user_id = user_id
        self._family_id = family_id
        self._cache: dict[str, CosCredentials] = {}

    def clear(self) -> None:
        self._cache.clear()

    def cached_credentials(self, device_id: str) -> Optional[CosCredentials]:
        """Return valid cached credentials without network access, or None if missing or expired."""
        cached = self._cache.get(device_id)
        if cached is not None and cached.valid:
            return cached
        return None

    def try_signed_url(
        self,
        device_id: str,
        device_uid: str,
        object_key: str,
        ttl: int = 600,
    ) -> Optional[str]:
        """Sign synchronously with cached credentials (event publishing path, no network wait)."""
        if not object_key:
            return None
        cached = self.cached_credentials(device_id)
        if cached is None:
            return None
        try:
            return signed_media_url(cached, object_key, ttl=ttl)
        except Exception:  # noqa: BLE001 - signing failures must not affect event publishing
            _LOGGER.exception("Failed to sign COS object key: %s", object_key)
            return None

    async def get_credentials(
        self,
        device_id: str,
        device_uid: str,
    ) -> Optional[CosCredentials]:
        """Return valid credentials, fetching them again with cmd=313 if missing or expired."""
        cached = self._cache.get(device_id)
        if cached is not None and cached.valid:
            return cached
        if self._ssl is None:
            return None
        resp = await self._ssl.send_cos_auth(
            user_id=self._user_id,
            device_id=device_id,
            device_uid=device_uid,
        )
        creds = parse_cos_response(resp) if resp else None
        if creds is None:
            _LOGGER.warning(
                "Failed to get lock media credentials: device=%s (invalid response or timeout)", device_id
            )
            return None
        self._cache[device_id] = creds
        _LOGGER.debug(
            "Lock media credentials refreshed: device=%s bucket=%s region=%s valid_for=%.0fh",
            device_id,
            creds.bucket,
            creds.region,
            (creds.expires_at - time.time()) / 3600,
        )
        return creds

    async def signed_url(
        self,
        device_id: str,
        device_uid: str,
        object_key: str,
        ttl: int = 600,
    ) -> Optional[str]:
        """Sign the object key into a temporary URL, or return None if credentials are unavailable."""
        if not object_key:
            return None
        creds = await self.get_credentials(device_id, device_uid)
        if creds is None:
            return None
        try:
            return signed_media_url(creds, object_key, ttl=ttl)
        except Exception:  # noqa: BLE001 - signing failures must not affect event publishing
            _LOGGER.exception("Failed to sign COS object key: %s", object_key)
            return None
