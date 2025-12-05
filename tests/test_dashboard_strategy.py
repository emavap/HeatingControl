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
from custom_components.heating_control.models import (
    DiagnosticsSnapshot,
    DeviceDecision,
    HeatingStateSnapshot,
    ScheduleDecision,
)


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


FRONTEND_RESOURCE_KEY = "frontend_extra_module_url"
APEX_RESOURCE_URL = "/hacsfiles/apexcharts-card/apexcharts-card.js"


def _state(state: str, *, current: float | None = None, target: float | None = None):
    """Return a mock Home Assistant state for a climate entity."""
    attributes = {}
    if current is not None:
        attributes["current_temperature"] = current
    if target is not None:
        attributes["temperature"] = target
    return SimpleNamespace(state=state, attributes=attributes)


def _build_hass(
    coordinator_map: dict[str, DummyCoordinator],
    *,
    states: dict[str, SimpleNamespace] | None = None,
    include_apex: bool = True,
):
    """Construct a minimal hass namespace for strategy tests."""
    hass_data: dict[str, object] = {DOMAIN: coordinator_map}
    if include_apex:
        hass_data[FRONTEND_RESOURCE_KEY] = {APEX_RESOURCE_URL}

    state_map = states or {}
    return SimpleNamespace(
        data=hass_data,
        states=SimpleNamespace(get=lambda entity_id: state_map.get(entity_id)),
    )
@pytest.mark.asyncio
async def test_strategy_uses_panel_view_with_vertical_stack() -> None:
    """Dashboard view should use panel mode with vertical-stack layout."""
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
    state_map = {
        "climate.living_room": _state("heat", current=21.5, target=22.0),
    }
    hass = _build_hass({"entry-one": coordinator}, states=state_map)
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-one"})

    result = await strategy.async_generate()

    view = result["views"][0]
    # Panel view with vertical-stack
    assert view.get("panel") is True
    assert "cards" in view
    assert len(view["cards"]) == 1
    assert view["cards"][0]["type"] == "vertical-stack"

    # Get all cards from the vertical-stack
    cards = view["cards"][0]["cards"]
    # Should have: header, status grid, climate grid, device status, schedules
    assert len(cards) >= 3  # At minimum: header, status, climate


@pytest.mark.asyncio
async def test_climate_grid_uses_multiple_columns_when_multiple_devices() -> None:
    """Climate grid should use multiple columns when more than one climate device is configured."""
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
    state_map = {
        "climate.bedroom": _state("heat", current=19.0, target=20.0),
        "climate.office": _state("cool", current=23.0, target=21.0),
        "climate.kitchen": _state("auto", current=21.5, target=22.0),
    }
    hass = _build_hass({"entry-two": coordinator}, states=state_map)
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-two"})

    result = await strategy.async_generate()

    view = result["views"][0]
    assert view.get("panel") is True
    cards = view["cards"][0]["cards"]

    # Find the climate controls section (vertical-stack with markdown header)
    climate_section = None
    for card in cards:
        if card.get("type") == "vertical-stack":
            inner_cards = card.get("cards", [])
            if inner_cards and inner_cards[0].get("type") == "markdown":
                content = inner_cards[0].get("content", "")
                if "Climate Controls" in content:
                    climate_section = card
                    break

    assert climate_section is not None
    # Second card in the section should be the grid
    thermostat_grid = climate_section["cards"][1]
    assert thermostat_grid["type"] == "grid"
    assert thermostat_grid["columns"] > 1  # Multiple devices = multiple columns


