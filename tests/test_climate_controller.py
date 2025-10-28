import pytest

from custom_components.heating_control.controller import ClimateController
from custom_components.heating_control.models import DeviceDecision
from custom_components.heating_control.const import DEFAULT_FINAL_SETTLE, DEFAULT_SETTLE_SECONDS
from tests.conftest import DummyHass, DummyState


def make_controller(hass: DummyHass) -> ClimateController:
    return ClimateController(
        hass,
        settle_seconds=DEFAULT_SETTLE_SECONDS,
        final_settle=DEFAULT_FINAL_SETTLE,
    )


def _decision(
    entity_id: str,
    *,
    on: bool,
    temp: float,
    fan: str,
) -> DeviceDecision:
    return DeviceDecision(
        entity_id=entity_id,
        should_be_active=on,
        active_schedules=("Test",),
        target_temp=temp,
        target_fan=fan,
    )


@pytest.mark.asyncio
async def test_turn_on_device_with_full_update(dummy_hass: DummyHass, no_sleep):
    dummy_hass.states.set(
        "climate.living_room",
        DummyState("off", {"fan_modes": ["auto", "high"]}),
    )
    controller = make_controller(dummy_hass)

    await controller.async_apply([_decision("climate.living_room", on=True, temp=23.5, fan="high")])

    assert dummy_hass.services.calls == [
        {
            "domain": "climate",
            "service": "set_hvac_mode",
            "data": {"entity_id": "climate.living_room", "hvac_mode": "heat"},
            "blocking": True,
        },
        {
            "domain": "climate",
            "service": "set_temperature",
            "data": {"entity_id": "climate.living_room", "temperature": 23.5},
            "blocking": True,
        },
        {
            "domain": "climate",
            "service": "set_fan_mode",
            "data": {"entity_id": "climate.living_room", "fan_mode": "high"},
            "blocking": True,
        },
    ]


@pytest.mark.asyncio
async def test_temperature_change_without_mode_toggle(dummy_hass: DummyHass, no_sleep):
    dummy_hass.states.set(
        "climate.office",
        DummyState("heat", {"fan_modes": ["auto", "medium"]}),
    )
    controller = make_controller(dummy_hass)

    # Prime controller history
    await controller.async_apply(
        [_decision("climate.office", on=True, temp=21.0, fan="auto")],
    )
    dummy_hass.services.calls.clear()

    await controller.async_apply(
        [_decision("climate.office", on=True, temp=22.5, fan="auto")],
    )

    assert dummy_hass.services.calls == [
        {
            "domain": "climate",
            "service": "set_temperature",
            "data": {"entity_id": "climate.office", "temperature": 22.5},
            "blocking": True,
        }
    ]


@pytest.mark.asyncio
async def test_turn_off_device(dummy_hass: DummyHass, no_sleep):
    dummy_hass.states.set(
        "climate.bedroom",
        DummyState("heat", {}),
    )
    controller = make_controller(dummy_hass)

    await controller.async_apply([_decision("climate.bedroom", on=True, temp=20.0, fan="auto")])
    dummy_hass.services.calls.clear()

    await controller.async_apply([_decision("climate.bedroom", on=False, temp=20.0, fan="auto")])

    assert dummy_hass.services.calls == [
        {
            "domain": "climate",
            "service": "set_hvac_mode",
            "data": {"entity_id": "climate.bedroom", "hvac_mode": "off"},
            "blocking": True,
        }
    ]


@pytest.mark.asyncio
async def test_no_changes_no_calls(dummy_hass: DummyHass, no_sleep):
    dummy_hass.states.set(
        "climate.kitchen",
        DummyState("heat", {"fan_modes": ["auto"]}),
    )
    controller = make_controller(dummy_hass)

    decision = _decision("climate.kitchen", on=True, temp=20.0, fan="auto")
    await controller.async_apply([decision])
    dummy_hass.services.calls.clear()

    await controller.async_apply([decision])

    assert dummy_hass.services.calls == []


@pytest.mark.asyncio
async def test_fan_mode_not_supported(dummy_hass: DummyHass, no_sleep):
    dummy_hass.states.set(
        "climate.study",
        DummyState("off", {"fan_modes": ["auto"]}),
    )
    controller = make_controller(dummy_hass)

    await controller.async_apply([_decision("climate.study", on=True, temp=21.0, fan="high")])

    assert any(call["service"] == "set_hvac_mode" for call in dummy_hass.services.calls)
    assert any(call["service"] == "set_temperature" for call in dummy_hass.services.calls)
    fan_calls = [
        call
        for call in dummy_hass.services.calls
        if call["service"] == "set_fan_mode"
    ]
    assert not fan_calls

