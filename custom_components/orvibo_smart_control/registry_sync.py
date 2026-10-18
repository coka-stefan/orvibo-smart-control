"""Keep Home Assistant registries aligned with the selected ORVIBO devices."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .selection import selected_device_ids


def _orvibo_device_id(device_entry: Any) -> str | None:
    """Return the ORVIBO identifier owned by this integration."""

    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN:
            return str(identifier)
    return None


def sync_selected_device_registries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    devices: Mapping[str, Mapping[str, Any]],
) -> int:
    """Remove registry records for devices excluded by entry options."""

    selected = selected_device_ids(entry.options, devices)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    entry_devices = dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    )
    entry_entities = er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    )
    entities_by_device: dict[str, list[str]] = {}
    for entity in entry_entities:
        if entity.device_id:
            entities_by_device.setdefault(entity.device_id, []).append(
                entity.entity_id
            )

    removed = 0
    for device_entry in entry_devices:
        device_id = _orvibo_device_id(device_entry)
        if device_id is None or device_id in selected:
            continue

        for entity_id in entities_by_device.get(device_entry.id, []):
            entity_registry.async_remove(entity_id)

        if len(device_entry.config_entries) > 1:
            device_registry.async_update_device(
                device_entry.id,
                remove_config_entry_id=entry.entry_id,
            )
        else:
            device_registry.async_remove_device(device_entry.id)
        removed += 1

    return removed


def assign_room_areas(
    hass: HomeAssistant,
    entry: ConfigEntry,
    devices: Mapping[str, Mapping[str, Any]],
) -> int:
    """Place selected devices that have no area yet into their ORVIBO room's area.

    Devices that already have an area keep it, so areas the user renamed,
    merged or reassigned in Home Assistant are not recreated on every reload.
    """

    selected = selected_device_ids(entry.options, devices)
    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    assigned = 0
    for device_id, device in devices.items():
        if device_id not in selected:
            continue
        room_name = device.get("room_name")
        if not room_name:
            continue
        device_entry = device_registry.async_get_device(
            identifiers={(DOMAIN, device_id)}
        )
        if device_entry is None or device_entry.area_id:
            continue
        area = area_registry.async_get_area_by_name(room_name)
        if area is None:
            area = area_registry.async_create(room_name)
        device_registry.async_update_device(device_entry.id, area_id=area.id)
        assigned += 1
    return assigned
