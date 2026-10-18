"""Temporary password probe (cmd=246 over an SSL persistent connection).

Implementation based on a lock6.log capture and APK reverse engineering (core.c.X → cmd 246):
send type/effectTime/startTime/endTime/number/phone/userName to the lock; the server returns
code/password containing a six-digit temporary password that can be entered on the lock.

Usage:
  python tests/temp_pwd_probe.py                     # type=2 temporary password, 24h, one use
  python tests/temp_pwd_probe.py --type 1 --hours 48 # time-limited password for 48 hours
  python tests/temp_pwd_probe.py --type 2 --minutes 30 --number 1 --name "Test temporary password"

Environment variables: ORVIBO_USERNAME / ORVIBO_PASSWORD
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

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
from orvibo_smart_control.packet import HomemateJsonData  # noqa: E402
from orvibo_smart_control.const import HTTP_HEADERS  # noqa: E402

LOGGER = logging.getLogger("temp_pwd_probe")
CMD_TEMP_PWD = 246
CMD_DELETE_AUTH = 247
CMD_QUERY_LIST = 171


class TempPwdSsl(Ssl):
    """Add a cmd=246 password request and single-response wait to the existing Ssl client."""

    async def request_temp_password(
        self,
        device_id: str,
        device_uid: str,
        auth_type: int,
        minutes: int,
        number: int,
        name: str,
        start_offset: int = 0,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        phone: str = "",
        timeout: float = 20.0,
    ) -> Optional[Dict[str, Any]]:
        now = int(time.time()) + start_offset
        # type=1 time-limited password: use --start/--end for an absolute range, otherwise calculate from minutes.
        # type=2 temporary password: effectTime is a relative duration (endTime=0).
        if auth_type == 1 and start_ts and end_ts:
            start_time, end_time = start_ts, end_ts
        else:
            start_time = now
            end_time = now + minutes * 60 if auth_type == 1 else 0
        payload = {
            "deviceId": device_id,
            "uid": device_uid,
            "userName": name,
            "type": auth_type,
            "effectTime": minutes,
            "startTime": start_time,
            "endTime": end_time,
            "number": number,
            "phone": phone,
            "cmd": CMD_TEMP_PWD,
            "serial": generate_serial(),
            "clientType": 1,
            "uniSerial": generate_serial(use_time=True),
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        LOGGER.info(
            "cmd=246 sent: device=%s type=%s minutes=%s number=%s name=%s start=%s end=%s",
            device_id,
            auth_type,
            minutes,
            number,
            name,
            payload["startTime"],
            payload["endTime"],
        )
        LOGGER.debug("payload=%s", json.dumps(payload, ensure_ascii=False))
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
            if cmd == CMD_TEMP_PWD:
                LOGGER.info("cmd=246 response received")
                return d
            LOGGER.debug("Ignoring intermediate packet cmd=%s", cmd)
        LOGGER.error("Timed out waiting for cmd=246 response")
        return None

    async def delete_authorization(
        self,
        device_id: str,
        device_uid: str,
        authorized_id: int,
        timeout: float = 15.0,
    ) -> Optional[Dict[str, Any]]:
        """Delete an authorization (cmd=247); authorizedId comes from the create response."""
        payload = {
            "uid": device_uid,
            "deviceId": device_id,
            "userId": authorized_id,
            "cmd": CMD_DELETE_AUTH,
            "serial": generate_serial(),
            "clientType": 1,
            "uniSerial": generate_serial(use_time=True),
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        LOGGER.info("cmd=247 sent: device=%s authorizedId=%s", device_id, authorized_id)
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
            if cmd == CMD_DELETE_AUTH:
                return d
            LOGGER.debug("Ignoring intermediate packet cmd=%s", cmd)
        LOGGER.error("Timed out waiting for cmd=247 response")
        return None

    async def query_authorization_list(
        self,
        family_id: str,
        timeout: float = 15.0,
    ) -> Optional[Dict[str, Any]]:
        """Send cmd=171 to query authorization/messages and return the raw response for inspection."""
        payload = {
            "familyId": family_id,
            "lastUpdateTime": 0,
            "start": 0,
            "limit": 50,
            "cmd": CMD_QUERY_LIST,
            "serial": generate_serial(),
            "clientType": 1,
            "uniSerial": generate_serial(use_time=True),
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        LOGGER.info("cmd=171 sent: family=%s", family_id)
        await self._send(payload, self.key)

        deadline = time.time() + timeout
        collected = []
        while time.time() < deadline:
            try:
                hdr = await asyncio.wait_for(self.r.readexactly(42), timeout=5)
                ln = HomematePacket.parse_length(hdr)
                body = await asyncio.wait_for(self.r.readexactly(ln - 42), timeout=10)
            except asyncio.TimeoutError:
                continue
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                LOGGER.error("SSL connection interrupted")
                break
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
            if cmd == CMD_QUERY_LIST or "authorizedUnlock" in json.dumps(d):
                collected.append(d)
                if cmd == CMD_QUERY_LIST:
                    break
        if not collected:
            LOGGER.error("Did not receive a cmd=171 response")
            return None
        return collected


def extract_password(resp: Dict[str, Any]) -> Optional[str]:
    """Extract the temporary password from code or authorizedUnlock.password in the response."""
    code = resp.get("code")
    if isinstance(code, str) and code:
        return code
    auth = resp.get("authorizedUnlock")
    if isinstance(auth, dict):
        pwd = auth.get("password")
        if isinstance(pwd, str) and pwd:
            return pwd
    return None


def parse_time(value: str) -> int:
    """Parse 'yyyy-MM-dd HH:mm' (optionally with seconds) or a Unix timestamp in seconds."""
    v = value.strip()
    if v.isdigit():
        return int(v)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(datetime.strptime(v, fmt).timestamp())
        except ValueError:
            continue
    raise SystemExit(f"Could not parse time: {value} (expected yyyy-MM-dd HH:mm or a Unix timestamp in seconds)")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Temporary password probe (cmd=246)")
    parser.add_argument("--type", type=int, default=2, help="Authorization type: 1=time-limited, 2=temporary, 3=recurring (default: 2)")
    parser.add_argument("--minutes", type=int, default=1440, help="Validity in minutes (default: 1440=24h)")
    parser.add_argument("--number", type=int, default=None, help="Allowed uses (type=2 defaults to 1; type=1 defaults to 0/unlimited)")
    parser.add_argument("--name", default="", help="Temporary username (generated automatically by default)")
    parser.add_argument("--start-offset", type=int, default=0, help="Start time offset in seconds (type=1 can start in the future)")
    parser.add_argument("--start", default="", help="Start time yyyy-MM-dd HH:mm (type=1; replaces the default now)")
    parser.add_argument("--end", default="", help="End time yyyy-MM-dd HH:mm (type=1; replaces default now+minutes)")
    parser.add_argument("--phone", default="", help="Optional phone number for an SMS notification")
    parser.add_argument("--delete", type=int, default=0, help="Delete the authorization with this authorizedId; do not create one")
    parser.add_argument("--list-auth", action="store_true", help="Query the authorization/message list (cmd=171) and print the raw response")
    parser.add_argument(
        "--list", action="store_true", help="List lock information only (reserved; cmd171 query is not implemented yet)"
    )
    parser.add_argument("--family-id", help="Family ID (uses the first family by default)")
    parser.add_argument("--device-id", help="Door lock deviceId (w- prefix; auto-detected by default)")
    parser.add_argument("--device-uid", help="Door lock uid (without w- prefix; auto-detected by default)")
    args = parser.parse_args()

    username = os.environ.get("ORVIBO_USERNAME") or ""
    password = os.environ.get("ORVIBO_PASSWORD") or ""
    if not username or not password:
        print("Set ORVIBO_USERNAME and ORVIBO_PASSWORD environment variables")
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    api = Https(username, password)
    if not await api.login():
        print("Login failed")
        return 1
    print(f"[1/4] Login succeeded user_id={api.uid[:8]}...")

    fs = await api.families()
    if not fs:
        print("No families found for this account")
        return 1
    fam = next((f for f in fs if f.get("familyId") == args.family_id), None) if args.family_id else fs[0]
    if not fam:
        print(f"Family not found: {args.family_id}")
        return 1
    fid = fam.get("familyId", "")
    print(f"[2/4] Family: {fam.get('familyName', '?')} ({fid[:8]}...)")

    devs = await api.devices(fid)
    if args.device_id and args.device_uid:
        dev = {"deviceId": args.device_id, "uid": args.device_uid}
    else:
        dev = next((d for d in devs if _is_lock_device(d)), None)
        if not dev:
            print("No door lock identified; specify --device-id or --device-uid")
            return 1
    device_id, device_uid = dev["deviceId"], dev["uid"]
    print(f"[3/4] Door lock: {dev.get('deviceName', '?')} deviceId={device_id} uid={device_uid}")

    if args.delete:
        sslc = TempPwdSsl(api.username, api.password, fid)
        if not await sslc.connect():
            print("SSL connection or login failed")
            await api.close()
            return 1
        resp = await sslc.delete_authorization(device_id, device_uid, args.delete)
        await sslc.close()
        await api.close()
        if not resp:
            print("Did not receive a cmd=247 response")
            return 1
        print(f"Delete response: {json.dumps(resp, ensure_ascii=False)[:400]}")
        if resp.get("status") in (None, 0, "0"):
            print(f"Delete succeeded authorizedId={args.delete}")
            return 0
        print(f"Delete failed status={resp.get('status')}")
        return 1

    if args.list_auth:
        # 1) Check whether REST readtable's full sync contains the authorization table.
        try:
            ret = HomemateJsonData.get_devices_status(
                api.token, "", api.uid, api.username, fid, device_flag=0
            )
            s = await api._s()
            async with s.post(ret["url"], data=ret["data"], headers=HTTP_HEADERS, ssl=False) as r:
                j = await r.json()
            data = j.get("data", {}) or {}
            print("[readtable] data keys:", list(data.keys()))
            auth_list = data.get("authorizedUnlock") or []
            if isinstance(auth_list, list):
                print(f"[readtable] authorizedUnlock has {len(auth_list)} entries; first 3:")
                for item in auth_list[:3]:
                    if isinstance(item, dict):
                        print(
                            "  ",
                            json.dumps(
                                {
                                    k: item.get(k)
                                    for k in (
                                        "authorizedId",
                                        "delFlag",
                                        "authorizeStatus",
                                        "pwdUseType",
                                        "number",
                                        "unlockNum",
                                        "startTime",
                                        "password",
                                        "createTime",
                                    )
                                },
                                ensure_ascii=False,
                            ),
                        )
            for k, v in data.items():
                if isinstance(v, list):
                    sample = list(v[0].keys())[:15] if v else "-"
                    print(f"  {k}: list[{len(v)}] first item keys={sample}")
                elif isinstance(v, dict):
                    print(f"  {k}: dict keys={list(v.keys())[:15]}")
                else:
                    print(f"  {k}: {type(v).__name__}")
        except Exception as e:
            print("[readtable] failed:", e)

        # 2) Query the message list over SSL with cmd=171.
        sslc = TempPwdSsl(api.username, api.password, fid)
        if not await sslc.connect():
            print("SSL connection or login failed")
            await api.close()
            return 1
        result = await sslc.query_authorization_list(fid)
        await sslc.close()
        await api.close()
        if not result:
            print("No response")
            return 1
        for item in result:
            print(json.dumps(item, ensure_ascii=False)[:1200])
        return 0

    name = args.name or f"Temporary User {time.strftime('%m%d%H%M')}"
    sslc = TempPwdSsl(api.username, api.password, fid)
    if not await sslc.connect():
        print("SSL connection or login failed")
        await api.close()
        return 1
    number = args.number if args.number is not None else (1 if args.type == 2 else 0)
    if args.type == 3:
        print("type=3 recurring passwords require the day (weekday) parameter; not implemented yet. Use type=1 or 2.")
        await sslc.close()
        await api.close()
        return 1
    start_ts = parse_time(args.start) if args.start else None
    end_ts = parse_time(args.end) if args.end else None
    if args.type == 1 and (start_ts or end_ts) and not (start_ts and end_ts):
        print("type=1 requires both --start and --end for a specified time range")
        await sslc.close()
        await api.close()
        return 1
    if start_ts and end_ts and end_ts <= start_ts:
        print("End time must be later than start time")
        await sslc.close()
        await api.close()
        return 1
    resp = await sslc.request_temp_password(
        device_id,
        device_uid,
        args.type,
        args.minutes,
        number,
        name,
        start_offset=args.start_offset,
        start_ts=start_ts,
        end_ts=end_ts,
        phone=args.phone,
    )
    await sslc.close()
    await api.close()
    if not resp:
        print("Did not receive a cmd=246 response")
        return 1

    print(f"[4/4] cmd=246 response: {json.dumps(resp, ensure_ascii=False)[:600]}")
    if resp.get("status") not in (None, 0, "0"):
        print(f"Request failed status={resp.get('status')} msg={resp.get('msg')}")
        return 1
    pwd = extract_password(resp)
    if not pwd:
        print("No temporary password found in the response")
        return 1
    auth = resp.get("authorizedUnlock") or {}
    print("\n========================================")
    print(f"  Temporary password: {pwd}")
    print(f"  Username:           {name}")
    print(f"  Type:               {args.type} (1=time-limited, 2=temporary, 3=recurring)")
    print(f"  Validity:           {args.minutes} minutes")
    print(f"  Uses:               {args.number if args.number else 'Unlimited'}")
    print(f"  SMS notification:   {'sent to ' + args.phone if args.phone else 'disabled'}")
    if resp.get("startTime"):
        print(
            "  Start time: %s (%s)",
            datetime.fromtimestamp(int(resp["startTime"])).strftime("%Y-%m-%d %H:%M"),
            resp["startTime"],
        )
    if resp.get("endTime"):
        print(
            "  End time: %s (%s)",
            datetime.fromtimestamp(int(resp["endTime"])).strftime("%Y-%m-%d %H:%M"),
            resp["endTime"],
        )
    if auth:
        print(f"  authorizedId: {auth.get('authorizedId')}")
        print(f"  unlockNum:    {auth.get('unlockNum')}")
    print("========================================")
    print("Enter this six-digit password on the lock to verify it")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
