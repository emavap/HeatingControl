"""DataUpdateCoordinator for heating_control."""
from datetime import datetime, timedelta
import logging
import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DOMAIN,
    UPDATE_INTERVAL,
    CONF_DEVICE_TRACKER_1,
    CONF_DEVICE_TRACKER_2,
    CONF_AUTO_HEATING_ENABLED,
    CONF_GAS_HEATER_ENTITY,
    CONF_ONLY_SCHEDULED_ACTIVE,
    CONF_SCHEDULES,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_ALWAYS_ACTIVE,
    CONF_SCHEDULE_ONLY_WHEN_HOME,
    CONF_SCHEDULE_USE_GAS,
    CONF_SCHEDULE_DEVICES,
    CONF_SCHEDULE_TEMPERATURE,
    CONF_SCHEDULE_FAN_MODE,
    CONF_CLIMATE_DEVICES,
    DEFAULT_ONLY_SCHEDULED_ACTIVE,
    DEFAULT_SCHEDULE_TEMPERATURE,
    DEFAULT_SCHEDULE_FAN_MODE,
    DEFAULT_SETTLE_SECONDS,
    DEFAULT_FINAL_SETTLE,
)

_LOGGER = logging.getLogger(__name__)


class HeatingControlCoordinator(DataUpdateCoordinator):
    """Class to manage fetching heating control data."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        """Initialize."""
        self.config_entry = config_entry
        self.hass = hass
        self._previous_state = {}

        # Track previous schedule states to detect transitions
        self._previous_schedule_states = {}  # schedule_id -> is_active
        self._previous_presence_state = None  # anyone_home state
        self._force_update = False  # Force update on config changes

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    async def _async_update_data(self):
        """Update data and apply control decisions."""
        try:
            # Calculate heating decisions
            data = await self.hass.async_add_executor_job(self._calculate_heating_state)

            # Check if we need to apply control (only on state transitions)
            should_apply_control = self._detect_state_transitions(data)

            if should_apply_control:
                _LOGGER.info("State transition detected, applying control decisions")
                # Apply control decisions to devices
                await self._apply_control_decisions(data)
            else:
                _LOGGER.debug("No state transitions, skipping control application (preserving manual changes)")

            # Update previous states for next cycle
            self._update_previous_states(data)

            return data
        except Exception as err:
            raise UpdateFailed(f"Error updating heating control: {err}")

    async def _apply_control_decisions(self, data: dict):
        """Apply heating control decisions to actual climate devices."""
        if not data:
            return

        device_decisions = data.get("device_decisions", {})
        gas_heater_decision = data.get("gas_heater_decision", {})

        # Control gas heater
        if gas_heater_decision:
            gas_heater_entity = gas_heater_decision.get("entity_id")
            gas_heater_active = gas_heater_decision.get("should_be_active", False)
            target_temp = gas_heater_decision.get("target_temp", DEFAULT_SCHEDULE_TEMPERATURE)
            target_fan = gas_heater_decision.get("target_fan", DEFAULT_SCHEDULE_FAN_MODE)

            if gas_heater_entity:
                await self._control_climate_device(
                    gas_heater_entity,
                    gas_heater_active,
                    target_temp,
                    target_fan
                )

        # Control all climate devices
        for device_entity, decision in device_decisions.items():
            should_be_active = decision.get("should_be_active", False)
            target_temp = decision.get("target_temp", DEFAULT_SCHEDULE_TEMPERATURE)
            target_fan = decision.get("target_fan", DEFAULT_SCHEDULE_FAN_MODE)

            await self._control_climate_device(
                device_entity,
                should_be_active,
                target_temp,
                target_fan
            )

    async def _control_climate_device(
        self,
        entity_id: str,
        should_be_on: bool,
        target_temp: float,
        target_fan: str
    ):
        """Control a single climate device."""
        # Check if entity exists and is available
        state = self.hass.states.get(entity_id)
        if not state or state.state in [STATE_UNAVAILABLE, STATE_UNKNOWN]:
            _LOGGER.debug(f"Climate entity {entity_id} is not available")
            return

        # Get previous state
        previous_state = self._previous_state.get(entity_id, {})
        previous_on = previous_state.get("on", None)

        # Only change if state is different
        if previous_on == should_be_on:
            return

        _LOGGER.info(f"Changing {entity_id}: {'ON' if should_be_on else 'OFF'}")

        try:
            if should_be_on:
                # Turn on heating
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "heat"},
                    blocking=True,
                )

                # Wait for device to settle
                await asyncio.sleep(DEFAULT_SETTLE_SECONDS)

                # Set temperature
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": entity_id, "temperature": target_temp},
                    blocking=True,
                )

                # Try to set fan mode if supported
                fan_modes = state.attributes.get("fan_modes", [])
                if fan_modes and target_fan in fan_modes:
                    await self.hass.services.async_call(
                        "climate",
                        "set_fan_mode",
                        {"entity_id": entity_id, "fan_mode": target_fan},
                        blocking=True,
                    )

                # Final settle
                await asyncio.sleep(DEFAULT_FINAL_SETTLE)

                _LOGGER.info(f"{entity_id} turned ON at {target_temp}°C, fan={target_fan}")

            else:
                # Turn off heating
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "off"},
                    blocking=True,
                )

                _LOGGER.info(f"{entity_id} turned OFF")

            # Update previous state
            self._previous_state[entity_id] = {"on": should_be_on}

        except Exception as err:
            _LOGGER.error(f"Error controlling {entity_id}: {err}")

    def _detect_state_transitions(self, data: dict) -> bool:
        """Detect if any schedule states or presence changed.

        Returns True if control should be applied (state transition occurred).
        Returns False if no transitions (preserve manual user changes).
        """
        # Force update if requested (e.g., config change)
        if self._force_update:
            _LOGGER.info("Forced update requested")
            self._force_update = False
            return True

        # First run - no previous state
        if self._previous_schedule_states is None or self._previous_presence_state is None:
            _LOGGER.info("First run, applying initial state")
            return True

        # Check for presence changes
        current_presence = data.get("anyone_home")
        if current_presence != self._previous_presence_state:
            _LOGGER.info(f"Presence changed: {self._previous_presence_state} -> {current_presence}")
            return True

        # Check for schedule state transitions
        current_schedule_decisions = data.get("schedule_decisions", {})

        for schedule_id, schedule_data in current_schedule_decisions.items():
            current_active = schedule_data.get("is_active", False)
            previous_active = self._previous_schedule_states.get(schedule_id, False)

            if current_active != previous_active:
                schedule_name = schedule_data.get("name", schedule_id)
                _LOGGER.info(f"Schedule '{schedule_name}' state changed: {previous_active} -> {current_active}")
                return True

        # Check for schedules that were removed
        for schedule_id in self._previous_schedule_states:
            if schedule_id not in current_schedule_decisions:
                _LOGGER.info(f"Schedule {schedule_id} was removed")
                return True

        # No transitions detected
        return False

    def _update_previous_states(self, data: dict) -> None:
        """Update stored previous states for next cycle comparison."""
        # Store current presence state
        self._previous_presence_state = data.get("anyone_home")

        # Store current schedule states
        current_schedule_decisions = data.get("schedule_decisions", {})
        self._previous_schedule_states = {
            schedule_id: schedule_data.get("is_active", False)
            for schedule_id, schedule_data in current_schedule_decisions.items()
        }

    def force_update_on_next_refresh(self) -> None:
        """Force control application on next update (for config changes)."""
        _LOGGER.info("Forcing update on next refresh")
        self._force_update = True

    def _is_time_in_schedule(self, now_hm: str, start_hm: str, end_hm: str) -> bool:
        """Check if current time is within schedule."""
        if start_hm == end_hm:
            # Zero length window
            return False

        spans_midnight = end_hm < start_hm

        if not spans_midnight:
            return start_hm <= now_hm < end_hm
        else:
            return (now_hm >= start_hm) or (now_hm < end_hm)

    def _calculate_heating_state(self):
        """Calculate the current heating state based on configuration."""
        config = self.config_entry.options or self.config_entry.data

        # Get current time
        now = datetime.now()
        now_hm = now.strftime("%H:%M")

        # Get global configuration
        auto_heating_enabled = config.get(CONF_AUTO_HEATING_ENABLED, True)
        gas_heater_entity = config.get(CONF_GAS_HEATER_ENTITY)
        only_scheduled_active = config.get(
            CONF_ONLY_SCHEDULED_ACTIVE, DEFAULT_ONLY_SCHEDULED_ACTIVE
        )

        # Get presence status
        device_tracker_1 = config.get(CONF_DEVICE_TRACKER_1)
        device_tracker_2 = config.get(CONF_DEVICE_TRACKER_2)

        tracker_1_home = False
        tracker_2_home = False

        if device_tracker_1:
            state_1 = self.hass.states.get(device_tracker_1)
            tracker_1_home = state_1 and state_1.state == STATE_HOME

        if device_tracker_2:
            state_2 = self.hass.states.get(device_tracker_2)
            tracker_2_home = state_2 and state_2.state == STATE_HOME

        both_away = not tracker_1_home and not tracker_2_home
        anyone_home = tracker_1_home or tracker_2_home

        # Get schedules and evaluate them
        schedules = config.get(CONF_SCHEDULES, [])
        schedule_decisions = {}
        device_decisions = {}  # Will track which devices should be active (and from which schedules)
        gas_heater_schedules = []  # Track schedules that want gas heater with their settings

        for schedule in schedules:
            schedule_id = schedule.get("id")
            schedule_name = schedule.get(CONF_SCHEDULE_NAME, "Unnamed")
            enabled = schedule.get(CONF_SCHEDULE_ENABLED, True)
            always_active = schedule.get(CONF_SCHEDULE_ALWAYS_ACTIVE, False)
            start_time = schedule.get(CONF_SCHEDULE_START, "00:00")[:5]
            end_time = schedule.get(CONF_SCHEDULE_END, "23:59")[:5]
            only_when_home = schedule.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True)
            use_gas_heater = schedule.get(CONF_SCHEDULE_USE_GAS, False)
            device_entities = schedule.get(CONF_SCHEDULE_DEVICES, [])
            schedule_temp = float(schedule.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE))
            schedule_fan = schedule.get(CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE)

            # Determine if schedule is currently active
            is_active = False

            if auto_heating_enabled and enabled:
                # Check time window
                in_time_window = always_active or self._is_time_in_schedule(now_hm, start_time, end_time)

                # Check presence requirement
                presence_ok = (not only_when_home) or anyone_home

                is_active = in_time_window and presence_ok

            schedule_decision = {
                "schedule_id": schedule_id,
                "name": schedule_name,
                "enabled": enabled,
                "is_active": is_active,
                "in_time_window": always_active or self._is_time_in_schedule(now_hm, start_time, end_time),
                "presence_ok": (not only_when_home) or anyone_home,
                "use_gas_heater": use_gas_heater,
                "device_count": len(device_entities),
                "devices": device_entities,
                "target_temp": schedule_temp,
                "target_fan": schedule_fan,
            }

            schedule_decisions[schedule_id] = schedule_decision

            # If schedule is active, process its device assignments
            if is_active:
                if use_gas_heater:
                    # This schedule wants the gas heater
                    gas_heater_schedules.append({
                        "name": schedule_name,
                        "temp": schedule_temp,
                        "fan": schedule_fan,
                    })
                elif device_entities:
                    # This schedule wants its devices to be active
                    for device_entity in device_entities:
                        if device_entity not in device_decisions:
                            device_decisions[device_entity] = {
                                "entity_id": device_entity,
                                "should_be_active": True,
                                "active_schedules": [],
                                "temperatures": [],
                                "fan_modes": [],
                            }
                        device_decisions[device_entity]["active_schedules"].append(schedule_name)
                        device_decisions[device_entity]["temperatures"].append(schedule_temp)
                        device_decisions[device_entity]["fan_modes"].append(schedule_fan)

        # Build device status for all configured devices
        all_devices = config.get(CONF_CLIMATE_DEVICES, [])
        for device_entity in all_devices:
            if device_entity not in device_decisions:
                should_be_active = False
                if (
                    not only_scheduled_active
                    and auto_heating_enabled
                    and anyone_home
                ):
                    should_be_active = True
                device_decisions[device_entity] = {
                    "entity_id": device_entity,
                    "should_be_active": should_be_active,
                    "active_schedules": [],
                    "temperatures": [],
                    "fan_modes": [],
                }

        # Calculate final temperature and fan mode for each device (highest temperature wins)
        for device_entity, decision in device_decisions.items():
            temperatures = decision.get("temperatures", [])
            fan_modes = decision.get("fan_modes", [])

            if temperatures:
                # Use highest temperature from active schedules
                decision["target_temp"] = max(temperatures)
                # Use fan mode from the schedule with highest temperature
                max_temp_idx = temperatures.index(max(temperatures))
                decision["target_fan"] = fan_modes[max_temp_idx]
            else:
                # No active schedules, use defaults
                decision["target_temp"] = DEFAULT_SCHEDULE_TEMPERATURE
                decision["target_fan"] = DEFAULT_SCHEDULE_FAN_MODE

        # Calculate gas heater decision (highest temperature from schedules that use it)
        gas_heater_decision = {}
        if gas_heater_entity and gas_heater_schedules:
            temps = [s["temp"] for s in gas_heater_schedules]
            max_temp = max(temps)
            max_temp_idx = temps.index(max_temp)

            gas_heater_decision = {
                "entity_id": gas_heater_entity,
                "should_be_active": True,
                "target_temp": max_temp,
                "target_fan": gas_heater_schedules[max_temp_idx]["fan"],
                "active_schedules": [s["name"] for s in gas_heater_schedules],
            }

        return {
            "both_away": both_away,
            "anyone_home": anyone_home,
            "schedule_decisions": schedule_decisions,
            "device_decisions": device_decisions,
            "gas_heater_decision": gas_heater_decision,
            "diagnostics": {
                "now_time": now_hm,
                "tracker_1_home": tracker_1_home,
                "tracker_2_home": tracker_2_home,
                "auto_heating_enabled": auto_heating_enabled,
                "only_scheduled_active": only_scheduled_active,
                "schedule_count": len(schedules),
                "active_schedules": sum(1 for s in schedule_decisions.values() if s["is_active"]),
                "active_devices": sum(1 for d in device_decisions.values() if d["should_be_active"]),
            }
        }
