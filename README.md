# Heating Control

A custom Home Assistant integration that **automatically controls** climate devices based on schedules, presence, and time-based rules. The integration directly manages your heating/cooling devices without requiring additional automations.

## Features

- **Automatic Device Control**: Integration directly controls all configured climate devices
- **Schedule-Based**: Define multiple schedules with time windows and device assignments
- **Many-to-Many Relationships**: Devices can be in multiple schedules, schedules can have multiple devices
- **Gas Heater Override**: Any schedule can use the gas heater instead of assigned aircos
- **Presence-Based**: Schedules can require someone to be home
- **Binary Sensors**: Monitor heating decisions and current state
- **Decision Diagnostics**: Full visibility into heating logic

## Directory Structure

```
HeatingControl/
├── custom_components/
│   └── heating_control/
│       ├── __init__.py
│       ├── binary_sensor.py
│       ├── config_flow.py
│       ├── const.py
│       ├── coordinator.py
│       ├── manifest.json
│       ├── sensor.py
│       └── strings.json
├── examples/
│   └── automations/
│       └── smart_house_heating_control.yaml
├── tests/
└── README.md
```

## Installation

### Method 1: Manual Installation

1. Copy the `custom_components/heating_control` directory to your Home Assistant `custom_components` folder
2. Restart Home Assistant
3. Go to Settings > Devices & Services > Add Integration
4. Search for "Heating Control" and follow the configuration wizard

### Method 2: HACS (when published)

1. Open HACS
2. Go to Integrations
3. Search for "Heating Control"
4. Install and restart Home Assistant

## Configuration

The integration uses a schedule-based model where you define time windows and assign devices to them.

### Step 1: Global Settings

Configure settings that apply to all schedules:

- **Gas Heater Entity**: Your gas heating thermostat (optional)
- **Device Trackers**: Up to 2 device trackers for presence detection (optional)
- **Automatic Heating**: Master enable/disable switch for automatic heating
- **Only Scheduled Devices Active**: If enabled, devices not in any schedule remain off. If disabled, devices not in schedules will be on when someone is home (default: false)

### Step 2: Select Climate Devices

Select all climate devices (aircos, heaters, thermostats) that you want to manage with schedules. These devices can then be assigned to one or more schedules.

### Step 3: Create Schedules

For each schedule, configure:

- **Schedule Name**: Friendly name (e.g., "Night Bedroom", "Day Living Area")
- **Enabled**: Enable/disable this schedule
- **Target Temperature**: Temperature for this schedule (default: 20°C)
- **Fan Mode**: Fan mode for this schedule (default: "auto")
- **Always Active**: Schedule ignores time window and is always active
- **Start Time**: When schedule becomes active (default: 00:00)
- **End Time**: When schedule becomes inactive (default: 23:59)
- **Only When Home**: Schedule only active when someone is home
- **Use Gas Heater**: Use gas heater instead of assigned devices
- **Devices**: Select which climate devices this schedule controls

## How It Works

### Automatic Control Cycle

Every 60 seconds, the integration:

1. **Evaluates All Schedules**:
   - Time Window Check: Is current time within schedule start/end (or always active)?
   - Presence Check: Is presence requirement met (only when home)?
   - Schedule Active: Both conditions must be true

2. **Determines Device States**:
   - Devices can be assigned to **multiple schedules**
   - If **any** active schedule includes a device, it should be on
   - Devices not in any schedule: depend on "Only Scheduled Devices Active" setting
   - **Temperature Selection**: When a device is in multiple active schedules with different temperatures, the **highest temperature wins**
   - **Fan Mode**: Uses the fan mode from the schedule with the highest temperature

3. **Controls Climate Devices Directly**:
   - Turns devices ON/OFF based on schedule decisions
   - Sets temperature from the active schedule (highest if multiple schedules)
   - Sets fan mode from the active schedule
   - Only sends commands when state changes (avoids unnecessary calls)

## Logic Explained

### Schedule Evaluation Process

The integration follows a clear decision-making process to determine which devices should be on and at what temperature:

#### Step 1: Evaluate Each Schedule

For each configured schedule, the integration checks:

