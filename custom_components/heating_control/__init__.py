"""The Heating Control integration."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import voluptuous as vol

from homeassistant.components import frontend, websocket_api
try:  # Home Assistant 2024.4+ exposes StaticPathConfig
    from homeassistant.components.http import StaticPathConfig
except ImportError:  # pragma: no cover - older HA cores
    StaticPathConfig = None  # type: ignore[assignment]
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
    DASHBOARD_ENTRY_ID_LENGTH,
    DASHBOARD_ICON,
    DASHBOARD_TITLE,
    DASHBOARD_URL_PATH_TEMPLATE,
    DOMAIN,
    SERVICE_SET_SCHEDULE_ENABLED,
)
from .coordinator import HeatingControlCoordinator
from .dashboard import SUPPORTS_DASHBOARD_STRATEGY

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

SERVICES_REGISTERED_KEY = f"{DOMAIN}_services_registered"
FRONTEND_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"
WS_REGISTERED_KEY = f"{DOMAIN}_ws_registered"

FRONTEND_STATIC_PATH = f"/{DOMAIN}-frontend"
FRONTEND_STRATEGY_SCRIPT = "dashboard-strategy.js"

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
    if SUPPORTS_DASHBOARD_STRATEGY:
        await _async_register_ws_api(hass)
        await _async_setup_frontend(hass)

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
                if SUPPORTS_DASHBOARD_STRATEGY:
                    _teardown_frontend(hass)
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
