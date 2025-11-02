from __future__ import annotations

from datetime import datetime as real_datetime
from types import SimpleNamespace

import pytest

import custom_components.heating_control.coordinator as coordinator_module
from custom_components.heating_control.const import (
    CONF_AUTO_HEATING_ENABLED,
    CONF_CLIMATE_DEVICES,
    CONF_DEVICE_TRACKERS,
    CONF_SCHEDULES,
    CONF_SCHEDULE_DEVICES,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_FAN_MODE,
    CONF_SCHEDULE_HVAC_MODE,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_ONLY_WHEN_HOME,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_TEMPERATURE,
    DEFAULT_FINAL_SETTLE,
    DEFAULT_SCHEDULE_FAN_MODE,
    DEFAULT_SCHEDULE_HVAC_MODE,
    DEFAULT_SCHEDULE_TEMPERATURE,
    DEFAULT_SETTLE_SECONDS,
)
from custom_components.heating_control.controller import ClimateController
from custom_components.heating_control.coordinator import HeatingControlCoordinator
from tests.conftest import DummyState, DummyHass


def make_coordinator(hass: DummyHass, config: dict) -> HeatingControlCoordinator:
    coordinator = HeatingControlCoordinator.__new__(HeatingControlCoordinator)
    coordinator.hass = hass
    coordinator.config_entry = SimpleNamespace(options=None, data=config)
    coordinator._controller = ClimateController(
        hass,
        settle_seconds=DEFAULT_SETTLE_SECONDS,
        final_settle=DEFAULT_FINAL_SETTLE,
    )
    coordinator._previous_schedule_states = None
    coordinator._previous_presence_state = None
    coordinator._force_update = False
    return coordinator


def freeze_time(monkeypatch, hour: int, minute: int):
    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2024, 1, 1, hour, minute)

    monkeypatch.setattr(coordinator_module, "datetime", FakeDateTime)


def base_schedule(
    name: str,
    start: str,
    end: str | None,
    *,
    enabled: bool = True,
    only_when_home: bool = True,
    hvac_mode: str = DEFAULT_SCHEDULE_HVAC_MODE,
    devices: list[str] | None = None,
    temperature: float = DEFAULT_SCHEDULE_TEMPERATURE,
    fan_mode: str = DEFAULT_SCHEDULE_FAN_MODE,
) -> dict:
    schedule = {
        "id": name,
        CONF_SCHEDULE_NAME: name,
        CONF_SCHEDULE_ENABLED: enabled,
        CONF_SCHEDULE_START: start,
        CONF_SCHEDULE_ONLY_WHEN_HOME: only_when_home,
        CONF_SCHEDULE_HVAC_MODE: hvac_mode,
        CONF_SCHEDULE_DEVICES: devices or [],
        CONF_SCHEDULE_TEMPERATURE: temperature,
        CONF_SCHEDULE_FAN_MODE: fan_mode,
    }
    if end is not None:
        schedule[CONF_SCHEDULE_END] = end
    return schedule


