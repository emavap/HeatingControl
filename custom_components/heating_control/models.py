"""Data models for heating control decisions.

This module contains immutable dataclasses that represent the state and decisions
made by the heating control coordinator. All models include validation, serialization,
and utility methods for robust data handling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Mapping


def _validate_entity_id(entity_id: str) -> bool:
    """Validate entity ID format (domain.entity)."""
    return bool(entity_id) and isinstance(entity_id, str) and entity_id.count('.') == 1

def _clamp_rate(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamp a rate value between min and max."""
    return max(min_val, min(max_val, value))


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

    def __post_init__(self):
        """Validate schedule decision data."""
        if self.device_count != len(self.devices):
            object.__setattr__(self, 'device_count', len(self.devices))

    def is_valid(self) -> bool:
        """Check if schedule decision is valid."""
        return (
            bool(self.schedule_id) and
            bool(self.name) and
            self.device_count >= 0 and
            len(self.devices) == self.device_count
        )

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

    def __post_init__(self):
        """Validate device decision data."""
        if not self.entity_id:
            raise ValueError("Device decision must have entity_id")

    def is_valid(self) -> bool:
        """Check if device decision is valid."""
        return (
            _validate_entity_id(self.entity_id) and
            (self.target_temp is None or self.target_temp > 0)
        )

    def has_temperature_control(self) -> bool:
        """Check if device decision includes temperature control."""
        return self.target_temp is not None and self.hvac_mode in {"heat", "cool", "heat_cool", "auto"}

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
    """Diagnostic information about the current state."""
    
    now_time: str
    tracker_states: Dict[str, str]
    trackers_home: int
    trackers_total: int
    auto_heating_enabled: bool
    schedule_count: int
    active_schedules: int
    active_devices: int
    last_update_duration: Optional[float] = None
    timed_out_devices: Tuple[str, ...] = ()
    watchdog_status: Optional[str] = None
    performance_metrics: Optional[PerformanceMetrics] = None
    schedule_warnings: List[str] = field(default_factory=list)
    device_health: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """Validate diagnostics snapshot data."""
        if self.trackers_home < 0:
            object.__setattr__(self, 'trackers_home', 0)
        if self.trackers_total < 0:
            object.__setattr__(self, 'trackers_total', 0)
        if self.schedule_count < 0:
            object.__setattr__(self, 'schedule_count', 0)
        if self.active_schedules < 0:
            object.__setattr__(self, 'active_schedules', 0)
        if self.active_devices < 0:
            object.__setattr__(self, 'active_devices', 0)

    def is_valid(self) -> bool:
        """Check if diagnostics snapshot is valid."""
        return (
            bool(self.now_time) and
            self.trackers_home >= 0 and
            self.trackers_total >= 0 and
            self.schedule_count >= 0 and
            self.active_schedules >= 0 and
            self.active_devices >= 0 and
            (self.performance_metrics is None or self.performance_metrics.is_valid())
        )

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
            "performance_metrics": self.performance_metrics.as_dict() if self.performance_metrics else None,
            "schedule_warnings": self.schedule_warnings,
            "device_health": self.device_health,
        }


@dataclass(frozen=True)
class PerformanceMetrics:
    """Performance metrics for monitoring coordinator health."""
    avg_update_time: float
    max_update_time: float
    cache_hit_rate: float
    timeout_rate: float
    command_success_rate: float

    def __post_init__(self):
        """Validate performance metrics data."""
        if self.avg_update_time < 0:
            object.__setattr__(self, 'avg_update_time', 0.0)
        if self.max_update_time < 0:
            object.__setattr__(self, 'max_update_time', 0.0)
        if not (0.0 <= self.cache_hit_rate <= 1.0):
            object.__setattr__(self, 'cache_hit_rate', _clamp_rate(self.cache_hit_rate))
        if not (0.0 <= self.timeout_rate <= 1.0):
            object.__setattr__(self, 'timeout_rate', _clamp_rate(self.timeout_rate))
        if not (0.0 <= self.command_success_rate <= 1.0):
            object.__setattr__(self, 'command_success_rate', _clamp_rate(self.command_success_rate))

    def is_valid(self) -> bool:
        """Check if performance metrics are valid."""
        return (
            self.avg_update_time >= 0 and
            self.max_update_time >= 0 and
            0.0 <= self.cache_hit_rate <= 1.0 and
            0.0 <= self.timeout_rate <= 1.0 and
            0.0 <= self.command_success_rate <= 1.0
        )

    def as_dict(self) -> Dict[str, float]:
        """Return a dictionary representation."""
        return {
            "avg_update_time": self.avg_update_time,
            "max_update_time": self.max_update_time,
            "cache_hit_rate": self.cache_hit_rate,
            "timeout_rate": self.timeout_rate,
            "command_success_rate": self.command_success_rate,
        }


