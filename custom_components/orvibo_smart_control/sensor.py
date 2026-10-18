"""Orvibo sensor platform.

Supported device categories:
- MOTION_SENSOR (deviceType=26) motion sensor
- SMOKE_SENSOR (deviceType=27) smoke sensor
- EMERGENCY_BUTTON (deviceType=56) emergency button
- DOOR_LOCK (deviceType=300) smart lock
- TEMP_HUMIDITY_SENSOR (deviceType=300 subType=491) temperature/humidity sensor
- DOOR_WINDOW_SENSOR (deviceType=46) door/window sensor
"""
import logging
from typing import Optional

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .lock_status import normalize_battery_level
from .capabilities import (
    ControlChannel,
    TransportPath,
    capability_for,
    transport_path_for,
)
from .coordinator import OrviboSmartControlCoordinator
from .camera_metadata import (
    CAMERA_CATEGORIES,
    CAMERA_SDK_OPTIONS,
    camera_diagnostics,
    camera_sdk_hint,
)
from .device_types import DeviceCategory, classify_device
from .selection import selected_device_ids

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OrviboSmartControlCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    selected_ids = selected_device_ids(config_entry.options, coordinator.devices)

    entities = []
    for device_id, device in coordinator.devices.items():
        if device_id not in selected_ids:
            continue
        capability = capability_for(device)
        if capability.platforms:
            entities.append(OrviboTransportPathSensor(coordinator, device))
        category = classify_device(device)
        if category in CAMERA_CATEGORIES:
            entities.append(OrviboCameraSdkSensor(coordinator, device))
        elif category == DeviceCategory.MOTION_SENSOR:
            entities.append(OrviboMotionBatterySensor(coordinator, device))
        elif category == DeviceCategory.TEMP_HUMIDITY_SENSOR:
            entities.append(OrviboTemperatureSensor(coordinator, device))
            entities.append(OrviboHumiditySensor(coordinator, device))
            entities.append(OrviboBatterySensor(coordinator, device))
        elif category == DeviceCategory.DOOR_WINDOW_SENSOR:
            entities.append(OrviboDoorWindowBatterySensor(coordinator, device))
        elif category == DeviceCategory.SMOKE_SENSOR:
            entities.append(OrviboSmokeBatterySensor(coordinator, device))
        elif category == DeviceCategory.EMERGENCY_BUTTON:
            entities.append(OrviboEmergencyButtonBatterySensor(coordinator, device))
        elif category == DeviceCategory.WATER_LEAK_SENSOR:
            entities.append(OrviboWaterLeakBatterySensor(coordinator, device))
        elif category == DeviceCategory.GAS_SENSOR:
            entities.append(OrviboGasBatterySensor(coordinator, device))
        elif category == DeviceCategory.DOOR_LOCK:
            entities.append(OrviboDoorLockDryBatterySensor(coordinator, device))
            entities.append(OrviboDoorLockLithiumBatterySensor(coordinator, device))
            entities.append(OrviboDoorLockStateSensor(coordinator, device))
            entities.append(OrviboDoorLockUnlockSensor(coordinator, device))

    async_add_entities(entities)


class OrviboSensorBase(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["device_id"]
        self._attr_unique_id = f"orvibo_smart_control_sensor_{self._device_id}"
        self._attr_name = device.get("device_name", self._device_id)

    @property
    def available(self) -> bool:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("online", False) if state else False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", self._device_id),
            "manufacturer": MANUFACTURER,
            "model": self._device.get("model", "Orvibo Sensor"),
            "sw_version": "1.0",
        }


class OrviboDoorLockSensorBase(OrviboSensorBase):
    """Lock state sensor.

    The cloud device list often omits or misreports ``online``, but the coordinator can still receive updates through
    SSL/cloud. Lock state, battery, and unlock events should keep showing the latest valid value.
    """

    @property
    def available(self) -> bool:
        return self.coordinator.get_device_state(self._device_id) is not None


