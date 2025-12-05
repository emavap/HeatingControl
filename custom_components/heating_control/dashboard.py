"""Dynamic Lovelace dashboard strategy for Heating Control.

This dashboard strategy generates a responsive Lovelace dashboard that works well
on both large screens (desktop, tablets) and phones. The layout uses sections view
with intelligent column counts based on content.

Key features:
- Quick status header for at-a-glance system state
- Responsive thermostat cards that stack on phones
- Condensed schedule cards with visual status indicators
- Device-to-schedule mapping for easy troubleshooting
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence

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
    SCHEDULE_BINARY_ENTITY_TEMPLATE,
    DEVICE_BINARY_ENTITY_TEMPLATE,
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

        The dashboard is organized for optimal viewing on all screen sizes:
        - Quick Status: At-a-glance system state (presence, active schedules)
        - Climate Controls: Thermostat cards for direct device control
        - Device Status: Which schedule controls each device
        - Schedules: Detailed schedule configuration and state
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

        # Build all card sections
        quick_status_cards = self._build_quick_status_cards(snapshot, tracker_entities)
        device_cards = self._build_device_cards(climate_entities)
        device_status_cards = self._build_device_status_cards(
            snapshot, climate_entities
        )
        schedule_cards = self._build_schedule_cards(entry_id, snapshot)

        sections: List[Dict[str, Any]] = []

        # Section 1: Quick Status - Overview at a glance
        sections.append(
            {
                "type": "grid",
                "columns": 1,
                "square": False,
                "title": "🏠 Quick Status",
                "cards": quick_status_cards,
            }
        )

        # Section 2: Climate Controls - Thermostat cards
        sections.append(
            {
                "type": "grid",
                "columns": 1,
                "square": False,
                "title": "🌡️ Climate Controls",
                "cards": device_cards
                or [
                    {
                        "type": "markdown",
                        "content": "No climate devices are configured for Heating Control.",
                    }
                ],
            }
        )

        # Section 3: Device Status - What schedule controls each device
        if device_status_cards:
            sections.append(
                {
                    "type": "grid",
                    "columns": min(max(len(device_status_cards), 1), 3),
                    "square": False,
                    "title": "📍 Device Status",
                    "cards": device_status_cards,
                }
            )

        # Section 4: Schedules - Detailed schedule information
        if schedule_cards:
            sections.append(
                {
                    "type": "grid",
                    "columns": min(max(len(schedule_cards), 1), 3),
                    "square": False,
                    "title": "📅 Schedules",
                    "cards": schedule_cards,
                }
            )

        return {
            "title": "Smart Heating",
            "views": [
                {
                    "title": "Smart Heating",
                    "path": "smart-heating",
                    "type": "sections",
                    "sections": sections,
                }
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

    def _build_quick_status_cards(
        self, snapshot, tracker_entities: Sequence[str]
    ) -> List[Dict[str, Any]]:
        """Build a quick status overview for at-a-glance system state.

        This section provides immediate visibility into:
        - Presence status (home/away)
        - Active schedule count
        - System diagnostics
        """
        cards: List[Dict[str, Any]] = []

        # Build status summary
        diagnostics = getattr(snapshot, "diagnostics", None) if snapshot else None
        anyone_home = getattr(snapshot, "anyone_home", True) if snapshot else True

        # Presence indicator
        presence_icon = "mdi:home-account" if anyone_home else "mdi:home-outline"
        presence_text = "Someone Home" if anyone_home else "Everyone Away"

        # Schedule summary
        active_schedules = 0
        total_schedules = 0
        active_devices = 0
        if diagnostics:
            active_schedules = getattr(diagnostics, "active_schedules", 0)
            total_schedules = getattr(diagnostics, "schedule_count", 0)
            active_devices = getattr(diagnostics, "active_devices", 0)

        # Build a horizontal-stack for phone-friendly quick glance
        status_cards: List[Dict[str, Any]] = [
            {
                "type": "tile",
                "entity": ENTITY_EVERYONE_AWAY,
                "name": presence_text,
                "icon": presence_icon,
                "color": "green" if anyone_home else "grey",
                "vertical": True,
            },
        ]

        # Active schedules indicator as markdown (tile doesn't support custom text)
        schedule_status = f"**{active_schedules}** of **{total_schedules}**"
        device_status = f"**{active_devices}** device{'s' if active_devices != 1 else ''}"

        status_cards.append(
            {
                "type": "markdown",
                "content": f"### 📅 Schedules\n{schedule_status} active\n\n### 🌡️ Devices\n{device_status} controlled",
            }
        )

        # Refresh button
        status_cards.append(
            {
                "type": "button",
                "entity": ENTITY_DECISION_DIAGNOSTICS,
                "name": "Refresh",
                "icon": "mdi:refresh",
                "show_state": False,
                "tap_action": {
                    "action": "call-service",
                    "service": "homeassistant.update_entity",
                    "data": {
                        "entity_id": ENTITY_DECISION_DIAGNOSTICS,
                    },
                },
            }
        )

        # Wrap in horizontal stack for side-by-side layout
        cards.append(
            {
                "type": "horizontal-stack",
                "cards": status_cards,
            }
        )

        # Presence trackers (collapsible on mobile via entities card)
        if tracker_entities:
            tracker_items = [
                {
                    "entity": tracker_entity,
                    "name": self._friendly_name(tracker_entity),
                }
                for tracker_entity in tracker_entities
            ]
            cards.append(
                {
                    "type": "entities",
                    "title": "Presence Trackers",
                    "entities": tracker_items,
                    "state_color": True,
                }
            )

        return cards

    def _build_device_cards(
        self, climate_entities: Sequence[str]
    ) -> List[Dict[str, Any]]:
        """Create thermostat cards for all climate devices.

        Uses a responsive grid that adapts to screen size:
        - 1 device: single column (full width on phones)
        - 2-3 devices: 2 columns (stacks on phones)
        - 4+ devices: 3 columns max
        """
        cards: List[Dict[str, Any]] = []

        for entity in climate_entities:
            cards.append(
                {
                    "type": "thermostat",
                    "entity": entity,
                    "name": self._friendly_name(entity),
                }
            )

        if cards:
            # Responsive column count: max 3 for large screens
            # Home Assistant sections view auto-stacks on phones
            column_count = min(max(len(cards), 1), 3)
            return [
                {
                    "type": "grid",
                    "columns": column_count,
                    "square": False,
                    "cards": cards,
                }
            ]
        return []

    def _build_device_status_cards(
        self, snapshot, climate_entities: Sequence[str]
    ) -> List[Dict[str, Any]]:
        """Build compact cards showing which schedule controls each device.

        Each card shows:
        - Device name and climate entity control
        - Active schedule (if any)
        - Current mode, target temp, and status with visual indicators
        """
        if not snapshot or not snapshot.device_decisions:
            return []

        device_entity_cards: List[Dict[str, Any]] = []

        for device_entity in climate_entities:
            device_decision = snapshot.device_decisions.get(device_entity)
            device_name = self._friendly_name(device_entity)

            # Build entity list for this device
            entities: List[Dict[str, Any]] = []

            # Add the climate entity itself as a control
            entities.append(
                {
                    "entity": device_entity,
                    "name": device_name,
                }
            )

            if not device_decision:
                # Device has no decision - show as idle
                entities.append(
                    {
                        "type": "text",
                        "name": "Schedule",
                        "text": "⏸️ No active schedule",
                    }
                )
            elif device_decision.active_schedules:
                # Device has an active schedule
                raw_schedule_name = device_decision.active_schedules[0]
                schedule_name = self._schedule_display_name(snapshot, raw_schedule_name)
                hvac_mode = device_decision.hvac_mode or "off"
                target_temp = device_decision.target_temp
                target_fan = device_decision.target_fan
                is_active = device_decision.should_be_active

                # Mode icons for visual scanning
                mode_icons = {
                    "heat": "🔥",
                    "cool": "❄️",
                    "heat_cool": "🔄",
                    "auto": "🔄",
                    "off": "⏹️",
                    "fan_only": "💨",
                    "dry": "💧",
                }
                mode_icon = mode_icons.get(hvac_mode.lower(), "")

                # Status indicator
                status_icon = "✅" if is_active else "⏸️"

                # Combined schedule + status line
                entities.append(
                    {
                        "type": "text",
                        "name": "Schedule",
                        "text": f"{status_icon} {schedule_name}",
                    }
                )

                # Mode and temperature in one line
                temp_str = f" → {target_temp:g}°C" if target_temp is not None else ""
                fan_str = f" • {target_fan}" if target_fan else ""
                entities.append(
                    {
                        "type": "text",
                        "name": "Target",
                        "text": f"{mode_icon} {hvac_mode.title()}{temp_str}{fan_str}",
                    }
                )

                # Current temperature from device
                entities.append(
                    {
                        "type": "attribute",
                        "entity": device_entity,
                        "attribute": "current_temperature",
                        "name": "Current",
                        "suffix": "°C",
                    }
                )
            else:
                # No active schedule
                entities.append(
                    {
                        "type": "text",
                        "name": "Schedule",
                        "text": "⏸️ Idle",
                    }
                )

            # Create a compact entities card for this device
            device_entity_cards.append(
                {
                    "type": "entities",
                    "title": device_name,
                    "entities": entities,
                    "state_color": True,
                }
            )

        return device_entity_cards

    def _build_schedule_cards(
        self, entry_id: str, snapshot
    ) -> List[Dict[str, Any]]:
        """Build compact, phone-friendly cards for each configured schedule.

        Each card shows essential info with visual status indicators:
        - Enable/disable toggle
        - Time window with visual status
        - Mode settings (home/away)
        - Devices being controlled
        """
        if not snapshot or not snapshot.schedule_decisions:
            return []

        # Build map of which devices are actually controlled by each schedule
        schedule_to_controlling_devices: Dict[str, List[str]] = {}
        if snapshot.device_decisions:
            for device_entity, device_decision in snapshot.device_decisions.items():
                if device_decision.active_schedules:
                    for schedule_name in device_decision.active_schedules:
                        schedule_to_controlling_devices.setdefault(
                            schedule_name, []
                        ).append(device_entity)

        cards: List[Dict[str, Any]] = []

        for decision in snapshot.schedule_decisions.values():
            switch_entity = self._schedule_switch_entity(entry_id, decision.schedule_id)

            # Build title with status indicator
            status_icon = self._get_schedule_status_icon(decision)
            display_name = f"{status_icon} {decision.name}"

            # Time window
            if decision.start_time == decision.end_time:
                time_caption = "🕐 All day"
            else:
                window_icon = "🟢" if decision.in_time_window else "⚪"
                time_caption = f"{window_icon} {decision.start_time} → {decision.end_time}"

            # Controlling devices
            controlling_devices = schedule_to_controlling_devices.get(
                decision.name, []
            )
            controlling_count = len(controlling_devices)

            card_entities: List[Dict[str, Any]] = [
                {
                    "entity": switch_entity,
                    "name": "Enabled",
                },
                {
                    "type": "text",
                    "name": "Time",
                    "text": time_caption,
                },
            ]

            # Build compact status line
            status_parts: List[str] = []
            if not decision.enabled:
                status_parts.append("⏹️ Disabled")
            elif decision.is_active and controlling_count > 0:
                status_parts.append("✅ Active")
            elif decision.is_active:
                status_parts.append("🔄 Superseded")
            elif decision.in_time_window:
                status_parts.append("⏳ Window open")
            else:
                status_parts.append("⏸️ Idle")

            # Presence status
            if decision.only_when_home:
                if decision.presence_ok:
                    status_parts.append("🏠 Home ✓")
                elif decision.enabled:
                    status_parts.append("🏠 Waiting")

            card_entities.append(
                {
                    "type": "text",
                    "name": "Status",
                    "text": " • ".join(status_parts),
                }
            )

            # Mode icons for visual scanning
            mode_icons = {
                "heat": "🔥",
                "cool": "❄️",
                "heat_cool": "🔄",
                "auto": "🔄",
                "off": "⏹️",
                "fan_only": "💨",
                "dry": "💧",
            }

            # Combined mode line: Home and Away settings
            mode_parts: List[str] = []
            if decision.hvac_mode_home:
                home_icon = mode_icons.get(decision.hvac_mode_home.lower(), "")
                home_text = f"🏠 {home_icon}{decision.hvac_mode_home.title()}"
                if decision.target_temp_home is not None:
                    home_text += f" {decision.target_temp_home:g}°"
                mode_parts.append(home_text)

            if decision.hvac_mode_away:
                away_icon = mode_icons.get(decision.hvac_mode_away.lower(), "")
                away_text = f"🚪 {away_icon}{decision.hvac_mode_away.title()}"
                if decision.target_temp_away is not None:
                    away_text += f" {decision.target_temp_away:g}°"
                mode_parts.append(away_text)

            if mode_parts:
                card_entities.append(
                    {
                        "type": "text",
                        "name": "Mode",
                        "text": " • ".join(mode_parts),
                    }
                )

            # Fan mode if set
            if decision.target_fan:
                card_entities.append(
                    {
                        "type": "text",
                        "name": "Fan",
                        "text": f"💨 {decision.target_fan}",
                    }
                )

            # Devices: show what's being controlled
            if controlling_count > 0:
                controlling_names = [
                    self._friendly_name(device) for device in controlling_devices
                ]
                if controlling_count <= 2:
                    devices_text = f"✅ {', '.join(controlling_names)}"
                else:
                    devices_text = f"✅ {controlling_count} devices"
            else:
                configured_count = decision.device_count
                if configured_count > 0:
                    devices_text = f"⏸️ {configured_count} device{'s' if configured_count != 1 else ''}"
                else:
                    devices_text = "—"

            card_entities.append(
                {
                    "type": "text",
                    "name": "Devices",
                    "text": devices_text,
                }
            )

            cards.append(
                {
                    "type": "entities",
                    "title": display_name,
                    "entities": card_entities,
                    "state_color": True,
                }
            )

        return cards

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
    def _schedule_binary_entity(entry_id: str, schedule_id: str) -> str:
        """Return the binary sensor entity id for a schedule."""
        return SCHEDULE_BINARY_ENTITY_TEMPLATE.format(
            entry=slugify(entry_id),
            schedule=slugify(schedule_id),
        )

    @staticmethod
    def _schedule_switch_entity(entry_id: str, schedule_id: str) -> str:
        """Return the switch entity id for toggling a schedule."""
        return SCHEDULE_SWITCH_ENTITY_TEMPLATE.format(
            entry=slugify(entry_id),
            schedule=slugify(schedule_id),
        )

    @staticmethod
    def _device_binary_entity(entry_id: str, climate_entity: str) -> str:
        """Return the binary sensor entity id for a managed climate device."""
        suffix = climate_entity.replace("climate.", "").replace(".", "_")
        return DEVICE_BINARY_ENTITY_TEMPLATE.format(
            entry=slugify(entry_id),
            device=slugify(suffix),
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

    @staticmethod
    def _get_config_value(coordinator, key: str) -> Optional[str]:
        """Return a configuration value (options preferred over data)."""
        options = coordinator.config_entry.options
        if key in options:
            return options.get(key)
        return coordinator.config_entry.data.get(key)
