"""The Heating Control integration with enhanced logging and error handling."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import HeatingControlCoordinator
from .dashboard import SUPPORTS_DASHBOARD_STRATEGY

_LOGGER = logging.getLogger(__name__)

# Config entry version for migrations
CONFIG_VERSION = 2
CONFIG_MINOR_VERSION = 1

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

SERVICES_REGISTERED_KEY = f"{DOMAIN}_services_registered"
FRONTEND_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"
WS_REGISTERED_KEY = f"{DOMAIN}_ws_registered"

FRONTEND_STATIC_PATH = f"/{DOMAIN}-frontend"
FRONTEND_STRATEGY_SCRIPT = "dashboard-strategy.js"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heating Control from a config entry."""
    try:
        # Initialize coordinator
        coordinator = HeatingControlCoordinator(hass, entry)
        
        # Set up event listeners for real-time updates
        await coordinator._setup_event_listeners()
        
        # Perform initial data fetch
        await coordinator.async_config_entry_first_refresh()
        
        # Store coordinator
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        
        # Set up platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        # Register services
        await _register_services(hass)
        
        # Set up dashboard
        await _setup_dashboard(hass, entry)
        
        # Set up entry update listener
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
        
        _LOGGER.info("Heating Control integration setup complete")
        return True
        
    except Exception as e:
        _LOGGER.error("Failed to set up Heating Control: %s", e)
        return False

async def _validate_config_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Validate configuration entry."""
    config = entry.options or entry.data
    
    # Validate climate devices exist
    climate_devices = config.get("climate_devices", [])
    for device_id in climate_devices:
        if not hass.states.get(device_id):
            _LOGGER.warning("Climate device %s not found", device_id)
    
    # Validate device trackers exist
    device_trackers = config.get("device_trackers", [])
    for tracker_id in device_trackers:
        if tracker_id and not hass.states.get(tracker_id):
            _LOGGER.warning("Device tracker %s not found", tracker_id)
    
    return True

async def _register_services(hass: HomeAssistant):
    """Register integration services."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE_ENABLED):
        return  # Already registered
        
    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv
    
    async def set_schedule_enabled(call):
        """Service to enable/disable schedules."""
        entry_id = call.data.get("entry_id")
        schedule_id = call.data.get("schedule_id")
        schedule_name = call.data.get("schedule_name")
        enabled = call.data.get("enabled", True)
        
        # Find the coordinator
        coordinator = None
        if entry_id:
            coordinator = hass.data[DOMAIN].get(entry_id)
        else:
            # Find first coordinator if no entry_id specified
            for coord in hass.data[DOMAIN].values():
                if hasattr(coord, 'config_entry'):
                    coordinator = coord
                    break
        
        if not coordinator:
            _LOGGER.error("No heating control coordinator found")
            return
        
        # Find and update schedule
        config = coordinator.config_entry.options or coordinator.config_entry.data
        schedules = config.get(CONF_SCHEDULES, [])
        
        for schedule in schedules:
            if (schedule_id and schedule.get(CONF_SCHEDULE_ID) == schedule_id) or \
               (schedule_name and schedule.get(CONF_SCHEDULE_NAME) == schedule_name):
                schedule[CONF_SCHEDULE_ENABLED] = enabled
                break
        else:
            _LOGGER.error("Schedule not found: %s", schedule_id or schedule_name)
            return
        
        # Update config entry
        hass.config_entries.async_update_entry(
            coordinator.config_entry,
            options={**config, CONF_SCHEDULES: schedules}
        )
        
        # Force update
        coordinator.force_update_on_next_refresh()
        await coordinator.async_request_refresh()
        
        _LOGGER.info("Schedule %s %s", schedule_id or schedule_name, 
                    "enabled" if enabled else "disabled")
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE_ENABLED,
        set_schedule_enabled,
        schema=vol.Schema({
            vol.Optional("entry_id"): cv.string,
            vol.Optional("schedule_id"): cv.string,
            vol.Optional("schedule_name"): cv.string,
            vol.Required("enabled"): cv.boolean,
        })
    )

