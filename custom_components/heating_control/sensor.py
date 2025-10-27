"""Sensor platform for heating_control."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
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
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_name = f"Heating Control {name}"
        self._sensor_type = sensor_type
        if icon:
            self._attr_icon = icon


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
        diagnostics = self.coordinator.data.get("diagnostics", {})
        active_schedules = diagnostics.get("active_schedules", 0)
        schedule_count = diagnostics.get("schedule_count", 0)
        return f"{active_schedules}/{schedule_count} schedules active"

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return the diagnostics as attributes."""
        data = self.coordinator.data
        diagnostics = data.get("diagnostics", {})

        # Add device summary
        device_decisions = data.get("device_decisions", {})
        active_devices = sum(1 for d in device_decisions.values() if d.get("should_be_active"))

        # Add schedule summary
        schedule_decisions = data.get("schedule_decisions", {})

        return {
            **diagnostics,
            "active_devices": active_devices,
            "total_devices": len(device_decisions),
            "both_away": data.get("both_away"),
            "anyone_home": data.get("anyone_home"),
        }
