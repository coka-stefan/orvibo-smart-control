import json
import struct
import binascii
import logging
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import (
    Cipher, algorithms, modes
)
from cryptography.hazmat.primitives import padding
from .functions import (
    text_utils_is_empty,
    hmac_sha256,
    generate_timestamp,
    generate_serial,
    generate_uuid,
)

_LOGGER = logging.getLogger(__name__)

from .const import (
    DEFAULT_KEY, SIGN_KEY, MAGIC,
    HTTPS_HOST, HTTP_HEADERS,
    SOFTWARE_NAME, SOFTWARE_VER, SOFTWARE_VERSION,
    SYS_VERSION, HARDWARE_VERSION, LANGUAGE, PHONE_NAME, DEBUG_INFO,
    CMD_HELLO, CMD_LOGIN, CMD_CONTROL, CMD_HEARTBEAT,
    CMD_CLOTHES_HORSE_CONTROL, CMD_CLOTHES_HORSE_QUERY,
    CMD_COS_AUTH, CMD_TEMP_PASSWORD, CMD_DELETE_AUTHORIZATION,
)

# Current HTTPS API host (module-level; can be switched at runtime between China and international regions)
_api_host = HTTPS_HOST


def set_api_host(host: str) -> None:
    global _api_host
    _api_host = host


def get_api_host() -> str:
    return _api_host
class HomematePacket:
    def __init__(self, data: bytes, keys: dict):
        self.raw = data
        if not data:
            self.magic = MAGIC
            self.length = 0
            self.packet_type = bytes([0x70, 0x6b])
            self.crc = None
            self.session_id = None
            self.json_payload = None
            return

        try:
            self.magic = data[0:2]
            assert self.magic == MAGIC

            self.length = struct.unpack(">H", data[2:4])[0]
            assert self.length == len(data)

            self.packet_type = data[4:6]
            assert self.packet_type == bytes([0x70, 0x6b]) or \
                self.packet_type == bytes([0x64, 0x6b])

            self.crc = binascii.crc32(data[42:]) & 0xFFFFFFFF
            data_crc = struct.unpack(">I", data[6:10])[0]
            assert self.crc == data_crc
        except AssertionError:
            _LOGGER.error("Bad packet (len=%d): %s", len(data), data.hex())
            raise

        self.session_id = data[10:42]

        current_key = DEFAULT_KEY.encode("utf-8")
        if self.packet_type == bytes([0x64, 0x6b]):
            current_key = keys[self.session_id.decode('utf-8')]

        if data[42:]:
            self.json_payload = self.decrypt_payload(current_key, data[42:])
        else:
            self.json_payload = None

    @classmethod
    def parse_length(cls, data: bytes):
        try:
            magic = data[0:2]
            assert magic == MAGIC
            length = struct.unpack(">H", data[2:4])[0]
            return length
        except Exception as e:
            _LOGGER.error("Bad packet: %s", str(e))
            raise

    @classmethod
    def decrypt_payload(cls, key: bytes, encrypted_payload: bytes):
        decryptor = Cipher(
            algorithms.AES(key),
            modes.ECB(),
            backend=default_backend()
        ).decryptor()
        data = decryptor.update(encrypted_payload)
        unpadder = padding.PKCS7(128).unpadder()
        unpad = unpadder.update(data)
        unpad += unpadder.finalize()

        if unpad[-1] == 0x00:
            unpad = unpad[:-1]
        return json.loads(unpad.decode('utf-8'))

    @classmethod
    def encrypt_payload(cls, key: bytes, payload: str):
        data = payload.encode('utf-8')

        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data)
        padded_data += padder.finalize()

        encryptor = Cipher(
            algorithms.AES(key),
            modes.ECB(),
            backend=default_backend()
        ).encryptor()

        encrypted_payload = encryptor.update(padded_data)
        return encrypted_payload

    @classmethod
    def build_packet(cls, packet_type: bytes, key: bytes, session_id: bytes, payload: dict):
        payload_str = json.dumps(payload, separators=(',', ':'))
        encrypted_payload = cls.encrypt_payload(key, payload_str)
        crc = struct.pack('>I', binascii.crc32(encrypted_payload) & 0xFFFFFFFF)
        length = struct.pack('>H', len(encrypted_payload) + len(MAGIC + packet_type + crc + session_id) + 2)

        packet = MAGIC + length + packet_type + crc + session_id + encrypted_payload
        return packet


