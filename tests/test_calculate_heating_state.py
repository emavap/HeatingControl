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
    CONF_SCHEDULE_AWAY_HVAC_MODE,
    CONF_SCHEDULE_AWAY_TEMPERATURE,
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
    away_hvac_mode: str | None = None,
    away_temperature: float | None = None,
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
    if away_hvac_mode:
        schedule[CONF_SCHEDULE_AWAY_HVAC_MODE] = away_hvac_mode
    if away_temperature is not None:
        schedule[CONF_SCHEDULE_AWAY_TEMPERATURE] = away_temperature
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
    living = result.device_decisions["climate.living_room"]
    bedroom = result.device_decisions["climate.bedroom"]
    assert living.should_be_active is True
    assert living.hvac_mode == "heat"
    assert bedroom.should_be_active is False
    assert bedroom.hvac_mode is None


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
    decision = result.device_decisions["climate.living_room"]
    assert decision.hvac_mode == "heat"
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
    decision = result.device_decisions["climate.living_room"]
    assert decision.hvac_mode == "heat"
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
    assert office.hvac_mode is None


def test_last_schedule_wins(monkeypatch, dummy_hass: DummyHass):
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
                temperature=19.0,
                fan_mode="high",
            ),
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    kitchen = result.device_decisions["climate.kitchen"]
    assert kitchen.should_be_active is True
    assert kitchen.hvac_mode == "heat"
    assert kitchen.target_temp == 19.0
    assert kitchen.target_fan == "high"
    assert kitchen.active_schedules == ("Dinner Boost",)