@pytest.mark.asyncio
async def test_device_cards_precede_schedule_cards_in_diagnostics_section() -> None:
    """Device diagnostic cards should appear before schedule cards."""
    schedule_decision = ScheduleDecision(
        schedule_id="weekday",
        name="Weekday AM",
        start_time="06:00",
        end_time="08:00",
        hvac_mode="heat",
        hvac_mode_home="heat",
        hvac_mode_away="off",
        only_when_home=False,
        enabled=True,
        is_active=True,
        in_time_window=True,
        presence_ok=True,
        device_count=1,
        devices=("climate.living_room",),
        schedule_device_trackers=(),
        target_temp=21.0,
        target_temp_home=21.0,
        target_temp_away=18.0,
        target_fan=None,
    )

    device_decision = DeviceDecision(
        entity_id="climate.living_room",
        should_be_active=True,
        active_schedules=("Weekday AM",),
        hvac_mode="heat",
        target_temp=21.0,
        target_fan=None,
    )

    diagnostics = DiagnosticsSnapshot(
        now_time="2024-01-01T06:30:00",
        tracker_states={},
        trackers_home=1,
        trackers_total=1,
        auto_heating_enabled=True,
        schedule_count=1,
        active_schedules=1,
        active_devices=1,
    )

    snapshot = HeatingStateSnapshot(
        everyone_away=False,
        anyone_home=True,
        schedule_decisions={"weekday": schedule_decision},
        device_decisions={"climate.living_room": device_decision},
        diagnostics=diagnostics,
    )

    config_entry = DummyConfigEntry(
        "entry-three",
        options={
            CONF_CLIMATE_DEVICES: ["climate.living_room"],
            CONF_DEVICE_TRACKERS: [],
        },
    )
    coordinator = DummyCoordinator(config_entry, snapshot)
    state_map = {
        "climate.living_room": _state("heat", current=21.5, target=22.0),
    }
    hass = _build_hass({"entry-three": coordinator}, states=state_map)
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-three"})

    result = await strategy.async_generate()

    view = result["views"][0]
    assert view.get("panel") is True
    cards = view["cards"][0]["cards"]

    # Find device status and schedule sections by their markdown headers
    device_index = None
    schedule_index = None
    for i, card in enumerate(cards):
        if card.get("type") == "vertical-stack":
            inner_cards = card.get("cards", [])
            if inner_cards and inner_cards[0].get("type") == "markdown":
                content = inner_cards[0].get("content", "")
                if "Device Status" in content:
                    device_index = i
                elif "Schedules" in content:
                    schedule_index = i

    assert device_index is not None, "Device Status section not found"
    assert schedule_index is not None, "Schedules section not found"
    assert device_index < schedule_index


@pytest.mark.asyncio
async def test_strategy_handles_missing_integration() -> None:
    """When the coordinator is missing, a helpful message should be returned."""
    hass = SimpleNamespace(
        data={},
        states=SimpleNamespace(get=lambda entity_id: None),
    )
    strategy = HeatingControlDashboardStrategy(hass, {})

    result = await strategy.async_generate()

    view = result["views"][0]
    # The _build_message method still uses sections for error messages
    message_card = view["sections"][0]["cards"][0]
    assert message_card["type"] == "markdown"
    assert "integration is not loaded" in message_card["content"]


@pytest.mark.asyncio
async def test_empty_option_lists_override_data() -> None:
    """Options with empty lists should override config entry data."""
    config_entry = DummyConfigEntry(
        "entry-clean",
        data={
            CONF_CLIMATE_DEVICES: ["climate.living_room"],
            CONF_DEVICE_TRACKERS: ["device_tracker.person"],
        },
        options={
            CONF_CLIMATE_DEVICES: [],
            CONF_DEVICE_TRACKERS: [],
        },
    )
    coordinator = DummyCoordinator(config_entry, _build_snapshot())
    hass = _build_hass({"entry-clean": coordinator})
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-clean"})

    result = await strategy.async_generate()

    view = result["views"][0]
    # Panel view with vertical-stack
    assert view.get("panel") is True
    cards = view["cards"][0]["cards"]

    # Should have at least header and status grid
    assert len(cards) >= 2

    # First card is header markdown
    assert cards[0]["type"] == "markdown"
    assert "Smart Heating" in cards[0]["content"]

    # Second card is status grid (no climate section when no devices)
    assert cards[1]["type"] in ("grid", "vertical-stack")
