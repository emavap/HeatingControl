"""Dynamic Lovelace dashboard strategy for Heating Control."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from homeassistant.components.lovelace.strategy import Strategy
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .const import (
    CONF_CLIMATE_DEVICES,
    CONF_GAS_HEATER_ENTITY,
    DOMAIN,
)


async def async_get_strategy(hass: HomeAssistant, config: dict[str, Any]) -> Strategy:
    """Return a Heating Control dashboard strategy instance."""
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
        gas_heater = self._get_config_value(coordinator, CONF_GAS_HEATER_ENTITY)
        snapshot = coordinator.data

        device_cards = self._build_device_cards(climate_entities, gas_heater)
        status_cards = self._build_status_cards(snapshot, climate_entities, gas_heater)

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
        self, climate_entities: Sequence[str], gas_heater: Optional[str]
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

        if gas_heater:
            cards.append(
                {
                    "type": "thermostat",
                    "entity": gas_heater,
                    "name": self._friendly_name(gas_heater),
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
        snapshot,
        climate_entities: Sequence[str],
        gas_heater: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Create entities/tile cards summarising integration status."""
        cards: List[Dict[str, Any]] = []

        status_entities = [
            {
                "entity": "sensor.heating_control_decision_diagnostics",
                "name": "Decision diagnostics",
            },
            {
                "entity": "binary_sensor.heating_control_both_away",
                "name": "Both residents away",
            },
        ]

        if gas_heater:
            status_entities.append(
                {
                    "entity": "binary_sensor.heating_gas_heater",
                    "name": "Gas heater requested",
                }
            )

        cards.append(
            {
                "type": "entities",
                "title": "Heating Control Status",
                "entities": status_entities,
            }
        )

        if snapshot:
            schedule_entities = [
                {
                    "entity": self._schedule_binary_entity(decision.name),
                    "name": decision.name,
                }
                for decision in snapshot.schedule_decisions.values()
            ]
            if schedule_entities:
                cards.append(
                    {
                        "type": "entities",
                        "title": "Schedules",
                        "entities": schedule_entities,
                    }
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
                        "entity_id": "sensor.heating_control_decision_diagnostics",
                    },
                },
            }
        )

        return cards

    @staticmethod
    def _schedule_binary_entity(schedule_name: str) -> str:
        """Return the binary sensor entity id for a schedule."""
        return f"binary_sensor.{slugify(f'Heating Schedule {schedule_name}')}"

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
