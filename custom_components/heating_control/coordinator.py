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
    CONF_SCHEDULE_DEVICE_TRACKERS,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_FAN_MODE,
    CONF_SCHEDULE_ID,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_ONLY_WHEN_HOME,
    CONF_SCHEDULE_HVAC_MODE,
    CONF_SCHEDULE_AWAY_HVAC_MODE,
    CONF_SCHEDULE_AWAY_TEMPERATURE,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_TEMPERATURE,
    DEFAULT_FINAL_SETTLE,
    DEFAULT_SCHEDULE_END,
    DEFAULT_SCHEDULE_FAN_MODE,
    DEFAULT_SCHEDULE_HVAC_MODE,
    DEFAULT_SCHEDULE_AWAY_HVAC_MODE,
    DEFAULT_SCHEDULE_START,
    DEFAULT_SCHEDULE_TEMPERATURE,
    DEFAULT_SETTLE_SECONDS,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .controller import ClimateController
from .models import DeviceDecision, DiagnosticsSnapshot, HeatingStateSnapshot, ScheduleDecision

_LOGGER = logging.getLogger(__name__)

MINUTES_PER_DAY = 24 * 60


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
        """Derive implicit end times per-device to allow overlapping schedules for different devices.

        For each device, schedules run sequentially. A schedule controlling multiple devices
        stays active until the last of its devices has a newer schedule take over.
        """
        # Step 1: Build per-device timelines
        # device_timelines[device_entity] = [(start_minutes, schedule_id, start_hm), ...]
        device_timelines: Dict[str, List[Tuple[int, str, str]]] = {}

        # schedule_info[schedule_id] = (index, start_hm, start_minutes, devices)
        schedule_info: Dict[str, Tuple[int, str, int, List[str]]] = {}

        for index, schedule in enumerate(schedules):
            if schedule.get(CONF_SCHEDULE_END):
                # Has explicit end time, skip auto-calculation
                continue
            if not schedule.get(CONF_SCHEDULE_ENABLED, True):
                # Disabled schedules don't need end times
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

            devices = schedule.get(CONF_SCHEDULE_DEVICES, [])
            schedule_info[schedule_id] = (index, start_hm, start_minutes, devices)

            # Add this schedule to each device's timeline
            for device_entity in devices:
                device_timelines.setdefault(device_entity, []).append(
                    (start_minutes, schedule_id, start_hm)
                )

        if not schedule_info:
            return {}

        # Step 2: For each device, calculate when each schedule ends for THAT device
        # device_schedule_ends[(device, schedule_id)] = end_time_minutes (or None for midnight)
        device_schedule_ends: Dict[Tuple[str, str], Optional[int]] = {}

        for device_entity, timeline in device_timelines.items():
            timeline.sort()  # Sort by start_minutes
            total = len(timeline)

            for position, (start_minutes, schedule_id, start_hm) in enumerate(timeline):
                if total == 1:
                    # Only one schedule for this device, runs until midnight
                    device_schedule_ends[(device_entity, schedule_id)] = None
                    continue

                # Find the next schedule with a different start time
                end_minutes = None
                for offset in range(1, total):
                    next_pos = (position + offset) % total
                    next_start_minutes, _, next_start_hm = timeline[next_pos]
                    if next_start_hm != start_hm:
                        end_minutes = next_start_minutes
                        break

                device_schedule_ends[(device_entity, schedule_id)] = end_minutes

        # Step 3: For each schedule, find when it should end overall
        # A schedule ends when the LAST of its devices has a newer schedule take over
        derived: Dict[str, str] = {}

        for schedule_id, (index, start_hm, start_minutes, devices) in schedule_info.items():
            if not devices:
                # Schedule controls no devices, default to midnight
                derived[schedule_id] = DEFAULT_SCHEDULE_END
                continue

            # Collect all end times for this schedule's devices
            end_times_minutes: List[int] = []
            for device_entity in devices:
                end_minutes = device_schedule_ends.get((device_entity, schedule_id))
                if end_minutes is not None:
                    end_times_minutes.append(end_minutes)

            if not end_times_minutes:
                # No overlapping schedules for any device, runs until midnight
                derived[schedule_id] = DEFAULT_SCHEDULE_END
            else:
                # Use the LATEST end time so the schedule stays active for all devices
                latest_end_minutes = max(end_times_minutes)
                hours = latest_end_minutes // 60
                mins = latest_end_minutes % 60
                derived[schedule_id] = f"{hours:02d}:{mins:02d}"

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

        try:
            now_hours, now_minutes_str = now_hm.split(":")
            now_minutes = int(now_hours) * 60 + int(now_minutes_str)
        except (ValueError, AttributeError):
            _LOGGER.debug("Invalid time '%s' while evaluating schedules; defaulting to 00:00", now_hm)
            now_minutes = 0

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

            try:
                start_hours, start_minutes = start_time.split(":")
                start_value = int(start_hours) * 60 + int(start_minutes)
            except (ValueError, AttributeError):
                _LOGGER.warning(
                    "Invalid start_time format for schedule %s: %s, defaulting to 00:00",
                    schedule_name,
                    start_time,
                )
                start_value = 0
            start_age = (now_minutes - start_value) % MINUTES_PER_DAY

            only_when_home = schedule.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True)

            # Per-schedule presence tracking
            schedule_trackers = schedule.get(CONF_SCHEDULE_DEVICE_TRACKERS, [])
            if schedule_trackers:
                # Schedule has specific trackers: check if any are home
                schedule_anyone_home = any(
                    self._is_tracker_home(tracker) for tracker in schedule_trackers
                )
            else:
                # No specific trackers: fall back to global presence
                schedule_anyone_home = anyone_home

            hvac_mode_home = str(
                schedule.get(CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE)
            ).lower()
            hvac_mode_away_raw = schedule.get(CONF_SCHEDULE_AWAY_HVAC_MODE)
            hvac_mode_away = (
                str(hvac_mode_away_raw).lower()
                if hvac_mode_away_raw not in (None, "", "inherit")
                else None
            )

            device_entities = schedule.get(CONF_SCHEDULE_DEVICES, [])
            schedule_temp_home = schedule.get(CONF_SCHEDULE_TEMPERATURE)
            if schedule_temp_home is None:
                schedule_temp_home = DEFAULT_SCHEDULE_TEMPERATURE
            schedule_temp_home = float(schedule_temp_home)

            schedule_temp_away = schedule.get(CONF_SCHEDULE_AWAY_TEMPERATURE)
            if schedule_temp_away is not None:
                schedule_temp_away = float(schedule_temp_away)

            schedule_fan = schedule.get(
                CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE
            )

            in_time_window = self._is_time_in_schedule(
                now_hm, start_time, end_time
            )
            presence_ok = schedule_anyone_home or not only_when_home
            has_away_settings = hvac_mode_away is not None

            # Schedule is active if in time window (presence affects settings, not activation)
            is_active = (
                auto_heating_enabled
                and enabled
                and in_time_window
            )

            # Determine effective settings based on schedule-specific presence
            if schedule_anyone_home:
                # Someone home (per schedule trackers): use home settings
                effective_hvac_mode = hvac_mode_home
                effective_temp = schedule_temp_home
            elif has_away_settings:
                # Nobody home but we have away settings: use them
                effective_hvac_mode = hvac_mode_away
                effective_temp = schedule_temp_away
            elif only_when_home:
                # Nobody home, no away settings, schedule requires presence: turn off
                effective_hvac_mode = "off"
                effective_temp = None
            else:
                # Nobody home, no away settings, schedule doesn't require presence: use home settings
                effective_hvac_mode = hvac_mode_home
                effective_temp = schedule_temp_home

            if effective_hvac_mode in (None, "off"):
                effective_temp = None
                effective_fan = None
            else:
                effective_fan = schedule_fan

            schedule_decisions[schedule_id] = ScheduleDecision(
                schedule_id=schedule_id,
                name=schedule_name,
                start_time=start_time,
                end_time=end_time,
                hvac_mode=effective_hvac_mode or "off",
                hvac_mode_home=hvac_mode_home,
                hvac_mode_away=hvac_mode_away,
                only_when_home=only_when_home,
                enabled=enabled,
                is_active=is_active,
                in_time_window=in_time_window,
                presence_ok=presence_ok,
                device_count=len(device_entities),
                devices=tuple(device_entities),
                schedule_device_trackers=tuple(schedule_trackers),
                target_temp=effective_temp,
                target_temp_home=schedule_temp_home if hvac_mode_home != "off" else None,
                target_temp_away=(
                    schedule_temp_away if hvac_mode_away and hvac_mode_away != "off" else None
                ),
                target_fan=effective_fan,
            )

            if not is_active:
                continue

            for device_entity in device_entities:
                device_builders.setdefault(device_entity, []).append(
                    {
                        "schedule_name": schedule_name,
                        "order": index,
                        "start_minutes": start_value,
                        "start_age": start_age,
                        "hvac_mode": effective_hvac_mode,
                        "temperature": effective_temp,
                        "fan_mode": effective_fan,
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

            hvac_mode, target_temp, target_fan, schedule_name = self._select_device_targets(
                entries
            )

            should_be_active = hvac_mode not in (None, "off")

            device_decisions[device_entity] = DeviceDecision(
                entity_id=device_entity,
                should_be_active=should_be_active,
                active_schedules=(schedule_name,) if schedule_name else tuple(),
                hvac_mode=hvac_mode,
                target_temp=target_temp,
                target_fan=target_fan,
            )

        return device_decisions

    @staticmethod
    def _select_device_targets(
        entries: List[Dict[str, Any]]
    ) -> Tuple[Optional[str], Optional[float], Optional[str], Optional[str]]:
        """Select the hvac mode, temperature, and fan for a device."""
        if not entries:
            return None, None, None, None

        def entry_key(entry: Dict[str, Any]) -> Tuple[int, int]:
            age = entry.get("start_age")
            if age is None:
                return (
                    entry.get("start_minutes", 0),
                    entry.get("order", 0),
                )
            freshness = MINUTES_PER_DAY - int(age)
            return (
                freshness,
                entry.get("order", 0),
            )

        best = max(entries, key=entry_key)
        mode = best.get("hvac_mode")
        temperature = best.get("temperature")
        fan_mode = best.get("fan_mode")

        if mode in (None, "off"):
            return mode, None, None, best.get("schedule_name")

        return mode, temperature, fan_mode, best.get("schedule_name")

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
