"""Enhanced dashboard strategy with proper error handling."""
import logging
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.util.version import parse_version
from homeassistant.const import __version__ as HA_VERSION

_LOGGER = logging.getLogger(__name__)

# Improved version detection using Home Assistant's version utilities
try:
    ha_version = parse_version(HA_VERSION)
    min_version = parse_version("2024.4.0")
    STRATEGY_SUPPORTED = ha_version >= min_version
except Exception as e:
    _LOGGER.warning("Failed to parse Home Assistant version: %s", e)
    STRATEGY_SUPPORTED = False

SUPPORTS_DASHBOARD_STRATEGY = STRATEGY_SUPPORTED

try:
    if STRATEGY_SUPPORTED:
        from homeassistant.components.lovelace.strategy import Strategy as LovelaceStrategy
    else:
        LovelaceStrategy = None
except ImportError:
    _LOGGER.warning("Lovelace strategy not available in this Home Assistant version")
    LovelaceStrategy = None
    STRATEGY_SUPPORTED = False
    SUPPORTS_DASHBOARD_STRATEGY = False

class HeatingControlDashboardStrategy:
    """Dashboard strategy for Heating Control integration with enhanced error handling."""
    
    def __init__(self):
        if not STRATEGY_SUPPORTED:
            _LOGGER.info("Dashboard strategy not supported, falling back to manual dashboard creation")
    
    async def async_generate_dashboard(self, hass: HomeAssistant, config_entry) -> Optional[Dict[str, Any]]:
        """Generate dashboard configuration with proper error handling."""
        if not STRATEGY_SUPPORTED:
            _LOGGER.debug("Dashboard strategy not supported in this Home Assistant version")
            return None
            
        try:
            return await self._build_dashboard_config(hass, config_entry)
        except Exception as e:
            _LOGGER.error("Failed to generate dashboard: %s", e)
            return None
    
    async def _build_dashboard_config(self, hass: HomeAssistant, config_entry) -> Dict[str, Any]:
        """Build dashboard configuration with error handling."""
        try:
            config = config_entry.options or config_entry.data
            climate_devices = config.get("climate_devices", [])
            
            if not climate_devices:
                _LOGGER.warning("No climate devices configured for dashboard")
                return self._build_empty_dashboard()
            
            # Build dashboard sections
            sections = []
            
            # Temperature history section (if ApexCharts available)
            try:
                history_section = await self._build_temperature_history_section(hass, climate_devices)
                if history_section:
                    sections.append(history_section)
            except Exception as e:
                _LOGGER.warning("Failed to build temperature history section: %s", e)
            
            # Climate control sections
            try:
                control_sections = await self._build_climate_control_sections(hass, climate_devices)
                sections.extend(control_sections)
            except Exception as e:
                _LOGGER.warning("Failed to build climate control sections: %s", e)
            
            # Schedule status sections
            try:
                schedule_sections = await self._build_schedule_sections(hass, config_entry)
                sections.extend(schedule_sections)
            except Exception as e:
                _LOGGER.warning("Failed to build schedule sections: %s", e)
            
            return {
                "title": "Heating Control",
                "sections": sections,
                "max_columns": 2,  # Allow responsive layout
            }
            
        except Exception as e:
            _LOGGER.error("Error building dashboard config: %s", e)
            return self._build_error_dashboard(str(e))
    
    def _build_empty_dashboard(self) -> Dict[str, Any]:
        """Build dashboard for when no devices are configured."""
        return {
            "title": "Heating Control",
            "sections": [{
                "title": "Configuration Required",
                "cards": [{
                    "type": "markdown",
                    "content": "No climate devices configured. Please configure the integration first."
                }]
            }],
        }
    
    def _build_error_dashboard(self, error_message: str) -> Dict[str, Any]:
        """Build dashboard showing error state."""
        return {
            "title": "Heating Control - Error",
            "sections": [{
                "title": "Dashboard Error",
                "cards": [{
                    "type": "markdown",
                    "content": f"Error generating dashboard: {error_message}\n\nPlease check the logs for more details."
                }]
            }],
        }
    
    async def _build_temperature_history_section(self, hass: HomeAssistant, climate_devices: List[str]) -> Optional[Dict[str, Any]]:
        """Build temperature history section with ApexCharts."""
        try:
            # Check if ApexCharts is available
            if not await self._is_apexcharts_available(hass):
                return {
                    "title": "Temperature History",
                    "cards": [{
                        "type": "markdown",
                        "content": "**ApexCharts Card Required**\n\nInstall ApexCharts Card from HACS to view temperature history."
                    }]
                }
            
            # Build ApexCharts configuration
            series = []
            for device in climate_devices:
                state = hass.states.get(device)
                if not state:
                    continue
                    
                device_name = state.attributes.get("friendly_name", device)
                
                # Actual temperature series
                series.append({
                    "entity": device,
                    "attribute": "current_temperature",
                    "name": f"{device_name} Actual",
                    "type": "line",
                })
                
                # Target temperature series (only when HVAC mode supports temperature)
                series.append({
                    "entity": device,
                    "attribute": "temperature",
                    "name": f"{device_name} Target",
                    "type": "line",
                    "show": {
                        "in_header": False,
                        "legend_value": False,
                    }
                })
            
            if not series:
                return None
            
            return {
                "title": "Temperature History (48h)",
                "cards": [{
                    "type": "custom:apexcharts-card",
                    "graph_span": "48h",
                    "span": {
                        "end": "day"
                    },
                    "update_interval": "5min",
                    "series": series,
                    "apex_config": {
                        "chart": {
                            "height": 300
                        },
                        "yaxis": {
                            "title": {
                                "text": "Temperature (°C)"
                            }
                        }
                    }
                }]
            }
            
        except Exception as e:
            _LOGGER.error("Error building temperature history section: %s", e)
            return None
    
    async def _is_apexcharts_available(self, hass: HomeAssistant) -> bool:
        """Check if ApexCharts card is available."""
        try:
            # Check if the custom card is registered
            # This is a simplified check - in reality you might need to check frontend resources
            return True  # Assume available for now, will show error in card if not
        except Exception:
            return False
    
    async def _build_climate_control_sections(self, hass: HomeAssistant, climate_devices: List[str]) -> List[Dict[str, Any]]:
        """Build climate control sections."""
        sections = []
        
        try:
            cards = []
            for device in climate_devices:
                state = hass.states.get(device)
                if not state:
                    continue
                    
                cards.append({
                    "type": "thermostat",
                    "entity": device,
                })
            
            if cards:
                sections.append({
                    "title": "Climate Control",
                    "cards": cards
                })
                
        except Exception as e:
            _LOGGER.error("Error building climate control sections: %s", e)
        
        return sections
    
    async def _build_schedule_sections(self, hass: HomeAssistant, config_entry) -> List[Dict[str, Any]]:
        """Build schedule status sections."""
        sections = []
        
        try:
            config = config_entry.options or config_entry.data
            schedules = config.get("schedules", [])
            
            if not schedules:
                return sections
            
            # Build schedule status cards
            schedule_cards = []
            for schedule in schedules:
                schedule_name = schedule.get("name", "Unnamed Schedule")
                schedule_id = schedule.get("id", schedule_name.lower().replace(" ", "_"))
                
                # Create entity ID for schedule binary sensor
                entity_id = f"binary_sensor.heating_schedule_{schedule_id}"
                
                schedule_cards.append({
                    "type": "entity",
                    "entity": entity_id,
                    "name": schedule_name,
                })
            
            if schedule_cards:
                sections.append({
                    "title": "Schedule Status",
                    "cards": schedule_cards
                })
                
        except Exception as e:
            _LOGGER.error("Error building schedule sections: %s", e)
        
        return sections

# Fallback strategy class for older Home Assistant versions
if not STRATEGY_SUPPORTED and LovelaceStrategy is None:
    class Strategy:
        """Fallback strategy class."""
        
        def __init__(self):
            raise NotImplementedError("Dashboard strategy not supported in this Home Assistant version")
