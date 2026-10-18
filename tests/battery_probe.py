"""Battery push probe: listen for SSL pushes and record each packet's cmd and batteryManager fields.

Purpose: identify which command reports door lock battery state and how often; app observations
suggest the state updates nearly in real time, so verify the server's push pattern.

Usage:
  python tests/battery_probe.py [duration in seconds, default 180]

Environment variables: ORVIBO_USERNAME / ORVIBO_PASSWORD
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orvibo_probe import Https, Ssl  # noqa: E402
from orvibo_smart_control.const import DEFAULT_KEY  # noqa: E402
from orvibo_smart_control.packet import HomematePacket  # noqa: E402

LOGGER = logging.getLogger("battery_probe")


async def main() -> int:
    username = os.environ.get("ORVIBO_USERNAME") or ""
    password = os.environ.get("ORVIBO_PASSWORD") or ""
    if not username or not password:
        print("Set ORVIBO_USERNAME and ORVIBO_PASSWORD environment variables")
        return 2
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 180

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    api = Https(username, password)
    if not await api.login():
        print("Login failed")
        return 1
    fs = await api.families()
    if not fs:
        print("No families found")
        return 1
    fid = fs[0].get("familyId", "")
    print(f"Family: {fid}")

    sslc = Ssl(username, password, fid)
    if not await sslc.connect():
        print("SSL connection failed")
        await api.close()
        return 1

    print(f"Listening for {duration} seconds. Open the lock battery page in the app or operate the lock to trigger a push...")
    start = time.time()
    battery_seen = 0
    while time.time() - start < duration:
        try:
            hdr = await asyncio.wait_for(sslc.r.readexactly(42), timeout=5)
            ln = HomematePacket.parse_length(hdr)
            body = await asyncio.wait_for(sslc.r.readexactly(ln - 42), timeout=10)
        except asyncio.TimeoutError:
            continue
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            print("Connection closed")
            break
        try:
            pkt = HomematePacket(
                hdr + body, {(sslc.sid or ""): sslc.key or DEFAULT_KEY.encode()}
            )
        except Exception:
            continue
        d = pkt.json_payload
        if not isinstance(d, dict):
            continue
        cmd = d.get("cmd")
        if cmd in (0, 2, 32, 6):
            continue
        props = d.get("properties") or {}
        bat = props.get("batteryManager") if isinstance(props, dict) else None
        bat1 = props.get("batteryManager1") if isinstance(props, dict) else None
        ts = f"{time.time() - start:.1f}s"
        if bat or bat1:
            battery_seen += 1
            print(f"[{ts}] 🪫 cmd={cmd} batteryManager={bat} batteryManager1={bat1}")
        else:
            print(f"[{ts}] cmd={cmd} action={d.get('action', '')} props_keys={list(props.keys()) if isinstance(props, dict) else '-'}")

    await sslc.close()
    await api.close()
    print(f"Listening ended; received {battery_seen} packets containing battery data")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
