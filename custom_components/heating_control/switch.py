"""Switch entities for Heating Control schedules."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
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
        self._pending_enabled_state: Optional[bool] = None
        self._pending_clear_unsub: Optional[Callable[[], None]] = None
        # Cache for config schedule to reduce repeated lookups
        self._cached_config_schedule: Optional[Dict[str, Any]] = None

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
        if self._pending_enabled_state is not None:
            return self._pending_enabled_state

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

        # Check if schedule exists in config
        if self._get_config_schedule():
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
        # Optimistically expose the new state until the coordinator refresh completes
        self._pending_enabled_state = True
        self._schedule_pending_clear()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the schedule."""
        await self.coordinator.async_set_schedule_enabled(
            schedule_id=self._schedule_id,
            enabled=False,
        )
        # Optimistically expose the new state until the coordinator refresh completes
        self._pending_enabled_state = False
        self._schedule_pending_clear()
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        """Clear any pending state overrides when fresh data arrives."""
        self._cancel_pending_clear()
        # Clear optimistic state on failed updates to revert UI to actual state
        if self.coordinator.last_update_success is False and self._pending_enabled_state is not None:
            self._pending_enabled_state = None
        elif self.coordinator.last_update_success:
            # Successful update - optimistic state no longer needed
            self._pending_enabled_state = None
        # Invalidate config schedule cache on coordinator update
        self._cached_config_schedule = None
        super()._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up any scheduled callbacks."""
        self._cancel_pending_clear()
        await super().async_will_remove_from_hass()

    def _get_schedule_decision(self) -> Optional[Any]:
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
        """Return the schedule config from entry data/options.

        Uses caching to reduce repeated lookups. Cache is invalidated on coordinator updates.
        Falls back to name matching if ID lookup fails (for robustness).
        """
        # Return cached value if available
        if self._cached_config_schedule is not None:
            return self._cached_config_schedule

        # Try coordinator's helper (matches by ID or exact name)
        schedule = self.coordinator.get_schedule_by_id(self._schedule_id)

        # Fallback: if not found and we have a fallback name, try case-insensitive name match
        if not schedule and self._fallback_name:
            schedules = self.coordinator.config.get(CONF_SCHEDULES, [])
            fallback_name_lower = self._fallback_name.casefold()
            for sched in schedules:
                if sched.get(CONF_SCHEDULE_NAME, "").casefold() == fallback_name_lower:
                    schedule = sched
                    break

        # Cache the result (even if None) to avoid repeated lookups
        self._cached_config_schedule = schedule
        return schedule

    def _clear_pending_state(self, *_args: Any) -> None:
        """Drop optimistic state if the coordinator never confirms."""
        if self._pending_enabled_state is None:
            return
        self._pending_enabled_state = None
        self._cancel_pending_clear()
        self.async_write_ha_state()

    def _schedule_pending_clear(self) -> None:
        """Ensure optimistic state is cleared even when refresh keeps failing.

        Timeout is set to 2x the coordinator update interval to allow for
        one potentially slow update cycle before reverting optimistic state.
        """
        self._cancel_pending_clear()
        # Scale timeout with coordinator update interval (2x with 60s minimum)
        timeout_seconds = max(60, int(self.coordinator.update_interval.total_seconds() * 2))
        self._pending_clear_unsub = async_call_later(
            self.hass,
            timeout_seconds,
            self._clear_pending_state,
        )

    def _cancel_pending_clear(self) -> None:
        """Cancel any scheduled optimistic-state reset."""
        if self._pending_clear_unsub:
            self._pending_clear_unsub()
            self._pending_clear_unsub = None
