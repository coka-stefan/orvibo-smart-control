"""Redaction helpers for logs and diagnostics.

Redaction approach adapted from orvibo-cloud capture.py:

- Mask credential fields such as token, password, sessionKey, and dynamicKey.
- Fingerprint identifiers such as deviceId, uid, and userId so records can be correlated but not recovered.
- With ``strict=True``, retain only string lengths for logs; with ``strict=False``,
  retain readable values for diagnostics.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Final

_REDACTED: Final = "<redacted>"
_MAX_DEPTH: Final = 6
_MAX_ITEMS: Final = 50

_SECRET_KEYS: Final = frozenset(
    {
        "accesstoken",
        "authorization",
        "dynamickey",
        "key",
        "password",
        "passwordmd5",
        "phonetoken",
        "phonenumber",
        "secret",
        "sessionid",
        "sessionkey",
        "token",
        "tokensecret",
    }
)

_IDENTIFIER_KEYS: Final = frozenset(
    {
        "account",
        "deviceid",
        "email",
        "extaddr",
        "familyid",
        "identifier",
        "mac",
        "parentuid",
        "phone",
        "uid",
        "userid",
        "username",
    }
)

_SAFE_FIELD_NAME: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_HEX_IDENTIFIER_KEY: Final = re.compile(r"^[A-Fa-f0-9]{12,64}$")


def _normalized_key(key: object) -> str:
    return "".join(
        character for character in str(key).casefold() if character.isalnum()
    )


def fingerprint(value: object, salt: bytes) -> str:
    """Return a salted fingerprint that cannot be reversed without the salt."""

    digest = hashlib.sha256(
        salt + str(value).encode("utf-8", errors="replace")
    ).hexdigest()
    return f"<id:{digest[:12]}>"


def _redacted_key(key: object, salt: bytes) -> str:
    text = str(key)
    if _SAFE_FIELD_NAME.fullmatch(text) and not _HEX_IDENTIFIER_KEY.fullmatch(text):
        return text
    return fingerprint(text, salt)


def redact_packet(
    value: object,
    salt: bytes,
    *,
    key: object = "",
    depth: int = 0,
    strict: bool = True,
) -> object:
    """Return a bounded redacted copy of a packet or state object.

    ``strict=True`` replaces every string with a length marker (suitable for
    logs); ``strict=False`` keeps values readable while still redacting
    credentials and fingerprinting identifiers (suitable for diagnostics).
    """

    normalized_key = _normalized_key(key)
    if normalized_key in _SECRET_KEYS:
        return _REDACTED
    if normalized_key in _IDENTIFIER_KEYS and value is not None:
        return fingerprint(value, salt)
    if depth >= _MAX_DEPTH:
        return "<max-depth>"
    if isinstance(value, Mapping):
        entries = list(value.items())
        result: dict[str, object] = {
            _redacted_key(child_key, salt): redact_packet(
                child_value,
                salt,
                key=child_key,
                depth=depth + 1,
                strict=strict,
            )
            for child_key, child_value in entries[:_MAX_ITEMS]
        }
        if len(entries) > _MAX_ITEMS:
            result["<truncated>"] = len(entries) - _MAX_ITEMS
        return result
    if isinstance(value, (list, tuple)):
        result = [
            redact_packet(item, salt, key=key, depth=depth + 1, strict=strict)
            for item in value[:_MAX_ITEMS]
        ]
        if len(value) > _MAX_ITEMS:
            result.append(f"<truncated:{len(value) - _MAX_ITEMS}>")
        return result
    if isinstance(value, str):
        return f"<string:length={len(value)}>" if strict else value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"
