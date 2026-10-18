"""Declare Home Assistant platforms and transport policy for each device.

Profiles identify device semantics; this module adds the runtime decisions used
by entity registration, LAN push filtering, and control transport selection.
Unknown devices remain registration-only and never receive inferred commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional

from .device_types import DeviceCategory, get_device_profile

# HA platform names (aligned with __init__.PLATFORMS)
PLATFORM_LIGHT = "light"
PLATFORM_COVER = "cover"
PLATFORM_CLIMATE = "climate"
PLATFORM_FAN = "fan"
PLATFORM_SENSOR = "sensor"
PLATFORM_BINARY_SENSOR = "binary_sensor"
PLATFORM_CAMERA = "camera"
PLATFORM_SWITCH = "switch"


class ControlChannel(str, Enum):
    """Control channels available for a device."""

    LAN = "lan"  # Direct gateway connection (prefer local)
    SSL = "ssl"  # Persistent cloud connection


class TransportMode(str, Enum):
    """Select which realtime/control transports may be used."""

    AUTO = "auto"
    LAN_ONLY = "lan_only"
    CLOUD_ONLY = "cloud_only"


class TransportPath(str, Enum):
    """User-facing transport policy for one device in the active mode."""

    LAN = "lan"
    CLOUD = "cloud"
    LAN_CLOUD = "lan_cloud"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DeviceCapability:
    """Merged capability declaration for a device category."""

    category: DeviceCategory
    platforms: FrozenSet[str]
    channels: FrozenSet[ControlChannel]
    status_only: bool = False
    cloud_only: bool = False
    hardware_verified: bool = False

    @property
    def controllable(self) -> bool:
        return bool(self.channels)


# ---- Type-level transport and read-only policy ----

# Device types that LAN can control directly (gateway forwarding; writable types from LAN profiles)
_LAN_CONTROLLABLE_TYPES = frozenset(
    {0, 1, 34, 35, 36, 38, 81, 102, 501, 502, 503, 516}
)

# Type-level read-only marker: only for the WiFi lock (107), which the cloud implementation does not map to a category.
# Other read-only types (sensors and type 522 locks) are determined by category in _STATUS_ONLY_CATEGORIES,
# Type 300 subtypes follow cloud observations: 481 underfloor heating is cloud-controllable; 491 temperature/humidity is read-only.
_STATUS_ONLY_TYPES = frozenset({107})

# This integration uses a cloud-only path (ADR-4); cameras use cloud inventory metadata only,
# with no MixPad LAN or SDK controls; this does not determine video stream transport.
_CLOUD_ONLY_TYPES = frozenset({14, 52, 107, 162, 522})

# Read-only categories (no device control channel; state updates continue)
_STATUS_ONLY_CATEGORIES = frozenset(
    {
        DeviceCategory.MOTION_SENSOR,
        DeviceCategory.TEMP_HUMIDITY_SENSOR,
        DeviceCategory.DOOR_WINDOW_SENSOR,
        DeviceCategory.SMOKE_SENSOR,
        DeviceCategory.EMERGENCY_BUTTON,
        DeviceCategory.WATER_LEAK_SENSOR,
        DeviceCategory.GAS_SENSOR,
        DeviceCategory.DOOR_LOCK,
        DeviceCategory.WIFI_CAMERA,
        DeviceCategory.CAMERA_NVR,
    }
)


# ---- Category -> Home Assistant platform ----

_CATEGORY_PLATFORMS: Dict[DeviceCategory, FrozenSet[str]] = {
    DeviceCategory.SIMPLE_ZIGBEE_LIGHT: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.MONO_LIGHT: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.LEGACY_LIGHT: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.DIM_COLOR_LIGHT: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.DIMMABLE_LIGHT: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.CCT_LIGHT: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.CCT_LIGHT_STRIP: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.ZIGBEE_DIMMABLE_LIGHT: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.FAST_MOVE_DIM_COLOR_LIGHT: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.LIGHT_VIRTUAL_GROUP: frozenset({PLATFORM_LIGHT}),
    DeviceCategory.ZIGBEE_CURTAIN: frozenset({PLATFORM_COVER}),
    DeviceCategory.ZIGBEE_ROLLING_SHUTTER: frozenset({PLATFORM_COVER}),
    DeviceCategory.LEGACY_CURTAIN: frozenset({PLATFORM_COVER}),
    DeviceCategory.DREAM_CURTAIN: frozenset({PLATFORM_COVER}),
    DeviceCategory.FAN_COIL_AC: frozenset({PLATFORM_CLIMATE}),
    DeviceCategory.FLOOR_HEATING: frozenset({PLATFORM_CLIMATE}),
    DeviceCategory.LEGACY_FLOOR_HEATING: frozenset({PLATFORM_CLIMATE}),
    DeviceCategory.VENTILATION_SYSTEM: frozenset({PLATFORM_FAN}),
    DeviceCategory.MOTION_SENSOR: frozenset(
        {PLATFORM_SENSOR, PLATFORM_BINARY_SENSOR}
    ),
    DeviceCategory.TEMP_HUMIDITY_SENSOR: frozenset({PLATFORM_SENSOR}),
    DeviceCategory.DOOR_WINDOW_SENSOR: frozenset(
        {PLATFORM_SENSOR, PLATFORM_BINARY_SENSOR}
    ),
    DeviceCategory.SMOKE_SENSOR: frozenset(
        {PLATFORM_SENSOR, PLATFORM_BINARY_SENSOR}
    ),
    DeviceCategory.EMERGENCY_BUTTON: frozenset(
        {PLATFORM_SENSOR, PLATFORM_BINARY_SENSOR}
    ),
    DeviceCategory.WATER_LEAK_SENSOR: frozenset(
        {PLATFORM_SENSOR, PLATFORM_BINARY_SENSOR}
    ),
    DeviceCategory.GAS_SENSOR: frozenset(
        {PLATFORM_SENSOR, PLATFORM_BINARY_SENSOR}
    ),
    DeviceCategory.DOOR_LOCK: frozenset(
        {PLATFORM_SENSOR, PLATFORM_BINARY_SENSOR, PLATFORM_CAMERA}
    ),
    DeviceCategory.CLOTHES_HORSE: frozenset({PLATFORM_SENSOR}),
    DeviceCategory.WIFI_CAMERA: frozenset({PLATFORM_SENSOR}),
    DeviceCategory.CAMERA_NVR: frozenset({PLATFORM_SENSOR}),
    DeviceCategory.MIX_SWITCH: frozenset({PLATFORM_SWITCH}),
    DeviceCategory.BACH_SWITCH: frozenset({PLATFORM_SWITCH}),
}


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _device_type_key(device: Any) -> int:
    """Extract normalized deviceType from a device dict, defaulting to 0."""
    if not isinstance(device, dict):
        return 0
    raw = device.get("device_type_raw")
    if raw is None:
        raw = device.get("deviceType")
    return _safe_int(raw) or 0


def capability_for(device: Any) -> DeviceCapability:
    """Resolve merged capabilities for one device without performing I/O."""
    profile = get_device_profile(device)
    category = profile.category
    device_type = _device_type_key(device)

    status_only = (
        device_type in _STATUS_ONLY_TYPES
        or category in _STATUS_ONLY_CATEGORIES
    )
    cloud_only = device_type in _CLOUD_ONLY_TYPES

    if cloud_only:
        # cloud_only means state and rich features use the cloud; channels describe device-control paths only.
        # Read-only devices such as locks have no control channel; clothes dryers (52) have cloud control commands.
        channels = (
            frozenset({ControlChannel.SSL})
            if not status_only
            else frozenset()
        )
    elif status_only:
        channels = frozenset()
    elif profile.registration_only:
        # Unknown or unverified categories are displayed without sending controls (the project default conservative policy).
        channels = frozenset()
    elif device_type in _LAN_CONTROLLABLE_TYPES:
        # Prefer local: when LAN and cloud are both supported, routing uses the mode and reachability.
        channels = frozenset({ControlChannel.LAN, ControlChannel.SSL})
    else:
        channels = frozenset({ControlChannel.SSL})

    return DeviceCapability(
        category=category,
        platforms=_CATEGORY_PLATFORMS.get(category, frozenset()),
        channels=channels,
        status_only=status_only,
        cloud_only=cloud_only,
        hardware_verified=profile.hardware_verified,
    )


def capability_for_type(
    device_type: int,
    sub_type: Optional[int] = None,
) -> DeviceCapability:
    """Resolve capabilities by type for tests and diagnostics; use capability_for at runtime."""
    return capability_for(
        {
            "device_type_raw": device_type,
            "sub_device_type": sub_type,
        }
    )


def lan_state_allowed(
    device: Any,
    transport_mode: TransportMode = TransportMode.AUTO,
) -> bool:
    """Return whether a LAN push may update this device in the active mode."""

    return (
        transport_mode != TransportMode.CLOUD_ONLY
        and not capability_for(device).cloud_only
    )


def transport_path_for(
    device: Any,
    transport_mode: TransportMode = TransportMode.AUTO,
) -> TransportPath:
    """Describe the configured runtime path without probing network state."""

    capability = capability_for(device)
    if transport_mode == TransportMode.CLOUD_ONLY:
        return TransportPath.CLOUD

    if transport_mode == TransportMode.LAN_ONLY:
        if capability.cloud_only:
            return TransportPath.UNAVAILABLE
        if capability.status_only or ControlChannel.LAN in capability.channels:
            return TransportPath.LAN
        return TransportPath.UNAVAILABLE

    if capability.cloud_only:
        return TransportPath.CLOUD
    if capability.status_only or ControlChannel.LAN in capability.channels:
        return TransportPath.LAN_CLOUD
    if ControlChannel.SSL in capability.channels:
        return TransportPath.CLOUD
    return TransportPath.UNAVAILABLE
