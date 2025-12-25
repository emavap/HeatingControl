"""Constants for the Heating Control integration."""

__all__ = [
    # Domain
    "DOMAIN",
    # Configuration keys - Global
    "CONF_DEVICE_TRACKERS",
    "CONF_AUTO_HEATING_ENABLED",
    "CONF_DISABLED_DEVICES",
    "CONF_OUTDOOR_TEMP_SENSOR",
    "CONF_OUTDOOR_TEMP_THRESHOLD",
    # Configuration keys - Schedules
    "CONF_SCHEDULES",
    "CONF_SCHEDULE_ID",
    "CONF_SCHEDULE_NAME",
    "CONF_SCHEDULE_ENABLED",
    "CONF_SCHEDULE_START",
    "CONF_SCHEDULE_END",
    "CONF_SCHEDULE_ONLY_WHEN_HOME",
    "CONF_SCHEDULE_DEVICE_TRACKERS",
    "CONF_SCHEDULE_HVAC_MODE",
    "CONF_SCHEDULE_AWAY_HVAC_MODE",
    "CONF_SCHEDULE_AWAY_TEMPERATURE",
    "CONF_SCHEDULE_DEVICES",
    "CONF_SCHEDULE_TEMPERATURE",
    "CONF_SCHEDULE_FAN_MODE",
    "CONF_SCHEDULE_TEMP_CONDITION",
    "CONF_CLIMATE_DEVICES",
    # Temperature condition values
    "TEMP_CONDITION_ALWAYS",
    "TEMP_CONDITION_COLD",
    "TEMP_CONDITION_WARM",
    "TEMP_CONDITION_OPTIONS",
    # Default values
    "DEFAULT_SCHEDULE_START",
    "DEFAULT_SCHEDULE_END",
    "DEFAULT_SCHEDULE_TEMPERATURE",
    "DEFAULT_SCHEDULE_FAN_MODE",
    "DEFAULT_SCHEDULE_HVAC_MODE",
    "DEFAULT_SCHEDULE_AWAY_HVAC_MODE",
    "DEFAULT_OUTDOOR_TEMP_THRESHOLD",
    "DEFAULT_OUTDOOR_TEMP_HYSTERESIS",
    "TEMPERATURE_MIN",
    "TEMPERATURE_MAX",
    "TEMPERATURE_STEP",
    "HVAC_MODE_OPTIONS",
    "AWAY_HVAC_MODE_OPTIONS",
    # Settle delays
    "DEFAULT_SETTLE_SECONDS",
    "DEFAULT_FINAL_SETTLE",
    # Timeout values
    "SERVICE_CALL_TIMEOUT",
    "UPDATE_CYCLE_TIMEOUT",
    "WATCHDOG_STUCK_THRESHOLD",
    "TEMPERATURE_EPSILON",
    # Sensor types
    "BINARY_SENSOR_EVERYONE_AWAY",
    "SENSOR_DECISION_DIAGNOSTICS",
    # Update interval
    "UPDATE_INTERVAL",
    # Services
    "SERVICE_SET_SCHEDULE_ENABLED",
    "SERVICE_SET_DEVICE_ENABLED",
    "SERVICE_STOP_ALL",
    "ATTR_ENTRY_ID",
    "ATTR_SCHEDULE_ID",
    "ATTR_SCHEDULE_NAME",
    "ATTR_DEVICE_ENTITY_ID",
    # Entity naming
    "SCHEDULE_SWITCH_ENTITY_TEMPLATE",
    "SCHEDULE_BINARY_ENTITY_TEMPLATE",
    "DEVICE_BINARY_ENTITY_TEMPLATE",
    "DEVICE_SWITCH_ENTITY_TEMPLATE",
    "ENTITY_DECISION_DIAGNOSTICS",
    "ENTITY_EVERYONE_AWAY",
    # Dashboard
    "DASHBOARD_TITLE",
    "DASHBOARD_ICON",
    "DASHBOARD_URL_PATH_TEMPLATE",
    "DASHBOARD_CREATED_KEY",
    "DASHBOARD_ENTRY_ID_LENGTH",
    # Dashboard status indicators
    "STATUS_OFF",
    "STATUS_ON",
    "STATUS_IDLE",
    "STATUS_WAIT",
]

