from datetime import datetime as real_datetime
from types import SimpleNamespace

import pytest

import custom_components.heating_control.coordinator as coordinator_module
from custom_components.heating_control.const import (
    CONF_AUTO_HEATING_ENABLED,
    CONF_CLIMATE_DEVICES,
    CONF_DEVICE_TRACKERS,
    CONF_GAS_HEATER_ENTITY,
    CONF_ONLY_SCHEDULED_ACTIVE,
    CONF_SCHEDULES,
    CONF_SCHEDULE_ALWAYS_ACTIVE,
    CONF_SCHEDULE_DEVICES,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_FAN_MODE,
    CONF_SCHEDULE_NAME,
    CONF_SCHEDULE_ONLY_WHEN_HOME,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_TEMPERATURE,
    CONF_SCHEDULE_USE_GAS,
    DEFAULT_FINAL_SETTLE,
    DEFAULT_ONLY_SCHEDULED_ACTIVE,
    DEFAULT_SCHEDULE_FAN_MODE,
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
    end: str,
    *,
    enabled: bool = True,
    always_active: bool = False,
    only_when_home: bool = True,
    use_gas: bool = False,
    devices: list[str] | None = None,
    temperature: float = DEFAULT_SCHEDULE_TEMPERATURE,
    fan_mode: str = DEFAULT_SCHEDULE_FAN_MODE,
) -> dict:
    return {
        "id": name,
        CONF_SCHEDULE_NAME: name,
        CONF_SCHEDULE_ENABLED: enabled,
        CONF_SCHEDULE_START: start,
        CONF_SCHEDULE_END: end,
        CONF_SCHEDULE_ALWAYS_ACTIVE: always_active,
        CONF_SCHEDULE_ONLY_WHEN_HOME: only_when_home,
        CONF_SCHEDULE_USE_GAS: use_gas,
        CONF_SCHEDULE_DEVICES: devices or [],
        CONF_SCHEDULE_TEMPERATURE: temperature,
        CONF_SCHEDULE_FAN_MODE: fan_mode,
    }


def test_schedule_activation_with_presence(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 7, 30)
    dummy_hass.states.set("device_tracker.user1", DummyState("home", {}))
    dummy_hass.states.set("device_tracker.user2", DummyState("not_home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.user1", "device_tracker.user2"],
        CONF_ONLY_SCHEDULED_ACTIVE: True,
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

    assert result.both_away is False
    assert result.anyone_home is True
    assert result.schedule_decisions["Morning"].is_active is True
    assert result.device_decisions["climate.living_room"].should_be_active is True
    assert result.device_decisions["climate.bedroom"].should_be_active is False


def test_only_scheduled_active_false_allows_defaults(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 12, 0)
    dummy_hass.states.set("device_tracker.user1", DummyState("home", {}))
    dummy_hass.states.set("device_tracker.user2", DummyState("not_home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.user1"],
        CONF_ONLY_SCHEDULED_ACTIVE: False,
        CONF_CLIMATE_DEVICES: ["climate.office"],
        CONF_SCHEDULES: [],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    office = result.device_decisions["climate.office"]
    assert office.should_be_active is True
    assert office.target_temp == DEFAULT_SCHEDULE_TEMPERATURE


def test_multiple_schedules_highest_temperature_wins(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 19, 0)
    dummy_hass.states.set("device_tracker.user1", DummyState("home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.user1"],
        CONF_ONLY_SCHEDULED_ACTIVE: True,
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
    assert kitchen.target_temp == 23.0
    assert kitchen.target_fan == "high"
    assert set(kitchen.active_schedules) == {"Evening Comfort", "Dinner Boost"}


def test_gas_heater_activation_and_defaults(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 8, 30)
    dummy_hass.states.set("device_tracker.user1", DummyState("home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.user1"],
        CONF_CLIMATE_DEVICES: ["climate.living_room"],
        CONF_GAS_HEATER_ENTITY: "climate.gas_heater",
        CONF_ONLY_SCHEDULED_ACTIVE: DEFAULT_ONLY_SCHEDULED_ACTIVE,
        CONF_SCHEDULES: [
            base_schedule(
                "Gas Morning",
                "07:00",
                "09:00",
                use_gas=True,
                devices=["climate.living_room"],
                temperature=24.0,
                fan_mode="high",
            )
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    active_result = coordinator._calculate_heating_state()
    gas_decision = active_result.gas_heater_decision

    assert gas_decision is not None
    assert gas_decision.entity_id == "climate.gas_heater"
    assert gas_decision.should_be_active is True
    assert gas_decision.target_temp == 24.0
    assert gas_decision.target_fan == "high"
    assert list(gas_decision.active_schedules) == ["Gas Morning"]

    freeze_time(monkeypatch, 10, 0)
    inactive_result = coordinator._calculate_heating_state()
    gas_decision = inactive_result.gas_heater_decision

    assert gas_decision is not None
    assert gas_decision.should_be_active is False
    assert gas_decision.target_temp == DEFAULT_SCHEDULE_TEMPERATURE
    assert list(gas_decision.active_schedules) == []


def test_schedule_requires_presence(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 15, 0)
    dummy_hass.states.set("device_tracker.user1", DummyState("not_home", {}))
    dummy_hass.states.set("device_tracker.user2", DummyState("not_home", {}))

    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_DEVICE_TRACKERS: ["device_tracker.user1", "device_tracker.user2"],
        CONF_CLIMATE_DEVICES: ["climate.bedroom"],
        CONF_ONLY_SCHEDULED_ACTIVE: True,
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

    assert result.both_away is True
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
        CONF_ONLY_SCHEDULED_ACTIVE: True,
        CONF_SCHEDULES: [],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    assert result.anyone_home is True
    assert result.both_away is False
    diagnostics = result.diagnostics
    assert diagnostics.trackers_home == 2
    assert diagnostics.trackers_total == 3
    assert diagnostics.tracker_states["device_tracker.user3"] is False


def test_always_active_schedule_ignores_time(monkeypatch, dummy_hass: DummyHass):
    freeze_time(monkeypatch, 3, 0)
    config = {
        CONF_AUTO_HEATING_ENABLED: True,
        CONF_CLIMATE_DEVICES: ["climate.server_room"],
        CONF_ONLY_SCHEDULED_ACTIVE: True,
        CONF_SCHEDULES: [
            base_schedule(
                "24/7 Cooling",
                "08:00",
                "18:00",
                always_active=True,
                only_when_home=False,
                devices=["climate.server_room"],
                temperature=18.0,
            )
        ],
    }

    coordinator = make_coordinator(dummy_hass, config)
    result = coordinator._calculate_heating_state()

    assert result.schedule_decisions["24/7 Cooling"].is_active is True
    assert result.device_decisions["climate.server_room"].target_temp == 18.0


def test_time_window_spanning_midnight():
    assert HeatingControlCoordinator._is_time_in_schedule("23:30", "22:00", "01:00") is True
    assert HeatingControlCoordinator._is_time_in_schedule("00:30", "22:00", "01:00") is True
    assert HeatingControlCoordinator._is_time_in_schedule("02:00", "22:00", "01:00") is False
    assert HeatingControlCoordinator._is_time_in_schedule("12:00", "08:00", "18:00") is True
    assert HeatingControlCoordinator._is_time_in_schedule("06:00", "08:00", "18:00") is False
