import logging
import asyncio
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable
from homeassistant.core import HomeAssistant
from .packet import HomematePacket, HomemateJsonData
from .protocol import normalize_password_hash
from .ssl_transport import SSLTransport, TlsFiles
from .pending_requests import PendingRequests
from .meari_session import CMD_MEARI_SESSION, build_session_request

from .const import (
    CLIENT_CERT, CLIENT_KEY, SERVER_CA, ID_UNSET, DEFAULT_KEY,
    SSL_MAX_RECONNECT_ATTEMPTS,
    CMD_HELLO, CMD_LOGIN, CMD_STATE_UPDATE, CMD_CONTROL, CMD_HEARTBEAT, CMD_HANDSHAKE,
    CMD_CLOTHES_HORSE_CONTROL, CMD_CLOTHES_HORSE_STATE, CMD_CLOTHES_HORSE_QUERY,
    CMD_COS_AUTH, CMD_TEMP_PASSWORD, CMD_DELETE_AUTHORIZATION,
)

_LOGGER = logging.getLogger(__name__)


class SSLClient:
    _initial_keys = {}

    RECONNECT_TIMEOUT = 30
    PACKET_WRITE_TIMEOUT = 10.0

    def __init__(
        self,
        hass: HomeAssistant,
        ssl_host: str,
        ssl_port: int,
        username: str,
        password_hash: str,
        family_id: str,
        on_session_id_obtained: Callable[[str], None],
        on_status_update: Callable[[str, dict], None],
        heartbeat_interval: int = 120,
        retry_interval: int = 5
    ):
        self.hass = hass
        self.ssl_host = ssl_host
        self.ssl_port = ssl_port
        self.username = username
        self.password_hash = normalize_password_hash(password_hash)
        self.family_id = family_id

        self.on_session_id_obtained = on_session_id_obtained
        self.on_status_update = on_status_update
        self.heartbeat_interval = heartbeat_interval
        self.retry_interval = retry_interval

        self.certfile = Path(CLIENT_CERT)
        self.keyfile = Path(CLIENT_KEY)
        self.cafile = Path(SERVER_CA)

        self.transport = SSLTransport(
            hass,
            ssl_host,
            ssl_port,
            TlsFiles(self.certfile, self.keyfile, self.cafile),
        )
        self.session_id: Optional[str] = None
        self.session_key: Optional[bytes] = None
        self._closed: bool = False
        self._reconnect_lock = asyncio.Lock()
        self._listening_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_failures: int = 0
        self.HEARTBEAT_MAX_FAILURES = 2

        self._pending_requests = PendingRequests()
        self._meari_request_identity: dict | None = None
        # Control response timeout (seconds)
        self._control_response_timeout: float = 3.0
        # Login wait mechanism
        self._login_event: Optional[asyncio.Event] = None
        self._login_result: bool = False
        self._login_status: Optional[int] = None
        self._login_msg: Optional[str] = None

    def _get_key(self) -> bytes:
        """Get this instance's session_key, falling back to the class variable or default key."""
        if self.session_key:
            return self.session_key
        if self.session_id and self.session_id in self._initial_keys:
            return self._initial_keys[self.session_id]
        return DEFAULT_KEY.encode("utf-8")

    @classmethod
    def add_key(cls, session_id: str, key: bytes):
        cls._initial_keys[session_id] = key

    @classmethod
    def get_key(cls, session_id: str) -> bytes:
        try:
            return cls._initial_keys[session_id]
        except KeyError:
            return DEFAULT_KEY.encode("utf-8")

    @property
    def connected(self) -> bool:
        return self.transport.connected

    @connected.setter
    def connected(self, value: bool) -> None:
        self.transport.connected = value

    @property
    def reader(self):
        return self.transport.reader

    @reader.setter
    def reader(self, value) -> None:
        self.transport.reader = value

    @property
    def writer(self):
        return self.transport.writer

    @writer.setter
    def writer(self, value) -> None:
        self.transport.writer = value

    @property
    def ssl_context(self):
        return self.transport.ssl_context

    @ssl_context.setter
    def ssl_context(self, value) -> None:
        self.transport.ssl_context = value

    @property
    def is_connected(self):
        return self.connected

    async def _create_ssl_context(self):
        return await self.transport.create_ssl_context()

    async def _connect(self):
        if self.connected:
            return True
        try:
            _LOGGER.debug("Connecting over SSL...")
            await self.transport.connect()
            _LOGGER.debug("SSL connected")
            return True
        except asyncio.TimeoutError:
            _LOGGER.error("Timed out connecting to SSL server [%s:%s]", self.ssl_host, self.ssl_port)
            return False
        except OSError as e:
            _LOGGER.error("SSL connection I/O error: %s", e)
            return False
        except Exception as e:
            _LOGGER.error("SSL connection failed: %s", e)
            return False

    async def _disconnect(self, *, permanent: bool = True):
        self.connected = False
        self._closed = permanent
        current_task = asyncio.current_task()
        for task in (self._listening_task, self._heartbeat_task):
            if task is None or task.done() or task is current_task:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._listening_task = None
        self._heartbeat_task = None

        if self.writer and not self.writer.is_closing():
            _LOGGER.debug("Closing existing SSL connection...")
            try:
                await self.transport.close()
            except Exception as e:
                _LOGGER.debug("Failed to close SSL connection: %s", e)

        else:
            await self.transport.close()
        self.session_id = None
        self.session_key = None
        self._pending_requests.cancel_all()
        _LOGGER.debug("SSL connection closed")

    async def _reconnect(self):
        async with self._reconnect_lock:
            if self.connected:
                return True
            try:
                await self._disconnect(permanent=False)
            except Exception as e:
                _LOGGER.error("Error while disconnecting: %s", e)

            if self.retry_interval > 0:
                _LOGGER.debug("Retrying connection in %s seconds...", self.retry_interval)
                await asyncio.sleep(self.retry_interval)
                try:
                    success = await asyncio.wait_for(
                        self.connect_and_login(),
                        timeout=self.RECONNECT_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    _LOGGER.error("SSL reconnect timed out after %s seconds; giving up on this attempt", self.RECONNECT_TIMEOUT)
                    raise ConnectionError('Cloud reconnection timed out')
                if not success:
                    _LOGGER.error("SSL reconnect failed; will retry later")
                    raise ConnectionError('Cloud reconnection failed')
                return True
            else:
                raise ConnectionError('Reconnect interval is zero; reconnect disabled')

    async def connect_and_login(
        self,
        max_attempts: int = SSL_MAX_RECONNECT_ATTEMPTS,
        hello_wait: float = 3.0,
    ):
        """Connect and log in. max_attempts/hello_wait are used by the lightweight config-flow probe."""
        if self.connected:
            return True
        self._closed = False
        
        # Cancel previous listen/heartbeat tasks to avoid concurrent listeners
        if self._listening_task and not self._listening_task.done():
            self._listening_task.cancel()
            try:
                await self._listening_task
            except asyncio.CancelledError:
                pass
            self._listening_task = None
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        
        for retry in range(max_attempts):
            try:
                _LOGGER.debug("Connecting and logging in over SSL...")
                self.connected = await self._connect()
                if self.connected:
                    _LOGGER.debug("SSL connected; sending Hello...")
                    await self._send_hello()
                    _LOGGER.debug("Creating background listener task...")
                    self._listening_task = self.hass.async_create_background_task(
                        self._listen_loop(),
                        name="orvibo_smart_control_server_response_listener"
                    )
                    # Wait for the Hello key
                    await asyncio.sleep(hello_wait)
                    _LOGGER.debug("After waiting, session_key ready: %s", self.session_key is not None)
                    login_result = await self._send_login()
                    _LOGGER.debug("SSL login result: %s", login_result)
                    if login_result:
                        _LOGGER.debug("Starting heartbeat keepalive task...")
                        self._heartbeat_task = self.hass.async_create_background_task(
                            self._heartbeat_loop(),
                            name="orvibo_smart_control_heartbeat"
                        )
                        return True
                    else:
                        _LOGGER.error("SSL login failed; disconnecting before retry")
                        await self._disconnect(permanent=False)
                        raise ConnectionError('Cloud login failed')
            except Exception as e:
                _LOGGER.debug("Connect/login retry %s/%s: %s", retry + 1, SSL_MAX_RECONNECT_ATTEMPTS, e)
                await asyncio.sleep(self.retry_interval * (retry + 1))
        return False

    async def _send_packet(self, data: dict, key: bytes):
        control_key = None
        try:
            if not self.writer or self.writer.is_closing():
                raise ConnectionError("SSL stream is not connected")
            device_id = str(data.get("deviceId") or "")
            if data.get("cmd") == CMD_CONTROL and device_id:
                control_key = f"control:{device_id}"
                self._pending_requests.register(control_key, replace=True)
            if key == DEFAULT_KEY.encode("utf-8"):
                packet_type = bytes([0x70, 0x6b])
                self.session_id = bytes(ID_UNSET).decode("utf-8")
            else:
                packet_type = bytes([0x64, 0x6b])

            ciphertext = HomematePacket.build_packet(
                packet_type=packet_type,
                key=key,
                session_id=self.session_id.encode("utf-8"),
                payload=data
            )
            await asyncio.wait_for(
                self.transport.write(ciphertext), timeout=self.PACKET_WRITE_TIMEOUT
            )
            _LOGGER.debug("Sending packet cmd=%s, deviceId=%s", data.get("cmd"), data.get("deviceId"))
        except Exception as e:
            if control_key is not None:
                self._pending_requests.resolve(control_key, None)
            if isinstance(e, (OSError, asyncio.TimeoutError)):
                self.connected = False
                self._pending_requests.cancel_all()
                # Wake the reader so its recovery loop can restore the session.
                if self.writer is not None:
                    try:
                        self.writer.close()
                    except Exception:
                        _LOGGER.debug("Failed to close the invalid SSL stream")
            _LOGGER.error("Failed to send packet: %s", type(e).__name__)
            # A failed write has an unknown outcome; do not replay the command
            # or allow send_control_* to return a false success.
            raise ConnectionError('Cloud command failed; try again later') from e

    async def _send_hello(self):
        payload = HomemateJsonData.ssl_get_session()
        _LOGGER.debug("Sending Hello packet: cmd=%s keys=%s", payload.get("cmd"), sorted(payload))
        await self._send_packet(payload, DEFAULT_KEY.encode("utf-8"))

    async def _send_login(self):
        if not self.connected:
            _LOGGER.debug("No SSL connection; cannot start login")
            return False
        _LOGGER.debug(
            "Preparing login: session_key_ready=%s, family_id=%s",
            self.session_key is not None,
            self.family_id,
        )
        payload = HomemateJsonData.ssl_login(
            username=self.username,
            password_md5=self.password_hash,
            family_id=self.family_id,
        )
        if self.session_key and self.session_key != DEFAULT_KEY.encode("utf-8"):
            # Set the login wait event
            self._login_event = asyncio.Event()
            await self._send_packet(payload, self.session_key)
            try:
                await asyncio.wait_for(self._login_event.wait(), timeout=10)
                login_ok = self._login_result
                if not login_ok:
                    _LOGGER.error("Server returned login failure: status=%s msg=%s", self._login_status, self._login_msg)
                return login_ok
            except asyncio.TimeoutError:
                _LOGGER.error("Timed out waiting for login response")
                return False
            finally:
                self._login_event = None
        else:
            _LOGGER.debug("Session key not received; delaying login packet")
            return False

    async def send_control_switch(self, device_id: str, device_uid: str, state: bool):
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_switch(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            state=state
        )
        _LOGGER.debug("Sending switch control: device=%s state=%s payload=%s", device_id, state, payload)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_cct_light_onoff(self, device_id: str, device_uid: str, state: bool):
        """Color temperature light switch control (set property format for statusType=503)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_cct_light_onoff(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            state=state
        )
        _LOGGER.debug("Sending color temperature light switch: device=%s state=%s", device_id, state)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_cct_light_brightness(self, device_id: str, device_uid: str, brightness_percent: int):
        """Color temperature light brightness control (set property format for statusType=503)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_cct_light_brightness(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            brightness_percent=brightness_percent
        )
        _LOGGER.debug("Sending color temperature light brightness: device=%s brightness=%s%%", device_id, brightness_percent)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_cct_light_colortemp(self, device_id: str, device_uid: str, colortemp_k: int):
        """Color temperature light color temperature control (set property format for statusType=503)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_cct_light_colortemp(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            colortemp_k=colortemp_k
        )
        _LOGGER.debug("Sending color temperature light temperature: device=%s temperature=%sK", device_id, colortemp_k)
        await self._send_packet(payload, self.session_key)
        return True

    async def _send_property_control(self, payload: dict) -> bool:
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_floor_heating_power(self, device_id: str, device_uid: str, state: bool):
        return await self._send_property_control(
            HomemateJsonData.ssl_control_floor_heating_power(
                self.username, device_id, device_uid, state
            )
        )

    async def send_control_floor_heating_temperature(self, device_id: str, device_uid: str, temperature: int):
        return await self._send_property_control(
            HomemateJsonData.ssl_control_floor_heating_temperature(
                self.username, device_id, device_uid, temperature
            )
        )

    async def send_control_dream_curtain_action(self, device_id: str, device_uid: str, action: str):
        return await self._send_property_control(
            HomemateJsonData.ssl_control_dream_curtain_action(
                self.username, device_id, device_uid, action
            )
        )

    async def send_control_dream_curtain_percent(self, device_id: str, device_uid: str, percent: int):
        return await self._send_property_control(
            HomemateJsonData.ssl_control_dream_curtain_percent(
                self.username, device_id, device_uid, percent
            )
        )

    async def send_control_dream_curtain_angle(self, device_id: str, device_uid: str, angle: int):
        return await self._send_property_control(
            HomemateJsonData.ssl_control_dream_curtain_angle(
                self.username, device_id, device_uid, angle
            )
        )

    async def send_control_dimmable_light_brightness(self, device_id: str, device_uid: str, brightness_percent: int):
        """Dimmable light brightness control (set property format, type=502)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_dimmable_light_brightness(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            brightness_percent=brightness_percent
        )
        _LOGGER.debug("Sending dimmable light brightness: device=%s brightness=%s%%", device_id, brightness_percent)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_zigbee_dimmable_light_onoff(self, device_id: str, device_uid: str, state: bool, brightness: int = 255):
        """Zigbee dimmable light switch control (on/off format for deviceType=0, subDeviceType=-2)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_zigbee_dimmable_light_onoff(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            state=state,
            brightness=brightness
        )
        _LOGGER.debug("Sending Zigbee dimmable light switch: device=%s state=%s brightness=%s", device_id, state, brightness)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_zigbee_dimmable_light_brightness(self, device_id: str, device_uid: str, brightness_255: int):
        """Zigbee dimmable light brightness control (set property format for deviceType=0, subDeviceType=-2)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_zigbee_dimmable_light_brightness(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            brightness_255=brightness_255
        )
        _LOGGER.debug("Sending Zigbee dimmable light brightness: device=%s brightness=%s", device_id, brightness_255)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_fast_move_dim_color_light_onoff(self, device_id: str, device_uid: str, state: bool, brightness: int = 0, colortemp_mired: int = 0):
        """Fast Move dimmable color-temperature light switch control (on/off format for statusType=2, subDeviceType=6)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_fast_move_dim_color_light_onoff(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            state=state,
            brightness=brightness,
            colortemp_mired=colortemp_mired
        )
        _LOGGER.debug("Sending Fast Move dimmable light switch: device=%s state=%s", device_id, state)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_fast_move_dim_color_light_brightness(self, device_id: str, device_uid: str, brightness: int, colortemp_mired: int = 0):
        """Fast Move dimmable color-temperature light brightness control (fast move to level format for statusType=2, subDeviceType=6)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_fast_move_dim_color_light_brightness(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            brightness=brightness,
            colortemp_mired=colortemp_mired
        )
        _LOGGER.debug("Sending Fast Move dimmable light brightness: device=%s brightness=%s colortemp=%s", device_id, brightness, colortemp_mired)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_fast_move_dim_color_light_colortemp(self, device_id: str, device_uid: str, brightness: int, colortemp_mired: int):
        """Fast Move dimmable color-temperature light color temperature control (fast color temperature format for statusType=2, subDeviceType=6)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_fast_move_dim_color_light_colortemp(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            brightness=brightness,
            colortemp_mired=colortemp_mired
        )
        _LOGGER.debug("Sending Fast Move dimmable light color temperature: device=%s brightness=%s colortemp=%s", device_id, brightness, colortemp_mired)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_light(self, device_id: str, device_uid: str, state: bool, brightness: int = 0, colortemp_mired: int = 0):
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_light(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            state=state,
            brightness=brightness,
            colortemp_mired=colortemp_mired
        )
        _LOGGER.debug("Sending light control: device=%s state=%s brightness=%s ct_mired=%s", device_id, state, brightness, colortemp_mired)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_light_brightness(self, device_id: str, device_uid: str, brightness: int):
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_light_brightness(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            brightness=brightness
        )
        _LOGGER.debug("Sending brightness: device=%s value=%s", device_id, brightness)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_light_colortemp(self, device_id: str, device_uid: str, colortemp_k: int, brightness: int = 0):
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_light_colortemp(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            colortemp_k=colortemp_k,
            brightness=brightness
        )
        _LOGGER.debug("Sending color temperature: device=%s temperature=%sK brightness=%s", device_id, colortemp_k, brightness)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_light_bri_ct(self, device_id: str, device_uid: str, brightness: Optional[int], color_temp_k: Optional[int], power: Optional[bool] = None):
        """Send brightness and color temperature together in one combined cmd=15 command."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send combined light command")
            return False

        if power is None:
            power = brightness > 0 if brightness is not None else True

        payload = HomemateJsonData.ssl_control_light_full(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            brightness=brightness,
            colortemp_k=color_temp_k,
            power=power
        )
        _LOGGER.debug("Sending combined dimming: device=%s power=%s brightness=%s color_temp=%s", device_id, power, brightness, color_temp_k)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_cover(self, device_id: str, device_uid: str, position: int, stop_value2: int = 0):
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_cover(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            position=position,
            stop_value2=stop_value2,
        )
        await self._send_packet(payload, self.session_key)
        return True

    async def _send_legacy_floor_heating(
        self,
        device_id: str,
        device_uid: str,
        *,
        order: str,
        value1: int,
        value2: int,
    ) -> bool:
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send legacy underfloor heating control")
            return False
        payload = HomemateJsonData.ssl_control_legacy_floor_heating(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            order=order,
            value1=value1,
            value2=value2,
        )
        await self._send_packet(payload, self.session_key)
        return True

    async def send_control_legacy_floor_heating_power(
        self,
        device_id: str,
        device_uid: str,
        is_on: bool,
        *,
        packed_state: int = 0,
    ) -> bool:
        return await self._send_legacy_floor_heating(
            device_id,
            device_uid,
            order="on" if is_on else "off",
            value1=0 if is_on else 1,
            value2=0 if is_on else max(0, int(packed_state)),
        )

    async def send_control_legacy_floor_heating_temperature(
        self, device_id: str, device_uid: str, temperature: int
    ) -> bool:
        target = max(10, min(35, int(round(temperature))))
        return await self._send_legacy_floor_heating(
            device_id,
            device_uid,
            order="temperature setting",
            value1=8,
            value2=target - 10,
        )

    async def send_control_ventilation(self, device_id: str, device_uid: str, value1: int):
        """Send a ventilation system control command (cmd=15 set property).
        value1: 0=slow, 50=stop, 100=fast
        """
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_control_ventilation(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            value1=value1
        )
        _LOGGER.debug("Sending ventilation system control: device=%s value1=%s", device_id, value1)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_clothes_horse_control(self, device_id: str, device_uid: str, ctrl_field: str, ctrl_value: str):
        """Send a clothes dryer control command (cmd=98).

        Args:
            ctrl_field: lightingCtrl/sterilizingCtrl/windDryingCtrl/heatDryingCtrl/mainSwitchCtrl/motorCtrl
            ctrl_value: on/off/up/down/stop
        """
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_clothes_horse_control(
            username=self.username,
            device_id=device_id,
            device_uid=device_uid,
            ctrl_field=ctrl_field,
            ctrl_value=ctrl_value,
        )
        _LOGGER.debug("Sending clothes dryer control: device=%s %s=%s", device_id, ctrl_field, ctrl_value)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_clothes_horse_query(self, device_id: str):
        """Send a clothes dryer state query command (cmd=100)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send command")
            return False
        payload = HomemateJsonData.ssl_clothes_horse_query(device_id=device_id)
        _LOGGER.debug("Querying clothes dryer state: %s", device_id)
        await self._send_packet(payload, self.session_key)
        return True

    async def send_meari_session(
        self, *, country_code: str = "CN", phone_code: str = "86",
        language: str = "zh", timeout: float = 15.0,
    ) -> Optional[dict]:
        """Request cmd=148 on the existing cloud session, without logging credentials."""
        if not self.connected or not self.session_key:
            return None
        if self.session_key == DEFAULT_KEY.encode("utf-8"):
            return None
        payload = build_session_request(
            self.family_id, country_code=country_code,
            phone_code=phone_code, language=language,
        )
        future = self._pending_requests.register("meari_session")
        self._meari_request_identity = payload
        try:
            await self._send_packet(payload, self.session_key)
            return await self._pending_requests.wait("meari_session", future, timeout)
        finally:
            self._pending_requests.discard("meari_session", future)
            self._meari_request_identity = None

    def _handle_meari_session_response(self, data: dict) -> None:
        expected = self._meari_request_identity
        if expected is None:
            return
        for field in ("serial", "uniSerial", "familyId"):
            if field in data and str(data[field]) != str(expected[field]):
                return
        self._pending_requests.resolve("meari_session", data)

    async def send_cos_auth(
        self,
        user_id: str,
        device_id: str,
        device_uid: str,
        timeout: float = 15.0,
    ) -> Optional[dict]:
        """Request lock media COS credentials (cmd=313, Skill.GetCOSAuthorization).

        Return the complete response dict, including the response field containing the QueryTxAuthResponse JSON
        string. Return None on timeout or connection failure. The caller caches the credentials.
        """
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot request COS authorization")
            return None
        payload = HomemateJsonData.ssl_cos_auth(
            user_id=user_id,
            device_id=device_id,
            device_uid=device_uid,
            family_id=self.family_id,
        )
        try:
            future = self._pending_requests.register("cos_auth")
        except RuntimeError:
            _LOGGER.debug("A COS authorization request is already awaiting a response")
            return None
        try:
            _LOGGER.debug("Sending COS authorization request: device=%s", device_id)
            await self._send_packet(payload, self.session_key)
            result = await self._pending_requests.wait("cos_auth", future, timeout)
            if result is None:
                _LOGGER.debug("Timed out waiting for COS authorization response")
            return result
        except Exception:
            self._pending_requests.cancel_all()
            raise

    async def _wait_temp_response(self, future, timeout: float) -> Optional[dict]:
        """Wait for a cmd=246/247 response, populated by the listener loop."""
        result = await self._pending_requests.wait("temp_authorization", future, timeout)
        if result is None:
            _LOGGER.debug("Timed out waiting for temporary password response")
        return result

    async def send_temp_password(
        self,
        device_id: str,
        device_uid: str,
        name: str,
        auth_type: int,
        minutes: int,
        number: int,
        phone: str = "",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        timeout: float = 15.0,
    ) -> Optional[dict]:
        """Send a temporary password (cmd=246) and return the complete response, including code/password."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot send temporary password")
            return None
        now = int(time.time())
        if auth_type == 1 and start_time is not None and end_time is not None:
            start_ts, end_ts = start_time, end_time
        else:
            start_ts = now
            end_ts = now + minutes * 60 if auth_type == 1 else 0
        payload = HomemateJsonData.ssl_temp_password(
            device_id=device_id,
            device_uid=device_uid,
            name=name,
            auth_type=auth_type,
            minutes=minutes,
            number=number,
            phone=phone,
            start_time=start_ts,
            end_time=end_ts,
        )
        _LOGGER.debug("Sending temporary password: device=%s type=%s minutes=%s", device_id, auth_type, minutes)
        try:
            future = self._pending_requests.register("temp_authorization")
        except RuntimeError:
            _LOGGER.debug("A temporary password request is already awaiting a response")
            return None
        await self._send_packet(payload, self.session_key)
        return await self._wait_temp_response(future, timeout)

    async def delete_authorization(
        self,
        device_id: str,
        device_uid: str,
        authorized_id: int,
        timeout: float = 15.0,
    ) -> Optional[dict]:
        """Delete an authorization (cmd=247; authorizedId comes from the send response)."""
        await self.connect_and_login()
        if not self.session_key or self.session_key == DEFAULT_KEY.encode("utf-8"):
            _LOGGER.debug("Invalid session key; cannot delete authorization")
            return None
        payload = HomemateJsonData.ssl_delete_authorization(
            device_id=device_id,
            device_uid=device_uid,
            authorized_id=authorized_id,
        )
        _LOGGER.debug("Deleting authorization: device=%s authorizedId=%s", device_id, authorized_id)
        try:
            future = self._pending_requests.register("temp_authorization")
        except RuntimeError:
            _LOGGER.debug("A temporary password request is already awaiting a response")
            return None
        await self._send_packet(payload, self.session_key)
        return await self._wait_temp_response(future, timeout)

    async def _wait_for_control_response(self, device_id: str, timeout: float | None = None) -> dict | None:
        """Wait for the device's cmd=42 state response after sending a control command.

        Call this after the corresponding send_control_* method. If the device returns cmd=42 before timeout,
        return the complete packet dict (including value1-4/properties); otherwise return None.
        """
        control_key = f"control:{device_id}"
        future = self._pending_requests.get(control_key)
        if future is None:
            _LOGGER.debug("No pending control request for device %s", device_id)
            return None
        effective_timeout = timeout if timeout is not None else self._control_response_timeout

        result = await self._pending_requests.wait(
            control_key,
            future,
            effective_timeout,
        )
        if result:
            _LOGGER.debug(f"[Control response] device={device_id} received a response within {effective_timeout}s: "
                          f"value1={result.get('value1')}, value2={result.get('value2')}, "
                          f"value3={result.get('value3')}, value4={result.get('value4')}")
        else:
            _LOGGER.debug(f"[Control response] device={device_id} received no response within {effective_timeout}s")
        return result

    async def _heartbeat_loop(self):
        """Heartbeat keepalive loop that sends a packet every heartbeat_interval seconds."""
        _LOGGER.debug("Heartbeat keepalive loop started; interval=%d seconds", self.heartbeat_interval)
        while self.connected:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if not self.connected:
                    break
                if self.session_key and self.session_key != DEFAULT_KEY.encode("utf-8"):
                    payload = HomemateJsonData.ssl_heartbeat()
                    await self._send_packet(payload, self.session_key)
                    self._heartbeat_failures = 0  # Reset the counter after a successful send
                    _LOGGER.debug("Heartbeat sent")
            except asyncio.CancelledError:
                _LOGGER.debug("Heartbeat task cancelled; exiting loop")
                return
            except Exception as e:
                _LOGGER.error("Heartbeat send error: %s", e)
                self._heartbeat_failures += 1
                if self._heartbeat_failures >= self.HEARTBEAT_MAX_FAILURES:
                    _LOGGER.error("Heartbeat failed %s times consecutively; reconnecting", self._heartbeat_failures)
                    self._heartbeat_failures = 0
                    self.connected = False
                    return  # Exit heartbeat; _listen_loop handles reconnects
                await asyncio.sleep(1)
        _LOGGER.debug("Heartbeat keepalive loop ended")

    async def _listen_loop(self):
        _LOGGER.debug("SSL background listener loop started")
        while True:
            try:
                header_data = await self.transport.readexactly(42)
                if not header_data:
                    await asyncio.sleep(1)
                    continue
                length = HomematePacket.parse_length(header_data)
                ciphertext = await self.transport.readexactly(length - 42)
                if self.session_key is None:
                    self.session_key = DEFAULT_KEY.encode("utf-8")
                try:
                    packet = HomematePacket(header_data + ciphertext, {self.session_id: self.session_key})
                except (AssertionError, Exception) as e:
                    _LOGGER.error("Failed to parse malformed packet; discarding: %s", e)
                    continue
                self.session_id = bytes(packet.session_id).decode("utf-8")
                data = packet.json_payload
                if data is None:
                    _LOGGER.debug("Packet JSON parsing failed; discarding")
                    continue
                cmd = data.get("cmd")
                _LOGGER.debug("Received server packet cmd=%s", cmd)
                if cmd == CMD_HELLO:
                    await self._handle_hello(data)
                elif cmd == CMD_LOGIN:
                    await self._handle_login(data)
                elif data.get("action") == "deviceStatusReport":
                    await self._handle_device_status_report(data)
                elif data.get("namespace") == "device_manage" and data.get("action") == "upLoadDeviceList":
                    await self._handle_upload_device_list(data)
                elif cmd == CMD_STATE_UPDATE:
                    await self._handle_state_update(data)
                elif cmd == CMD_CLOTHES_HORSE_STATE:
                    await self._handle_clothes_horse_state(data)
                elif cmd == 82:
                    await self._handle_push_message(data)
                elif cmd == 352:
                    # Lock events (unlockEvent/errorUnlockEvent/picklockEvent/
                    # leaveHomeEvent/doorUnclose/doorbell ring) use the same state channel
                    await self._handle_state_update(data)
                elif cmd == CMD_MEARI_SESSION:
                    self._handle_meari_session_response(data)
                elif cmd == CMD_COS_AUTH:
                    # Skill.GetCOSAuthorization response (lock media COS credentials)
                    if not self._pending_requests.resolve("cos_auth", data):
                        _LOGGER.debug("Received unexpected cmd=313 response")
                elif cmd in (CMD_TEMP_PASSWORD, CMD_DELETE_AUTHORIZATION):
                    # Temporary password send/authorization deletion response
                    if not self._pending_requests.resolve("temp_authorization", data):
                        _LOGGER.debug("Received unexpected cmd=%s response", cmd)
                elif cmd in (CMD_HEARTBEAT, CMD_HANDSHAKE):
                    continue
                else:
                    _LOGGER.debug("Unknown cmd packet: %s", data)
            except asyncio.IncompleteReadError:
                _LOGGER.debug("Incomplete SSL stream read; connection closed")
                break
            except asyncio.TimeoutError:
                continue
            except (ConnectionError, OSError) as e:
                _LOGGER.debug("Network connection interrupted: %s: %s", type(e).__name__, e)
                break
            except asyncio.CancelledError:
                _LOGGER.debug("Listener task cancelled; exiting loop")
                return
            except Exception as e:
                import traceback
                _LOGGER.error("Listener loop error: %s\n%s", e, traceback.format_exc())
                if self.reader is None:
                    _LOGGER.debug("reader is gone; exiting listener loop")
                    break
                await asyncio.sleep(1)
        self.connected = False
        self._pending_requests.cancel_all()
        _LOGGER.debug("SSL listener loop ended; starting reconnect loop...")
        reconnect_count = 0
        max_reconnect = 5
        while not self._closed and reconnect_count < max_reconnect:
            try:
                await self._reconnect()
                _LOGGER.debug("SSL reconnected; resuming listener")
                return  # connect_and_login starts a new _listen_loop after _reconnect succeeds
            except ConnectionError:
                reconnect_count += 1
                backoff = min(self.retry_interval * (2 ** (reconnect_count - 1)), 60)
                _LOGGER.debug("SSL reconnect failed (%s/%s); retrying in %s seconds...", reconnect_count, max_reconnect, backoff)
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                _LOGGER.debug("Reconnect task cancelled")
                return
        if reconnect_count >= max_reconnect:
            _LOGGER.warning("SSL reconnect limit reached (%s); stopping retries", max_reconnect)

    async def _handle_hello(self, data: dict):
        key = data.get("key")
        self.session_key = str(key).encode("utf-8") if key else DEFAULT_KEY.encode("utf-8")
        SSLClient.add_key(self.session_id, self.session_key)
        _LOGGER.debug("Hello response succeeded: session_key_len=%s", len(self.session_key))
        self.on_session_id_obtained(self.session_id)

    async def _handle_login(self, data: dict):
        status = data.get("status")
        user_id = data.get("userId")
        result = bool(status == 0 or user_id)
        # Store the result for _send_login
        self._login_result = result
        self._login_status = status
        self._login_msg = data.get("msg")
        if self._login_event:
            self._login_event.set()
        if result:
            _LOGGER.debug("SSL login succeeded: userId=%s", user_id)
        else:
            _LOGGER.error("Login failed: status=%s msg=%s", status, data.get("msg"))
        return result

    async def _handle_upload_device_list(self, data: dict):
        device_list = data.get("data", {}).get("deviceList", [])
        _LOGGER.debug("Full device list push: %s devices", len(device_list))
        for dev_data in device_list:
            dev_id = dev_data.get("deviceId")
            if not dev_id:
                continue
            status_info = {}
            props = dev_data.get("properties", {})
            status_info["properties"] = props
            # Parse switch state
            onoff = props.get("onoff", {})
            status_info["state"] = onoff.get("status") == "on"
            # Support brightness / value2 for brightness
            status_info["brightness"] = props.get("brightness", props.get("value2"))
            # Support colortemp / value3 for color temperature
            status_info["color_temp"] = props.get("colortemp", props.get("value3"))
            # Curtain
            status_info["position"] = props.get("percent")
            # Online state
            online = dev_data.get("online", "")
            status_info["online"] = online.strip().lower() in ("online", "1", "true")
            self.on_status_update(dev_id, status_info)

    async def _handle_device_status_report(self, data: dict):
        """Handle deviceStatusReport messages and extract raw data only."""
        dev_data = data.get("data", {})
        dev_id = dev_data.get("deviceId")
        if not dev_id:
            return
        
        _LOGGER.debug("[SSL receive] deviceStatusReport data: %s", data)
        
        # Extract raw data only; do not parse it
        raw_status = {
            "raw_data": data,  # Keep the complete raw data
            "properties": dev_data.get("properties", {}),
            "deviceId": dev_id,
            "uid": dev_data.get("uid", ""),
            "cmd": data.get("cmd"),
            "action": data.get("action"),
            "event": data.get("event"),
            "online": True,
        }
        
        _LOGGER.debug("[SSL output] deviceStatusReport raw data: deviceId=%s", dev_id)
        self.on_status_update(dev_id, raw_status)

    async def _handle_state_update(self, data: dict):
        """Handle cmd=42 cloud live-state pushes; extract raw data only without parsing state."""
        # Log all cmd=42 messages for diagnostics
        _LOGGER.debug("[SSL receive] complete cmd=42 data: %s", data)

        dev_id = data.get("deviceId", "")
        if self._pending_requests.resolve(f"control:{dev_id}", data):
            _LOGGER.debug("[Control response match] device=%s response received; waking waiter", dev_id)

        # Filter only control echoes (respByAcc=false and not an active event); active pushes
        # (doorbell/unlock events, lock state, etc.) must still be processed so they reach entities.
        if data.get("respByAcc") is False and not isinstance(data.get("event"), dict):
            _LOGGER.debug("[SSL filter] respByAcc=false; skipping deviceId=%s", data.get("deviceId"))
            return
        
        uid = data.get("uid", "")
        
        # Extract raw data only; the coordinator parses it based on device type
        raw_status = {
            "raw_data": data,  # Keep the complete raw data
            "properties": data.get("properties", {}),  # properties field
            "value1": data.get("value1"),  # Switch state / curtain position
            "value2": data.get("value2"),  # Brightness
            "value3": data.get("value3"),  # Color temperature
            "value4": data.get("value4"),  # Other parameters
            "statusType": data.get("statusType"),  # State type
            "subDeviceType": data.get("subDeviceType"),  # Sub-device type
            "cmd": data.get("cmd"),
            "action": data.get("action"),
            "event": data.get("event"),
            "time": data.get("time"),
            "deviceId": dev_id,
            "uid": uid,
            "online": True,  # Devices with a live cloud push are considered online
        }
        
        _LOGGER.debug("[SSL output] Raw state: deviceId=%s, value1=%s, value2=%s, value3=%s", dev_id, raw_status["value1"], raw_status["value2"], raw_status["value3"])
        
        self.on_status_update(dev_id, raw_status)

    async def _handle_clothes_horse_state(self, data: dict):
        """Handle cmd=99 clothes dryer state pushes."""
        _LOGGER.debug("[SSL receive] cmd=99 clothes dryer state: %s", data)

        dev_id = data.get("deviceId", "")
        if not dev_id:
            return

        raw_status = {
            "raw_data": data,
            "is_clothes_horse": True,
            "motor_state": data.get("motorState", "stop"),
            "motor_position": data.get("motorPosition", 0),
            "lighting_state": data.get("lightingState", "off"),
            "heat_drying_state": data.get("heatDryingState", "off"),
            "wind_drying_state": data.get("windDryingState", "off"),
            "sterilizing_state": data.get("sterilizingState", "off"),
            "main_switch_state": data.get("mainSwitchState", "off"),
            "deviceId": dev_id,
            "uid": data.get("uid", ""),
            "online": True,
        }

        _LOGGER.debug(
            f"[SSL output] Clothes dryer state: deviceId={dev_id}, "
            f"lighting={raw_status['lighting_state']}, motor={raw_status['motor_state']}, "
            f"pos={raw_status['motor_position']}"
        )

        self.on_status_update(dev_id, raw_status)

    async def _handle_push_message(self, data: dict):
        """Handle cmd=82 push messages, including lock text messages and alerts."""
        raw_status = {
            "raw_data": data,
            "cmd": 82,
            "data": data.get("data"),
            "text": data.get("text"),
            "infoType": data.get("infoType"),
            "messageType": data.get("messageType"),
            "deviceId": data.get("deviceId", ""),
            "uid": data.get("uid", ""),
            "online": True,
        }
        self.on_status_update(raw_status.get("deviceId") or "", raw_status)
