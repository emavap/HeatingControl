"""Switch entities for Heating Control schedules."""
from __future__ import annotations

from typing import Any, Dict, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    CONF_SCHEDULES,
    CONF_SCHEDULE_DEVICES,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_HVAC_MODE,
    CONF_SCHEDULE_AWAY_HVAC_MODE,
    CONF_SCHEDULE_AWAY_TEMPERATURE,
    CONF_SCHEDULE_ID,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_ONLY_WHEN_HOME,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_TEMPERATURE,
    DEFAULT_SCHEDULE_HVAC_MODE,
    DOMAIN,
    SCHEDULE_SWITCH_ENTITY_TEMPLATE,
)
from .coordinator import HeatingControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities for Heating Control schedules."""
    coordinator: HeatingControlCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[ScheduleEnableSwitch] = []

    if coordinator.data:
        for schedule_id in coordinator.data.schedule_decisions:
            entities.append(ScheduleEnableSwitch(coordinator, entry, schedule_id))

    async_add_entities(entities)


class ScheduleEnableSwitch(CoordinatorEntity, SwitchEntity):
    """Switch that enables or disables a Heating Control schedule."""

    _attr_icon = "mdi:calendar-check"
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: HeatingControlCoordinator,
        entry: ConfigEntry,
        schedule_id: str,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator)
        self._schedule_id = schedule_id
        self._entry_id = entry.entry_id

        schedule = self._get_schedule_decision()
        schedule_name = schedule.name if schedule else schedule_id
        slug_entry = slugify(entry.entry_id)
        slug_schedule = slugify(schedule_id)

        self.entity_id = SCHEDULE_SWITCH_ENTITY_TEMPLATE.format(
            entry=slug_entry,
            schedule=slug_schedule,
        )
        self._fallback_name = schedule_name
        self._attr_unique_id = f"{entry.entry_id}_schedule_{schedule_id}_enabled"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="Heating Control",
            manufacturer="Heating Control",
            model="Smart Heating Schedule",
        )

    @property
    def name(self) -> str:
        """Return the display name of the switch."""
        schedule = self._get_schedule_decision()
        if schedule:
            self._fallback_name = schedule.name
        schedule_name = self._fallback_name
        return f"Heating Schedule {schedule_name} Enabled"

    @property
    def is_on(self) -> bool:
        """Return True if the schedule is enabled."""
        schedule = self._get_schedule_decision()
        if schedule:
            return schedule.enabled

        config_enabled = self._config_schedule_enabled()
        return bool(config_enabled)

    @property
    def available(self) -> bool:
        """Return whether the switch is available."""
        if self._get_schedule_decision():
            return True

        config = self.coordinator.config_entry.options or self.coordinator.config_entry.data
        for schedule in config.get(CONF_SCHEDULES, []):
            if self._matches_schedule(schedule):
                return True

        return False

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional metadata for the schedule."""
        schedule = self._get_schedule_decision()
        if schedule:
            return {
                "schedule_id": schedule.schedule_id,
                "start_time": schedule.start_time,
                "end_time": schedule.end_time,
                "hvac_mode": schedule.hvac_mode,
                "only_when_home": schedule.only_when_home,
                "in_time_window": schedule.in_time_window,
                "presence_ok": schedule.presence_ok,
                "device_count": schedule.device_count,
                "target_temp": schedule.target_temp,
                "target_fan": schedule.target_fan,
            }

        config_schedule = self._get_config_schedule()
        if config_schedule:
            return {
                "schedule_id": config_schedule.get(CONF_SCHEDULE_ID, self._schedule_id),
                "start_time": config_schedule.get(CONF_SCHEDULE_START),
                "end_time": config_schedule.get(CONF_SCHEDULE_END),
                "hvac_mode": config_schedule.get(
                    CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE
                ),
                "hvac_mode_away": config_schedule.get(CONF_SCHEDULE_AWAY_HVAC_MODE),
                "only_when_home": config_schedule.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True),
                "device_count": len(config_schedule.get(CONF_SCHEDULE_DEVICES, [])),
                "target_temp": config_schedule.get(CONF_SCHEDULE_TEMPERATURE),
                "target_temp_away": config_schedule.get(CONF_SCHEDULE_AWAY_TEMPERATURE),
            }

        return {"schedule_id": self._schedule_id}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the schedule."""
        await self.coordinator.async_set_schedule_enabled(
            schedule_id=self._schedule_id,
            enabled=True,
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the schedule."""
        await self.coordinator.async_set_schedule_enabled(
            schedule_id=self._schedule_id,
            enabled=False,
        )
        self.async_write_ha_state()

    def _get_schedule_decision(self):
        """Return the current schedule decision snapshot."""
        snapshot = self.coordinator.data
        if not snapshot:
            return None
        return snapshot.schedule_decisions.get(self._schedule_id)

    def _config_schedule_enabled(self) -> Optional[bool]:
        """Return the enabled state from stored config."""
        schedule = self._get_config_schedule()
        if not schedule:
            return None
        return schedule.get(CONF_SCHEDULE_ENABLED, True)

    def _get_config_schedule(self) -> Optional[Dict[str, Any]]:
        """Return the schedule config from entry data/options."""
        config = self.coordinator.config_entry.options or self.coordinator.config_entry.data
        for schedule in config.get(CONF_SCHEDULES, []):
            if self._matches_schedule(schedule):
                return schedule
        return None

    def _matches_schedule(self, schedule: Dict[str, Any]) -> bool:
        """Return True if the config schedule matches this switch."""
        current_id = schedule.get(CONF_SCHEDULE_ID)
        current_name = schedule.get(CONF_SCHEDULE_NAME, "")
        if current_id and current_id == self._schedule_id:
            return True
        return current_name.casefold() == self._fallback_name.casefold()
