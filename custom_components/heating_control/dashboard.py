"""Dynamic Lovelace dashboard strategy for Heating Control.

This dashboard strategy generates a modern Lovelace dashboard inspired by
electricity_planner's design. Uses panel view with vertical-stack for a clean,
responsive layout that works well on all screen sizes.

Key features:
- Modern header with markdown and visual gauges
- Grid of status buttons for at-a-glance system state
- Compact schedule cards with markdown formatting
- Thermostat cards in responsive grid
- Quick action buttons for common operations
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.components.lovelace.strategy import Strategy as LovelaceStrategy
except ImportError:  # Home Assistant version without Lovelace strategies support
    LovelaceStrategy = None

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import slugify

from .const import (
    CONF_CLIMATE_DEVICES,
    CONF_DEVICE_TRACKERS,
    CONF_DISABLED_DEVICES,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_OUTDOOR_TEMP_THRESHOLD,
    DEFAULT_OUTDOOR_TEMP_THRESHOLD,
    DEVICE_SWITCH_ENTITY_TEMPLATE,
    DOMAIN,
    ENTITY_DECISION_DIAGNOSTICS,
    ENTITY_EVERYONE_AWAY,
    SCHEDULE_SWITCH_ENTITY_TEMPLATE,
    STATUS_IDLE,
    STATUS_OFF,
    STATUS_ON,
    STATUS_WAIT,
)

if TYPE_CHECKING:
    from homeassistant.components.lovelace.strategy import Strategy as StrategyType
    from .models import HeatingStateSnapshot

if LovelaceStrategy is not None:
    Strategy: type[StrategyType] = LovelaceStrategy
    SUPPORTS_DASHBOARD_STRATEGY = True
else:
    SUPPORTS_DASHBOARD_STRATEGY = False

    class Strategy:  # type: ignore[misc]
        """Fallback base strategy for Home Assistant versions without native support."""

        def __init__(
            self, hass: HomeAssistant, config: Optional[dict[str, Any]] = None
        ) -> None:
            self.hass = hass
            self.config: dict[str, Any] = config or {}

        async def async_generate(self) -> Dict[str, Any]:
            """Raise as strategies are unsupported in this HA version."""
            raise NotImplementedError(
                "Lovelace dashboard strategies are not supported by this Home Assistant version"
            )


async def async_get_strategy(hass: HomeAssistant, config: dict[str, Any]) -> Strategy:
    """Return a Heating Control dashboard strategy instance."""
    if not SUPPORTS_DASHBOARD_STRATEGY:
        raise HomeAssistantError(
            "Lovelace dashboard strategies are not supported by this Home Assistant version"
        )
    return HeatingControlDashboardStrategy(hass, config)


class HeatingControlDashboardStrategy(Strategy):
    """Strategy that builds a Smart Heating dashboard from integration data."""

    def __init__(self, hass: HomeAssistant, config: Optional[dict[str, Any]] = None) -> None:
        """Initialise the strategy."""
        super().__init__(hass, config or {})

    async def async_generate(self) -> Dict[str, Any]:
        """Return the Lovelace dashboard configuration.

        Modern panel-based dashboard with vertical-stack layout:
        - Header with title and presence status
        - Quick status buttons in a grid
        - Climate controls (thermostat cards)
        - Device status cards
        - Schedule cards with rich formatting
        """
        try:
            coordinator = self._resolve_coordinator()
            if coordinator is None:
                return self._build_message(
                    "Heating Control",
                    "Heating Control integration is not loaded. "
                    "Add the integration and ensure it is configured before using this dashboard.",
                )

            entry_id = coordinator.config_entry.entry_id
            climate_entities: Sequence[str] = self._get_config_list(
                coordinator, CONF_CLIMATE_DEVICES
            )
            snapshot = coordinator.data

            tracker_entities: Sequence[str] = self._get_config_list(
                coordinator, CONF_DEVICE_TRACKERS
            )

            # Build all card components
            cards: List[Dict[str, Any]] = []

            # Header section
            cards.append(self._build_header_card())

            # Quick status grid with buttons
            cards.append(self._build_status_grid(snapshot, tracker_entities, coordinator))

            # Climate controls section
            climate_cards = self._build_climate_grid(climate_entities)
            if climate_cards:
                cards.append(climate_cards)

            # Device status section (with enable/disable switches)
            disabled_devices: Sequence[str] = self._get_config_list(
                coordinator, CONF_DISABLED_DEVICES
            )
            device_status_card = self._build_device_status_section(
                entry_id, snapshot, climate_entities, disabled_devices
            )
            if device_status_card:
                cards.append(device_status_card)

            # Schedules section
            schedule_section = self._build_schedule_section(entry_id, snapshot)
            if schedule_section:
                cards.append(schedule_section)

            return {
                "title": "Smart Heating",
                "views": [
                    {
                        "title": "Smart Heating",
                        "path": "smart-heating",
                        "icon": "mdi:thermostat",
                        "panel": True,
                        "cards": [
                            {
                                "type": "vertical-stack",
                                "cards": cards,
                            }
                        ],
                    }
                ],
            }
        except Exception as err:
            _LOGGER.exception("Error generating dashboard: %s", err)
            return self._build_message(
                "Dashboard Error",
                f"An error occurred while generating the dashboard: {err}",
            )

    def _build_header_card(self) -> Dict[str, Any]:
        """Build the dashboard header with title."""
        return {
            "type": "markdown",
            "content": "## Smart Heating Dashboard",
        }

    def _build_status_grid(
        self, snapshot: Optional["HeatingStateSnapshot"], tracker_entities: Sequence[str], coordinator=None
    ) -> Dict[str, Any]:
        """Build a grid of status buttons for at-a-glance system state."""
        diagnostics = getattr(snapshot, "diagnostics", None) if snapshot else None
        anyone_home = getattr(snapshot, "anyone_home", True) if snapshot else True

        active_schedules = 0
        total_schedules = 0
        active_devices = 0
        if diagnostics:
            active_schedules = getattr(diagnostics, "active_schedules", 0)
            total_schedules = getattr(diagnostics, "schedule_count", 0)
            active_devices = getattr(diagnostics, "active_devices", 0)

        # Get outdoor temperature sensor and threshold from config
        outdoor_temp_sensor = None
        outdoor_temp_threshold = DEFAULT_OUTDOOR_TEMP_THRESHOLD
        if coordinator:
            config = coordinator.config
            outdoor_temp_sensor = config.get(CONF_OUTDOOR_TEMP_SENSOR)
            outdoor_temp_threshold = config.get(CONF_OUTDOOR_TEMP_THRESHOLD, DEFAULT_OUTDOOR_TEMP_THRESHOLD)

        # Get outdoor temperature state from diagnostics
        outdoor_temp = getattr(diagnostics, "outdoor_temp", None) if diagnostics else None
        outdoor_temp_state = getattr(diagnostics, "outdoor_temp_state", "warm") if diagnostics else "warm"
        is_cold = outdoor_temp_state == "cold"

        # Check if master heating is enabled
        auto_heating_enabled = getattr(diagnostics, "auto_heating_enabled", True) if diagnostics else True

        buttons: List[Dict[str, Any]] = [
            # Master on/off switch
            {
                "type": "button",
                "entity": "switch.heating_control_master",
                "name": "All Heating",
                "icon": "mdi:power" if auto_heating_enabled else "mdi:power-off",
                "icon_height": "50px",
                "show_name": True,
                "show_state": True,
                "tap_action": {"action": "toggle"},
            },
            # Presence button
            {
                "type": "button",
                "entity": ENTITY_EVERYONE_AWAY,
                "name": "Home" if anyone_home else "Away",
                "icon": "mdi:home-account" if anyone_home else "mdi:home-outline",
                "icon_height": "50px",
                "show_name": True,
                "show_state": True,
                "tap_action": {"action": "more-info"},
            },
            # Active schedules indicator
            {
                "type": "button",
                "name": f"{active_schedules}/{total_schedules}",
                "icon": "mdi:calendar-check" if active_schedules > 0 else "mdi:calendar-blank",
                "icon_height": "50px",
                "show_name": True,
                "show_icon": True,
                "tap_action": {"action": "none"},
            },
            # Active devices indicator
            {
                "type": "button",
                "name": f"{active_devices} Active",
                "icon": "mdi:thermostat" if active_devices > 0 else "mdi:thermostat-off",
                "icon_height": "50px",
                "show_name": True,
                "show_icon": True,
                "tap_action": {"action": "none"},
            },
            # Refresh button
            {
                "type": "button",
                "entity": ENTITY_DECISION_DIAGNOSTICS,
                "name": "Refresh",
                "icon": "mdi:refresh",
                "icon_height": "50px",
                "show_name": True,
                "show_state": False,
                "tap_action": {
                    "action": "call-service",
                    "service": "homeassistant.update_entity",
                    "data": {"entity_id": ENTITY_DECISION_DIAGNOSTICS},
                },
            },
        ]

        # Add outdoor temperature button if sensor is configured
        if outdoor_temp_sensor:
            # Show current temp, mode (cold/warm), and threshold
            if outdoor_temp is not None:
                temp_display = f"{outdoor_temp:g}°"
            else:
                temp_display = "N/A"
            mode_label = "Cold" if is_cold else "Warm"
            mode_icon = "mdi:snowflake" if is_cold else "mdi:weather-sunny"

            buttons.insert(1, {
                "type": "button",
                "entity": outdoor_temp_sensor,
                "name": f"{mode_label} (<{outdoor_temp_threshold:g}°)",
                "icon": mode_icon,
                "icon_height": "50px",
                "show_name": True,
                "show_state": True,
                "tap_action": {"action": "more-info"},
            })

        grid: Dict[str, Any] = {
            "type": "grid",
            "square": False,
            "columns": 6 if outdoor_temp_sensor else 5,
            "cards": buttons,
        }

        # Add presence trackers if configured
        if tracker_entities:
            tracker_items = [
                {"entity": t, "name": self._friendly_name(t)}
                for t in tracker_entities
            ]
            return {
                "type": "vertical-stack",
                "cards": [
                    grid,
                    {
                        "type": "entities",
                        "title": "Presence Trackers",
                        "entities": tracker_items,
                        "state_color": True,
                    },
                ],
            }

        return grid

    def _build_climate_grid(
        self, climate_entities: Sequence[str]
    ) -> Optional[Dict[str, Any]]:
        """Build thermostat cards grid for climate devices."""
        if not climate_entities:
            return None

        thermostat_cards = [
            {
                "type": "thermostat",
                "entity": entity,
                "name": self._friendly_name(entity),
            }
            for entity in climate_entities
        ]

        column_count = min(max(len(thermostat_cards), 1), 3)

        return {
            "type": "vertical-stack",
            "cards": [
                {"type": "markdown", "content": "### Climate Controls"},
                {
                    "type": "grid",
                    "columns": column_count,
                    "square": False,
                    "cards": thermostat_cards,
                },
            ],
        }

    def _build_device_status_section(
        self,
        entry_id: str,
        snapshot: Optional["HeatingStateSnapshot"],
        climate_entities: Sequence[str],
        disabled_devices: Sequence[str],
    ) -> Optional[Dict[str, Any]]:
        """Build device status cards with enable/disable switches.

        Each device gets an entities card showing:
        - Enable/disable switch for automatic control
        - Current status (active schedule, HVAC mode, temperature)
        """
        if not climate_entities:
            return None

        device_cards: List[Dict[str, Any]] = []
        disabled_set = set(disabled_devices)

        for device_entity in climate_entities:
            device_decision = None
            if snapshot and snapshot.device_decisions:
                device_decision = snapshot.device_decisions.get(device_entity)

            device_name = self._friendly_name(device_entity)
            switch_entity = self._device_switch_entity(entry_id, device_entity)
            is_disabled = device_entity in disabled_set

            # Build status text based on device state
            if is_disabled:
                status_text = "Disabled - manual control"
                status_icon = STATUS_OFF
            elif device_decision and device_decision.active_schedules:
                schedule_name = self._schedule_display_name(
                    snapshot, device_decision.active_schedules[0]
                )
                hvac_mode = device_decision.hvac_mode or "off"
                target_temp = device_decision.target_temp
                temp_str = f" @ {target_temp:g}°" if target_temp is not None else ""
                status_text = f"{schedule_name} | {hvac_mode.title()}{temp_str}"
                status_icon = STATUS_ON if device_decision.should_be_active else STATUS_IDLE
            else:
                status_text = "Idle - no active schedule"
                status_icon = STATUS_IDLE

            # Build card entities
            card_entities: List[Dict[str, Any]] = [
                {"entity": switch_entity, "name": "Auto Control"},
                {"type": "text", "name": "Status", "text": status_text},
            ]

            device_cards.append({
                "type": "entities",
                "title": f"{status_icon} {device_name}",
                "entities": card_entities,
                "state_color": True,
            })

        if not device_cards:
            return None

        column_count = min(max(len(device_cards), 1), 2)

        return {
            "type": "vertical-stack",
            "cards": [
                {"type": "markdown", "content": "### Device Status"},
                {
                    "type": "grid",
                    "columns": column_count,
                    "square": False,
                    "cards": device_cards,
                },
            ],
        }

    def _build_schedule_section(
        self, entry_id: str, snapshot: Optional["HeatingStateSnapshot"]
    ) -> Optional[Dict[str, Any]]:
        """Build modern schedule cards with rich formatting."""
        if not snapshot or not snapshot.schedule_decisions:
            return None

        # Build map of which devices are controlled by each schedule
        schedule_to_devices: Dict[str, List[str]] = {}
        if snapshot.device_decisions:
            for device_entity, device_decision in snapshot.device_decisions.items():
                if device_decision.active_schedules:
                    for sched_name in device_decision.active_schedules:
                        schedule_to_devices.setdefault(sched_name, []).append(
                            device_entity
                        )

        schedule_cards: List[Dict[str, Any]] = []

        for decision in snapshot.schedule_decisions.values():
            switch_entity = self._schedule_switch_entity(entry_id, decision.schedule_id)
            controlling_devices = schedule_to_devices.get(decision.name, [])
            controlling_count = len(controlling_devices)

            # Status text
            if not decision.enabled:
                status = "Disabled"
            elif decision.is_active and controlling_count > 0:
                status = "Active"
            elif decision.is_active:
                status = "Superseded"
            elif decision.in_time_window:
                status = "Window open"
            else:
                status = "Idle"

            # Time window
            if decision.start_time == decision.end_time:
                time_str = "All day"
            else:
                window_marker = "(now)" if decision.in_time_window else ""
                time_str = f"{decision.start_time} - {decision.end_time} {window_marker}".strip()

            # Build mode info
            mode_lines: List[str] = []
            if decision.hvac_mode_home:
                temp = f" @ {decision.target_temp_home:g}°" if decision.target_temp_home else ""
                mode_lines.append(f"Home: {decision.hvac_mode_home.title()}{temp}")
            if decision.hvac_mode_away:
                temp = f" @ {decision.target_temp_away:g}°" if decision.target_temp_away else ""
                mode_lines.append(f"Away: {decision.hvac_mode_away.title()}{temp}")

            # Presence status
            presence_str = ""
            if decision.only_when_home:
                if decision.presence_ok:
                    presence_str = "Home required: Yes"
                elif decision.enabled:
                    presence_str = "Home required: Waiting..."

            # Temperature condition status
            temp_condition_str = ""
            temp_condition = getattr(decision, "temp_condition", "always")
            temp_condition_met = getattr(decision, "temp_condition_met", True)
            if temp_condition != "always":
                condition_label = "Cold only" if temp_condition == "cold" else "Warm only"
                if temp_condition_met:
                    temp_condition_str = f"{condition_label}: ✓"
                elif decision.enabled:
                    temp_condition_str = f"{condition_label}: ✗"

            # Devices info
            if controlling_count > 0:
                device_names = [self._friendly_name(d) for d in controlling_devices[:2]]
                if controlling_count > 2:
                    devices_str = f"Controlling: {', '.join(device_names)} +{controlling_count - 2}"
                else:
                    devices_str = f"Controlling: {', '.join(device_names)}"
            else:
                cfg_count = decision.device_count
                devices_str = f"Configured: {cfg_count} device{'s' if cfg_count != 1 else ''}" if cfg_count else "—"

            # Build card with switch and info
            card_entities: List[Dict[str, Any]] = [
                {"entity": switch_entity, "name": "Enabled"},
                {"type": "text", "name": "Time", "text": time_str},
                {"type": "text", "name": "Status", "text": status},
            ]

            if presence_str:
                card_entities.append({"type": "text", "name": "Presence", "text": presence_str})

            if temp_condition_str:
                card_entities.append({"type": "text", "name": "Temp Condition", "text": temp_condition_str})

            for mode_line in mode_lines:
                card_entities.append({"type": "text", "name": "Mode", "text": mode_line})

            if decision.target_fan:
                card_entities.append({"type": "text", "name": "Fan", "text": decision.target_fan})

            card_entities.append({"type": "text", "name": "Devices", "text": devices_str})

            # Schedule card with status icon in title
            status_icon = self._get_schedule_status_icon(decision)
            schedule_cards.append({
                "type": "entities",
                "title": f"{status_icon} {decision.name}",
                "entities": card_entities,
                "state_color": True,
            })

        if not schedule_cards:
            return None

        column_count = min(max(len(schedule_cards), 1), 3)

        return {
            "type": "vertical-stack",
            "cards": [
                {"type": "markdown", "content": "### Schedules"},
                {
                    "type": "grid",
                    "columns": column_count,
                    "square": False,
                    "cards": schedule_cards,
                },
            ],
        }

    def _resolve_coordinator(self):
        """Return the coordinator for the requested config entry (or the first available)."""
        entry_id = self.config.get("entry_id")
        domain_data = self.hass.data.get(DOMAIN)
        if not domain_data:
            return None

        if entry_id:
            return domain_data.get(entry_id)

        # Fallback to the first coordinator for this integration
        return next(iter(domain_data.values()), None)

    def _friendly_name(self, entity_id: str) -> str:
        """Return a Home Assistant friendly name for an entity id.

        Checks multiple sources in order of preference:
        1. State attributes (friendly_name) - most accurate when available
        2. Entity registry (name or original_name) - available at boot before states
        3. Slugified entity_id - fallback when nothing else is available
        """
        if not entity_id:
            return ""

        # Try state attributes first (most accurate when available)
        hass_states = getattr(self.hass, "states", None)
        if hass_states:
            state = hass_states.get(entity_id)
            if state:
                friendly_name = state.attributes.get("friendly_name")
                if isinstance(friendly_name, str) and friendly_name.strip():
                    return friendly_name

                state_name = getattr(state, "name", None)
                if isinstance(state_name, str) and state_name.strip():
                    return state_name

        # Try entity registry (available earlier than states at boot)
        try:
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(self.hass)
            entry = registry.async_get(entity_id)
            if entry:
                # Prefer user-set name, then original name
                if entry.name and entry.name.strip():
                    return entry.name
                if entry.original_name and entry.original_name.strip():
                    return entry.original_name
        except Exception:
            pass  # Entity registry not available or other error

        # Fallback to a slugified title when no friendly name is available
        return entity_id.split(".", 1)[-1].replace("_", " ").title()

    def _schedule_display_name(
        self, snapshot: Optional["HeatingStateSnapshot"], schedule_ref: Optional[str]
    ) -> str:
        """Return a friendly name for a schedule using snapshot data when possible."""
        if not schedule_ref:
            return ""

        schedule_decisions = getattr(snapshot, "schedule_decisions", None)
        if schedule_decisions:
            # Direct lookup by schedule_id (mapping keys) or by stored name
            decision = schedule_decisions.get(schedule_ref)
            if decision:
                decision_name = getattr(decision, "name", None)
                if isinstance(decision_name, str) and decision_name.strip():
                    return decision_name

            for decision in schedule_decisions.values():
                schedule_id = getattr(decision, "schedule_id", None)
                decision_name = getattr(decision, "name", None)
                if schedule_ref in (schedule_id, decision_name):
                    if isinstance(decision_name, str) and decision_name.strip():
                        return decision_name
                    break

        return schedule_ref

    def _get_schedule_status_icon(self, decision) -> str:
        """Return a status marker for a schedule based on its current state."""
        if not decision.enabled:
            return STATUS_OFF
        elif decision.is_active:
            return STATUS_ON
        elif decision.in_time_window:
            return STATUS_WAIT
        else:
            return ""

    @staticmethod
    def _schedule_switch_entity(entry_id: str, schedule_id: str) -> str:
        """Return the switch entity id for toggling a schedule."""
        return SCHEDULE_SWITCH_ENTITY_TEMPLATE.format(
            entry=slugify(entry_id),
            schedule=slugify(schedule_id),
        )

    @staticmethod
    def _device_switch_entity(entry_id: str, device_entity_id: str) -> str:
        """Return the switch entity id for enabling/disabling a device."""
        # Extract device name from entity_id (e.g., climate.bedroom_ac -> bedroom_ac)
        device_slug = slugify(device_entity_id.replace("climate.", ""))
        return DEVICE_SWITCH_ENTITY_TEMPLATE.format(
            entry=slugify(entry_id),
            device=device_slug,
        )

    @staticmethod
    def _build_message(title: str, message: str) -> Dict[str, Any]:
        """Return a simple dashboard with a markdown message."""
        return {
            "title": title,
            "views": [
                {
                    "title": title,
                    "path": "smart-heating",
                    "type": "sections",
                    "sections": [
                        {
                            "type": "grid",
                            "cards": [
                                {
                                    "type": "markdown",
                                    "content": message,
                                }
                            ],
                        }
                    ],
                }
            ],
        }

    @staticmethod
    def _get_config_list(coordinator, key: str) -> Sequence[str]:
        """Return a list configuration value (options preferred over data)."""
        options = coordinator.config_entry.options
        if key in options:
            value = options.get(key)
            return value if value is not None else []
        data = coordinator.config_entry.data
        return data.get(key, [])
