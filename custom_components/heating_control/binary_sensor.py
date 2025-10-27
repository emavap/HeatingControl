"""Binary sensor platform for heating_control."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    BINARY_SENSOR_BOTH_AWAY,
)
from .coordinator import HeatingControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        BothAwayBinarySensor(coordinator, entry),
        GasHeaterBinarySensor(coordinator, entry),
    ]

    # Add per-schedule binary sensors
    if coordinator.data:
        schedule_decisions = coordinator.data.get("schedule_decisions", {})
        for schedule_id, schedule_data in schedule_decisions.items():
            entities.append(ScheduleActiveBinarySensor(coordinator, entry, schedule_id))

        # Add per-device binary sensors
        device_decisions = coordinator.data.get("device_decisions", {})
        for entity_id in device_decisions.keys():
            entities.append(DeviceActiveBinarySensor(coordinator, entry, entity_id))

    async_add_entities(entities)


class HeatingControlBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Base binary sensor for heating control."""

    def __init__(
        self,
        coordinator: HeatingControlCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
        name: str,
        icon: str | None = None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_name = f"Heating Control {name}"
        self._sensor_type = sensor_type
        if icon:
            self._attr_icon = icon


class BothAwayBinarySensor(HeatingControlBinarySensor):
    """Binary sensor for both away status."""

    def __init__(
        self, coordinator: HeatingControlCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            BINARY_SENSOR_BOTH_AWAY,
            "Both Away",
            "mdi:home-export-outline",
        )
        self._attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    @property
    def is_on(self) -> bool:
        """Return true if both residents are away."""
        return self.coordinator.data.get("both_away", False)


class GasHeaterBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for gas heater active status."""

    def __init__(
        self, coordinator: HeatingControlCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_gas_heater"
        self._attr_name = "Heating Gas Heater"
        self._attr_icon = "mdi:fire"
        self._attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        """Return true if gas heater should be active."""
        gas_heater_decision = self.coordinator.data.get("gas_heater_decision", {})
        return gas_heater_decision.get("should_be_active", False)

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return additional attributes."""
        gas_heater_decision = self.coordinator.data.get("gas_heater_decision", {})

        return {
            "entity_id": gas_heater_decision.get("entity_id"),
            "target_temp": gas_heater_decision.get("target_temp"),
            "target_fan": gas_heater_decision.get("target_fan"),
            "active_schedules": gas_heater_decision.get("active_schedules", []),
        }


class ScheduleActiveBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for schedule active status."""

    def __init__(
        self, coordinator: HeatingControlCoordinator, entry: ConfigEntry, schedule_id: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._schedule_id = schedule_id
        self._entry_id = entry.entry_id

        # Get schedule info from coordinator data
        schedule_data = coordinator.data.get("schedule_decisions", {}).get(schedule_id, {})
        schedule_name = schedule_data.get("name", "Unknown Schedule")

        self._attr_unique_id = f"{entry.entry_id}_schedule_{schedule_id}"
        self._attr_name = f"Heating Schedule {schedule_name}"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        """Return true if schedule is currently active."""
        schedule_decisions = self.coordinator.data.get("schedule_decisions", {})
        schedule_data = schedule_decisions.get(self._schedule_id, {})
        return schedule_data.get("is_active", False)

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return additional attributes."""
        schedule_decisions = self.coordinator.data.get("schedule_decisions", {})
        schedule_data = schedule_decisions.get(self._schedule_id, {})
        return {
            "schedule_name": schedule_data.get("name"),
            "in_time_window": schedule_data.get("in_time_window"),
            "presence_ok": schedule_data.get("presence_ok"),
            "use_gas_heater": schedule_data.get("use_gas_heater"),
            "device_count": schedule_data.get("device_count"),
            "devices": schedule_data.get("devices", []),
            "target_temp": schedule_data.get("target_temp"),
            "target_fan": schedule_data.get("target_fan"),
        }


class DeviceActiveBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for individual device active status."""

    def __init__(
        self, coordinator: HeatingControlCoordinator, entry: ConfigEntry, device_entity: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_entity = device_entity
        self._entry_id = entry.entry_id

        # Generate a safe unique ID from the entity ID
        safe_id = device_entity.replace("climate.", "").replace(".", "_")
        self._attr_unique_id = f"{entry.entry_id}_device_{safe_id}"
        self._attr_name = f"Heating {device_entity.replace('climate.', '').replace('_', ' ').title()}"
        self._attr_icon = "mdi:radiator"
        self._attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        """Return true if device should be active."""
        device_decisions = self.coordinator.data.get("device_decisions", {})
        device_data = device_decisions.get(self._device_entity, {})
        return device_data.get("should_be_active", False)

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return additional attributes."""
        device_decisions = self.coordinator.data.get("device_decisions", {})
        device_data = device_decisions.get(self._device_entity, {})
        return {
            "entity_id": device_data.get("entity_id"),
            "active_schedules": device_data.get("active_schedules", []),
            "schedule_count": len(device_data.get("active_schedules", [])),
            "target_temp": device_data.get("target_temp"),
            "target_fan": device_data.get("target_fan"),
        }