async def _setup_dashboard(hass: HomeAssistant, entry: ConfigEntry):
    """Set up dashboard with comprehensive error handling."""
    try:
        from .dashboard import HeatingControlDashboardStrategy
        
        # Check if dashboard strategy is supported
        if not hasattr(hass.components, 'lovelace') or \
           not hasattr(hass.components.lovelace, 'dashboard'):
            _LOGGER.info("Dashboard strategy not supported in this Home Assistant version")
            return
        
        strategy = HeatingControlDashboardStrategy()
        dashboard_config = await strategy.async_generate_dashboard(hass, entry)
        
        if dashboard_config:
            dashboard_url = f"/dashboard/heating-control-{entry.entry_id}"
            
            # Create dashboard
            await hass.components.lovelace.async_create_dashboard(
                url_path=f"heating-control-{entry.entry_id}",
                require_admin=False,
                sidebar_title="Heating Control",
                sidebar_icon="mdi:thermostat",
                config=dashboard_config
            )
            
            # Store dashboard URL in config entry data
            new_data = {**(entry.data or {}), "dashboard_url": dashboard_url}
            hass.config_entries.async_update_entry(entry, data=new_data)
            
            _LOGGER.info("Dashboard created at %s", dashboard_url)
        
    except ImportError:
        _LOGGER.info("Dashboard components not available")
    except Exception as e:
        _LOGGER.warning("Failed to create dashboard: %s", e)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        # Unload platforms
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        
        if unload_ok:
            # Remove coordinator
            coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
            if coordinator:
                # Clean up any resources
                coordinator._circuit_breaker_active = False
                coordinator._presence_cache = None
            
            # Remove dashboard if it exists
            dashboard_url = entry.data.get("dashboard_url")
            if dashboard_url:
                try:
                    dashboard_id = dashboard_url.split("/")[-1]
                    await hass.components.lovelace.async_delete_dashboard(dashboard_id)
                    _LOGGER.info("Dashboard removed: %s", dashboard_url)
                except Exception as e:
                    _LOGGER.warning("Failed to remove dashboard: %s", e)
            
            # Remove services if no more entries
            if not hass.data[DOMAIN]:
                hass.services.async_remove(DOMAIN, SERVICE_SET_SCHEDULE_ENABLED)
                hass.data.pop(DOMAIN, None)
        
        return unload_ok
        
    except Exception as e:
        _LOGGER.error("Failed to unload Heating Control: %s", e)
        return False


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def _async_setup_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Auto-create a dashboard for easy access to heating controls."""
    generated_config: Optional[dict[str, Any]] = None

    if not SUPPORTS_DASHBOARD_STRATEGY:
        _LOGGER.debug(
            "Lovelace strategies unavailable; generating storage-mode dashboard for %s",
            entry.entry_id,
        )
        try:
            from .dashboard import HeatingControlDashboardStrategy

            strategy = HeatingControlDashboardStrategy(
                hass, {"entry_id": entry.entry_id}
            )
            generated_config = await strategy.async_generate()
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning(
                "Failed to generate fallback dashboard for entry %s: %s",
                entry.entry_id,
                err,
            )
            return
        if not isinstance(generated_config, dict) or "views" not in generated_config:
            _LOGGER.warning(
                "Generated fallback dashboard invalid for entry %s; skipping",
                entry.entry_id,
            )
            return

    dashboard_url = entry.data.get(DASHBOARD_CREATED_KEY)
    url_path = dashboard_url or DASHBOARD_URL_PATH_TEMPLATE.format(
        entry_id=entry.entry_id[:DASHBOARD_ENTRY_ID_LENGTH]
    )

    if not dashboard_url:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, DASHBOARD_CREATED_KEY: url_path},
        )
        _LOGGER.info(
            "Preparing auto-generated '%s' dashboard at /%s",
            DASHBOARD_TITLE,
            url_path,
        )
    else:
        _LOGGER.debug("Dashboard already recorded at %s", url_path)

    try:
        await _async_register_lovelace_dashboard(
            hass,
            url_path,
            entry.entry_id,
            created_dashboard=dashboard_url is None,
            generated_config=generated_config,
        )
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warning(
            "Failed to set up Lovelace dashboard (non-critical): %s",
            err,
        )


async def _async_setup_frontend(hass: HomeAssistant) -> None:
    """Expose frontend resources for the dashboard strategy."""
    if not SUPPORTS_DASHBOARD_STRATEGY:
        return

    if hass.data.get(FRONTEND_REGISTERED_KEY):
        return

    frontend_dir = Path(__file__).parent / "frontend"
    if not frontend_dir.exists():
        _LOGGER.debug(
            "Frontend directory %s is missing; skipping strategy asset registration",
            frontend_dir,
        )
        return

    if StaticPathConfig is None:
        _LOGGER.debug(
            "Static path registration unavailable; skipping strategy asset exposure"
        )
        return

    try:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    FRONTEND_STATIC_PATH,
                    str(frontend_dir),
                    cache_headers=False,
                )
            ]
        )
        frontend.add_extra_js_url(
            hass, f"{FRONTEND_STATIC_PATH}/{FRONTEND_STRATEGY_SCRIPT}"
        )
    except Exception:  # pylint: disable=broad-except
        hass.data.pop(FRONTEND_REGISTERED_KEY, None)
        raise

    hass.data[FRONTEND_REGISTERED_KEY] = True


def _teardown_frontend(hass: HomeAssistant) -> None:
    """Remove registered frontend resources when no entries remain."""
    if not SUPPORTS_DASHBOARD_STRATEGY:
        return

    if not hass.data.pop(FRONTEND_REGISTERED_KEY, None):
        return

    frontend.remove_extra_js_url(
        hass, f"{FRONTEND_STATIC_PATH}/{FRONTEND_STRATEGY_SCRIPT}"
    )


async def _async_register_ws_api(hass: HomeAssistant) -> None:
    """Register websocket handlers for dashboard generation."""
    if not SUPPORTS_DASHBOARD_STRATEGY:
        return

    if hass.data.get(WS_REGISTERED_KEY):
        return

    hass.data[WS_REGISTERED_KEY] = True

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/generate_dashboard",
            vol.Optional("config", default={}): dict,
        }
    )
    @websocket_api.async_response
    async def websocket_generate_dashboard(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Return the generated dashboard for the requested config."""
        config: dict[str, Any] = dict(msg["config"] or {})
        config.pop("type", None)
        from .dashboard import HeatingControlDashboardStrategy

        strategy = HeatingControlDashboardStrategy(hass, config)

        try:
            dashboard_config = await strategy.async_generate()
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error(
                "Failed to generate Heating Control dashboard via websocket: %s",
                err,
                exc_info=True,
            )
            connection.send_error(
                msg["id"], "dashboard_generation_failed", str(err)
            )
            return

        connection.send_result(msg["id"], dashboard_config)

    try:
        websocket_api.async_register_command(hass, websocket_generate_dashboard)
    except Exception:  # pylint: disable=broad-except
        hass.data.pop(WS_REGISTERED_KEY, None)
        raise


