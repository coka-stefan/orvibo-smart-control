"""Tests for GatewayManager login identity fallback."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest

COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "orvibo_smart_control"


def _load_package() -> types.ModuleType:
    package_name = "orvibo_smart_control_lanmgr_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(COMPONENT_PATH)]
    sys.modules[package_name] = package
    return package


class GatewayManagerLoginFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        package = _load_package()
        cls.manager_mod = importlib.import_module(f"{package.__name__}.lan.gateway_manager")
        cls.conn_mod = importlib.import_module(f"{package.__name__}.lan.gateway_connection")
        cls.adapter_mod = importlib.import_module(f"{package.__name__}.lan.control_adapter")

    def _factory(self, accepted: set[str]):
        attempts: list[str] = []
        closed: list[str] = []
        rejected = self.conn_mod.GatewayLoginRejectedError

        class FakeConnection:
            def __init__(self, host: str) -> None:
                self.host = host
                self.connected = False
                self.push_callback = None

            async def connect(self, username, password, **kwargs) -> None:
                attempts.append(username)
                if username not in accepted:
                    raise rejected("gateway login was rejected", reason="login_rejected")
                self.connected = True

            async def close(self) -> None:
                closed.append(self.host)

        return FakeConnection, attempts, closed

    def _manager(self, factory, fallbacks=()):
        return self.manager_mod.GatewayManager(
            "user@example.com",
            "HASH",
            {"gw-1": "192.168.1.90"},
            connection_factory=factory,
            password_is_hash=True,
            fallback_usernames=fallbacks,
        )

    def test_falls_back_to_user_id_and_remembers_it(self) -> None:
        factory, attempts, closed = self._factory({"user-id-1"})
        manager = self._manager(factory, ("user-id-1",))
        connection = asyncio.run(manager._connect("gw-1", "192.168.1.90"))

        self.assertTrue(connection.connected)
        self.assertEqual(attempts, ["user@example.com", "user-id-1"])
        self.assertEqual(len(closed), 1)
        self.assertEqual(manager.username, "user-id-1")
        # Control payloads follow the identity the gateway accepted.
        adapter = self.adapter_mod.LanControlAdapter("user@example.com", manager)
        self.assertEqual(adapter._username, "user-id-1")

    def test_primary_username_is_tried_first(self) -> None:
        factory, attempts, _ = self._factory({"user@example.com", "user-id-1"})
        manager = self._manager(factory, ("user-id-1",))
        asyncio.run(manager._connect("gw-1", "192.168.1.90"))

        self.assertEqual(attempts, ["user@example.com"])
        self.assertEqual(manager.username, "user@example.com")

    def test_rejection_propagates_when_no_identity_is_accepted(self) -> None:
        factory, attempts, _ = self._factory(set())
        manager = self._manager(factory, ("user-id-1", "", "user@example.com"))
        with self.assertRaises(self.conn_mod.GatewayLoginRejectedError):
            asyncio.run(manager._connect("gw-1", "192.168.1.90"))
        self.assertEqual(attempts, ["user@example.com", "user-id-1"])

    def test_no_fallback_keeps_single_attempt(self) -> None:
        factory, attempts, _ = self._factory(set())
        manager = self._manager(factory)
        with self.assertRaises(self.conn_mod.GatewayLoginRejectedError):
            asyncio.run(manager._connect("gw-1", "192.168.1.90"))
        self.assertEqual(attempts, ["user@example.com"])


if __name__ == "__main__":
    unittest.main()
