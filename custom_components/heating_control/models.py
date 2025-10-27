"""Data models for heating control decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ScheduleDecision:
    """Decision data for an individual schedule."""

    schedule_id: str
    name: str
    enabled: bool
    is_active: bool
    in_time_window: bool
    presence_ok: bool
    use_gas_heater: bool
    device_count: int
    devices: Tuple[str, ...]
    target_temp: float
    target_fan: str

    def as_dict(self) -> Dict[str, object]:
        """Return a dictionary representation used by diagnostics and sensors."""
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "enabled": self.enabled,
            "is_active": self.is_active,
            "in_time_window": self.in_time_window,
            "presence_ok": self.presence_ok,
            "use_gas_heater": self.use_gas_heater,
            "device_count": self.device_count,
            "devices": list(self.devices),
            "target_temp": self.target_temp,
            "target_fan": self.target_fan,
        }


@dataclass(frozen=True)
class DeviceDecision:
    """Decision data for an individual climate device."""

    entity_id: str
    should_be_active: bool
    active_schedules: Tuple[str, ...]
    target_temp: float
    target_fan: str

    def as_dict(self) -> Dict[str, object]:
        """Return a dictionary representation used by diagnostics and sensors."""
        return {
            "entity_id": self.entity_id,
            "should_be_active": self.should_be_active,
            "active_schedules": list(self.active_schedules),
            "target_temp": self.target_temp,
            "target_fan": self.target_fan,
        }


@dataclass(frozen=True)
class GasHeaterDecision:
    """Decision data for the gas heater."""

    entity_id: str
    should_be_active: bool
    target_temp: float
    target_fan: str
    active_schedules: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        """Return a dictionary representation used by diagnostics and sensors."""
        return {
            "entity_id": self.entity_id,
            "should_be_active": self.should_be_active,
            "target_temp": self.target_temp,
            "target_fan": self.target_fan,
            "active_schedules": list(self.active_schedules),
        }


@dataclass(frozen=True)
class DiagnosticsSnapshot:
    """Diagnostics information about the current coordinator decision state."""

    now_time: str
    tracker_states: Mapping[str, bool]
    trackers_home: int
    trackers_total: int
    auto_heating_enabled: bool
    only_scheduled_active: bool
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
            "only_scheduled_active": self.only_scheduled_active,
            "schedule_count": self.schedule_count,
            "active_schedules": self.active_schedules,
            "active_devices": self.active_devices,
        }


@dataclass(frozen=True)
class HeatingStateSnapshot:
    """Complete state snapshot calculated by the coordinator."""

    both_away: bool
    anyone_home: bool
    schedule_decisions: Mapping[str, ScheduleDecision]
    device_decisions: Mapping[str, DeviceDecision]
    gas_heater_decision: Optional[GasHeaterDecision]
    diagnostics: DiagnosticsSnapshot

    def as_dict(self) -> Dict[str, object]:
        """Return the snapshot data as dictionaries (for backwards compatibility)."""
        return {
            "both_away": self.both_away,
            "anyone_home": self.anyone_home,
            "schedule_decisions": {
                key: decision.as_dict()
                for key, decision in self.schedule_decisions.items()
            },
            "device_decisions": {
                key: decision.as_dict()
                for key, decision in self.device_decisions.items()
            },
            "gas_heater_decision": (
                self.gas_heater_decision.as_dict()
                if self.gas_heater_decision
                else {}
            ),
            "diagnostics": self.diagnostics.as_dict(),
        }
