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
CONF_SCHEDULE_DEVICE_TRACKERS = "schedule_device_trackers"
CONF_SCHEDULE_HVAC_MODE = "hvac_mode"
CONF_SCHEDULE_AWAY_HVAC_MODE = "away_hvac_mode"
CONF_SCHEDULE_AWAY_TEMPERATURE = "away_temperature"
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
DEFAULT_SCHEDULE_AWAY_HVAC_MODE = "off"
# Settle delays after HVAC mode changes (seconds)
# Some devices need time to stabilize after mode changes before accepting temperature commands
DEFAULT_SETTLE_SECONDS = 5  # Wait after HVAC mode change before sending temperature
DEFAULT_FINAL_SETTLE = 2  # Final wait after all commands to ensure device stability

# Maximum time for a single climate service call
# Some smart thermostats (especially Zigbee/Z-Wave) can take 20-25s to respond
SERVICE_CALL_TIMEOUT = 30

# Maximum expected time for a complete update cycle
# With 10 devices: 10 * (1s mode + 1s temp + 1s fan + 5s settle) ≈ 80s worst case
# Set conservatively lower to catch stuck cycles early via watchdog diagnostics
UPDATE_CYCLE_TIMEOUT = 50

# Circuit breaker and watchdog constants
CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 0.8  # 80% timeout rate triggers circuit breaker
CIRCUIT_BREAKER_COOLDOWN_MINUTES = 5  # Minutes to wait before re-enabling after circuit breaker
WATCHDOG_STUCK_THRESHOLD = 600  # 10 minutes in seconds
WATCHDOG_TIMEOUT_THRESHOLD = 300  # 5 minutes in seconds

# Temperature comparison epsilon
TEMPERATURE_EPSILON = 0.1  # Degrees - avoid unnecessary commands for tiny differences

# Performance optimization
MAX_CONCURRENT_DEVICE_COMMANDS = 5  # Limit parallel climate commands
PRESENCE_CACHE_SECONDS = 30  # Cache presence state to reduce entity lookups

# Entity validation
SUPPORTED_CLIMATE_DOMAINS = ["climate"]
SUPPORTED_TRACKER_DOMAINS = ["device_tracker", "person", "zone"]

# Sensor types
BINARY_SENSOR_EVERYONE_AWAY = "everyone_away"

SENSOR_DECISION_DIAGNOSTICS = "decision_diagnostics"

# Update interval (seconds)
# How often the coordinator checks schedules and evaluates state transitions
# 60 seconds provides responsive updates without excessive polling
UPDATE_INTERVAL = 60

# Services
SERVICE_SET_SCHEDULE_ENABLED = "set_schedule_enabled"

# Service attributes
ATTR_ENTRY_ID = "entry_id"
ATTR_SCHEDULE_ID = "schedule_id"
ATTR_SCHEDULE_NAME = "schedule_name"

# Entity naming
SCHEDULE_SWITCH_ENTITY_TEMPLATE = "switch.heating_schedule_{entry}_{schedule}_enabled"
SCHEDULE_BINARY_ENTITY_TEMPLATE = "binary_sensor.heating_schedule_{entry}_{schedule}_active"
DEVICE_BINARY_ENTITY_TEMPLATE = "binary_sensor.heating_device_{entry}_{device}"
# Entity IDs
ENTITY_DECISION_DIAGNOSTICS = "sensor.heating_control_decision_diagnostics"
ENTITY_EVERYONE_AWAY = "binary_sensor.heating_control_everyone_away"

# Time parsing constants
MINUTES_PER_DAY = 24 * 60
HOURS_PER_DAY = 24
MINUTES_PER_HOUR = 60

# HVAC mode constants
HVAC_MODES_WITH_TEMPERATURE = {"heat", "cool", "heat_cool", "auto"}

# Dashboard and UI constants
DASHBOARD_REFRESH_DELAY_SECONDS = 2
OPTIMISTIC_STATE_TIMEOUT_MULTIPLIER = 2
OPTIMISTIC_STATE_MIN_TIMEOUT = 60

# Schedule evaluation constants
SCHEDULE_CACHE_EXPIRY_SECONDS = 300  # 5 minutes
PRESENCE_HASH_CACHE_SECONDS = 60

# Performance monitoring
PERFORMANCE_SAMPLE_SIZE = 50
CACHE_HIT_RATE_WINDOW = 100

# Version compatibility
MIN_DASHBOARD_STRATEGY_VERSION = "2024.4.0"

# Device timeout overrides (seconds)
DEVICE_TIMEOUT_OVERRIDES = {
    "zigbee": 45,
    "zwave": 35, 
    "wifi": 20,
    "esphome": 15,
    "tasmota": 20,
}

# Device-specific settle delays (seconds)
DEVICE_SETTLE_OVERRIDES = {
    "zigbee": {"settle": 8, "final_settle": 3},
    "zwave": {"settle": 6, "final_settle": 2}, 
    "wifi": {"settle": 3, "final_settle": 1},
    "esphome": {"settle": 2, "final_settle": 1},
    "tasmota": {"settle": 3, "final_settle": 1},
}

# Validation thresholds
MAX_SCHEDULE_OVERLAPS_WARNING = 3
MIN_SCHEDULE_DURATION_MINUTES = 15
