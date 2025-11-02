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

            device_entities = [
                {
                    "entity": self._device_binary_entity(device_entity),
                    "name": self._friendly_name(device_entity),
                }
                for device_entity in climate_entities
            ]
            if device_entities:
                cards.append(
                    {
                        "type": "entities",
                        "title": "Device activity",
                        "entities": device_entities,
                    }
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

    def _build_schedule_cards(
        self, entry_id: str, snapshot
    ) -> List[Dict[str, Any]]:
        """Build interactive cards for each configured schedule."""
        if not snapshot or not snapshot.schedule_decisions:
            return []

        cards: List[Dict[str, Any]] = []

        for decision in snapshot.schedule_decisions.values():
            switch_entity = self._schedule_switch_entity(entry_id, decision.schedule_id)

            display_name = decision.name
            if decision.start_time == decision.end_time:
                time_caption = "All day"
            else:
                time_caption = f"{decision.start_time} → {decision.end_time}"

            detail_label = self._format_schedule_label(decision)
            label = time_caption
            if detail_label:
                label = f"{time_caption} • {detail_label}"

            if decision.is_active:
                icon = "mdi:calendar-star"
                icon_color = "green"
                badge = "Active"
                badge_icon = "mdi:fire"
                badge_color = "green"
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
                        "entity": self._schedule_binary_entity(decision.name),
                    },
                }
            )

        return cards

    @staticmethod
    def _schedule_binary_entity(schedule_name: str) -> str:
        """Return the binary sensor entity id for a schedule."""
        return f"binary_sensor.{slugify(f'Heating Schedule {schedule_name}')}"

    @staticmethod
    def _schedule_switch_entity(entry_id: str, schedule_id: str) -> str:
        """Return the switch entity id for toggling a schedule."""
        return SCHEDULE_SWITCH_ENTITY_TEMPLATE.format(
            entry=slugify(entry_id),
            schedule=slugify(schedule_id),
        )

    @staticmethod
    def _format_schedule_label(decision) -> str:
        """Return a descriptive label for a schedule card."""
        parts: List[str] = []

        window_status = "Window open" if decision.in_time_window else "Window closed"
        parts.append(window_status)

        if decision.only_when_home:
            parts.append("Home required")

        if decision.device_count:
            device_suffix = "device" if decision.device_count == 1 else "devices"
            parts.append(f"{decision.device_count} {device_suffix}")

        return " • ".join(parts)

    @staticmethod
    def _device_binary_entity(climate_entity: str) -> str:
        """Return the binary sensor entity id for a managed climate device."""
        suffix = climate_entity.replace("climate.", "").replace(".", "_")
        friendly = suffix.replace("_", " ")
        return f"binary_sensor.{slugify(f'Heating {friendly}')}"

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
