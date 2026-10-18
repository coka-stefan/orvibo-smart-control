"""Send an SSL control command to a COCO smart power strip (type=43)."""
import asyncio, hashlib, json, ssl, sys, time
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "custom_components"))

_init = Path(sys.path[0]) / "orvibo_smart_control" / "__init__.py"
_orig = _init.read_bytes()
if b"homeassistant" in _orig: _init.write_bytes(b"#")

from orvibo_smart_control.const import SSL_HOST, SSL_PORT, CMD_HELLO, CMD_LOGIN, CMD_CONTROL, CMD_HEARTBEAT, CMD_HANDSHAKE
from orvibo_smart_control.const import SOFTWARE_NAME, SOFTWARE_VERSION, SYS_VERSION, HARDWARE_VERSION, LANGUAGE, PHONE_NAME, DEBUG_INFO
from orvibo_smart_control.const import SOFTWARE_VER, DEFAULT_KEY, ID_UNSET, MAGIC, HTTPS_HOST, HTTP_HEADERS
from orvibo_smart_control.packet import HomematePacket, HomemateJsonData
from orvibo_smart_control.functions import generate_serial, generate_uuid

if _orig: _init.write_bytes(_orig)

USERNAME = os.environ.get("ORVIBO_USERNAME", "")
PASSWORD = os.environ.get("ORVIBO_PASSWORD", "")
FAMILY_ID = os.environ.get("ORVIBO_FAMILY_ID", "")
DEVICE_ID = os.environ.get("ORVIBO_DEVICE_ID", "")
DEVICE_UID = os.environ.get("ORVIBO_DEVICE_UID", "")
if not all((USERNAME, PASSWORD, FAMILY_ID, DEVICE_ID, DEVICE_UID)):
    sys.exit(
        "Set the ORVIBO_USERNAME, ORVIBO_PASSWORD, ORVIBO_FAMILY_ID, "
        "ORVIBO_DEVICE_ID, and ORVIBO_DEVICE_UID environment variables"
    )

pw_md5 = hashlib.md5(PASSWORD.encode()).hexdigest().upper()

async def main():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cert_dir = PROJECT_ROOT / "custom_components" / "orvibo_smart_control" / "certs"
    ctx.load_cert_chain(str(cert_dir / "client_cert.pem"), str(cert_dir / "client_key.pem"))
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    r, w = await asyncio.wait_for(
        asyncio.open_connection(SSL_HOST, SSL_PORT, ssl=ctx, server_hostname=SSL_HOST), timeout=15
    )
    print("✅ SSL connection succeeded")

    async def send(data: dict, key: bytes):
        if key == DEFAULT_KEY.encode():
            ptype = bytes([0x70, 0x6b])
            sid = bytes(ID_UNSET)
        else:
            ptype = bytes([0x64, 0x6b])
            sid = session_id.encode() if session_id else bytes(ID_UNSET)
        w.write(HomematePacket.build_packet(ptype, key, sid, data))
        await w.drain()

    async def recv(key) -> dict:
        hdr = await asyncio.wait_for(r.readexactly(42), timeout=10)
        ln = HomematePacket.parse_length(hdr)
        body = await asyncio.wait_for(r.readexactly(ln - 42), timeout=10)
        pkt = HomematePacket(hdr + body, {session_id: key})
        return pkt.json_payload

    # HELLO
    session_id = ""
    await send(HomemateJsonData.ssl_get_session(), DEFAULT_KEY.encode())
    hello_resp = await recv(DEFAULT_KEY.encode())
    if hello_resp and hello_resp.get("cmd") == CMD_HELLO:
        session_key = str(hello_resp["key"]).encode()
        session_id = hello_resp.get("sessionId", str(hello_resp))
        print("✅ HELLO: session_id retrieved")

    # LOGIN
    login_payload = HomemateJsonData.ssl_login(USERNAME, pw_md5, FAMILY_ID)
    await send(login_payload, session_key)
    await asyncio.sleep(2)
    print("✅ LOGIN sent")

    # Send control commands, starting with off.
    serial = generate_serial()
    uni_serial = generate_serial(use_time=True)
    # Try multiple control formats, focusing on endpoint parameters.
    test_commands = [
        # Combinations of order=on/off and values.
        ("on", 0, 0, 0, 0, None),
        ("on", 1, 0, 0, 0, None),
        ("off", 1, 0, 0, 0, None),
        ("off", 0, 0, 0, 0, None),
        # Set property format.
        ("set property", 0, 0, 0, 0, {"onoff": {"status": "on"}}),
        ("set property", 0, 0, 0, 0, {"onoff": {"status": "off"}}),
        # Try endpoint=1 (gdid=1).
        ("on", 0, 0, 0, 0, {"endpoint": 1}),
        ("off", 0, 0, 0, 0, {"endpoint": 1}),
        # Try endpoint=0.
        ("on", 0, 0, 0, 0, {"endpoint": 0}),
        ("off", 0, 0, 0, 0, {"endpoint": 0}),
        # Try order=open/close for older devices.
        ("open", 100, 0, 0, 0, None),
        ("close", 0, 0, 0, 0, None),
        # Try value2=1 or value3=1; older devices may differ.
        ("on", 1, 1, 0, 0, None),
        ("off", 0, 1, 0, 0, None),
    ]
    
    for order, v1, v2, v3, v4, props in test_commands:
        serial = generate_serial()
        uni_serial = generate_serial(use_time=True)
        control_payload = {
            "uid": DEVICE_UID, "userName": USERNAME,
            "deviceId": DEVICE_ID, "groupId": "",
            "order": order, "value1": v1, "value2": v2, "value3": v3, "value4": v4,
            "delayTime": 0, "qualityOfService": 1, "defaultResponse": 1, "propertyResponse": 0,
            "cmd": CMD_CONTROL, "serial": serial, "clientType": 1,
            "uniSerial": uni_serial, "serverRecord": False,
            "ver": SOFTWARE_VER, "debugInfo": DEBUG_INFO,
        }
        if props:
            control_payload["properties"] = props
        print(f"📤 Sending: order={order}, v1={v1}, props={props}")
        await send(control_payload, session_key)
        await asyncio.sleep(2)
        try:
            resp = await recv(session_key)
            print(f"📥 Response: {json.dumps(resp, ensure_ascii=False)}")
        except Exception as e:
            print(f"📥 No response: {e}")

    w.close()
    await asyncio.sleep(0.5)

asyncio.run(main())
