"""Tests for the Heating Control Lovelace dashboard strategy."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.heating_control.const import (
    CONF_CLIMATE_DEVICES,
    CONF_DEVICE_TRACKERS,
    DOMAIN,
)
from custom_components.heating_control.dashboard import HeatingControlDashboardStrategy
from custom_components.heating_control.models import DiagnosticsSnapshot, HeatingStateSnapshot


class DummyConfigEntry:
    """Minimal config entry stub for dashboard strategy tests."""

    def __init__(
        self,
        entry_id: str,
        *,
        data: dict | None = None,
        options: dict | None = None,
    ) -> None:
        self.entry_id = entry_id
        self.data = data or {}
        self.options = options or {}


class DummyCoordinator:
    """Coordinator stub returning a predefined snapshot."""

    def __init__(self, config_entry: DummyConfigEntry, snapshot: HeatingStateSnapshot) -> None:
        self.config_entry = config_entry
        self.data = snapshot


def _build_snapshot(**diagnostic_kwargs) -> HeatingStateSnapshot:
    """Return a snapshot populated with diagnostics data."""
    diagnostics = DiagnosticsSnapshot(
        now_time="2024-01-01T12:00:00",
        tracker_states={},
        trackers_home=diagnostic_kwargs.get("trackers_home", 0),
        trackers_total=diagnostic_kwargs.get("trackers_total", 0),
        auto_heating_enabled=True,
        schedule_count=diagnostic_kwargs.get("schedule_count", 0),
        active_schedules=diagnostic_kwargs.get("active_schedules", 0),
        active_devices=diagnostic_kwargs.get("active_devices", 0),
    )

    return HeatingStateSnapshot(
        everyone_away=not diagnostic_kwargs.get("anyone_home", True),
        anyone_home=diagnostic_kwargs.get("anyone_home", True),
        schedule_decisions={},
        device_decisions={},
        diagnostics=diagnostics,
    )


@pytest.mark.asyncio
async def test_strategy_renders_single_column_layout() -> None:
    """Dashboard view should render as a single column without diagnostics summary."""
    config_entry = DummyConfigEntry(
        "entry-one",
        options={
            CONF_CLIMATE_DEVICES: ["climate.living_room"],
            CONF_DEVICE_TRACKERS: [],
        },
    )
    coordinator = DummyCoordinator(
        config_entry,
        _build_snapshot(
            schedule_count=2,
            active_schedules=1,
            active_devices=1,
            trackers_home=0,
            trackers_total=0,
        ),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-one": coordinator}})
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-one"})

    result = await strategy.async_generate()

    view = result["views"][0]
    assert view["max_columns"] == 1

    airco_section = view["sections"][0]
    assert airco_section["type"] == "grid"
    assert airco_section["columns"] == 1
    assert airco_section["square"] is False

    thermostat_grid = airco_section["cards"][1]
    assert thermostat_grid["type"] == "grid"
    assert thermostat_grid["columns"] == 1

    diagnostics_section = view["sections"][1]
    heading_card, status_card, *rest = diagnostics_section["cards"]
    assert heading_card["type"] == "heading"
    assert status_card["type"] == "entities"
    assert not any(
        "Schedules:" in card.get("content", "")
        for card in rest
        if card.get("type") == "markdown"
    )
    assert not any(
        "Devices:" in card.get("content", "")
        for card in rest
        if card.get("type") == "markdown"
    )
    assert not any(
        "Presence:" in card.get("content", "")
        for card in rest
        if card.get("type") == "markdown"
    )


@pytest.mark.asyncio
async def test_device_section_uses_multiple_columns_when_multiple_devices() -> None:
    """Device section should use multiple columns when more than one climate device is configured."""
    config_entry = DummyConfigEntry(
        "entry-two",
        options={
            CONF_CLIMATE_DEVICES: [
                "climate.bedroom",
                "climate.office",
                "climate.kitchen",
            ],
            CONF_DEVICE_TRACKERS: ["device_tracker.person_one", "device_tracker.person_two"],
        },
    )
    coordinator = DummyCoordinator(
        config_entry,
        _build_snapshot(
            schedule_count=3,
            active_schedules=2,
            active_devices=2,
            trackers_home=1,
            trackers_total=2,
            anyone_home=True,
        ),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-two": coordinator}})
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-two"})

    result = await strategy.async_generate()

    airco_section = result["views"][0]["sections"][0]
    thermostat_grid = airco_section["cards"][1]
    assert thermostat_grid["type"] == "grid"
    assert thermostat_grid["columns"] > 1

    diagnostics_section = result["views"][0]["sections"][1]
    markdown_contents = [
        card.get("content", "")
        for card in diagnostics_section["cards"]
        if card.get("type") == "markdown"
    ]
    assert not markdown_contents


@pytest.mark.asyncio
async def test_strategy_handles_missing_integration() -> None:
    """When the coordinator is missing, a helpful message should be returned."""
    hass = SimpleNamespace(data={})
    strategy = HeatingControlDashboardStrategy(hass, {})

    result = await strategy.async_generate()

    view = result["views"][0]
    message_card = view["sections"][0]["cards"][0]
    assert message_card["type"] == "markdown"
    assert "integration is not loaded" in message_card["content"]
