"""Config flow for Heating Control integration."""
from __future__ import annotations

import logging
from typing import Any
import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_DEVICE_TRACKERS,
    CONF_AUTO_HEATING_ENABLED,
    CONF_SCHEDULES,
    CONF_SCHEDULE_ID,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_ONLY_WHEN_HOME,
    CONF_SCHEDULE_DEVICE_TRACKERS,
    CONF_SCHEDULE_HVAC_MODE,
    CONF_SCHEDULE_AWAY_HVAC_MODE,
    CONF_SCHEDULE_AWAY_TEMPERATURE,
    CONF_SCHEDULE_DEVICES,
    CONF_SCHEDULE_TEMPERATURE,
    CONF_SCHEDULE_FAN_MODE,
    CONF_CLIMATE_DEVICES,
    DEFAULT_SCHEDULE_START,
    DEFAULT_SCHEDULE_END,
    DEFAULT_SCHEDULE_TEMPERATURE,
    DEFAULT_SCHEDULE_HVAC_MODE,
    DEFAULT_SCHEDULE_FAN_MODE,
    DEFAULT_SCHEDULE_AWAY_HVAC_MODE,
)

_LOGGER = logging.getLogger(__name__)


def _extract_trackers(config: dict[str, Any] | None) -> list[str]:
    """Return configured device trackers."""
    if not config:
        return []

    trackers = config.get(CONF_DEVICE_TRACKERS, [])
    return list(trackers)


class HeatingControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Heating Control."""

    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self):
        """Initialize the config flow state containers."""
        # In-progress schedules gathered before creating the entry
        self._pending_schedules: list[dict[str, Any]] = []
        # Global integration settings from the initial step
        self._global_settings: dict[str, Any] = {}
        # Climate devices chosen for Heating Control management
        self._selected_climate_entities: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - global settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._global_settings = {
                **user_input,
                CONF_DEVICE_TRACKERS: list(user_input.get(CONF_DEVICE_TRACKERS, [])),
            }
            return await self.async_step_select_devices()

        default_trackers = _extract_trackers(self._global_settings)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DEVICE_TRACKERS,
                    default=default_trackers,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker", multiple=True)
                ),
                vol.Required(CONF_AUTO_HEATING_ENABLED, default=True): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select which climate devices to manage."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._selected_climate_entities = user_input.get(CONF_CLIMATE_DEVICES, [])
            if not self._selected_climate_entities:
                errors["base"] = "no_devices"
            else:
                return await self.async_step_add_schedule()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_CLIMATE_DEVICES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate", multiple=True)
                ),
            }
        )

        return self.async_show_form(
            step_id="select_devices",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "info": "Select all climate devices (aircos, heaters) that you want to manage with schedules."
            }
        )

    async def async_step_add_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask if user wants to add a schedule."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("add_schedule"):
                return await self.async_step_schedule_config()
            else:
                # Done adding schedules, create the entry
                await self.async_set_unique_id("heating_control_instance")
                self._abort_if_unique_id_configured()

                config_data = {
                    **self._global_settings,
                    CONF_CLIMATE_DEVICES: self._selected_climate_entities,
                    CONF_SCHEDULES: self._pending_schedules,
                }
                return self.async_create_entry(title="Heating Control", data=config_data)

        data_schema = vol.Schema(
            {
                vol.Required("add_schedule", default=True): selector.BooleanSelector(),
            }
        )

        description = f"Schedules configured: {len(self._pending_schedules)}\n\n"
        if self._pending_schedules:
            description += "Schedules:\n"
            for schedule in self._pending_schedules:
                name = schedule.get(CONF_SCHEDULE_NAME, "Unnamed")
                start = schedule.get(CONF_SCHEDULE_START, "")
                device_count = len(schedule.get(CONF_SCHEDULE_DEVICES, []))
                hvac_mode = schedule.get(
                    CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE
                )
                description += (
                    f"- {name} (starts {start}, auto end, mode {hvac_mode}): "
                    f"{device_count} devices\n"
                )

        return self.async_show_form(
            step_id="add_schedule",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"schedules": description}
        )

    async def async_step_schedule_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure a single schedule."""
        errors: dict[str, str] = {}

        if user_input is not None:
            schedule_config = {
                CONF_SCHEDULE_ID: str(uuid.uuid4()),
                CONF_SCHEDULE_NAME: user_input[CONF_SCHEDULE_NAME],
                CONF_SCHEDULE_ENABLED: user_input.get(CONF_SCHEDULE_ENABLED, True),
                CONF_SCHEDULE_START: user_input.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START),
                CONF_SCHEDULE_HVAC_MODE: user_input.get(
                    CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE
                ),
                CONF_SCHEDULE_ONLY_WHEN_HOME: user_input.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True),
                CONF_SCHEDULE_DEVICE_TRACKERS: list(user_input.get(CONF_SCHEDULE_DEVICE_TRACKERS, [])),
                CONF_SCHEDULE_DEVICES: user_input.get(CONF_SCHEDULE_DEVICES, []),
                CONF_SCHEDULE_TEMPERATURE: user_input.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE),
                CONF_SCHEDULE_FAN_MODE: user_input.get(CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE),
            }

            away_mode = user_input.get(CONF_SCHEDULE_AWAY_HVAC_MODE, "inherit")
            away_temp = user_input.get(CONF_SCHEDULE_AWAY_TEMPERATURE)

            # Validate away settings
            if away_temp is not None and (not away_mode or away_mode == "inherit"):
                errors["away_temperature"] = "away_temp_without_mode"

            if not errors:
                if away_mode and away_mode != "inherit":
                    schedule_config[CONF_SCHEDULE_AWAY_HVAC_MODE] = away_mode
                    if away_temp is not None:
                        schedule_config[CONF_SCHEDULE_AWAY_TEMPERATURE] = away_temp
                self._pending_schedules.append(schedule_config)
                return await self.async_step_add_schedule()

        # Create device options from available devices
        device_options = [{"label": device, "value": device} for device in self._selected_climate_entities]

        hvac_options = [
            {"label": "Heat", "value": "heat"},
            {"label": "Cool", "value": "cool"},
            {"label": "Heat/Cool", "value": "heat_cool"},
            {"label": "Off", "value": "off"},
            {"label": "Auto", "value": "auto"},
            {"label": "Dry", "value": "dry"},
            {"label": "Fan Only", "value": "fan_only"},
        ]

        away_hvac_options = [{"label": "Use home HVAC mode", "value": "inherit"}] + hvac_options

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SCHEDULE_NAME): selector.TextSelector(),
                vol.Required(CONF_SCHEDULE_ENABLED, default=True): selector.BooleanSelector(),
                vol.Required(
                    CONF_SCHEDULE_HVAC_MODE,
                    default=DEFAULT_SCHEDULE_HVAC_MODE,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=hvac_options,
                        multiple=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_SCHEDULE_TEMPERATURE, default=DEFAULT_SCHEDULE_TEMPERATURE): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=30, step=0.5, unit_of_measurement="°C")
                ),
                vol.Required(CONF_SCHEDULE_FAN_MODE, default=DEFAULT_SCHEDULE_FAN_MODE): selector.TextSelector(),
                vol.Optional(CONF_SCHEDULE_START, default=DEFAULT_SCHEDULE_START): selector.TimeSelector(),
                vol.Required(CONF_SCHEDULE_ONLY_WHEN_HOME, default=True): selector.BooleanSelector(),
                vol.Optional(CONF_SCHEDULE_DEVICE_TRACKERS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker", multiple=True)
                ),
                vol.Optional(CONF_SCHEDULE_AWAY_HVAC_MODE, default="inherit"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=away_hvac_options,
                        multiple=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_SCHEDULE_AWAY_TEMPERATURE): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=30, step=0.5, unit_of_measurement="°C")
                ),
                vol.Optional(CONF_SCHEDULE_DEVICES, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="schedule_config",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "info": (
                    "Configure a schedule with a start time; it stays active until the next schedule starts. "
                    "Select HVAC modes and temperatures for when people are home, and optionally different settings "
                    "for when everyone is away."
                )
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HeatingControlOptionsFlow:
        """Get the options flow for this handler."""
        return HeatingControlOptionsFlow(config_entry)


class HeatingControlOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Heating Control."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        # Mutable copy of current schedules shown in the options flow
        self._pending_schedules: list[dict[str, Any]] = []
        # Updated global settings staged during the options flow
        self._global_settings: dict[str, Any] = {}
        # Snapshot of the climate devices selection
        self._selected_climate_entities: list[str] = []
        # Index of the schedule currently being edited (if any)
        self._active_schedule_index: int | None = None

    def _build_schedule_options(self) -> list[dict[str, str]]:
        """Build schedule selector options for edit/delete operations."""
        return [
            {
                "label": f"{idx + 1}. {schedule.get(CONF_SCHEDULE_NAME, 'Unnamed')} "
                         f"(starts {schedule.get(CONF_SCHEDULE_START, '')}, mode "
                         f"{schedule.get(CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE)}"
                         + (
                             f" / away {schedule.get(CONF_SCHEDULE_AWAY_HVAC_MODE)}"
                             if schedule.get(CONF_SCHEDULE_AWAY_HVAC_MODE)
                             else ""
                         )
                         + ")",
                "value": str(idx)
            }
            for idx, schedule in enumerate(self._pending_schedules)
        ]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options - global settings."""
        if user_input is not None:
            self._global_settings = {
                **user_input,
                CONF_DEVICE_TRACKERS: list(user_input.get(CONF_DEVICE_TRACKERS, [])),
            }
            return await self.async_step_select_devices()

        current_config = self.config_entry.options or self.config_entry.data
        default_trackers = _extract_trackers(current_config)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DEVICE_TRACKERS,
                    default=default_trackers,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker", multiple=True)
                ),
                vol.Required(
                    CONF_AUTO_HEATING_ENABLED,
                    default=current_config.get(CONF_AUTO_HEATING_ENABLED, True)
                ): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select which climate devices to manage."""
        current_config = self.config_entry.options or self.config_entry.data

        if user_input is not None:
            self._selected_climate_entities = user_input.get(CONF_CLIMATE_DEVICES, [])
            return await self.async_step_manage_schedules()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_CLIMATE_DEVICES,
                    default=current_config.get(CONF_CLIMATE_DEVICES, [])
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate", multiple=True)
                ),
            }
        )

        return self.async_show_form(step_id="select_devices", data_schema=data_schema)

    async def async_step_manage_schedules(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage schedules."""
        current_config = self.config_entry.options or self.config_entry.data

        if not self._pending_schedules:
            self._pending_schedules = list(current_config.get(CONF_SCHEDULES, []))

        if user_input is not None:
            action = user_input.get("action")

            if action == "add":
                return await self.async_step_add_schedule()
            elif action == "edit":
                return await self.async_step_select_schedule_to_edit()
            elif action == "delete":
                return await self.async_step_select_schedule_to_delete()
            elif action == "done":
                config_data = {
                    **self._global_settings,
                    CONF_CLIMATE_DEVICES: self._selected_climate_entities,
                    CONF_SCHEDULES: self._pending_schedules,
                }
                return self.async_create_entry(title="", data=config_data)

        schedule_list = "Schedules:\n\n"
        if self._pending_schedules:
            for idx, schedule in enumerate(self._pending_schedules):
                name = schedule.get(CONF_SCHEDULE_NAME, "Unnamed")
                start = schedule.get(CONF_SCHEDULE_START, "")
                device_count = len(schedule.get(CONF_SCHEDULE_DEVICES, []))
                hvac_mode = schedule.get(
                    CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE
                )
                away_mode = schedule.get(CONF_SCHEDULE_AWAY_HVAC_MODE)
                away_fragment = f", away {away_mode}" if away_mode else ""
                schedule_list += (
                    f"{idx + 1}. {name} (starts {start}, auto end, mode {hvac_mode}{away_fragment}): "
                    f"{device_count} devices\n"
                )
        else:
            schedule_list = "No schedules configured yet.\n\n"

        # Build action options based on whether schedules exist
        action_options = [{"label": "Add Schedule", "value": "add"}]
        if self._pending_schedules:
            action_options.extend([
                {"label": "Edit Schedule", "value": "edit"},
                {"label": "Delete Schedule", "value": "delete"},
            ])
        action_options.append({"label": "Done", "value": "done"})

        data_schema = vol.Schema(
            {
                vol.Required("action", default="done"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=action_options,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="manage_schedules",
            data_schema=data_schema,
            description_placeholders={"schedules": schedule_list}
        )

    async def async_step_add_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a schedule."""
        errors: dict[str, str] = {}

        if user_input is not None:
            schedule_config = {
                CONF_SCHEDULE_ID: str(uuid.uuid4()),
                CONF_SCHEDULE_NAME: user_input[CONF_SCHEDULE_NAME],
                CONF_SCHEDULE_ENABLED: user_input.get(CONF_SCHEDULE_ENABLED, True),
                CONF_SCHEDULE_START: user_input.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START),
                CONF_SCHEDULE_HVAC_MODE: user_input.get(
                    CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE
                ),
                CONF_SCHEDULE_ONLY_WHEN_HOME: user_input.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True),
                CONF_SCHEDULE_DEVICE_TRACKERS: list(user_input.get(CONF_SCHEDULE_DEVICE_TRACKERS, [])),
                CONF_SCHEDULE_DEVICES: user_input.get(CONF_SCHEDULE_DEVICES, []),
                CONF_SCHEDULE_TEMPERATURE: user_input.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE),
                CONF_SCHEDULE_FAN_MODE: user_input.get(CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE),
            }

            away_mode = user_input.get(CONF_SCHEDULE_AWAY_HVAC_MODE, "inherit")
            away_temp = user_input.get(CONF_SCHEDULE_AWAY_TEMPERATURE)

            # Validate away settings
            if away_temp is not None and (not away_mode or away_mode == "inherit"):
                errors["away_temperature"] = "away_temp_without_mode"

            if not errors:
                if away_mode and away_mode != "inherit":
                    schedule_config[CONF_SCHEDULE_AWAY_HVAC_MODE] = away_mode
                    if away_temp is not None:
                        schedule_config[CONF_SCHEDULE_AWAY_TEMPERATURE] = away_temp
                self._pending_schedules.append(schedule_config)
                return await self.async_step_manage_schedules()

        device_options = [{"label": device, "value": device} for device in self._selected_climate_entities]

        hvac_options = [
            {"label": "Heat", "value": "heat"},
            {"label": "Cool", "value": "cool"},
            {"label": "Heat/Cool", "value": "heat_cool"},
            {"label": "Off", "value": "off"},
            {"label": "Auto", "value": "auto"},
            {"label": "Dry", "value": "dry"},
            {"label": "Fan Only", "value": "fan_only"},
        ]

        away_hvac_options = [{"label": "Use home HVAC mode", "value": "inherit"}] + hvac_options

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SCHEDULE_NAME): selector.TextSelector(),
                vol.Required(CONF_SCHEDULE_ENABLED, default=True): selector.BooleanSelector(),
                vol.Required(
                    CONF_SCHEDULE_HVAC_MODE,
                    default=DEFAULT_SCHEDULE_HVAC_MODE,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=hvac_options,
                        multiple=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_SCHEDULE_TEMPERATURE, default=DEFAULT_SCHEDULE_TEMPERATURE): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=30, step=0.5, unit_of_measurement="°C")
                ),
                vol.Required(CONF_SCHEDULE_FAN_MODE, default=DEFAULT_SCHEDULE_FAN_MODE): selector.TextSelector(),
                vol.Optional(CONF_SCHEDULE_START, default=DEFAULT_SCHEDULE_START): selector.TimeSelector(),
                vol.Required(CONF_SCHEDULE_ONLY_WHEN_HOME, default=True): selector.BooleanSelector(),
                vol.Optional(CONF_SCHEDULE_DEVICE_TRACKERS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker", multiple=True)
                ),
                vol.Optional(CONF_SCHEDULE_AWAY_HVAC_MODE, default="inherit"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=away_hvac_options,
                        multiple=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_SCHEDULE_AWAY_TEMPERATURE): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=30, step=0.5, unit_of_measurement="°C")
                ),
                vol.Optional(CONF_SCHEDULE_DEVICES, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="add_schedule",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "info": (
                    "Configure a schedule with a start time; it stays active until the next schedule starts. "
                    "Select HVAC modes and temperatures for when people are home, and optionally different settings "
                    "for when everyone is away."
                )
            }
        )

    async def async_step_select_schedule_to_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select which schedule to edit."""
        # Guard: Ensure schedules exist
        if not self._pending_schedules:
            _LOGGER.warning("Attempted to edit schedule but no schedules available")
            return await self.async_step_manage_schedules()

        if user_input is not None:
            try:
                self._active_schedule_index = int(user_input.get("schedule_index"))
                return await self.async_step_edit_schedule()
            except (ValueError, TypeError) as err:
                _LOGGER.error("Invalid schedule index selected: %s", err)
                return await self.async_step_manage_schedules()

        # Build schedule options using helper
        schedule_options = self._build_schedule_options()

        data_schema = vol.Schema(
            {
                vol.Required("schedule_index"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=schedule_options,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="select_schedule_to_edit",
            data_schema=data_schema,
            description_placeholders={"info": "Select a schedule to edit."}
        )

    async def async_step_edit_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit an existing schedule."""
        # Validate index bounds
        if self._active_schedule_index is None or not (0 <= self._active_schedule_index < len(self._pending_schedules)):
            _LOGGER.error("Invalid schedule index for edit: %s (total: %d)",
                         self._active_schedule_index, len(self._pending_schedules))
            self._active_schedule_index = None
            return await self.async_step_manage_schedules()

        if user_input is not None:
            try:
                # Update the schedule at the stored index
                existing_schedule = self._pending_schedules[self._active_schedule_index]
                schedule_config = {
                    CONF_SCHEDULE_ID: existing_schedule.get(CONF_SCHEDULE_ID, str(uuid.uuid4())),
                    CONF_SCHEDULE_NAME: user_input[CONF_SCHEDULE_NAME],
                    CONF_SCHEDULE_ENABLED: user_input.get(CONF_SCHEDULE_ENABLED, True),
                    CONF_SCHEDULE_START: user_input.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START),
                    CONF_SCHEDULE_HVAC_MODE: user_input.get(
                        CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE
                    ),
                    CONF_SCHEDULE_ONLY_WHEN_HOME: user_input.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True),
                    CONF_SCHEDULE_DEVICE_TRACKERS: list(user_input.get(CONF_SCHEDULE_DEVICE_TRACKERS, [])),
                    CONF_SCHEDULE_DEVICES: user_input.get(CONF_SCHEDULE_DEVICES, []),
                    CONF_SCHEDULE_TEMPERATURE: user_input.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE),
                    CONF_SCHEDULE_FAN_MODE: user_input.get(CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE),
                }
                away_mode = user_input.get(CONF_SCHEDULE_AWAY_HVAC_MODE, "inherit")
                away_temp = user_input.get(CONF_SCHEDULE_AWAY_TEMPERATURE)

                # Validate away settings
                errors: dict[str, str] = {}
                if away_temp is not None and (not away_mode or away_mode == "inherit"):
                    errors["away_temperature"] = "away_temp_without_mode"

                if errors:
                    # Return to the same form with errors
                    pass  # Will fall through to show form with errors
                else:
                    if away_mode and away_mode != "inherit":
                        schedule_config[CONF_SCHEDULE_AWAY_HVAC_MODE] = away_mode
                        if away_temp is not None:
                            schedule_config[CONF_SCHEDULE_AWAY_TEMPERATURE] = away_temp
                    else:
                        schedule_config.pop(CONF_SCHEDULE_AWAY_HVAC_MODE, None)
                        schedule_config.pop(CONF_SCHEDULE_AWAY_TEMPERATURE, None)
                    if CONF_SCHEDULE_END in existing_schedule:
                        schedule_config[CONF_SCHEDULE_END] = existing_schedule[CONF_SCHEDULE_END]
                    self._pending_schedules[self._active_schedule_index] = schedule_config
                    self._active_schedule_index = None
                    return await self.async_step_manage_schedules()
            except (IndexError, KeyError) as err:
                _LOGGER.error("Error updating schedule: %s", err)
                self._active_schedule_index = None
                return await self.async_step_manage_schedules()

        # Get current schedule data
        current_schedule = self._pending_schedules[self._active_schedule_index]
        device_options = [{"label": device, "value": device} for device in self._selected_climate_entities]
        hvac_options = [
            {"label": "Heat", "value": "heat"},
            {"label": "Cool", "value": "cool"},
            {"label": "Heat/Cool", "value": "heat_cool"},
            {"label": "Off", "value": "off"},
            {"label": "Auto", "value": "auto"},
            {"label": "Dry", "value": "dry"},
            {"label": "Fan Only", "value": "fan_only"},
        ]
        away_hvac_options = [{"label": "Use home HVAC mode", "value": "inherit"}] + hvac_options

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCHEDULE_NAME,
                    default=current_schedule.get(CONF_SCHEDULE_NAME, "")
                ): selector.TextSelector(),
                vol.Required(
                    CONF_SCHEDULE_ENABLED,
                    default=current_schedule.get(CONF_SCHEDULE_ENABLED, True)
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_SCHEDULE_HVAC_MODE,
                    default=current_schedule.get(CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=hvac_options,
                        multiple=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_SCHEDULE_TEMPERATURE,
                    default=current_schedule.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=30, step=0.5, unit_of_measurement="°C")
                ),
                vol.Required(
                    CONF_SCHEDULE_FAN_MODE,
                    default=current_schedule.get(CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE)
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_SCHEDULE_START,
                    default=current_schedule.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START)
                ): selector.TimeSelector(),
                vol.Optional(
                    CONF_SCHEDULE_AWAY_HVAC_MODE,
                    default=current_schedule.get(CONF_SCHEDULE_AWAY_HVAC_MODE, "inherit")
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=away_hvac_options,
                        multiple=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_SCHEDULE_AWAY_TEMPERATURE,
                    default=current_schedule.get(CONF_SCHEDULE_AWAY_TEMPERATURE)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=30, step=0.5, unit_of_measurement="°C")
                ),
                vol.Required(
                    CONF_SCHEDULE_ONLY_WHEN_HOME,
                    default=current_schedule.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True)
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_SCHEDULE_DEVICE_TRACKERS,
                    default=current_schedule.get(CONF_SCHEDULE_DEVICE_TRACKERS, [])
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker", multiple=True)
                ),
                vol.Optional(
                    CONF_SCHEDULE_DEVICES,
                    default=current_schedule.get(CONF_SCHEDULE_DEVICES, [])
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        # Build detailed schedule information
        schedule_info_parts = [
            f"**Editing schedule: {current_schedule.get(CONF_SCHEDULE_NAME, 'Unnamed')}**",
            "",
            f"**Current Configuration:**",
            f"- Start Time: {current_schedule.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START)}",
            f"- HVAC Mode (Home): {current_schedule.get(CONF_SCHEDULE_HVAC_MODE, DEFAULT_SCHEDULE_HVAC_MODE).title()}",
            f"- Temperature (Home): {current_schedule.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE)}°C",
        ]

        away_mode = current_schedule.get(CONF_SCHEDULE_AWAY_HVAC_MODE)
        away_temp = current_schedule.get(CONF_SCHEDULE_AWAY_TEMPERATURE)
        if away_mode:
            schedule_info_parts.append(f"- HVAC Mode (Away): {away_mode.title()}")
        if away_temp is not None:
            schedule_info_parts.append(f"- Temperature (Away): {away_temp}°C")

        fan_mode = current_schedule.get(CONF_SCHEDULE_FAN_MODE)
        if fan_mode:
            schedule_info_parts.append(f"- Fan Mode: {fan_mode}")

        schedule_info_parts.append(f"- Only When Home: {'Yes' if current_schedule.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True) else 'No'}")

        devices = current_schedule.get(CONF_SCHEDULE_DEVICES, [])
        if devices:
            schedule_info_parts.append(f"- Devices: {len(devices)}")

        schedule_info = "\n".join(schedule_info_parts)

        return self.async_show_form(
            step_id="edit_schedule",
            data_schema=data_schema,
            description_placeholders={
                "info": schedule_info
            }
        )

    async def async_step_select_schedule_to_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select which schedule to delete."""
        # Guard: Ensure schedules exist
        if not self._pending_schedules:
            _LOGGER.warning("Attempted to delete schedule but no schedules available")
            return await self.async_step_manage_schedules()

        if user_input is not None:
            try:
                self._active_schedule_index = int(user_input.get("schedule_index"))
                return await self.async_step_confirm_delete()
            except (ValueError, TypeError) as err:
                _LOGGER.error("Invalid schedule index selected: %s", err)
                return await self.async_step_manage_schedules()

        # Build schedule options using helper
        schedule_options = self._build_schedule_options()

        data_schema = vol.Schema(
            {
                vol.Required("schedule_index"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=schedule_options,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="select_schedule_to_delete",
            data_schema=data_schema,
            description_placeholders={"info": "Select a schedule to delete."}
        )

    async def async_step_confirm_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm deletion of a schedule."""
        # Validate index bounds
        if self._active_schedule_index is None or not (0 <= self._active_schedule_index < len(self._pending_schedules)):
            _LOGGER.error("Invalid schedule index for delete: %s (total: %d)",
                         self._active_schedule_index, len(self._pending_schedules))
            self._active_schedule_index = None
            return await self.async_step_manage_schedules()

        schedule_to_delete = self._pending_schedules[self._active_schedule_index]
        schedule_name = schedule_to_delete.get(CONF_SCHEDULE_NAME, "Unnamed")

        if user_input is not None:
            action = user_input.get("action")
            if action == "confirm":
                try:
                    # Delete the schedule
                    _LOGGER.info("Deleting schedule: %s", schedule_name)
                    del self._pending_schedules[self._active_schedule_index]
                    self._active_schedule_index = None
                except IndexError as err:
                    _LOGGER.error("Error deleting schedule: %s", err)
                    self._active_schedule_index = None
            else:
                # Cancel deletion
                _LOGGER.debug("Schedule deletion cancelled: %s", schedule_name)
                self._active_schedule_index = None
            return await self.async_step_manage_schedules()

        # Use select dropdown for better UX instead of boolean toggle
        data_schema = vol.Schema(
            {
                vol.Required("action", default="cancel"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"label": "← Cancel - Don't delete", "value": "cancel"},
                            {"label": f"🗑️ Yes, delete '{schedule_name}'", "value": "confirm"},
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="confirm_delete",
            data_schema=data_schema,
            description_placeholders={
                "info": f"You are about to delete the schedule: '{schedule_name}'\n\n"
                        f"Starts at: {schedule_to_delete.get(CONF_SCHEDULE_START, '')} (auto end)\n"
                        f"Devices: {len(schedule_to_delete.get(CONF_SCHEDULE_DEVICES, []))}\n\n"
                        "This action cannot be undone."
            }
        )
