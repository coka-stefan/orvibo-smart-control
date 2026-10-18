import logging
from typing import Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, DEVICE_TYPE_SWITCH, DEVICE_TYPE_CLOTHES_HORSE
from .coordinator import OrviboSmartControlCoordinator
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
        if device.get("device_type") == DEVICE_TYPE_SWITCH:
            entities.append(OrviboSwitch(coordinator, device))
        elif device.get("device_type") == DEVICE_TYPE_CLOTHES_HORSE:
            # Clothes dryer: main switch / sterilize / air dry / heat dry
            entities.append(OrviboClothesHorseSwitch(coordinator, device, "main_switch", 'Power', "mdi:power"))
            entities.append(OrviboClothesHorseSwitch(coordinator, device, "sterilizing", 'Disinfection', "mdi:shield-sun"))
            entities.append(OrviboClothesHorseSwitch(coordinator, device, "wind_drying", 'Air drying', "mdi:fan"))
            entities.append(OrviboClothesHorseSwitch(coordinator, device, "heat_drying", 'Heated drying', "mdi:heat-wave"))

    async_add_entities(entities)


class OrviboSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["device_id"]
        self._attr_unique_id = f"orvibo_smart_control_switch_{self._device_id}"
        # Primary entity: has_entity_name with name None shows only the device name.
        self._attr_name = None

    @property
    def is_on(self) -> bool:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("state", False) if state else False

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
            "model": self._device.get("model", "Orvibo Switch"),
            "sw_version": "1.0",
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_turn_on(self._device_id)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_turn_off(self._device_id)


class OrviboClothesHorseSwitch(CoordinatorEntity, SwitchEntity):
    """A clothes dryer switch sub-entity (main switch / sterilize / air dry / heat dry)."""
    _attr_has_entity_name = True

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict, feature: str, name: str, icon: str):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["device_id"]
        self._feature = feature
        self._state_key = f"{feature}_state"
        self._attr_unique_id = f"orvibo_smart_control_ch_switch_{feature}_{self._device_id}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get(self._state_key, False) if state else False

    @property
    def available(self) -> bool:
        state = self.coordinator.get_device_state(self._device_id)
        if not state or not state.get("online", False):
            return False
        # The sterilize switch is available only when the motor is at the top; keep it available while on so it can be turned off
        if self._feature == "sterilizing":
            position = state.get("position", 0)
            is_on = self.is_on
            return position == 0 or is_on
        return True

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", self._device_id),
            "manufacturer": MANUFACTURER,
            "model": self._device.get("model", "Orvibo Clothes Horse"),
            "sw_version": "1.0",
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_clothes_horse_control(self._device_id, self._feature, "on")

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_clothes_horse_control(self._device_id, self._feature, "off")