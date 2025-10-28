from types import SimpleNamespace

from custom_components.heating_control.const import DEFAULT_FINAL_SETTLE, DEFAULT_SETTLE_SECONDS
from custom_components.heating_control.controller import ClimateController
from custom_components.heating_control.coordinator import HeatingControlCoordinator
from custom_components.heating_control.models import (
    DiagnosticsSnapshot,
    HeatingStateSnapshot,
    ScheduleDecision,
)
from tests.conftest import DummyHass


def make_coordinator() -> HeatingControlCoordinator:
    coordinator = HeatingControlCoordinator.__new__(HeatingControlCoordinator)
    coordinator.hass = DummyHass()
    coordinator.config_entry = SimpleNamespace(options=None, data={})
    coordinator._controller = ClimateController(
        coordinator.hass,
        settle_seconds=DEFAULT_SETTLE_SECONDS,
        final_settle=DEFAULT_FINAL_SETTLE,
    )
    coordinator._previous_schedule_states = None
    coordinator._previous_presence_state = None
    coordinator._force_update = False
    return coordinator


def snapshot(
    *,
    anyone_home: bool,
    schedule_states: dict[str, bool],
) -> HeatingStateSnapshot:
    schedule_decisions = {
        schedule_id: ScheduleDecision(
            schedule_id=schedule_id,
            name=schedule_id.title(),
            start_time="00:00",
            end_time="23:59",
            always_active=False,
            only_when_home=True,
            enabled=True,
            is_active=is_active,
            in_time_window=True,
            presence_ok=True,
            use_gas_heater=False,
            device_count=0,
            devices=(),
            target_temp=20.0,
            target_fan="auto",
        )
        for schedule_id, is_active in schedule_states.items()
    }

    diagnostics = DiagnosticsSnapshot(
        now_time="00:00",
        tracker_states={"device_tracker.test": anyone_home},
        trackers_home=int(anyone_home),
        trackers_total=1,
        auto_heating_enabled=True,
        only_scheduled_active=True,
        schedule_count=len(schedule_states),
        active_schedules=sum(schedule_states.values()),
        active_devices=0,
    )

    return HeatingStateSnapshot(
        both_away=not anyone_home,
        anyone_home=anyone_home,
        schedule_decisions=schedule_decisions,
        device_decisions={},
        gas_heater_decision=None,
        diagnostics=diagnostics,
    )


def test_force_update_flag():
    coordinator = make_coordinator()
    coordinator._force_update = True
    result = coordinator._detect_state_transitions(
        snapshot(anyone_home=True, schedule_states={})
    )

    assert result is True
    assert coordinator._force_update is False


def test_first_run_triggers_update():
    coordinator = make_coordinator()

    assert (
        coordinator._detect_state_transitions(
            snapshot(anyone_home=True, schedule_states={})
        )
        is True
    )


def test_presence_change_detected():
    coordinator = make_coordinator()
    coordinator._previous_schedule_states = {"morning": False}
    coordinator._previous_presence_state = False

    assert (
        coordinator._detect_state_transitions(
            snapshot(anyone_home=True, schedule_states={"morning": False})
        )
        is True
    )


def test_schedule_activation_detected():
    coordinator = make_coordinator()
    coordinator._previous_schedule_states = {"morning": False}
    coordinator._previous_presence_state = True

    assert (
        coordinator._detect_state_transitions(
            snapshot(anyone_home=True, schedule_states={"morning": True})
        )
        is True
    )


def test_schedule_removed_detected():
    coordinator = make_coordinator()
    coordinator._previous_schedule_states = {"morning": True}
    coordinator._previous_presence_state = True

    assert (
        coordinator._detect_state_transitions(
            snapshot(anyone_home=True, schedule_states={})
        )
        is True
    )


def test_no_changes_returns_false():
    coordinator = make_coordinator()
    coordinator._previous_schedule_states = {"morning": False}
    coordinator._previous_presence_state = False

    assert (
        coordinator._detect_state_transitions(
            snapshot(anyone_home=False, schedule_states={"morning": False})
        )
        is False
    )
