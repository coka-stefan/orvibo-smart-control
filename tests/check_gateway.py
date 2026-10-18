"""Inspect gateway and device bindings."""
import hashlib, json, asyncio, aiohttp, sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))
_init = Path(sys.path[0]) / "orvibo_smart_control" / "__init__.py"
_orig = _init.read_bytes()
if b"homeassistant" in _orig: _init.write_bytes(b"#")
from orvibo_smart_control.const import HTTPS_HOST, HTTP_HEADERS
from orvibo_smart_control.packet import HomemateJsonData
from orvibo_smart_control.functions import hmac_sha256, generate_uuid
if _orig: _init.write_bytes(_orig)

USER = os.environ.get("ORVIBO_USERNAME", "")
PASS = os.environ.get("ORVIBO_PASSWORD", "")
if not USER or not PASS:
    sys.exit("Set the ORVIBO_USERNAME and ORVIBO_PASSWORD environment variables first")
DEV = "example-device-id"

async def main():
    pw_md5 = hashlib.md5(PASS.encode()).hexdigest().upper()
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"https://{HTTPS_HOST}/getOauthToken?userName={USER}&type=0&password={pw_md5}",
                       headers={**HTTP_HEADERS, "Accept":"*/*"}, ssl=False)
        j = json.loads(await r.text())
        token = j["data"]["access_token"]
        uid = j["data"]["user_id"]
        print("✅ Login succeeded")

        # Query each family's information and check for gateway bindings.
        ret = HomemateJsonData.get_family_statistics_users(uid, token)
        async with s.post(ret["url"], data=ret["data"], headers=HTTP_HEADERS, ssl=False) as r:
            families = json.loads(await r.text()).get("data", [])

        for f in families:
            fid = f.get("familyId","")
            fname = f.get("familyName","?")
            print(f"\n🏠 {fname}")
            
            ret2 = HomemateJsonData.get_devices_status(token, "", uid, USER, fid, 1)
            async with s.post(ret2["url"], data=ret2["data"], headers=HTTP_HEADERS, ssl=False) as r:
                data = json.loads(await r.text()).get("data", {})
                
                # Gateways
                gws = data.get("gateway", [])
                print(f"  Gateways: {len(gws)}")
                for g in gws:
                    print(f"    {json.dumps(g, ensure_ascii=False)[:300]}")
                
                # User-gateway bindings
                binds = data.get("userGatewayBind", [])
                print(f"  User-gateway bindings: {len(binds)}")
                for b in binds:
                    print(f"    {json.dumps(b, ensure_ascii=False)[:200]}")
                
                # Devices
                devs = data.get("device", [])
                for d in devs:
                    if d.get("deviceId") == DEV:
                        print("\n  🔌 Power strip details:")
                        print(f"    {json.dumps(d, ensure_ascii=False)}")
                        # Inspect its endpoint, profileID, and zoneId.
                        print(f"    endpoint={d.get('endpoint')}, profileID={d.get('profileID')}, zoneId={d.get('zoneId')}")
                        print(f"    appDeviceId={d.get('appDeviceId')}, gdid={d.get('gdid')}")
                
                # Device state
                sts = data.get("deviceStatus", [])
                for st in sts:
                    if st.get("deviceId") == DEV:
                        print("\n  🔌 Power strip state:")
                        print(f"    {json.dumps(st, ensure_ascii=False)}")
                
                # Check whether another family has a power strip endpoint configured.
                ret3 = HomemateJsonData.get_devices_status(token, "", uid, USER, fid, 0)
                async with s.post(ret3["url"], data=ret3["data"], headers=HTTP_HEADERS, ssl=False) as r:
                    data2 = json.loads(await r.text()).get("data", {})
                    devs2 = data2.get("device", [])
                    for d in devs2:
                        if d.get("deviceId") == DEV:
                            print("\n  🔌 Power strip (deviceFlag=0):")
                            print(f"    {json.dumps(d, ensure_ascii=False)[:500]}")

asyncio.run(main())
