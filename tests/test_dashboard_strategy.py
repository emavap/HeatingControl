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

    # First section is now Quick Status
    quick_status_section = view["sections"][0]
    assert quick_status_section["type"] == "grid"
    assert quick_status_section["columns"] == 1
    assert quick_status_section["title"] == "🏠 Quick Status"

    # Second section is Climate Controls
    climate_section = view["sections"][1]
    assert climate_section["title"] == "🌡️ Climate Controls"
    thermostat_grid = climate_section["cards"][0]
    assert thermostat_grid["type"] == "grid"
    assert thermostat_grid["columns"] == 1


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

    # First section is Quick Status with horizontal-stack for responsive layout
    quick_status_section = result["views"][0]["sections"][0]
    assert quick_status_section["title"] == "🏠 Quick Status"
    # Quick status uses horizontal-stack for its cards
    status_stack = quick_status_section["cards"][0]
    assert status_stack["type"] == "horizontal-stack"

    # Second section is Climate Controls with thermostat grid
    climate_section = result["views"][0]["sections"][1]
    assert climate_section["title"] == "🌡️ Climate Controls"
    thermostat_grid = climate_section["cards"][0]
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

    section_titles = [
        section.get("title") for section in result["views"][0]["sections"]
    ]
    # New section titles use emojis
    device_index = section_titles.index("📍 Device Status")
    schedule_index = section_titles.index("📅 Schedules")

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
    # Now we have Quick Status + Climate Controls = 2 sections when no devices
    assert len(sections) == 2

    # First section is Quick Status
    quick_status = sections[0]
    assert quick_status["title"] == "🏠 Quick Status"

    # Second section is Climate Controls with "no devices" message
    climate_section = sections[1]
    assert climate_section["title"] == "🌡️ Climate Controls"
    message_card = climate_section["cards"][0]
    assert message_card["type"] == "markdown"
    assert "No climate devices" in message_card["content"]


