"""The Heating Control integration."""
from __future__ import annotations

import logging
from typing import Optional

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ENTRY_ID,
    ATTR_SCHEDULE_ID,
    ATTR_SCHEDULE_NAME,
    CONF_SCHEDULE_ENABLED,
    DASHBOARD_CREATED_KEY,
    DASHBOARD_ICON,
    DASHBOARD_TITLE,
    DASHBOARD_URL_PATH_TEMPLATE,
    DOMAIN,
    SERVICE_SET_SCHEDULE_ENABLED,
)
from .coordinator import HeatingControlCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

SERVICES_REGISTERED_KEY = f"{DOMAIN}_services_registered"

SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(ATTR_SCHEDULE_ID): cv.string,
        vol.Optional(ATTR_SCHEDULE_NAME): cv.string,
        vol.Required(CONF_SCHEDULE_ENABLED): cv.boolean,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heating Control from a config entry."""
    coordinator = HeatingControlCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Auto-create dashboard if it doesn't exist
    await _async_setup_dashboard(hass, entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_store = hass.data.get(DOMAIN)
        if entry_store is not None:
            entry_store.pop(entry.entry_id, None)
            if not entry_store:
                await _async_unregister_services(hass)
                hass.data.pop(DOMAIN, None)

        # Remove auto-created dashboard (optional - keeps dashboard for user)
        # Uncomment the following line if you want to remove dashboard on uninstall
        # await _async_remove_dashboard(hass, entry)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry options update by reloading the entry."""
    _LOGGER.info("Configuration updated, reloading Heating Control entry")
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_setup_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Auto-create a dashboard for easy access to heating controls."""
    # Check if we've already created a dashboard for this entry
    dashboard_url = entry.data.get(DASHBOARD_CREATED_KEY)

    if dashboard_url:
        # Dashboard already created, don't recreate
        _LOGGER.debug("Dashboard already exists at %s", dashboard_url)
        return

    # Generate unique URL path for this entry
    url_path = DASHBOARD_URL_PATH_TEMPLATE.format(entry_id=entry.entry_id[:8])

    try:
        # Use Home Assistant's lovelace integration to create dashboard
        await hass.async_add_executor_job(
            _create_dashboard_sync,
            hass,
            url_path,
            entry.entry_id,
        )

        # Store the dashboard URL in entry data
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, DASHBOARD_CREATED_KEY: url_path},
        )

        _LOGGER.info(
            "Auto-created '%s' dashboard at /%s",
            DASHBOARD_TITLE,
            url_path,
        )
    except Exception as err:  # pylint: disable=broad-except
        # Don't fail setup if dashboard creation fails
        _LOGGER.warning(
            "Failed to auto-create dashboard (non-critical): %s",
            err,
        )


def _create_dashboard_sync(
    hass: HomeAssistant,
    url_path: str,
    entry_id: str,
) -> None:
    """Create dashboard synchronously (runs in executor)."""
    import json
    from pathlib import Path

    # Path to lovelace storage
    storage_dir = Path(hass.config.path(".storage"))
    dashboard_file = storage_dir / f"lovelace.{url_path}"

    # Check if dashboard file already exists
    if dashboard_file.exists():
        _LOGGER.debug("Dashboard file already exists: %s", dashboard_file)
    else:
        # Create dashboard configuration
        dashboard_config = {
            "version": 1,
            "minor_version": 1,
            "key": url_path,
            "data": {
                "config": {
                    "strategy": {
                        "type": f"custom:{DOMAIN}-smart-heating",
                        "entry_id": entry_id,
                    }
                },
                "title": DASHBOARD_TITLE,
                "icon": DASHBOARD_ICON,
                "show_in_sidebar": True,
                "require_admin": False,
            },
        }

        # Write dashboard configuration
        storage_dir.mkdir(parents=True, exist_ok=True)
        with dashboard_file.open("w", encoding="utf-8") as f:
            json.dump(dashboard_config, f, indent=2)

        _LOGGER.debug("Created dashboard file: %s", dashboard_file)

    # Ensure the dashboard is registered so it shows up in the sidebar
    dashboards_file = storage_dir / "lovelace_dashboards"
    dashboards_data = {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_dashboards",
        "data": {"items": {}},
    }

    if dashboards_file.exists():
        try:
            with dashboards_file.open("r", encoding="utf-8") as f:
                dashboards_data = json.load(f)
        except json.JSONDecodeError as err:
            _LOGGER.warning(
                "Failed to read existing lovelace_dashboards file (%s), recreating: %s",
                dashboards_file,
                err,
            )

    items = dashboards_data.setdefault("data", {}).setdefault("items", {})

    desired = {
        "mode": "storage",
        "filename": f"lovelace.{url_path}",
        "title": DASHBOARD_TITLE,
        "icon": DASHBOARD_ICON,
        "show_in_sidebar": True,
        "require_admin": False,
        "url_path": url_path,
    }

    dashboard_id = f"{DOMAIN}_{entry_id[:8]}"
    existing_id: Optional[str] = None

    for item_id, item in items.items():
        if item.get("filename") == desired["filename"] or item.get("url_path") == url_path:
            existing_id = item_id
            break

    changed = False
    new_entry = False
    if existing_id:
        existing = items[existing_id]
        if any(existing.get(k) != v for k, v in desired.items()):
            existing.update(desired)
            changed = True
    else:
        # Use stable identifier so we can find/update on subsequent runs
        items[dashboard_id] = desired
        existing_id = dashboard_id
        changed = True
        new_entry = True

    if changed:
        with dashboards_file.open("w", encoding="utf-8") as f:
            json.dump(dashboards_data, f, indent=2)
        _LOGGER.debug(
            "%s dashboard '%s' in lovelace_dashboards",
            "Registered" if new_entry else "Updated",
            url_path,
        )
    else:
        _LOGGER.debug(
            "Dashboard '%s' already registered in lovelace_dashboards", url_path
        )


async def _async_remove_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove auto-created dashboard when integration is uninstalled."""
    dashboard_url = entry.data.get(DASHBOARD_CREATED_KEY)

    if not dashboard_url:
        # No dashboard was auto-created
        return

    try:
        await hass.async_add_executor_job(
            _remove_dashboard_sync,
            hass,
            dashboard_url,
        )
        _LOGGER.info("Removed auto-created dashboard at /%s", dashboard_url)
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warning("Failed to remove dashboard (non-critical): %s", err)


