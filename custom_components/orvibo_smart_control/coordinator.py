import logging
import asyncio
import secrets
from datetime import timedelta
from typing import Dict, Any, Optional
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .ssl_client import SSLClient
from .lan import GatewayManager, LanControlAdapter
from .capabilities import TransportMode, lan_state_allowed
from .https_client import HttpsClient
from .device_types import (
    DeviceCategory,
    classify_device,
)
from .redact import fingerprint
from .models import AccountCredentials
from .cloud import CHINA_CLOUD, CloudEndpoint, cloud_candidates
from .state_store import StateSource, StateStore
from .parsers import get_state_parser
from .lock_manager import LockEventManager
from .status_dispatcher import StatusUpdateDispatcher
from .lock_media_manager import LockMediaManager
from .temp_password_manager import TempPasswordManager
from .device_inventory import DeviceInventory
from .control_executor import ControlExecutor
from .const import (
    DOMAIN,
    SSL_PORT,
    UPDATE_INTERVAL,
    DEFAULT_KEY,
    DEFAULT_LOCK_SNAPSHOT_LIMIT,
)

_LOGGER = logging.getLogger(__name__)


class OrviboSmartControlCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    MOTION_RESET_DELAY = 30  # Reset delay after motion sensor activation (seconds)
    EMERGENCY_RESET_DELAY = 180  # Reset delay after emergency button activation (seconds), 3 minutes
    LOCK_RESET_DELAY = 5  # Reset delay after lock doorbell/unlock events (seconds)
    LOCK_DOOR_OPEN_WINDOW = 30  # Attribution window from unlock to door opening (seconds)
    
    def __init__(
        self,
        hass: HomeAssistant,
        credentials: AccountCredentials,
        lock_user_names: Optional[Dict[str, str]] = None,
        cloud: CloudEndpoint = CHINA_CLOUD,
        transport_mode: TransportMode = TransportMode.AUTO,
        lan_credentials: AccountCredentials | None = None,
        poll_interval: timedelta | None = UPDATE_INTERVAL,
        lock_snapshot_limit: int = DEFAULT_LOCK_SNAPSHOT_LIMIT,
    ):
        self.credentials = credentials
        self.username = credentials.username
        self.password_hash = credentials.password_hash
        self.family_id = credentials.family_id
        self.hass = hass
        self._transport_mode = transport_mode
        self.lan_credentials = lan_credentials or credentials

        self.https_client = HttpsClient(
            username=credentials.username,
            password_hash=credentials.password_hash,
            session=async_get_clientsession(hass),
            cloud=cloud,
        )
        self.https_client.family_id = credentials.family_id or None
        self.ssl_client = None
        self.gateway_manager: Optional[GatewayManager] = None
        self.lan_adapter: Optional[LanControlAdapter] = None
        self._lan_discover_task: Optional[asyncio.Task] = None
        self._lan_closed = False
        
        self._motion_reset_tasks: Dict[str, asyncio.Task] = {}  # Motion sensor reset tasks
        self._emergency_reset_tasks: Dict[str, asyncio.Task] = {}  # Emergency button reset tasks
        self._lock_reset_tasks: Dict[tuple, asyncio.Task] = {}  # Lock event reset tasks
        self._lock_user_names: Dict[str, Dict[str, str]] = {}  # device_id -> {user_id: name}
        self._lock_user_names_shared: Dict[str, str] = dict(lock_user_names or {})  # Persistent mapping (config-entry level)
        self.lock_events = LockEventManager(
            self.lock_user_name,
            credential_name=self.lock_user_name,
            door_open_window=self.LOCK_DOOR_OPEN_WINDOW,
        )
        
        # Debug: retain recent raw state pushes in memory only; logs and diagnostics are redacted
        self._cmd42_log: list[dict] = []
        self._redaction_salt = secrets.token_bytes(32)
        self._last_update_time: Dict[str, float] = {}  # Timestamp of the last device update

        super().__init__(
            hass,
            _LOGGER,
            name="Orvibo Mesh Coordinator",
            update_interval=(
                None
                if transport_mode == TransportMode.LAN_ONLY
                else poll_interval
            ),
        )

        self.devices: Dict[str, Any] = {}
        self.device_states: Dict[str, Any] = {}
        self.state_store = StateStore(self.device_states)
        self.inventory = DeviceInventory(
            self.https_client,
            self.devices,
            self.device_states,
            self.state_store,
            self.lock_events.remove,
        )
        self.control = ControlExecutor(
            self.devices,
            self.device_states,
            self.state_store,
            lambda: self.ssl_client,
            lambda: self,
            self.get_device_state,
            lambda: self.async_set_updated_data(self.device_states),
            lambda: self.lan_adapter,
            self._lan_gateway_connected,
            transport_mode,
        )
        self.lock_media = LockMediaManager(
            self.hass, self.devices, self._redaction_salt,
            snapshot_limit=lock_snapshot_limit,
        )
        self.temp_passwords = TempPasswordManager(
            self.hass,
            self.devices,
            self.device_states,
            self.https_client,
            lambda: self.ssl_client,
            lambda: self.async_set_updated_data(self.device_states),
            self._redaction_salt,
        )
        self.status_dispatcher = StatusUpdateDispatcher(
            self.devices,
            self.device_states,
            self.state_store,
            self._last_update_time,
            self._cmd42_log,
            on_motion=self._apply_motion_state_parser,
            on_emergency=self._apply_emergency_state_parser,
            on_lock_transient=lambda state, raw, device_id: self._apply_lock_transient_event(
                device_id, state, raw
            ),
            on_lock_message=self._publish_lock_message,
            on_lock_event=self._publish_lock_event,
            on_updated=lambda: self.hass.add_job(
                self.async_set_updated_data, self.device_states
            ),
            device_label=lambda device_id: fingerprint(
                device_id, self._redaction_salt
            ),
        )

    @property
    def transport_mode(self) -> TransportMode:
        """Return the configured transport mode for diagnostic entities."""

        return self._transport_mode

    def lan_gateway_connected(self, device_id: str) -> bool:
        """Return whether the device's owning gateway has an active LAN session."""

        device = self.devices.get(device_id) or {}
        return self._lan_gateway_connected(str(device.get("uid") or ""))

    def _apply_registered_state_parser(
        self, category: DeviceCategory, dev_state: dict, raw_status: dict
    ) -> bool:
        """Apply a pure state parser registered for the device category."""

        parser = get_state_parser(category)
        if parser is None:
            return False
        parser(dev_state, raw_status).apply_to(dev_state)
        return True

    def _apply_motion_state_parser(
        self, dev_state: dict, raw_status: dict, device_id: Optional[str]
    ) -> None:
        """Parse motion state, then own its coordinator-level reset lifecycle."""

        self._apply_registered_state_parser(
            DeviceCategory.MOTION_SENSOR, dev_state, raw_status
        )
        value3 = raw_status.get("value3")
        reset_key = device_id or raw_status.get("deviceId", "")
        if value3 is None or not reset_key:
            return
        try:
            detected = int(value3) == 1
        except (TypeError, ValueError):
            return
        if detected:
            asyncio.create_task(self._schedule_motion_reset(reset_key))
        else:
            self._cancel_motion_reset(reset_key)

    def _apply_emergency_state_parser(
        self, dev_state: dict, raw_status: dict, device_id: Optional[str]
    ) -> None:
        """Parse an emergency button, then own its reset-task lifecycle."""

        self._apply_registered_state_parser(
            DeviceCategory.EMERGENCY_BUTTON, dev_state, raw_status
        )
        value1 = raw_status.get("value1")
        if value1 is None or not device_id:
            return
        try:
            triggered = int(value1) == 1
        except (TypeError, ValueError):
            return
        if triggered:
            asyncio.create_task(self._schedule_emergency_reset(device_id))
        else:
            self._cancel_emergency_reset(device_id)

    async def _schedule_motion_reset(self, device_id: str) -> None:
        """Schedule a motion sensor state reset."""
        self._cancel_motion_reset(device_id)
        
        async def reset_motion():
            await asyncio.sleep(self.MOTION_RESET_DELAY)
            state = self.device_states.get(device_id)
            if state and state.get("motion_detected"):
                state["motion_detected"] = False
                _LOGGER.debug(f"[Motion sensor] {device_id[:12]}... resetting to inactive after {self.MOTION_RESET_DELAY} seconds")
                self.async_update_listeners()
        
        self._motion_reset_tasks[device_id] = asyncio.create_task(reset_motion())

    def _cancel_motion_reset(self, device_id: str) -> None:
        """Cancel the motion sensor state reset task."""
        task = self._motion_reset_tasks.pop(device_id, None)
        if task and not task.done():
            task.cancel()

    async def _schedule_emergency_reset(self, device_id: str) -> None:
        """Schedule an emergency button state reset (automatically resets after 3 minutes)."""
        self._cancel_emergency_reset(device_id)

        async def reset_emergency():
            await asyncio.sleep(self.EMERGENCY_RESET_DELAY)
            state = self.device_states.get(device_id)
            if state and state.get("emergency_state"):
                state["emergency_state"] = False
                _LOGGER.debug(f"[Emergency button] {device_id[:12]}... resetting to normal after {self.EMERGENCY_RESET_DELAY} seconds")
                self.async_update_listeners()

        self._emergency_reset_tasks[device_id] = asyncio.create_task(reset_emergency())

    def _cancel_emergency_reset(self, device_id: str) -> None:
        """Cancel the emergency button state reset task."""
        task = self._emergency_reset_tasks.pop(device_id, None)
        if task and not task.done():
            task.cancel()

    def _apply_lock_transient_event(
        self, device_id: str, dev_state: dict, raw_status: dict
    ) -> None:
        """Apply transient cmd=352 flags and schedule their reset."""

        update = self.lock_events.transient_update(raw_status)
        update.patch.apply_to(dev_state)
        if update.reset_kind:
            self._schedule_lock_reset(device_id, update.reset_kind)

    def _schedule_lock_reset(self, device_id: str, kind: str) -> None:
        """Schedule a lock event state reset (inactive after 5 seconds by default), keeping one task per device and event type."""
        key = (device_id, kind)
        task = self._lock_reset_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

        async def reset_lock():
            try:
                await asyncio.sleep(self.LOCK_RESET_DELAY)
            except asyncio.CancelledError:
                return
            state = self.device_states.get(device_id)
            if not state:
                return
            if kind == "doorbell" and state.get("doorbell_ring"):
                state["doorbell_ring"] = False
            elif kind == "unlock" and state.get("unlock_event"):
                state["unlock_event"] = False
            self.async_set_updated_data(self.device_states)

        self._lock_reset_tasks[key] = asyncio.create_task(reset_lock())

    def _publish_lock_event(self, device_id: str, raw_status: dict) -> None:
        """Publish normalized lock states/events to the HA event bus (redacted in logs)."""
        from .const import LOCK_EVENT

        data = self.lock_events.build_event(device_id, raw_status)
        if data is None:
            return
        if not data.get("historical") and (data.get("kind") == "unlock" or data.get("door_opened")):
            state = self.device_states.get(device_id)
            if state is not None:
                values = {
                    "open_direction": data.get("open_direction", "inside"),
                    "unlock_method": data.get("unlock_method"),
                    "unlock_type": data.get("unlock_type"),
                    "unlock_user_id": data.get("unlock_user_id"),
                    "unlock_time": data.get("time"),
                }
                self.state_store.merge(device_id, values, StateSource.SSL)
        data["source"] = raw_status.get("source", "ssl")
        if data.get("kind"):
            data.update(self.lock_media.attach_urls(device_id, raw_status, data))
        self.hass.bus.async_fire(LOCK_EVENT, data)
        _LOGGER.debug(
            "[Lock event bus] device=%s locked=%s door=%s kind=%s",
            fingerprint(device_id, self._redaction_salt),
            data.get("locked"),
            data.get("door_open"),
            data.get("kind"),
        )

    def register_lock_camera(self, device_id: str, camera: Any) -> None:
        """Compatibility facade for the camera platform."""

        self.lock_media.register_camera(device_id, camera)

    async def async_fetch_video(
        self,
        device_id: str,
        object_key: str,
        device_uid: str = "",
    ) -> Dict[str, Any]:
        """Compatibility facade for the fetch-video service."""

        return await self.lock_media.fetch_video(
            device_id, object_key, device_uid
        )

    async def async_list_events(
        self,
        device_id: str = "",
        limit: int = 100,
        media_type: str | None = None,
    ) -> list[dict[str, str]]:
        return await self.lock_media.list_events(device_id, limit, media_type)

    def start_history_cleanup(self) -> None:
        self.lock_media.start_cleanup()

    def stop_history_cleanup(self) -> None:
        self.lock_media.stop_cleanup()

    async def async_cleanup_history(
        self,
        keep_days: int = 7,
        device_id: str = "",
        max_entries: Optional[int] = None,
    ) -> int:
        return await self.lock_media.cleanup_history(
            keep_days, device_id, max_entries
        )

    async def async_grant_temp_password(
        self,
        device_id: str,
        auth_type: int = 2,
        minutes: int = 1440,
        number: int = 1,
        name: str = "",
        phone: str = "",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        device_uid: str = "",
    ) -> Dict[str, Any]:
        """Send a temporary password and return the normalized result."""
        return await self.temp_passwords.grant(
            device_id,
            auth_type,
            minutes,
            number,
            name,
            phone,
            start_time,
            end_time,
            device_uid,
        )

    async def async_revoke_temp_password(
        self,
        device_id: str,
        authorized_id: int,
        device_uid: str = "",
    ) -> Dict[str, Any]:
        """Delete a temporary password (cmd=247)."""
        return await self.temp_passwords.revoke(
            device_id, authorized_id, device_uid
        )

    async def async_list_temp_passwords(self, device_id: str = "") -> Dict[str, Any]:
        """List all server-side temporary passwords from readtable authorizedUnlock, including expired entries."""
        return await self.temp_passwords.list(device_id)

    async def async_fetch_server_temp_passwords(self) -> list[dict]:
        """Fetch the authorizedUnlock table from readtable (full REST sync)."""
        return await self.temp_passwords.fetch_server_records()

    def temp_password_state(self, device_id: str) -> Optional[dict]:
        """Return display information for the latest valid temporary password for sensors."""
        return self.temp_passwords.state(device_id)

    def start_temp_password_cleanup(self) -> None:
        """Start automatic temporary password cleanup, removing expired or exhausted passwords every 6 hours."""
        self.temp_passwords.start_cleanup()

    def stop_temp_password_cleanup(self) -> None:
        """Cancel the scheduled temporary password cleanup task when the integration unloads."""
        self.temp_passwords.stop_cleanup()

    def lock_user_name(self, device_id: str, user_id: object, method: Optional[str] = None) -> Optional[str]:
        """Return the configured display name for a lock userId, or None if unset."""
        if not isinstance(user_id, (str, int)):
            return None
        key = str(user_id)
        if method:
            for scoped_key in (f"{device_id}/{method}/{key}", f"{method}/{key}"):
                if scoped_key in self._lock_user_names_shared:
                    return self._lock_user_names_shared[scoped_key] or None
        name = self._lock_user_names.get(device_id, {}).get(key)
        if name is None:
            name = self._lock_user_names_shared.get(f"{device_id}/{key}")
        if name is None:
            name = self._lock_user_names_shared.get(key)
        return name if isinstance(name, str) and name else None

    def set_lock_user_name(self, device_id: str, user_id: str, name: str) -> bool:
        """Set or clear a display name for a lock userId."""
        device_id = str(device_id or "")
        user_id = str(user_id) if user_id is not None else ""
        if not device_id or not user_id:
            return False
        names = self._lock_user_names.setdefault(device_id, {})
        names[user_id] = str(name or "")
        self._lock_user_names_shared[f"{device_id}/{user_id}"] = str(name or "")
        return True

    def _publish_lock_message(self, device_id: str, raw_status: dict) -> None:
        """Publish a cmd=82 push-message event (lock text messages/alerts; logs are redacted)."""
        from .const import LOCK_EVENT

        event = self.lock_events.build_message(device_id, raw_status)
        if event is None:
            return
        event["source"] = raw_status.get("source", "ssl")
        event.update(self.lock_media.attach_urls(device_id, raw_status, event))
        self.hass.bus.async_fire(LOCK_EVENT, event)
        _LOGGER.debug(
            "[Lock message] device=%s kind=%s is_alarm=%s text=%s",
            fingerprint(device_id, self._redaction_salt),
            event.get("kind"),
            event.get("is_alarm"),
            event.get("text"),
        )

    async def _discover_devices(self):
        """Fetch and parse devices, falling back through readtable -> getDeviceDesc -> queryHomepageData."""
        return await self.inventory.discover()

    async def _async_setup(self):
        try:
            if self.family_id:
                self.https_client.family_id = self.family_id
                self.https_client.family_name = None

            if not await self.https_client.async_detect_cloud(self.family_id):
                raise ConfigEntryAuthFailed('HTTPS login failed')

            _LOGGER.debug("Step 1: fetching device list (three fallback paths)...")
            device_status_data, devices = await self._discover_devices()

            if not devices:
                fallback_cloud = cloud_candidates(self.https_client.cloud)[1]
                _LOGGER.warning(
                    "No devices found in %s cloud; trying %s cloud ...",
                    self.https_client.cloud.region.value,
                    fallback_cloud.region.value,
                )
                await self.https_client.switch_cloud(
                    fallback_cloud,
                    family_id=self.family_id or None,
                )
                if await self.https_client.ensure_login():
                    device_status_data, devices = await self._discover_devices()
                    if devices:
                        _LOGGER.warning(
                            "Found %s devices in %s cloud; this instance will use that region",
                            fallback_cloud.region.value,
                            len(devices),
                        )
                else:
                    _LOGGER.error("Failed to log in to %s cloud", fallback_cloud.region.value)

            if device_status_data is None and not devices:
                raise UpdateFailed('Device discovery failed')

            self.inventory.initialize(devices)

            _LOGGER.info("Device list retrieval complete: %s devices", len(self.devices))

            if self._transport_mode != TransportMode.LAN_ONLY:
                await self._init_ssl_client()

            if self.ssl_client is not None:
                ssl_ok = await self.ssl_client.connect_and_login()
                login_status = getattr(self.ssl_client, "_login_status", None)
                if not ssl_ok and login_status is not None and login_status != 0:
                    # The server explicitly rejected login (e.g. incorrect password, status=12); trigger HA reauthentication
                    raise ConfigEntryAuthFailed(
                        f'Cloud login rejected by server (status={login_status})'
                    )
                if ssl_ok:
                    await self._query_clothes_horse_initial_status()
                    # Prefetch lock COS media credentials so event URLs can be signed immediately
                    self.hass.async_create_task(self._prewarm_cos_credentials())
                else:
                    _LOGGER.warning(
                        "SSL connection/login is not ready (not an authentication rejection); will retry in the background"
                    )

            if self._transport_mode != TransportMode.CLOUD_ONLY:
                try:
                    await self._init_lan_gateways()
                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning("LAN gateway initialization failed: %s", e)

            _LOGGER.info("Initialization complete: %s devices", len(self.devices))
            for device_id, dev in self.devices.items():
                state = self.device_states.get(device_id, {})
                category = classify_device(dev)
                
                if category == DeviceCategory.TEMP_HUMIDITY_SENSOR:
                    self._apply_registered_state_parser(category, state, {"properties": state.get("properties", {}), "value3": state.get("value3"), "value4": state.get("value4")})
                elif category == DeviceCategory.DOOR_WINDOW_SENSOR:
                    self._apply_registered_state_parser(category, state, {"value3": state.get("value3"), "value4": state.get("value4")})
                elif category == DeviceCategory.MOTION_SENSOR:
                    self._apply_motion_state_parser(state, {"value3": state.get("value3"), "value4": state.get("value4")}, device_id)
                elif category == DeviceCategory.SMOKE_SENSOR:
                    self._apply_registered_state_parser(category, state, {"value3": state.get("value3"), "value4": state.get("value4")})
                elif category == DeviceCategory.EMERGENCY_BUTTON:
                    self._apply_emergency_state_parser(state, {"value1": state.get("value1"), "value4": state.get("value4")}, device_id)
                elif category == DeviceCategory.WATER_LEAK_SENSOR:
                    self._apply_registered_state_parser(category, state, {"value1": state.get("value1"), "value4": state.get("value4")})
                elif category == DeviceCategory.GAS_SENSOR:
                    self._apply_registered_state_parser(category, state, {"value1": state.get("value1"), "value4": state.get("value4")})
                elif category == DeviceCategory.DOOR_LOCK:
                    self._apply_registered_state_parser(
                        category, state, {"properties": state.get("properties", {})}
                    )
                elif category == DeviceCategory.VENTILATION_SYSTEM:
                    self._apply_registered_state_parser(category, state, {"properties": state.get("properties", {}), "value1": state.get("value1")})
                
                _LOGGER.debug(
                    f"  Device: name={dev.get('device_name')}, device_id={device_id}, "
                    f"deviceType={dev.get('device_type_raw')}, uid={dev.get('uid')}, "
                    f"online={state.get('online')}, state={state.get('state')}"
                )

            self.async_set_updated_data(self.device_states)
        except ConfigEntryAuthFailed:
            raise
        except Exception as e:
            raise UpdateFailed(f'Initialization failed: {str(e)}') from e

    async def _async_update_data(self) -> Dict[str, Any]:
        _LOGGER.debug("Updating device data...")
        if self._transport_mode == TransportMode.LAN_ONLY:
            return self.device_states
        try:
            device_status_data = await self.https_client.fetch_device_status()
            if device_status_data:
                devices = self.https_client.parse_device_status_list(device_status_data)
                self.inventory.merge_cloud(devices)
            if self.gateway_manager is not None:
                await self.gateway_manager.async_update_cloud_gateways(
                    self.https_client.gateway_ips
                )
            return self.device_states
        except Exception as e:
            raise UpdateFailed(f'Update failed: {str(e)}') from e

    async def _init_ssl_client(self):
        if self.ssl_client is not None:
            return

        while not self.https_client.family_id:
            _LOGGER.debug("Waiting for family_id...")
            await asyncio.sleep(1)

        def on_session_id_obtained(session_id: str):
            _LOGGER.debug("Set session_id: %s", session_id)
            self.https_client.set_session_id(session_id)

        # The SSL control channel follows the current client cloud region, not module-level global state.
        ssl_host = self.https_client.cloud.ssl_host
        self.ssl_client = SSLClient(
            hass=self.hass,
            ssl_host=ssl_host,
            ssl_port=SSL_PORT,
            username=self.username,
            password_hash=self.password_hash,
            family_id=self.https_client.family_id,
            on_status_update=self.status_dispatcher.dispatch,
            on_session_id_obtained=on_session_id_obtained,
        )
        self.lock_media.configure(
            self.ssl_client,
            self.https_client.user_id or "",
            self.https_client.family_id or "",
        )

    async def _init_lan_gateways(self) -> None:
        """Discover and connect to LAN MixPad gateways to receive live state updates."""
        if self.gateway_manager is not None:
            return
        lan_credentials = self.lan_credentials
        self.gateway_manager = GatewayManager(
            lan_credentials.username,
            lan_credentials.password_hash,
            self.https_client.gateway_ips,
            push_callback=self._on_lan_status_update,
            password_is_hash=True,
        )
        self.lan_adapter = LanControlAdapter(
            lan_credentials.username,
            self.gateway_manager,
        )
        await self._connect_all_lan_gateways()
        self._lan_discover_task = self.hass.async_create_background_task(
            self._lan_discover_loop(),
            name=f"{DOMAIN}_lan_gateway_discovery",
        )

    async def _connect_all_lan_gateways(self) -> None:
        if self.gateway_manager is None:
            return
        hosts = dict(self.gateway_manager.gateway_hosts)
        if not hosts:
            return
        results = await asyncio.gather(
            *(self.gateway_manager.ensure(uid) for uid in hosts),
            return_exceptions=True,
        )
        for uid, result in zip(hosts, results):
            if isinstance(result, BaseException):
                reason = (
                    result.reason
                    if isinstance(result, Exception) and hasattr(result, "reason")
                    else type(result).__name__
                )
                _LOGGER.debug("LAN gateway %s is not ready: %s", uid, reason)

    def _lan_gateway_connected(self, device_uid: str) -> bool:
        if self.gateway_manager is None:
            return False
        return self.gateway_manager.is_connected(device_uid)

    async def _lan_discover_loop(self) -> None:
        """Refresh gateway endpoints periodically and keep connections alive (matching lan-control's five-minute interval)."""
        while not self._lan_closed:
            await asyncio.sleep(300)
            if self._lan_closed or self.gateway_manager is None:
                return
            try:
                await self.gateway_manager.discover()
                await self._connect_all_lan_gateways()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("LAN gateway discovery failed: %s", e)

    @staticmethod
    def _lan_payload_device_id(payload: dict) -> Optional[str]:
        """Support deviceId, deviceID, and device_id push fields."""
        for field in ("deviceId", "deviceID", "device_id"):
            value = payload.get(field)
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                continue
            device_id = str(value).strip()
            if device_id:
                return device_id
        return None

    @staticmethod
    def _lan_payload_gateway_uid(payload: dict) -> Optional[str]:
        for field in ("gatewayUid", "gatewayUID", "uid"):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _lan_valid_state_payload(payload: dict) -> bool:
        """Reject malformed state values to avoid corrupting entity state."""
        properties = payload.get("properties")
        if properties is not None and not isinstance(properties, dict):
            return False
        derived = {
            "battery",
            "door_state",
            "motion_detected",
            "smoke_detected",
            "gas_detected",
            "water_leak_detected",
            "emergency_state",
            "temperature",
            "humidity",
        }
        if derived.intersection(payload):
            return False
        for field in ("value1", "value2", "value3", "value4"):
            if field not in payload:
                continue
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                return False
            try:
                int(str(value).strip())
            except (TypeError, ValueError):
                return False
        return True

    def _on_lan_status_update(self, gateway_uid: str, payload: dict) -> None:
        """Validate gateway pushes and process them through the same parsing path as cloud updates (StateSource.LAN takes priority)."""
        device_id = self._lan_payload_device_id(payload)
        if device_id is None or not self._lan_valid_state_payload(payload):
            return
        device = self.devices.get(device_id)
        if not lan_state_allowed(device or {}, self._transport_mode):
            return
        expected_gateway = device.get("uid") if device is not None else None
        if isinstance(expected_gateway, str) and expected_gateway != gateway_uid:
            return
        payload_gateway = self._lan_payload_gateway_uid(payload)
        if payload_gateway is not None and payload_gateway != gateway_uid:
            return
        raw_status = {
            "raw_data": payload,
            "properties": payload.get("properties", {}),
            "value1": payload.get("value1"),
            "value2": payload.get("value2"),
            "value3": payload.get("value3"),
            "value4": payload.get("value4"),
            "statusType": payload.get("statusType"),
            "subDeviceType": payload.get("subDeviceType"),
            "cmd": payload.get("cmd"),
            "action": payload.get("action"),
            "event": payload.get("event"),
            "deviceId": device_id,
            "uid": payload.get("uid", ""),
            "online": True,
        }
        self.status_dispatcher.dispatch(
            device_id,
            raw_status,
            source=StateSource.LAN,
        )

    async def _prewarm_cos_credentials(self) -> None:
        await self.lock_media.prewarm()

    async def _query_clothes_horse_initial_status(self) -> None:
        """After SSL login succeeds, send cmd=100 to all clothes dryers to query their initial state."""
        if not self.ssl_client:
            return
        for device_id, device in self.devices.items():
            category = classify_device(device)
            if category != DeviceCategory.CLOTHES_HORSE:
                continue
            try:
                await self.ssl_client.send_clothes_horse_query(device_id=device_id)
                _LOGGER.debug(f"[Initial clothes dryer query] Sent cmd=100: device={device_id}")
            except Exception as e:
                _LOGGER.warning(f"[Initial clothes dryer query] {device_id} failed: {e}")

    async def _wait_for_control_response(self, device_id: str) -> dict | None:
        """Wait for the device state after sending a control command, with a 3-second timeout fallback."""
        return await self.control.wait_for_response(device_id)

    def _apply_optimistic_state(
        self,
        device_id: str,
        values: Dict[str, Any],
    ) -> None:
        """Apply a local command fallback until SSL/cloud confirms it."""
        self.control.apply_optimistic(device_id, values)

    async def async_turn_on(self, device_id: str, brightness: int = None, color_temp: int = None) -> bool:
        """Open a device, routing the control command by category.

        Optional brightness/color_temp parameters send light settings in one request.
        """
        return await self.control.turn_on(
            device_id, brightness, color_temp
        )

    async def async_turn_off(self, device_id: str) -> bool:
        """Close a device, routing the control command by category."""
        return await self.control.turn_off(device_id)

    async def async_set_cover_position(self, device_id: str, position: int) -> bool:
        return await self.control.set_cover_position(device_id, position)

    async def async_stop_cover(self, device_id: str) -> bool:
        """Stop the curtain motor."""
        return await self.control.stop_cover(device_id)

    async def async_dream_curtain_action(self, device_id: str, action: str) -> bool:
        return await self.control.dream_curtain_action(device_id, action)

    async def async_relay_curtain_action(self, device_id: str, action: str) -> bool:
        return await self.control.relay_curtain_action(device_id, action)

    async def async_set_dream_curtain_angle(self, device_id: str, angle: int) -> bool:
        return await self.control.set_dream_curtain_angle(device_id, angle)

    async def async_set_floor_heating_temperature(self, device_id: str, temperature: int) -> bool:
        return await self.control.set_floor_heating_temperature(device_id, temperature)

    async def async_set_brightness(self, device_id: str, brightness: int) -> bool:
        """Set brightness using the HA LightEntity range (0-255)."""
        return await self.control.set_brightness(device_id, brightness)

    async def async_set_color_temp(self, device_id: str, color_temp_k: int) -> bool:
        """Set color temperature separately (Kelvin)."""
        return await self.control.set_color_temp(device_id, color_temp_k)

    async def async_set_light_param(self, device_id: str, brightness: Optional[int], color_temp_k: Optional[int]) -> bool:
        """Send brightness and color temperature together in one cmd=15 to avoid out-of-sync requests."""
        return await self.control.set_light_param(
            device_id, brightness, color_temp_k
        )

    # ------------------------------------------------------------------
    # AC control (deviceType=36, cmd=15 set property)
    # ------------------------------------------------------------------
    async def _async_ac_control_raw(self, device_id: str, device_uid: str,
                                    value1=None, value2=None, value3=None, value4=None,
                                    order: str = "set property") -> bool:
        """Send a raw AC command (value1-value4).

        Based on a 2026-07-17 Smart Home 365 app packet capture, AC control uses these orders:
          - Power on:  order="on",               value1=0, value2=mode, value3=fan speed, value4=temperature<<16
          - Power off: order="off",              value1=1, value2=mode, value3=fan speed, value4=temperature<<16
          - Set mode:  order="mode setting",     value1=0, value2=mode
          - Set temp:  order="temperature setting", value1=0, value2=mode, value3=fan speed, value4=(temp*100)<<16
          - Set fan:   order="wind setting",     value1=0, value2=mode, value3=fan speed, value4=temperature<<16
        """
        from .packet import HomemateJsonData

        owner, scope = self.control._transport(device_id)
        if owner is None:
            _LOGGER.error("Control channel is not initialized; cannot send AC command")
            return False

        _LOGGER.debug(
            f"Sending AC control {device_id} scope={scope} order={order} "
            f"v1={value1}, v2={value2}, v3={value3}, v4={value4}"
        )
        if scope == "lan":
            try:
                ok = bool(
                    await owner.send_ac_control(
                        device_id,
                        device_uid,
                        order=order,
                        value1=value1,
                        value2=value2,
                        value3=value3,
                        value4=value4,
                    )
                )
            except Exception as error:  # noqa: BLE001 - cloud fallback is intentional
                _LOGGER.debug(
                    "LAN AC control failed; falling back to cloud: device=%s error=%s",
                    device_id,
                    type(error).__name__,
                )
                ok = False
            if ok:
                self._apply_ac_optimistic(device_id, value1, value2, value3, value4)
                return ok
            _LOGGER.debug("LAN AC control unconfirmed; falling back to SSL: device=%s", device_id)

        if (
            not self.ssl_client
            or not self.ssl_client.session_key
            or self.ssl_client.session_key == DEFAULT_KEY.encode("utf-8")
        ):
            _LOGGER.warning("Session key is invalid; cannot send AC command")
            return False

        payload = HomemateJsonData.ssl_control_ac(
            self.username,
            device_id,
            device_uid,
            order=order,
            value1=value1,
            value2=value2,
            value3=value3,
            value4=value4,
        )
        await self.ssl_client._send_packet(payload, self.ssl_client.session_key)

        # Wait for the AC device response
        response = await self._wait_for_control_response(device_id)
        if not response:
            # On timeout, keep the optimistic update as a fallback
            self._apply_ac_optimistic(device_id, value1, value2, value3, value4)
        else:
            # If a response arrives, update the coordinator (SSL pushes call on_status_update)
            dev_state = self.get_device_state(device_id)
            if dev_state:
                self.async_set_updated_data(self.device_states)
        return True

    def _apply_ac_optimistic(
        self,
        device_id: str,
        value1,
        value2,
        value3,
        value4,
    ) -> None:
        """Write back an optimistic state after AC control when waiting for the echo times out."""
        dev_state = self.get_device_state(device_id)
        if not dev_state:
            return
        optimistic_fields = set()
        if value1 is not None:
            dev_state["state"] = value1 == 0
            optimistic_fields.add("state")
        if value2 is not None:
            ac_mode_map = {2: "dehumidify", 3: "cool", 4: "heat", 7: "fan_only"}
            dev_state["ac_mode"] = ac_mode_map.get(value2, f"unknown({value2})")
            dev_state["ac_mode_raw"] = value2
            optimistic_fields.update(("ac_mode", "ac_mode_raw"))
        if value3 is not None:
            fan_speed_map = {1: "low", 2: "medium", 3: "high"}
            dev_state["fan_speed"] = fan_speed_map.get(value3, f"unknown({value3})")
            dev_state["fan_speed_raw"] = value3
            optimistic_fields.update(("fan_speed", "fan_speed_raw"))
        if value4 is not None:
            try:
                temp_raw = value4 >> 16
                dev_state["temperature"] = (
                    round(temp_raw / 100.0, 1) if temp_raw else 0
                )
            except (TypeError, ValueError):
                dev_state["temperature"] = value4
            optimistic_fields.add("temperature")
        if optimistic_fields:
            self.state_store.mark(
                device_id,
                optimistic_fields,
                StateSource.OPTIMISTIC,
            )
        self.async_set_updated_data(self.device_states)

    async def async_set_ac_mode(self, device_id: str, ac_mode: str) -> bool:
        """Control the AC mode (cool/dehumidify/heat/fan_only)."""
        device = self.devices.get(device_id)
        if not device:
            return False
        mode_map = {"dehumidify": 2, "cool": 3, "heat": 4, "fan_only": 7}
        mode_value = mode_map.get(ac_mode.lower())
        if mode_value is None:
            _LOGGER.error("Invalid AC mode: %s", ac_mode)
            return False
        # Change mode: order="mode setting", value1=0, value2=mode code
        # Inherit the current temperature
        dev_state = self.get_device_state(device_id) or {}
        cur_v4 = dev_state.get("value4", 0)
        if not cur_v4:
            cur_v4 = 2500 << 16
        return await self._async_ac_control_raw(device_id, device.get("uid", ""),
                                                value1=0, value2=mode_value,
                                                value4=cur_v4,
                                                order="mode setting")

    async def async_set_ac_temperature(self, device_id: str, temperature: float) -> bool:
        """Control the AC temperature in Celsius."""
        device = self.devices.get(device_id)
        if not device:
            return False
        
        # Set temperature: order="temperature setting", value2=current mode, value3=current fan speed, value4=(temp*100)<<16
        dev_state = self.get_device_state(device_id) or {}
        cur_v2 = dev_state.get("ac_mode_raw", 3)
        cur_v3 = dev_state.get("fan_speed_raw", 1)
        
        target_temp_scaled = int(temperature * 100)
        value4 = target_temp_scaled << 16
        
        return await self._async_ac_control_raw(device_id, device.get("uid", ""),
                                                value1=0, value2=cur_v2,
                                                value3=cur_v3, value4=value4,
                                                order="temperature setting")

    async def async_set_ac_fan_speed(self, device_id: str, fan_speed: str) -> bool:
        """Control the AC fan speed (low/medium/high)."""
        device = self.devices.get(device_id)
        if not device:
            return False
        speed_map = {"low": 1, "medium": 2, "high": 3}
        speed_value = speed_map.get(fan_speed.lower())
        if speed_value is None:
            _LOGGER.error("Invalid fan speed: %s", fan_speed)
            return False
        # Set fan speed: order="wind setting", value2=current mode, value3=fan speed, value4=current temperature<<16
        dev_state = self.get_device_state(device_id) or {}
        cur_v2 = dev_state.get("ac_mode_raw", 3)
        cur_v4 = dev_state.get("value4", 0)
        if not cur_v4:
            cur_v4 = 2500 << 16
        return await self._async_ac_control_raw(device_id, device.get("uid", ""),
                                                value1=0, value2=cur_v2,
                                                value3=speed_value, value4=cur_v4,
                                                order="wind setting")

    # ------------------------------------------------------------------
    # Ventilation system control (deviceType=516, cmd=15 set property)
    # ------------------------------------------------------------------
    async def async_ventilation_state_update(self, device_id: str, value1: int) -> bool:
        """Ventilation system control (value1 format).
        value1: 0=slow, 50=stop, 100=fast
        """
        return await self.control.ventilation_state_update(device_id, value1)

    async def async_set_ventilation_preset_mode(self, device_id: str, preset_mode: str) -> bool:
        """Set the ventilation preset mode (stop/slow/fast)."""
        return await self.control.set_ventilation_preset_mode(
            device_id, preset_mode
        )

    # ------------------------------------------------------------------
    # Clothes dryer control (cmd=98)
    # ------------------------------------------------------------------
    async def async_clothes_horse_control(self, device_id: str, feature: str, value: str) -> bool:
        """Control a clothes dryer.

        feature: lighting/sterilizing/wind_drying/heat_drying/main_switch/motor
        value: on/off for switch controls or up/down/stop for motor controls
        """
        return await self.control.clothes_horse_control(
            device_id, feature, value
        )

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        return self.devices.get(device_id)

    def get_device_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Return the last reported state without changing availability.

        Device pushes report changes, not periodic per-device heartbeats. A quiet
        light may still be online, including after a fresh REST snapshot. Only
        state reconciliation should update online; reading state for a control
        or an entity property must never mark the device offline.
        """
        return self.device_states.get(device_id)

    async def async_cleanup(self):
        self._lan_closed = True
        await self.lock_media.async_shutdown()
        if self._lan_discover_task is not None:
            self._lan_discover_task.cancel()
            self._lan_discover_task = None
        if self.gateway_manager is not None:
            await self.gateway_manager.close()
            self.gateway_manager = None
            _LOGGER.debug("LAN gateway cleaned up")
        if self.ssl_client:
            await self.ssl_client._disconnect()
            _LOGGER.debug("SSL connection closed and cleaned up")
        if self.https_client:
            await self.https_client.close()
            _LOGGER.debug("HTTPS client cleaned up")
