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

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

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
    DOMAIN,
    ENTITY_DECISION_DIAGNOSTICS,
    ENTITY_EVERYONE_AWAY,
    SCHEDULE_SWITCH_ENTITY_TEMPLATE,
)

if TYPE_CHECKING:
    from homeassistant.components.lovelace.strategy import Strategy as StrategyType

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
        cards.append(self._build_status_grid(snapshot, tracker_entities))

        # Climate controls section
        climate_cards = self._build_climate_grid(climate_entities)
        if climate_cards:
            cards.append(climate_cards)

        # Device status section
        device_status_card = self._build_device_status_section(
            snapshot, climate_entities
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

    def _build_header_card(self) -> Dict[str, Any]:
        """Build the dashboard header with title."""
        return {
            "type": "markdown",
            "content": "## 🌡️ Smart Heating Dashboard",
        }

    def _build_status_grid(
        self, snapshot, tracker_entities: Sequence[str]
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

        buttons: List[Dict[str, Any]] = [
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

        grid: Dict[str, Any] = {
            "type": "grid",
            "square": False,
            "columns": 4,
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
                        "title": "👥 Presence Trackers",
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
                {"type": "markdown", "content": "### 🌡️ Climate Controls"},
                {
                    "type": "grid",
                    "columns": column_count,
                    "square": False,
                    "cards": thermostat_cards,
                },
            ],
        }

    def _build_device_status_section(
        self, snapshot, climate_entities: Sequence[str]
    ) -> Optional[Dict[str, Any]]:
        """Build device status cards showing which schedule controls each device."""
        if not snapshot or not snapshot.device_decisions:
            return None

        device_cards: List[Dict[str, Any]] = []

        for device_entity in climate_entities:
            device_decision = snapshot.device_decisions.get(device_entity)
            device_name = self._friendly_name(device_entity)

            if not device_decision or not device_decision.active_schedules:
                # Device idle - simple tile
                device_cards.append({
                    "type": "tile",
                    "entity": device_entity,
                    "name": device_name,
                    "icon": "mdi:thermostat-off",
                    "color": "grey",
                    "vertical": False,
                })
            else:
                # Device active with schedule
                schedule_name = self._schedule_display_name(
                    snapshot, device_decision.active_schedules[0]
                )
                hvac_mode = device_decision.hvac_mode or "off"
                target_temp = device_decision.target_temp

                # Mode icons
                mode_icons = {
                    "heat": "mdi:fire",
                    "cool": "mdi:snowflake",
                    "heat_cool": "mdi:autorenew",
                    "auto": "mdi:autorenew",
                    "off": "mdi:power-off",
                    "fan_only": "mdi:fan",
                    "dry": "mdi:water-percent",
                }
                icon = mode_icons.get(hvac_mode.lower(), "mdi:thermostat")

                # Build secondary info
                temp_str = f" → {target_temp:g}°" if target_temp is not None else ""
                secondary = f"📅 {schedule_name} • {hvac_mode.title()}{temp_str}"

                device_cards.append({
                    "type": "tile",
                    "entity": device_entity,
                    "name": device_name,
                    "icon": icon,
                    "color": "green" if device_decision.should_be_active else "grey",
                    "vertical": False,
                    "secondary_info": secondary,
                })

        if not device_cards:
            return None

        column_count = min(max(len(device_cards), 1), 2)

        return {
            "type": "vertical-stack",
            "cards": [
                {"type": "markdown", "content": "### 📍 Device Status"},
                {
                    "type": "grid",
                    "columns": column_count,
                    "square": False,
                    "cards": device_cards,
                },
            ],
        }

    def _build_schedule_section(
        self, entry_id: str, snapshot
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
                status = "⏹️ Disabled"
            elif decision.is_active and controlling_count > 0:
                status = "✅ Active"
            elif decision.is_active:
                status = "🔄 Superseded"
            elif decision.in_time_window:
                status = "⏳ Window Open"
            else:
                status = "⏸️ Idle"

            # Time window
            if decision.start_time == decision.end_time:
                time_str = "🕐 All day"
            else:
                window_icon = "🟢" if decision.in_time_window else "⚪"
                time_str = f"{window_icon} {decision.start_time} → {decision.end_time}"

            # Mode icons
            mode_icons = {
                "heat": "🔥", "cool": "❄️", "heat_cool": "🔄",
                "auto": "🔄", "off": "⏹️", "fan_only": "💨", "dry": "💧",
            }

            # Build mode info
            mode_lines: List[str] = []
            if decision.hvac_mode_home:
                icon = mode_icons.get(decision.hvac_mode_home.lower(), "")
                temp = f" {decision.target_temp_home:g}°" if decision.target_temp_home else ""
                mode_lines.append(f"🏠 {icon} {decision.hvac_mode_home.title()}{temp}")
            if decision.hvac_mode_away:
                icon = mode_icons.get(decision.hvac_mode_away.lower(), "")
                temp = f" {decision.target_temp_away:g}°" if decision.target_temp_away else ""
                mode_lines.append(f"🚪 {icon} {decision.hvac_mode_away.title()}{temp}")

            # Presence status
            presence_str = ""
            if decision.only_when_home:
                if decision.presence_ok:
                    presence_str = "🏠 Home ✓"
                elif decision.enabled:
                    presence_str = "🏠 Waiting..."

            # Devices info
            if controlling_count > 0:
                device_names = [self._friendly_name(d) for d in controlling_devices[:2]]
                if controlling_count > 2:
                    devices_str = f"✅ {', '.join(device_names)} +{controlling_count - 2}"
                else:
                    devices_str = f"✅ {', '.join(device_names)}"
            else:
                cfg_count = decision.device_count
                devices_str = f"⏸️ {cfg_count} device{'s' if cfg_count != 1 else ''}" if cfg_count else "—"

            # Build card with switch and info
            card_entities: List[Dict[str, Any]] = [
                {"entity": switch_entity, "name": "Enabled"},
                {"type": "text", "name": "Time", "text": time_str},
                {"type": "text", "name": "Status", "text": status},
            ]

            if presence_str:
                card_entities.append({"type": "text", "name": "Presence", "text": presence_str})

            for mode_line in mode_lines:
                card_entities.append({"type": "text", "name": "Mode", "text": mode_line})

            if decision.target_fan:
                card_entities.append({"type": "text", "name": "Fan", "text": f"💨 {decision.target_fan}"})

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
                {"type": "markdown", "content": "### 📅 Schedules"},
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
        """Return a Home Assistant friendly name for an entity id."""
        if not entity_id:
            return ""

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

        # Fallback to a slugified title when no friendly name is available
        return entity_id.split(".", 1)[-1].replace("_", " ").title()

    def _schedule_display_name(self, snapshot, schedule_ref: Optional[str]) -> str:
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
        """Return a status icon for a schedule based on its current state."""
        if not decision.enabled:
            return "⏹️"
        elif decision.is_active:
            return "✅"
        elif decision.in_time_window:
            return "⏳"
        else:
            return "📅"

    @staticmethod
    def _schedule_switch_entity(entry_id: str, schedule_id: str) -> str:
        """Return the switch entity id for toggling a schedule."""
        return SCHEDULE_SWITCH_ENTITY_TEMPLATE.format(
            entry=slugify(entry_id),
            schedule=slugify(schedule_id),
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