def test_midnight_schedule_precedence(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 0, 30)

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.bedroom"],
        CONF_SCHEDULES: [
            base_schedule(
                "Late Night",
                "23:30",
                "06:00",
                devices=["climate.bedroom"],
                temperature=20.0,
            ),
            base_schedule(
                "After Midnight",
                "00:15",
                "02:00",
                devices=["climate.bedroom"],
                temperature=24.0,
            ),
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    bedroom = result.device_decisions["climate.bedroom"]
    assert bedroom.should_be_active is True
    assert bedroom.hvac_mode == "heat"
    assert bedroom.target_temp == 24.0
    assert bedroom.active_schedules == ("After Midnight",)


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
    morning_decision = morning_state.device_decisions["climate.living_room"]
    assert morning_decision.active_schedules == ("Morning",)
    assert morning_decision.hvac_mode == "heat"
    assert morning_decision.target_temp == 21.0

    freeze_time(monkeypatch, 19, 0)
    coordinator_evening = make_coordinator(dummy_hass, config)
    evening_state = coordinator_evening._calculate_heating_state()

    assert evening_state.schedule_decisions["Morning"].in_time_window is False
    assert evening_state.schedule_decisions["Evening"].in_time_window is True
    evening_decision = evening_state.device_decisions["climate.living_room"]
    assert evening_decision.active_schedules == ("Evening",)
    assert evening_decision.target_temp == 19.0
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
    decision_day = morning_state.device_decisions["climate.bedroom"]
    assert decision_day.active_schedules == ("AllDay",)
    assert decision_day.hvac_mode == "heat"
    assert decision_day.target_temp == 20.5

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
    morning_kitchen = morning.device_decisions[kitchen]
    morning_bedroom1 = morning.device_decisions[bedroom1]
    morning_bedroom2 = morning.device_decisions[bedroom2]
    assert morning_kitchen.active_schedules == ("Morning Warmup",)
    assert morning_kitchen.hvac_mode == "heat"
    assert morning_kitchen.target_temp == 20.0
    assert morning_bedroom1.active_schedules == ("Morning Warmup",)
    assert morning_bedroom1.hvac_mode == "heat"
    assert morning_bedroom1.target_temp == 20.0
    assert morning_bedroom2.active_schedules == ("Morning Warmup",)
    assert morning_bedroom2.hvac_mode == "heat"
    assert morning_bedroom2.target_temp == 20.0

    freeze_time(monkeypatch, 11, 0)
    midday = coordinator._calculate_heating_state()
    midday_kitchen = midday.device_decisions[kitchen]
    midday_bedroom1 = midday.device_decisions[bedroom1]
    midday_bedroom2 = midday.device_decisions[bedroom2]
    assert midday_kitchen.active_schedules == ("Daytime Kitchen",)
    assert midday_kitchen.target_temp == 20.0
    assert midday_bedroom1.should_be_active is True
    assert midday_bedroom1.hvac_mode == "heat"
    assert midday_bedroom1.target_temp == 20.0
    assert midday_bedroom2.should_be_active is True
    assert midday_bedroom2.hvac_mode == "heat"
    assert midday_bedroom2.target_temp == 20.0

    freeze_time(monkeypatch, 19, 30)
    evening = coordinator._calculate_heating_state()
    evening_kitchen = evening.device_decisions[kitchen]
    evening_bedroom2 = evening.device_decisions[bedroom2]
    evening_bedroom1 = evening.device_decisions[bedroom1]
    assert evening_kitchen.active_schedules == ("Evening Kitchen",)
    assert evening_kitchen.target_temp == 20.0
    assert evening_bedroom2.active_schedules == ("Evening Bedroom2",)
    assert evening_bedroom2.target_temp == 22.0
    assert evening_bedroom1.should_be_active is True
    assert evening_bedroom1.hvac_mode == "heat"
    assert evening_bedroom1.target_temp == 20.0

    freeze_time(monkeypatch, 21, 30)
    night = coordinator._calculate_heating_state()
    night_kitchen = night.device_decisions[kitchen]
    night_bedroom2 = night.device_decisions[bedroom2]
    night_bedroom1 = night.device_decisions[bedroom1]
    assert night_kitchen.active_schedules == ("Night Kitchen",)
    assert night_kitchen.target_temp == 20.0
    assert night_bedroom2.active_schedules == ("Night Bedroom2",)
    assert night_bedroom2.target_temp == 22.0
    assert night_bedroom1.active_schedules == ("Night Bedroom1",)
    assert night_bedroom1.target_temp == 20.0

    freeze_time(monkeypatch, 23, 30)
    lights_out = coordinator._calculate_heating_state()
    # At 23:00, "Lights Out" schedule starts with no devices. Existing schedules keep control
    # of their devices until another schedule that targets them begins.
    assert lights_out.device_decisions[kitchen].should_be_active is True
    assert lights_out.device_decisions[kitchen].active_schedules == ("Night Kitchen",)
    assert lights_out.device_decisions[kitchen].target_temp == 20.0
    assert lights_out.device_decisions[bedroom1].should_be_active is True
    assert lights_out.device_decisions[bedroom1].active_schedules == ("Night Bedroom1",)
    assert lights_out.device_decisions[bedroom1].target_temp == 20.0
    assert lights_out.device_decisions[bedroom2].should_be_active is True
    assert lights_out.device_decisions[bedroom2].active_schedules == ("Night Bedroom2",)
    assert lights_out.device_decisions[bedroom2].target_temp == 22.0
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
    # Schedule stays active in time window, but presence affects settings
    assert result.schedule_decisions["Afternoon"].is_active is True
    assert result.device_decisions["climate.bedroom"].should_be_active is False
    # With only_when_home=True and nobody home, device is turned off
    assert result.device_decisions["climate.bedroom"].hvac_mode == "off"


def test_schedule_away_settings_used_when_empty(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 8, 0)
    dummy_hass.states.set("device_tracker.alice", DummyState("not_home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.alice"],
        CONF_CLIMATE_DEVICES: ["climate.office"],
        CONF_SCHEDULES: [
            base_schedule(
                "Workday",
                "07:00",
                "18:00",
                devices=["climate.office"],
                temperature=21.0,
                away_hvac_mode="off",
                away_temperature=None,
            )
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    decision = result.device_decisions["climate.office"]
    assert decision.hvac_mode == "off"
    assert decision.should_be_active is False
    assert decision.target_temp is None


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


def test_exactly_at_midnight_schedule_wins(monkeypatch, dummy_hass: DummyHass):
    """Test schedule starting at 00:00 beats one from 23:00 when current time is 00:00."""
    freeze_time(monkeypatch, 0, 0)

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.bedroom"],
        CONF_SCHEDULES: [
            base_schedule(
                "Night",
                "23:00",
                "07:00",
                devices=["climate.bedroom"],
                temperature=18.0,
            ),
            base_schedule(
                "Midnight",
                "00:00",
                "06:00",
                devices=["climate.bedroom"],
                temperature=20.0,
            ),
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    bedroom = result.device_decisions["climate.bedroom"]
    assert bedroom.should_be_active is True
    assert bedroom.hvac_mode == "heat"
    assert bedroom.target_temp == 20.0
    assert bedroom.active_schedules == ("Midnight",)


def test_schedule_one_minute_across_midnight(monkeypatch, dummy_hass: DummyHass):
    """Test schedule at 23:59 vs 00:00, checked at 00:01."""
    freeze_time(monkeypatch, 0, 1)

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.bedroom"],
        CONF_SCHEDULES: [
            base_schedule(
                "Late",
                "23:59",
                "06:00",
                devices=["climate.bedroom"],
                temperature=18.0,
            ),
            base_schedule(
                "Early",
                "00:00",
                "06:00",
                devices=["climate.bedroom"],
                temperature=22.0,
            ),
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    bedroom = result.device_decisions["climate.bedroom"]
    assert bedroom.should_be_active is True
    assert bedroom.hvac_mode == "heat"
    assert bedroom.target_temp == 22.0
    assert bedroom.active_schedules == ("Early",)


def test_multiple_schedules_crossing_midnight(monkeypatch, dummy_hass: DummyHass):
    """Test multiple overlapping schedules crossing midnight."""
    freeze_time(monkeypatch, 1, 0)

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.bedroom"],
        CONF_SCHEDULES: [
            base_schedule(
                "Early Night",
                "22:00",
                "02:00",
                devices=["climate.bedroom"],
                temperature=18.0,
            ),
            base_schedule(
                "Late Night",
                "23:00",
                "03:00",
                devices=["climate.bedroom"],
                temperature=19.0,
            ),
            base_schedule(
                "After Midnight",
                "00:30",
                "04:00",
                devices=["climate.bedroom"],
                temperature=20.0,
            ),
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    bedroom = result.device_decisions["climate.bedroom"]
    assert bedroom.should_be_active is True
    assert bedroom.hvac_mode == "heat"
    assert bedroom.target_temp == 20.0
    assert bedroom.active_schedules == ("After Midnight",)


def test_current_time_equals_schedule_start(monkeypatch, dummy_hass: DummyHass):
    """Test when current time exactly matches a schedule start time."""
    freeze_time(monkeypatch, 7, 0)

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: [],
        CONF_CLIMATE_DEVICES: ["climate.bedroom"],
        CONF_SCHEDULES: [
            base_schedule(
                "Night",
                "23:00",
                "07:00",
                devices=["climate.bedroom"],
                temperature=18.0,
            ),
            base_schedule(
                "Morning",
                "07:00",
                "09:00",
                devices=["climate.bedroom"],
                temperature=22.0,
            ),
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    bedroom = result.device_decisions["climate.bedroom"]
    assert bedroom.should_be_active is True
    assert bedroom.hvac_mode == "heat"
    assert bedroom.target_temp == 22.0
    assert bedroom.active_schedules == ("Morning",)
