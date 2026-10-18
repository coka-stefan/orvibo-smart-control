"""Tests for config-entry device selection."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "orvibo_smart_control"
    / "selection.py"
)
SPEC = importlib.util.spec_from_file_location("orvibo_smart_control_selection", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
selection = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = selection
SPEC.loader.exec_module(selection)


class SelectionTests(unittest.TestCase):
    def test_hidden_name_patterns_are_normalized(self) -> None:
        result = selection.parse_hidden_device_name_patterns(
            " Test\n*Controller*, TEST; Bedroom?X\nSample "
        )
        self.assertEqual(result, ["Test", "*Controller*", "Bedroom?X", "Sample"])

    def test_hidden_name_matches_keyword_and_wildcard(self) -> None:
        device = {"device_name": "Bedroom1Controller"}
        self.assertTrue(selection.device_name_is_hidden(device, ["Bedroom1"]))
        self.assertTrue(selection.device_name_is_hidden(device, ["*Controller"]))
        self.assertTrue(selection.device_name_is_hidden(device, ["Bedroom?Controller"]))
        self.assertFalse(selection.device_name_is_hidden(device, ["Living Room"]))

    def test_hidden_name_matching_is_case_insensitive(self) -> None:
        device = {"device_name": "Test Controller"}
        self.assertTrue(selection.device_name_is_hidden(device, ["controller"]))
        self.assertTrue(selection.device_name_is_hidden(device, ["TEST*"]))

    def test_hidden_devices_are_excluded_from_entity_selection(self) -> None:
        available = {
            "dev-001": {"device_name": "Living Room Light"},
            "dev-002": {"device_name": "Bedroom Light"},
            "dev-003": {"device_name": "Curtain"},
        }
        options = {
            selection.CONF_SELECTED_DEVICE_IDS: [
                "dev-001",
                "dev-002",
                "dev-003",
            ],
            selection.CONF_HIDDEN_DEVICE_NAME_PATTERNS: ["Bedroom"],
        }
        self.assertEqual(
            selection.selected_device_ids(options, available),
            {"dev-001", "dev-003"},
        )

        options.pop(selection.CONF_HIDDEN_DEVICE_NAME_PATTERNS)
        self.assertEqual(
            selection.selected_device_ids(options, available),
            {"dev-001", "dev-002", "dev-003"},
        )

    def test_legacy_entries_select_all_available_devices(self) -> None:
        self.assertEqual(
            selection.selected_device_ids({}, ["curtain", "light"]),
            {"curtain", "light"},
        )
        self.assertTrue(selection.device_is_selected({}, "curtain"))

    def test_explicit_selection_filters_devices(self) -> None:
        options = {selection.CONF_SELECTED_DEVICE_IDS: ["light", "removed"]}
        self.assertEqual(
            selection.selected_device_ids(options, ["curtain", "light"]),
            {"light"},
        )
        self.assertTrue(selection.device_is_selected(options, "light"))
        self.assertFalse(selection.device_is_selected(options, "curtain"))

    def test_empty_selection_adds_no_devices(self) -> None:
        options = {selection.CONF_SELECTED_DEVICE_IDS: []}
        self.assertEqual(selection.selected_device_ids(options, ["light"]), set())
        self.assertFalse(selection.device_is_selected(options, "light"))

    def test_area_mapping_keeps_ids_and_explicit_unassigned_values(self) -> None:
        options = {
            selection.CONF_DEVICE_AREAS: {
                "curtain": "living_room",
                "light": None,
                "invalid": 42,
            }
        }
        self.assertEqual(
            selection.configured_device_areas(options),
            {"curtain": "living_room", "light": None},
        )


if __name__ == "__main__":
    unittest.main()
