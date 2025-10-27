"""DataUpdateCoordinator for heating_control."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple

from homeassistant.const import STATE_HOME
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_AUTO_HEATING_ENABLED,
    CONF_CLIMATE_DEVICES,
    CONF_DEVICE_TRACKER_1,
    CONF_DEVICE_TRACKER_2,
    CONF_GAS_HEATER_ENTITY,
    CONF_ONLY_SCHEDULED_ACTIVE,
    CONF_SCHEDULES,
    CONF_SCHEDULE_ALWAYS_ACTIVE,
    CONF_SCHEDULE_DEVICES,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_FAN_MODE,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_ONLY_WHEN_HOME,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_TEMPERATURE,
    CONF_SCHEDULE_USE_GAS,
    DEFAULT_FINAL_SETTLE,
    DEFAULT_ONLY_SCHEDULED_ACTIVE,
    DEFAULT_SCHEDULE_FAN_MODE,
    DEFAULT_SCHEDULE_TEMPERATURE,
    DEFAULT_SETTLE_SECONDS,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .controller import ClimateController
from .models import (
    DeviceDecision,
    DiagnosticsSnapshot,
    GasHeaterDecision,
    HeatingStateSnapshot,
    ScheduleDecision,
)

_LOGGER = logging.getLogger(__name__)


class HeatingControlCoordinator(DataUpdateCoordinator[HeatingStateSnapshot]):
    """Class to manage fetching heating control data."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        """Initialize."""
        self.config_entry = config_entry
        self.hass = hass

        self._controller = ClimateController(
            hass,
            settle_seconds=DEFAULT_SETTLE_SECONDS,
            final_settle=DEFAULT_FINAL_SETTLE,
        )
        self._previous_schedule_states: Optional[Dict[str, bool]] = None
        self._previous_presence_state: Optional[bool] = None
        self._force_update = False

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    async def _async_update_data(self) -> HeatingStateSnapshot:
        """Update data and apply control decisions."""
        try:
            snapshot = await self.hass.async_add_executor_job(
                self._calculate_heating_state
            )

            should_apply_control = self._detect_state_transitions(snapshot)

            if should_apply_control:
                _LOGGER.info("State transition detected, applying control decisions")
                await self._controller.async_apply(
                    snapshot.device_decisions.values(),
                    snapshot.gas_heater_decision,
                )
            else:
                _LOGGER.debug(
                    "No state transitions, skipping control application (preserving manual changes)"
                )

            self._update_previous_states(snapshot)
            return snapshot
        except Exception as err:
            raise UpdateFailed(f"Error updating heating control: {err}") from err

    def _detect_state_transitions(self, snapshot: HeatingStateSnapshot) -> bool:
        """Detect if any schedule states or presence changed."""
        if self._force_update:
            _LOGGER.info("Forced update requested")
            self._force_update = False
            self._controller.reset_history()
            return True

        if (
            self._previous_schedule_states is None
            or self._previous_presence_state is None
        ):
            _LOGGER.info("First run, applying initial state")
            return True

        if snapshot.anyone_home != self._previous_presence_state:
            _LOGGER.info(
                "Presence changed: %s -> %s",
                self._previous_presence_state,
                snapshot.anyone_home,
            )
            return True

        for schedule_id, decision in snapshot.schedule_decisions.items():
            current_active = decision.is_active
            previous_active = self._previous_schedule_states.get(schedule_id, False)

            if current_active != previous_active:
                _LOGGER.info(
                    "Schedule '%s' state changed: %s -> %s",
                    decision.name,
                    previous_active,
                    current_active,
                )
                return True

        for schedule_id in self._previous_schedule_states:
            if schedule_id not in snapshot.schedule_decisions:
                _LOGGER.info("Schedule %s was removed", schedule_id)
                return True

        return False

    def _update_previous_states(self, snapshot: HeatingStateSnapshot) -> None:
        """Update stored state for next cycle comparisons."""
        self._previous_presence_state = snapshot.anyone_home
        self._previous_schedule_states = {
            schedule_id: decision.is_active
            for schedule_id, decision in snapshot.schedule_decisions.items()
        }

    def force_update_on_next_refresh(self) -> None:
        """Force control application on next update (for config changes)."""
        _LOGGER.info("Forcing update on next refresh")
        self._force_update = True

    @staticmethod
    def _is_time_in_schedule(now_hm: str, start_hm: str, end_hm: str) -> bool:
        """Check if current time is within schedule."""
        if start_hm == end_hm:
            return False

        spans_midnight = end_hm < start_hm
        if not spans_midnight:
            return start_hm <= now_hm < end_hm
        return now_hm >= start_hm or now_hm < end_hm

    def _calculate_heating_state(self) -> HeatingStateSnapshot:
        """Calculate the current heating state based on configuration."""
        config = self.config_entry.options or self.config_entry.data
        now = datetime.now()
        now_hm = now.strftime("%H:%M")

        (
            tracker_1_home,
            tracker_2_home,
            anyone_home,
            both_away,
        ) = self._resolve_presence(config)

        auto_heating_enabled = config.get(CONF_AUTO_HEATING_ENABLED, True)
        only_scheduled_active = config.get(
            CONF_ONLY_SCHEDULED_ACTIVE, DEFAULT_ONLY_SCHEDULED_ACTIVE
        )

        schedule_decisions, device_builders, gas_heater_sources = self._evaluate_schedules(
            config,
            now_hm,
            anyone_home,
            auto_heating_enabled,
        )

        device_decisions = self._finalize_device_decisions(
            config,
            device_builders,
            anyone_home,
            auto_heating_enabled,
            only_scheduled_active,
        )

        gas_heater_decision = self._build_gas_heater_decision(
            config, gas_heater_sources
        )

        diagnostics = DiagnosticsSnapshot(
            now_time=now_hm,
            tracker_1_home=tracker_1_home,
            tracker_2_home=tracker_2_home,
            auto_heating_enabled=auto_heating_enabled,
            only_scheduled_active=only_scheduled_active,
            schedule_count=len(config.get(CONF_SCHEDULES, [])),
            active_schedules=sum(dec.is_active for dec in schedule_decisions.values()),
            active_devices=sum(
                dec.should_be_active for dec in device_decisions.values()
            ),
        )

        return HeatingStateSnapshot(
            both_away=both_away,
            anyone_home=anyone_home,
            schedule_decisions=schedule_decisions,
            device_decisions=device_decisions,
            gas_heater_decision=gas_heater_decision,
            diagnostics=diagnostics,
        )

    def _resolve_presence(self, config) -> Tuple[bool, bool, bool, bool]:
        """Determine presence based on configured device trackers."""
        device_tracker_1 = config.get(CONF_DEVICE_TRACKER_1)
        device_tracker_2 = config.get(CONF_DEVICE_TRACKER_2)

        tracker_1_home = self._is_tracker_home(device_tracker_1)
        tracker_2_home = self._is_tracker_home(device_tracker_2)

        anyone_home = tracker_1_home or tracker_2_home
        both_away = not anyone_home

        return tracker_1_home, tracker_2_home, anyone_home, both_away

    def _is_tracker_home(self, entity_id: Optional[str]) -> bool:
        """Return True if the given tracker entity is in STATE_HOME."""
        if not entity_id:
            return False

        state: Optional[State] = self.hass.states.get(entity_id)
        return bool(state and state.state == STATE_HOME)

    def _evaluate_schedules(
        self,
        config,
        now_hm: str,
        anyone_home: bool,
        auto_heating_enabled: bool,
    ) -> Tuple[
        Dict[str, ScheduleDecision],
        Dict[str, Dict[str, List]],
        List[Dict[str, object]],
    ]:
        """Evaluate all configured schedules and prepare device aggregations."""
        schedules = config.get(CONF_SCHEDULES, [])
        schedule_decisions: Dict[str, ScheduleDecision] = {}
        device_builders: Dict[str, Dict[str, List]] = {}
        gas_heater_sources: List[Dict[str, object]] = []

        for schedule in schedules:
            schedule_id = schedule.get("id") or schedule.get(CONF_SCHEDULE_NAME, "unnamed")
            schedule_name = schedule.get(CONF_SCHEDULE_NAME, "Unnamed")
            enabled = schedule.get(CONF_SCHEDULE_ENABLED, True)
            always_active = schedule.get(CONF_SCHEDULE_ALWAYS_ACTIVE, False)
            start_time = str(schedule.get(CONF_SCHEDULE_START, "00:00"))[:5]
            end_time = str(schedule.get(CONF_SCHEDULE_END, "23:59"))[:5]
            only_when_home = schedule.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True)
            use_gas_heater = schedule.get(CONF_SCHEDULE_USE_GAS, False)
            device_entities = schedule.get(CONF_SCHEDULE_DEVICES, [])
            schedule_temp = float(
                schedule.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE)
            )
            schedule_fan = schedule.get(
                CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE
            )

            in_time_window = always_active or self._is_time_in_schedule(
                now_hm, start_time, end_time
            )
            presence_ok = (not only_when_home) or anyone_home
            is_active = (
                auto_heating_enabled and enabled and in_time_window and presence_ok
            )

            schedule_decisions[schedule_id] = ScheduleDecision(
                schedule_id=schedule_id,
                name=schedule_name,
                enabled=enabled,
                is_active=is_active,
                in_time_window=in_time_window,
                presence_ok=presence_ok,
                use_gas_heater=use_gas_heater,
                device_count=len(device_entities),
                devices=tuple(device_entities),
                target_temp=schedule_temp,
                target_fan=schedule_fan,
            )

            if not is_active:
                continue

            if use_gas_heater:
                gas_heater_sources.append(
                    {"name": schedule_name, "temp": schedule_temp, "fan": schedule_fan}
                )
                continue

            for device_entity in device_entities:
                builder = device_builders.setdefault(
                    device_entity,
                    {
                        "active_schedules": [],
                        "temperatures": [],
                        "fan_modes": [],
                        "should_be_active": False,
                    },
                )
                builder["active_schedules"].append(schedule_name)
                builder["temperatures"].append(schedule_temp)
                builder["fan_modes"].append(schedule_fan)
                builder["should_be_active"] = True

        return schedule_decisions, device_builders, gas_heater_sources

    def _finalize_device_decisions(
        self,
        config,
        device_builders: Dict[str, Dict[str, List]],
        anyone_home: bool,
        auto_heating_enabled: bool,
        only_scheduled_active: bool,
    ) -> Dict[str, DeviceDecision]:
        """Create DeviceDecision objects for each configured device."""
        all_devices = config.get(CONF_CLIMATE_DEVICES, [])
        device_decisions: Dict[str, DeviceDecision] = {}

        for device_entity in all_devices:
            builder = device_builders.setdefault(
                device_entity,
                {
                    "active_schedules": [],
                    "temperatures": [],
                    "fan_modes": [],
                    "should_be_active": False,
                },
            )

            if not builder["should_be_active"]:
                builder["should_be_active"] = (
                    not only_scheduled_active and auto_heating_enabled and anyone_home
                )

            temperatures = builder["temperatures"]
            fan_modes = builder["fan_modes"]

            if temperatures:
                max_temp = max(temperatures)
                max_temp_idx = temperatures.index(max_temp)
                target_temp = max_temp
                target_fan = fan_modes[max_temp_idx]
            else:
                target_temp = DEFAULT_SCHEDULE_TEMPERATURE
                target_fan = DEFAULT_SCHEDULE_FAN_MODE

            device_decisions[device_entity] = DeviceDecision(
                entity_id=device_entity,
                should_be_active=builder["should_be_active"],
                active_schedules=tuple(builder["active_schedules"]),
                target_temp=target_temp,
                target_fan=target_fan,
            )

        return device_decisions

    def _build_gas_heater_decision(
        self, config, gas_heater_sources: List[Dict[str, object]]
    ) -> Optional[GasHeaterDecision]:
        """Return the gas heater decision for the current cycle."""
        gas_heater_entity = config.get(CONF_GAS_HEATER_ENTITY)
        if not gas_heater_entity:
            return None

        should_be_active = False
        target_temp = DEFAULT_SCHEDULE_TEMPERATURE
        target_fan = DEFAULT_SCHEDULE_FAN_MODE
        active_schedule_names: List[str] = []

        if gas_heater_sources:
            temps = [source["temp"] for source in gas_heater_sources]
            max_temp = max(temps)
            max_temp_idx = temps.index(max_temp)
            should_be_active = True
            target_temp = max_temp
            target_fan = gas_heater_sources[max_temp_idx]["fan"]
            active_schedule_names = [source["name"] for source in gas_heater_sources]

        return GasHeaterDecision(
            entity_id=gas_heater_entity,
            should_be_active=should_be_active,
            target_temp=target_temp,
            target_fan=target_fan,
            active_schedules=tuple(active_schedule_names),
        )
