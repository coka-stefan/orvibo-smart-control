"""Inspect a device's full description and possible control methods."""
import hashlib, json, asyncio, aiohttp, sys, time
import os
from pathlib import Path

USER = os.environ.get("ORVIBO_USERNAME", "")
PASSWORD = os.environ.get("ORVIBO_PASSWORD", "")
if not USER or not PASSWORD:
    sys.exit("Set the ORVIBO_USERNAME and ORVIBO_PASSWORD environment variables first")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))
_init = Path(sys.path[0]) / "orvibo_smart_control" / "__init__.py"
_orig = _init.read_bytes()
if b"homeassistant" in _orig: _init.write_bytes(b"#")
from orvibo_smart_control.const import HTTPS_HOST, HTTP_HEADERS
from orvibo_smart_control.packet import HomemateJsonData, generate_serial, generate_uuid
from orvibo_smart_control.functions import hmac_sha256
if _orig: _init.write_bytes(_orig)

async def main():
    pw_md5 = hashlib.md5(PASSWORD.encode()).hexdigest().upper()
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"https://{HTTPS_HOST}/getOauthToken?userName={USER}&type=0&password={pw_md5}",
                       headers={**HTTP_HEADERS, "Accept":"*/*"}, ssl=False)
        j = json.loads(await r.text())
        token, uid = j["data"]["access_token"], j["data"]["user_id"]
        print("✅ Login succeeded")

        # 1. Get the full device description.
        print(f"\n📋 getDeviceDesc...")
        url = f"https://{HTTPS_HOST}/getDeviceDesc?source=ZhiJia365&lastUpdateTime=0&accessToken={token}"
        async with s.get(url, headers=HTTP_HEADERS, ssl=False) as r:
            text = await r.text()
            desc = json.loads(text)
            print(json.dumps(desc, ensure_ascii=False)[:3000])

        # 2. Inspect the power strip device configuration.
        print(f"\n📋 queryDeviceById...")
        tid = int(time.time() * 1000)
        url = f"https://{HTTPS_HOST}/v2/device/queryDeviceById"
        data = json.dumps({"accessToken": token, "deviceId": "example-device-id", "timestamp": tid, "random": generate_uuid()})
        async with s.post(url, data=data, headers=HTTP_HEADERS, ssl=False) as r:
            text = await r.text()
            print(json.dumps(json.loads(text), ensure_ascii=False)[:2000])

        # 3. Try the gateway control endpoint.
        print("\n📋 Try v2/device/send...")
        url = f"https://{HTTPS_HOST}/v2/device/send"
        # The COCO power strip may use the legacy protocol: order=on/off uses value1=1/0.
        for order, v1 in [("on", 1), ("off", 0)]:
            ts = int(time.time() * 1000)
            rd = generate_uuid()
            params = {
                "accessToken": token, "deviceId": "example-device-id",
                "order": order, "value1": v1, "value2": 0, "value3": 0, "value4": 0,
                "random": rd, "timestamp": ts, "userId": uid, "userName": USER,
            }
            keys = sorted(params.keys())
            sb = [f"{k}={params[k]}" for k in keys]
            sb.append("key=nQ45RjPtOws96jmH")
            params["sign"] = hmac_sha256("nQ45RjPtOws96jmH", "&".join(sb))
            params["cmd"] = 15
            params["serial"] = generate_serial()
            params["uniSerial"] = generate_serial(use_time=True)
            params["ver"] = "5.1.3.309"
            params["clientType"] = 1
            params["serverRecord"] = False
            params["debugInfo"] = "Android_ZhiJia365_34_5.1.3.309"
            payload = json.dumps(params, ensure_ascii=False)
            async with s.post(url, data=payload, headers=HTTP_HEADERS, ssl=False) as r:
                resp = json.loads(await r.text())
                print(f"  {order}(v1={v1}): {json.dumps(resp, ensure_ascii=False)}")

        # 4. Try the legacy API.
        print("\n📋 Try v2/cmd/app/write...")
        url = f"https://{HTTPS_HOST}/v2/cmd/app/write"
        for order, v1 in [("on", 1), ("off", 0)]:
            ts = int(time.time() * 1000)
            rd = generate_uuid()
            params = {
                "accessToken": token, "deviceId": "example-device-id",
                "order": order, "value1": v1, "value2": 0, "value3": 0, "value4": 0,
                "random": rd, "timestamp": ts, "userId": uid, "userName": USER,
            }
            keys = sorted(params.keys())
            sb = [f"{k}={params[k]}" for k in keys]
            sb.append("key=nQ45RjPtOws96jmH")
            params["sign"] = hmac_sha256("nQ45RjPtOws96jmH", "&".join(sb))
            params["ver"] = "5.1.3.309"
            payload = json.dumps(params, ensure_ascii=False)
            async with s.post(url, data=payload, headers=HTTP_HEADERS, ssl=False) as r:
                resp = json.loads(await r.text())
                print(f"  {order}(v1={v1}): {json.dumps(resp, ensure_ascii=False)}")

asyncio.run(main())