@dataclass(frozen=True)
class DevicePerformanceMetrics:
    """Performance metrics per device."""
    
    entity_id: str
    response_time_ms: float
    success_rate: float
    last_command_time: Optional[float]
    timeout_count: int
    success_count: int

    def __post_init__(self):
        """Validate device performance metrics data."""
        if not self.entity_id:
            raise ValueError("Device performance metrics must have entity_id")
        if self.response_time_ms < 0:
            object.__setattr__(self, 'response_time_ms', 0.0)
        if not (0.0 <= self.success_rate <= 1.0):
            object.__setattr__(self, 'success_rate', _clamp_rate(self.success_rate))
        if self.timeout_count < 0:
            object.__setattr__(self, 'timeout_count', 0)
        if self.success_count < 0:
            object.__setattr__(self, 'success_count', 0)

    def is_valid(self) -> bool:
        """Check if device performance metrics are valid."""
        return (
            _validate_entity_id(self.entity_id) and
            self.response_time_ms >= 0 and
            0.0 <= self.success_rate <= 1.0 and
            self.timeout_count >= 0 and
            self.success_count >= 0
        )

    def as_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation."""
        return {
            "entity_id": self.entity_id,
            "response_time_ms": self.response_time_ms,
            "success_rate": self.success_rate,
            "last_command_time": self.last_command_time,
            "timeout_count": self.timeout_count,
            "success_count": self.success_count,
        }


@dataclass(frozen=True)
class HeatingStateSnapshot:
    """Complete state snapshot calculated by the coordinator."""

    everyone_away: bool
    anyone_home: bool
    schedule_decisions: Mapping[str, ScheduleDecision]
    device_decisions: Mapping[str, DeviceDecision]
    diagnostics: DiagnosticsSnapshot

    def get_active_schedules(self) -> List[ScheduleDecision]:
        """Get list of currently active schedules."""
        return [decision for decision in self.schedule_decisions.values() if decision.is_active]

    def get_active_devices(self) -> List[DeviceDecision]:
        """Get list of devices that should be active."""
        return [decision for decision in self.device_decisions.values() if decision.should_be_active]

    def get_schedule_by_id(self, schedule_id: str) -> Optional[ScheduleDecision]:
        """Get schedule decision by ID."""
        return self.schedule_decisions.get(schedule_id)

    def get_device_by_id(self, entity_id: str) -> Optional[DeviceDecision]:
        """Get device decision by entity ID."""
        return self.device_decisions.get(entity_id)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the current state."""
        active_schedules = self.get_active_schedules()
        active_devices = self.get_active_devices()
        
        return {
            "presence": "away" if self.everyone_away else "home",
            "total_schedules": len(self.schedule_decisions),
            "active_schedules": len(active_schedules),
            "total_devices": len(self.device_decisions),
            "active_devices": len(active_devices),
            "schedule_names": [s.name for s in active_schedules],
            "active_device_ids": [d.entity_id for d in active_devices],
        }

    def is_valid(self) -> bool:
        """Check if snapshot is valid."""
        return (
            self.diagnostics is not None and
            all(decision.is_valid() for decision in self.schedule_decisions.values()) and
            all(decision.is_valid() for decision in self.device_decisions.values())
        )

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