1. **Is the schedule enabled?** If disabled, skip it.
2. **Is automatic heating enabled globally?** If not, skip all schedules.
3. **Time Window Check**:
   - If "Always Active" is enabled, this check passes automatically
   - Otherwise, check if current time is between start_time and end_time
   - Handles schedules that span midnight (e.g., 22:00 to 07:00)
4. **Presence Check**:
   - If "Only When Home" is enabled, at least one device tracker must be "home"
   - If "Only When Home" is disabled, this check always passes

If ALL conditions pass, the schedule is **ACTIVE**.

#### Step 2: Collect Device Assignments

For each **active** schedule:

- **If "Use Gas Heater" is enabled**:
  - The schedule is added to the gas heater's list of requesting schedules
  - The schedule's temperature and fan mode are recorded for the gas heater
  - The assigned devices are NOT turned on (gas heater replaces them)

- **If "Use Gas Heater" is disabled AND devices are assigned**:
  - Each assigned device is marked as "should be on"
  - The schedule's temperature is added to that device's temperature list
  - The schedule's fan mode is added to that device's fan mode list
  - The schedule name is added to the device's active schedules list

#### Step 3: Handle Devices Not in Any Schedule

For devices that are NOT in any active schedule:

- **If "Only Scheduled Devices Active" = true**: Device should be OFF
- **If "Only Scheduled Devices Active" = false AND someone is home AND automatic heating enabled**: Device should be ON at default temperature (20°C)
- **Otherwise**: Device should be OFF

#### Step 4: Resolve Temperature Conflicts (Highest Wins)

For each device that should be ON:

1. Collect all temperatures from active schedules that include this device
2. **Select the HIGHEST temperature** as the target
3. Find which schedule provided that highest temperature
4. Use the **fan mode from that same schedule**

**Example:**
```
Device: bedroom_ac
Active Schedules:
  - "Morning Warmup": 22°C, fan: "auto"
  - "Day Comfort": 19°C, fan: "low"
  - "Evening Heat": 23°C, fan: "high"

Result:
  - Target Temperature: 23°C (highest)
  - Target Fan Mode: "high" (from "Evening Heat" schedule)
```

#### Step 5: Gas Heater Temperature Resolution

If any active schedules have "Use Gas Heater" enabled:

1. Collect all temperatures from schedules using the gas heater
2. **Select the HIGHEST temperature** as the gas heater target
3. Find which schedule provided that highest temperature
4. Use the **fan mode from that same schedule**

**Example:**
```
Gas Heater
Active Schedules Using It:
  - "Day Living Areas": 20°C, fan: "auto"
  - "Cold Morning Boost": 24°C, fan: "high"

Result:
  - Gas Heater: ON
  - Target Temperature: 24°C (highest)
  - Target Fan Mode: "high" (from "Cold Morning Boost")
```

#### Step 6: Execute Control Commands

For each device and the gas heater:

1. **Check if state change is needed**: Compare desired state with previous state
2. **If state changed** (from OFF to ON, ON to OFF, or temperature/fan changed):
   - **Turning ON**:
     - Set HVAC mode to "heat"
     - Wait 5 seconds (allows device to initialize)
     - Set target temperature
     - Set fan mode (if supported by device)
     - Wait 2 seconds (final settling)
   - **Turning OFF**:
     - Set HVAC mode to "off"
3. **Track the new state** to avoid redundant commands in next cycle

### Why Highest Temperature Wins?

The "highest temperature wins" logic ensures user comfort in complex scenarios:

- **Safety**: If multiple schedules are active, the warmest setting takes priority
- **Comfort**: Users won't be cold because one schedule set a lower temperature
- **Flexibility**: You can have overlapping schedules without conflicts
- **Intuitive**: Most users expect "warmer" to take priority over "cooler"

**Real-World Example:**

```
Bedroom AC is in two schedules:
1. "Night Sleep": 18°C (22:00 - 07:00) - for sleeping comfort
2. "Cold Weather Boost": 22°C (Always Active, only when temp < 10°C outside)

On a very cold night:
- Both schedules are active
- Integration uses 22°C (highest) to ensure you stay warm
- Without this logic, you might freeze at 18°C on cold nights
```

### Schedule Priority and Conflicts

**Q: What if two schedules have the same highest temperature but different fan modes?**