DOMAIN = "heating_control"

# Configuration keys - Global
CONF_DEVICE_TRACKERS = "device_trackers"
CONF_AUTO_HEATING_ENABLED = "automatic_heating_enabled"
CONF_DISABLED_DEVICES = "disabled_devices"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"
CONF_OUTDOOR_TEMP_THRESHOLD = "outdoor_temp_threshold"

# Configuration keys - Schedules
CONF_SCHEDULES = "schedules"
CONF_SCHEDULE_ID = "id"
CONF_SCHEDULE_NAME = "name"
CONF_SCHEDULE_ENABLED = "enabled"
CONF_SCHEDULE_START = "start_time"
CONF_SCHEDULE_END = "end_time"
CONF_SCHEDULE_ONLY_WHEN_HOME = "only_when_home"
CONF_SCHEDULE_DEVICE_TRACKERS = "schedule_device_trackers"
CONF_SCHEDULE_HVAC_MODE = "hvac_mode"
CONF_SCHEDULE_AWAY_HVAC_MODE = "away_hvac_mode"
CONF_SCHEDULE_AWAY_TEMPERATURE = "away_temperature"
CONF_SCHEDULE_DEVICES = "device_entities"
CONF_SCHEDULE_TEMPERATURE = "temperature"
CONF_SCHEDULE_FAN_MODE = "fan_mode"
CONF_SCHEDULE_TEMP_CONDITION = "temp_condition"

# Configuration keys - Climate devices (just a list of available entities)
CONF_CLIMATE_DEVICES = "climate_devices"

# Temperature condition values (for outdoor temperature-based schedule selection)
TEMP_CONDITION_ALWAYS = "always"
TEMP_CONDITION_COLD = "cold"
TEMP_CONDITION_WARM = "warm"

# Temperature condition selector options for config flow
TEMP_CONDITION_OPTIONS = [
    {"label": "Always (no condition)", "value": "always"},
    {"label": "Cold only (outdoor temp < threshold)", "value": "cold"},
    {"label": "Warm only (outdoor temp ≥ threshold)", "value": "warm"},
]

# Default values
DEFAULT_SCHEDULE_START = "00:00"
DEFAULT_SCHEDULE_END = "23:59"
DEFAULT_SCHEDULE_TEMPERATURE = 20.0
DEFAULT_SCHEDULE_FAN_MODE = "auto"
DEFAULT_SCHEDULE_HVAC_MODE = "heat"
DEFAULT_SCHEDULE_AWAY_HVAC_MODE = "off"
DEFAULT_OUTDOOR_TEMP_THRESHOLD = 5.0  # °C - default threshold for cold/warm mode (migration default)
# Hysteresis for outdoor temperature threshold (Schmitt trigger)
# Prevents rapid switching when temperature hovers around threshold
# cold→warm: requires temp >= threshold + hysteresis
# warm→cold: requires temp < threshold
DEFAULT_OUTDOOR_TEMP_HYSTERESIS = 1.0  # °C

# Temperature range for schedule configuration (°C)
TEMPERATURE_MIN = 5.0
TEMPERATURE_MAX = 35.0
TEMPERATURE_STEP = 0.5

# HVAC mode selector options for config flow
HVAC_MODE_OPTIONS = [
    {"label": "Heat", "value": "heat"},
    {"label": "Cool", "value": "cool"},
    {"label": "Heat/Cool", "value": "heat_cool"},
    {"label": "Off", "value": "off"},
    {"label": "Auto", "value": "auto"},
    {"label": "Dry", "value": "dry"},
    {"label": "Fan Only", "value": "fan_only"},
]