def test_schedule_activation_with_presence(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 7, 30)
    dummy_hass.states.set("device_tracker.user1", DummyState("home", {}))
    dummy_hass.states.set("device_tracker.user2", DummyState("not_home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.user1", "device_tracker.user2"],
        CONF_CLIMATE_DEVICES: ["climate.living_room", "climate.bedroom"],
        CONF_SCHEDULES: [
            base_schedule(
                "Morning",
                "06:00",
                "09:00",
                devices=["climate.living_room"],
                temperature=21.5,
                fan_mode="auto",
            )
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    assert result.everyone_away is False
    assert result.anyone_home is True
    assert result.schedule_decisions["Morning"].is_active is True
    assert result.device_decisions["climate.living_room"].should_be_active is True
    assert result.device_decisions["climate.living_room"].hvac_mode == "heat"
    assert result.device_decisions["climate.bedroom"].should_be_active is False
    assert result.device_decisions["climate.bedroom"].hvac_mode == "off"


def test_schedule_activation_without_trackers_defaults_to_home(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 7, 30)

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.living_room"],
        CONF_SCHEDULES: [
            base_schedule(
                "Morning",
                "06:00",
                "09:00",
                devices=["climate.living_room"],
                temperature=21.5,
                fan_mode="auto",
            )
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    assert result.everyone_away is False
    assert result.anyone_home is True
    assert result.schedule_decisions["Morning"].is_active is True
    assert result.diagnostics.trackers_total == 0
    assert result.diagnostics.trackers_home == 0


def test_off_schedule_turns_device_off(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 12, 0)

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.living_room"],
        CONF_SCHEDULES: [
            base_schedule(
                "Shutdown",
                "11:00",
                "13:00",
                hvac_mode="off",
                devices=["climate.living_room"],
            )
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    decision = result.device_decisions["climate.living_room"]
    assert decision.should_be_active is False
    assert decision.hvac_mode == "off"
    assert decision.active_schedules == ("Shutdown",)


def test_cool_schedule_sets_cooling_mode(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 16, 0)

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.living_room"],
        CONF_SCHEDULES: [
            base_schedule(
                "Afternoon Cool",
                "15:00",
                "18:00",
                hvac_mode="cool",
                devices=["climate.living_room"],
                temperature=24.0,
            )
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    decision = result.device_decisions["climate.living_room"]
    assert decision.hvac_mode == "cool"
    assert decision.should_be_active is True
    assert decision.target_temp == 24.0


def test_blank_tracker_entries_are_ignored(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 7, 30)
    dummy_hass.states.set("device_tracker.user1", DummyState("home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["", None, "device_tracker.user1"],
        CONF_CLIMATE_DEVICES: ["climate.living_room"],
        CONF_SCHEDULES: [
            base_schedule(
                "Morning",
                "06:00",
                "09:00",
                devices=["climate.living_room"],
                temperature=21.5,
                fan_mode="auto",
            )
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    assert result.anyone_home is True
    assert result.diagnostics.trackers_total == 1
    assert result.diagnostics.trackers_home == 1


def test_device_without_schedule_stays_idle(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 12, 0)
    dummy_hass.states.set("device_tracker.user1", DummyState("home", {}))
    dummy_hass.states.set("device_tracker.user2", DummyState("not_home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.user1"],
        CONF_CLIMATE_DEVICES: ["climate.office"],
        CONF_SCHEDULES: [],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    office = result.device_decisions["climate.office"]
    assert office.should_be_active is False
    assert office.hvac_mode == "off"


def test_multiple_schedules_highest_temperature_wins(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 19, 0)
    dummy_hass.states.set("device_tracker.user1", DummyState("home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.user1"],
        CONF_CLIMATE_DEVICES: ["climate.kitchen"],
        CONF_SCHEDULES: [
            base_schedule(
                "Evening Comfort",
                "18:00",
                "22:00",
                devices=["climate.kitchen"],
                temperature=21.0,
                fan_mode="medium",
            ),
            base_schedule(
                "Dinner Boost",
                "19:00",
                "21:00",
                devices=["climate.kitchen"],
                temperature=23.0,
                fan_mode="high",
            ),
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    kitchen = result.device_decisions["climate.kitchen"]
    assert kitchen.should_be_active is True
    assert kitchen.hvac_mode == "heat"
    assert kitchen.target_temp == 23.0
    assert kitchen.target_fan == "high"
    assert set(kitchen.active_schedules) == {"Evening Comfort", "Dinner Boost"}


def test_schedule_without_end_uses_next_start(monkeypatch, dummy_hass: DummyHass):
    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.living_room"],
        CONF_SCHEDULES: [
            base_schedule(
                "Morning",
                "06:00",
                None,
                devices=["climate.living_room"],
                temperature=21.0,
            ),
            base_schedule(
                "Evening",
                "18:00",
                None,
                devices=["climate.living_room"],
                temperature=19.0,
            ),
        ],
    }

    freeze_time(monkeypatch, 7, 30)
    coordinator_morning = make_coordinator(dummy_hass, config)
    morning_state = coordinator_morning._calculate_heating_state()

    assert morning_state.schedule_decisions["Morning"].in_time_window is True
    assert morning_state.schedule_decisions["Morning"].end_time == "18:00"
    assert morning_state.schedule_decisions["Evening"].in_time_window is False

    freeze_time(monkeypatch, 19, 0)
    coordinator_evening = make_coordinator(dummy_hass, config)
    evening_state = coordinator_evening._calculate_heating_state()

    assert evening_state.schedule_decisions["Morning"].in_time_window is False
    assert evening_state.schedule_decisions["Evening"].in_time_window is True
    assert evening_state.schedule_decisions["Evening"].end_time == "06:00"


def test_single_schedule_without_end_covers_full_day(monkeypatch, dummy_hass: DummyHass):
    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.bedroom"],
        CONF_SCHEDULES: [
            base_schedule(
                "AllDay",
                "08:00",
                None,
                devices=["climate.bedroom"],
                temperature=20.5,
            ),
        ],
    }

    freeze_time(monkeypatch, 10, 0)
    morning_state = make_coordinator(dummy_hass, config)._calculate_heating_state()
    assert morning_state.schedule_decisions["AllDay"].in_time_window is True
    assert morning_state.schedule_decisions["AllDay"].end_time == "23:59"

    freeze_time(monkeypatch, 2, 0)
    overnight_state = make_coordinator(dummy_hass, config)._calculate_heating_state()
    assert overnight_state.schedule_decisions["AllDay"].in_time_window is False


def test_daily_schedule_flow(monkeypatch, dummy_hass: DummyHass):
    dummy_hass.states.set("device_tracker.family", DummyState("home", {}))

    kitchen = "climate.kitchen"
    bedroom1 = "climate.bedroom1"
    bedroom2 = "climate.bedroom2"

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.family"],
        CONF_CLIMATE_DEVICES: [kitchen, bedroom1, bedroom2],
        CONF_SCHEDULES: [
            base_schedule(
                "Morning Warmup",
                "07:00",
                None,
                devices=[kitchen, bedroom1, bedroom2],
                temperature=20.0,
            ),
            base_schedule(
                "Daytime Kitchen",
                "10:00",
                None,
                devices=[kitchen],
                temperature=20.0,
            ),
            base_schedule(
                "Evening Kitchen",
                "19:00",
                None,
                devices=[kitchen],
                temperature=20.0,
            ),
            base_schedule(
                "Evening Bedroom2",
                "19:00",
                None,
                devices=[bedroom2],
                temperature=22.0,
            ),
            base_schedule(
                "Night Kitchen",
                "21:00",
                None,
                devices=[kitchen],
                temperature=20.0,
            ),
            base_schedule(
                "Night Bedroom2",
                "21:00",
                None,
                devices=[bedroom2],
                temperature=22.0,
            ),
            base_schedule(
                "Night Bedroom1",
                "21:00",
                None,
                devices=[bedroom1],
                temperature=20.0,
            ),
            base_schedule(
                "Lights Out",
                "23:00",
                None,
                devices=[],
            ),
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)

    freeze_time(monkeypatch, 8, 0)
    morning = coordinator._calculate_heating_state()
    assert morning.device_decisions[kitchen].should_be_active is True
    assert morning.device_decisions[kitchen].target_temp == 20.0
    assert morning.device_decisions[bedroom1].should_be_active is True
    assert morning.device_decisions[bedroom1].target_temp == 20.0
    assert morning.device_decisions[bedroom2].should_be_active is True
    assert morning.device_decisions[bedroom2].target_temp == 20.0

    freeze_time(monkeypatch, 11, 0)
    midday = coordinator._calculate_heating_state()
    assert midday.device_decisions[kitchen].should_be_active is True
    assert midday.device_decisions[kitchen].target_temp == 20.0
    assert midday.device_decisions[bedroom1].should_be_active is False
    assert midday.device_decisions[bedroom2].should_be_active is False

    freeze_time(monkeypatch, 19, 30)
    evening = coordinator._calculate_heating_state()
    assert evening.device_decisions[kitchen].should_be_active is True
    assert evening.device_decisions[kitchen].target_temp == 20.0
    assert evening.device_decisions[bedroom2].should_be_active is True
    assert evening.device_decisions[bedroom2].target_temp == 22.0
    assert evening.device_decisions[bedroom1].should_be_active is False

    freeze_time(monkeypatch, 21, 30)
    night = coordinator._calculate_heating_state()
    assert night.device_decisions[kitchen].should_be_active is True
    assert night.device_decisions[kitchen].target_temp == 20.0
    assert night.device_decisions[bedroom2].should_be_active is True
    assert night.device_decisions[bedroom2].target_temp == 22.0
    assert night.device_decisions[bedroom1].should_be_active is True
    assert night.device_decisions[bedroom1].target_temp == 20.0

    freeze_time(monkeypatch, 23, 30)
    lights_out = coordinator._calculate_heating_state()
    assert lights_out.device_decisions[kitchen].should_be_active is False
    assert lights_out.device_decisions[bedroom1].should_be_active is False
    assert lights_out.device_decisions[bedroom2].should_be_active is False
def test_schedule_requires_presence(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 15, 0)
    dummy_hass.states.set("device_tracker.user1", DummyState("not_home", {}))
    dummy_hass.states.set("device_tracker.user2", DummyState("not_home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.user1", "device_tracker.user2"],
        CONF_CLIMATE_DEVICES: ["climate.bedroom"],
        CONF_SCHEDULES: [
            base_schedule(
                "Afternoon",
                "14:00",
                "16:00",
                devices=["climate.bedroom"],
                temperature=22.0,
                only_when_home=True,
            )
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    assert result.everyone_away is True
    assert result.anyone_home is False
    assert result.schedule_decisions["Afternoon"].is_active is False
    assert result.device_decisions["climate.bedroom"].should_be_active is False


def test_multiple_trackers_presence_counts(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 8, 0)
    dummy_hass.states.set("device_tracker.user1", DummyState("home", {}))
    dummy_hass.states.set("device_tracker.user2", DummyState("home", {}))
    dummy_hass.states.set("device_tracker.user3", DummyState("not_home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [
            "device_tracker.user1",
            "device_tracker.user2",
            "device_tracker.user3",
        ],
        CONF_CLIMATE_DEVICES: ["climate.living_room"],
        CONF_SCHEDULES: [],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    assert result.anyone_home is True
    assert result.everyone_away is False
    diagnostics = result.diagnostics
    assert diagnostics.trackers_home == 2
    assert diagnostics.trackers_total == 3
    assert diagnostics.tracker_states["device_tracker.user3"] is False


def test_time_window_spanning_midnight():
    assert HeatingControlCoordinator._is_time_in_schedule("23:30", "22:00", "01:00") is True
    assert HeatingControlCoordinator._is_time_in_schedule("00:30", "22:00", "01:00") is True
    assert HeatingControlCoordinator._is_time_in_schedule("02:00", "22:00", "01:00") is False
    assert HeatingControlCoordinator._is_time_in_schedule("12:00", "08:00", "18:00") is True
    assert HeatingControlCoordinator._is_time_in_schedule("06:00", "08:00", "18:00") is False
