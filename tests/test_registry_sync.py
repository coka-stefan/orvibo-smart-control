"""Tests for keeping Home Assistant registries aligned with device selection."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


COMPONENT_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "orvibo_smart_control"
)


def _module(name: str, **values) -> ModuleType:
    module = ModuleType(name)
    for key, value in values.items():
        setattr(module, key, value)
    return module


def _load_module():
    package_name = "orvibo_smart_control_registry_sync_test"
    package = _module(package_name)
    package.__path__ = [str(COMPONENT_PATH)]

    device_registry = _module(
        "homeassistant.helpers.device_registry",
        async_get=lambda hass: hass.device_registry,
        async_entries_for_config_entry=lambda registry, entry_id: [
            device
            for device in registry.devices
            if entry_id in device.config_entries
        ],
    )
    entity_registry = _module(
        "homeassistant.helpers.entity_registry",
        async_get=lambda hass: hass.entity_registry,
        async_entries_for_config_entry=lambda registry, entry_id: [
            entity
            for entity in registry.entities
            if entity.config_entry_id == entry_id
        ],
    )
    area_registry = _module(
        "homeassistant.helpers.area_registry",
        async_get=lambda hass: hass.area_registry,
    )
    helpers = _module(
        "homeassistant.helpers",
        area_registry=area_registry,
        device_registry=device_registry,
        entity_registry=entity_registry,
    )
    modules = {
        package_name: package,
        "homeassistant": _module("homeassistant", helpers=helpers),
        "homeassistant.config_entries": _module(
            "homeassistant.config_entries", ConfigEntry=object
        ),
        "homeassistant.core": _module(
            "homeassistant.core", HomeAssistant=object
        ),
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.area_registry": area_registry,
        "homeassistant.helpers.device_registry": device_registry,
        "homeassistant.helpers.entity_registry": entity_registry,
        f"{package_name}.const": _module(
            f"{package_name}.const", DOMAIN="orvibo_smart_control"
        ),
    }

    with patch.dict(sys.modules, modules):
        return importlib.import_module(f"{package_name}.registry_sync")


class RegistrySyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def _hass(self):
        selected_device = SimpleNamespace(
            id="registry-selected",
            identifiers={("orvibo_smart_control", "selected")},
            config_entries={"entry-1"},
        )
        hidden_device = SimpleNamespace(
            id="registry-hidden",
            identifiers={("orvibo_smart_control", "hidden")},
            config_entries={"entry-1"},
        )
        other_integration_device = SimpleNamespace(
            id="registry-other",
            identifiers={("other_domain", "other")},
            config_entries={"entry-1"},
        )
        entities = [
            SimpleNamespace(
                entity_id="light.selected",
                device_id="registry-selected",
                config_entry_id="entry-1",
            ),
            SimpleNamespace(
                entity_id="switch.hidden",
                device_id="registry-hidden",
                config_entry_id="entry-1",
            ),
            SimpleNamespace(
                entity_id="sensor.other",
                device_id="registry-other",
                config_entry_id="entry-1",
            ),
        ]
        return SimpleNamespace(
            device_registry=SimpleNamespace(
                devices=[
                    selected_device,
                    hidden_device,
                    other_integration_device,
                ],
                async_remove_device=MagicMock(),
                async_update_device=MagicMock(),
            ),
            entity_registry=SimpleNamespace(
                entities=entities,
                async_remove=MagicMock(),
            ),
        )

    def test_removes_deselected_entities_and_devices_only(self):
        hass = self._hass()
        entry = SimpleNamespace(
            entry_id="entry-1",
            options={
                "selected_device_ids": ["selected", "hidden"],
                "hidden_device_name_patterns": ["Relay"],
            },
        )
        devices = {
            "selected": {
                "device_id": "selected",
                "device_name": "Living Room Light",
            },
            "hidden": {
                "device_id": "hidden",
                "device_name": "Dining Room Light Strip Relay",
            },
        }

        removed = self.module.sync_selected_device_registries(
            hass, entry, devices
        )

        self.assertEqual(removed, 1)
        hass.entity_registry.async_remove.assert_called_once_with(
            "switch.hidden"
        )
        hass.device_registry.async_remove_device.assert_called_once_with(
            "registry-hidden"
        )
        hass.device_registry.async_update_device.assert_not_called()

    def test_shared_device_drops_only_this_config_entry(self):
        hass = self._hass()
        hidden = hass.device_registry.devices[1]
        hidden.config_entries.add("entry-2")
        entry = SimpleNamespace(
            entry_id="entry-1",
            options={"selected_device_ids": ["selected"]},
        )

        self.module.sync_selected_device_registries(
            hass,
            entry,
            {
                "selected": {"device_id": "selected"},
                "hidden": {"device_id": "hidden"},
            },
        )

        hass.device_registry.async_remove_device.assert_not_called()
        hass.device_registry.async_update_device.assert_called_once_with(
            "registry-hidden", remove_config_entry_id="entry-1"
        )


class AssignRoomAreasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def _hass(self, areas, devices):
        by_identifier = {
            next(iter(device.identifiers))[1]: device for device in devices
        }
        created = []

        def create(name):
            area = SimpleNamespace(id=name.lower().replace(" ", "_"), name=name)
            areas[name] = area
            created.append(name)
            return area

        hass = SimpleNamespace(
            area_registry=SimpleNamespace(
                async_get_area_by_name=lambda name: areas.get(name),
                async_create=MagicMock(side_effect=create),
            ),
            device_registry=SimpleNamespace(
                async_get_device=lambda identifiers: by_identifier.get(
                    next(iter(identifiers))[1]
                ),
                async_update_device=MagicMock(),
            ),
        )
        return hass, created

    @staticmethod
    def _device(device_id, area_id):
        return SimpleNamespace(
            id=f"registry-{device_id}",
            identifiers={("orvibo_smart_control", device_id)},
            area_id=area_id,
        )

    def test_keeps_areas_the_user_already_assigned(self):
        hass, created = self._hass(
            {}, [self._device("spots", "bedroom"), self._device("ceiling", "study")]
        )
        entry = SimpleNamespace(options={})
        devices = {
            "spots": {"device_id": "spots", "room_name": "Main bedroom"},
            "ceiling": {"device_id": "ceiling", "room_name": "Study room"},
        }

        assigned = self.module.assign_room_areas(hass, entry, devices)

        self.assertEqual(assigned, 0)
        self.assertEqual(created, [])
        hass.device_registry.async_update_device.assert_not_called()

    def test_places_devices_without_an_area_in_their_room(self):
        living = SimpleNamespace(id="living_room", name="Living Room")
        hass, created = self._hass(
            {"Living Room": living},
            [self._device("sofa", None), self._device("wardrobe", None)],
        )
        entry = SimpleNamespace(options={})
        devices = {
            "sofa": {"device_id": "sofa", "room_name": "Living Room"},
            "wardrobe": {"device_id": "wardrobe", "room_name": "Main bedroom"},
            "unnamed": {"device_id": "unnamed", "room_name": ""},
        }

        assigned = self.module.assign_room_areas(hass, entry, devices)

        self.assertEqual(assigned, 2)
        self.assertEqual(created, ["Main bedroom"])
        hass.device_registry.async_update_device.assert_any_call(
            "registry-sofa", area_id="living_room"
        )
        hass.device_registry.async_update_device.assert_any_call(
            "registry-wardrobe", area_id="main_bedroom"
        )


if __name__ == "__main__":
    unittest.main()
