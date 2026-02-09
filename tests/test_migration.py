"""Tests for config entry migration logic in __init__.py.

Covers:
1. Version 1 → rejected (returns False)
2. Version 2.1 → 2.2: entity registry rename (everyone_away → presence)
3. Already at version 2.2 → no migration needed
4. Migration with no matching entity (fresh install)
5. Migration callback only renames the presence entity, not others
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call

from custom_components.heating_control import async_migrate_entry
from custom_components.heating_control.const import (
    BINARY_SENSOR_EVERYONE_AWAY,
    BINARY_SENSOR_PRESENCE,
)


def _make_config_entry(
    entry_id: str = "test_entry_01",
    version: int = 2,
    minor_version: int = 1,
) -> SimpleNamespace:
    """Create a mock ConfigEntry with version info."""
    return SimpleNamespace(
        entry_id=entry_id,
        version=version,
        minor_version=minor_version,
        data={},
        options={},
    )


def _make_registry_entry(
    entity_id: str,
    unique_id: str,
    config_entry_id: str = "test_entry_01",
) -> SimpleNamespace:
    """Create a mock entity registry RegistryEntry."""
    return SimpleNamespace(
        entity_id=entity_id,
        unique_id=unique_id,
        config_entry_id=config_entry_id,
        id=f"reg_{unique_id}",
    )


# ============================================================================
# VERSION 1 → REJECTED
# ============================================================================


@pytest.mark.asyncio
async def test_version_1_rejected():
    """Version 1 config entries are incompatible and should be rejected."""
    entry = _make_config_entry(version=1, minor_version=0)
    hass = MagicMock()

    result = await async_migrate_entry(hass, entry)

    assert result is False


# ============================================================================
# VERSION 2.1 → 2.2: ENTITY RENAME
# ============================================================================


@pytest.mark.asyncio
async def test_migration_2_1_to_2_2_renames_presence_entity():
    """Migration from 2.1 to 2.2 should rename everyone_away → presence."""
    entry = _make_config_entry(version=2, minor_version=1)
    hass = MagicMock()

    # Track what async_migrate_entries receives
    captured_callback = None

    async def fake_migrate_entries(hass_arg, config_entry_id, cb):
        nonlocal captured_callback
        captured_callback = cb

    with patch(
        "custom_components.heating_control.er.async_migrate_entries",
        side_effect=fake_migrate_entries,
    ):
        result = await async_migrate_entry(hass, entry)

    assert result is True

    # Verify async_update_entry was called to bump minor version
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, minor_version=2
    )

    # Verify the callback renames the correct entity
    assert captured_callback is not None

    old_unique_id = f"test_entry_01_{BINARY_SENSOR_EVERYONE_AWAY}"
    new_unique_id = f"test_entry_01_{BINARY_SENSOR_PRESENCE}"

    # Matching entity → should return rename dict
    matching_entity = _make_registry_entry(
        entity_id="binary_sensor.heating_control_everyone_away",
        unique_id=old_unique_id,
    )
    updates = captured_callback(matching_entity)
    assert updates is not None
    assert updates["new_unique_id"] == new_unique_id
    assert updates["new_entity_id"] == "binary_sensor.heating_control_presence"


@pytest.mark.asyncio
async def test_migration_2_1_to_2_2_ignores_other_entities():
    """Migration callback should return None for non-presence entities."""
    entry = _make_config_entry(version=2, minor_version=1)
    hass = MagicMock()

    captured_callback = None

    async def fake_migrate_entries(hass_arg, config_entry_id, cb):
        nonlocal captured_callback
        captured_callback = cb

    with patch(
        "custom_components.heating_control.er.async_migrate_entries",
        side_effect=fake_migrate_entries,
    ):
        await async_migrate_entry(hass, entry)

    assert captured_callback is not None

    # Schedule entity → should NOT be renamed
    schedule_entity = _make_registry_entry(
        entity_id="binary_sensor.heating_control_schedule_abc123",
        unique_id="test_entry_01_schedule_abc123",
    )
    assert captured_callback(schedule_entity) is None

    # Device entity → should NOT be renamed
    device_entity = _make_registry_entry(
        entity_id="binary_sensor.heating_control_device_bedroom",
        unique_id="test_entry_01_device_bedroom",
    )
    assert captured_callback(device_entity) is None

    # Master switch → should NOT be renamed
    master_entity = _make_registry_entry(
        entity_id="switch.heating_control_master",
        unique_id="test_entry_01_master_enabled",
    )
    assert captured_callback(master_entity) is None


@pytest.mark.asyncio
async def test_migration_2_1_to_2_2_no_matching_entity():
    """Migration should succeed even if the old entity doesn't exist (fresh install)."""
    entry = _make_config_entry(version=2, minor_version=1)
    hass = MagicMock()

    captured_callback = None

    async def fake_migrate_entries(hass_arg, config_entry_id, cb):
        nonlocal captured_callback
        captured_callback = cb

    with patch(
        "custom_components.heating_control.er.async_migrate_entries",
        side_effect=fake_migrate_entries,
    ):
        result = await async_migrate_entry(hass, entry)

    # Migration should still succeed
    assert result is True

    # Version should still be bumped
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry, minor_version=2
    )

    # Callback returns None for entities that don't match
    assert captured_callback is not None
    unrelated = _make_registry_entry(
        entity_id="sensor.something_else",
        unique_id="some_other_unique_id",
    )
    assert captured_callback(unrelated) is None


