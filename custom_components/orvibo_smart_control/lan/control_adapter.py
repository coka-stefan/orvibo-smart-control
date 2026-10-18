"""LAN control adapter that reuses the HomeMate cloud HomemateJsonData payload builder,
changing only the transport from SSL to gateway TCP (ADR-3: unified control semantics).
"""

from __future__ import annotations

import logging
from typing import Any

from ..packet import HomemateJsonData
from .privacy import mask_identifier

_LOGGER = logging.getLogger(__name__)

# SSL-only fields included in cloud packets must be stripped because LAN gateways/firmware do not recognize them (verified on hardware).
_SSL_ONLY_FIELDS = frozenset(
    ("groupId", "qualityOfService", "defaultResponse", "propertyResponse", "debugInfo")
)


class LanControlAdapter:
    """Control methods matching ssl_client.send_control_* names and arguments, sent through the gateway."""

    def __init__(self, username: str, gateway_manager: Any) -> None:
        self._default_username = username
        self._gateway_manager = gateway_manager

    @property
    def _username(self) -> str:
        # Follow the identity the gateway accepted at login (see GatewayManager fallbacks).
        return getattr(self._gateway_manager, "username", None) or self._default_username

    async def _send(self, payload: dict[str, Any]) -> bool:
        lan_payload = {
            key: value
            for key, value in payload.items()
            if key not in _SSL_ONLY_FIELDS
        }
        uid = lan_payload.get("uid", "")
        _LOGGER.debug(
            "Sending LAN control: device=%s cmd=%s",
            mask_identifier(lan_payload.get("deviceId", "")),
            lan_payload.get("cmd"),
        )
        try:
            response = await self._gateway_manager.send(uid, lan_payload, timeout=8.0)
        except Exception as error:  # noqa: BLE001
            _LOGGER.debug("LAN control send failed: %s", type(error).__name__)
            return False
        if response is None:
            return False
        status = response.get("status") if isinstance(response, dict) else None
        if isinstance(status, bool):
            status_ok = False
        elif isinstance(status, int):
            status_ok = status == 0
        elif isinstance(status, str):
            status_ok = status.strip() == "0"
        else:
            # Some gateway firmware acknowledges cmd=15 without a status field.
            status_ok = True
        _LOGGER.debug(
            "LAN control response: device=%s status=%s",
            mask_identifier(lan_payload.get("deviceId", "")),
            status if isinstance(status, int) and not isinstance(status, bool) else "legacy",
        )
        return status_ok

    async def send_control_switch(
        self, device_id: str, device_uid: str, state: bool
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_switch(
                self._username, device_id, device_uid, state
            )
        )

    async def send_control_cct_light_onoff(
        self, device_id: str, device_uid: str, state: bool
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_cct_light_onoff(
                self._username, device_id, device_uid, state
            )
        )

    async def send_control_cct_light_brightness(
        self, device_id: str, device_uid: str, brightness_percent: int
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_cct_light_brightness(
                self._username, device_id, device_uid, brightness_percent
            )
        )

    async def send_control_cct_light_colortemp(
        self, device_id: str, device_uid: str, colortemp_k: int
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_cct_light_colortemp(
                self._username, device_id, device_uid, colortemp_k
            )
        )

    async def send_control_floor_heating_power(
        self, device_id: str, device_uid: str, state: bool
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_floor_heating_power(
                self._username, device_id, device_uid, state
            )
        )

    async def send_control_floor_heating_temperature(
        self, device_id: str, device_uid: str, temperature: int
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_floor_heating_temperature(
                self._username, device_id, device_uid, temperature
            )
        )

    async def send_control_dream_curtain_action(
        self, device_id: str, device_uid: str, action: str
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_dream_curtain_action(
                self._username, device_id, device_uid, action
            )
        )

    async def send_control_dream_curtain_percent(
        self, device_id: str, device_uid: str, percent: int
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_dream_curtain_percent(
                self._username, device_id, device_uid, percent
            )
        )

    async def send_control_dream_curtain_angle(
        self, device_id: str, device_uid: str, angle: int
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_dream_curtain_angle(
                self._username, device_id, device_uid, angle
            )
        )

    async def send_control_dimmable_light_brightness(
        self, device_id: str, device_uid: str, brightness_percent: int
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_dimmable_light_brightness(
                self._username, device_id, device_uid, brightness_percent
            )
        )

    async def send_control_zigbee_dimmable_light_onoff(
        self,
        device_id: str,
        device_uid: str,
        state: bool,
        brightness: int = 255,
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_zigbee_dimmable_light_onoff(
                self._username, device_id, device_uid, state, brightness
            )
        )

    async def send_control_zigbee_dimmable_light_brightness(
        self, device_id: str, device_uid: str, brightness_255: int
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_zigbee_dimmable_light_brightness(
                self._username, device_id, device_uid, brightness_255
            )
        )

    async def send_control_fast_move_dim_color_light_onoff(
        self,
        device_id: str,
        device_uid: str,
        state: bool,
        brightness: int = 0,
        colortemp_mired: int = 0,
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_fast_move_dim_color_light_onoff(
                self._username,
                device_id,
                device_uid,
                state,
                brightness,
                colortemp_mired,
            )
        )

    async def send_control_fast_move_dim_color_light_brightness(
        self,
        device_id: str,
        device_uid: str,
        brightness: int,
        colortemp_mired: int = 0,
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_fast_move_dim_color_light_brightness(
                self._username,
                device_id,
                device_uid,
                brightness,
                colortemp_mired,
            )
        )

    async def send_control_fast_move_dim_color_light_colortemp(
        self,
        device_id: str,
        device_uid: str,
        brightness: int,
        colortemp_mired: int,
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_fast_move_dim_color_light_colortemp(
                self._username,
                device_id,
                device_uid,
                brightness,
                colortemp_mired,
            )
        )

    async def send_control_light(
        self,
        device_id: str,
        device_uid: str,
        state: bool,
        brightness: int = 0,
        colortemp_mired: int = 0,
    ) -> bool:
        if state and (brightness is None or int(brightness or 0) <= 0):
            # The legacy LAN protocol (types 0/1/38) requires value2=255 when turning on a light,
            # or it turns on at brightness 0 and immediately goes dark (observed lan-control light_on behavior).
            brightness = 255
        return await self._send(
            HomemateJsonData.ssl_control_light(
                self._username,
                device_id,
                device_uid,
                state,
                brightness,
                colortemp_mired,
            )
        )

    async def send_control_light_brightness(
        self, device_id: str, device_uid: str, brightness: int
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_light_brightness(
                self._username, device_id, device_uid, brightness
            )
        )

    async def send_control_light_colortemp(
        self,
        device_id: str,
        device_uid: str,
        colortemp_k: int,
        brightness: int = 0,
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_light_colortemp(
                self._username,
                device_id,
                device_uid,
                colortemp_k,
                brightness,
            )
        )

    async def send_control_cover(
        self,
        device_id: str,
        device_uid: str,
        position: int,
        stop_value2: int = 0,
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_cover(
                self._username,
                device_id,
                device_uid,
                position,
                stop_value2,
            )
        )

    async def send_control_legacy_floor_heating_power(
        self,
        device_id: str,
        device_uid: str,
        is_on: bool,
        *,
        packed_state: int = 0,
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_legacy_floor_heating(
                self._username,
                device_id,
                device_uid,
                order="on" if is_on else "off",
                value1=0 if is_on else 1,
                value2=0 if is_on else max(0, int(packed_state)),
            )
        )

    async def send_control_legacy_floor_heating_temperature(
        self, device_id: str, device_uid: str, temperature: int
    ) -> bool:
        target = max(10, min(35, int(round(temperature))))
        return await self._send(
            HomemateJsonData.ssl_control_legacy_floor_heating(
                self._username,
                device_id,
                device_uid,
                order="temperature setting",
                value1=8,
                value2=target - 10,
            )
        )

    async def send_control_ventilation(
        self, device_id: str, device_uid: str, value1: int
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_ventilation(
                self._username, device_id, device_uid, value1
            )
        )

    async def send_ac_control(
        self,
        device_id: str,
        device_uid: str,
        *,
        order: str,
        value1: int | None = None,
        value2: int | None = None,
        value3: int | None = None,
        value4: int | None = None,
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_ac(
                self._username,
                device_id,
                device_uid,
                order=order,
                value1=value1,
                value2=value2,
                value3=value3,
                value4=value4,
            )
        )

    async def send_light_bri_ct(
        self,
        device_id: str,
        device_uid: str,
        brightness: int | None,
        color_temp_k: int | None,
    ) -> bool:
        return await self._send(
            HomemateJsonData.ssl_control_light_full(
                self._username,
                device_id,
                device_uid,
                brightness,
                color_temp_k,
            )
        )
