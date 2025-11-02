"""Data models for heating control decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ScheduleDecision:
    """Decision data for an individual schedule."""

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
    """Decision data for an individual climate device."""

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
    """Diagnostics information about the current coordinator decision state."""

    now_time: str
    tracker_states: Mapping[str, bool]
    trackers_home: int
    trackers_total: int
    auto_heating_enabled: bool
    schedule_count: int
    active_schedules: int
    active_devices: int

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
        }


@dataclass(frozen=True)
class HeatingStateSnapshot:
    """Complete state snapshot calculated by the coordinator."""

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
