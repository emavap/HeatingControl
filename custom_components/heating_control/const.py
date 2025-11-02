"""Constants for the Heating Control integration."""

DOMAIN = "heating_control"

# Configuration keys - Global
CONF_DEVICE_TRACKERS = "device_trackers"
CONF_AUTO_HEATING_ENABLED = "automatic_heating_enabled"

# Configuration keys - Schedules
CONF_SCHEDULES = "schedules"
CONF_SCHEDULE_ID = "id"
CONF_SCHEDULE_NAME = "name"
CONF_SCHEDULE_ENABLED = "enabled"
CONF_SCHEDULE_START = "start_time"
CONF_SCHEDULE_END = "end_time"
CONF_SCHEDULE_ONLY_WHEN_HOME = "only_when_home"
CONF_SCHEDULE_HVAC_MODE = "hvac_mode"
CONF_SCHEDULE_DEVICES = "device_entities"
CONF_SCHEDULE_TEMPERATURE = "temperature"
CONF_SCHEDULE_FAN_MODE = "fan_mode"

# Configuration keys - Climate devices (just a list of available entities)
CONF_CLIMATE_DEVICES = "climate_devices"

# Default values
DEFAULT_SCHEDULE_START = "00:00"
DEFAULT_SCHEDULE_END = "23:59"
DEFAULT_SCHEDULE_TEMPERATURE = 20.0
DEFAULT_SCHEDULE_FAN_MODE = "auto"
DEFAULT_SCHEDULE_HVAC_MODE = "heat"
DEFAULT_SETTLE_SECONDS = 5
DEFAULT_FINAL_SETTLE = 2

# Sensor types
BINARY_SENSOR_EVERYONE_AWAY = "everyone_away"

SENSOR_DECISION_DIAGNOSTICS = "decision_diagnostics"

# Update interval (seconds)
UPDATE_INTERVAL = 60

# Services
SERVICE_SET_SCHEDULE_ENABLED = "set_schedule_enabled"

# Service attributes
ATTR_ENTRY_ID = "entry_id"
ATTR_SCHEDULE_ID = "schedule_id"
ATTR_SCHEDULE_NAME = "schedule_name"

# Entity naming
SCHEDULE_SWITCH_ENTITY_TEMPLATE = "switch.heating_schedule_{entry}_{schedule}_enabled"

# Entity IDs
ENTITY_DECISION_DIAGNOSTICS = "sensor.heating_control_decision_diagnostics"
ENTITY_EVERYONE_AWAY = "binary_sensor.heating_control_everyone_away"

# Dashboard
DASHBOARD_TITLE = "Smart Heating"
DASHBOARD_ICON = "mdi:thermostat"
DASHBOARD_URL_PATH_TEMPLATE = "heating-control-{entry_id}"
DASHBOARD_CREATED_KEY = "dashboard_url"
DASHBOARD_ENTRY_ID_LENGTH = 8  # Length of entry_id prefix for dashboard URL
