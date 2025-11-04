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
async def test_strategy_does_not_force_single_column_layout() -> None:
    """Dashboard view should not be forced into a single column when rendered."""
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
    assert "max_columns" not in view

    history_section = view["sections"][0]
    assert history_section["title"] == "Temperature History (48h)"
    assert history_section["columns"] == 1
    assert history_section.get("column_span") == 3
    history_card = history_section["cards"][0]
    assert history_card["type"] == "custom:apexcharts-card"
    assert history_card["graph_span"] == "48h"
    assert history_card["update_interval"] == "5min"
    assert history_card["header"]["show"] is False
    history_series = history_card["series"]
    assert len(history_series) == 2
    assert history_series[0]["entity"] == "climate.living_room"
    assert history_series[0]["attribute"] == "current_temperature"
    assert "Actual" in history_series[0]["name"]
    assert history_series[1]["entity"] == "climate.living_room"
    assert history_series[1]["attribute"] == "temperature"
    assert "Target" in history_series[1]["name"]

    airco_section = view["sections"][1]
    assert airco_section["type"] == "grid"
    assert airco_section["columns"] == 1
    assert airco_section["title"] == "Aircos & Thermostats"
    thermostat_grid = airco_section["cards"][0]
    assert thermostat_grid["type"] == "grid"
    assert thermostat_grid["columns"] == 1

    diagnostics_section = view["sections"][2]
    assert diagnostics_section["title"] == "Smart Heating — Diagnostics"
    cards = diagnostics_section["cards"]
    assert cards[0]["type"] == "entities"
    assert any(card["type"] == "button" for card in cards)


@pytest.mark.asyncio
async def test_temperature_history_renders_without_apex_metadata() -> None:
    """Graph card should render even when ApexCharts resources are not detected."""
    config_entry = DummyConfigEntry(
        "entry-one",
        options={
            CONF_CLIMATE_DEVICES: ["climate.living_room"],
            CONF_DEVICE_TRACKERS: [],
        },
    )
    coordinator = DummyCoordinator(config_entry, _build_snapshot())
    state_map = {
        "climate.living_room": _state("heat", current=21.0, target=22.0),
    }
    hass = _build_hass({"entry-one": coordinator}, states=state_map, include_apex=False)
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-one"})

    result = await strategy.async_generate()

    history_section = result["views"][0]["sections"][0]
    assert history_section["title"] == "Temperature History (48h)"
    chart_card = history_section["cards"][0]
    assert chart_card["type"] == "custom:apexcharts-card"


@pytest.mark.asyncio
async def test_temperature_history_waits_for_device_attributes() -> None:
    """A message should be shown until climate attributes are available."""
    config_entry = DummyConfigEntry(
        "entry-attr",
        options={
            CONF_CLIMATE_DEVICES: ["climate.living_room"],
            CONF_DEVICE_TRACKERS: [],
        },
    )
    coordinator = DummyCoordinator(config_entry, _build_snapshot())
    state_map = {
        "climate.living_room": _state("heat"),
    }
    hass = _build_hass({"entry-attr": coordinator}, states=state_map)
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-attr"})

    result = await strategy.async_generate()

    history_section = result["views"][0]["sections"][0]
    message_card = history_section["cards"][0]
    assert message_card["type"] == "markdown"
    assert "Temperature history will appear" in message_card["content"]


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
    state_map = {
        "climate.bedroom": _state("heat", current=19.0, target=20.0),
        "climate.office": _state("cool", current=23.0, target=21.0),
        "climate.kitchen": _state("auto", current=21.5, target=22.0),
    }
    hass = _build_hass({"entry-two": coordinator}, states=state_map)
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-two"})

    result = await strategy.async_generate()

    history_section = result["views"][0]["sections"][0]
    history_card = history_section["cards"][0]
    assert history_card["type"] == "custom:apexcharts-card"
    series = history_card["series"]
    assert len(series) == 6  # 3 devices * (actual + target)
    expected_pairs = [
        ("climate.bedroom", "current_temperature"),
        ("climate.bedroom", "temperature"),
        ("climate.office", "current_temperature"),
        ("climate.office", "temperature"),
        ("climate.kitchen", "current_temperature"),
        ("climate.kitchen", "temperature"),
    ]
    assert [(entry["entity"], entry["attribute"]) for entry in series] == expected_pairs

    # First section is temperature history, second is airco
    airco_section = result["views"][0]["sections"][1]
    thermostat_grid = airco_section["cards"][0]
    assert thermostat_grid["type"] == "grid"
    assert thermostat_grid["columns"] > 1

    diagnostics_section = result["views"][0]["sections"][2]
    markdown_contents = [
        card.get("content", "")
        for card in diagnostics_section["cards"]
        if card.get("type") == "markdown"
    ]
    assert not markdown_contents


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

    section_titles = [
        section.get("title") for section in result["views"][0]["sections"]
    ]
    device_index = section_titles.index("Device → Schedule Mapping")
    schedule_index = section_titles.index("Schedules")

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
    sections = view["sections"]
    assert len(sections) == 2

    airco_section = sections[0]
    assert airco_section["title"] == "Aircos & Thermostats"
    message_card = airco_section["cards"][0]
    assert message_card["type"] == "markdown"
    assert "No climate devices" in message_card["content"]

    diagnostics_cards = sections[1]["cards"]
    assert not any(
        isinstance(card, dict) and card.get("title") == "Presence trackers"
        for card in diagnostics_cards
    )


