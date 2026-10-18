"""Entity naming regressions: no doubled "<device> <device>" friendly names.

Home Assistant builds the friendly name of an entity with
``has_entity_name = True`` from the device name plus the entity name. The
primary entity of a device must use ``name = None`` so HA shows only the
device name. Secondary entities keep a feature name. Translated entities must
not set ``_attr_name`` at all, because any ``_attr_name`` value (also None)
takes precedence over the translation key.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


PACKAGE = "orvibo_smart_control_entity_naming_test"


def _module(name, **values):
    module = ModuleType(name)
    module.__dict__.update(values)
    return module


class _Flags:
    """Enum stand-in: each member is a distinct bit, so ``|`` works."""

    def __init__(self):
        self._values = {}

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        values = self.__dict__["_values"]
        if item not in values:
            values[item] = 1 << len(values)
        return values[item]


def _base(name):
    return type(name, (), {})


def _load_platforms():
    package = _module(PACKAGE)
    package.__path__ = [str(
        Path(__file__).parents[1] / "custom_components" / "orvibo_smart_control"
    )]

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    modules = {
        PACKAGE: package,
        "homeassistant": _module("homeassistant"),
        "homeassistant.components": _module("homeassistant.components"),
        "homeassistant.components.cover": _module(
            "homeassistant.components.cover", CoverEntity=_base("CoverEntity"),
            CoverDeviceClass=_Flags(), CoverEntityFeature=_Flags(),
        ),
        "homeassistant.components.light": _module(
            "homeassistant.components.light", LightEntity=_base("LightEntity"),
            ColorMode=_Flags(),
        ),
        "homeassistant.components.switch": _module(
            "homeassistant.components.switch", SwitchEntity=_base("SwitchEntity"),
        ),
        "homeassistant.components.climate": _module(
            "homeassistant.components.climate", ClimateEntity=_base("ClimateEntity"),
            ClimateEntityFeature=_Flags(), HVACMode=_Flags(),
        ),
        "homeassistant.components.fan": _module(
            "homeassistant.components.fan", FanEntity=_base("FanEntity"),
            FanEntityFeature=_Flags(),
        ),
        "homeassistant.components.sensor": _module(
            "homeassistant.components.sensor", SensorEntity=_base("SensorEntity"),
            SensorDeviceClass=_Flags(), SensorStateClass=_Flags(),
        ),
        "homeassistant.config_entries": _module("homeassistant.config_entries", ConfigEntry=object),
        "homeassistant.const": _module(
            "homeassistant.const", UnitOfTemperature=_Flags(), EntityCategory=_Flags(),
        ),
        "homeassistant.core": _module("homeassistant.core", HomeAssistant=object),
        "homeassistant.helpers": _module("homeassistant.helpers"),
        "homeassistant.helpers.entity_registry": _module("homeassistant.helpers.entity_registry"),
        "homeassistant.helpers.entity_platform": _module(
            "homeassistant.helpers.entity_platform", AddEntitiesCallback=object,
        ),
        "homeassistant.helpers.update_coordinator": _module(
            "homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity,
        ),
        f"{PACKAGE}.coordinator": _module(
            f"{PACKAGE}.coordinator", OrviboSmartControlCoordinator=object,
        ),
    }
    with patch.dict(sys.modules, modules):
        return {
            name: importlib.import_module(f"{PACKAGE}.{name}")
            for name in ("cover", "light", "switch", "climate", "fan", "sensor")
        }


def _ha_name(entity):
    """Mirror the start of HA's ``Entity.name``: ``_attr_name`` wins if present."""
    if hasattr(entity, "_attr_name"):
        return entity._attr_name
    return f"translation:{entity._attr_translation_key}"


class EntityNamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.platforms = _load_platforms()
        cls.coordinator = SimpleNamespace(
            get_device_state=lambda _: {"online": True},
            devices={}, device_states={},
        )

    def device(self, name="Roller Blinds", **extra):
        return {"device_id": "dev-1", "device_name": name, **extra}

    def test_primary_entities_use_only_the_device_name(self):
        p = self.platforms
        cases = {
            "cover": p["cover"].OrviboCover(self.coordinator, self.device()),
            "light": p["light"].OrviboLight(self.coordinator, self.device(
                "Kitchen pendant", device_type_raw=38, sub_device_type=-2,
            )),
            "switch": p["switch"].OrviboSwitch(self.coordinator, self.device("Socket")),
            "fan_coil": p["climate"].OrviboFanCoilAC(self.coordinator, self.device("AC")),
            "floor_heating": p["climate"].OrviboFloorHeating(self.coordinator, self.device("Floor")),
            "fan": p["fan"].OrviboVentilationFan(self.coordinator, self.device("Fresh air")),
        }
        for label, entity in cases.items():
            with self.subTest(label):
                self.assertTrue(entity._attr_has_entity_name)
                self.assertIsNone(_ha_name(entity))

    def test_primary_entity_unique_ids_are_unchanged(self):
        p = self.platforms
        self.assertEqual(
            p["cover"].OrviboCover(self.coordinator, self.device())._attr_unique_id,
            "orvibo_smart_control_cover_dev-1",
        )
        self.assertEqual(
            p["light"].OrviboLight(self.coordinator, self.device())._attr_unique_id,
            "orvibo_smart_control_light_dev-1",
        )
        self.assertEqual(
            p["switch"].OrviboSwitch(self.coordinator, self.device())._attr_unique_id,
            "orvibo_smart_control_switch_dev-1",
        )

    def test_device_info_keeps_the_device_name(self):
        fan = self.platforms["fan"].OrviboVentilationFan(
            self.coordinator, self.device("Fresh air"),
        )
        self.assertEqual(fan._attr_device_info["name"], "Fresh air")
        cover = self.platforms["cover"].OrviboCover(self.coordinator, self.device())
        self.assertEqual(cover.device_info["name"], "Roller Blinds")

    def test_secondary_entities_keep_feature_names(self):
        p = self.platforms
        device = self.device("Clothes horse")
        self.assertEqual(
            _ha_name(p["cover"].OrviboClothesHorseMotor(self.coordinator, device)),
            "Drying rack",
        )
        self.assertEqual(
            _ha_name(p["light"].OrviboClothesHorseLight(self.coordinator, device)),
            "Light",
        )
        self.assertEqual(
            _ha_name(p["switch"].OrviboClothesHorseSwitch(
                self.coordinator, device, "main_switch", "Power", "mdi:power",
            )),
            "Power",
        )
        self.assertEqual(
            _ha_name(p["sensor"].OrviboMotionBatterySensor(self.coordinator, device)),
            "Battery",
        )

    def test_translated_diagnostic_sensors_use_translation_names(self):
        sensor = self.platforms["sensor"]
        transport = sensor.OrviboTransportPathSensor(self.coordinator, self.device())
        sdk = sensor.OrviboCameraSdkSensor(self.coordinator, self.device("Camera"))
        self.assertEqual(_ha_name(transport), "translation:transport_path")
        self.assertEqual(_ha_name(sdk), "translation:camera_sdk")


if __name__ == "__main__":
    unittest.main()
