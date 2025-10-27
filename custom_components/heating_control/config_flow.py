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
    CONF_DEVICE_TRACKER_1,
    CONF_DEVICE_TRACKER_2,
    CONF_AUTO_HEATING_ENABLED,
    CONF_GAS_HEATER_ENTITY,
    CONF_ONLY_SCHEDULED_ACTIVE,
    CONF_SCHEDULES,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_ALWAYS_ACTIVE,
    CONF_SCHEDULE_ONLY_WHEN_HOME,
    CONF_SCHEDULE_USE_GAS,
    CONF_SCHEDULE_DEVICES,
    CONF_SCHEDULE_TEMPERATURE,
    CONF_SCHEDULE_FAN_MODE,
    CONF_CLIMATE_DEVICES,
    DEFAULT_SCHEDULE_START,
    DEFAULT_SCHEDULE_END,
    DEFAULT_SCHEDULE_TEMPERATURE,
    DEFAULT_SCHEDULE_FAN_MODE,
    DEFAULT_ONLY_SCHEDULED_ACTIVE,
)

_LOGGER = logging.getLogger(__name__)


class HeatingControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Heating Control."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._schedules = []
        self._global_config = {}
        self._available_devices = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - global settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._global_config = user_input
            return await self.async_step_select_devices()

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_GAS_HEATER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_DEVICE_TRACKER_1): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker")
                ),
                vol.Optional(CONF_DEVICE_TRACKER_2): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker")
                ),
                vol.Required(CONF_AUTO_HEATING_ENABLED, default=True): selector.BooleanSelector(),
                vol.Required(
                    CONF_ONLY_SCHEDULED_ACTIVE,
                    default=DEFAULT_ONLY_SCHEDULED_ACTIVE
                ): selector.BooleanSelector(),
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
            self._available_devices = user_input.get(CONF_CLIMATE_DEVICES, [])
            if not self._available_devices:
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
                    **self._global_config,
                    CONF_CLIMATE_DEVICES: self._available_devices,
                    CONF_SCHEDULES: self._schedules,
                }
                return self.async_create_entry(title="Heating Control", data=config_data)

        data_schema = vol.Schema(
            {
                vol.Required("add_schedule", default=True): selector.BooleanSelector(),
            }
        )

        description = f"Schedules configured: {len(self._schedules)}\n\n"
        if self._schedules:
            description += "Schedules:\n"
            for schedule in self._schedules:
                name = schedule.get(CONF_SCHEDULE_NAME, "Unnamed")
                start = schedule.get(CONF_SCHEDULE_START, "")
                end = schedule.get(CONF_SCHEDULE_END, "")
                device_count = len(schedule.get(CONF_SCHEDULE_DEVICES, []))
                use_gas = schedule.get(CONF_SCHEDULE_USE_GAS, False)
                gas_info = " (uses gas heater)" if use_gas else ""
                description += f"- {name} ({start} - {end}): {device_count} devices{gas_info}\n"

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
                "id": str(uuid.uuid4()),
                CONF_SCHEDULE_NAME: user_input[CONF_SCHEDULE_NAME],
                CONF_SCHEDULE_ENABLED: user_input.get(CONF_SCHEDULE_ENABLED, True),
                CONF_SCHEDULE_START: user_input.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START),
                CONF_SCHEDULE_END: user_input.get(CONF_SCHEDULE_END, DEFAULT_SCHEDULE_END),
                CONF_SCHEDULE_ALWAYS_ACTIVE: user_input.get(CONF_SCHEDULE_ALWAYS_ACTIVE, False),
                CONF_SCHEDULE_ONLY_WHEN_HOME: user_input.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True),
                CONF_SCHEDULE_USE_GAS: user_input.get(CONF_SCHEDULE_USE_GAS, False),
                CONF_SCHEDULE_DEVICES: user_input.get(CONF_SCHEDULE_DEVICES, []),
                CONF_SCHEDULE_TEMPERATURE: user_input.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE),
                CONF_SCHEDULE_FAN_MODE: user_input.get(CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE),
            }
            self._schedules.append(schedule_config)
            return await self.async_step_add_schedule()

        # Create device options from available devices
        device_options = [{"label": device, "value": device} for device in self._available_devices]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SCHEDULE_NAME): selector.TextSelector(),
                vol.Required(CONF_SCHEDULE_ENABLED, default=True): selector.BooleanSelector(),
                vol.Required(CONF_SCHEDULE_TEMPERATURE, default=DEFAULT_SCHEDULE_TEMPERATURE): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=30, step=0.5, unit_of_measurement="°C")
                ),
                vol.Required(CONF_SCHEDULE_FAN_MODE, default=DEFAULT_SCHEDULE_FAN_MODE): selector.TextSelector(),
                vol.Required(CONF_SCHEDULE_ALWAYS_ACTIVE, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_SCHEDULE_START, default=DEFAULT_SCHEDULE_START): selector.TimeSelector(),
                vol.Optional(CONF_SCHEDULE_END, default=DEFAULT_SCHEDULE_END): selector.TimeSelector(),
                vol.Required(CONF_SCHEDULE_ONLY_WHEN_HOME, default=True): selector.BooleanSelector(),
                vol.Required(CONF_SCHEDULE_USE_GAS, default=False): selector.BooleanSelector(),
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
                "info": "Configure a schedule with time window and device assignment. "
                        "If 'Use Gas Heater' is enabled, the gas heater will be used instead of the selected devices."
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
        self._schedules = []
        self._global_config = {}
        self._available_devices = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options - global settings."""
        if user_input is not None:
            self._global_config = user_input
            return await self.async_step_select_devices()

        current_config = self.config_entry.options or self.config_entry.data

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_GAS_HEATER_ENTITY,
                    default=current_config.get(CONF_GAS_HEATER_ENTITY)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(
                    CONF_DEVICE_TRACKER_1,
                    default=current_config.get(CONF_DEVICE_TRACKER_1)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker")
                ),
                vol.Optional(
                    CONF_DEVICE_TRACKER_2,
                    default=current_config.get(CONF_DEVICE_TRACKER_2)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker")
                ),
                vol.Required(
                    CONF_AUTO_HEATING_ENABLED,
                    default=current_config.get(CONF_AUTO_HEATING_ENABLED, True)
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_ONLY_SCHEDULED_ACTIVE,
                    default=current_config.get(CONF_ONLY_SCHEDULED_ACTIVE, DEFAULT_ONLY_SCHEDULED_ACTIVE)
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
            self._available_devices = user_input.get(CONF_CLIMATE_DEVICES, [])
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

        if not self._schedules:
            self._schedules = list(current_config.get(CONF_SCHEDULES, []))

        if user_input is not None:
            action = user_input.get("action")

            if action == "add":
                return await self.async_step_add_schedule()
            elif action == "done":
                config_data = {
                    **self._global_config,
                    CONF_CLIMATE_DEVICES: self._available_devices,
                    CONF_SCHEDULES: self._schedules,
                }
                return self.async_create_entry(title="", data=config_data)

        schedule_list = "Schedules:\n\n"
        if self._schedules:
            for idx, schedule in enumerate(self._schedules):
                name = schedule.get(CONF_SCHEDULE_NAME, "Unnamed")
                start = schedule.get(CONF_SCHEDULE_START, "")
                end = schedule.get(CONF_SCHEDULE_END, "")
                device_count = len(schedule.get(CONF_SCHEDULE_DEVICES, []))
                use_gas = schedule.get(CONF_SCHEDULE_USE_GAS, False)
                gas_info = " (uses gas heater)" if use_gas else ""
                schedule_list += f"{idx + 1}. {name} ({start} - {end}): {device_count} devices{gas_info}\n"
        else:
            schedule_list = "No schedules configured yet.\n\n"

        data_schema = vol.Schema(
            {
                vol.Required("action", default="done"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"label": "Add Schedule", "value": "add"},
                            {"label": "Done", "value": "done"},
                        ],
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
        if user_input is not None:
            schedule_config = {
                "id": str(uuid.uuid4()),
                CONF_SCHEDULE_NAME: user_input[CONF_SCHEDULE_NAME],
                CONF_SCHEDULE_ENABLED: user_input.get(CONF_SCHEDULE_ENABLED, True),
                CONF_SCHEDULE_START: user_input.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START),
                CONF_SCHEDULE_END: user_input.get(CONF_SCHEDULE_END, DEFAULT_SCHEDULE_END),
                CONF_SCHEDULE_ALWAYS_ACTIVE: user_input.get(CONF_SCHEDULE_ALWAYS_ACTIVE, False),
                CONF_SCHEDULE_ONLY_WHEN_HOME: user_input.get(CONF_SCHEDULE_ONLY_WHEN_HOME, True),
                CONF_SCHEDULE_USE_GAS: user_input.get(CONF_SCHEDULE_USE_GAS, False),
                CONF_SCHEDULE_DEVICES: user_input.get(CONF_SCHEDULE_DEVICES, []),
                CONF_SCHEDULE_TEMPERATURE: user_input.get(CONF_SCHEDULE_TEMPERATURE, DEFAULT_SCHEDULE_TEMPERATURE),
                CONF_SCHEDULE_FAN_MODE: user_input.get(CONF_SCHEDULE_FAN_MODE, DEFAULT_SCHEDULE_FAN_MODE),
            }
            self._schedules.append(schedule_config)
            return await self.async_step_manage_schedules()

        device_options = [{"label": device, "value": device} for device in self._available_devices]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SCHEDULE_NAME): selector.TextSelector(),
                vol.Required(CONF_SCHEDULE_ENABLED, default=True): selector.BooleanSelector(),
                vol.Required(CONF_SCHEDULE_TEMPERATURE, default=DEFAULT_SCHEDULE_TEMPERATURE): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=30, step=0.5, unit_of_measurement="°C")
                ),
                vol.Required(CONF_SCHEDULE_FAN_MODE, default=DEFAULT_SCHEDULE_FAN_MODE): selector.TextSelector(),
                vol.Required(CONF_SCHEDULE_ALWAYS_ACTIVE, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_SCHEDULE_START, default=DEFAULT_SCHEDULE_START): selector.TimeSelector(),
                vol.Optional(CONF_SCHEDULE_END, default=DEFAULT_SCHEDULE_END): selector.TimeSelector(),
                vol.Required(CONF_SCHEDULE_ONLY_WHEN_HOME, default=True): selector.BooleanSelector(),
                vol.Required(CONF_SCHEDULE_USE_GAS, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_SCHEDULE_DEVICES, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="add_schedule", data_schema=data_schema)
