"""Sensor platform for heating_control."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    SENSOR_DECISION_DIAGNOSTICS,
)
from .coordinator import HeatingControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        HeatingControlDiagnosticsSensor(coordinator, config_entry),
        HeatingControlPerformanceSensor(coordinator, config_entry),
    ]

    async_add_entities(entities)


class HeatingControlSensor(CoordinatorEntity, SensorEntity):
    """Base sensor for heating control."""

    def __init__(
        self,
        coordinator: HeatingControlCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
        name: str,
        icon: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_name = f"Heating Control {name}"
        self._sensor_type = sensor_type
        if icon:
            self._attr_icon = icon

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="Heating Control",
            manufacturer="Heating Control",
            model="Smart Heating Schedule",
        )


class HeatingControlDiagnosticsSensor(HeatingControlSensor):
    """Sensor for decision diagnostics."""

    def __init__(
        self, coordinator: HeatingControlCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SENSOR_DECISION_DIAGNOSTICS,
            "Decision Diagnostics",
            "mdi:chart-box-outline",
        )

    @property
    def native_value(self) -> str:
        """Return the state."""
        snapshot = self.coordinator.data
        if not snapshot:
            return "0/0 schedules active"

        diagnostics = snapshot.diagnostics
        active_schedules = diagnostics.active_schedules
        schedule_count = diagnostics.schedule_count
        return f"{active_schedules}/{schedule_count} schedules active"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the diagnostics as attributes."""
        snapshot = self.coordinator.data
        if not snapshot:
            return {}

        diagnostics = snapshot.diagnostics
        
        # Convert to dict if it has as_dict method, otherwise use dataclass fields
        if hasattr(diagnostics, 'as_dict'):
            attrs = diagnostics.as_dict()
        else:
            attrs = {
                "now_time": diagnostics.now_time,
                "tracker_states": diagnostics.tracker_states,
                "trackers_home": diagnostics.trackers_home,
                "trackers_total": diagnostics.trackers_total,
                "auto_heating_enabled": diagnostics.auto_heating_enabled,
                "schedule_count": diagnostics.schedule_count,
                "active_schedules": diagnostics.active_schedules,
                "active_devices": diagnostics.active_devices,
                "last_update_duration": diagnostics.last_update_duration,
                "timed_out_devices": list(diagnostics.timed_out_devices),
                "watchdog_status": diagnostics.watchdog_status,
                "schedule_warnings": diagnostics.schedule_warnings,
                "device_health": diagnostics.device_health,
            }

        active_devices = sum(
            1 for decision in snapshot.device_decisions.values() if decision.should_be_active
        )

        attrs.update({
            "active_devices": active_devices,
            "total_devices": len(snapshot.device_decisions),
            "everyone_away": snapshot.everyone_away,
            "anyone_home": snapshot.anyone_home,
        })
        
        return attrs


class HeatingControlPerformanceSensor(SensorEntity):
    """Sensor for performance metrics."""

    def __init__(self, coordinator: HeatingControlCoordinator, config_entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_performance"
        self._attr_name = "Heating Control Performance"
        self._attr_device_class = None
        self._attr_state_class = None

    @property
    def native_value(self) -> str:
        """Return performance summary."""
        if not self._coordinator.data or not self._coordinator.data.diagnostics:
            return "No data"
        
        metrics = self._coordinator.data.diagnostics.performance_metrics
        if not metrics:
            return "No metrics"
            
        return f"{metrics.update_duration_ms:.1f}ms"

    @property
    def extra_state_attributes(self) -> dict:
        """Return performance attributes."""
        if not self._coordinator.data or not self._coordinator.data.diagnostics:
            return {}
        
        metrics = self._coordinator.data.diagnostics.performance_metrics
        if not metrics:
            return {}
            
        return {
            "update_duration_ms": round(metrics.update_duration_ms, 1),
            "device_commands": metrics.device_command_count,
            "cache_hit_rate": round(metrics.cache_hit_rate * 100, 1),
            "circuit_breaker_trips": metrics.circuit_breaker_trips,
            "avg_response_time_ms": round(metrics.average_device_response_time, 1),
            "successful_commands": metrics.successful_commands,
            "failed_commands": metrics.failed_commands,
        }

    @property
    def icon(self) -> str:
        return "mdi:speedometer"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        self._coordinator.async_remove_listener(self.async_write_ha_state)
