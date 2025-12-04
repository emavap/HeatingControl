"""DataUpdateCoordinator for heating_control."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Mapping, Set, Union
from collections.abc import Iterable
from threading import Lock
from dataclasses import dataclass
from contextlib import contextmanager

from homeassistant.util import dt as dt_util
from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_state_change_event, async_call_later
from homeassistant.helpers import device_registry as dr, entity_registry as er

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
    DEVICE_SETTLE_OVERRIDES,
    DOMAIN,
    UPDATE_CYCLE_TIMEOUT,
    UPDATE_INTERVAL,
    WATCHDOG_STUCK_THRESHOLD,
    CIRCUIT_BREAKER_TIMEOUT_THRESHOLD,
    CIRCUIT_BREAKER_COOLDOWN_MINUTES,
    TEMPERATURE_EPSILON,
    PRESENCE_CACHE_SECONDS,
    DASHBOARD_REFRESH_DELAY_SECONDS,
    MINUTES_PER_DAY,
    HVAC_MODES_WITH_TEMPERATURE,
)
from .controller import ClimateController
from .models import DeviceDecision, DiagnosticsSnapshot, HeatingStateSnapshot, ScheduleDecision

_LOGGER = logging.getLogger(__name__)

@dataclass
class PresenceCache:
    """Cache for presence detection to reduce entity lookups."""
    anyone_home: bool
    everyone_away: bool
    timestamp: float
    tracker_count: int = 0
    
    def is_expired(self) -> bool:
        """Check if cache has expired."""
        return (time.time() - self.timestamp) > PRESENCE_CACHE_SECONDS
    
    def is_valid(self) -> bool:
        """Check if cache is valid (not expired and has data)."""
        return not self.is_expired() and self.tracker_count > 0
    
    def __post_init__(self):
        """Validate cache data after initialization."""
        if self.tracker_count < 0:
            self.tracker_count = 0
        if self.timestamp < 0:
            self.timestamp = time.time()

def _mode_supports_temperature(mode: Optional[str]) -> bool:
    """Return True if the HVAC mode typically exposes a temperature target."""
    if mode is None or not isinstance(mode, str):
        return False
    return mode.lower() in HVAC_MODES_WITH_TEMPERATURE

def _validate_time_format(time_str: str) -> bool:
    """Validate time string format without parsing."""
    if not isinstance(time_str, str):
        return False
    
    time_str = time_str.strip()
    if not time_str or ':' not in time_str:
        return False
        
    parts = time_str.split(':')
    if len(parts) != 2:
        return False
        
    try:
        hours, minutes = int(parts[0]), int(parts[1])
        return 0 <= hours < 24 and 0 <= minutes < 60
    except ValueError:
        return False

def _parse_time_to_minutes(time_str: str, logger: logging.Logger) -> int:
    """Parse HH:MM time string to minutes since midnight with validation."""
    if not time_str:
        logger.warning("Empty time string provided, defaulting to 00:00")
        return 0
        
    try:
        if not isinstance(time_str, str):
            raise ValueError(f"Time must be string, got {type(time_str)}")
            
        time_str = time_str.strip()
        if ':' not in time_str:
            raise ValueError(f"Invalid time format: {time_str}")

        parts = time_str.split(':')
        if len(parts) != 2:
            raise ValueError(f"Time must be HH:MM format: {time_str}")

        try:
            hours, minutes = int(parts[0]), int(parts[1])
        except ValueError as e:
            raise ValueError(f"Non-numeric time components in {time_str}: {e}")

        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError(f"Time out of range: {time_str} (hours: 0-23, minutes: 0-59)")

        total_minutes = hours * 60 + minutes

        if total_minutes >= MINUTES_PER_DAY or total_minutes < 0:
            raise ValueError(f"Time out of bounds: {total_minutes} minutes")

        return total_minutes

    except (ValueError, AttributeError) as err:
        logger.warning(
            "Invalid time '%s': %s, defaulting to 00:00", 
            time_str, 
            err,
            extra={
                "time_input": time_str, 
                "error_type": type(err).__name__,
                "function": "_parse_time_to_minutes"
            }
        )
        return 0

class HeatingControlCoordinator(DataUpdateCoordinator[HeatingStateSnapshot]):
    """Enhanced coordinator with circuit breaker and performance optimizations."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        """Initialize."""
        self.config_entry = config_entry
        self.hass = hass

        self._controller = ClimateController(
            hass,
            settle_seconds=DEFAULT_SETTLE_SECONDS,
            final_settle=DEFAULT_FINAL_SETTLE,
            use_device_specific_timing=True,
        )
        self._previous_schedule_states: Optional[Dict[str, bool]] = None
        self._previous_presence_state: Optional[bool] = None
        self._force_update = False

        # Enhanced watchdog state tracking with thread safety
        self._last_update_start: Optional[float] = None
        self._last_update_complete: Optional[float] = None
        self._last_update_duration: Optional[float] = None
        self._timed_out_devices: List[str] = []
        self._update_lock = Lock()

        # Circuit breaker state
        self._circuit_breaker_active = False
        self._circuit_breaker_until: Optional[float] = None

        # Performance optimization caches
        self._presence_cache: Optional[PresenceCache] = None
        self._device_decision_cache: Dict[str, Any] = {}
        self._schedule_evaluation_cache: Dict[str, Tuple[ScheduleDecision, float]] = {}
        self._last_schedule_hash: Optional[int] = None
        self._last_global_presence_hash: Optional[int] = None
        
        # Performance metrics tracking
        self._performance_metrics = {
            "update_times": [],
            "command_counts": [],
            "cache_hits": 0,
            "cache_misses": 0,
            "circuit_breaker_trips": 0,
        }
        self._device_response_times: Dict[str, List[float]] = {}

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=UPDATE_INTERVAL))
        
        # Set up event listeners for real-time updates
        self._event_listeners = []
        self._setup_event_listeners()

    def _setup_event_listeners(self):
        """Set up event listeners for real-time updates."""
        @callback
        def handle_state_change(event):
            """Handle state change events."""
            entity_id = event.data.get("entity_id")
            if not entity_id:
                return
                
            # Check if it's a tracked entity
            config = self.config
            device_trackers = config.get(CONF_DEVICE_TRACKERS, [])
            climate_devices = config.get(CONF_CLIMATE_DEVICES, [])
            
            # Check schedule-specific trackers
            schedule_trackers = []
            for schedule in config.get(CONF_SCHEDULES, []):
                schedule_trackers.extend(schedule.get(CONF_SCHEDULE_DEVICE_TRACKERS, []))
            
            all_tracked = set(device_trackers + climate_devices + schedule_trackers)
            
            if entity_id in all_tracked:
                _LOGGER.debug("Tracked entity %s changed, scheduling refresh", entity_id)
                self.force_update_on_next_refresh()
                # Schedule refresh with small delay to batch multiple changes
                self.hass.async_create_task(self._delayed_refresh())
        
        self.hass.bus.async_listen("state_changed", handle_state_change)

    async def _delayed_refresh(self):
        """Delayed refresh to batch multiple state changes."""
        await asyncio.sleep(DASHBOARD_REFRESH_DELAY_SECONDS)
        await self.async_request_refresh()

    async def _handle_presence_change(self, event):
        """Handle presence state changes for immediate response."""
        _LOGGER.debug("Presence change detected, triggering update")
        # Invalidate presence cache
        self._presence_cache = None
        await self.async_request_refresh()

    async def _handle_climate_change(self, event):
        """Handle manual climate changes to avoid conflicts."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        
        if new_state and entity_id in self._controller._last_commands:
            # Check if this was a manual change (not from our commands)
            last_command = self._controller._last_commands[entity_id]
            current_hvac = new_state.state
            current_temp = new_state.attributes.get(ATTR_TEMPERATURE)
            
            manual_change = (
                current_hvac != last_command.get("hvac_mode") or
                (current_temp and last_command.get("temperature") and 
                 abs(current_temp - last_command.get("temperature", 0)) > TEMPERATURE_EPSILON)
            )
            
            if manual_change:
                _LOGGER.info("Manual change detected on %s, will respect user adjustment", entity_id)
                # Update our command history to match manual change
                self._controller._last_commands[entity_id].update({
                    "hvac_mode": current_hvac,
                    "temperature": current_temp,
                })

    @property
    def config(self) -> Dict[str, Any]:
        """Get current configuration (options or data)."""
        return self.config_entry.options or self.config_entry.data

    def get_schedule_by_id(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Get schedule config by ID or name."""
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

    def _calculate_schedule_hash(self) -> int:
        """Calculate hash of current schedule configuration for caching."""
        schedules = self.config.get(CONF_SCHEDULES, [])
        schedule_data = []
        for schedule in schedules:
            if schedule.get(CONF_SCHEDULE_ENABLED, True):
                schedule_data.append((
                    schedule.get(CONF_SCHEDULE_START),
                    schedule.get(CONF_SCHEDULE_END),
                    schedule.get(CONF_SCHEDULE_TEMPERATURE),
                    schedule.get(CONF_SCHEDULE_HVAC_MODE),
                    tuple(schedule.get(CONF_SCHEDULE_DEVICES, []))
                ))
        return hash(tuple(schedule_data))

    def _calculate_global_presence_hash(self) -> int:
        """Calculate hash of global presence state for caching."""
        config = self.config
        device_trackers = config.get(CONF_DEVICE_TRACKERS, [])
        tracker_states = []
        for tracker in device_trackers:
            state = self.hass.states.get(tracker)
            tracker_states.append((tracker, state.state if state else None))
        return hash(tuple(tracker_states))

    def _get_cached_schedule_decision(self, schedule_id: str, schedule_hash: int) -> Optional[ScheduleDecision]:
        """Get cached schedule decision if still valid."""
        if schedule_id not in self._schedule_evaluation_cache:
            return None
        
        cached_decision, cached_hash = self._schedule_evaluation_cache[schedule_id]
        if cached_hash == schedule_hash:
            return cached_decision
        
        return None

    def _cache_schedule_decision(self, schedule_id: str, decision: ScheduleDecision, schedule_hash: int) -> None:
        """Cache schedule decision with its hash."""
        self._schedule_evaluation_cache[schedule_id] = (decision, schedule_hash)

    def _should_force_update(self) -> bool:
        """Check if update should be forced."""
        return self._force_update

    async def _async_update_data(self) -> HeatingStateSnapshot:
        """Update data with circuit breaker protection and performance optimizations."""
        start_time = time.time()
        
        # Thread-safe update tracking
        with self._update_lock:
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

        # Check circuit breaker
        if self._circuit_breaker_active:
            if self._circuit_breaker_until and start_time < self._circuit_breaker_until:
                _LOGGER.warning("Circuit breaker active, skipping update")
                return self.data or HeatingStateSnapshot(
                    everyone_away=True,
                    anyone_home=False,
                    schedule_decisions={},
                    device_decisions={},
                    diagnostics=DiagnosticsSnapshot(
                        now_time="00:00",
                        tracker_states={},
                        trackers_home=0,
                        trackers_total=0,
                        auto_heating_enabled=False,
                        schedule_count=0,
                        active_schedules=0,
                        active_devices=0,
                    )
                )
            else:
                _LOGGER.info("Circuit breaker cooldown expired, resuming operations")
                self._circuit_breaker_active = False
                self._circuit_breaker_until = None

        try:
            async with asyncio.timeout(UPDATE_CYCLE_TIMEOUT):
                # Check if we can use cached decisions
                current_schedule_hash = self._calculate_schedule_hash()
                if (self._last_schedule_hash == current_schedule_hash and 
                    self._device_decision_cache and 
                    not self._should_force_update()):
                    _LOGGER.debug("Using cached device decisions")
                    return self.data

                snapshot = await self._async_update_data_internal()

                # Update caches
                self._last_schedule_hash = current_schedule_hash
                self._device_decision_cache = {
                    device.entity_id: device for device in snapshot.device_decisions.values()
                }

            # Update timing
            end_time = time.time()
            with self._update_lock:
                self._last_update_complete = end_time
                self._last_update_duration = end_time - start_time

            _LOGGER.debug(
                "Update cycle completed in %.2fs", self._last_update_duration
            )

            return snapshot

        except asyncio.TimeoutError as err:
            end_time = time.time()
            with self._update_lock:
                self._last_update_complete = end_time
                self._last_update_duration = end_time - start_time
            self._timed_out_devices = ["update_cycle_timeout"]
            raise UpdateFailed(
                f"Heating control update exceeded {UPDATE_CYCLE_TIMEOUT}s watchdog timeout"
            ) from err

        except Exception as err:
            end_time = time.time()
            with self._update_lock:
                self._last_update_complete = end_time
                self._last_update_duration = end_time - start_time
            raise UpdateFailed(f"Error updating heating control: {err}") from err

    async def _async_update_data_internal(self) -> HeatingStateSnapshot:
        """Internal update logic without timeout wrapper."""
        start_time = time.time()
        
        snapshot = await self.hass.async_add_executor_job(
            self._calculate_heating_state_optimized
        )

        should_apply_control = self._detect_state_transitions(snapshot)
        command_count = 0

        if should_apply_control:
            _LOGGER.info("State transition detected, applying control decisions")
            await self._apply_control_with_circuit_breaker(snapshot)
            command_count = len(snapshot.device_decisions)
        else:
            _LOGGER.debug(
                "No state transitions, skipping control application (preserving manual changes)"
            )
            self._timed_out_devices = []

        self._update_previous_states(snapshot)

        # Calculate performance metrics
        update_duration = time.time() - start_time
        performance_metrics = self._calculate_performance_metrics(update_duration, command_count)
        
        # Validate schedules for conflicts
        schedules = self.config.get(CONF_SCHEDULES, [])
        warnings = self._validate_schedule_conflicts(schedules)
        
        if warnings:
            for warning in warnings[:3]:  # Log first 3 warnings
                _LOGGER.warning(warning)

        # Enrich snapshot with enhanced diagnostics
        enhanced_diagnostics = DiagnosticsSnapshot(
            now_time=snapshot.diagnostics.now_time,
            tracker_states=snapshot.diagnostics.tracker_states,
            trackers_home=snapshot.diagnostics.trackers_home,
            trackers_total=snapshot.diagnostics.trackers_total,
            auto_heating_enabled=snapshot.diagnostics.auto_heating_enabled,
            schedule_count=snapshot.diagnostics.schedule_count,
            active_schedules=snapshot.diagnostics.active_schedules,
            active_devices=snapshot.diagnostics.active_devices,
            last_update_duration=update_duration,
            timed_out_devices=tuple(self._timed_out_devices),
            watchdog_status=self._get_watchdog_status(),
            performance_metrics=performance_metrics,
            schedule_warnings=warnings,
            device_health=self._assess_device_health(),
        )
        
        return snapshot._replace(diagnostics=enhanced_diagnostics)

    async def _apply_control_with_circuit_breaker(self, snapshot):
        """Apply control with circuit breaker protection."""
        device_decisions = list(snapshot.device_decisions.values())
        
        try:
            timed_out_devices = await self._controller.async_apply(device_decisions)
            self._timed_out_devices = timed_out_devices

            if timed_out_devices:
                device_count = len(snapshot.device_decisions)
                timeout_count = len(timed_out_devices)
                timeout_rate = timeout_count / device_count if device_count > 0 else 0

                if timeout_rate >= CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
                    self._log_circuit_breaker_activation(timeout_count, device_count, timeout_rate)
                    self._activate_circuit_breaker()
                
        except Exception as e:
            _LOGGER.error("Control application failed: %s", e, exc_info=True)
            self._activate_circuit_breaker()

    def _activate_circuit_breaker(self):
        """Activate circuit breaker with proper timing."""
        self._circuit_breaker_active = True
        self._circuit_breaker_until = time.time() + (CIRCUIT_BREAKER_COOLDOWN_MINUTES * 60)

    def _calculate_heating_state_optimized(self) -> HeatingStateSnapshot:
        """Optimized state calculation with presence caching."""
        # Use cached presence if available and not expired
        if self._presence_cache and not self._presence_cache.is_expired():
            anyone_home = self._presence_cache.anyone_home
            everyone_away = self._presence_cache.everyone_away
        else:
            tracker_states, anyone_home, everyone_away = self._resolve_presence(self.config)
            self._presence_cache = PresenceCache(
                anyone_home=anyone_home,
                everyone_away=everyone_away,
                timestamp=time.time()
            )

        # Continue with existing calculation logic
        return self._calculate_heating_state_with_presence(anyone_home, everyone_away)

    def _calculate_heating_state_with_presence(self, anyone_home: bool, everyone_away: bool) -> HeatingStateSnapshot:
        """Calculate heating state with provided presence information."""
        config = self.config
        now = dt_util.now()
        now_hm = now.strftime("%H:%M")

        # Delegate to focused methods
        tracker_states = self._get_tracker_states(config)
        auto_heating_enabled = config.get(CONF_AUTO_HEATING_ENABLED, True)
        
        schedule_decisions, device_builders = self._evaluate_all_schedules(
            config, now_hm, anyone_home, auto_heating_enabled
        )
        
        device_decisions = self._build_final_device_decisions(config, device_builders, now_hm)
        diagnostics = self._build_diagnostics_snapshot(
            now_hm, tracker_states, auto_heating_enabled, config, 
            schedule_decisions, device_decisions
        )

        return HeatingStateSnapshot(
            everyone_away=everyone_away,
            anyone_home=anyone_home,
            schedule_decisions=schedule_decisions,
            device_decisions=device_decisions,
            diagnostics=diagnostics,
        )

    def _get_tracker_states(self, config) -> Dict[str, bool]:
        """Get current tracker states."""
        tracker_states, _, _ = self._resolve_presence(config)
        return dict(tracker_states)

    def _evaluate_all_schedules(self, config, now_hm: str, anyone_home: bool, auto_heating_enabled: bool):
        """Evaluate all schedules with caching."""
        return self._evaluate_schedules(config, now_hm, anyone_home, auto_heating_enabled)

    def _build_final_device_decisions(self, config, device_builders, now_hm: str):
        """Build final device decisions from schedule builders."""
        return self._finalize_device_decisions(config, device_builders, now_hm)

    def _build_diagnostics_snapshot(self, now_hm: str, tracker_states: Dict[str, bool], 
                                   auto_heating_enabled: bool, config, schedule_decisions, device_decisions):
        """Build diagnostics snapshot."""
        return DiagnosticsSnapshot(
            now_time=now_hm,
            tracker_states=tracker_states,
            trackers_home=sum(tracker_states.values()),
            trackers_total=len(tracker_states),
            auto_heating_enabled=auto_heating_enabled,
            schedule_count=len(config.get(CONF_SCHEDULES, [])),
            active_schedules=sum(dec.is_active for dec in schedule_decisions.values()),
            active_devices=sum(dec.should_be_active for dec in device_decisions.values()),
        )

    def _resolve_presence(self, config: Dict[str, Any]) -> Tuple[List[Tuple[str, bool]], bool, bool]:
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

    def _is_tracker_home(self, entity_id: str) -> bool:
        """Check if a device tracker is home with enhanced logging."""
        if not entity_id:
            _LOGGER.debug("Empty entity_id provided to _is_tracker_home")
            return False
            
        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.debug("Tracker entity %s not found in Home Assistant", entity_id)
            return False
            
        is_home = state.state.lower() in ["home", "on", "true"]
        _LOGGER.debug("Tracker %s state: %s (home: %s)", entity_id, state.state, is_home)
        return is_home

    def _evaluate_schedules(
        self,
        config: Dict[str, Any],
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

    async def async_unload(self):
        """Clean up event listeners."""
        for remove_listener in self._event_listeners:
            try:
                remove_listener()
            except Exception as e:
                _LOGGER.warning("Error removing event listener: %s", e)
        self._event_listeners.clear()

    def _validate_schedule_conflicts(self, schedules: List[Dict]) -> List[str]:
        """Detect potential schedule conflicts and return warnings."""
        warnings = []
        device_schedules = {}
        
        # Group schedules by device
        for schedule in schedules:
            if not schedule.get("enabled", True):
                continue
            
            for device in schedule.get("device_entities", []):
                if device not in device_schedules:
                    device_schedules[device] = []
                device_schedules[device].append(schedule)
        
        # Check for overlapping schedules on same device
        for device, device_schedule_list in device_schedules.items():
            if len(device_schedule_list) <= 1:
                continue
            
            # Sort by start time
            sorted_schedules = sorted(
                device_schedule_list, 
                key=lambda s: _parse_time_to_minutes(s.get("start_time", "00:00"), _LOGGER)
            )
            
            # Check for overlaps
            for i in range(len(sorted_schedules) - 1):
                current = sorted_schedules[i]
                next_schedule = sorted_schedules[i + 1]
                
                current_start = _parse_time_to_minutes(current.get("start_time", "00:00"), _LOGGER)
                current_end = _parse_time_to_minutes(current.get("end_time", "23:59"), _LOGGER)
                next_start = _parse_time_to_minutes(next_schedule.get("start_time", "00:00"), _LOGGER)
                
                # Handle day wraparound
                if current_end < current_start:  # Crosses midnight
                    current_end += MINUTES_PER_DAY
                
                if next_start < current_end:
                    warnings.append(
                        f"Schedule '{current.get('name')}' overlaps with "
                        f"'{next_schedule.get('name')}' on device {device}. "
                        f"Most recent schedule will take precedence."
                    )
        
        return warnings

    def _calculate_performance_metrics(self, update_duration: float, command_count: int) -> PerformanceMetrics:
        """Calculate current performance metrics."""
        # Update rolling averages
        self._performance_metrics["update_times"].append(update_duration)
        self._performance_metrics["command_counts"].append(command_count)
        
        # Keep only last 100 measurements
        if len(self._performance_metrics["update_times"]) > 100:
            self._performance_metrics["update_times"] = self._performance_metrics["update_times"][-100:]
            self._performance_metrics["command_counts"] = self._performance_metrics["command_counts"][-100:]
        
        # Calculate averages
        avg_response_time = 0.0
        if self._device_response_times:
            all_times = [t for times in self._device_response_times.values() for t in times]
            avg_response_time = sum(all_times) / len(all_times) if all_times else 0.0
        
        cache_total = self._performance_metrics["cache_hits"] + self._performance_metrics["cache_misses"]
        cache_hit_rate = (
            self._performance_metrics["cache_hits"] / cache_total 
            if cache_total > 0 else 0.0
        )
        
        return PerformanceMetrics(
            update_duration_ms=update_duration * 1000,
            device_command_count=command_count,
            cache_hit_rate=cache_hit_rate,
            circuit_breaker_trips=self._performance_metrics["circuit_breaker_trips"],
            average_device_response_time=avg_response_time * 1000,  # Convert to ms
            failed_commands=len(self._timed_out_devices),
            successful_commands=command_count - len(self._timed_out_devices),
        )

    def _assess_device_health(self) -> Dict[str, str]:
        """Assess health status of each managed device."""
        health_status = {}
        
        for entity_id in self.config.get(CONF_CLIMATE_DEVICES, []):
            if entity_id in self._timed_out_devices:
                health_status[entity_id] = "timeout"
            elif entity_id in self._controller._last_commands:
                health_status[entity_id] = "healthy"
            else:
                health_status[entity_id] = "unknown"
        
        return health_status

    @contextmanager
    def _circuit_breaker_context(self):
        """Context manager for circuit breaker operations."""
        if self._circuit_breaker_active:
            if self._circuit_breaker_until and time.time() < self._circuit_breaker_until:
                raise UpdateFailed("Circuit breaker active")
            else:
                _LOGGER.info("Circuit breaker cooldown expired, resuming operations")
                self._circuit_breaker_active = False
                self._circuit_breaker_until = None
        
        try:
            yield
        except Exception as e:
            # Activate circuit breaker on critical failures
            self._circuit_breaker_active = True
            self._circuit_breaker_until = time.time() + (CIRCUIT_BREAKER_COOLDOWN_MINUTES * 60)
            raise

    @contextmanager
    def _log_operation(self, operation_name: str):
        """Context manager for logging operations with timing."""
        start_time = time.time()
        _LOGGER.debug("Starting %s", operation_name)
        
        try:
            yield
            duration = time.time() - start_time
            _LOGGER.debug(
                "Completed %s in %.3fs", 
                operation_name, 
                duration,
                extra={"operation": operation_name, "duration_ms": round(duration * 1000, 1)}
            )
        except Exception as e:
            duration = time.time() - start_time
            _LOGGER.error(
                "Failed %s after %.3fs: %s", 
                operation_name, 
                duration, 
                e,
                extra={"operation": operation_name, "duration_ms": round(duration * 1000, 1), "error": str(e)}
            )
            raise

    def _log_with_context(self, level: str, message: str, **context):
        """Log with structured context."""
        context_str = " ".join(f"{k}={v}" for k, v in context.items())
        getattr(_LOGGER, level)(f"{message} [{context_str}]")

    def force_update_on_next_refresh(self):
        """Force update on next refresh cycle."""
        self._force_update = True

    def _log_performance_metrics(self, start_time: float, end_time: float, command_count: int):
        """Log structured performance metrics."""
        duration = end_time - start_time
        _LOGGER.info(
            "Update cycle completed",
            extra={
                "duration_ms": round(duration * 1000, 1),
                "command_count": command_count,
                "devices_managed": len(self.config.get(CONF_CLIMATE_DEVICES, [])),
                "schedules_active": len([s for s in self.data.schedule_decisions.values() if s.is_active]) if self.data else 0,
            }
        )

    def _log_circuit_breaker_activation(self, timeout_count: int, device_count: int, timeout_rate: float):
        """Log circuit breaker activation with structured data."""
        _LOGGER.error(
            "Circuit breaker activated due to high timeout rate",
            extra={
                "timeout_count": timeout_count,
                "device_count": device_count,
                "timeout_rate_percent": round(timeout_rate * 100, 1),
                "cooldown_minutes": CIRCUIT_BREAKER_COOLDOWN_MINUTES,
            }
        )
