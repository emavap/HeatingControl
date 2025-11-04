"""Sensor platform for heating_control."""
from __future__ import annotations

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
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            DecisionDiagnosticsSensor(coordinator, entry),
        ]
    )


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


class DecisionDiagnosticsSensor(HeatingControlSensor):
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
    def extra_state_attributes(self) -> dict[str, any]:
        """Return the diagnostics as attributes."""
        snapshot = self.coordinator.data
        if not snapshot:
            return {}

        diagnostics = snapshot.diagnostics.as_dict()

        active_devices = sum(
            1 for decision in snapshot.device_decisions.values() if decision.should_be_active
        )

        diagnostics.update(
            {
                "active_devices": active_devices,
                "total_devices": len(snapshot.device_decisions),
                "everyone_away": snapshot.everyone_away,
                "anyone_home": snapshot.anyone_home,
            }
        )
        return diagnostics