A: The integration uses the first schedule encountered with that temperature. The order is deterministic (based on how schedules are stored), but you should avoid this scenario by setting slightly different temperatures (e.g., 20.0°C vs 20.5°C) if the fan mode matters.

**Q: Can I have a schedule that LOWERS temperature if another schedule set it higher?**

A: No. The "highest temperature wins" rule always applies. If you need devices at different temperatures, assign them to separate schedules, not overlapping ones.

**Q: What about devices not in any schedule?**

A: This depends on the "Only Scheduled Devices Active" setting:
- **If TRUE**: Devices not in any schedule stay OFF (most restrictive, saves energy)
- **If FALSE**: Devices not in any schedule turn ON when someone is home (convenience mode)

### Gas Heater Override Logic

When a schedule has "Use Gas Heater" enabled:

1. **Schedule Must Be Active**: All normal schedule conditions apply (time, presence, enabled)
2. **Gas Heater Turns ON**: The gas heater activates at the schedule's temperature
3. **Assigned Devices Stay OFF**: Any devices assigned to this schedule do NOT turn on
4. **Purpose**: This allows you to use gas heating instead of individual aircos during certain periods

**Important:** The gas heater only activates if the schedule has "Use Gas Heater" enabled AND the schedule is active. Multiple schedules can request the gas heater, and it will use the highest temperature from those schedules.

**Example:**

```yaml
Schedule: "Daytime Gas Heating"
  Time: 07:00 - 22:00
  Temperature: 21°C
  Use Gas Heater: Yes
  Devices: [bedroom_ac, living_room_ac, kitchen_ac]

When Active:
  - Gas heater: ON at 21°C
  - bedroom_ac: OFF (not ON, because gas heater is being used)
  - living_room_ac: OFF
  - kitchen_ac: OFF

When Inactive (e.g., 23:00):
  - Gas heater: OFF
  - bedroom_ac: depends on other schedules or "Only Scheduled Devices Active"
  - living_room_ac: depends on other schedules
  - kitchen_ac: depends on other schedules
```

### Device Assignment Logic

- Devices can be assigned to **multiple schedules**
- If **any** active schedule includes a device, it should be on
- Devices not in any schedule:
  - If "Only Scheduled Devices Active" = true: remain off
  - If "Only Scheduled Devices Active" = false: on when someone is home

### Gas Heater Override

When a schedule has **"Use Gas Heater" enabled**:
- If the schedule is active AND has devices assigned
- The gas heater will be used **instead** of those devices
- The assigned devices will NOT be turned on

**Example:**
```yaml
Schedule: "Day Time"
  Start: 07:00
  End: 22:00
  Use Gas Heater: Yes
  Devices: [bedroom_ac, living_room_ac, kitchen_ac]

Result when active:
  - Gas heater: ON
  - bedroom_ac: OFF
  - living_room_ac: OFF
  - kitchen_ac: OFF
```

## Exposed Entities

### Global Binary Sensors

- `binary_sensor.heating_control_both_away` - Are both residents away

### Gas Heater Binary Sensor

- `binary_sensor.heating_gas_heater` - Should gas heater be active

**Attributes:**
- `entity_id` - The gas heater climate entity
- `target_temp` - Target temperature (highest from active schedules using gas heater)
- `target_fan` - Target fan mode (from schedule with highest temperature)
- `active_schedules` - List of schedules using gas heater

### Per-Schedule Binary Sensors

For each schedule configured:
- `binary_sensor.heating_schedule_<schedule_name>` - Is this schedule active

**Attributes:**
- `schedule_name` - Schedule name
- `in_time_window` - Is current time within schedule window
- `presence_ok` - Does presence requirement allow activation
- `use_gas_heater` - Does this schedule use gas heater
- `device_count` - Number of devices in schedule
- `devices` - List of device entity IDs
- `target_temp` - Target temperature
- `target_fan` - Target fan mode

### Per-Device Binary Sensors

For each climate device configured:
- `binary_sensor.heating_<device_name>` - Should this device be active

**Attributes:**
- `entity_id` - The climate entity ID
- `active_schedules` - List of schedules wanting this device active
- `schedule_count` - Number of active schedules for this device
- `target_temp` - Target temperature (highest from active schedules for this device)
- `target_fan` - Target fan mode (from schedule with highest temperature)

### Global Sensors

