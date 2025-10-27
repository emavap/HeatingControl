"""The Heating Control integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HeatingControlCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heating Control from a config entry."""
    coordinator = HeatingControlCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry options update.

    Instead of fully reloading, we force the coordinator to apply
    the new configuration on next update cycle.
    """
    coordinator = hass.data[DOMAIN].get(entry.entry_id)

    if coordinator:
        _LOGGER.info("Configuration updated, forcing control application on next refresh")
        # Force update on next refresh to apply new config immediately
        coordinator.force_update_on_next_refresh()
        # Trigger immediate refresh
        await coordinator.async_request_refresh()
    else:
        # Fallback to full reload if coordinator not found
        _LOGGER.warning("Coordinator not found, performing full reload")
        await async_unload_entry(hass, entry)
        await async_setup_entry(hass, entry)