async def _async_register_lovelace_dashboard(
    hass: HomeAssistant,
    url_path: str,
    entry_id: str,
    *,
    created_dashboard: bool,
    generated_config: Optional[dict[str, Any]] = None,
) -> None:
    """Ensure the auto-created dashboard is registered with Lovelace."""
    from homeassistant.components.lovelace import dashboard as lovelace_dashboard
    from homeassistant.components.lovelace import const as lovelace_const

    lovelace_data = hass.data.get(lovelace_const.LOVELACE_DATA)
    if lovelace_data is None:
        _LOGGER.debug(
            "Lovelace not initialised; skipping dashboard registration for %s",
            url_path,
        )
        return

    try:
        dashboards_collection = lovelace_dashboard.DashboardsCollection(hass)
        await dashboards_collection.async_load()
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warning(
            "Unable to load Lovelace dashboards; skipping auto-registration: %s",
            err,
        )
        return

    desired_fields = {
        lovelace_const.CONF_TITLE: DASHBOARD_TITLE,
        lovelace_const.CONF_ICON: DASHBOARD_ICON,
        lovelace_const.CONF_SHOW_IN_SIDEBAR: True,
        lovelace_const.CONF_REQUIRE_ADMIN: False,
    }

    dashboard_item: Optional[dict[str, Any]] = None
    existing_item_id: Optional[str] = None
    for item in dashboards_collection.data.values():
        if item.get(lovelace_const.CONF_URL_PATH) == url_path:
            dashboard_item = item
            existing_item_id = item["id"]
            break

    created_item = False
    if dashboard_item is None:
        try:
            dashboard_item = await dashboards_collection.async_create_item(
                {
                    lovelace_const.CONF_URL_PATH: url_path,
                    lovelace_const.CONF_TITLE: DASHBOARD_TITLE,
                    lovelace_const.CONF_ICON: DASHBOARD_ICON,
                    lovelace_const.CONF_SHOW_IN_SIDEBAR: True,
                    lovelace_const.CONF_REQUIRE_ADMIN: False,
                    lovelace_const.CONF_ALLOW_SINGLE_WORD: True,
                }
            )
            _LOGGER.debug("Created Lovelace dashboard entry for %s", url_path)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning(
                "Could not create Lovelace dashboard entry for %s: %s",
                    url_path,
                    err,
                )
            return
        created_item = True
        existing_item_id = dashboard_item["id"]
    else:
        updates: dict[str, Any] = {
            key: value
            for key, value in desired_fields.items()
            if dashboard_item.get(key) != value
        }
        if updates:
            try:
                dashboard_item = await dashboards_collection.async_update_item(
                    existing_item_id, updates
                )
                _LOGGER.debug(
                    "Updated Lovelace dashboard metadata for %s with %s",
                    url_path,
                    updates,
                )
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.warning(
                    "Could not update Lovelace dashboard entry for %s: %s",
                    url_path,
                    err,
                )

    if dashboard_item is None:
        return

    existing_dashboard = lovelace_data.dashboards.get(url_path)
    if isinstance(existing_dashboard, lovelace_dashboard.LovelaceStorage):
        existing_dashboard.config = dashboard_item
        dashboard_store = existing_dashboard
    else:
        dashboard_store = lovelace_dashboard.LovelaceStorage(hass, dashboard_item)
        lovelace_data.dashboards[url_path] = dashboard_store

    if generated_config is None:
        desired_config: dict[str, Any] = {
            "strategy": {
                "type": f"custom:{DOMAIN}-smart-heating",
                "entry_id": entry_id,
            }
        }
    else:
        desired_config = generated_config
    should_save_config = True

    try:
        current_config = await dashboard_store.async_load(False)
    except lovelace_dashboard.ConfigNotFound:
        current_config = None
    except HomeAssistantError as err:  # pylint: disable=broad-except
        _LOGGER.debug(
            "Lovelace dashboard '%s' config not yet available (%s), overwriting",
            url_path,
            err,
        )
        current_config = None

    if isinstance(current_config, dict):
        if current_config == desired_config:
            should_save_config = False
        else:
            _LOGGER.debug(
                "Replacing Lovelace dashboard '%s' config with Heating Control strategy",
                url_path,
            )

    if should_save_config:
        await dashboard_store.async_save(desired_config)
        _LOGGER.debug("Saved strategy config for Lovelace dashboard '%s'", url_path)

    panel_kwargs = {
        "frontend_url_path": url_path,
        "require_admin": dashboard_item.get(
            lovelace_const.CONF_REQUIRE_ADMIN, False
        ),
        "config": {"mode": lovelace_const.MODE_STORAGE},
        "update": not created_item,
    }

    if dashboard_item.get(lovelace_const.CONF_SHOW_IN_SIDEBAR, True):
        panel_kwargs["sidebar_title"] = dashboard_item.get(
            lovelace_const.CONF_TITLE, DASHBOARD_TITLE
        )
        panel_kwargs["sidebar_icon"] = dashboard_item.get(
            lovelace_const.CONF_ICON, DASHBOARD_ICON
        )

    try:
        frontend.async_register_built_in_panel(
            hass,
            lovelace_const.DOMAIN,
            **panel_kwargs,
        )
    except ValueError as err:
        _LOGGER.debug(
            "Panel registration skipped for %s (likely already registered): %s",
            url_path,
            err,
        )
        return

    if created_dashboard or created_item:
        _LOGGER.info("Registered Lovelace dashboard at /%s", url_path)
    else:
        _LOGGER.debug("Ensured Lovelace dashboard is registered at /%s", url_path)


