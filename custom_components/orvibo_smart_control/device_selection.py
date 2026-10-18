"""Runtime device grouping helpers for the config and options flows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .selection import CONF_SELECTED_DEVICE_IDS

DEVICE_GROUP_FIELD_PREFIX = "device_group_"
DEVICE_GROUP_ALL_FIELD_PREFIX = "device_group_all_"
DEVICE_GROUP_ALL_VALUE_PREFIX = "__all__:"


@dataclass(frozen=True)
class DeviceSelectionGroup:
    """A group generated from the devices returned by HomeMate."""

    key: str
    label: str
    devices: tuple[Mapping[str, Any], ...]

    @property
    def device_field(self) -> str:
        return f"{DEVICE_GROUP_FIELD_PREFIX}{self.key}"

    @property
    def all_field(self) -> str:
        """Compatibility key used by the previous two-control form."""

        return f"{DEVICE_GROUP_FIELD_PREFIX}{self.key}_all"

    @property
    def legacy_all_field(self) -> str:
        return f"{DEVICE_GROUP_ALL_FIELD_PREFIX}{self.key}"

    @property
    def all_value(self) -> str:
        """Sentinel selected by the single-control form for a whole group."""

        return f"{DEVICE_GROUP_ALL_VALUE_PREFIX}{self.key}"

    @property
    def device_ids(self) -> tuple[str, ...]:
        return tuple(str(device.get("device_id") or "") for device in self.devices)


# Name matching is intentionally a small, editable heuristic.  It lets real
# device names improve the UI without coupling config-flow rendering to the
# integration's controllability enum.
_NAME_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # Chinese keywords are retained to recognize vendor-localized names in incoming device records.
    ("lights", 'Lights', ("灯", "灯带", "射灯", "筒灯", "照明")),
    ("switches", 'Switches', ("开关", "面板", "插座")),
    ("curtains", 'Curtains', ("窗帘", "卷帘", "纱帘")),
    ("clothes_horse", 'Clothes dryers', ("晾衣", "晾衣架")),
    ("climate", 'Heating and cooling', ("空调", "地暖", "暖气", "风机盘管")),
    ("ventilation", 'Ventilation', ("新风", "通风")),
    (
        "sensors",
        'Sensors',
        ("传感器", "温湿度", "人体", "烟雾", "水浸", "燃气", "门磁", "门窗"),
    ),
    ("locks", 'Locks', ("门锁", "智能锁", "指纹锁")),
    ("cameras", 'Cameras', ("摄像头", "相机", "监控")),
)

# Fallback for records whose display name is generic or empty.
_RAW_TYPE_GROUPS: dict[int, tuple[str, str]] = {
    0: ("lights", 'Lights'),
    1: ("lights", 'Lights'),
    14: ("cameras", 'Cameras'),
    22: ("sensors", 'Sensors'),
    23: ("sensors", 'Sensors'),
    25: ("sensors", 'Sensors'),
    26: ("sensors", 'Sensors'),
    27: ("sensors", 'Sensors'),
    34: ("curtains", 'Curtains'),
    35: ("curtains", 'Curtains'),
    36: ("climate", 'Heating and cooling'),
    38: ("lights", 'Lights'),
    42: ("curtains", 'Curtains'),
    43: ("lights", 'Lights'),
    46: ("sensors", 'Sensors'),
    52: ("clothes_horse", 'Clothes dryers'),
    54: ("sensors", 'Sensors'),
    56: ("sensors", 'Sensors'),
    102: ("lights", 'Lights'),
    112: ("climate", 'Heating and cooling'),
    114: ("other", 'Other devices'),
    128: ("other", 'Other devices'),
    135: ("switches", 'Switches'),
    136: ("switches", 'Switches'),
    137: ("switches", 'Switches'),
    143: ("switches", 'Switches'),
    150: ("other", 'Other devices'),
    162: ("cameras", 'Cameras'),
    501: ("lights", 'Lights'),
    502: ("lights", 'Lights'),
    503: ("lights", 'Lights'),
    506: ("curtains", 'Curtains'),
    511: ("switches", 'Switches'),
    516: ("ventilation", 'Ventilation'),
    518: ("switches", 'Switches'),
    522: ("locks", 'Locks'),
    10086: ("lights", 'Lights'),
}

_TYPE_NAME_GROUPS: dict[str, tuple[str, str]] = {
    "light": ("lights", 'Lights'),
    "switch": ("switches", 'Switches'),
    "cover": ("curtains", 'Curtains'),
    "climate": ("climate", 'Heating and cooling'),
    "fan": ("climate", 'Heating and cooling'),
    "sensor": ("sensors", 'Sensors'),
    "binary_sensor": ("sensors", 'Sensors'),
    "lock": ("locks", 'Locks'),
    "camera": ("cameras", 'Cameras'),
}


def _text(value: object) -> str:
    return str(value or "").strip().lower()


def _raw_type(device: Mapping[str, Any]) -> int | None:
    value = device.get("device_type_raw")
    if value is None:
        value = device.get("deviceType")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sub_type(device: Mapping[str, Any]) -> int | None:
    value = device.get("sub_device_type")
    if value is None:
        value = device.get("subDeviceType")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def infer_device_group(device: Mapping[str, Any]) -> tuple[str, str]:
    """Infer a group key and display label from one device record."""

    # Confirmed camera types take precedence over user-defined name keywords.
    raw_type = _raw_type(device)
    if raw_type in (14, 162):
        return "cameras", 'Cameras'

    searchable = " ".join(
        _text(device.get(field))
        for field in ("device_name", "class_name", "model", "ui_model", "device_type")
    )
    for key, label, keywords in _NAME_GROUPS:
        if any(keyword in searchable for keyword in keywords):
            return key, label

    if raw_type == 300:
        sub_type = _sub_type(device)
        if sub_type == 481:
            return "climate", 'Heating and cooling'
        if sub_type == 491:
            return "sensors", 'Sensors'
    raw_group = _RAW_TYPE_GROUPS.get(raw_type)
    if raw_group is not None:
        return raw_group

    type_name = _text(device.get("device_type"))
    named_group = _TYPE_NAME_GROUPS.get(type_name)
    if named_group is not None:
        return named_group
    return "other", 'Other devices'


def device_selection_groups(
    devices: Iterable[Mapping[str, Any]],
) -> tuple[DeviceSelectionGroup, ...]:
    """Build dynamic groups, preserving the order of the returned devices."""

    buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    labels: dict[str, str] = {}
    for device in devices:
        key, label = infer_device_group(device)
        buckets[key].append(device)
        labels.setdefault(key, label)
    return tuple(
        DeviceSelectionGroup(key, labels[key], tuple(values))
        for key, values in buckets.items()
    )


def grouped_devices(
    devices: Iterable[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    """Compatibility view of :func:`device_selection_groups`."""

    return {
        group.key: list(group.devices)
        for group in device_selection_groups(devices)
    }


def merge_grouped_selection(
    user_input: Mapping[str, Any],
    devices: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Merge dynamic category fields into the persisted flat ID list."""

    ordered_devices = list(devices)
    available = {str(device.get("device_id") or "") for device in ordered_devices}
    if CONF_SELECTED_DEVICE_IDS in user_input:
        raw_requested = user_input.get(CONF_SELECTED_DEVICE_IDS, [])
        if not isinstance(raw_requested, (list, tuple, set)):
            return []
        requested = {str(value) for value in raw_requested}
    else:
        requested: set[str] = set()
        for group in device_selection_groups(ordered_devices):
            values = user_input.get(group.device_field, [])
            normalized = (
                {str(value) for value in values}
                if isinstance(values, (list, tuple, set))
                else set()
            )
            if (
                group.all_value in normalized
                or bool(user_input.get(group.all_field, False))
                or bool(user_input.get(group.legacy_all_field, False))
            ):
                requested.update(group.device_ids)
                continue
            requested.update(normalized)

    requested &= available
    return [
        str(device.get("device_id") or "")
        for device in ordered_devices
        if str(device.get("device_id") or "") in requested
    ]


__all__ = [
    "DeviceSelectionGroup",
    "device_selection_groups",
    "grouped_devices",
    "infer_device_group",
    "merge_grouped_selection",
]
