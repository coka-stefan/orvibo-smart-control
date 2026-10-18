import logging
import json
import aiohttp
from aiohttp import ClientSession
from typing import Optional, Any, Dict, List
from .packet import HomemateJsonData
from .protocol import normalize_password_hash
from .cloud import (
    CHINA_CLOUD,
    CloudEndpoint,
    cloud_candidates,
    cloud_for_api_host,
)
from .const import (
    ID_UNSET,
    HTTP_HEADERS,
    DEVICE_TYPE_MAP,
    CLASS_ID_MAP,
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_COVER,
    DEVICE_TYPE_SWITCH,
    DEVICE_TYPE_SENSOR,
    DEVICE_TYPE_CLIMATE,
)

_LOGGER = logging.getLogger(__name__)


class HttpsClient:
    def __init__(
        self,
        username: str,
        password_hash: str,
        session: ClientSession | None = None,
        cloud: CloudEndpoint = CHINA_CLOUD,
    ):
        self.username = username
        self.password_hash = normalize_password_hash(password_hash)
        self._session = session
        self.cloud = cloud

        self.user_id = None
        self.session_id: Optional[str] = None
        self.access_token: Optional[str] = None
        self.family_id: Optional[str] = None
        self.family_name: Optional[str] = None
        self.family_list: List[Dict[str, str]] = []  # All families
        self.gateway_ips: Dict[str, str] = {}  # MixPad gateway uid to LAN IP

    @property
    def is_logged_in(self) -> bool:
        return self.access_token is not None and self.user_id is not None

    async def close(self):
        """Close the client and release its resources."""
        self.access_token = None

    def set_session_id(self, session_id: str):
        self.session_id = session_id

    @property
    def api_host(self) -> str:
        """REST endpoint owned by this client instance."""
        return self.cloud.api_host

    async def _send_request(self, url, data, params=None):
        session = self._session
        owns_session = session is None
        if session is None:
            session = aiohttp.ClientSession(connector=aiohttp.TCPConnector())
        try:
            if not data:
                request = session.get(
                    url=url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers=HTTP_HEADERS,
                    skip_auto_headers=["Accept", "Connection"],
                )
            else:
                request = session.post(
                    url=url,
                    timeout=aiohttp.ClientTimeout(total=10),
                    data=data,
                    headers=HTTP_HEADERS,
                    skip_auto_headers=["Accept", "Connection"],
                )
            async with request as resp:
                resp.raise_for_status()
                response_text = await resp.text()
                return json.loads(response_text)
        finally:
            if owns_session:
                await session.close()

    async def ensure_login(self) -> bool:
        if not self.access_token or not self.user_id:
            data = await self._fetch_access_token()
            if data:
                self.access_token = data.get("access_token", "")
                self.user_id = data.get("user_id", "")
            if not self.access_token or not self.user_id:
                return False

        # Fetch family information (including family_name and family_list even if family_id is already set)
        data = await self._fetch_family()
        if data:
            # Use the fetched family_id if none was set previously
            if not self.family_id:
                self.family_id = data.get("familyId", "")
            self.family_name = data.get("familyName", "")

        return bool(self.access_token and self.user_id and self.family_id)

    async def _fetch_access_token(self) -> dict:
        try:
            if self.session_id is None or self.session_id == bytes(ID_UNSET).decode('utf-8'):
                ret = HomemateJsonData.get_access_token_by_password(
                    self.username, self.password_hash, api_host=self.api_host
                )
            else:
                ret = HomemateJsonData.get_access_token_by_session_id(
                    self.session_id, api_host=self.api_host
                )
            resp = await self._send_request(
                ret["url"],
                ret["data"],
                params=ret.get("params"),
            )
            if "message" in resp:
                _LOGGER.error(resp["message"])
                return {}
            if "data" not in resp:
                _LOGGER.error("Response packet is missing [data]")
                return {}
            if "access_token" not in resp["data"]:
                _LOGGER.error("Response packet is missing [access_token]")
                return {}
            _LOGGER.info("HTTPS access token request succeeded")
            return resp["data"]
        except Exception as e:
            _LOGGER.error("HTTPS request failed: %s", e)
            return {}

    async def _fetch_family(self) -> dict:
        try:
            if not self.user_id or not self.access_token:
                _LOGGER.debug("Skipping family request: userId or accessToken is missing")
                return {}
            ret = HomemateJsonData.get_family_statistics_users(
                self.user_id, self.access_token, api_host=self.api_host
            )
            resp = await self._send_request(ret['url'], ret['data'])
            if "message" in resp:
                _LOGGER.error(resp["message"])
                return {}
            if "data" not in resp:
                _LOGGER.error("Response packet is missing [data]")
                return {}
            data = resp["data"]
            if not isinstance(data, list):
                _LOGGER.error("Response packet [data] is not an array")
                return {}
            
            # Store the complete family list
            self.family_list = [
                {"familyId": item.get("familyId", ""), "familyName": item.get("familyName", "Unknown family")}
                for item in data if item.get("familyId")
            ]
            _LOGGER.info("Retrieved %s families", len(self.family_list))
            
            # Confirm an existing family belongs to the current region to avoid false positives during region detection.
            if self.family_id:
                selected = next(
                    (
                        family
                        for family in self.family_list
                        if family["familyId"] == self.family_id
                    ),
                    None,
                )
                if selected is None:
                    _LOGGER.info(
                        "Family %s does not belong to cloud region %s",
                        self.family_id,
                        self.cloud.region.value,
                    )
                    return {}
                self.family_name = selected["familyName"]
            elif self.family_list:
                first_family = self.family_list[0]
                self.family_id = first_family["familyId"]
                self.family_name = first_family["familyName"]
            
            if not self.family_id:
                _LOGGER.error("Response packet is missing [familyId]")
                return {}
            return {"familyId": self.family_id, "familyName": self.family_name}
        except Exception as e:
            _LOGGER.error("HTTPS request failed: %s", e)
            return {}

    def set_family(self, family_id: str):
        """Set the currently selected family."""
        self.family_id = family_id
        for family in self.family_list:
            if family["familyId"] == family_id:
                self.family_name = family["familyName"]
                break
        _LOGGER.info("Switched to family: %s (%s)", self.family_name, self.family_id)

    async def switch_cloud(
        self,
        cloud: CloudEndpoint,
        *,
        family_id: str | None = None,
    ) -> None:
        """Switch this client to another account partition and clear auth state."""
        self.cloud = cloud
        self.access_token = None
        self.user_id = None
        self.session_id = None
        self.family_id = family_id
        self.family_name = None
        self.family_list = []
        _LOGGER.info("Cloud region changed to %s (%s)", cloud.region.value, cloud.api_host)

    async def switch_host(self, host: str) -> None:
        """Compatibility wrapper accepting only known ORVIBO API hosts."""
        await self.switch_cloud(cloud_for_api_host(host))

    async def async_detect_cloud(self, family_id: str | None = None) -> bool:
        """Select the first partition where this account/family can log in."""
        preferred_family = str(family_id or self.family_id or "").strip() or None
        for cloud in cloud_candidates(self.cloud):
            await self.switch_cloud(cloud, family_id=preferred_family)
            if await self.ensure_login():
                return True
        return False

    async def _readtable(self, device_flag: int) -> Optional[Dict[str, Any]]:
        """Send a readtable request and return the merged data dictionary."""
        ret = HomemateJsonData.get_devices_status(
            access_token=self.access_token,
            session_id=self.session_id or "",
            user_id=self.user_id,
            user_name=self.username,
            family_id=self.family_id,
            device_flag=device_flag,
            api_host=self.api_host,
        )
        resp = await self._send_request(ret['url'], ret['data'])

        if "message" in resp:
            _LOGGER.error("readtable(deviceFlag=%s) failed: %s", device_flag, resp["message"])
            return None
        if "data" not in resp:
            _LOGGER.error("readtable(deviceFlag=%s) response packet is missing [data]", device_flag)
            return None

        data = resp["data"]
        # data may be a list when the server returns tables in chunks; merge every chunk
        if isinstance(data, list):
            _LOGGER.info("readtable(deviceFlag=%s) returned %s data chunks", device_flag, len(data))
            merged: Dict[str, Any] = {}
            for element in data:
                if not isinstance(element, dict):
                    continue
                for key, value in element.items():
                    if key not in merged:
                        merged[key] = value
                    elif isinstance(merged[key], list) and isinstance(value, list):
                        merged[key] = merged[key] + value
                    elif isinstance(merged[key], dict) and isinstance(value, dict):
                        merged[key] = {**merged[key], **value}
            data = merged

        _LOGGER.info(f"readtable(deviceFlag={device_flag}) data keys: "
                     f"{list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
        return data if isinstance(data, dict) else None

    async def fetch_device_status(self) -> Optional[Dict[str, Any]]:
        """Fetch the device state list through the /v2/cmd/app/readtable API.

        deviceFlag=0 may return only account-level tables (account/userGatewayBind/gateway);
        if so, request device-level tables (device/deviceStatus) with deviceFlag=1 and merge them.
        """
        try:
            if not await self.ensure_login():
                _LOGGER.error("HTTPS client is not logged in")
                return None

            data = await self._readtable(device_flag=0)
            if data is None:
                return None

            if "device" not in data:
                _LOGGER.warning("readtable(deviceFlag=0) returned no device table; trying deviceFlag=1 ...")
                data_flag1 = await self._readtable(device_flag=1)
                if data_flag1:
                    data = {**data, **data_flag1}

            if "device" not in data:
                _LOGGER.warning(
                    f"readtable response is still missing the device table: gateway={data.get('gateway')}, "
                    f"userGatewayBind={data.get('userGatewayBind')}"
                )
            self.gateway_ips = self._extract_gateway_ips(data)
            return data
        except Exception as e:
            _LOGGER.error("Failed to fetch device states: %s", e)
            return None

    @staticmethod
    def _extract_gateway_ips(data: Dict[str, Any]) -> Dict[str, str]:
        """Extract MixPad gateway uid to LAN IP from readtable (ported from the LAN source implementation)."""
        from .protocol import _safe_int, _table_rows

        mixpad_uids = {
            str(item["uid"])
            for item in _table_rows(data.get("device"), "deviceId")
            if _safe_int(item.get("deviceType")) == 114 and item.get("uid")
            and item.get("delFlag") not in (1, "1")
        }
        result: Dict[str, str] = {}
        for gateway in _table_rows(data.get("gateway"), "uid"):
            if gateway.get("delFlag") in (1, "1"):
                continue
            uid = gateway.get("uid")
            raw_ip = gateway.get("localStaticIP") or gateway.get("ip")
            if isinstance(uid, str) and uid in mixpad_uids and isinstance(raw_ip, str) and raw_ip:
                result[uid] = raw_ip.split(":", maxsplit=1)[0]
        return result

    async def fetch_device_desc(self, last_update_time: int = 0) -> Optional[Dict[str, Any]]:
        """Fetch device descriptions and states through getDeviceDesc for the initial full state."""
        try:
            if not await self.ensure_login():
                _LOGGER.error("HTTPS client is not logged in")
                return None

            if not self.access_token:
                _LOGGER.error("accessToken is empty")
                return None

            url = f"https://{self.api_host}/getDeviceDesc?source=ZhiJia365&lastUpdateTime={last_update_time}&accessToken={self.access_token}"

            headers = {
                **HTTP_HEADERS,
            }

            _LOGGER.debug("Requesting getDeviceDesc API: host=%s", self.api_host)

            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector()
            ) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        _LOGGER.error("getDeviceDesc API failed: %s", response.status)
                        return None
                    
                    data = await response.json()
                    _LOGGER.info("getDeviceDesc API returned data type: %s", type(data))
                    if isinstance(data, dict):
                        _LOGGER.info("getDeviceDesc returned keys: %s", list(data.keys()))
                        if "devices" in data:
                            devices = data.get("devices", [])
                            _LOGGER.info("Device count: %s", len(devices))
                            if len(devices) > 0 and isinstance(devices[0], dict):
                                _LOGGER.info("First device keys: %s", list(devices[0].keys())[:15])
                        if "status" in data:
                            _LOGGER.info(f"status: {data.get('status')}")
                    
                    return data
        except Exception as e:
            _LOGGER.error("getDeviceDesc API call failed: %s", e)
            return None

    def parse_device_desc(self, device_desc_data: dict) -> Dict[str, Dict[str, Any]]:
        """Parse getDeviceDesc data and extract device states."""
        device_status_map = {}
        
        devices = device_desc_data.get("deviceDescList", device_desc_data.get("devices", []))
        if not isinstance(devices, list):
            _LOGGER.warning("getDeviceDesc returned a non-list deviceDescList: %s", type(devices))
            return device_status_map
        
        for device in devices:
            if not isinstance(device, dict):
                continue
            
            device_id = device.get("deviceId", "")
            if not device_id:
                continue
            
            status_info = {}
            
            properties = device.get("properties", {})
            if isinstance(properties, dict):
                onoff_val = properties.get("onoff")
                if onoff_val is not None:
                    if isinstance(onoff_val, dict):
                        status_info["state"] = onoff_val.get("status", "off") == "on"
                    elif isinstance(onoff_val, str):
                        status_info["state"] = onoff_val == "on"
                    elif isinstance(onoff_val, bool):
                        status_info["state"] = onoff_val
                    elif isinstance(onoff_val, int):
                        status_info["state"] = onoff_val == 1
                
                brightness_val = properties.get("brightness")
                if brightness_val is not None:
                    if isinstance(brightness_val, dict):
                        val = brightness_val.get("brightness", brightness_val.get("value"))
                        if val is not None:
                            status_info["brightness"] = int(val)
                    else:
                        if isinstance(brightness_val, (int, float)):
                            status_info["brightness"] = int(brightness_val)
                
                colortemp_val = properties.get("colortemp")
                if colortemp_val is not None:
                    if isinstance(colortemp_val, dict):
                        val = colortemp_val.get("colortemp", colortemp_val.get("value"))
                        if val is not None and val > 0:
                            status_info["color_temp"] = int(val)
                    else:
                        if isinstance(colortemp_val, (int, float)) and colortemp_val > 0:
                            status_info["color_temp"] = int(colortemp_val)
                
                percent_val = properties.get("percent")
                if percent_val is not None:
                    if isinstance(percent_val, dict):
                        val = percent_val.get("percent", percent_val.get("value"))
                        if val is not None:
                            status_info["position"] = int(val)
                    else:
                        if isinstance(percent_val, (int, float)):
                            status_info["position"] = int(percent_val)
                
                temp_val = properties.get("temperature")
                if temp_val is not None:
                    if isinstance(temp_val, dict):
                        val = temp_val.get("value")
                        if val is not None:
                            status_info["temperature"] = float(val)
                    else:
                        if isinstance(temp_val, (int, float)):
                            status_info["temperature"] = float(temp_val)
                
                hum_val = properties.get("humidity")
                if hum_val is not None:
                    if isinstance(hum_val, dict):
                        val = hum_val.get("value")
                        if val is not None:
                            status_info["humidity"] = float(val)
                    else:
                        if isinstance(hum_val, (int, float)):
                            status_info["humidity"] = float(hum_val)
                
                bat_val = properties.get("battery")
                if bat_val is not None:
                    if isinstance(bat_val, dict):
                        val = bat_val.get("power", bat_val.get("value"))
                        if val is not None:
                            status_info["battery"] = int(float(val))
                    else:
                        if isinstance(bat_val, (int, float)):
                            status_info["battery"] = int(float(bat_val))
                
                value3_val = properties.get("value3")
                if value3_val is not None:
                    if isinstance(value3_val, dict):
                        val = value3_val.get("value")
                        if val is not None:
                            status_info["value3"] = int(val)
                    else:
                        if isinstance(value3_val, (int, float)):
                            status_info["value3"] = int(value3_val)
                
                value4_val = properties.get("value4")
                if value4_val is not None:
                    if isinstance(value4_val, dict):
                        val = value4_val.get("value")
                        if val is not None:
                            status_info["value4"] = int(val)
                    else:
                        if isinstance(value4_val, (int, float)):
                            status_info["value4"] = int(value4_val)
            
            online_val = device.get("online")
            if online_val is not None:
                status_info["online"] = self._parse_online_status(online_val)
            
            uid = device.get("uid", "")
            if uid:
                status_info["uid"] = uid
            
            status_id = device.get("statusId", "")
            if status_id:
                status_info["status_id"] = status_id
            
            ext_addr = device.get("extAddr", "")
            if ext_addr:
                status_info["ext_addr"] = ext_addr
            
            _LOGGER.info("Parsed getDeviceDesc device: deviceId=%s, state=%s, online=%s, brightness=%s, color_temp=%s, position=%s", device_id, status_info.get("state", "N/A"), status_info.get("online", "N/A"), status_info.get("brightness"), status_info.get("color_temp"), status_info.get("position"))
            
            device_status_map[device_id] = status_info
        
        _LOGGER.info("Parsed %s device states from getDeviceDesc", len(device_status_map))
        return device_status_map

    def parse_device_status_list(self, device_status_data: dict) -> List[Dict[str, Any]]:
        """Parse a device list from the /v2/cmd/app/readtable response.

        Parsing is implemented in protocol.py; this wrapper preserves the interface.
        device_status_data is resp["data"] returned by fetch_device_status() (the inner readtable data).
        """
        from .protocol import parse_readtable_devices, device_to_dict

        result = [device_to_dict(device) for device in parse_readtable_devices(
            {"code": 0, "data": device_status_data}
        )]

        # Skip parent switch devices (type=135/136 with empty properties)
        filtered = []
        for dev in result:
            dt = dev.get("device_type_raw")
            if dt in (135, 136):
                props = dev.get("properties", {})
                if isinstance(props, dict) and len(props) == 0:
                    _LOGGER.info("Skipping parent switch device: deviceId=%s, name=%s", dev["device_id"], dev.get("device_name"))
                    continue
            filtered.append(dev)
        
        _LOGGER.info("Parsed %s devices from device_status", len(filtered))
        return filtered

    async def fetch_homepage_data(self) -> Optional[Dict[str, Any]]:
        try:
            if not await self.ensure_login():
                _LOGGER.error("HTTPS client is not logged in")
                return None

            ret = HomemateJsonData.get_homepage_data(
                self.family_id,
                self.user_id,
                self.access_token,
                api_host=self.api_host,
            )
            resp = await self._send_request(ret['url'], ret['data'])

            if "message" in resp:
                _LOGGER.error(resp["message"])
                return None
            if "data" not in resp:
                _LOGGER.error("Response packet is missing [data]")
                return None

            return resp["data"]
        except Exception as e:
            _LOGGER.error("Failed to fetch homepage data: %s", e)
            return None

    def parse_device_list(self, homepage_data: dict) -> List[Dict[str, Any]]:
        """Use the inventory parser for homepage fallbacks too."""
        data = dict(homepage_data)
        data["device"] = data.get("deviceList") or data.get("device") or []
        return self.parse_device_status_list(data)

    def _get_device_type(self, item: dict) -> Optional[str]:
        device_type_raw = item.get("deviceType")
        sub_device_type = item.get("subDeviceType")
        class_id = item.get("classId")

        try:
            device_type_raw = int(device_type_raw) if device_type_raw is not None else None
            sub_device_type = int(sub_device_type) if sub_device_type is not None else None
            class_id = int(class_id) if class_id is not None else None
        except (TypeError, ValueError):
            device_type_raw = None
            class_id = None

        if device_type_raw in (14, 162):
            return DEVICE_TYPE_SENSOR
        if device_type_raw == 0:
            return DEVICE_TYPE_LIGHT
        if device_type_raw == 102:
            return DEVICE_TYPE_LIGHT
        if device_type_raw == 112:
            ui_model = (
                item.get("ui", {}).get("model")
                if isinstance(item.get("ui"), dict)
                else None
            )
            return (
                DEVICE_TYPE_CLIMATE
                if sub_device_type == -2 and (
                    ui_model == "orb_floorheat"
                    or item.get("model") == "2ac836760da10748856a7e4eafb91efa"
                )
                else None
            )
        if device_type_raw == 10086:
            # Do not create controllable entities for virtual light groups until the control protocol is verified on hardware.
            return None
        if device_type_raw == 300:
            return DEVICE_TYPE_CLIMATE if sub_device_type == 481 else DEVICE_TYPE_SENSOR if sub_device_type == 491 else None
        if device_type_raw == 506:
            return DEVICE_TYPE_COVER if sub_device_type == 408 else None
        if device_type_raw == 42:
            return DEVICE_TYPE_COVER if sub_device_type == -2 else None
        if device_type_raw == 501:
            return DEVICE_TYPE_LIGHT if sub_device_type in (426, 429) else None
        if device_type_raw == 502:
            return DEVICE_TYPE_LIGHT if sub_device_type == 431 else None
        if device_type_raw == 503:
            return DEVICE_TYPE_LIGHT if sub_device_type in (436, 461) else None
        if device_type_raw == 522:
            return DEVICE_TYPE_SENSOR if sub_device_type == 463 else None

        if class_id in CLASS_ID_MAP:
            return CLASS_ID_MAP[class_id]

        if device_type_raw in DEVICE_TYPE_MAP:
            return DEVICE_TYPE_MAP[device_type_raw]

        return None

    def _parse_online_status(self, online_value) -> bool:
        """Parse online state in multiple formats."""
        if online_value is None:
            return False
        if isinstance(online_value, bool):
            return online_value
        if isinstance(online_value, int):
            return online_value == 1
        if isinstance(online_value, str):
            value = online_value.strip().lower()
            return value in ("online", "1", "true", "yes")
        return False