class HomemateJsonData:
    @classmethod
    def ssl_get_session(cls):
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        identifier = generate_uuid()[:12]

        payload = {
            "source": SOFTWARE_NAME,
            "softwareVersion": SOFTWARE_VERSION,
            "sysVersion": SYS_VERSION,
            "hardwareVersion": HARDWARE_VERSION,
            "language": LANGUAGE,
            "identifier": identifier,
            "phoneName": PHONE_NAME,
            "cmd": CMD_HELLO,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_switch(cls, username: str, device_id: str, device_uid: str, state: bool):
        """Switch control (set property format, used by types 501/135/136, etc.)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "set property",
            "value1": 0,
            "value2": 0,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "properties": {"onoff": {"status": "on" if state else "off"}},
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_ac(
        cls,
        username: str,
        device_id: str,
        device_uid: str,
        *,
        order: str,
        value1: int | None = None,
        value2: int | None = None,
        value3: int | None = None,
        value4: int | None = None,
    ):
        """Raw AC control (cmd=15 set property; value1-value4 follow the app semantics)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        return {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": order,
            "value1": value1 if value1 is not None else 0,
            "value2": value2 if value2 is not None else 0,
            "value3": value3 if value3 is not None else 0,
            "value4": value4 if value4 is not None else 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }

    @classmethod
    def ssl_control_dimmable_light_brightness(cls, username: str, device_id: str, device_uid: str, brightness_percent: int):
        """Dimmable light brightness control (set property format for type=502).

        Args:
            brightness_percent: Brightness percentage (0-100)
        """
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        bri = max(0, min(int(brightness_percent), 100))
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "set property",
            "value1": 0,
            "value2": 0,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "properties": {"brightness": {"percent": bri}},
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_zigbee_dimmable_light_onoff(cls, username: str, device_id: str, device_uid: str, state: bool, brightness: int = 255):
        """Zigbee dimmable light switch control (on/off format for deviceType=0, subDeviceType=-2)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        bri = max(0, min(int(brightness), 255))
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "on" if state else "off",
            "value1": 0 if state else 1,
            "value2": bri,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_zigbee_dimmable_light_brightness(cls, username: str, device_id: str, device_uid: str, brightness_255: int):
        """Zigbee dimmable light brightness control (move to level format for deviceType=0, subDeviceType=-2)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        bri = max(1, min(int(brightness_255), 255))
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "move to level",
            "value1": 0,
            "value2": bri,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_fast_move_dim_color_light_onoff(cls, username: str, device_id: str, device_uid: str, state: bool, brightness: int = 0, colortemp_mired: int = 0):
        """Fast Move dimmable color-temperature light switch control (on/off format for statusType=2, subDeviceType=6)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "on" if state else "off",
            "value1": 0 if state else 1,
            "value2": int(brightness),
            "value3": int(colortemp_mired),
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "properties": {},
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_fast_move_dim_color_light_brightness(cls, username: str, device_id: str, device_uid: str, brightness: int, colortemp_mired: int = 0):
        """Fast Move dimmable color-temperature light brightness control (fast move to level format for statusType=2, subDeviceType=6)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        bri = max(0, min(int(brightness), 255))
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "fast move to level",
            "value1": 0,
            "value2": bri,
            "value3": int(colortemp_mired),
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "properties": {},
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_fast_move_dim_color_light_colortemp(cls, username: str, device_id: str, device_uid: str, brightness: int, colortemp_mired: int):
        """Fast Move dimmable color-temperature light color temperature control (fast color temperature format for statusType=2, subDeviceType=6)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        bri = max(0, min(int(brightness), 255))
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "fast color temperature",
            "value1": 0,
            "value2": bri,
            "value3": int(colortemp_mired),
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "properties": {},
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_cct_light_onoff(cls, username: str, device_id: str, device_uid: str, state: bool):
        """Color temperature light switch control (set property format for statusType=503)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "set property",
            "value1": 0,
            "value2": 0,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "properties": {"onoff": {"status": "on" if state else "off"}},
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_property(cls, username: str, device_id: str, device_uid: str, properties: dict):
        """Build the common cmd=15 ``set property`` envelope."""
        return {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "set property",
            "value1": 0,
            "value2": 0,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "properties": properties,
            "cmd": CMD_CONTROL,
            "serial": generate_serial(),
            "clientType": 1,
            "uniSerial": generate_serial(use_time=True),
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }

    @classmethod
    def ssl_control_floor_heating_power(cls, username: str, device_id: str, device_uid: str, state: bool):
        return cls.ssl_control_property(
            username, device_id, device_uid,
            {"onoff": {"status": "on" if state else "off"}},
        )

    @classmethod
    def ssl_control_floor_heating_temperature(cls, username: str, device_id: str, device_uid: str, temperature: int):
        target = max(8, min(35, int(round(temperature))))
        return cls.ssl_control_property(
            username, device_id, device_uid,
            {"thermostat": {"targetTemp": target}},
        )

    @classmethod
    def ssl_control_dream_curtain_action(cls, username: str, device_id: str, device_uid: str, action: str):
        if action not in {"open", "close", "pause"}:
            raise ValueError("invalid dream curtain action")
        return cls.ssl_control_property(
            username, device_id, device_uid, {"curtain": {"action": action}}
        )

    @classmethod
    def ssl_control_dream_curtain_percent(cls, username: str, device_id: str, device_uid: str, percent: int):
        position = max(0, min(100, int(percent)))
        return cls.ssl_control_property(
            username, device_id, device_uid, {"curtain": {"percent": position}}
        )

    @classmethod
    def ssl_control_dream_curtain_angle(cls, username: str, device_id: str, device_uid: str, angle: int):
        value = max(0, min(180, int(angle)))
        return cls.ssl_control_property(
            username, device_id, device_uid, {"curtain": {"angle": value}}
        )

    @classmethod
    def ssl_control_cct_light_brightness(cls, username: str, device_id: str, device_uid: str, brightness_percent: int):
        """Color temperature light brightness control (set property format for statusType=503)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        bri = max(0, min(int(brightness_percent), 100))
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "set property",
            "value1": 0,
            "value2": 0,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "properties": {"brightness": {"percent": bri}},
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_cct_light_colortemp(cls, username: str, device_id: str, device_uid: str, colortemp_k: int):
        """Color temperature light color temperature control (set property format for statusType=503)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        ct = max(2700, min(int(colortemp_k), 6500))
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "set property",
            "value1": 0,
            "value2": 0,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "properties": {"colorTemp": {"value": ct}},
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_light(cls, username: str, device_id: str, device_uid: str, state: bool, brightness: int = 0, colortemp_mired: int = 0):
        """Light switch control (order=on/off + value1 format for types 102/38, etc.)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "order": "on" if state else "off",
            "value1": 0 if state else 1,
            "value2": brightness,
            "value3": colortemp_mired,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_cover(cls, username: str, device_id: str, device_uid: str, position: int, stop_value2: int = 0):
        """Control a curtain (position: 0-100, or the order 'open'/'close'/'stop')."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        if isinstance(position, str) and position in ("open", "close", "stop"):
            # Relay controllers have no position; app scenes send open with value1=100.
            order = position
            value1 = 100 if position == "open" else 0
        else:
            order = "open"
            value1 = int(position)
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": order,
            "value1": value1,  # Position percentage (0-100)
            "value2": stop_value2 if order == "stop" else 0,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_legacy_floor_heating(
        cls,
        username: str,
        device_id: str,
        device_uid: str,
        *,
        order: str,
        value1: int,
        value2: int,
    ):
        """Control verified type=112 ``orb_floorheat`` devices."""
        return {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": order,
            "value1": int(value1),
            "value2": int(value2),
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": generate_serial(),
            "clientType": 1,
            "uniSerial": generate_serial(use_time=True),
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }

    @classmethod
    def ssl_control_ventilation(cls, username: str, device_id: str, device_uid: str, value1: int):
        """Ventilation system control (set property format for deviceType=516, classId=1114).
        value1: 0=slow, 50=stop, 100=fast
        """
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "set property",
            "value1": value1,
            "value2": 0,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_light_brightness(cls, username: str, device_id: str, device_uid: str, brightness: int):
        """Set light brightness (range: 0-255)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        brightness_val = min(int(brightness), 255)
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "on",
            "value1": 0,
            "value2": brightness_val,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_light_colortemp(cls, username: str, device_id: str, device_uid: str, colortemp_k: int, brightness: int = 0):
        """Set light color temperature (input in Kelvin, converted to mireds for transmission).

        Note: type=38 control commands must omit the properties field and use order="fast color temperature".
        """
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        colortemp_mired = 1000000 // colortemp_k if colortemp_k > 0 else 0
        brightness_val = min(int(brightness), 255) if brightness else 0
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "fast color temperature",
            "value1": 0,
            "value2": brightness_val,
            "value3": colortemp_mired,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_control_light_full(cls, username: str, device_id: str, device_uid: str,
                                brightness: int = None, colortemp_k: int = None, power: bool = True):
        """Set all light parameters (brightness, color temperature, and power).

        Note: type=38 control commands use Kelvin directly for value3 and use order="on"/"off";
        the properties field must be omitted.
        """
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        colortemp_val = colortemp_k if colortemp_k and colortemp_k > 0 else 0
        brightness_val = brightness if brightness else 0
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            "groupId": "",
            "order": "on" if power else "off",
            "value1": 0 if power else 1,
            "value2": brightness_val,
            "value3": colortemp_val,
            "value4": 0,
            "delayTime": 0,
            "qualityOfService": 1,
            "defaultResponse": 1,
            "propertyResponse": 0,
            "cmd": CMD_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_clothes_horse_control(cls, username: str, device_id: str, device_uid: str, ctrl_field: str, ctrl_value: str):
        """Build a clothes dryer control command (cmd=98).

        Args:
            ctrl_field: Control field, e.g. lightingCtrl/sterilizingCtrl/windDryingCtrl/heatDryingCtrl/mainSwitchCtrl/motorCtrl
            ctrl_value: Control value, e.g. on/off/up/down/stop
        """
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        payload = {
            "uid": device_uid,
            "userName": username,
            "deviceId": device_id,
            ctrl_field: ctrl_value,
            "cmd": CMD_CLOTHES_HORSE_CONTROL,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_clothes_horse_query(cls, device_id: str):
        """Build a clothes dryer state query command (cmd=100)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        payload = {
            "deviceList": [{"deviceId": device_id}],
            "cmd": CMD_CLOTHES_HORSE_QUERY,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_login(cls, username: str, password_md5: str, family_id: str):
        serial = generate_serial()
        payload = {
            "userName": username,
            "password": password_md5,
            "cmd": CMD_LOGIN,
            "serial": serial,
            "clientType": 1,
            "source": SOFTWARE_VER,
            "familyId": family_id,
            "type": 4,
            "needAccountDetailError": True,
        }
        return payload

    @classmethod
    def ssl_heartbeat(cls):
        """Build a heartbeat packet (cmd=32)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        payload = {
            "cmd": CMD_HEARTBEAT,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_cos_auth(cls, user_id: str, device_id: str, device_uid: str, family_id: str):
        """Build a lock media authorization request (cmd=313, Skill.GetCOSAuthorization).

        Matches AbstractC0003b.m28V in the Smart Home 365 app:
        The inner JSON string contains namespace/requestId/version/userId/deviceId/
        familyId/uid/type=lock, wrapped in the outer {"request": "<inner JSON>"} object.
        The response QueryTxAuthResponse.security provides credentials for the lock-specific COS bucket.
        """
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        inner = {
            "namespace": "Skill.GetCOSAuthorization",
            "requestId": generate_uuid(),
            "version": 1,
            "userId": user_id,
            "deviceId": device_id,
            "familyId": family_id,
            "uid": device_uid,
            "type": "lock",
        }
        payload = {
            "request": json.dumps(inner, separators=(",", ":")),
            "cmd": CMD_COS_AUTH,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }
        return payload

    @classmethod
    def ssl_temp_password(
        cls,
        device_id: str,
        device_uid: str,
        name: str,
        auth_type: int,
        minutes: int,
        number: int,
        phone: str,
        start_time: int,
        end_time: int,
    ):
        """Build a temporary password request (cmd=246, verified against an app packet capture)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        return {
            "deviceId": device_id,
            "uid": device_uid,
            "userName": name,
            "type": auth_type,
            "effectTime": minutes,
            "startTime": start_time,
            "endTime": end_time,
            "number": number,
            "phone": phone,
            "cmd": CMD_TEMP_PASSWORD,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }

    @classmethod
    def ssl_delete_authorization(
        cls,
        device_id: str,
        device_uid: str,
        authorized_id: int,
    ):
        """Build an authorization deletion request (cmd=247; authorizedId comes from the send response)."""
        serial = generate_serial()
        uniSerial = generate_serial(use_time=True)
        return {
            "uid": device_uid,
            "deviceId": device_id,
            "userId": authorized_id,
            "cmd": CMD_DELETE_AUTHORIZATION,
            "serial": serial,
            "clientType": 1,
            "uniSerial": uniSerial,
            "serverRecord": False,
            "ver": SOFTWARE_VER,
            "debugInfo": DEBUG_INFO,
        }

    @classmethod
    def create_sign(cls, params, key=SIGN_KEY):
        sorted_keys = sorted(params.keys())
        sb = []
        for k in sorted_keys:
            value = params[k]
            if not text_utils_is_empty(value):
                sb.append(f"{k}={value}&")
        sb.append(f"key={key}")
        sign_str = ''.join(sb)
        sign = hmac_sha256(key, sign_str)
        return sign

    @classmethod
    def get_access_token_by_password(
        cls, username: str, password_md5: str, api_host: str | None = None
    ):
        """Build the legacy GET query without materializing a credential URL."""
        url = f"https://{api_host or get_api_host()}/getOauthToken"
        _LOGGER.debug("Request access_token: type=0 (structured query parameters)")
        return {
            "url": url,
            "data": None,
            "params": {
                "userName": username,
                "type": "0",
                "password": password_md5,
            },
        }

    @classmethod
    def get_access_token_by_session_id(cls, session_id, api_host: str | None = None):
        url = f"https://{api_host or get_api_host()}/getOauthToken"
        return {
            "url": url,
            "data": None,
            "params": {"type": "0", "sessionId": session_id},
        }

    @classmethod
    def get_family_statistics_users(
        cls, user_id, access_token, api_host: str | None = None
    ):
        url = f"https://{api_host or get_api_host()}/v2/family/statistics/users"

        timestamp = generate_timestamp()
        random_str = generate_uuid()
        req_data = {
            "accessToken": access_token,
            "random": random_str,
            "userId": user_id,
            "sign": "1234567890",
            "timestamp": timestamp,
            "requestId": generate_uuid()
        }
        params = {
            "requestId": req_data["requestId"],
            "userId": req_data["userId"],
            "accessToken": req_data["accessToken"],
            "random": req_data["random"],
            "timestamp": req_data["timestamp"]
        }

        sign = cls.create_sign(params)
        req_data["sign"] = sign
        postData_str = json.dumps(req_data, ensure_ascii=False, indent=None)
        return {"url": url, "data": postData_str}

    @classmethod
    def get_homepage_data(
        cls, family_id, user_id, access_token, api_host: str | None = None
    ):
        url = f"https://{api_host or get_api_host()}/v2/family/config/queryHomepageData"

        timestamp = generate_timestamp()
        random_str = generate_uuid()
        req_data = {
            "accessToken": access_token,
            "random": random_str,
            "userId": user_id,
            "familyId": family_id,
            "sign": "1234567890",
            "timestamp": timestamp,
            "requestId": generate_uuid()
        }
        params = {
            "requestId": req_data["requestId"],
            "userId": req_data["userId"],
            "accessToken": req_data["accessToken"],
            "familyId": req_data["familyId"],
            "random": req_data["random"],
            "timestamp": req_data["timestamp"]
        }

        sign = cls.create_sign(params)
        req_data["sign"] = sign
        postData_str = json.dumps(req_data, ensure_ascii=False, indent=None)

        return {"url": url, "data": postData_str}

    @classmethod
    def get_devices_status(
        cls,
        access_token,
        session_id,
        user_id,
        user_name,
        family_id,
        device_flag=0,
        api_host: str | None = None,
    ):
        """Get the device state list through the /v2/cmd/app/readtable API."""
        url = f"https://{api_host or get_api_host()}/v2/cmd/app/readtable"

        random_str = generate_uuid()
        serial = generate_serial()
        timestamp = generate_timestamp()

        # Set lastUpdateTime to an earlier time to ensure all devices are retrieved
        lastUpdateTime = 0

        req_data = {
            "accessToken": access_token,
            "random": random_str,
            "serial": serial,
            "userId": user_id,
            "userName": user_name,
            "lastUpdateTime": lastUpdateTime,
            "ver": SOFTWARE_VER,
            "sign": "1234567890",
            "timestamp": timestamp,
            "sessionId": session_id,
            "deviceFlag": device_flag,
            "familyId": family_id,
            "pageIndex": 0,
            "dataType": "all"
        }
        # Sort parameters before encryption
        params = {
            "accessToken": req_data["accessToken"],
            "dataType": req_data["dataType"],
            "deviceFlag": req_data["deviceFlag"],
            "familyId": req_data["familyId"],
            "lastUpdateTime": req_data["lastUpdateTime"],
            "pageIndex": req_data["pageIndex"],
            "random": req_data["random"],
            "serial": req_data["serial"],
            "sessionId": req_data["sessionId"],
            "timestamp": req_data["timestamp"],
            "userId": req_data["userId"],
            "userName": req_data["userName"],
            "ver": req_data["ver"]
        }

        sign = cls.create_sign(params)
        req_data["sign"] = sign
        postData_str = json.dumps(req_data, ensure_ascii=False, indent=None)

        return {"url": url, "data": postData_str}
