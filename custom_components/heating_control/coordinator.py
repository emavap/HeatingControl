"""DataUpdateCoordinator for heating_control."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
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
    UPDATE_CYCLE_TIMEOUT,
    UPDATE_INTERVAL,
    WATCHDOG_STUCK_THRESHOLD,
)
from .controller import ClimateController
from .models import DeviceDecision, DiagnosticsSnapshot, HeatingStateSnapshot, ScheduleDecision

_LOGGER = logging.getLogger(__name__)

MINUTES_PER_DAY = 24 * 60

HVAC_MODES_WITH_TEMPERATURE = {"heat", "cool", "heat_cool", "auto"}


def _mode_supports_temperature(mode: Optional[str]) -> bool:
    """Return True if the HVAC mode typically exposes a temperature target."""
    if mode is None:
        return False
    return mode in HVAC_MODES_WITH_TEMPERATURE


def _parse_time_to_minutes(time_str: str, logger: logging.Logger) -> int:
    """Parse HH:MM time string to minutes since midnight with validation.

    Args:
        time_str: Time string in HH:MM format
        logger: Logger instance for warnings

    Returns:
        Minutes since midnight (0-1439), or 0 if invalid

    Examples:
        >>> _parse_time_to_minutes("08:30", logger)
        510  # 8 * 60 + 30
        >>> _parse_time_to_minutes("23:59", logger)
        1439
        >>> _parse_time_to_minutes("invalid", logger)
        0  # Logs warning and returns default
    """
    try:
        if not isinstance(time_str, str) or ':' not in time_str:
            raise ValueError(f"Invalid time format: {time_str}")

        parts = time_str.split(':')
        if len(parts) != 2:
            raise ValueError(f"Time must be HH:MM format: {time_str}")

        hours, minutes = int(parts[0]), int(parts[1])

        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError(f"Time out of range: {time_str}")

        total_minutes = hours * 60 + minutes

        # Additional validation for edge cases
        if total_minutes >= MINUTES_PER_DAY or total_minutes < 0:
            raise ValueError(f"Time out of bounds: {total_minutes} minutes")

        return total_minutes

    except (ValueError, AttributeError) as err:
        logger.warning("Invalid time '%s': %s, defaulting to 00:00", time_str, err)
        return 0


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

        # Watchdog state tracking
        self._last_update_start: Optional[float] = None
        self._last_update_complete: Optional[float] = None
        self._last_update_duration: Optional[float] = None
        self._timed_out_devices: List[str] = []

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    @property
    def config(self) -> Dict[str, Any]:
        """Get current configuration (options or data)."""
        return self.config_entry.options or self.config_entry.data

    def get_schedule_by_id(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Get schedule config by ID or name.

        Args:
            schedule_id: Schedule ID or name to look up

        Returns:
            Schedule configuration dict, or None if not found
        """
        schedules = self.config.get(CONF_SCHEDULES, [])
        schedule_id_lower = schedule_id.casefold()

        for schedule in schedules:
            # Match by ID first
            if schedule.get(CONF_SCHEDULE_ID) == schedule_id:
                return schedule
            # Fall back to name match (case-insensitive)
            if schedule.get(CONF_SCHEDULE_NAME, "").casefold() == schedule_id_lower:
                return schedule

        return None

    async def _async_update_data(self) -> HeatingStateSnapshot:
        """Update data and apply control decisions with watchdog protection.

        NOTE: Timing variables (_last_update_start, _last_update_complete, _last_update_duration)
        are accessed without locks because DataUpdateCoordinator guarantees serial execution
        of update cycles. Only one instance of this method runs at a time.
        """
        start_time = time.time()
        self._last_update_start = start_time

        # Check if previous update is stuck
        if self._last_update_complete:
            time_since_complete = start_time - self._last_update_complete
            if time_since_complete > WATCHDOG_STUCK_THRESHOLD:
                _LOGGER.warning(
                    "Integration may be stuck - last update completed %.1fs ago (threshold: %ds)",
                    time_since_complete,
                    WATCHDOG_STUCK_THRESHOLD,
                )

        try:
            async with asyncio.timeout(UPDATE_CYCLE_TIMEOUT):
                snapshot = await self._async_update_data_internal()

            # Update timing
            end_time = time.time()
            self._last_update_complete = end_time
            self._last_update_duration = end_time - start_time

            _LOGGER.debug(
                "Update cycle completed in %.2fs", self._last_update_duration
            )

            return snapshot

        except asyncio.TimeoutError as err:
            end_time = time.time()
            self._last_update_complete = end_time
            self._last_update_duration = end_time - start_time
            self._timed_out_devices = ["update_cycle_timeout"]
            raise UpdateFailed(
                f"Heating control update exceeded {UPDATE_CYCLE_TIMEOUT}s watchdog timeout"
            ) from err

        except Exception as err:
            end_time = time.time()
            self._last_update_complete = end_time
            self._last_update_duration = end_time - start_time
            raise UpdateFailed(f"Error updating heating control: {err}") from err

    async def _async_update_data_internal(self) -> HeatingStateSnapshot:
        """Internal update logic without timeout wrapper."""
        snapshot = await self.hass.async_add_executor_job(
            self._calculate_heating_state
        )

        should_apply_control = self._detect_state_transitions(snapshot)

        if should_apply_control:
            _LOGGER.info("State transition detected, applying control decisions")
            timed_out_devices = await self._controller.async_apply(
                snapshot.device_decisions.values()
            )
            self._timed_out_devices = timed_out_devices

            if timed_out_devices:
                device_count = len(snapshot.device_decisions)
                timeout_count = len(timed_out_devices)
                timeout_rate = timeout_count / device_count if device_count > 0 else 0

                _LOGGER.warning(
                    "The following devices timed out during control application: %s",
                    ", ".join(timed_out_devices),
                )

                # Circuit breaker: detect cascading timeout scenario
                if timeout_rate >= 0.8:  # 80% or more devices timing out
                    _LOGGER.error(
                        "CIRCUIT BREAKER: %d/%d devices (%.0f%%) are timing out. "
                        "Possible network issue or unresponsive devices. "
                        "Check device connectivity and network stability.",
                        timeout_count,
                        device_count,
                        timeout_rate * 100,
                    )
        else:
            _LOGGER.debug(
                "No state transitions, skipping control application (preserving manual changes)"
            )
            self._timed_out_devices = []

        self._update_previous_states(snapshot)

        # Enrich snapshot with watchdog data
        snapshot = self._add_watchdog_diagnostics(snapshot)

        return snapshot

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

    def _add_watchdog_diagnostics(self, snapshot: HeatingStateSnapshot) -> HeatingStateSnapshot:
        """Enrich snapshot with watchdog diagnostics."""
        # Determine watchdog status
        # Use fractions of UPDATE_CYCLE_TIMEOUT as heuristic thresholds for diagnostics
        watchdog_status = "healthy"
        if self._last_update_duration:
            if self._last_update_duration > UPDATE_CYCLE_TIMEOUT * 0.7:  # >35s
                watchdog_status = "critical"
            elif self._last_update_duration > UPDATE_CYCLE_TIMEOUT * 0.4:  # >20s
                watchdog_status = "warning"

        if self._timed_out_devices:
            watchdog_status = "timeout"  # Timeout overrides all other statuses

        # Create enriched diagnostics
        enriched_diagnostics = DiagnosticsSnapshot(
            now_time=snapshot.diagnostics.now_time,
            tracker_states=snapshot.diagnostics.tracker_states,
            trackers_home=snapshot.diagnostics.trackers_home,
            trackers_total=snapshot.diagnostics.trackers_total,
            auto_heating_enabled=snapshot.diagnostics.auto_heating_enabled,
            schedule_count=snapshot.diagnostics.schedule_count,
            active_schedules=snapshot.diagnostics.active_schedules,
            active_devices=snapshot.diagnostics.active_devices,
            last_update_duration=self._last_update_duration,
            timed_out_devices=tuple(self._timed_out_devices),
            watchdog_status=watchdog_status,
        )

        # Return new snapshot with enriched diagnostics
        return HeatingStateSnapshot(
            everyone_away=snapshot.everyone_away,
            anyone_home=snapshot.anyone_home,
            schedule_decisions=snapshot.schedule_decisions,
            device_decisions=snapshot.device_decisions,
            diagnostics=enriched_diagnostics,
        )

    def force_update_on_next_refresh(self) -> None:
        """Force control application on next update (for config changes)."""
        _LOGGER.info("Forcing update on next refresh")
        self._force_update = True

    @staticmethod
    def _derive_auto_end_times(schedules: List[dict]) -> Dict[str, str]:
        """Derive implicit end times per-device to allow overlapping schedules for different devices.

        For each device, schedules run sequentially. A schedule controlling multiple devices
        stays active until the last of its devices has a newer schedule take over.

        Example:
            Schedules:
            - Schedule A: 08:00-auto, devices=[bedroom, living_room]
            - Schedule B: 10:00-auto, devices=[bedroom]
            - Schedule C: 12:00-auto, devices=[living_room]

            Per-device timelines:
            - bedroom: [A@08:00, B@10:00]
            - living_room: [A@08:00, C@12:00]

            Derived end times:
            - Schedule A: 10:00 (bedroom ends at 10:00, living_room at 12:00 → take latest: 12:00)
              Actually, we take the LATEST, so A ends at 12:00
            - Schedule B: 23:59 (only schedule for bedroom after 10:00)
            - Schedule C: 23:59 (only schedule for living_room after 12:00)

        Args:
            schedules: List of schedule configurations (dicts with CONF_* keys)

        Returns:
            Dict mapping schedule_id to derived end time (HH:MM format)
            Only includes schedules that need auto-derived end times.
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

            start_minutes = _parse_time_to_minutes(start_hm, _LOGGER)

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
        config = self.config
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
            now_hm,
        )

        diagnostics = DiagnosticsSnapshot(
            now_time=now_hm,
            tracker_states=tracker_states,
            trackers_home=sum(1 for v in tracker_states.values() if v),
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
            _LOGGER.debug("Tracker entity_id is empty or None")
            return False

        state: Optional[State] = self.hass.states.get(entity_id)
        if not state:
            _LOGGER.debug(
                "Tracker %s has no state object (entity may not exist)", entity_id
            )
            return False

        is_home = state.state == STATE_HOME
        _LOGGER.debug(
            "Tracker %s state='%s', STATE_HOME='%s', is_home=%s",
            entity_id,
            state.state,
            STATE_HOME,
            is_home,
        )
        return is_home

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

        now_minutes = _parse_time_to_minutes(now_hm, _LOGGER)

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

            start_value = _parse_time_to_minutes(start_time, _LOGGER)
            start_age = (now_minutes - start_value) % MINUTES_PER_DAY

            only_when_home = schedule.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True)

            # Per-schedule presence tracking
            schedule_trackers = schedule.get(CONF_SCHEDULE_DEVICE_TRACKERS, [])
            # Filter out None, empty strings, and other falsy values
            valid_schedule_trackers = [t for t in schedule_trackers if t]

            # Fetch states ONCE and store string values to prevent race conditions
            # Store both State object and its state string value atomically
            tracker_states: Dict[str, Tuple[Optional[State], Optional[str]]] = {
                t: (
                    (state := self.hass.states.get(t)),
                    state.state if state else None
                )
                for t in valid_schedule_trackers
            }

            # Filter to usable trackers (with valid, available states)
            usable_tracker_state_values: Dict[str, str] = {}
            for tracker, (state_obj, state_value) in tracker_states.items():
                if not state_obj or not state_value:
                    continue
                if state_value in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                    _LOGGER.debug(
                        "Schedule '%s' tracker %s is %s, falling back to global presence",
                        schedule_name,
                        tracker,
                        state_value,
                    )
                    continue
                usable_tracker_state_values[tracker] = state_value

            # Log warning if trackers were specified but all are invalid
            if valid_schedule_trackers and not usable_tracker_state_values:
                _LOGGER.warning(
                    "Schedule '%s' has per-schedule trackers configured %s but none are usable. "
                    "Falling back to global presence tracking.",
                    schedule_name,
                    valid_schedule_trackers,
                )

            if usable_tracker_state_values:
                # Use the captured state string values (prevents race condition)
                schedule_anyone_home = any(
                    state_value == STATE_HOME
                    for state_value in usable_tracker_state_values.values()
                )
            else:
                # No specific trackers or all invalid: fall back to global presence
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
            elif not _mode_supports_temperature(effective_hvac_mode):
                effective_temp = None
                effective_fan = schedule_fan
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
                target_temp_home=(
                    schedule_temp_home
                    if _mode_supports_temperature(hvac_mode_home)
                    else None
                ),
                target_temp_away=(
                    schedule_temp_away
                    if hvac_mode_away and _mode_supports_temperature(hvac_mode_away)
                    else None
                ),
                target_fan=effective_fan,
            )

            if not is_active:
                continue

            for device_entity in device_entities:
                device_builders.setdefault(device_entity, []).append(
                    {
                        "schedule_name": schedule_name,
                        "schedule_id": schedule_id,
                        "order": index,
                        "start_minutes": start_value,
                        "start_age": start_age,
                        "start_time": start_time,
                        "end_time": end_time,
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
        now_hm: str,
    ) -> Dict[str, DeviceDecision]:
        """Create DeviceDecision objects for each configured device."""
        all_devices = config.get(CONF_CLIMATE_DEVICES, [])
        device_decisions: Dict[str, DeviceDecision] = {}

        for device_entity in all_devices:
            entries = device_builders.get(device_entity, [])

            hvac_mode, target_temp, target_fan, schedule_name = self._select_device_targets(
                entries,
                now_hm,
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
        entries: List[Dict[str, Any]],
        now_hm: str,
    ) -> Tuple[Optional[str], Optional[float], Optional[str], Optional[str]]:
        """Select the hvac mode, temperature, and fan for a device.

        Selects the schedule with the most recent start time among those that:
        1. Are currently in their time window (double-check to catch edge cases)
        2. Have the highest "freshness" (most recently started)
        3. Break ties by schedule order (higher order = later in config, wins)
        """
        if not entries:
            return None, None, None, None

        # Filter to only schedules that are currently in their time window
        # This is a safety check - entries should already be filtered, but this catches edge cases
        valid_entries = []
        for entry in entries:
            start_time = entry.get("start_time", "00:00")
            end_time = entry.get("end_time", "23:59")

            # Check if current time is within this schedule's window
            if HeatingControlCoordinator._is_time_in_schedule(now_hm, start_time, end_time):
                valid_entries.append(entry)
            else:
                # Log when we filter out a schedule that shouldn't be in entries
                _LOGGER.debug(
                    "Filtered out schedule '%s' (not in time window: now=%s, window=%s-%s)",
                    entry.get("schedule_name", "Unknown"),
                    now_hm,
                    start_time,
                    end_time,
                )

        if not valid_entries:
            # No schedules are actually in their time window
            _LOGGER.debug(
                "No valid schedules found for device (had %d entries, none in time window)",
                len(entries),
            )
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

        best = max(valid_entries, key=entry_key)
        mode = best.get("hvac_mode")
        temperature = best.get("temperature")
        fan_mode = best.get("fan_mode")

        # Log the selection for debugging
        if len(valid_entries) > 1:
            _LOGGER.debug(
                "Selected schedule '%s' from %d candidates (start_age=%d, order=%d)",
                best.get("schedule_name", "Unknown"),
                len(valid_entries),
                best.get("start_age", 0),
                best.get("order", 0),
            )

        if mode in (None, "off"):
            return mode, None, None, best.get("schedule_name")

        return mode, temperature, fan_mode, best.get("schedule_name")

    async def async_set_schedule_enabled(
        self,
        *,
        schedule_id: Optional[str] = None,
        schedule_name: Optional[str] = None,
        enabled: bool,
    ) -> None:
        """Enable or disable a schedule and persist the change."""
        config_entry = self.config_entry
        source = config_entry.options or config_entry.data
        schedules = source.get(CONF_SCHEDULES, [])

        if not schedules:
            raise ValueError("No schedules are configured for this entry")

        new_schedules = deepcopy(schedules)
        # Check for empty strings in addition to None
        target_name = schedule_name.casefold() if schedule_name and schedule_name.strip() else None
        target_id_casefold = schedule_id.casefold() if schedule_id and schedule_id.strip() else None
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
            return

        update_kwargs: Dict[str, Dict] = {}
        if config_entry.options:
            new_options = dict(config_entry.options)
            new_options[CONF_SCHEDULES] = new_schedules
            update_kwargs["options"] = new_options
        else:
            new_data = dict(config_entry.data)
            new_data[CONF_SCHEDULES] = new_schedules
            update_kwargs["data"] = new_data

        # Update config entry (callback method; no await needed)
        self.hass.config_entries.async_update_entry(
            config_entry, **update_kwargs
        )

        # Ensure the new configuration is applied immediately.
        self._force_update = True
        self.hass.async_create_task(self.async_refresh())