def _remove_dashboard_sync(hass: HomeAssistant, url_path: str) -> None:
    """Remove dashboard file synchronously (runs in executor)."""
    from pathlib import Path

    storage_dir = Path(hass.config.path(".storage"))
    dashboard_file = storage_dir / f"lovelace.{url_path}"

    if dashboard_file.exists():
        dashboard_file.unlink()
        _LOGGER.debug("Removed dashboard file: %s", dashboard_file)


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.data.get(SERVICES_REGISTERED_KEY):
        return

    async def async_handle_set_schedule_enabled(call: ServiceCall) -> None:
        """Enable or disable a Heating Control schedule."""
        entry_id: Optional[str] = call.data.get(ATTR_ENTRY_ID)
        schedule_id: Optional[str] = call.data.get(ATTR_SCHEDULE_ID)
        schedule_name: Optional[str] = call.data.get(ATTR_SCHEDULE_NAME)
        enabled: bool = call.data[CONF_SCHEDULE_ENABLED]

        if not schedule_id and not schedule_name:
            raise HomeAssistantError("Provide either schedule_id or schedule_name")

        coordinator = _resolve_coordinator_for_service(hass, entry_id)

        try:
            await coordinator.async_set_schedule_enabled(
                schedule_id=schedule_id,
                schedule_name=schedule_name,
                enabled=enabled,
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE_ENABLED,
        async_handle_set_schedule_enabled,
        schema=SET_SCHEDULE_SCHEMA,
    )
    hass.data[SERVICES_REGISTERED_KEY] = True


async def _async_unregister_services(hass: HomeAssistant) -> None:
    """Remove integration services when no entries remain."""
    if not hass.data.get(SERVICES_REGISTERED_KEY):
        return

    if hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE_ENABLED):
        hass.services.async_remove(DOMAIN, SERVICE_SET_SCHEDULE_ENABLED)

    hass.data.pop(SERVICES_REGISTERED_KEY, None)


def _resolve_coordinator_for_service(
    hass: HomeAssistant, entry_id: Optional[str]
) -> HeatingControlCoordinator:
    """Return the coordinator to use for a service call."""
    domain_data = hass.data.get(DOMAIN)

    if not domain_data:
        raise HomeAssistantError("No Heating Control entries are configured")

    if entry_id:
        coordinator = domain_data.get(entry_id)
        if coordinator is None:
            raise HomeAssistantError(
                f"Heating Control entry '{entry_id}' was not found"
            )
        return coordinator

    if len(domain_data) == 1:
        return next(iter(domain_data.values()))

    raise HomeAssistantError(
        "Multiple Heating Control entries exist; set entry_id in the service call"
    )
