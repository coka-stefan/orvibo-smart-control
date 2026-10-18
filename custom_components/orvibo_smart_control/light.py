import logging
from typing import Optional

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, DEVICE_TYPE_LIGHT, DEVICE_TYPE_CLOTHES_HORSE
from .coordinator import OrviboSmartControlCoordinator
from .device_types import classify_device, DeviceCategory
from .light_values import normalize_brightness
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
        if device.get("device_type") == DEVICE_TYPE_LIGHT:
            entities.append(OrviboLight(coordinator, device))
        elif device.get("device_type") == DEVICE_TYPE_CLOTHES_HORSE:
            entities.append(OrviboClothesHorseLight(coordinator, device))

    async_add_entities(entities)


class OrviboLight(CoordinatorEntity, LightEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["device_id"]
        self._attr_unique_id = f"orvibo_smart_control_light_{self._device_id}"
        # Primary entity: has_entity_name with name None shows only the device name.
        self._attr_name = None
        device_name = device.get("device_name", self._device_id)

        ui_model = device.get("ui_model", "")
        device_type_raw = device.get("device_type_raw")
        class_id = device.get("class_id")
        model = device.get("model", "")
        properties = device.get("properties", {})
        
        # Convert to an integer
        try:
            device_type_raw = int(device_type_raw) if device_type_raw is not None else None
            class_id = int(class_id) if class_id is not None else None
        except (TypeError, ValueError):
            device_type_raw = None
            class_id = None
        
        sub_device_type = device.get("sub_device_type")
        status = device.get("status", {})
        _LOGGER.info("Initializing light: name=%s, device_type_raw=%s (type=%s), class_id=%s (type=%s), sub_device_type=%s, status=%s, device=%s", device_name, device_type_raw, type(device_type_raw), class_id, type(class_id), sub_device_type, status, device)
        
        # Identify a dimmable light from sub_device_type=-2 and value2 (brightness) in status
        if device_type_raw is None and sub_device_type == -2 and isinstance(status, dict):
            if "value2" in status:
                device_type_raw = 0
                _LOGGER.info("Inferred device_type_raw=0 from sub_device_type=-2 and value2")
        
        # Prefer classify_device; it is the most accurate source
        category = classify_device(device)
        
        # type=503 color temperature strips and type=502 dimmable lights use brightness 0-100; type=38 and type=0 use 0-255
        # FAST_MOVE_DIM_COLOR_LIGHT (subDeviceType=6) uses brightness 0-255
        self._brightness_is_percent = (device_type_raw in (502, 503))
        if category == DeviceCategory.FAST_MOVE_DIM_COLOR_LIGHT:
            self._brightness_is_percent = False

        _LOGGER.info("Light: %s, device_id=%s, ui_model=%s, deviceType=%s (type=%s), classId=%s (type=%s), model=%s", device_name, self._device_id, ui_model, device_type_raw, type(device_type_raw), class_id, type(class_id), model)

        is_dimmable = False

        if category in (DeviceCategory.DIM_COLOR_LIGHT, DeviceCategory.DIMMABLE_LIGHT, DeviceCategory.CCT_LIGHT, DeviceCategory.CCT_LIGHT_STRIP, DeviceCategory.ZIGBEE_DIMMABLE_LIGHT, DeviceCategory.FAST_MOVE_DIM_COLOR_LIGHT):
            is_dimmable = True
            _LOGGER.info("classify_device identified a dimmable light: category=%s", category)
        # Identify from ui.model
        elif ui_model in ("light_colortemp", "light_dimmable", "light_color") or "colortemp" in ui_model or "dimmable" in ui_model:
            is_dimmable = True
            _LOGGER.info("ui_model identified a dimmable light: %s", ui_model)
        # deviceType=38 is dimmable with color temperature; 502 is brightness-only; 503 is a color temperature strip; 0 is brightness-only
        elif device_type_raw in (38, 502, 503, 0):
            is_dimmable = True
            _LOGGER.info("deviceType=%s identified as a dimmable light", device_type_raw)
        # Check whether properties contains brightness or colortemp fields
        elif isinstance(properties, dict):
            has_brightness = "brightness" in properties
            has_colortemp = "colortemp" in properties
            if has_brightness or has_colortemp:
                is_dimmable = True
                _LOGGER.info("properties indicate a dimmable light: brightness=%s, colortemp=%s", has_brightness, has_colortemp)
        # classId=426/436 are dimmable lights
        elif category == DeviceCategory.UNKNOWN and class_id in (426, 436):
            is_dimmable = True
            _LOGGER.info("classId=%s identified as a dimmable light", class_id)

        if is_dimmable:
            if category in (DeviceCategory.DIMMABLE_LIGHT, DeviceCategory.ZIGBEE_DIMMABLE_LIGHT):
                self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
                self._attr_color_mode = ColorMode.BRIGHTNESS
                _LOGGER.info("Set BRIGHTNESS mode: category=%s", category)
            elif category == DeviceCategory.FAST_MOVE_DIM_COLOR_LIGHT:
                self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
                self._attr_color_mode = ColorMode.COLOR_TEMP
                self._min_mireds = 167  # 6000K
                self._max_mireds = 370  # 2700K
                self._attr_min_color_temp_kelvin = 2700
                self._attr_max_color_temp_kelvin = 6000
                _LOGGER.info("Set COLOR_TEMP mode (Fast Move): category=%s", category)
            else:
                self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
                self._attr_color_mode = ColorMode.COLOR_TEMP
                self._min_mireds = 154  # 6500K
                self._max_mireds = 370  # 2700K
                self._attr_min_color_temp_kelvin = 2700
                self._attr_max_color_temp_kelvin = 6500
                _LOGGER.info("Set COLOR_TEMP mode: category=%s", category)
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF
            _LOGGER.info("Set ONOFF mode")

        _LOGGER.info("Created light entity: %s, supported_modes=%s, is_dimmable=%s, brightness=%s, color_temp=%s", device_name, self._attr_supported_color_modes, is_dimmable, device.get("brightness"), device.get("color_temp"))

    @property
    def is_on(self) -> bool:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("state", False) if state else False

    @property
    def available(self) -> bool:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("online", False) if state else False

    @property
    def brightness(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state and state.get("state", False):
            brightness = normalize_brightness(
                state.get("brightness"), 100 if self._brightness_is_percent else 255
            )
            if brightness is not None:
                if self._brightness_is_percent:
                    # type=503 brightness is 0-100; convert it to the HA range of 0-255
                    return min(int(brightness * 255 / 100), 255)
                # type=38 brightness is already in the 0-255 range
                return min(brightness, 255)
        return None

    @property
    def color_temp(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state and state.get("state", False):
            color_temp = state.get("color_temp")
            if color_temp is not None and color_temp > 0:
                # color_temp in state is in Kelvin; HA expects mireds
                return int(1000000 / color_temp)
        return None

    @property
    def color_temp_kelvin(self) -> Optional[int]:
        state = self.coordinator.get_device_state(self._device_id)
        if state and state.get("state", False):
            color_temp = state.get("color_temp")
            if color_temp is not None and color_temp > 0:
                return int(color_temp)
        return None

    @property
    def min_mireds(self) -> int:
        return self._min_mireds

    @property
    def max_mireds(self) -> int:
        return self._max_mireds

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device.get("device_name", self._device_id),
            "manufacturer": MANUFACTURER,
            "model": self._device.get("model", "Orvibo Light"),
            "sw_version": "1.0",
        }

    async def async_turn_on(self, **kwargs) -> None:
        state = self.coordinator.get_device_state(self._device_id)
        current_state = state.get("state", False) if state else False

        brightness = kwargs.get("brightness")
        # HA 2024+ prefers color_temp_kelvin; older versions use color_temp in mireds
        color_temp_mired = kwargs.get("color_temp")
        color_temp_kelvin = kwargs.get("color_temp_kelvin")

        # Normalize to Kelvin, the unit used by the device protocol
        color_temp_k = None
        if color_temp_kelvin is not None:
            color_temp_k = int(color_temp_kelvin)
        elif color_temp_mired is not None and color_temp_mired > 0:
            color_temp_k = int(1000000 / color_temp_mired)

        _LOGGER.info(f"async_turn_on: kwargs={kwargs}, current_state={current_state}, color_temp_k={color_temp_k}")

        if brightness is not None and color_temp_k is not None:
            # HA brightness range is 0-255
            brightness_value = min(int(brightness), 255)
            if brightness_value == 0:
                brightness_value = 1
            # type=503 device brightness is 0-100 and needs conversion
            if self._brightness_is_percent:
                device_brightness = max(1, int(brightness_value * 100 / 255))
            else:
                device_brightness = brightness_value
            _LOGGER.info("Set brightness and color temperature together: brightness=%s, color_temp=%sK", device_brightness, color_temp_k)
            # ssl_control_light_brightness uses order="on" and turns the light on, so do not call async_turn_on again
            # Otherwise, async_turn_on without arguments sends value2=0/value3=0 and overwrites the brightness just set
            await self.coordinator.async_set_brightness(self._device_id, device_brightness)
            await self.coordinator.async_set_color_temp(self._device_id, color_temp_k)
        elif brightness is not None:
            brightness_value = min(int(brightness), 255)
            if brightness_value == 0:
                brightness_value = 1
            # type=503 device brightness is 0-100 and needs conversion
            if self._brightness_is_percent:
                device_brightness = max(1, int(brightness_value * 100 / 255))
            else:
                device_brightness = brightness_value
            _LOGGER.info("Set brightness: HA=%s -> device=%s", brightness, device_brightness)
            # ssl_control_light_brightness uses order="on" and turns the light on, so do not call async_turn_on again
            await self.coordinator.async_set_brightness(self._device_id, device_brightness)
        elif color_temp_k is not None:
            _LOGGER.info("Set color temperature: %sK", color_temp_k)
            # ssl_control_light_colortemp uses order="fast color temperature", which already includes current brightness
            # Match standalone behavior; do not call async_turn_on again
            await self.coordinator.async_set_color_temp(self._device_id, color_temp_k)
        else:
            await self.coordinator.async_turn_on(self._device_id)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_turn_off(self._device_id)


class OrviboClothesHorseLight(CoordinatorEntity, LightEntity):
    """Clothes dryer light entity (on/off only; no brightness or color temperature)."""
    _attr_has_entity_name = True
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator: OrviboSmartControlCoordinator, device: dict):
        super().__init__(coordinator)
        self._device = device
        self._device_id = device["device_id"]
        self._attr_unique_id = f"orvibo_smart_control_clothes_horse_light_{self._device_id}"
        self._attr_name = 'Light'
        self._attr_icon = "mdi:lightbulb"

    @property
    def is_on(self) -> bool:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get("lighting_state", False) if state else False

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

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_clothes_horse_control(self._device_id, "lighting", "on")

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_clothes_horse_control(self._device_id, "lighting", "off")
