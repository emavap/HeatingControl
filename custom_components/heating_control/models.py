"""Data models for heating control decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

__all__ = [
    "ScheduleDecision",
    "DeviceDecision",
    "DiagnosticsSnapshot",
    "HeatingStateSnapshot",
]


@dataclass(frozen=True)
class ScheduleDecision:
    """Decision data for an individual schedule.

    Attributes:
        schedule_id: Unique identifier for this schedule (UUID).
        name: User-friendly display name for the schedule.
        start_time: Schedule start time in "HH:MM" format.
        end_time: Schedule end time in "HH:MM" format (may be auto-derived).
        hvac_mode: Current HVAC mode to apply (considering presence).
        hvac_mode_home: HVAC mode when someone is home.
        hvac_mode_away: HVAC mode when away, or None if not configured.
        only_when_home: Whether schedule requires presence to activate.
        enabled: Whether the schedule is enabled by the user.
        is_active: True if schedule is currently controlling devices.
        in_time_window: True if current time is within schedule window.
        presence_ok: True if presence requirement is satisfied.
        temp_condition: Temperature condition ("always", "cold", "warm").
        temp_condition_met: True if outdoor temp condition is satisfied.
        device_count: Number of climate devices this schedule controls.
        devices: Tuple of climate entity IDs this schedule controls.
        schedule_device_trackers: Per-schedule device trackers, or empty.
        target_temp: Current target temperature (considering presence).
        target_temp_home: Target temperature when home.
        target_temp_away: Target temperature when away, or None.
        target_fan: Fan mode to set, or None if not configured.
    """

    schedule_id: str
    name: str
    start_time: str
    end_time: str
    hvac_mode: str
    hvac_mode_home: str
    hvac_mode_away: Optional[str]
    only_when_home: bool
    enabled: bool
    is_active: bool
    in_time_window: bool
    presence_ok: bool
    temp_condition: str
    temp_condition_met: bool
    device_count: int
    devices: Tuple[str, ...]
    schedule_device_trackers: Tuple[str, ...]
    target_temp: Optional[float]
    target_temp_home: Optional[float]
    target_temp_away: Optional[float]
    target_fan: Optional[str]

    def as_dict(self) -> Dict[str, object]:
        """Return a dictionary representation used by diagnostics and sensors."""
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "hvac_mode": self.hvac_mode,
            "hvac_mode_home": self.hvac_mode_home,
            "hvac_mode_away": self.hvac_mode_away,
            "only_when_home": self.only_when_home,
            "enabled": self.enabled,
            "is_active": self.is_active,
            "in_time_window": self.in_time_window,
            "presence_ok": self.presence_ok,
            "temp_condition": self.temp_condition,
            "temp_condition_met": self.temp_condition_met,
            "device_count": self.device_count,
            "devices": list(self.devices),
            "schedule_device_trackers": list(self.schedule_device_trackers),
            "target_temp": self.target_temp,
            "target_temp_home": self.target_temp_home,
            "target_temp_away": self.target_temp_away,
            "target_fan": self.target_fan,
        }


@dataclass(frozen=True)
class DeviceDecision:
    """Decision data for an individual climate device.

    Attributes:
        entity_id: Climate entity ID (e.g., "climate.bedroom_ac").
        should_be_active: True if device should be actively heating/cooling.
        active_schedules: Tuple of schedule IDs currently controlling this device.
        hvac_mode: HVAC mode to set (heat/cool/off), or None for no action.
        target_temp: Target temperature to set, or None.
        target_fan: Fan mode to set, or None.
    """

    entity_id: str
    should_be_active: bool
    active_schedules: Tuple[str, ...]
    hvac_mode: Optional[str]
    target_temp: Optional[float]
    target_fan: Optional[str]

    def as_dict(self) -> Dict[str, object]:
        """Return a dictionary representation used by diagnostics and sensors."""
        return {
            "entity_id": self.entity_id,
            "should_be_active": self.should_be_active,
            "active_schedules": list(self.active_schedules),
            "hvac_mode": self.hvac_mode,
            "target_temp": self.target_temp,
            "target_fan": self.target_fan,
        }


@dataclass(frozen=True)
class DiagnosticsSnapshot:
    """Diagnostics information about the current coordinator decision state.

    Attributes:
        now_time: Current time string when snapshot was taken.
        tracker_states: Map of device tracker entity ID to home status.
        trackers_home: Count of trackers currently showing "home".
        trackers_total: Total number of configured trackers.
        auto_heating_enabled: Whether automatic heating is globally enabled.
        schedule_count: Total number of configured schedules.
        active_schedules: Number of currently active schedules.
        active_devices: Number of devices with active control.
        last_update_duration: Duration of last update cycle in seconds.
        timed_out_devices: Tuple of entity IDs that timed out during control.
        watchdog_status: Health status ("healthy", "degraded", "stuck").
        outdoor_temp: Current outdoor temperature if sensor is configured, None otherwise.
        outdoor_temp_state: Current outdoor temperature state ("cold" or "warm").
    """

    now_time: str
    tracker_states: Mapping[str, bool]
    trackers_home: int
    trackers_total: int
    auto_heating_enabled: bool
    schedule_count: int
    active_schedules: int
    active_devices: int
    last_update_duration: Optional[float] = None
    timed_out_devices: Tuple[str, ...] = tuple()
    watchdog_status: str = "healthy"
    outdoor_temp: Optional[float] = None
    outdoor_temp_state: str = "warm"

    def as_dict(self) -> Dict[str, object]:
        """Return a dictionary representation used by diagnostics sensors."""
        return {
            "now_time": self.now_time,
            "tracker_states": dict(self.tracker_states),
            "trackers_home": self.trackers_home,
            "trackers_total": self.trackers_total,
            "auto_heating_enabled": self.auto_heating_enabled,
            "schedule_count": self.schedule_count,
            "active_schedules": self.active_schedules,
            "active_devices": self.active_devices,
            "last_update_duration": self.last_update_duration,
            "timed_out_devices": list(self.timed_out_devices),
            "watchdog_status": self.watchdog_status,
            "outdoor_temp": self.outdoor_temp,
            "outdoor_temp_state": self.outdoor_temp_state,
        }


@dataclass(frozen=True)
class HeatingStateSnapshot:
    """Complete state snapshot calculated by the coordinator.

    Attributes:
        everyone_away: True if all tracked persons are away.
        anyone_home: True if at least one tracked person is home.
        schedule_decisions: Map of schedule ID to ScheduleDecision.
        device_decisions: Map of climate entity ID to DeviceDecision.
        diagnostics: Diagnostics metadata about this update cycle.
    """

    everyone_away: bool
    anyone_home: bool
    schedule_decisions: Mapping[str, ScheduleDecision]
    device_decisions: Mapping[str, DeviceDecision]
    diagnostics: DiagnosticsSnapshot

    def as_dict(self) -> Dict[str, object]:
        """Return the snapshot data as dictionaries (for backwards compatibility)."""
        return {
            "everyone_away": self.everyone_away,
            "anyone_home": self.anyone_home,
            "schedule_decisions": {
                key: decision.as_dict()
                for key, decision in self.schedule_decisions.items()
            },
            "device_decisions": {
                key: decision.as_dict()
                for key, decision in self.device_decisions.items()
            },
            "diagnostics": self.diagnostics.as_dict(),
        }