# Away HVAC mode includes inherit option
AWAY_HVAC_MODE_OPTIONS = [{"label": "Use home HVAC mode", "value": "inherit"}] + HVAC_MODE_OPTIONS
# Settle delays after HVAC mode changes (seconds)
# Some devices need time to stabilize after mode changes before accepting temperature commands
DEFAULT_SETTLE_SECONDS = 5  # Wait after HVAC mode change before sending temperature
DEFAULT_FINAL_SETTLE = 2  # Final wait after all commands to ensure device stability

# Timeout values (seconds)
# Maximum time for a single climate service call
# Some smart thermostats (especially Zigbee/Z-Wave) can take 20-25s to respond
SERVICE_CALL_TIMEOUT = 30

# Maximum expected time for a complete update cycle
# Worst case per device: mode change (up to 30s timeout) + 5s settle + temp (30s) + fan (30s) + 2s final
# With 10 devices transitioning: 10 * (30 + 5 + 30 + 30 + 2) ≈ 970s theoretical max
# Realistic case: most commands succeed quickly (1-2s), only settle delays are guaranteed
# With 10 devices: 10 * (2s mode + 5s settle + 2s temp + 2s fan + 2s final) ≈ 130s
# Set to 120s to accommodate realistic worst case while still detecting actual stuck cycles
UPDATE_CYCLE_TIMEOUT = 120

# Time after which we consider the integration completely stuck (3 minutes)
# This threshold should be significantly higher than normal operation time
WATCHDOG_STUCK_THRESHOLD = 180

# Temperature comparison epsilon (°C)
# Minimum temperature change to trigger an update
# Set to 0.1°C to accommodate devices with 0.5°C increments and avoid floating-point comparison issues
TEMPERATURE_EPSILON = 0.1

# Sensor types
BINARY_SENSOR_EVERYONE_AWAY = "everyone_away"

SENSOR_DECISION_DIAGNOSTICS = "decision_diagnostics"

# Update interval (seconds)
# How often the coordinator checks schedules and evaluates state transitions
# 60 seconds provides responsive updates without excessive polling
UPDATE_INTERVAL = 60

# Services
SERVICE_SET_SCHEDULE_ENABLED = "set_schedule_enabled"
SERVICE_SET_DEVICE_ENABLED = "set_device_enabled"
SERVICE_STOP_ALL = "stop_all"

# Service attributes
ATTR_ENTRY_ID = "entry_id"
ATTR_SCHEDULE_ID = "schedule_id"
ATTR_SCHEDULE_NAME = "schedule_name"
ATTR_DEVICE_ENTITY_ID = "device_entity_id"

# Entity naming
SCHEDULE_SWITCH_ENTITY_TEMPLATE = "switch.heating_schedule_{entry}_{schedule}_enabled"
SCHEDULE_BINARY_ENTITY_TEMPLATE = "binary_sensor.heating_schedule_{entry}_{schedule}_active"
DEVICE_BINARY_ENTITY_TEMPLATE = "binary_sensor.heating_device_{entry}_{device}"
DEVICE_SWITCH_ENTITY_TEMPLATE = "switch.heating_device_{entry}_{device}_enabled"
# Entity IDs
ENTITY_DECISION_DIAGNOSTICS = "sensor.heating_control_decision_diagnostics"
ENTITY_EVERYONE_AWAY = "binary_sensor.heating_control_everyone_away"

# Dashboard
DASHBOARD_TITLE = "Smart Heating"
DASHBOARD_ICON = "mdi:thermostat"
DASHBOARD_URL_PATH_TEMPLATE = "heating-control-{entry_id}"
DASHBOARD_CREATED_KEY = "dashboard_url"
DASHBOARD_ENTRY_ID_LENGTH = 8  # Length of entry_id prefix for dashboard URL

# Dashboard status indicators
STATUS_OFF = "[OFF]"
STATUS_ON = "[ON]"
STATUS_IDLE = "[IDLE]"
STATUS_WAIT = "[WAIT]"
