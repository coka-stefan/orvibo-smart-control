"""Temporary password management core: response parsing, expiration checks, and cleanup rules (independent of HA)."""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional


def parse_grant_response(resp: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Parse a cmd=246 response and return a normalized record, or None on failure.

    Record fields: password/authorized_id/authorized_unlock_id/type/start_time/
    end_time/number/unlock_num/phone/name.
    """
    if not isinstance(resp, Mapping):
        return None
    status = resp.get("status")
    if status not in (None, 0, "0"):
        return None
    password = resp.get("code") or ""
    auth = resp.get("authorizedUnlock")
    if isinstance(auth, Mapping):
        password = password or auth.get("password") or ""
        authorized_id = auth.get("authorizedId")
        authorized_unlock_id = auth.get("authorizedUnlockId") or ""
        start_time = auth.get("startTime")
        end_time = auth.get("endTime")
        number = auth.get("number")
        unlock_num = auth.get("unlockNum")
    else:
        authorized_id = None
        authorized_unlock_id = ""
        start_time = resp.get("startTime")
        end_time = resp.get("endTime")
        number = resp.get("number")
        unlock_num = 0
    if not password or authorized_id is None:
        return None
    return {
        "password": str(password),
        "authorized_id": int(authorized_id),
        "authorized_unlock_id": str(authorized_unlock_id),
        "type": int(resp.get("type") or 2),
        "start_time": int(start_time) if start_time else int(time.time()),
        "end_time": int(end_time) if end_time else 0,
        "number": int(number) if number is not None else 0,
        "unlock_num": int(unlock_num) if unlock_num is not None else 0,
        "phone": resp.get("phone") or "",
        "name": resp.get("userName") or "",
    }


def parse_authorization_item(item: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Parse one record from the full server-side readtable authorizedUnlock list."""
    if not isinstance(item, Mapping):
        return None
    if item.get("delFlag"):  # Skip deleted authorizations
        return None
    # Observed in the app: authorizeStatus=0 is valid; 3 is deleted/invalid (delFlag remains 0).
    status = item.get("authorizeStatus")
    if status not in (None, 0, "0"):
        return None
    authorized_id = item.get("authorizedId")
    if authorized_id is None:
        return None
    try:
        authorization_type = int(item.get("type") or 0)
    except (TypeError, ValueError):
        authorization_type = 0
    return {
        # The cloud may omit the password from list responses. An
        # authorization is still manageable by its server-side ID.
        "password": str(item.get("password") or ""),
        "authorized_id": int(authorized_id),
        "authorized_unlock_id": item.get("authorizedUnlockId") or "",
        "type": authorization_type,
        "start_time": int(item.get("startTime") or 0),
        "end_time": int(item.get("endTime") or 0),
        "number": int(item.get("number") or 0),
        "unlock_num": int(item.get("unlockNum") or 0),
        "phone": item.get("phone") or "",
        "name": item.get("userName") or item.get("name") or "",
        "authorize_status": item.get("authorizeStatus"),
    }


def is_expired(record: Mapping[str, Any], now: Optional[int] = None) -> bool:
    """Check whether a temporary password has expired (end time reached or usage count exhausted)."""
    now = int(time.time()) if now is None else int(now)
    end = int(record.get("end_time") or 0)
    if end > 0 and now >= end:
        return True
    number = int(record.get("number") or 0)
    unlock_num = int(record.get("unlock_num") or 0)
    if number > 0 and unlock_num >= number:
        return True
    return False


def describe_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Generate user-friendly fields for event and sensor display."""
    start = int(record.get("start_time") or 0)
    end = int(record.get("end_time") or 0)
    return {
        "password": record.get("password"),
        "authorized_id": record.get("authorized_id"),
        "name": record.get("name"),
        "phone": record.get("phone"),
        "type": record.get("type"),
        "number": record.get("number"),
        "unlock_num": record.get("unlock_num"),
        "start_time": start,
        "end_time": end,
        "expired": is_expired(record),
    }
