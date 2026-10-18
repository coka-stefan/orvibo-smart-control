"""Orvibo binary sensor platform.

Supported device categories:
- MOTION_SENSOR (deviceType=26) motion sensor
- DOOR_WINDOW_SENSOR (deviceType=46) door/window sensor
- EMERGENCY_BUTTON (deviceType=56) emergency button
"""
import logging
from typing import Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import OrviboSmartControlCoordinator
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
        category = classify_device(device)
        if category == DeviceCategory.MOTION_SENSOR:
            entities.append(OrviboMotionSensor(coordinator, device))
        elif category == DeviceCategory.DOOR_WINDOW_SENSOR:
            entities.append(OrviboDoorWindowSensor(coordinator, device))
        elif category == DeviceCategory.DOOR_LOCK:
            entities.append(OrviboDoorLockDoorSensor(coordinator, device))
            entities.append(OrviboDoorLockDoorbellSensor(coordinator, device))
        elif category == DeviceCategory.SMOKE_SENSOR:
            entities.append(OrviboSmokeSensor(coordinator, device))
        elif category == DeviceCategory.EMERGENCY_BUTTON:
            entities.append(OrviboEmergencyButton(coordinator, device))
        elif category == DeviceCategory.WATER_LEAK_SENSOR:
            entities.append(OrviboWaterLeakSensor(coordinator, device))
        elif category == DeviceCategory.GAS_SENSOR:
            entities.append(OrviboGasSensor(coordinator, device))

    async_add_entities(entities)


class OrviboMotionSensor(CoordinatorEntity, BinarySensorEntity):
    """Motion sensor (deviceType=26)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.get("device_id", "")
        self._attr_unique_id = f"orvibo_smart_control_motion_{self._device_id}"
        self._attr_name = 'Motion'
        self._attr_device_class = BinarySensorDeviceClass.MOTION
        self._attr_icon = "mdi:motion-sensor"

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("motion_detected", False) if state else False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", "Orvibo Motion Sensor"),
            "manufacturer": MANUFACTURER,
            "model": "Motion Sensor",
            "sw_version": "1.0",
        }


class OrviboDoorWindowSensor(CoordinatorEntity, BinarySensorEntity):
    """Door/window sensor (deviceType=46)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.get("device_id", "")
        self._attr_unique_id = f"orvibo_smart_control_door_{self._device_id}"
        self._attr_name = 'Door'
        self._attr_device_class = BinarySensorDeviceClass.DOOR
        self._attr_icon = "mdi:door-open"

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("door_state", False) if state else False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", "Orvibo Door Window Sensor"),
            "manufacturer": MANUFACTURER,
            "model": "Door Window Sensor",
            "sw_version": "1.0",
        }


class OrviboDoorLockDoorSensor(CoordinatorEntity, BinarySensorEntity):
    """Smart lock door contact state (deviceType=522)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.get("device_id", "")
        self._attr_unique_id = f"orvibo_smart_control_door_lock_door_{self._device_id}"
        self._attr_name = 'Door'
        self._attr_device_class = BinarySensorDeviceClass.DOOR
        self._attr_icon = "mdi:door-open"

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("door_state", False) if state else False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", "Orvibo Door Lock"),
            "manufacturer": MANUFACTURER,
            "model": "Smart Lock",
            "sw_version": "1.0",
        }


class OrviboSmokeSensor(CoordinatorEntity, BinarySensorEntity):
    """Smoke sensor (deviceType=27)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.get("device_id", "")
        self._attr_unique_id = f"orvibo_smart_control_smoke_{self._device_id}"
        self._attr_name = 'Smoke'
        self._attr_device_class = BinarySensorDeviceClass.SMOKE
        self._attr_icon = "mdi:smoke-detector"

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("smoke_detected", False) if state else False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", "Orvibo Smoke Sensor"),
            "manufacturer": MANUFACTURER,
            "model": "Smoke Sensor",
            "sw_version": "1.0",
        }


class OrviboEmergencyButton(CoordinatorEntity, BinarySensorEntity):
    """Emergency button (deviceType=56)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.get("device_id", "")
        self._attr_unique_id = f"orvibo_smart_control_emergency_{self._device_id}"
        self._attr_name = 'Emergency button'
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_icon = "mdi:alert-octagon"

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("emergency_state", False) if state else False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", "Orvibo Emergency Button"),
            "manufacturer": MANUFACTURER,
            "model": "Emergency Button",
            "sw_version": "1.0",
        }


class OrviboWaterLeakSensor(CoordinatorEntity, BinarySensorEntity):
    """Water leak detector (deviceType=54)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.get("device_id", "")
        self._attr_unique_id = f"orvibo_smart_control_water_leak_{self._device_id}"
        self._attr_name = 'Water leak'
        self._attr_device_class = BinarySensorDeviceClass.MOISTURE
        self._attr_icon = "mdi:water"

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("water_leak_detected", False) if state else False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", "Orvibo Water Leak Sensor"),
            "manufacturer": MANUFACTURER,
            "model": "Water Leak Sensor",
            "sw_version": "1.0",
        }


class OrviboGasSensor(CoordinatorEntity, BinarySensorEntity):
    """Combustible gas detector (deviceType=25)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.get("device_id", "")
        self._attr_unique_id = f"orvibo_smart_control_gas_{self._device_id}"
        self._attr_name = 'Gas'
        self._attr_device_class = BinarySensorDeviceClass.GAS
        self._attr_icon = "mdi:gas-cylinder"

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("gas_detected", False) if state else False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", "Orvibo Gas Sensor"),
            "manufacturer": MANUFACTURER,
            "model": "Gas Sensor",
            "sw_version": "1.0",
        }


class OrviboDoorLockDoorbellSensor(CoordinatorEntity, BinarySensorEntity):
    """Smart lock doorbell event (deviceType=522)."""

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.get("device_id", "")
        self._attr_unique_id = f"orvibo_smart_control_door_lock_doorbell_{self._device_id}"
        self._attr_name = 'Doorbell'
        self._attr_device_class = BinarySensorDeviceClass.OCCUPANCY
        self._attr_icon = "mdi:bell-ring"

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("doorbell_ring", False) if state else False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", "Orvibo Door Lock"),
            "manufacturer": MANUFACTURER,
            "model": "Smart Lock",
            "sw_version": "1.0",
        }