@pytest.mark.asyncio
async def test_temperature_history_card_appears_first() -> None:
    """Temperature history graph should be the first section when devices are configured."""
    config_entry = DummyConfigEntry(
        "entry-four",
        options={
            CONF_CLIMATE_DEVICES: ["climate.bedroom", "climate.living_room"],
            CONF_DEVICE_TRACKERS: [],
        },
    )
    coordinator = DummyCoordinator(config_entry, _build_snapshot())

    state_map = {
        "climate.bedroom": _state("heat", current=18.5, target=20.0),
        "climate.living_room": _state("cool", current=23.0, target=21.0),
    }
    hass = _build_hass({"entry-four": coordinator}, states=state_map)
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-four"})

    result = await strategy.async_generate()

    view = result["views"][0]
    sections = view["sections"]

    # First section should be temperature history
    history_section = sections[0]
    assert history_section["type"] == "grid"
    assert history_section["title"] == "Temperature History (48h)"

    history_card = history_section["cards"][0]
    assert history_card["type"] == "custom:apexcharts-card"
    assert history_card["graph_span"] == "48h"
    assert history_card["update_interval"] == "5min"

    # Verify series include both actual and target temperatures for each device
    series = history_card["series"]
    assert len(series) == 4  # 2 devices * 2 series each
    expected_pairs = [
        ("climate.bedroom", "current_temperature"),
        ("climate.bedroom", "temperature"),
        ("climate.living_room", "current_temperature"),
        ("climate.living_room", "temperature"),
    ]
    assert [(entry["entity"], entry["attribute"]) for entry in series] == expected_pairs
    names = [entry["name"] for entry in series]
    assert all("Actual" in name or "Target" in name for name in names)


@pytest.mark.asyncio
async def test_temperature_history_card_not_shown_when_no_devices() -> None:
    """Temperature history graph should not appear when no climate devices are configured."""
    config_entry = DummyConfigEntry(
        "entry-five",
        options={
            CONF_CLIMATE_DEVICES: [],
            CONF_DEVICE_TRACKERS: [],
        },
    )
    coordinator = DummyCoordinator(config_entry, _build_snapshot())
    hass = _build_hass({"entry-five": coordinator})
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-five"})

    result = await strategy.async_generate()

    view = result["views"][0]
    sections = view["sections"]

    # First section should be "Aircos & Thermostats" since there's no history card
    first_section = sections[0]
    assert first_section["title"] == "Aircos & Thermostats"
    fallback_card = first_section["cards"][0]
    assert fallback_card["type"] == "markdown"


@pytest.mark.asyncio
async def test_temperature_history_excludes_target_when_hvac_off() -> None:
    """Target temperature should only appear for devices in heat/cool mode."""
    config_entry = DummyConfigEntry(
        "entry-six",
        options={
            CONF_CLIMATE_DEVICES: [
                "climate.bedroom",  # heat mode - should show target
                "climate.living_room",  # off mode - should NOT show target
                "climate.kitchen",  # auto mode - should show target
            ],
            CONF_DEVICE_TRACKERS: [],
        },
    )
    coordinator = DummyCoordinator(config_entry, _build_snapshot())

    state_map = {
        "climate.bedroom": _state("heat", current=18.0, target=20.0),
        "climate.living_room": _state("off", current=19.5),
        "climate.kitchen": _state("auto", current=20.5, target=21.0),
    }
    hass = _build_hass({"entry-six": coordinator}, states=state_map)
    strategy = HeatingControlDashboardStrategy(hass, {"entry_id": "entry-six"})

    result = await strategy.async_generate()

    view = result["views"][0]
    history_section = view["sections"][0]
    history_card = history_section["cards"][0]
    assert history_card["type"] == "custom:apexcharts-card"

    series = history_card["series"]
    expected_pairs = [
        ("climate.bedroom", "current_temperature"),
        ("climate.bedroom", "temperature"),
        ("climate.living_room", "current_temperature"),
        ("climate.kitchen", "current_temperature"),
        ("climate.kitchen", "temperature"),
    ]

    # Should have 3 actual temp series + 2 target temp series (bedroom and kitchen only)
    assert len(series) == 5
    assert sorted((entry["entity"], entry["attribute"]) for entry in series) == sorted(
        expected_pairs
    )

    # Check bedroom: should have both actual and target
    bedroom_series = [entry for entry in series if "bedroom" in entry["name"].lower()]
    assert len(bedroom_series) == 2
    assert any("Actual" in entry["name"] for entry in bedroom_series)
    assert any("Target" in entry["name"] for entry in bedroom_series)

    # Check living_room: should have only actual (no target because it's off)
    living_room_series = [
        entry for entry in series if "living room" in entry["name"].lower()
    ]
    assert len(living_room_series) == 1
    assert "Actual" in living_room_series[0]["name"]

    # Check kitchen: should have both actual and target (auto mode)
    kitchen_series = [entry for entry in series if "kitchen" in entry["name"].lower()]
    assert len(kitchen_series) == 2
    assert any("Actual" in entry["name"] for entry in kitchen_series)
    assert any("Target" in entry["name"] for entry in kitchen_series)