class OrviboTransportPathSensor(OrviboSensorBase):
    """Diagnostic marker for the device's configured control/state path."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = [path.value for path in TransportPath]
    _attr_translation_key = "transport_path"

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = (
            f"orvibo_smart_control_transport_path_{self._device_id}"
        )
        self._attr_name = None

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return transport_path_for(
            self._device,
            self.coordinator.transport_mode,
        ).value

    @property
    def icon(self) -> str:
        return {
            TransportPath.LAN.value: "mdi:lan-connect",
            TransportPath.CLOUD.value: "mdi:cloud",
            TransportPath.LAN_CLOUD.value: "mdi:swap-horizontal",
            TransportPath.UNAVAILABLE.value: "mdi:lan-disconnect",
        }[self.native_value]

    @property
    def extra_state_attributes(self) -> dict:
        capability = capability_for(self._device)
        attributes = {
            "configured_mode": self.coordinator.transport_mode.value,
            "lan_control_supported": ControlChannel.LAN in capability.channels,
            "cloud_control_supported": ControlChannel.SSL in capability.channels,
            "cloud_only": capability.cloud_only,
            "gateway_connected": self.coordinator.lan_gateway_connected(
                self._device_id
            ),
        }
        last_transport = self.coordinator.control.last_transport(self._device_id)
        if last_transport is not None:
            attributes["last_control_transport"] = last_transport
        return attributes


class OrviboCameraSdkSensor(OrviboSensorBase):
    """Read-only SDK hint, independent of the camera's online state."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = list(CAMERA_SDK_OPTIONS)
    _attr_translation_key = "camera_sdk"
    _attr_icon = "mdi:camera-outline"

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_camera_sdk_{self._device_id}"
        self._attr_name = None

    @property
    def available(self) -> bool:
        return self._device_id in self.coordinator.devices

    @property
    def native_value(self) -> str:
        return camera_sdk_hint(self.coordinator.devices.get(self._device_id, {}))

    @property
    def extra_state_attributes(self) -> dict:
        return camera_diagnostics(self.coordinator.devices.get(self._device_id, {}))


class OrviboMotionBatterySensor(OrviboSensorBase):
    """Motion sensor battery level (deviceType=26)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_motion_battery_{self._device_id}"
        self._attr_name = 'Battery'
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            bat = state.get("battery")
            if bat is not None:
                return int(bat)
        return None


class OrviboTemperatureSensor(OrviboSensorBase):
    """Temperature/humidity sensor temperature (deviceType=300 subType=491)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_temp_{self._device_id}"
        self._attr_name = 'Temperature'
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "°C"

    @property
    def native_value(self) -> Optional[float]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            temp = state.get("temperature")
            if temp is not None:
                return float(temp)
        return None


class OrviboHumiditySensor(OrviboSensorBase):
    """Temperature/humidity sensor humidity (deviceType=300 subType=491)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_humidity_{self._device_id}"
        self._attr_name = 'Humidity'
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[float]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            hum = state.get("humidity")
            if hum is not None:
                return float(hum)
        return None


class OrviboBatterySensor(OrviboSensorBase):
    """Temperature/humidity sensor battery level (deviceType=300 subType=491)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_battery_{self._device_id}"
        self._attr_name = 'Battery'
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            bat = state.get("battery")
            if bat is not None:
                return int(bat)
        return None


class OrviboDoorWindowBatterySensor(OrviboSensorBase):
    """Door/window sensor battery level (deviceType=46)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_door_battery_{self._device_id}"
        self._attr_name = 'Battery'
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            bat = state.get("battery")
            if bat is not None:
                return int(bat)
        return None


class OrviboSmokeBatterySensor(OrviboSensorBase):
    """Smoke sensor battery level (deviceType=27)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_smoke_battery_{self._device_id}"
        self._attr_name = 'Battery'
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            bat = state.get("battery")
            if bat is not None:
                return int(bat)
        return None


class OrviboEmergencyButtonBatterySensor(OrviboSensorBase):
    """Emergency button battery level (deviceType=56)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_emergency_battery_{self._device_id}"
        self._attr_name = 'Battery'
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            bat = state.get("battery")
            if bat is not None:
                return int(bat)
        return None


class OrviboWaterLeakBatterySensor(OrviboSensorBase):
    """Water leak detector battery level (deviceType=54)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_water_leak_battery_{self._device_id}"
        self._attr_name = 'Battery'
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            bat = state.get("battery")
            if bat is not None:
                return int(bat)
        return None


