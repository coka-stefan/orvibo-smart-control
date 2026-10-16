"""Diagnostics support for orvibo_smart_control.

在 HA 设备页面 → 三个点 → 诊断信息 中查看原始数据。
包含：设备列表、状态、最近 50 条实时协议推送记录。
"""

from __future__ import annotations
import time
from typing import Any
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN
from .camera_metadata import camera_diagnostics
from .device_types import DeviceCategory, get_device_profile
from .redact import redact_packet


def _redact_device_rows(rows: dict[str, Any], salt: bytes) -> dict[str, Any]:
    """Keep every device; apply packet size bounds within each device instead."""
    result: dict[str, Any] = {}
    for device_id, row in rows.items():
        # Single-row wrappers retain the same identifier fingerprints and depth
        # bounds, without treating a whole home's inventory as a 50-item packet.
        result.update(redact_packet({device_id: row}, salt, strict=False))
    return result


def _lock_diagnostics(device: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Expose the source data needed to distinguish missing battery properties."""
    return {
        "sub_device_type": device.get("sub_device_type"),
        "class_id": device.get("class_id"),
        "status_type": device.get("status_type"),
        "inventory_values": {
            f"value{index}": device.get(f"value{index}") for index in range(1, 5)
        },
        "state_values": {
            key: state[key]
            for index in range(1, 5)
            for key in (f"raw_value{index}", f"value{index}")
            if key in state
        },
        # Inventory and live pushes can differ; keep both sources for comparison.
        "device_properties": device.get("properties") or {},
        "state_properties": state.get("properties") or {},
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """返回配置条目的诊断信息。"""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not coordinator:
        return {"error": "coordinator not found"}

    now = time.time()
    salt = getattr(coordinator, "_redaction_salt", b"") or b"orvibo_smart_control"

    # 整理设备列表
    devices_raw = {}
    for dev_id, dev in coordinator.devices.items():
        profile = get_device_profile(dev)
        devices_raw[dev_id] = {
            "device_name": dev.get("device_name"),
            "device_type": dev.get("device_type"),
            "device_type_raw": dev.get("device_type_raw"),
            "model": dev.get("model"),
            "recognized_as": profile.info.label,
            "category": profile.category.value,
            "hardware_verified": profile.hardware_verified,
            "registration_only": profile.registration_only,
            "uid": dev.get("uid"),
            "online": dev.get("online"),
            **camera_diagnostics(dev),
        }
        if profile.category == DeviceCategory.DOOR_LOCK:
            devices_raw[dev_id]["lock_diagnostics"] = _lock_diagnostics(
                dev, coordinator.device_states.get(dev_id, {})
            )

    # 整理当前状态
    states_raw = {}
    for dev_id, st in coordinator.device_states.items():
        states_raw[dev_id] = dict(st)
        # 去掉 over-length 属性
        states_raw[dev_id].pop("properties", None)

    # 整理最近50条cmd42推送
    cmd42_entries = []
    for entry_ in getattr(coordinator, "_cmd42_log", [])[-50:]:
        cmd42_entries.append({
            "ago_s": round(now - entry_["ts"], 1) if entry_.get("ts") else None,
            "device_id": entry_["device_id"],
            "raw": redact_packet(entry_.get("raw", {}), salt, strict=False),
        })

    info = {
        "device_count": len(devices_raw),
        "devices": _redact_device_rows(devices_raw, salt),
        "states": _redact_device_rows(states_raw, salt),
        "recent_cmd42_push": cmd42_entries,
    }
    return info


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """返回某个设备专有的诊断信息。"""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not coordinator:
        return {"error": "coordinator not found"}

    # 从 device identifier 反查 device_id
    device_id = None
    for domain, identifier in device.identifiers:
        if domain == DOMAIN:
            device_id = identifier
            break

    now = time.time()
    salt = getattr(coordinator, "_redaction_salt", b"") or b"orvibo_smart_control"

    result: dict[str, Any] = {}

    # 设备原始信息
    if device_id and device_id in coordinator.devices:
        result["device_info"] = redact_packet(
            coordinator.devices[device_id], salt, strict=False
        )
    else:
        result["device_info"] = {"error": f"device {device_id} not found in coordinator"}

    # 当前状态
    if device_id and device_id in coordinator.device_states:
        result["current_state"] = redact_packet(
            dict(coordinator.device_states[device_id]), salt, strict=False
        )
        result["current_state"].pop("properties", None)
    else:
        result["current_state"] = None

    if device_id and device_id in coordinator.devices:
        raw_device = coordinator.devices[device_id]
        if get_device_profile(raw_device).category == DeviceCategory.DOOR_LOCK:
            result["lock_diagnostics"] = redact_packet(
                _lock_diagnostics(
                    raw_device, coordinator.device_states.get(device_id, {})
                ),
                salt,
                strict=False,
            )

    # 该设备的最近cmd42推送
    device_cmd42 = []
    for entry_ in getattr(coordinator, "_cmd42_log", []):
        if entry_["device_id"] == device_id or entry_.get("raw", {}).get("uid") == device_id:
            device_cmd42.append({
                "ago_s": round(now - entry_["ts"], 1) if entry_.get("ts") else None,
                "raw": redact_packet(entry_.get("raw", {}), salt, strict=False),
            })
    result["recent_cmd42_push"] = device_cmd42[-20:]

    return result
