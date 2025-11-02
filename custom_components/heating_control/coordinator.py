"""DataUpdateCoordinator for heating_control."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.const import STATE_HOME
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_AUTO_HEATING_ENABLED,
    CONF_CLIMATE_DEVICES,
    CONF_DEVICE_TRACKERS,
    CONF_SCHEDULES,
    CONF_SCHEDULE_DEVICES,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_FAN_MODE,
    CONF_SCHEDULE_ID,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_ONLY_WHEN_HOME,
    CONF_SCHEDULE_HVAC_MODE,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_TEMPERATURE,
    DEFAULT_FINAL_SETTLE,
    DEFAULT_SCHEDULE_END,
    DEFAULT_SCHEDULE_FAN_MODE,
    DEFAULT_SCHEDULE_HVAC_MODE,
    DEFAULT_SCHEDULE_START,
    DEFAULT_SCHEDULE_TEMPERATURE,
    DEFAULT_SETTLE_SECONDS,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .controller import ClimateController
from .models import DeviceDecision, DiagnosticsSnapshot, HeatingStateSnapshot, ScheduleDecision

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
                await self._controller.async_apply(snapshot.device_decisions.values())
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
    def _derive_auto_end_times(schedules: List[dict]) -> Dict[str, str]:
        """Derive implicit end times using the next enabled schedule start time."""
        timeline: List[Tuple[int, int, str, str]] = []

        for index, schedule in enumerate(schedules):
            if schedule.get(CONF_SCHEDULE_END):
                continue
            if not schedule.get(CONF_SCHEDULE_ENABLED, True):
                continue

            schedule_id = (
                schedule.get(CONF_SCHEDULE_ID)
                or schedule.get(CONF_SCHEDULE_NAME)
                or f"schedule_{index}"
            )
            raw_start = str(schedule.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START))
            start_hm = raw_start[:5]

            try:
                hours, minutes = start_hm.split(":")
                start_minutes = int(hours) * 60 + int(minutes)
            except (ValueError, AttributeError):
                start_hm = DEFAULT_SCHEDULE_START
                hours, minutes = start_hm.split(":")
                start_minutes = int(hours) * 60 + int(minutes)

            timeline.append((start_minutes, index, schedule_id, start_hm))

        if not timeline:
            return {}

        timeline.sort()
        derived: Dict[str, str] = {}
        total = len(timeline)

        for position, (_, _, schedule_id, start_hm) in enumerate(timeline):
            if total == 1:
                derived[schedule_id] = DEFAULT_SCHEDULE_END
                continue

            derived_end = DEFAULT_SCHEDULE_END
            for offset in range(1, total):
                candidate = timeline[(position + offset) % total][3]
                if candidate != start_hm:
                    derived_end = candidate
                    break

            derived[schedule_id] = derived_end

        return derived

    @staticmethod
    def _is_time_in_schedule(now_hm: str, start_hm: str, end_hm: str) -> bool:
        """Check if current time is within schedule."""
        if start_hm == end_hm:
            return True

        spans_midnight = end_hm < start_hm
        if not spans_midnight:
            return start_hm <= now_hm < end_hm
        return now_hm >= start_hm or now_hm < end_hm

    def _calculate_heating_state(self) -> HeatingStateSnapshot:
        """Calculate the current heating state based on configuration."""
        config = self.config_entry.options or self.config_entry.data
        now = datetime.now()
        now_hm = now.strftime("%H:%M")

        tracker_states, anyone_home, everyone_away = self._resolve_presence(config)
        tracker_states = dict(tracker_states)

        auto_heating_enabled = config.get(CONF_AUTO_HEATING_ENABLED, True)

        schedule_decisions, device_builders = self._evaluate_schedules(
            config,
            now_hm,
            anyone_home,
            auto_heating_enabled,
        )

        device_decisions = self._finalize_device_decisions(
            config,
            device_builders,
        )

        diagnostics = DiagnosticsSnapshot(
            now_time=now_hm,
            tracker_states=tracker_states,
            trackers_home=sum(tracker_states.values()),
            trackers_total=len(tracker_states),
            auto_heating_enabled=auto_heating_enabled,
            schedule_count=len(config.get(CONF_SCHEDULES, [])),
            active_schedules=sum(dec.is_active for dec in schedule_decisions.values()),
            active_devices=sum(
                dec.should_be_active for dec in device_decisions.values()
            ),
        )

        return HeatingStateSnapshot(
            everyone_away=everyone_away,
            anyone_home=anyone_home,
            schedule_decisions=schedule_decisions,
            device_decisions=device_decisions,
            diagnostics=diagnostics,
        )

    def _resolve_presence(self, config) -> Tuple[Dict[str, bool], bool, bool]:
        """Determine presence based on configured device trackers."""
        tracker_entities = [
            tracker for tracker in config.get(CONF_DEVICE_TRACKERS, []) if tracker
        ]

        if not tracker_entities:
            # Presence tracking disabled; assume occupants are home so schedules remain eligible.
            return {}, True, False

        tracker_states: Dict[str, bool] = {}
        for tracker in tracker_entities:
            tracker_states[tracker] = self._is_tracker_home(tracker)

        anyone_home = any(tracker_states.values())
        everyone_away = not anyone_home

        return tracker_states, anyone_home, everyone_away

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
        Dict[str, List[Dict[str, Any]]],
    ]:
        """Evaluate all configured schedules and prepare device aggregations."""
        schedules = config.get(CONF_SCHEDULES, [])
        schedule_decisions: Dict[str, ScheduleDecision] = {}
        device_builders: Dict[str, List[Dict[str, Any]]] = {}

        auto_end_times = self._derive_auto_end_times(schedules)

        for index, schedule in enumerate(schedules):
            schedule_id = (
                schedule.get(CONF_SCHEDULE_ID)
                or schedule.get(CONF_SCHEDULE_NAME)
                or f"schedule_{index}"
            )
            schedule_name = schedule.get(CONF_SCHEDULE_NAME, "Unnamed")
            enabled = schedule.get(CONF_SCHEDULE_ENABLED, True)
            start_time = str(schedule.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START))[:5]
            configured_end = schedule.get(CONF_SCHEDULE_END)
            if configured_end:
                end_time = str(configured_end)[:5]
            else:
                end_time = auto_end_times.get(schedule_id, DEFAULT_SCHEDULE_END)
            only_when_home = schedule.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True)
            hvac_mode = str(
                schedule.get(CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE)
            ).lower()
            device_entities = schedule.get(CONF_SCHEDULE_DEVICES, [])
            schedule_temp = float(
                schedule.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE)
            )
            schedule_fan = schedule.get(
                CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE
            )

            in_time_window = self._is_time_in_schedule(
                now_hm, start_time, end_time
            )
            presence_ok = (not only_when_home) or anyone_home
            is_active = (
                auto_heating_enabled and enabled and in_time_window and presence_ok
            )

            schedule_decisions[schedule_id] = ScheduleDecision(
                schedule_id=schedule_id,
                name=schedule_name,
                start_time=start_time,
                end_time=end_time,
                hvac_mode=hvac_mode,
                only_when_home=only_when_home,
                enabled=enabled,
                is_active=is_active,
                in_time_window=in_time_window,
                presence_ok=presence_ok,
                device_count=len(device_entities),
                devices=tuple(device_entities),
                target_temp=schedule_temp,
                target_fan=schedule_fan,
            )

            if not is_active:
                continue

            for device_entity in device_entities:
                device_builders.setdefault(device_entity, []).append(
                    {
                        "schedule_name": schedule_name,
                        "order": index,
                        "hvac_mode": hvac_mode,
                        "temperature": schedule_temp,
                        "fan_mode": schedule_fan,
                    }
                )

        return schedule_decisions, device_builders

    def _finalize_device_decisions(
        self,
        config,
        device_builders: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, DeviceDecision]:
        """Create DeviceDecision objects for each configured device."""
        all_devices = config.get(CONF_CLIMATE_DEVICES, [])
        device_decisions: Dict[str, DeviceDecision] = {}

        for device_entity in all_devices:
            entries = device_builders.get(device_entity, [])
            active_schedules = tuple(entry["schedule_name"] for entry in entries)

            hvac_mode, target_temp, target_fan = self._select_device_targets(entries)

            should_be_active = hvac_mode != "off"
            if target_temp is None:
                target_temp = DEFAULT_SCHEDULE_TEMPERATURE
            if target_fan is None:
                target_fan = DEFAULT_SCHEDULE_FAN_MODE

            device_decisions[device_entity] = DeviceDecision(
                entity_id=device_entity,
                should_be_active=should_be_active,
                active_schedules=active_schedules,
                hvac_mode=hvac_mode,
                target_temp=target_temp,
                target_fan=target_fan,
            )

        return device_decisions

    @staticmethod
    def _select_device_targets(
        entries: List[Dict[str, Any]]
    ) -> Tuple[str, Optional[float], Optional[str]]:
        """Select the hvac mode, temperature, and fan for a device."""
        if not entries:
            return "off", None, None

        hvac_priority = {
            "off": 3,
            "heat": 2,
            "cool": 2,
            "dry": 1,
            "fan_only": 1,
            "auto": 1,
        }

        def entry_key(entry: Dict[str, Any]) -> Tuple[int, float, int]:
            mode = entry.get("hvac_mode", "heat")
            priority = hvac_priority.get(mode, 1)
            temperature = entry.get("temperature")
            temp_value = temperature if temperature is not None else float("-inf")
            order = entry.get("order", 0)
            return (priority, temp_value, -order)

        best = max(entries, key=entry_key)
        mode = best.get("hvac_mode", "heat")

        if mode == "off":
            return "off", None, None

        return mode, best.get("temperature"), best.get("fan_mode")

    async def async_set_schedule_enabled(
        self,
        *,
        schedule_id: Optional[str] = None,
        schedule_name: Optional[str] = None,
        enabled: bool,
    ) -> bool:
        """Enable or disable a schedule and persist the change."""
        config_entry = self.config_entry
        source = config_entry.options or config_entry.data
        schedules = source.get(CONF_SCHEDULES, [])

        if not schedules:
            raise ValueError("No schedules are configured for this entry")

        new_schedules = deepcopy(schedules)
        target_name = schedule_name.casefold() if schedule_name else None
        target_id_casefold = schedule_id.casefold() if schedule_id else None
        updated = False
        matched = False

        for schedule in new_schedules:
            current_id = schedule.get(CONF_SCHEDULE_ID)
            current_name = schedule.get(CONF_SCHEDULE_NAME, "")

            id_matches = False
            if schedule_id:
                if current_id == schedule_id:
                    id_matches = True
                elif not current_id and current_name.casefold() == target_id_casefold:
                    id_matches = True

            name_matches = (
                target_name is not None and current_name.casefold() == target_name
            )

            if not id_matches and not name_matches:
                continue

            matched = True

            if schedule.get(CONF_SCHEDULE_ENABLED, True) == enabled:
                break

            schedule[CONF_SCHEDULE_ENABLED] = enabled
            updated = True
            break

        if not matched:
            identifier = schedule_id or schedule_name or "unknown"
            raise ValueError(f"Schedule '{identifier}' was not found")

        if not updated:
            _LOGGER.debug(
                "Schedule %s already %s",
                schedule_id or schedule_name,
                "enabled" if enabled else "disabled",
            )
            return False

        update_kwargs: Dict[str, Dict] = {}
        if config_entry.options:
            new_options = dict(config_entry.options)
            new_options[CONF_SCHEDULES] = new_schedules
            update_kwargs["options"] = new_options
        else:
            new_data = dict(config_entry.data)
            new_data[CONF_SCHEDULES] = new_schedules
            update_kwargs["data"] = new_data

        await self.hass.config_entries.async_update_entry(
            config_entry, **update_kwargs
        )

        # Ensure the new configuration is applied promptly.
        self._force_update = True
        return True
