"""Constants for the Heating Control integration."""

DOMAIN = "heating_control"

# Configuration keys - Global
CONF_DEVICE_TRACKER_1 = "device_tracker_1"
CONF_DEVICE_TRACKER_2 = "device_tracker_2"
CONF_AUTO_HEATING_ENABLED = "automatic_heating_enabled"
CONF_GAS_HEATER_ENTITY = "gas_heater_entity"
CONF_ONLY_SCHEDULED_ACTIVE = "only_scheduled_devices_active"

# Configuration keys - Schedules
CONF_SCHEDULES = "schedules"
CONF_SCHEDULE_ID = "id"
CONF_SCHEDULE_NAME = "name"
CONF_SCHEDULE_ENABLED = "enabled"
CONF_SCHEDULE_START = "start_time"
CONF_SCHEDULE_END = "end_time"
CONF_SCHEDULE_ALWAYS_ACTIVE = "always_active"
CONF_SCHEDULE_ONLY_WHEN_HOME = "only_when_home"
CONF_SCHEDULE_USE_GAS = "use_gas_heater"
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
DEFAULT_SETTLE_SECONDS = 5
DEFAULT_FINAL_SETTLE = 2
DEFAULT_ONLY_SCHEDULED_ACTIVE = False

# Sensor types
BINARY_SENSOR_BOTH_AWAY = "both_away"

SENSOR_DECISION_DIAGNOSTICS = "decision_diagnostics"

# Update interval (seconds)
UPDATE_INTERVAL = 60
