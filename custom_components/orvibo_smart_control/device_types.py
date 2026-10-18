"""Orvibo device classification taxonomy for the HA integration.

Device categories are defined by deviceTypeId and subType. classify_device accepts
the device dict returned by https_client.parse_device_status_list (including device_type_raw,
class_id, sub_device_type, and ui_model) and returns a DeviceCategory enum value;
unrecognized devices return UNKNOWN.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .known_device_models import identify_known_device


class DeviceCategory(Enum):
    UNKNOWN = "unknown"
    SIMPLE_ZIGBEE_LIGHT = "simple_zigbee_light"        # deviceTypeId=1
    ZIGBEE_CURTAIN = "zigbee_curtain"                  # deviceTypeId=34
    ZIGBEE_ROLLING_SHUTTER = "zigbee_rolling_shutter"   # deviceTypeId=35
    FAN_COIL_AC = "fan_coil_ac"                        # deviceTypeId=36
    MIXPAD_GATEWAY = "mixpad_gateway"                  # deviceTypeId=114
    MUSIC_HOST = "music_host"                          # deviceTypeId=128
    MIX_SWITCH = "mix_switch"                          # deviceTypeId=135/136/137/143
    MONO_LIGHT = "mono_light"                          # deviceTypeId=501
    CCT_LIGHT_STRIP = "cct_light_strip"                # deviceTypeId=503
    BACH_SWITCH = "bach_switch"                        # deviceTypeId=518
    DOOR_LOCK = "door_lock"                            # deviceTypeId=107/522, classId=462/463
    WIFI_CAMERA = "wifi_camera"                        # deviceTypeId=14
    CAMERA_NVR = "camera_nvr"                          # deviceTypeId=162
    LIGHT_VIRTUAL_GROUP = "light_virtual_group"        # deviceTypeId=10086
    DIM_COLOR_LIGHT = "dim_color_light"                # deviceTypeId=38
    LEGACY_LIGHT = "legacy_light"                      # deviceTypeId=102
    LEGACY_CURTAIN = "legacy_curtain"                  # deviceTypeId=52 (legacy mapping, retained for compatibility)
    CLOTHES_HORSE = "clothes_horse"                    # deviceTypeId=52, smart electric clothes dryer
    MOTION_SENSOR = "motion_sensor"                    # deviceTypeId=26
    SMOKE_SENSOR = "smoke_sensor"                      # deviceTypeId=27
    EMERGENCY_BUTTON = "emergency_button"              # deviceTypeId=56
    WATER_LEAK_SENSOR = "water_leak_sensor"            # deviceTypeId=54, water-leak sensor
    GAS_SENSOR = "gas_sensor"                          # deviceTypeId=25, gas sensor
    SMART_REMOTE = "smart_remote"                      # deviceTypeId=150
    MIXPAD_4WAY_BASE = "mixpad_4way_base"              # deviceTypeId=511
    DIMMABLE_LIGHT = "dimmable_light"                  # deviceTypeId=502, dimmable light (brightness only, no color temperature)
    ZIGBEE_DIMMABLE_LIGHT = "zigbee_dimmable_light"    # deviceTypeId=0, subDeviceType=-2, 0–10 V dimmable light
    CCT_LIGHT = "cct_light"                            # statusType=503 subDeviceType=461, 0-10 V color temperature light
    TEMP_HUMIDITY_SENSOR = "temp_humidity_sensor"      # deviceTypeId=300 subType=491, temperature and humidity sensor
    DOOR_WINDOW_SENSOR = "door_window_sensor"          # deviceTypeId=46, door/window sensor
    FAST_MOVE_DIM_COLOR_LIGHT = "fast_move_dim_color_light"  # statusType=2, subDeviceType=6, Fast Move dimmable color-temperature light
    VENTILATION_SYSTEM = "ventilation_system"                # deviceType=516, classId=1114, ventilation system
    FLOOR_HEATING = "floor_heating"                          # deviceType=300, subType=481
    LEGACY_FLOOR_HEATING = "legacy_floor_heating"            # deviceType=112, orb_floorheat
    DREAM_CURTAIN = "dream_curtain"                          # deviceType=506, subType=408
    RELAY_CURTAIN = "relay_curtain"                          # deviceType=42, subType=-2, multifunction controller
    OTHER = "other"


@dataclass(frozen=True)
class CategoryInfo:
    category: DeviceCategory
    label: str
    description: str
    capabilities: Tuple[str, ...]
    is_container: bool = False


@dataclass(frozen=True)
class DeviceProfile:
    """Resolved capability and hardware-verification metadata."""

    category: DeviceCategory
    info: CategoryInfo
    hardware_verified: bool
    registration_only: bool


_CATEGORY_INFO: Dict[DeviceCategory, CategoryInfo] = {
    DeviceCategory.SIMPLE_ZIGBEE_LIGHT: CategoryInfo(
        category=DeviceCategory.SIMPLE_ZIGBEE_LIGHT,
        label="Simple Zigbee light",
        description='deviceTypeId=1, subType=-2/1/13 (downlight/pendant/strip); on/off only',
        capabilities=("onoff",),
    ),
    DeviceCategory.ZIGBEE_CURTAIN: CategoryInfo(
        category=DeviceCategory.ZIGBEE_CURTAIN,
        label="Zigbee curtain",
        description='deviceTypeId=34, subType=-2; position 0–100%',
        capabilities=("position",),
    ),
    DeviceCategory.ZIGBEE_ROLLING_SHUTTER: CategoryInfo(
        category=DeviceCategory.ZIGBEE_ROLLING_SHUTTER,
        label="Zigbee roller blind",
        description='deviceTypeId=35; roller-blind control using the curtain protocol',
        capabilities=("position",),
    ),
    DeviceCategory.FAN_COIL_AC: CategoryInfo(
        category=DeviceCategory.FAN_COIL_AC,
        label="Fan-coil thermostat",
        description='deviceTypeId=36; power, temperature, mode and fan speed',
        capabilities=("onoff", "temperature", "mode", "fan_speed"),
    ),
    DeviceCategory.MIXPAD_GATEWAY: CategoryInfo(
        category=DeviceCategory.MIXPAD_GATEWAY,
        label="MixPad gateway",
        description='deviceTypeId=114; Zigbee hub and background music',
        capabilities=("gateway", "music"),
        is_container=True,
    ),
    DeviceCategory.MUSIC_HOST: CategoryInfo(
        category=DeviceCategory.MUSIC_HOST,
        label="Music controller",
        description='deviceTypeId=128; playback, volume and track selection',
        capabilities=("music_play", "volume", "skip"),
    ),
    DeviceCategory.MIX_SWITCH: CategoryInfo(
        category=DeviceCategory.MIX_SWITCH,
        label="MixSwitch",
        description='deviceTypeId=135/136/137/143; 1/2/3/4 channels; ui=MIXSWITCH',
        capabilities=("multi_channel_switch",),
        is_container=True,
    ),
    DeviceCategory.MONO_LIGHT: CategoryInfo(
        category=DeviceCategory.MONO_LIGHT,
        label="Single-color light",
        description='deviceTypeId=501, subType=426/429 (lightStd); on/off only',
        capabilities=("onoff",),
    ),
    DeviceCategory.CCT_LIGHT_STRIP: CategoryInfo(
        category=DeviceCategory.CCT_LIGHT_STRIP,
        label="Color-temperature light strip",
        description='deviceTypeId=503, subType=436 (colorTempLightStd); brightness and 2700–6500 K color temperature',
        capabilities=("onoff", "brightness", "color_temp"),
    ),
    DeviceCategory.BACH_SWITCH: CategoryInfo(
        category=DeviceCategory.BACH_SWITCH,
        label="Bach switch",
        description='deviceTypeId=518, subType=424 (8 channels)/1107 (4 channels)',
        capabilities=("multi_channel_switch",),
        is_container=True,
    ),
    DeviceCategory.DOOR_LOCK: CategoryInfo(
        category=DeviceCategory.DOOR_LOCK,
        label="Smart door lock",
        description='deviceTypeId=107/522, classId=462/463; lock, door and battery state',
        capabilities=("lock", "door_state", "battery"),
    ),
    DeviceCategory.WIFI_CAMERA: CategoryInfo(
        category=DeviceCategory.WIFI_CAMERA,
        label="Wi-Fi camera",
        description='deviceTypeId=14; live video for matching Meari XTS/p2p2 models, diagnostics only for other protocols',
        capabilities=(),
    ),
    DeviceCategory.CAMERA_NVR: CategoryInfo(
        category=DeviceCategory.CAMERA_NVR,
        label="Network video recorder",
        description='deviceTypeId=162; live video for matching Meari XTS/p2p2 channels; disk playback in development',
        capabilities=(),
        is_container=True,
    ),
    DeviceCategory.LIGHT_VIRTUAL_GROUP: CategoryInfo(
        category=DeviceCategory.LIGHT_VIRTUAL_GROUP,
        label="Light group",
        description='deviceTypeId=10086',
        capabilities=("group_onoff",),
    ),
    DeviceCategory.DIM_COLOR_LIGHT: CategoryInfo(
        category=DeviceCategory.DIM_COLOR_LIGHT,
        label="Dimmable color-temperature light",
        description='deviceTypeId=38 (legacy field); brightness and color temperature',
        capabilities=("onoff", "brightness", "color_temp"),
    ),
    DeviceCategory.LEGACY_LIGHT: CategoryInfo(
        category=DeviceCategory.LEGACY_LIGHT,
        label="On/off light",
        description='deviceTypeId=102 (legacy field); on/off only',
        capabilities=("onoff",),
    ),
    DeviceCategory.LEGACY_CURTAIN: CategoryInfo(
        category=DeviceCategory.LEGACY_CURTAIN,
        label="Curtain",
        description='deviceTypeId=52 (legacy field)',
        capabilities=("position",),
    ),
    DeviceCategory.CLOTHES_HORSE: CategoryInfo(
        category=DeviceCategory.CLOTHES_HORSE,
        label="Clothes dryer",
        description='deviceTypeId=52; drying rack with light, disinfection, drying and lift controls',
        capabilities=("lighting", "sterilizing", "wind_drying", "heat_drying", "motor", "main_switch"),
    ),
    DeviceCategory.MOTION_SENSOR: CategoryInfo(
        category=DeviceCategory.MOTION_SENSOR,
        label="Motion sensor",
        description='deviceTypeId=26; motion detection',
        capabilities=("motion_detection",),
    ),
    DeviceCategory.SMOKE_SENSOR: CategoryInfo(
        category=DeviceCategory.SMOKE_SENSOR,
        label="Smoke sensor",
        description='deviceTypeId=27; smoke detection',
        capabilities=("smoke_detection",),
    ),
    DeviceCategory.EMERGENCY_BUTTON: CategoryInfo(
        category=DeviceCategory.EMERGENCY_BUTTON,
        label='Emergency button',
        description='deviceTypeId=56; emergency button',
        capabilities=("emergency_alarm",),
    ),
    DeviceCategory.WATER_LEAK_SENSOR: CategoryInfo(
        category=DeviceCategory.WATER_LEAK_SENSOR,
        label="Water-leak sensor",
        description='deviceTypeId=54; water-leak detection',
        capabilities=("water_leak_detection",),
    ),
    DeviceCategory.GAS_SENSOR: CategoryInfo(
        category=DeviceCategory.GAS_SENSOR,
        label="Gas sensor",
        description='deviceTypeId=25; combustible-gas detection',
        capabilities=("gas_detection",),
    ),
    DeviceCategory.SMART_REMOTE: CategoryInfo(
        category=DeviceCategory.SMART_REMOTE,
        label="Smart remote control",
        description='deviceTypeId=150; infrared remote control',
        capabilities=("ir_control",),
    ),
    DeviceCategory.MIXPAD_4WAY_BASE: CategoryInfo(
        category=DeviceCategory.MIXPAD_4WAY_BASE,
        label="MixPad four-channel base",
        description='deviceTypeId=511; MixPad expansion base',
        capabilities=("multi_channel_switch",),
        is_container=True,
    ),
    DeviceCategory.DIMMABLE_LIGHT: CategoryInfo(
        category=DeviceCategory.DIMMABLE_LIGHT,
        label="Dimmable light",
        description='deviceTypeId=502, subType=431; brightness without color temperature',
        capabilities=("onoff", "brightness"),
    ),
    DeviceCategory.ZIGBEE_DIMMABLE_LIGHT: CategoryInfo(
        category=DeviceCategory.ZIGBEE_DIMMABLE_LIGHT,
        label="0–10 V dimmable light",
        description='deviceTypeId=0, subDeviceType=-2; dimming using value1/value2',
        capabilities=("onoff", "brightness"),
    ),
    DeviceCategory.TEMP_HUMIDITY_SENSOR: CategoryInfo(
        category=DeviceCategory.TEMP_HUMIDITY_SENSOR,
        label="Temperature and humidity sensor",
        description='deviceTypeId=300 subType=491; temperature, humidity and battery',
        capabilities=("temperature", "humidity", "battery"),
    ),
    DeviceCategory.DOOR_WINDOW_SENSOR: CategoryInfo(
        category=DeviceCategory.DOOR_WINDOW_SENSOR,
        label="Door/window sensor",
        description='deviceTypeId=46; door and battery state',
        capabilities=("door_state", "battery"),
    ),
    DeviceCategory.FAST_MOVE_DIM_COLOR_LIGHT: CategoryInfo(
        category=DeviceCategory.FAST_MOVE_DIM_COLOR_LIGHT,
        label="Fast Move dimmable color-temperature light",
        description='statusType=2, subDeviceType=6; fast move to level protocol, brightness and color temperature',
        capabilities=("onoff", "brightness", "color_temp"),
    ),
    DeviceCategory.VENTILATION_SYSTEM: CategoryInfo(
        category=DeviceCategory.VENTILATION_SYSTEM,
        label="Ventilation system",
        description='deviceType=516, classId=1114; ventilation with Off/Low/High presets',
        capabilities=("onoff", "fan_speed", "preset_mode"),
    ),
    DeviceCategory.FLOOR_HEATING: CategoryInfo(
        category=DeviceCategory.FLOOR_HEATING,
        label="Floor-heating controller",
        description='deviceType=300, subType=481, MixPadFloorHeat',
        capabilities=("onoff", "target_temperature", "temperature", "humidity"),
    ),
    DeviceCategory.LEGACY_FLOOR_HEATING: CategoryInfo(
        category=DeviceCategory.LEGACY_FLOOR_HEATING,
        label="Floor-heating thermostat",
        description='deviceType=112, subType=-2, ui.model=orb_floorheat',
        capabilities=("onoff", "target_temperature", "temperature"),
    ),
    DeviceCategory.DREAM_CURTAIN: CategoryInfo(
        category=DeviceCategory.DREAM_CURTAIN,
        label="Sheer curtain",
        description='deviceType=506, subType=408; curtain position and slat angle',
        capabilities=("position", "stop", "angle"),
    ),
    DeviceCategory.RELAY_CURTAIN: CategoryInfo(
        category=DeviceCategory.RELAY_CURTAIN,
        label="Relay curtain controller",
        description='deviceType=42, subType=-2; open/close/stop keys without position feedback',
        capabilities=("open", "close", "stop"),
    ),
    DeviceCategory.OTHER: CategoryInfo(
        category=DeviceCategory.OTHER,
        label="Other device",
        description='Recognized deviceType outside the supported device categories',
        capabilities=(),
    ),
    DeviceCategory.UNKNOWN: CategoryInfo(
        category=DeviceCategory.UNKNOWN,
        label="Unrecognized device",
        description='No matching deviceType, subType or ui.model',
        capabilities=(),
    ),
}


def get_category_info(category: DeviceCategory) -> CategoryInfo:
    return _CATEGORY_INFO.get(category, _CATEGORY_INFO[DeviceCategory.UNKNOWN])


# Main mapping: deviceTypeId -> Category
_DEVICE_TYPE_MAP: Dict[int, DeviceCategory] = {
    1: DeviceCategory.SIMPLE_ZIGBEE_LIGHT,
    34: DeviceCategory.ZIGBEE_CURTAIN,
    35: DeviceCategory.ZIGBEE_ROLLING_SHUTTER,
    36: DeviceCategory.FAN_COIL_AC,
    81: DeviceCategory.FAN_COIL_AC,
    114: DeviceCategory.MIXPAD_GATEWAY,
    128: DeviceCategory.MUSIC_HOST,
    135: DeviceCategory.MIX_SWITCH,
    136: DeviceCategory.MIX_SWITCH,
    137: DeviceCategory.MIX_SWITCH,
    143: DeviceCategory.MIX_SWITCH,
    501: DeviceCategory.MONO_LIGHT,
    503: DeviceCategory.CCT_LIGHT,
    518: DeviceCategory.BACH_SWITCH,
    107: DeviceCategory.DOOR_LOCK,
    522: DeviceCategory.DOOR_LOCK,
    45: DeviceCategory.MIXPAD_GATEWAY,  # Zigbee Mini Hub (Hub100), hidden
    14: DeviceCategory.WIFI_CAMERA,
    162: DeviceCategory.CAMERA_NVR,
    10086: DeviceCategory.LIGHT_VIRTUAL_GROUP,
    38: DeviceCategory.DIM_COLOR_LIGHT,
    52: DeviceCategory.CLOTHES_HORSE,
    43: DeviceCategory.SIMPLE_ZIGBEE_LIGHT,   # COCO smart power strip (order=on/off format, same as light control)
    26: DeviceCategory.MOTION_SENSOR,
    27: DeviceCategory.SMOKE_SENSOR,
    25: DeviceCategory.GAS_SENSOR,
    56: DeviceCategory.EMERGENCY_BUTTON,
    54: DeviceCategory.WATER_LEAK_SENSOR,
    150: DeviceCategory.SMART_REMOTE,
    511: DeviceCategory.MIXPAD_4WAY_BASE,
    502: DeviceCategory.DIMMABLE_LIGHT,
    46: DeviceCategory.DOOR_WINDOW_SENSOR,
    516: DeviceCategory.VENTILATION_SYSTEM,
    22: DeviceCategory.TEMP_HUMIDITY_SENSOR,
    23: DeviceCategory.TEMP_HUMIDITY_SENSOR,
}

_UI_MODEL_MAP: Dict[str, DeviceCategory] = {
    "lightStd": DeviceCategory.MONO_LIGHT,
    "colorTempLightStd": DeviceCategory.CCT_LIGHT_STRIP,
    "MIXSWITCH": DeviceCategory.MIX_SWITCH,
    "orb_wifi_clotheshorse_ultimate": DeviceCategory.CLOTHES_HORSE,
}

_CLASS_ID_MAP: Dict[int, DeviceCategory] = {
    426: DeviceCategory.MONO_LIGHT,
    429: DeviceCategory.MONO_LIGHT,
    436: DeviceCategory.CCT_LIGHT_STRIP,
    424: DeviceCategory.BACH_SWITCH,
    1107: DeviceCategory.BACH_SWITCH,
    462: DeviceCategory.DOOR_LOCK,
    463: DeviceCategory.DOOR_LOCK,
    1114: DeviceCategory.VENTILATION_SYSTEM,
}

# P20 records are not consistent across cloud inventory endpoints: some omit
# deviceType/classId even though the exact official model identity is present.
# These two catalogue models have verified read-only door-lock semantics.
_VERIFIED_DOOR_LOCK_MODELS = frozenset({
    "112edf14194543ed90148ce3a447ad33",  # P20 / Z1
    "dec7d494f0454110805c0d5f7e7cba73",  # P20 / Z2
})

# Device categories that should not be displayed or added to HA
HIDDEN_CATEGORIES: set = {
    DeviceCategory.MIXPAD_GATEWAY,      # deviceTypeId=114
    DeviceCategory.MIX_SWITCH,          # deviceTypeId=135/136/137/143
    DeviceCategory.BACH_SWITCH,         # deviceTypeId=518
    DeviceCategory.SMART_REMOTE,        # deviceTypeId=150
    DeviceCategory.MIXPAD_4WAY_BASE,    # deviceTypeId=511
}

# Maintainers verify devices listed in the README support table; omission from this set does not mean incompatibility,
# it only means no capability is currently claimed as verified on physical devices.
HARDWARE_VERIFIED_CATEGORIES = frozenset({
    DeviceCategory.SIMPLE_ZIGBEE_LIGHT,
    DeviceCategory.ZIGBEE_CURTAIN,
    DeviceCategory.FAN_COIL_AC,
    DeviceCategory.MIX_SWITCH,
    DeviceCategory.MONO_LIGHT,
    DeviceCategory.CCT_LIGHT_STRIP,
    DeviceCategory.CCT_LIGHT,
    DeviceCategory.BACH_SWITCH,
    DeviceCategory.DOOR_LOCK,
    DeviceCategory.DIM_COLOR_LIGHT,
    DeviceCategory.LEGACY_LIGHT,
    DeviceCategory.CLOTHES_HORSE,
    DeviceCategory.MOTION_SENSOR,
    DeviceCategory.SMOKE_SENSOR,
    DeviceCategory.EMERGENCY_BUTTON,
    DeviceCategory.WATER_LEAK_SENSOR,
    DeviceCategory.GAS_SENSOR,
    DeviceCategory.DIMMABLE_LIGHT,
    DeviceCategory.ZIGBEE_DIMMABLE_LIGHT,
    DeviceCategory.TEMP_HUMIDITY_SENSOR,
    DeviceCategory.DOOR_WINDOW_SENSOR,
    DeviceCategory.FAST_MOVE_DIM_COLOR_LIGHT,
    DeviceCategory.VENTILATION_SYSTEM,
    DeviceCategory.ZIGBEE_ROLLING_SHUTTER,
    DeviceCategory.FLOOR_HEATING,
    DeviceCategory.LEGACY_FLOOR_HEATING,
    DeviceCategory.DREAM_CURTAIN,
    DeviceCategory.RELAY_CURTAIN,
})


def is_hidden_category(category: DeviceCategory) -> bool:
    """Determine whether this category should be hidden (not displayed or added to HA)."""
    return category in HIDDEN_CATEGORIES


def get_device_profile(device: Dict[str, Any]) -> DeviceProfile:
    """Resolve a device without granting control to unknown categories."""
    category = classify_device(device)
    known_model = identify_known_device(device)
    if category in {DeviceCategory.UNKNOWN, DeviceCategory.OTHER} and known_model:
        category = DeviceCategory.OTHER
        info = CategoryInfo(
            category=category,
            label=known_model.display_name,
            description=(
                "Recognized model; control protocol not yet verified"
                + (
                    f" (internal model: {', '.join(known_model.internal_models)})"
                    if known_model.internal_models
                    else ""
                )
            ),
            capabilities=(),
        )
    else:
        info = get_category_info(category)
    hardware_verified = category in HARDWARE_VERIFIED_CATEGORIES
    return DeviceProfile(
        category=category,
        info=info,
        hardware_verified=hardware_verified,
        # A catalogue/category match is identification evidence, not control
        # evidence.  Only hardware-verified profiles may leave registration-only.
        registration_only=(
            not hardware_verified
            or category == DeviceCategory.LIGHT_VIRTUAL_GROUP
        ),
    )


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_device(device: Dict[str, Any]) -> DeviceCategory:
    """Determine the category from fields in the device dict.

    Priority:
    1. Main deviceType mapping (type=300 requires further distinction by subType)
    2. Special combination: deviceType=0 and subDeviceType=-2 is a Zigbee dimmable light
    3. ui.model fallback
    4. classId / subDeviceType fallback
    5. Return UNKNOWN
    """
    if not isinstance(device, dict):
        return DeviceCategory.UNKNOWN

    raw_type_value = device.get("device_type_raw")
    if raw_type_value is None:
        raw_type_value = device.get("deviceType")
    raw_sub_value = device.get("sub_device_type")
    if raw_sub_value is None:
        raw_sub_value = device.get("subDeviceType")
    device_type_raw = _safe_int(raw_type_value)
    sub_type = _safe_int(raw_sub_value)

    model = device.get("model")
    if (
        isinstance(model, str)
        and model.strip() in _VERIFIED_DOOR_LOCK_MODELS
    ):
        return DeviceCategory.DOOR_LOCK

    # Physical-device profiles take precedence over bare deviceType mappings.
    if device_type_raw == 0:
        return DeviceCategory.ZIGBEE_DIMMABLE_LIGHT
    if device_type_raw == 102:
        return DeviceCategory.LEGACY_LIGHT
    if device_type_raw == 112:
        ui = device.get("ui")
        ui_model = device.get("ui_model")
        if not ui_model and isinstance(ui, dict):
            ui_model = ui.get("model")
        if sub_type == -2 and (
            ui_model == "orb_floorheat"
            or device.get("model") == "2ac836760da10748856a7e4eafb91efa"
        ):
            return DeviceCategory.LEGACY_FLOOR_HEATING
        return DeviceCategory.UNKNOWN
    if device_type_raw == 300:
        if sub_type == 481:
            return DeviceCategory.FLOOR_HEATING
        if sub_type == 491:
            return DeviceCategory.TEMP_HUMIDITY_SENSOR
        return DeviceCategory.UNKNOWN
    if device_type_raw == 503:
        if sub_type == 436:
            return DeviceCategory.CCT_LIGHT_STRIP
        if sub_type == 461:
            return DeviceCategory.CCT_LIGHT
        return DeviceCategory.UNKNOWN
    if device_type_raw == 107:
        return DeviceCategory.DOOR_LOCK
    if device_type_raw == 522:
        return DeviceCategory.DOOR_LOCK
    if device_type_raw == 501:
        return (
            DeviceCategory.MONO_LIGHT
            if sub_type in (426, 429)
            else DeviceCategory.UNKNOWN
        )
    if device_type_raw == 502:
        return (
            DeviceCategory.DIMMABLE_LIGHT
            if sub_type == 431
            else DeviceCategory.UNKNOWN
        )
    if device_type_raw == 506 and sub_type == 408:
        return DeviceCategory.DREAM_CURTAIN
    if device_type_raw == 42 and sub_type == -2:
        return DeviceCategory.RELAY_CURTAIN

    if device_type_raw is not None and device_type_raw in _DEVICE_TYPE_MAP:
        # Use the fast move protocol for deviceType=38 and subDeviceType=6.
        if device_type_raw == 38 and sub_type == 6:
            return DeviceCategory.FAST_MOVE_DIM_COLOR_LIGHT
        return _DEVICE_TYPE_MAP[device_type_raw]

    # Special case: statusType=2 and subDeviceType=6 is a Fast Move dimmable color-temperature light.
    status_type = _safe_int(device.get("status_type") or device.get("statusType"))
    if status_type == 2 and sub_type == 6:
        return DeviceCategory.FAST_MOVE_DIM_COLOR_LIGHT

    ui_model = device.get("ui_model") or device.get("ui", {}).get("model") if isinstance(device.get("ui"), dict) else device.get("ui_model")
    if isinstance(ui_model, str) and ui_model in _UI_MODEL_MAP:
        return _UI_MODEL_MAP[ui_model]

    raw_class_id = device.get("class_id")
    if raw_class_id is None:
        raw_class_id = device.get("classId")
    class_id = _safe_int(raw_class_id)
    if class_id is not None and class_id in _CLASS_ID_MAP:
        return _CLASS_ID_MAP[class_id]

    # subDeviceType is not classId. Using it as a cross-deviceType fallback would misclassify underfloor heating, gateways,
    # and many motion sensor records with subType=-2 as dimmable lights.
    return (
        DeviceCategory.OTHER
        if identify_known_device(device) is not None
        else DeviceCategory.UNKNOWN
    )
