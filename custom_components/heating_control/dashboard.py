"""Dynamic Lovelace dashboard strategy for Heating Control."""
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
        """Return the Lovelace dashboard configuration."""
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

        device_cards = self._build_device_cards(climate_entities)
        tracker_entities: Sequence[str] = self._get_config_list(
            coordinator, CONF_DEVICE_TRACKERS
        )

        status_cards = self._build_status_cards(
            entry_id, snapshot, climate_entities, tracker_entities
        )

        sections: List[Dict[str, Any]] = []

        sections.append(
            {
                "type": "grid",
                "cards": self._wrap_with_heading(
                    "Aircos & Thermostats",
                    device_cards
                    or [
                        {
                            "type": "markdown",
                            "content": "No climate devices are configured for Heating Control.",
                            "column_span": 2,
                        }
                    ],
                ),
            }
        )

        sections.append(
            {
                "type": "grid",
                "cards": self._wrap_with_heading(
                    "Smart Heating — Diagnostics",
                    status_cards
                    or [
                        {
                            "type": "markdown",
                            "content": (
                                "Coordinator data not available yet. The view will populate after the "
                                "next update cycle."
                            ),
                        }
                    ],
                ),
            }
        )

        return {
            "title": "Smart Heating",
            "views": [
                {
                    "title": "Smart Heating",
                    "path": "smart-heating",
                    "type": "sections",
                    "max_columns": 2,
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

    @staticmethod
    def _wrap_with_heading(
        heading: str, cards: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Attach a heading card before the provided cards."""
        if not cards:
            return cards

        return [
            {
                "type": "heading",
                "heading": heading,
                "column_span": 2,
            },
            *cards,
        ]

    @staticmethod
    def _friendly_name(entity_id: str) -> str:
        """Guess a human-friendly name from an entity id."""
        return entity_id.split(".", 1)[-1].replace("_", " ").title()

    def _build_device_cards(
        self, climate_entities: Sequence[str]
    ) -> List[Dict[str, Any]]:
        """Create thermostat cards for all climate devices."""
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
            return [
                {
                    "type": "grid",
                    "square": False,
                    "cards": cards,
                    "column_span": 2,
                }
            ]
        return []

    def _build_status_cards(
        self,
        entry_id: str,
        snapshot,
        climate_entities: Sequence[str],
        tracker_entities: Sequence[str],
    ) -> List[Dict[str, Any]]:
        """Create entities/tile cards summarising integration status."""
        cards: List[Dict[str, Any]] = []

        # Add overview cards if snapshot is available
        if snapshot and snapshot.diagnostics:
            diagnostics = snapshot.diagnostics
            overview_cards = []

            # Active schedules card
            schedules_label = (
                f"{diagnostics.active_schedules}/{diagnostics.schedule_count} active"
            )
            overview_cards.append(
                {
                    "type": "button",
                    "entity": ENTITY_DECISION_DIAGNOSTICS,
                    "name": "Active Schedules",
                    "icon": "mdi:calendar-clock",
                    "icon_color": (
                        "green" if diagnostics.active_schedules > 0 else "grey"
                    ),
                    "show_state": False,
                    "layout": "vertical",
                    "label": schedules_label,
                }
            )

            # Active devices card
            devices_label = (
                f"{diagnostics.active_devices}/{len(climate_entities)} running"
            )
            overview_cards.append(
                {
                    "type": "button",
                    "entity": ENTITY_DECISION_DIAGNOSTICS,
                    "name": "Active Devices",
                    "icon": "mdi:radiator",
                    "icon_color": (
                        "orange" if diagnostics.active_devices > 0 else "grey"
                    ),
                    "show_state": False,
                    "layout": "vertical",
                    "label": devices_label,
                }
            )

            # Presence status card
            presence_icon = "mdi:home-account" if snapshot.anyone_home else "mdi:home-export-outline"
            presence_color = "blue" if snapshot.anyone_home else "grey"
            presence_text = f"{diagnostics.trackers_home} / {diagnostics.trackers_total} home"
            overview_cards.append(
                {
                    "type": "button",
                    "entity": ENTITY_EVERYONE_AWAY,
                    "name": "Presence",
                    "icon": presence_icon,
                    "icon_color": presence_color,
                    "show_state": False,
                    "layout": "vertical",
                    "label": presence_text,
                }
            )

            cards.append(
                {
                    "type": "grid",
                    "columns": 3,
                    "square": False,
                    "cards": overview_cards,
                }
            )

        status_entities = [
            {
                "entity": ENTITY_DECISION_DIAGNOSTICS,
                "name": "Decision diagnostics",
            },
            {
                "entity": ENTITY_EVERYONE_AWAY,
                "name": "Everyone away",
            },
        ]

        cards.append(
            {
                "type": "entities",
                "title": "Heating Control Status",
                "entities": status_entities,
            }
        )

        if snapshot:
            schedule_cards = self._build_schedule_cards(entry_id, snapshot)
            if schedule_cards:
                cards.extend(
                    self._wrap_with_heading(
                        "Schedules",
                        [
                            {
                                "type": "grid",
                                "columns": 2,
                                "square": False,
                                "cards": schedule_cards,
                            }
                        ],
                    )
                )

            # Create device status cards showing which schedule controls each device
            device_status_cards = self._build_device_status_cards(
                snapshot, climate_entities
            )
            if device_status_cards:
                cards.extend(
                    self._wrap_with_heading(
                        "Device → Schedule Mapping",
                        device_status_cards,
                    )
                )

        if tracker_entities:
            cards.append(
                {
                    "type": "entities",
                    "title": "Presence trackers",
                    "entities": [
                        {
                            "entity": tracker_entity,
                            "name": self._friendly_name(tracker_entity),
                        }
                        for tracker_entity in tracker_entities
                    ],
                }
            )

        cards.append(
            {
                "type": "button",
                "name": "Refresh decisions",
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

        return cards

    def _build_device_status_cards(
        self, snapshot, climate_entities: Sequence[str]
    ) -> List[Dict[str, Any]]:
        """Build cards showing which schedule controls each device."""
        if not snapshot or not snapshot.device_decisions:
            return []

        device_cards: List[Dict[str, Any]] = []

        for device_entity in climate_entities:
            device_decision = snapshot.device_decisions.get(device_entity)
            device_name = self._friendly_name(device_entity)

            if not device_decision:
                # Device has no decision (shouldn't happen but handle gracefully)
                device_cards.append(
                    {
                        "type": "button",
                        "entity": device_entity,
                        "name": device_name,
                        "icon": "mdi:air-conditioner",
                        "icon_color": "grey",
                        "show_state": False,
                        "layout": "vertical",
                        "label": "No schedule",
                        "tap_action": {"action": "more-info"},
                    }
                )
                continue

            # Get the active schedule name
            if device_decision.active_schedules:
                schedule_name = device_decision.active_schedules[0]
                is_active = device_decision.should_be_active
                hvac_mode = device_decision.hvac_mode or "off"
                target_temp = device_decision.target_temp
                target_fan = device_decision.target_fan

                # Build status content
                status_parts = [f"Mode: {hvac_mode.title()}"]
                if target_temp is not None:
                    status_parts.append(f"{target_temp:g}°")
                if target_fan:
                    status_parts.append(f"Fan: {target_fan}")

                status_text = " • ".join(status_parts)
                label_lines = [f"Schedule: {schedule_name}"]

                # Color based on activity
                if is_active:
                    if hvac_mode in ["heat", "auto"]:
                        icon_color = "red"
                        icon = "mdi:fire"
                    elif hvac_mode in ["cool", "heat_cool"]:
                        icon_color = "blue"
                        icon = "mdi:snowflake"
                    else:
                        icon_color = "green"
                        icon = "mdi:fan"
                    label_lines.append(status_text)
                else:
                    icon_color = "grey"
                    icon = "mdi:power-off"
                    label_lines.append("Off")

                device_cards.append(
                    {
                        "type": "button",
                        "entity": device_entity,
                        "name": device_name,
                        "icon": icon,
                        "icon_color": icon_color,
                        "show_state": False,
                        "layout": "vertical",
                        "label": "\n".join(label_lines),
                        "tap_action": {"action": "more-info"},
                    }
                )
            else:
                # No active schedule
                device_cards.append(
                    {
                        "type": "button",
                        "entity": device_entity,
                        "name": device_name,
                        "icon": "mdi:air-conditioner",
                        "icon_color": "grey",
                        "show_state": False,
                        "layout": "vertical",
                        "label": "No active schedule",
                        "tap_action": {"action": "more-info"},
                    }
                )

        if device_cards:
            return [
                {
                    "type": "grid",
                    "columns": 2,
                    "square": False,
                    "cards": device_cards,
                }
            ]

        return []

    def _build_schedule_cards(
        self, entry_id: str, snapshot
    ) -> List[Dict[str, Any]]:
        """Build interactive cards for each configured schedule."""
        if not snapshot or not snapshot.schedule_decisions:
            return []

        # Build map of which devices are actually controlled by each schedule
        schedule_to_controlling_devices: Dict[str, List[str]] = {}
        if snapshot.device_decisions:
            for device_entity, device_decision in snapshot.device_decisions.items():
                if device_decision.active_schedules:
                    # active_schedules is a tuple, usually with one schedule name
                    for schedule_name in device_decision.active_schedules:
                        schedule_to_controlling_devices.setdefault(schedule_name, []).append(device_entity)

        cards: List[Dict[str, Any]] = []

        for decision in snapshot.schedule_decisions.values():
            switch_entity = self._schedule_switch_entity(entry_id, decision.schedule_id)

            display_name = decision.name
            if decision.start_time == decision.end_time:
                time_caption = "All day"
            else:
                time_caption = f"{decision.start_time} → {decision.end_time}"

            # Determine how many devices are actually controlled by this schedule
            controlling_devices = schedule_to_controlling_devices.get(decision.name, [])
            controlling_count = len(controlling_devices)

            detail_label = self._format_schedule_label(decision, controlling_devices)
            label = time_caption
            if detail_label:
                label = f"{time_caption} • {detail_label}"

            # Badge logic: Active means in time window, but also show if controlling devices
            if decision.is_active and controlling_count > 0:
                # Active and controlling devices
                icon = "mdi:calendar-star"
                icon_color = "green"
                badge = f"Active ({controlling_count})"
                badge_icon = "mdi:fire"
                badge_color = "green"
            elif decision.is_active and controlling_count == 0:
                # Active but not controlling any devices (superseded by later schedules)
                icon = "mdi:calendar-alert"
                icon_color = "orange"
                badge = "Superseded"
                badge_icon = "mdi:alert-circle-outline"
                badge_color = "orange"
            elif not decision.enabled:
                icon = "mdi:calendar-remove"
                icon_color = "grey"
                badge = "Disabled"
                badge_icon = "mdi:cancel"
                badge_color = "grey"
            else:
                icon = "mdi:calendar-clock"
                icon_color = "var(--primary-color)"
                badge = "Idle"
                badge_icon = "mdi:clock-outline"
                badge_color = "var(--primary-color)"

            cards.append(
                {
                    "type": "button",
                    "entity": switch_entity,
                    "name": display_name,
                    "icon": icon,
                    "icon_color": icon_color,
                    "badge": badge,
                    "badge_icon": badge_icon,
                    "badge_color": badge_color,
                    "show_state": False,
                    "label": label,
                    "tap_action": {
                        "action": "call-service",
                        "service": "heating_control.set_schedule_enabled",
                        "data": {
                            "entry_id": entry_id,
                            "schedule_id": decision.schedule_id,
                            "schedule_enabled": not decision.enabled,
                        },
                    },
                    "hold_action": {
                        "action": "more-info",
                        "entity": self._schedule_binary_entity(
                            entry_id, decision.schedule_id
                        ),
                    },
                }
            )

        return cards

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

    def _format_schedule_label(self, decision, controlling_devices: List[str]) -> str:
        """Return a descriptive label for a schedule card."""
        lines: List[str] = []

        # Line 1: Time window and presence status
        line1_parts: List[str] = []
        window_status = "Window open" if decision.in_time_window else "Window closed"
        line1_parts.append(window_status)

        if decision.only_when_home:
            presence_status = "Home required"
            if not decision.presence_ok and decision.enabled:
                presence_status += " ❌"
            else:
                presence_status += " ✓"
            line1_parts.append(presence_status)

        if decision.schedule_device_trackers:
            tracker_count = len(decision.schedule_device_trackers)
            line1_parts.append(f"{tracker_count} tracker{'s' if tracker_count > 1 else ''}")

        if line1_parts:
            lines.append(" • ".join(line1_parts))

        # Line 2: HVAC modes and temperatures
        line2_parts: List[str] = []
        hvac_info = f"🏠 {decision.hvac_mode_home.title()}"
        if decision.target_temp_home is not None:
            hvac_info += f" {decision.target_temp_home}°"
        line2_parts.append(hvac_info)

        if decision.hvac_mode_away:
            away_info = f"🚪 {decision.hvac_mode_away.title()}"
            if decision.target_temp_away is not None:
                away_info += f" {decision.target_temp_away}°"
            line2_parts.append(away_info)

        if line2_parts:
            lines.append(" • ".join(line2_parts))

        # Line 3: Fan mode and device status
        line3_parts: List[str] = []
        if decision.target_fan:
            line3_parts.append(f"Fan: {decision.target_fan}")

        # Show controlling vs configured devices
        controlling_count = len(controlling_devices)
        configured_count = decision.device_count

        if controlling_count > 0:
            # Show which devices are being controlled
            controlling_names = [self._friendly_name(dev) for dev in controlling_devices]
            if len(controlling_names) <= 2:
                line3_parts.append(f"Controlling: {', '.join(controlling_names)}")
            else:
                line3_parts.append(f"Controlling {controlling_count} devices")
        elif configured_count > 0 and decision.is_active:
            # Configured for devices but not controlling them (superseded)
            configured_names = [self._friendly_name(dev) for dev in decision.devices]
            if len(configured_names) <= 2:
                line3_parts.append(f"Configured: {', '.join(configured_names)} (superseded)")
            else:
                line3_parts.append(f"Configured for {configured_count} devices (superseded)")
        elif configured_count > 0:
            # Not active, just show configured devices
            configured_names = [self._friendly_name(dev) for dev in decision.devices]
            if len(configured_names) <= 2:
                line3_parts.append(f"Configured: {', '.join(configured_names)}")
            else:
                line3_parts.append(f"{configured_count} devices")

        if line3_parts:
            lines.append(" • ".join(line3_parts))

        return "\n".join(lines)

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
        data = coordinator.config_entry.data
        return options.get(key) or data.get(key, [])

    @staticmethod
    def _get_config_value(coordinator, key: str) -> Optional[str]:
        """Return a configuration value (options preferred over data)."""
        options = coordinator.config_entry.options
        if key in options:
            return options.get(key)
        return coordinator.config_entry.data.get(key)
