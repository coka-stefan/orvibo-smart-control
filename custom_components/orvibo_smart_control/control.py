"""Pure command mapping and Orvibo device control command builders.

No external dependencies beyond the Python standard library; can be tested without Home Assistant.

Includes:
- OrviboControlCommand dataclass for command parameters
- Control command builders for different device types
- State parsers for values such as value1 -> switch state
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


# ---- Color temperature constants ----

KELVIN_MIN = 2700
KELVIN_MAX = 6500
MIRED_MIN = 154  # 6500K
MIRED_MAX = 370  # 2700K


def kelvin_to_mired(kelvin: int) -> int:
    """Convert Kelvin color temperature to mireds."""
    return round(1_000_000 / max(1, int(kelvin)))


def mired_to_kelvin(mired: int) -> int | None:
    """Convert mireds to Kelvin, returning None for invalid values."""
    if mired <= 0:
        return None
    k = round(1_000_000 / mired)
    if k < KELVIN_MIN:
        return KELVIN_MIN
    if k > KELVIN_MAX:
        return KELVIN_MAX
    return k


def clamp_brightness(value: int, max_val: int = 255) -> int:
    """Clamp brightness to its valid range."""
    return max(1, min(max_val, int(value)))


# ---- Control command data model ----

@dataclass(frozen=True, slots=True)
class OrviboControlCommand:
    """Container for the payload parameters of a cmd=15 control command."""

    order: str
    value1: int = 0
    value2: int = 0
    value3: int = 0
    value4: int = 0
    properties: Mapping[str, Any] | None = None


# ---- Curtain control ----

def curtain_position_command(ha_position: int) -> OrviboControlCommand:
    """Curtain position command, with an opening percentage from 0 to 100."""
    position = max(0, min(100, int(ha_position)))
    return OrviboControlCommand("open", position)


def curtain_stop_command() -> OrviboControlCommand:
    """Curtain stop command."""
    return OrviboControlCommand("stop", 0)


def curtain_position_from_orvibo(value: int | None) -> int | None:
    """Convert an Orvibo curtain position value to the HA standard (0-100)."""
    if value is None or not 0 <= value <= 100:
        return None
    return value


# ---- Switch control (set property format) ----

def switch_power_command(is_on: bool) -> OrviboControlCommand:
    """Switch control (set property format, type=501/135/136/502)."""
    return OrviboControlCommand(
        "set property",
        0, 0, 0, 0,
        properties={"onoff": {"status": "on" if is_on else "off"}},
    )


def dimmable_light_brightness_command(percent: int) -> OrviboControlCommand:
    """Dimmable light brightness (set property format, type=502)."""
    bri = max(0, min(100, int(percent)))
    return OrviboControlCommand(
        "set property",
        0, 0, 0, 0,
        properties={"brightness": {"percent": bri}},
    )


# ---- Color temperature light control (set property format, type=503) ----

def cct_light_power_command(is_on: bool) -> OrviboControlCommand:
    """Color temperature light switch (set property format, type=503)."""
    return OrviboControlCommand(
        "set property",
        0, 0, 0, 0,
        properties={"onoff": {"status": "on" if is_on else "off"}},
    )


def cct_light_brightness_command(percent: int) -> OrviboControlCommand:
    """Color temperature light brightness (set property format, type=503)."""
    bri = max(0, min(100, int(percent)))
    return OrviboControlCommand(
        "set property",
        0, 0, 0, 0,
        properties={"brightness": {"percent": bri}},
    )


def cct_light_colortemp_command(kelvin: int) -> OrviboControlCommand:
    """Color temperature light color temperature (set property format, type=503)."""
    k = max(KELVIN_MIN, min(KELVIN_MAX, int(kelvin)))
    return OrviboControlCommand(
        "set property",
        0, 0, 0, 0,
        properties={"colorTemp": {"value": k}},
    )


# ---- Light control (order=on/off format, type=1/38/102) ----

def light_power_command(is_on: bool, brightness: int = 0, color_temp_mired: int = 0) -> OrviboControlCommand:
    """Light switch (order=on/off, active-low).

    type=38/102: value1=0 means on, value1=1 means off
    type=1: same as above
    """
    return OrviboControlCommand(
        "on" if is_on else "off",
        0 if is_on else 1,
        brightness,
        color_temp_mired,
    )


def light_brightness_command(brightness: int, color_temp_mired: int = 0) -> OrviboControlCommand:
    """Light brightness (fast move to level format)."""
    return OrviboControlCommand(
        "fast move to level",
        0,
        clamp_brightness(brightness),
        color_temp_mired,
    )


def light_colortemp_command(brightness: int, color_temp_mired: int) -> OrviboControlCommand:
    """Light color temperature (fast color temperature format)."""
    return OrviboControlCommand(
        "fast color temperature",
        0,
        clamp_brightness(brightness),
        color_temp_mired,
    )


def light_full_command(
    is_on: bool, brightness: int, color_temp_mired: int,
) -> OrviboControlCommand:
    """Set all light controls together: switch, brightness, and color temperature."""
    return OrviboControlCommand(
        "on" if is_on else "off",
        0 if is_on else 1,
        clamp_brightness(brightness),
        color_temp_mired,
    )


# ---- Zigbee dimmable light control (type=0, subDeviceType=-2) ----

def zigbee_dimmable_light_power_command(is_on: bool, brightness: int = 255) -> OrviboControlCommand:
    """Zigbee dimmable light switch (on/off + brightness)."""
    return OrviboControlCommand(
        "on" if is_on else "off",
        0 if is_on else 1,
        clamp_brightness(brightness),
    )


def zigbee_dimmable_light_brightness_command(brightness: int) -> OrviboControlCommand:
    """Zigbee dimmable light brightness (move to level format)."""
    return OrviboControlCommand(
        "move to level",
        0,
        clamp_brightness(brightness),
    )


# ---- Fast Move dimmable color temperature light control (type=2, subType=6) ----

def fast_move_light_power_command(
    is_on: bool, brightness: int = 0, colortemp_mired: int = 0,
) -> OrviboControlCommand:
    """Fast Move light switch (on/off + brightness + mireds)."""
    return OrviboControlCommand(
        "on" if is_on else "off",
        0 if is_on else 1,
        clamp_brightness(brightness),
        colortemp_mired,
    )


def fast_move_light_brightness_command(brightness: int, colortemp_mired: int = 0) -> OrviboControlCommand:
    """Fast Move light brightness (fast move to level)."""
    return OrviboControlCommand(
        "fast move to level",
        0,
        clamp_brightness(brightness),
        colortemp_mired,
    )


def fast_move_light_colortemp_command(brightness: int, colortemp_mired: int) -> OrviboControlCommand:
    """Fast Move light color temperature (fast color temperature)."""
    return OrviboControlCommand(
        "fast color temperature",
        0,
        clamp_brightness(brightness),
        colortemp_mired,
    )


# ---- Ventilation control (type=516) ----

def ventilation_command(value1: int) -> OrviboControlCommand:
    """Ventilation system control. value1: 0=slow, 50=stop, 100=fast."""
    return OrviboControlCommand(
        "set property", int(value1),
    )


# ---- Air conditioning control (type=36) ----

def fan_coil_ac_power_command(
    is_on: bool, mode: int = 3, fan_speed: int = 1, temp_value4: int = 0,
) -> OrviboControlCommand:
    """Fan coil AC switch.

    Args:
        is_on: True=on, False=off
        mode: mode code (2=dry, 3=cool, 4=heat, 7=fan only)
        fan_speed: fan speed code (1=low, 2=medium, 3=high)
        temp_value4: encoded temperature (temp*100)<<16
    """
    return OrviboControlCommand(
        "on" if is_on else "off",
        0 if is_on else 1,
        int(mode),
        int(fan_speed),
        int(temp_value4),
    )


def fan_coil_ac_mode_command(mode: int, temp_value4: int) -> OrviboControlCommand:
    """Set the AC mode."""
    return OrviboControlCommand(
        "mode setting",
        0, int(mode),
        value4=int(temp_value4),
    )


def fan_coil_ac_temperature_command(
    mode: int, fan_speed: int, temp_value4: int,
) -> OrviboControlCommand:
    """Set the AC temperature."""
    return OrviboControlCommand(
        "temperature setting",
        0, int(mode), int(fan_speed),
        int(temp_value4),
    )


def fan_coil_ac_fan_speed_command(
    mode: int, fan_speed: int, temp_value4: int,
) -> OrviboControlCommand:
    """Set the AC fan speed."""
    return OrviboControlCommand(
        "wind setting",
        0, int(mode), int(fan_speed),
        int(temp_value4),
    )


def ac_temperature_encode(temperature_celsius: float) -> int:
    """Encode AC temperature in value4 format."""
    return int(temperature_celsius * 100) << 16


AC_MODE_MAP = {"dehumidify": 2, "cool": 3, "heat": 4, "fan_only": 7}
AC_MODE_REVERSE = {2: "dehumidify", 3: "cool", 4: "heat", 7: "fan_only"}
AC_FAN_SPEED_MAP = {"low": 1, "medium": 2, "high": 3}
AC_FAN_SPEED_REVERSE = {1: "low", 2: "medium", 3: "high"}


# ---- State parsing functions ----

def light_is_on_from_value1(value1: int | None) -> bool | None:
    """Infer active-low light switch state from value1.

    type=38/102/503: value1=0->on, value1=1->off
    """
    if value1 not in (0, 1):
        return None
    return value1 == 0


def switch_is_on_from_value1(value1: int | None) -> bool | None:
    """Infer active-high switch state from value1.

    type=135/136: value1=0->off, value1=1->on
    """
    if value1 not in (0, 1):
        return None
    return value1 == 1


def curtain_position_from_value1(value1: int | None) -> int | None:
    """Infer curtain position (0-100) from value1."""
    if value1 is None or not 0 <= value1 <= 100:
        return None
    return int(value1)


def zigbee_dimmable_is_on(value1: int | None, sub_device_type: int | None) -> bool | None:
    """Zigbee dimmable light switch (active-low when subDeviceType=-2)."""
    if value1 not in (0, 1):
        return None
    if sub_device_type == -2:
        return value1 == 0  # active-low
    return value1 == 1  # active-high


def ventilation_fan_speed_from_value1(value1: int | None) -> str | None:
    """Ventilation speed: 0=slow, 50=stop, 100=fast."""
    if value1 is None:
        return None
    return {0: 'Low', 50: 'Off', 100: 'High'}.get(int(value1))


# ---- Build a complete payload, including header fields ----

BUILD_PAYLOAD_FIELDS = [
    "uid", "userName", "deviceId", "groupId",
    "order", "value1", "value2", "value3", "value4",
    "delayTime", "qualityOfService", "defaultResponse", "propertyResponse",
    "cmd", "serial", "clientType", "uniSerial",
    "serverRecord", "ver", "debugInfo",
]

DEFAULT_PAYLOAD_HEADERS = {
    "groupId": "",
    "delayTime": 0,
    "qualityOfService": 1,
    "defaultResponse": 1,
    "propertyResponse": 0,
    "cmd": 15,  # CMD_CONTROL
    "clientType": 1,
    "serverRecord": False,
    "ver": "5.1.3.309",
    "debugInfo": "Android_ZhiJia365_34_5.1.3.309",
}


def build_control_payload(
    cmd: OrviboControlCommand,
    device_id: str,
    device_uid: str,
    username: str,
    serial: int,
    uni_serial: int | None = None,
) -> dict[str, Any]:
    """Assemble an OrviboControlCommand into a complete SSL control payload.

    The result can be passed to packet.py build_packet() or ssl_client._send_packet().
    """
    payload: dict[str, Any] = {
        "uid": device_uid,
        "userName": username,
        "deviceId": device_id,
        "order": cmd.order,
        "value1": cmd.value1,
        "value2": cmd.value2,
        "value3": cmd.value3,
        "value4": cmd.value4,
        "serial": serial,
        "uniSerial": uni_serial if uni_serial is not None else serial,
        **DEFAULT_PAYLOAD_HEADERS,
    }
    if cmd.properties:
        payload["properties"] = cmd.properties
    return payload


def control_payload_to_command(payload: dict[str, Any]) -> OrviboControlCommand:
    """Extract an OrviboControlCommand from a complete control payload."""
    return OrviboControlCommand(
        order=payload.get("order", ""),
        value1=payload.get("value1", 0),
        value2=payload.get("value2", 0),
        value3=payload.get("value3", 0),
        value4=payload.get("value4", 0),
        properties=payload.get("properties"),
    )
