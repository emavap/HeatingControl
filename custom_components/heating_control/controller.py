"""Service orchestration for climate device control."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .models import DeviceDecision

_LOGGER = logging.getLogger(__name__)


@dataclass
class _DeviceCommandState:
    """Track the last command sent to a device."""

    on: bool
    temperature: Optional[float]
    fan: Optional[str]


class ClimateController:
    """Encapsulate calls to Home Assistant climate services."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        settle_seconds: int,
        final_settle: int,
    ) -> None:
        self._hass = hass
        self._settle_seconds = settle_seconds
        self._final_settle = final_settle
        self._history: Dict[str, _DeviceCommandState] = {}

    async def async_apply(
        self,
        device_decisions: Iterable[DeviceDecision],
    ) -> None:
        """Apply decisions to all devices."""
        for decision in device_decisions:
            await self._apply_device(
                decision.entity_id,
                decision.should_be_active,
                decision.target_temp,
                decision.target_fan,
            )

    def reset_history(self) -> None:
        """Forget previously issued commands."""
        self._history.clear()

    async def _apply_device(
        self,
        entity_id: str,
        should_be_on: bool,
        target_temp: float,
        target_fan: str,
    ) -> None:
        """Apply commands for a single climate device."""
        state = self._hass.states.get(entity_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug("Skipping %s – entity state unavailable (%s)", entity_id, state)
            return

        previous = self._history.get(entity_id)
        previous_on = previous.on if previous else None
        previous_temp = previous.temperature if previous else None
        previous_fan = previous.fan if previous else None

        state_changed = previous_on != should_be_on
        temp_changed = should_be_on and (
            previous_temp is None or abs(previous_temp - target_temp) > 0.01
        )
        fan_changed = should_be_on and target_fan is not None and previous_fan != target_fan

        if not state_changed and not temp_changed and not fan_changed:
            _LOGGER.debug("No changes required for %s", entity_id)
            return

        try:
            if should_be_on:
                if state_changed:
                    _LOGGER.info("Turning %s ON", entity_id)
                    await self._hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": entity_id, "hvac_mode": "heat"},
                        blocking=True,
                    )
                    await asyncio.sleep(self._settle_seconds)

                if temp_changed:
                    _LOGGER.info(
                        "Setting %s temperature to %.2f°C", entity_id, target_temp
                    )
                    await self._hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {"entity_id": entity_id, "temperature": target_temp},
                        blocking=True,
                    )

                if fan_changed:
                    fan_modes = state.attributes.get("fan_modes", [])
                    if fan_modes and target_fan in fan_modes:
                        _LOGGER.info("Setting %s fan mode to %s", entity_id, target_fan)
                        await self._hass.services.async_call(
                            "climate",
                            "set_fan_mode",
                            {"entity_id": entity_id, "fan_mode": target_fan},
                            blocking=True,
                        )

                if state_changed:
                    await asyncio.sleep(self._final_settle)
            else:
                if state_changed:
                    _LOGGER.info("Turning %s OFF", entity_id)
                    await self._hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": entity_id, "hvac_mode": "off"},
                        blocking=True,
                    )

            self._history[entity_id] = _DeviceCommandState(
                on=should_be_on,
                temperature=target_temp if should_be_on else None,
                fan=target_fan if should_be_on else None,
            )
        except Exception as err:  # pragma: no cover - defensive logging
            _LOGGER.error("Error controlling %s: %s", entity_id, err)