async def _async_remove_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove auto-created dashboard when integration is uninstalled."""
    dashboard_url = entry.data.get(DASHBOARD_CREATED_KEY)

    if not dashboard_url:
        # No dashboard was auto-created
        return

    # Remove Lovelace dashboard registry entry and sidebar panel
    try:
        from homeassistant.components.lovelace import (
            const as lovelace_const,
            dashboard as lovelace_dashboard,
        )

        dashboards_collection = lovelace_dashboard.DashboardsCollection(hass)
        await dashboards_collection.async_load()

        # Locate the dashboard entry by url_path
        item_id = None
        for item in dashboards_collection.data.values():
            if item.get(lovelace_const.CONF_URL_PATH) == dashboard_url:
                item_id = item.get("id")
                break

        if item_id:
            await dashboards_collection.async_delete_item(item_id)
            _LOGGER.debug("Deleted Lovelace dashboard registry entry %s", item_id)

        # Remove the built-in panel if present
        frontend.async_remove_panel(hass, dashboard_url)
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug(
            "Dashboard registry/panel removal failed for %s (non-critical): %s",
            dashboard_url,
            err,
        )

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
    storage_dir = Path(hass.config.path(".storage"))
    dashboard_file = storage_dir / f"lovelace.{url_path}"

    if dashboard_file.exists():
        dashboard_file.unlink()
        _LOGGER.debug("Removed dashboard file: %s", dashboard_file)


async def _async_refresh_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Trigger dashboard refresh after configuration changes."""
    dashboard_url = entry.data.get(DASHBOARD_CREATED_KEY)

    if not dashboard_url:
        _LOGGER.debug("No dashboard URL found for entry %s, skipping refresh", entry.entry_id)
        return

    try:
        # Fire event to notify frontend that dashboard should be refreshed
        hass.bus.async_fire(
            "lovelace_updated",
            {"url_path": dashboard_url},
        )
        _LOGGER.debug("Fired lovelace_updated event for dashboard %s", dashboard_url)

        # Also fire a custom event for any listeners
        hass.bus.async_fire(
            f"{DOMAIN}_dashboard_updated",
            {
                "entry_id": entry.entry_id,
                "dashboard_url": dashboard_url,
            },
        )
        _LOGGER.info("Dashboard refresh triggered for %s", dashboard_url)
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warning("Failed to trigger dashboard refresh (non-critical): %s", err)


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
