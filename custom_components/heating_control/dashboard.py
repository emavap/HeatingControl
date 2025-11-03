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
                "columns": 1,
                "square": False,
                "cards": self._wrap_with_heading(
                    "Aircos & Thermostats",
                    device_cards
                    or [
                        {
                            "type": "markdown",
                            "content": "No climate devices are configured for Heating Control.",
                        }
                    ],
                ),
            }
        )

        sections.append(
            {
                "type": "grid",
                "columns": 1,
                "square": False,
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
                    "max_columns": 1,
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

    def _build_status_cards(
        self,
        entry_id: str,
        snapshot,
        climate_entities: Sequence[str],
        tracker_entities: Sequence[str],
    ) -> List[Dict[str, Any]]:
        """Create entities/tile cards summarising integration status."""
        cards: List[Dict[str, Any]] = []

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
                        schedule_cards,
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
                # Device has no decision
                entities.append(
                    {
                        "type": "attribute",
                        "entity": device_entity,
                        "attribute": "temperature",
                        "name": "Status",
                        "suffix": " - No schedule",
                    }
                )
            elif device_decision.active_schedules:
                # Device has an active schedule
                schedule_name = device_decision.active_schedules[0]
                hvac_mode = device_decision.hvac_mode or "off"
                target_temp = device_decision.target_temp
                target_fan = device_decision.target_fan
                is_active = device_decision.should_be_active

                # Active schedule
                entities.append(
                    {
                        "type": "text",
                        "name": "Active Schedule",
                        "text": schedule_name,
                    }
                )

                # Status
                status_value = "Active" if is_active else "Inactive"
                entities.append(
                    {
                        "type": "text",
                        "name": "Status",
                        "text": status_value,
                    }
                )

                # HVAC Mode
                entities.append(
                    {
                        "type": "text",
                        "name": "Mode",
                        "text": hvac_mode.title(),
                    }
                )

                # Target Temperature
                if target_temp is not None:
                    entities.append(
                        {
                            "type": "text",
                            "name": "Target Temperature",
                            "text": f"{target_temp:g}°C",
                        }
                    )

                # Current Temperature (from climate entity attribute)
                entities.append(
                    {
                        "type": "attribute",
                        "entity": device_entity,
                        "attribute": "current_temperature",
                        "name": "Current Temperature",
                        "suffix": "°C",
                    }
                )

                # Fan Mode
                if target_fan:
                    entities.append(
                        {
                            "type": "text",
                            "name": "Fan Mode",
                            "text": target_fan,
                        }
                    )
            else:
                # No active schedule
                entities.append(
                    {
                        "type": "text",
                        "name": "Status",
                        "text": "No active schedule",
                    }
                )

            # Create an entities card for this device
            device_entity_cards.append(
                {
                    "type": "entities",
                    "title": device_name,
                    "entities": entities,
                }
            )

        return device_entity_cards

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
                        schedule_to_controlling_devices.setdefault(
                            schedule_name, []
                        ).append(device_entity)

        cards: List[Dict[str, Any]] = []

        for decision in snapshot.schedule_decisions.values():
            switch_entity = self._schedule_switch_entity(entry_id, decision.schedule_id)

            display_name = decision.name
            if decision.start_time == decision.end_time:
                time_caption = "All day"
            else:
                time_caption = f"{decision.start_time} → {decision.end_time}"

            # Determine how many devices are actually controlled by this schedule
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
                    "name": "Time Window",
                    "text": time_caption,
                },
            ]

            window_state = "Open" if decision.in_time_window else "Closed"
            card_entities.append(
                {
                    "type": "text",
                    "name": "Window",
                    "text": window_state,
                }
            )

            if not decision.enabled:
                status_text = "Disabled"
            elif decision.is_active and controlling_count > 0:
                status_text = "Active"
            elif decision.is_active:
                status_text = "Active window • superseded"
            elif decision.in_time_window:
                status_text = "Window open"
            else:
                status_text = "Idle"

            if (
                decision.only_when_home
                and not decision.presence_ok
                and decision.enabled
            ):
                status_text += " • waiting for presence"

            card_entities.append(
                {
                    "type": "text",
                    "name": "Status",
                    "text": status_text,
                }
            )

            presence_parts: List[str] = []
            if decision.only_when_home:
                presence_part = "Home required"
                if decision.presence_ok:
                    presence_part += " ✓"
                elif decision.enabled:
                    presence_part += " ✖"
                presence_parts.append(presence_part)

            if decision.schedule_device_trackers:
                tracker_names = [
                    self._friendly_name(tracker)
                    for tracker in decision.schedule_device_trackers
                ]
                if len(tracker_names) <= 2:
                    trackers_text = ", ".join(tracker_names)
                else:
                    trackers_text = f"{len(tracker_names)} trackers"
                presence_parts.append(f"Trackers: {trackers_text}")

            if presence_parts:
                card_entities.append(
                    {
                        "type": "text",
                        "name": "Presence",
                        "text": " • ".join(presence_parts),
                    }
                )

            if decision.hvac_mode_home:
                home_text = decision.hvac_mode_home.title()
                if decision.target_temp_home is not None:
                    home_text += f" {decision.target_temp_home:g}°C"
                card_entities.append(
                    {
                        "type": "text",
                        "name": "Mode (Home)",
                        "text": home_text,
                    }
                )

            if decision.hvac_mode_away:
                away_text = decision.hvac_mode_away.title()
                if decision.target_temp_away is not None:
                    away_text += f" {decision.target_temp_away:g}°C"
                card_entities.append(
                    {
                        "type": "text",
                        "name": "Mode (Away)",
                        "text": away_text,
                    }
                )

            if decision.target_fan:
                card_entities.append(
                    {
                        "type": "text",
                        "name": "Fan Mode",
                        "text": decision.target_fan,
                    }
                )

            if controlling_count > 0:
                controlling_names = [
                    self._friendly_name(device) for device in controlling_devices
                ]
                if controlling_count <= 2:
                    controlling_text = ", ".join(controlling_names)
                else:
                    controlling_text = f"{controlling_count} devices"
            else:
                controlling_text = "None"

            card_entities.append(
                {
                    "type": "text",
                    "name": "Controlling",
                    "text": controlling_text,
                }
            )

            configured_devices = getattr(decision, "devices", []) or []
            if configured_devices:
                configured_names = [
                    self._friendly_name(device) for device in configured_devices
                ]
                if len(configured_names) <= 2:
                    configured_text = ", ".join(configured_names)
                else:
                    configured_text = f"{len(configured_names)} devices"
                card_entities.append(
                    {
                        "type": "text",
                        "name": "Configured",
                        "text": configured_text,
                    }
                )

            detail_label = self._format_schedule_label(decision, controlling_devices)
            if detail_label:
                card_entities.append(
                    {
                        "type": "text",
                        "name": "Details",
                        "text": detail_label,
                    }
                )

            cards.append(
                {
                    "type": "entities",
                    "title": display_name,
                    "entities": card_entities,
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
