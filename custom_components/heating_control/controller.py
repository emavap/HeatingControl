"""Service orchestration for climate device control."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

__all__ = ["ClimateController"]

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound

from .const import SERVICE_CALL_TIMEOUT, TEMPERATURE_EPSILON
from .models import DeviceDecision

_LOGGER = logging.getLogger(__name__)


@dataclass
class _DeviceCommandState:
    """Track the last command sent to a device."""

    hvac_mode: Optional[str]
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
        self._timed_out_devices: set[str] = set()  # Use set to prevent duplicates
        self._force_refresh_devices: set[str] = set()  # Devices that need history ignored

    async def async_apply(
        self,
        device_decisions: Iterable[DeviceDecision],
    ) -> list[str]:
        """Apply decisions to all devices.

        Returns list of device entity_ids that timed out during service calls.
        """
        self._timed_out_devices.clear()

        # Convert to list to allow multiple iterations
        decisions_list = list(device_decisions)

        # Collect current device IDs and clean up orphaned devices
        current_devices = {d.entity_id for d in decisions_list}
        self._force_refresh_devices &= current_devices  # Set intersection

        # Clean up history for devices no longer in configuration
        orphaned_devices = set(self._history.keys()) - current_devices
        for device_id in orphaned_devices:
            del self._history[device_id]
            _LOGGER.debug("Cleaned up history for removed device: %s", device_id)

        for decision in decisions_list:
            await self._apply_device(decision)
        return list(self._timed_out_devices)

    async def _apply_device(self, decision: DeviceDecision) -> None:
        """Apply commands for a single climate device."""
        entity_id = decision.entity_id
        hvac_mode = decision.hvac_mode
        target_temp = decision.target_temp
        target_fan = decision.target_fan

        if hvac_mode is None:
            _LOGGER.debug("No HVAC mode specified for %s; leaving device untouched", entity_id)
            self._history.pop(entity_id, None)
            return

        state = self._hass.states.get(entity_id)
        if not state:
            _LOGGER.debug("Skipping %s – entity not found in state machine", entity_id)
            return
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug("Skipping %s – entity state unavailable (%s)", entity_id, state.state)
            return

        # If device previously timed out, ignore history to force full refresh
        if entity_id in self._force_refresh_devices:
            _LOGGER.info(
                "Forcing full refresh for %s (previous timeout)", entity_id
            )
            previous_mode = None
            previous_temp = None
            previous_fan = None
        else:
            previous = self._history.get(entity_id)
            previous_mode = previous.hvac_mode if previous else None
            previous_temp = previous.temperature if previous else None
            previous_fan = previous.fan if previous else None

        hvac_mode = hvac_mode or "off"
        should_be_on = hvac_mode != "off"

        state_changed = previous_mode != hvac_mode
        temp_changed = (
            should_be_on
            and target_temp is not None
            and (previous_temp is None or abs(previous_temp - target_temp) > TEMPERATURE_EPSILON)
        )
        fan_changed = should_be_on and target_fan is not None and previous_fan != target_fan

        if not state_changed and not temp_changed and not fan_changed:
            _LOGGER.debug("No changes required for %s", entity_id)
            return

        # Track which operations succeeded for history updates
        hvac_mode_succeeded = not state_changed
        temp_succeeded = not temp_changed
        fan_succeeded = not fan_changed

        try:
            if should_be_on:
                if state_changed:
                    _LOGGER.info("Setting %s HVAC mode to %s", entity_id, hvac_mode)
                    try:
                        await asyncio.wait_for(
                            self._hass.services.async_call(
                                "climate",
                                "set_hvac_mode",
                                {"entity_id": entity_id, "hvac_mode": hvac_mode},
                                blocking=True,
                            ),
                            timeout=SERVICE_CALL_TIMEOUT,
                        )
                        hvac_mode_succeeded = True
                        await asyncio.sleep(self._settle_seconds)
                    except asyncio.TimeoutError:
                        _LOGGER.error(
                            "Timeout setting HVAC mode for %s (timeout=%ds), continuing with other settings",
                            entity_id,
                            SERVICE_CALL_TIMEOUT,
                        )
                        self._timed_out_devices.add(entity_id)

                if temp_changed:
                    _LOGGER.info(
                        "Setting %s temperature to %.2f°C", entity_id, target_temp
                    )
                    try:
                        await asyncio.wait_for(
                            self._hass.services.async_call(
                                "climate",
                                "set_temperature",
                                {"entity_id": entity_id, "temperature": target_temp},
                                blocking=True,
                            ),
                            timeout=SERVICE_CALL_TIMEOUT,
                        )
                        temp_succeeded = True
                    except asyncio.TimeoutError:
                        _LOGGER.error(
                            "Timeout setting temperature for %s (timeout=%ds), continuing with other settings",
                            entity_id,
                            SERVICE_CALL_TIMEOUT,
                        )
                        self._timed_out_devices.add(entity_id)

                if fan_changed:
                    fan_modes = state.attributes.get("fan_modes", [])
                    if fan_modes and target_fan in fan_modes:
                        _LOGGER.info("Setting %s fan mode to %s", entity_id, target_fan)
                        try:
                            await asyncio.wait_for(
                                self._hass.services.async_call(
                                    "climate",
                                    "set_fan_mode",
                                    {"entity_id": entity_id, "fan_mode": target_fan},
                                    blocking=True,
                                ),
                                timeout=SERVICE_CALL_TIMEOUT,
                            )
                            fan_succeeded = True
                        except asyncio.TimeoutError:
                            _LOGGER.error(
                                "Timeout setting fan mode for %s (timeout=%ds)",
                                entity_id,
                                SERVICE_CALL_TIMEOUT,
                            )
                            self._timed_out_devices.add(entity_id)

                if state_changed and hvac_mode_succeeded:
                    await asyncio.sleep(self._final_settle)
            else:
                if state_changed:
                    _LOGGER.info("Turning %s OFF", entity_id)
                    try:
                        await asyncio.wait_for(
                            self._hass.services.async_call(
                                "climate",
                                "set_hvac_mode",
                                {"entity_id": entity_id, "hvac_mode": "off"},
                                blocking=True,
                            ),
                            timeout=SERVICE_CALL_TIMEOUT,
                        )
                        hvac_mode_succeeded = True
                    except asyncio.TimeoutError:
                        _LOGGER.error(
                            "Timeout turning off %s (timeout=%ds)",
                            entity_id,
                            SERVICE_CALL_TIMEOUT,
                        )
                        self._timed_out_devices.add(entity_id)

            # Update command history and force refresh status
            self._update_device_history(
                entity_id,
                hvac_mode if hvac_mode_succeeded else previous_mode,
                target_temp if temp_succeeded else previous_temp,
                target_fan if fan_succeeded else previous_fan,
                should_be_on,
            )
            self._update_force_refresh_status(
                entity_id,
                hvac_mode_succeeded,
                temp_succeeded,
                fan_succeeded,
            )

        except (ServiceNotFound, HomeAssistantError) as err:
            _LOGGER.error(
                "Home Assistant error controlling %s: %s",
                entity_id,
                err,
                exc_info=True,
            )
            self._force_refresh_devices.add(entity_id)
        except Exception as err:  # Unexpected errors
            _LOGGER.exception("Unexpected error controlling %s", entity_id)
            self._force_refresh_devices.add(entity_id)
            raise  # Re-raise unexpected errors

    def _update_device_history(
        self,
        entity_id: str,
        hvac_mode: Optional[str],
        temperature: Optional[float],
        fan: Optional[str],
        should_be_on: bool,
    ) -> None:
        """Update command history for a device.

        Args:
            entity_id: Climate entity ID
            hvac_mode: HVAC mode that was set (or None if failed)
            temperature: Temperature that was set (or None if failed/not applicable)
            fan: Fan mode that was set (or None if failed/not applicable)
            should_be_on: Whether device should be in an active state
        """
        # When off, always store None for temp/fan to ensure they're set on next turn-on
        if not should_be_on:
            temperature = None
            fan = None

        self._history[entity_id] = _DeviceCommandState(
            hvac_mode=hvac_mode,
            temperature=temperature,
            fan=fan,
        )

    def _update_force_refresh_status(
        self,
        entity_id: str,
        hvac_mode_succeeded: bool,
        temp_succeeded: bool,
        fan_succeeded: bool,
    ) -> None:
        """Update force refresh status based on operation results.

        Devices that experience command failures are marked for force refresh
        on the next cycle to ensure state synchronization.

        Args:
            entity_id: Climate entity ID
            hvac_mode_succeeded: Whether HVAC mode command succeeded
            temp_succeeded: Whether temperature command succeeded
            fan_succeeded: Whether fan mode command succeeded
        """
        operation_failed = not (hvac_mode_succeeded and temp_succeeded and fan_succeeded)

        if operation_failed:
            self._force_refresh_devices.add(entity_id)
            _LOGGER.debug(
                "Marked %s for force refresh (hvac=%s, temp=%s, fan=%s)",
                entity_id,
                hvac_mode_succeeded,
                temp_succeeded,
                fan_succeeded,
            )
        elif entity_id in self._force_refresh_devices:
            # All operations succeeded - clear force refresh flag
            self._force_refresh_devices.discard(entity_id)
            _LOGGER.debug(
                "Cleared force refresh flag for %s (all operations succeeded)",
                entity_id,
            )