- `sensor.heating_control_decision_diagnostics` - Diagnostic information

## Example Scenarios

### Scenario 1: Bedroom Night Heating Only

```yaml
Schedule: "Bedroom Night"
  Start: 22:00
  End: 07:00
  Only When Home: Yes
  Use Gas Heater: No
  Devices: [bedroom_ac, bedroom_ac_2]

Result:
  - Between 22:00-07:00 when someone is home: bedroom ACs on
  - All other times: bedroom ACs off
  - These ACs can also be in other schedules
```

### Scenario 2: Day Time with Gas Heater

```yaml
Schedule: "Day Living Areas"
  Start: 07:00
  End: 22:00
  Only When Home: Yes
  Use Gas Heater: Yes
  Devices: [living_room_ac, kitchen_ac, office_ac]

Result:
  - Between 07:00-22:00 when someone is home: gas heater on
  - The listed ACs will NOT be used (gas heater replaces them)
  - Gas heater off all other times
```

### Scenario 3: Office Always On (Even When Away)

```yaml
Schedule: "Office Work Hours"
  Start: 09:00
  End: 17:00
  Only When Home: No
  Use Gas Heater: No
  Devices: [office_ac]

Result:
  - Between 09:00-17:00 every day: office_ac on
  - Works even when no one is home
```

### Scenario 4: Device in Multiple Schedules

```yaml
Schedule 1: "Morning Kitchen"
  Start: 06:00
  End: 10:00
  Devices: [kitchen_ac]

Schedule 2: "Evening Kitchen"
  Start: 18:00
  End: 23:00
  Devices: [kitchen_ac]

Result:
  - kitchen_ac is on from 06:00-10:00
  - kitchen_ac is off from 10:00-18:00
  - kitchen_ac is on from 18:00-23:00
  - kitchen_ac is off from 23:00-06:00
```

## Automatic Control

The integration **automatically controls** all configured climate devices every 60 seconds:

### What Happens Automatically

1. **Schedule Evaluation**: All schedules are evaluated based on current time and presence
2. **Device Control**: Climate devices are turned on/off based on active schedules
3. **Temperature Setting**: Devices are set to the temperature from their active schedule(s) - highest wins if multiple
4. **Fan Mode**: Fan mode from the schedule with highest temperature
5. **Gas Heater**: Activated when any schedule with "use_gas_heater" is active, using the highest temperature from those schedules

### Device Control Logic

- **Turn ON**: When a schedule becomes active for a device
  - Set HVAC mode to "heat"
  - Wait 5 seconds for device to settle
  - Set target temperature (from schedule, highest if multiple active schedules)
  - Set fan mode (from schedule with highest temperature, if supported)
  - Wait 2 seconds for final settling

- **Turn OFF**: When no active schedules need the device
  - Set HVAC mode to "off"

- **State Tracking**: Integration only sends commands when state actually changes (avoids unnecessary calls)

### Monitoring with Binary Sensors

Binary sensors are provided for monitoring and creating custom notifications or additional automations:

```yaml
# Example: Notify when gas heater turns on
automation:
  - alias: "Notify Gas Heater On"
    trigger:
      - platform: state
        entity_id: binary_sensor.heating_gas_heater
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          message: "Gas heater activated: {{ state_attr('binary_sensor.heating_gas_heater', 'active_schedules') }}"
```

```yaml
# Example: Notify when specific schedule becomes active
automation:
  - alias: "Heating Night Mode Active"
    trigger:
      - platform: state
        entity_id: binary_sensor.heating_schedule_bedroom_night
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          message: "Bedroom night heating activated at {{ state_attr('binary_sensor.heating_schedule_bedroom_night', 'target_temp') }}°C"
```

## Development

### Running Tests

```bash
cd tests
pytest
```

### Project Structure

- `__init__.py` - Integration setup and entry point
- `config_flow.py` - Multi-step UI configuration wizard (global settings → devices → schedules)
- `coordinator.py` - Schedule evaluation and decision logic
- `binary_sensor.py` - Binary sensor entities (schedule, device, gas heater sensors)
- `sensor.py` - Regular sensor entities for diagnostics
- `const.py` - Constants and configuration keys
- `manifest.json` - Integration metadata
- `strings.json` - UI translations
