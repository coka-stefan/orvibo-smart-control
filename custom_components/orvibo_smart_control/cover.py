import logging
from typing import Optional

from homeassistant.components.cover import CoverEntity, CoverDeviceClass, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, DEVICE_TYPE_COVER, DEVICE_TYPE_CLOTHES_HORSE
from .coordinator import OrviboSmartControlCoordinator
from .selection import selected_device_ids
from .device_types import DeviceCategory, classify_device

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
        if device.get("device_type") == DEVICE_TYPE_COVER:
            entities.append(OrviboCover(coordinator, device))
        elif device.get("device_type") == DEVICE_TYPE_CLOTHES_HORSE:
            entities.append(OrviboClothesHorseMotor(coordinator, device))

    async_add_entities(entities)


class OrviboCover(CoordinatorEntity, CoverEntity):
    _attr_has_entity_name = True
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["device_id"]
        self._attr_unique_id = f"orvibo_smart_control_cover_{self._device_id}"
        # Primary entity: has_entity_name with name None shows only the device name.
        self._attr_name = None
        self._category = classify_device(device)
        if self._category == DeviceCategory.DREAM_CURTAIN:
            self._attr_supported_features = self._attr_supported_features | CoverEntityFeature.SET_TILT_POSITION
        if self._category == DeviceCategory.RELAY_CURTAIN:
            # The relay controller reports no position, so HA keeps both directions enabled.
            self._attr_supported_features = (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
            )
            self._attr_assumed_state = True
            self._attr_device_class = CoverDeviceClass.SHADE
            self._attr_icon = "mdi:roller-shade"
            return
        # Check whether this is a roller blind (type=35) and use the SHUTTER icon
        device_type_raw = device.get("device_type_raw", 0)
        if device_type_raw == 35:
            self._attr_device_class = CoverDeviceClass.SHUTTER
            self._attr_icon = "mdi:roller-shade"
        else:
            self._attr_device_class = CoverDeviceClass.CURTAIN

    @property
    def current_cover_position(self) -> Optional[int]:
        if self._category == DeviceCategory.RELAY_CURTAIN:
            return None
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("position", 0) if state else 0

    @property
    def is_closed(self) -> Optional[bool]:
        if self._category == DeviceCategory.RELAY_CURTAIN:
            return None
        position = self.current_cover_position
        return position == 0

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
            "model": self._device.get("model", "Orvibo Curtain"),
            "sw_version": "1.0",
        }

    async def async_open_cover(self, **kwargs) -> None:
        if self._category == DeviceCategory.RELAY_CURTAIN:
            await self.coordinator.async_relay_curtain_action(self._device_id, "open")
        elif self._category == DeviceCategory.DREAM_CURTAIN:
            await self.coordinator.async_dream_curtain_action(self._device_id, "open")
        else:
            await self.coordinator.async_set_cover_position(self._device_id, 100)

    async def async_close_cover(self, **kwargs) -> None:
        if self._category == DeviceCategory.RELAY_CURTAIN:
            await self.coordinator.async_relay_curtain_action(self._device_id, "close")
        elif self._category == DeviceCategory.DREAM_CURTAIN:
            await self.coordinator.async_dream_curtain_action(self._device_id, "close")
        else:
            await self.coordinator.async_set_cover_position(self._device_id, 0)

    async def async_stop_cover(self, **kwargs) -> None:
        if self._category == DeviceCategory.RELAY_CURTAIN:
            await self.coordinator.async_relay_curtain_action(self._device_id, "stop")
        else:
            await self.coordinator.async_stop_cover(self._device_id)

    async def async_set_cover_position(self, **kwargs) -> None:
        position = kwargs.get("position", 0)
        await self.coordinator.async_set_cover_position(self._device_id, position)

    @property
    def current_cover_tilt_position(self) -> Optional[int]:
        if self._category != DeviceCategory.DREAM_CURTAIN:
            return None
        state = self.coordinator.get_device_state(self._device_id) or {}
        angle = state.get("angle")
        return round(int(angle) * 100 / 180) if angle is not None else None

    async def async_set_cover_tilt_position(self, **kwargs) -> None:
        if self._category != DeviceCategory.DREAM_CURTAIN:
            return
        tilt = max(0, min(100, int(kwargs.get("tilt_position", 0))))
        await self.coordinator.async_set_dream_curtain_angle(
            self._device_id, round(tilt * 180 / 100)
        )


class OrviboClothesHorseMotor(CoordinatorEntity, CoverEntity):
    """Clothes dryer motor cover entity (raise/lower)."""
    _attr_has_entity_name = True
    _attr_device_class = CoverDeviceClass.AWNING
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["device_id"]
        self._attr_unique_id = f"orvibo_smart_control_ch_motor_{self._device_id}"
        self._attr_name = 'Drying rack'
        self._attr_icon = "mdi:hanger"

    @property
    def current_cover_position(self) -> int:
        state = self.coordinator.get_device_state(self._device_id)
        # Clothes dryer position=0 is the top (retracted); HA cover position=0 is closed
        # Map directly: top=0=closed, bottom=100=open
        return state.get("position", 0) if state else 0

    @property
    def is_closed(self) -> bool:
        position = self.current_cover_position
        return position == 0

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
            "model": self._device.get("model", "Orvibo Clothes Horse"),
            "sw_version": "1.0",
        }

    async def async_open_cover(self, **kwargs) -> None:
        """Open the clothes rail (lower it to the bottom)."""
        await self.coordinator.async_clothes_horse_control(self._device_id, "motor", "down")

    async def async_close_cover(self, **kwargs) -> None:
        """Close the clothes rail (raise it to the top)."""
        await self.coordinator.async_clothes_horse_control(self._device_id, "motor", "up")

    async def async_stop_cover(self, **kwargs) -> None:
        """Stop the motor."""
        await self.coordinator.async_clothes_horse_control(self._device_id, "motor", "stop")

    async def async_set_cover_position(self, **kwargs) -> None:
        """Set the position. The clothes dryer does not support precise positioning, so convert this to a raise/lower operation."""
        position = kwargs.get("position", 0)
        current = self.current_cover_position
        if position == current:
            return
        if position > current:
            # Increasing HA position means more open; the clothes dryer lowers
            await self.coordinator.async_clothes_horse_control(self._device_id, "motor", "down")
        else:
            # Decreasing HA position means more closed; the clothes dryer rises
            await self.coordinator.async_clothes_horse_control(self._device_id, "motor", "up")
