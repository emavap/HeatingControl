"""Tests for force refresh behavior in ClimateController."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import STATE_ON

from custom_components.heating_control.controller import ClimateController
from custom_components.heating_control.models import DeviceDecision
from tests.conftest import DummyHass, DummyState


@pytest.mark.asyncio
async def test_force_refresh_after_timeout(dummy_hass: DummyHass, no_sleep):
    """Test that devices are marked for force refresh after timeout."""
    controller = ClimateController(dummy_hass, settle_seconds=0, final_settle=0)
    entity_id = "climate.test"

    # Mock state
    dummy_hass.states.set(entity_id, DummyState(STATE_ON, {}))

    # Mock service call that times out
    with patch.object(dummy_hass.services, "async_call", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = asyncio.TimeoutError()

        decision = DeviceDecision(
            entity_id=entity_id,
            should_be_active=True,
            active_schedules=("test",),
            hvac_mode="heat",
            target_temp=20.0,
            target_fan="auto",
        )

        timed_out = await controller.async_apply([decision])

        # Should be in timed out list
        assert entity_id in timed_out

        # Should be marked for force refresh
        assert entity_id in controller._force_refresh_devices


@pytest.mark.asyncio
async def test_force_refresh_set_on_timeout(dummy_hass: DummyHass, no_sleep):
    """Test that force refresh flag is set when operations timeout."""
    controller = ClimateController(dummy_hass, settle_seconds=0, final_settle=0)
    entity_id = "climate.test"

    # Mock state
    dummy_hass.states.set(entity_id, DummyState(STATE_ON, {}))

    # Verify force refresh not set initially
    assert entity_id not in controller._force_refresh_devices

    # Make call that times out
    with patch.object(dummy_hass.services, "async_call", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = asyncio.TimeoutError()

        decision = DeviceDecision(
            entity_id=entity_id,
            should_be_active=True,
            active_schedules=("test",),
            hvac_mode="heat",
            target_temp=20.0,
            target_fan="auto",
        )

        await controller.async_apply([decision])

        # Should now be marked for force refresh
        assert entity_id in controller._force_refresh_devices


@pytest.mark.asyncio
async def test_force_refresh_flag_persists_between_cycles(dummy_hass: DummyHass, no_sleep):
    """Test that force refresh flag persists and triggers full refresh on next cycle."""
    controller = ClimateController(dummy_hass, settle_seconds=0, final_settle=0)
    entity_id = "climate.test"

    # Mock state
    dummy_hass.states.set(entity_id, DummyState(STATE_ON, {}))

    call_count = 0

    async def count_calls(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return None

    with patch.object(dummy_hass.services, "async_call", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = count_calls

        # First application - set history
        decision = DeviceDecision(
            entity_id=entity_id,
            should_be_active=True,
            active_schedules=("test",),
            hvac_mode="heat",
            target_temp=20.0,
            target_fan=None,
        )

        await controller.async_apply([decision])
        initial_calls = call_count

        # Manually set force refresh flag (simulating a timeout from previous cycle)
        controller._force_refresh_devices.add(entity_id)

        # Apply again with same settings - should still make calls due to force refresh
        call_count = 0
        await controller.async_apply([decision])

        # Should have made at least HVAC and temperature calls even though settings unchanged
        assert call_count >= 2  # HVAC mode + temperature


@pytest.mark.asyncio
async def test_partial_operation_failure(dummy_hass: DummyHass, no_sleep):
    """Test force refresh when some operations succeed and others fail."""
    controller = ClimateController(dummy_hass, settle_seconds=0, final_settle=0)
    entity_id = "climate.test"

    # Mock state with fan modes
    dummy_hass.states.set(
        entity_id,
        DummyState(STATE_ON, {"fan_modes": ["auto", "low", "high"]})
    )

    call_count = {"hvac": 0, "temp": 0, "fan": 0}

    async def selective_timeout(*args, **kwargs):
        """Timeout only on temperature calls."""
        service = args[1] if len(args) > 1 else kwargs.get("service", "")
        # Map service name to counter key
        key_map = {
            "set_hvac_mode": "hvac",
            "set_temperature": "temp",
            "set_fan_mode": "fan",
        }
        key = key_map.get(service, "unknown")
        if key != "unknown":
            call_count[key] += 1

        if service == "set_temperature":
            raise asyncio.TimeoutError()
        return None

    with patch.object(dummy_hass.services, "async_call", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = selective_timeout

        decision = DeviceDecision(
            entity_id=entity_id,
            should_be_active=True,
            active_schedules=("test",),
            hvac_mode="heat",
            target_temp=20.0,
            target_fan="auto",
        )

        await controller.async_apply([decision])

        # Should be marked for force refresh due to partial failure
        assert entity_id in controller._force_refresh_devices

        # HVAC and fan should have been attempted
        assert call_count["hvac"] >= 1
        assert call_count["temp"] >= 1
