"""Enhanced climate controller with validation and error handling."""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Iterable
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_TEMPERATURE, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    SUPPORT_FAN_MODE,
    SUPPORT_TARGET_TEMPERATURE,
)

from .const import (
    TEMPERATURE_EPSILON,
    MAX_CONCURRENT_DEVICE_COMMANDS,
    SERVICE_CALL_TIMEOUT,
    DEVICE_TIMEOUT_OVERRIDES,
    DEVICE_SETTLE_OVERRIDES,
)
from .models import DeviceDecision

_LOGGER = logging.getLogger(__name__)

from homeassistant.helpers import device_registry as dr, entity_registry as er

@dataclass
class CommandResult:
    """Result of a device command."""
    entity_id: str
    success: bool
    timeout: bool = False
    error: Optional[str] = None

class ClimateController:
    """Enhanced climate controller with validation and error handling."""
    
    def __init__(self, hass: HomeAssistant, settle_seconds: int = 5, final_settle: int = 2, use_device_specific_timing: bool = False):
        self._hass = hass
        self._settle_seconds = settle_seconds
        self._final_settle = final_settle
        self._use_device_specific_timing = use_device_specific_timing
        self._last_commands: Dict[str, Dict[str, Any]] = {}
        self._device_capabilities: Dict[str, Dict[str, Any]] = {}
        self._timed_out_devices: List[str] = []
        self._force_refresh_devices: set = set()
        self._device_response_times: Dict[str, List[float]] = {}

    async def async_apply(self, device_decisions: Iterable[DeviceDecision]) -> List[str]:
        """Apply decisions to all devices with enhanced error handling."""
        self._timed_out_devices.clear()
        
        # Convert to list and validate
        decisions_list = list(device_decisions)
        if not decisions_list:
            return []

        # Collect current device IDs and clean up orphaned devices
        current_devices = {d.entity_id for d in decisions_list}
        self._force_refresh_devices &= current_devices

        # Apply with concurrency control
        results = await self._apply_with_concurrency_control(decisions_list)
        
        # Extract timed out devices
        self._timed_out_devices = [
            result.entity_id for result in results 
            if result.timeout or not result.success
        ]
        
        return self._timed_out_devices

    async def _apply_with_concurrency_control(self, device_decisions: List[DeviceDecision]) -> List[CommandResult]:
        """Apply decisions with concurrency control and validation."""
        results = []
        
        # Validate devices first
        validated_decisions = []
        for decision in device_decisions:
            if await self._validate_device_decision(decision):
                validated_decisions.append(decision)
            else:
                results.append(CommandResult(
                    entity_id=decision.entity_id,
                    success=False,
                    error="Device validation failed"
                ))
        
        # Apply commands with concurrency limit
        if validated_decisions:
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_DEVICE_COMMANDS)
            tasks = [
                self._apply_device_with_semaphore(semaphore, decision)
                for decision in validated_decisions
            ]
            
            command_results = await asyncio.gather(*tasks, return_exceptions=True)
            results.extend([
                result if isinstance(result, CommandResult) else 
                CommandResult(entity_id="unknown", success=False, error=str(result))
                for result in command_results
            ])
        
        return results

    async def _apply_device_with_semaphore(self, semaphore: asyncio.Semaphore, decision: DeviceDecision) -> CommandResult:
        """Apply device decision with semaphore protection."""
        async with semaphore:
            return await self._apply_device_with_timeout(decision)

    async def _apply_device_with_timeout(self, decision: DeviceDecision) -> CommandResult:
        """Apply device decision with timeout and performance tracking."""
        start_time = time.time()
        timeout = await self._get_device_timeout(decision.entity_id)
        
        try:
            result = await asyncio.wait_for(
                self._apply_device_validated(decision),
                timeout=timeout
            )
            
            # Track performance metrics
            response_time = time.time() - start_time
            self._track_device_performance(decision.entity_id, response_time, True)
            
            return result
        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            self._track_device_performance(decision.entity_id, response_time, False)
            
            _LOGGER.warning("Timeout applying control to %s (timeout: %ds)", decision.entity_id, timeout)
            return CommandResult(
                entity_id=decision.entity_id,
                success=False,
                timeout=True,
                error=f"Service call timeout ({timeout}s)"
            )
        except Exception as e:
            response_time = time.time() - start_time
            self._track_device_performance(decision.entity_id, response_time, False)
            
            _LOGGER.error("Error applying control to %s: %s", decision.entity_id, e)
            return CommandResult(
                entity_id=decision.entity_id,
                success=False,
                error=str(e)
            )

    async def _apply_device_validated(self, decision: DeviceDecision) -> CommandResult:
        """Apply device decision with proper change detection."""
        entity_id = decision.entity_id
        hvac_mode = decision.hvac_mode
        target_temp = decision.target_temp
        target_fan = decision.target_fan

        if hvac_mode is None:
            _LOGGER.debug("No HVAC mode specified for %s; leaving device untouched", entity_id)
            self._last_commands.pop(entity_id, None)
            return CommandResult(entity_id=entity_id, success=True)

        state = self._hass.states.get(entity_id)
        if not state:
            _LOGGER.debug("Skipping %s – entity not found in state machine", entity_id)
            return CommandResult(entity_id=entity_id, success=False, error="Entity not found")

        last_command = self._last_commands.get(entity_id, {})
        commands_sent = []
        hvac_changed = False

        # Get device-specific settle times
        settle_seconds, final_settle = await self._get_device_settle_times(entity_id)

        try:
            # Check HVAC mode change
            if hvac_mode != last_command.get("hvac_mode"):
                await self._send_hvac_mode(entity_id, hvac_mode)
                commands_sent.append("hvac_mode")
                hvac_changed = True
                
                if settle_seconds > 0:
                    await asyncio.sleep(settle_seconds)

            # Check temperature change (with epsilon comparison)
            last_temp = last_command.get("temperature")
            if (target_temp is not None and 
                (last_temp is None or abs(target_temp - last_temp) > TEMPERATURE_EPSILON)):
                await self._send_temperature(entity_id, target_temp)
                commands_sent.append("temperature")

            # Check fan mode change
            if (target_fan and 
                target_fan != last_command.get("fan_mode") and
                await self._device_supports_fan_mode(entity_id)):
                await self._send_fan_mode(entity_id, target_fan)
                commands_sent.append("fan_mode")

            # Final settle after HVAC mode changes
            if hvac_changed and final_settle > 0:
                await asyncio.sleep(final_settle)

            # Update command history
            self._last_commands[entity_id] = {
                "hvac_mode": hvac_mode,
                "temperature": target_temp,
                "fan_mode": target_fan,
            }

            _LOGGER.debug("Applied commands to %s: %s", entity_id, commands_sent)
            return CommandResult(entity_id=entity_id, success=True)

        except Exception as e:
            _LOGGER.error("Failed to apply commands to %s: %s", entity_id, e)
            return CommandResult(entity_id=entity_id, success=False, error=str(e))

    async def _validate_device_decision(self, decision: DeviceDecision) -> bool:
        """Validate that device supports the requested operations."""
        entity_id = decision.entity_id
        
        # Check if entity exists
        state = self._hass.states.get(entity_id)
        if not state:
            _LOGGER.error("Entity %s not found", entity_id)
            return False
        
        # Check domain
        if not entity_id.startswith("climate."):
            _LOGGER.error("Entity %s is not a climate device", entity_id)
            return False
        
        # Cache device capabilities
        if entity_id not in self._device_capabilities:
            self._device_capabilities[entity_id] = await self._get_device_capabilities(entity_id)
        
        capabilities = self._device_capabilities[entity_id]
        
        # Validate HVAC mode support
        supported_modes = capabilities.get("hvac_modes", [])
        if decision.hvac_mode and decision.hvac_mode not in supported_modes:
            _LOGGER.warning(
                "Device %s does not support HVAC mode %s (supported: %s)",
                entity_id, decision.hvac_mode, supported_modes
            )
            return False
        
        # Validate fan mode support (don't fail validation, just skip fan mode)
        if decision.target_fan:
            supported_fan_modes = capabilities.get("fan_modes", [])
            if decision.target_fan not in supported_fan_modes:
                _LOGGER.warning(
                    "Device %s does not support fan mode %s (supported: %s)",
                    entity_id, decision.target_fan, supported_fan_modes
                )
                # Modify decision to skip unsupported fan mode
                decision.target_fan = None
        
        return True

    async def _get_device_capabilities(self, entity_id: str) -> Dict[str, Any]:
        """Get device capabilities from state attributes."""
        state = self._hass.states.get(entity_id)
        if not state:
            return {}
        
        return {
            "hvac_modes": state.attributes.get("hvac_modes", []),
            "fan_modes": state.attributes.get("fan_modes", []),
            "supported_features": state.attributes.get("supported_features", 0),
        }

    async def _device_supports_fan_mode(self, entity_id: str) -> bool:
        """Check if device supports fan mode control."""
        capabilities = self._device_capabilities.get(entity_id, {})
        supported_features = capabilities.get("supported_features", 0)
        return bool(supported_features & SUPPORT_FAN_MODE)

    async def _send_hvac_mode(self, entity_id: str, hvac_mode: str):
        """Send HVAC mode command with validation."""
        await self._hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": hvac_mode},
            blocking=True,
        )

    async def _send_temperature(self, entity_id: str, temperature: float):
        """Send temperature command with validation."""
        await self._hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": temperature},
            blocking=True,
        )

    async def _send_fan_mode(self, entity_id: str, fan_mode: str):
        """Send fan mode command with validation."""
        await self._hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": entity_id, "fan_mode": fan_mode},
            blocking=True,
        )

    def reset_history(self) -> None:
        """Forget previously issued commands."""
        self._last_commands.clear()
        self._timed_out_devices.clear()
        self._force_refresh_devices.clear()
        self._device_capabilities.clear()

    async def _get_device_timeout(self, entity_id: str) -> int:
        """Get timeout based on device type."""
        try:
            device_registry = dr.async_get(self._hass)
            entity_registry = er.async_get(self._hass)
            
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry and entity_entry.device_id:
                device_entry = device_registry.async_get(entity_entry.device_id)
                if device_entry:
                    for integration in device_entry.identifiers:
                        if integration[0] in DEVICE_TIMEOUT_OVERRIDES:
                            _LOGGER.debug(
                                "Using %ds timeout for %s device %s",
                                DEVICE_TIMEOUT_OVERRIDES[integration[0]],
                                integration[0],
                                entity_id
                            )
                            return DEVICE_TIMEOUT_OVERRIDES[integration[0]]
        except Exception as e:
            _LOGGER.debug("Could not determine device type for %s: %s", entity_id, e)
        
        return SERVICE_CALL_TIMEOUT

    async def _get_device_settle_times(self, entity_id: str) -> tuple[int, int]:
        """Get settle times based on device type."""
        try:
            device_registry = dr.async_get(self._hass)
            entity_registry = er.async_get(self._hass)
            
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry and entity_entry.device_id:
                device_entry = device_registry.async_get(entity_entry.device_id)
                if device_entry:
                    for integration in device_entry.identifiers:
                        if integration[0] in DEVICE_SETTLE_OVERRIDES:
                            overrides = DEVICE_SETTLE_OVERRIDES[integration[0]]
                            return overrides["settle"], overrides["final_settle"]
        except Exception as e:
            _LOGGER.debug("Could not determine device type for %s: %s", entity_id, e)
        
        return self._settle_seconds, self._final_settle

    def _track_device_performance(self, entity_id: str, response_time: float, success: bool):
        """Track device performance metrics."""
        if entity_id not in self._device_response_times:
            self._device_response_times[entity_id] = []
        
        self._device_response_times[entity_id].append(response_time)
        
        # Keep only last 10 measurements per device
        if len(self._device_response_times[entity_id]) > 10:
            self._device_response_times[entity_id] = self._device_response_times[entity_id][-10:]
