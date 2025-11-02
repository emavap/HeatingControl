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
    BINARY_SENSOR_EVERYONE_AWAY,
)
from .coordinator import HeatingControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [EveryoneAwayBinarySensor(coordinator, entry)]

    # Add per-schedule binary sensors
    if coordinator.data:
        for schedule_id in coordinator.data.schedule_decisions:
            entities.append(ScheduleActiveBinarySensor(coordinator, entry, schedule_id))

        for entity_id in coordinator.data.device_decisions:
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


class EveryoneAwayBinarySensor(HeatingControlBinarySensor):
    """Binary sensor that reports when everyone tracked is away."""

    def __init__(
        self, coordinator: HeatingControlCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            BINARY_SENSOR_EVERYONE_AWAY,
            "Everyone Away",
            "mdi:home-export-outline",
        )
        self._attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    @property
    def is_on(self) -> bool:
        """Return true if everyone is away."""
        snapshot = self.coordinator.data
        return bool(snapshot and snapshot.everyone_away)


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
        schedule = None
        if coordinator.data:
            schedule = coordinator.data.schedule_decisions.get(schedule_id)
        schedule_name = schedule.name if schedule else "Unknown Schedule"

        self._attr_unique_id = f"{entry.entry_id}_schedule_{schedule_id}"
        self._attr_name = f"Heating Schedule {schedule_name}"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        """Return true if schedule is currently active."""
        snapshot = self.coordinator.data
        if not snapshot:
            return False
        schedule = snapshot.schedule_decisions.get(self._schedule_id)
        return bool(schedule and schedule.is_active)

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return additional attributes."""
        snapshot = self.coordinator.data
        schedule = snapshot.schedule_decisions.get(self._schedule_id) if snapshot else None
        if not schedule:
            return {}

        return {
            "schedule_id": schedule.schedule_id,
            "schedule_name": schedule.name,
            "enabled": schedule.enabled,
            "start_time": schedule.start_time,
            "end_time": schedule.end_time,
            "hvac_mode": schedule.hvac_mode,
            "only_when_home": schedule.only_when_home,
            "in_time_window": schedule.in_time_window,
            "presence_ok": schedule.presence_ok,
            "device_count": schedule.device_count,
            "devices": list(schedule.devices),
            "target_temp": schedule.target_temp,
            "target_fan": schedule.target_fan,
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
        snapshot = self.coordinator.data
        if not snapshot:
            return False

        device = snapshot.device_decisions.get(self._device_entity)
        return bool(device and device.should_be_active)

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return additional attributes."""
        snapshot = self.coordinator.data
        device = snapshot.device_decisions.get(self._device_entity) if snapshot else None
        if not device:
            return {}

        active_schedules = list(device.active_schedules)
        return {
            "entity_id": device.entity_id,
            "active_schedules": active_schedules,
            "schedule_count": len(active_schedules),
            "hvac_mode": device.hvac_mode,
            "target_temp": device.target_temp,
            "target_fan": device.target_fan,
        }