# ============================================================================
# ALREADY AT VERSION 2.2 → NO MIGRATION
# ============================================================================


@pytest.mark.asyncio
async def test_already_at_2_2_no_migration():
    """Config entry already at 2.2 should not trigger any migration."""
    entry = _make_config_entry(version=2, minor_version=2)
    hass = MagicMock()

    with patch(
        "custom_components.heating_control.er.async_migrate_entries",
    ) as mock_migrate:
        result = await async_migrate_entry(hass, entry)

    assert result is True

    # async_migrate_entries should NOT have been called
    mock_migrate.assert_not_called()

    # async_update_entry should NOT have been called
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_future_minor_version_no_migration():
    """Config entry at a future minor version (e.g. 2.3) should not trigger migration."""
    entry = _make_config_entry(version=2, minor_version=3)
    hass = MagicMock()

    with patch(
        "custom_components.heating_control.er.async_migrate_entries",
    ) as mock_migrate:
        result = await async_migrate_entry(hass, entry)

    assert result is True
    mock_migrate.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()


# ============================================================================
# EDGE CASES
# ============================================================================


@pytest.mark.asyncio
async def test_migration_passes_correct_entry_id():
    """Migration should pass the config entry ID to async_migrate_entries."""
    entry = _make_config_entry(entry_id="my_custom_entry_id", version=2, minor_version=1)
    hass = MagicMock()

    with patch(
        "custom_components.heating_control.er.async_migrate_entries",
        new_callable=AsyncMock,
    ) as mock_migrate:
        await async_migrate_entry(hass, entry)

    # Verify the correct entry_id was passed
    mock_migrate.assert_called_once()
    call_args = mock_migrate.call_args
    assert call_args[0][1] == "my_custom_entry_id"


@pytest.mark.asyncio
async def test_migration_callback_uses_entry_id_in_unique_ids():
    """Migration callback should use the actual entry_id for unique_id matching."""
    custom_entry_id = "01ABCDEF"
    entry = _make_config_entry(entry_id=custom_entry_id, version=2, minor_version=1)
    hass = MagicMock()

    captured_callback = None

    async def fake_migrate_entries(hass_arg, config_entry_id, cb):
        nonlocal captured_callback
        captured_callback = cb

    with patch(
        "custom_components.heating_control.er.async_migrate_entries",
        side_effect=fake_migrate_entries,
    ):
        await async_migrate_entry(hass, entry)

    assert captured_callback is not None

    # Should match with the custom entry_id
    matching = _make_registry_entry(
        entity_id="binary_sensor.heating_control_everyone_away",
        unique_id=f"{custom_entry_id}_{BINARY_SENSOR_EVERYONE_AWAY}",
    )
    updates = captured_callback(matching)
    assert updates is not None
    assert updates["new_unique_id"] == f"{custom_entry_id}_{BINARY_SENSOR_PRESENCE}"

    # Should NOT match with a different entry_id
    wrong_entry = _make_registry_entry(
        entity_id="binary_sensor.heating_control_everyone_away",
        unique_id=f"other_entry_{BINARY_SENSOR_EVERYONE_AWAY}",
    )
    assert captured_callback(wrong_entry) is None