class OrviboGasBatterySensor(OrviboSensorBase):
    """Combustible gas detector battery level (deviceType=25)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_gas_battery_{self._device_id}"
        self._attr_name = 'Battery'
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            bat = state.get("battery")
            if bat is not None:
                return int(bat)
        return None


class OrviboDoorLockBatterySensorBase(OrviboDoorLockSensorBase):
    """Keep valid battery sources visible as readings arrive or batteries are removed."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._sync_battery_visibility()

    def _handle_coordinator_update(self) -> None:
        self._sync_battery_visibility()
        super()._handle_coordinator_update()

    def _sync_battery_visibility(self) -> None:
        registry = er.async_get(self.hass)
        entry = registry.async_get(self.entity_id)
        if entry is None or entry.hidden_by not in (None, er.RegistryEntryHider.INTEGRATION):
            return
        hidden_by = er.RegistryEntryHider.INTEGRATION if self.native_value is None else None
        if entry.hidden_by != hidden_by:
            registry.async_update_entity(self.entity_id, hidden_by=hidden_by)


class OrviboDoorLockDryBatterySensor(OrviboDoorLockBatterySensorBase):
    """Smart lock disposable battery level (deviceType=522)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_door_lock_dry_battery_{self._device_id}"
        self._attr_name = 'Primary battery'
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            if state.get("dry_battery_setup") is False:
                return None
            return normalize_battery_level(state.get("dry_battery_level"))
        return None

    @property
    def extra_state_attributes(self):
        state = self.coordinator.get_device_state(self._device_id)
        if not state:
            return {}
        return {
            "is_setup": state.get("dry_battery_setup"),
        }


class OrviboDoorLockLithiumBatterySensor(OrviboDoorLockBatterySensorBase):
    """Smart lock lithium battery level (deviceType=522)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_door_lock_lithium_battery_{self._device_id}"
        self._attr_name = 'Rechargeable battery'
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state:
            if state.get("lithium_battery_setup") is False:
                return None
            return normalize_battery_level(state.get("lithium_battery_level"))
        return None

    @property
    def extra_state_attributes(self):
        state = self.coordinator.get_device_state(self._device_id)
        if not state:
            return {}
        return {
            "is_setup": state.get("lithium_battery_setup"),
        }


class OrviboDoorLockStateSensor(OrviboDoorLockSensorBase):
    """Smart lock state (locked/unlocked/deadbolted from inside/inconsistent, with a bound door contact)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["locked", "unlocked", "inside_locked", "abnormal"]
    _attr_translation_key = "door_lock_state"

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_door_lock_state_{self._device_id}"
        self._attr_name = 'Lock state'
        self._attr_icon = "mdi:lock"

    @property
    def native_value(self) -> Optional[str]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("lock_status") if state else None

    @property
    def extra_state_attributes(self) -> dict:
        state = self.coordinator.get_device_state(self._device_id) or {}
        return {
            "door_open": state.get("door_state"),
            "inside_locked": state.get("inside_lock_state"),
            "leave_home_armed": state.get("leave_home_armed"),
            "locked": state.get("locked"),
        }


class OrviboDoorLockUnlockSensor(OrviboDoorLockSensorBase):
    """Smart lock unlock event (state displays "xxx door opened")."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator, device)
        self._attr_unique_id = f"orvibo_smart_control_door_lock_unlock_{self._device_id}"
        self._attr_name = 'Unlock event'
        self._attr_icon = "mdi:key"

    @property
    def native_value(self) -> str:
        from .lock_status import format_unlock_label

        state = self.coordinator.get_device_state(self._device_id)
        if not state:
            return 'None'
        user_id = state.get("unlock_user_id")
        name = self.coordinator.lock_user_name(self._device_id, user_id, state.get("unlock_method"))
        return format_unlock_label(
            user_id, name, state.get("open_direction"), state.get("unlock_method")
        )

    @property
    def extra_state_attributes(self) -> dict:
        state = self.coordinator.get_device_state(self._device_id) or {}
        attributes = {
            "unlock_type": state.get("unlock_type"),
            "unlock_user_id": state.get("unlock_user_id"),
            "open_direction": state.get("open_direction"),
            "unlock_method": state.get("unlock_method"),
        }
        user_name = self.coordinator.lock_user_name(
            self._device_id,
            state.get("unlock_user_id"),
            state.get("unlock_method"),
        )
        if user_name:
            attributes["unlock_user_name"] = user_name
        if state.get("unlock_time") is not None:
            attributes["unlock_time"] = state.get("unlock_time")
        return attributes
