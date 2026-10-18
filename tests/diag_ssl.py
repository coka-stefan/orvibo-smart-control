"""Diagnose SSL persistent connectivity by checking DNS, TCP, TLS, and HELLO in sequence."""

from __future__ import annotations

import asyncio
import socket
import ssl
import sys
import time

sys.path.insert(0, r"D:\orvibo1\dump1\standalone")
from core.packet import HomematePacket, HomemateJsonData  # noqa: E402
from core.const import (  # noqa: E402
    DEFAULT_KEY,
    ID_UNSET,
    SSL_HOST,
    SSL_PORT,
)


async def main() -> None:
    print("1) Resolve DNS", SSL_HOST)
    try:
        print("   ->", socket.gethostbyname(SSL_HOST))
    except Exception as e:
        print("   ❌ DNS lookup failed:", repr(e))
        return

    t0 = time.time()
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_connection(SSL_HOST, SSL_PORT), timeout=10
        )
        print(f"2) TCP connected ({time.time()-t0:.1f}s)")
        w.close()
    except Exception as e:
        print(f"2) ❌ TCP connection failed ({time.time()-t0:.1f}s): {e!r}")
        print("   Note: a timeout here means this machine cannot reach china.orvibo.com:10002")
        return

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        cert_dir = r"D:\orvibo1\dump1\standalone\certs"
        ctx.load_cert_chain(
            cert_dir + r"\client_cert.pem", cert_dir + r"\client_key.pem"
        )
        ctx.load_verify_locations(cafile=cert_dir + r"\server_ca.pem")
        t0 = time.time()
        r2, w2 = await asyncio.wait_for(
            asyncio.open_connection(
                SSL_HOST, SSL_PORT, ssl=ctx, server_hostname=SSL_HOST
            ),
            timeout=12,
        )
        print(f"3) TLS handshake succeeded ({time.time()-t0:.1f}s)")
    except Exception as e:
        print(f"3) ❌ TLS handshake failed: {e!r}")
        print("   Note: the certificate/CA may not match, or an intermediary may block the port")
        return

    try:
        payload = HomemateJsonData.ssl_get_session()
        packet = HomematePacket.build_packet(
            bytes([0x70, 0x6B]), DEFAULT_KEY.encode(), bytes(ID_UNSET), payload
        )
        w2.write(packet)
        await w2.drain()
        hdr = await asyncio.wait_for(r2.readexactly(42), timeout=10)
        ln = HomematePacket.parse_length(hdr)
        body = await asyncio.wait_for(r2.readexactly(ln - 42), timeout=10)
        pkt = HomematePacket(hdr + body, {"": DEFAULT_KEY.encode()})
        print("4) HELLO response:", pkt.json_payload)
        w2.close()
        print("\n[OK] All checks passed: SSL persistent connection is available")
    except Exception as e:
        print(f"4) [FAIL] HELLO interaction failed: {e!r}")


if __name__ == "__main__":
    asyncio.run(main())
