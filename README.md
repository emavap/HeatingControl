# Heating Control

A custom Home Assistant integration that **automatically controls** climate devices based on schedules, presence, and time-based rules. The integration directly manages your heating/cooling devices without requiring additional automations.

## Features

- **Automatic Device Control**: Integration directly controls all configured climate devices
- **Schedule-Based**: Define multiple schedules with time windows and device assignments
- **Many-to-Many Relationships**: Devices can be in multiple schedules, schedules can have multiple devices
- **Per-Schedule HVAC Modes**: Choose heating, cooling, or explicit off per schedule
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

- **Device Trackers**: One or more device trackers for presence detection (optional)
- **Automatic Heating**: Master enable/disable switch for automatic heating

### Step 2: Select Climate Devices

Select all climate devices (aircos, heaters, thermostats) that you want to manage with schedules. These devices can then be assigned to one or more schedules.

### Step 3: Create Schedules

For each schedule, configure:

- **Schedule Name**: Friendly name (e.g., "Night Bedroom", "Day Living Area")
- **Enabled**: Enable/disable this schedule
- **HVAC Mode**: Select whether the schedule heats, cools, or turns devices off
- **Target Temperature**: Temperature for this schedule (default: 20°C)
- **Fan Mode**: Fan mode for this schedule (default: "auto")
- **Start Time**: When schedule becomes active (default: 00:00)
- **Automatic End**: The schedule stays active until another schedule begins
- **Only When Home**: Schedule only active when someone is home
- **Devices**: Select which climate devices this schedule controls

## How It Works

### Automatic Control Cycle

Every 60 seconds, the integration:

1. **Evaluates All Schedules**:
   - Time Window Check: Is current time within the schedule window?
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
   - Check if current time is between start_time and end_time
   - Handles schedules that span midnight (e.g., 22:00 to 07:00)
4. **Presence Check**:
   - If "Only When Home" is enabled, at least one device tracker must be "home"
   - If "Only When Home" is disabled, this check always passes

If ALL conditions pass, the schedule is **ACTIVE**.

#### Step 2: Collect Device Assignments

For each **active** schedule:

- Each assigned device records the schedule name, HVAC mode, temperature, and fan mode
- Multiple schedules can contribute entries for the same device

#### Step 3: Handle Devices Not in Any Schedule

For devices that are NOT in any active schedule:

- The integration leaves their current state untouched; no commands are sent

#### Step 4: Resolve Temperature Conflicts (Highest Wins)

For each device with at least one active schedule:

1. Collect all HVAC mode entries recorded in step 2
2. If any active schedule sets the mode to `off`, the device is turned off
3. Otherwise, **select the entry with the highest requested temperature** (ties fall back to schedule order)
4. Use the temperature and fan mode from the selected schedule

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

#### Step 5: Execute Control Commands

For each managed climate device:

1. **Resolve desired state**: Collect the target HVAC mode (heat/cool/off/auto), temperature, and fan mode from the decision engine
2. **Compare with last command**: The coordinator remembers the last HVAC/temperature/fan values it sent for each entity
3. **Apply HVAC changes**: If the desired HVAC mode differs, send `set_hvac_mode` and wait 5 seconds for the device to settle
4. **Apply setpoint changes**: Whenever the target temperature differs, send `set_temperature` even if the device was already on
5. **Apply fan changes**: When the target fan mode differs and is supported by the device, send `set_fan_mode`
6. **Final settle**: If the HVAC mode changed during this cycle, wait an additional 2 seconds before moving on
7. **Store the command**: Record the values that were just sent so future cycles can skip redundant calls

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
2. "Cold Weather Boost": 22°C (Starts at 05:00, only when temp < 10°C outside)

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

A: They are left alone. Heating Control only touches devices that are targeted by an active schedule; everything else stays in the state you set manually.

### Device Assignment Logic

- Devices can be assigned to **multiple schedules**
- If **any** active schedule includes a device, that schedule defines the device's HVAC mode and targets
- Devices not included in any active schedule are left untouched by the integration

## Exposed Entities

### Global Binary Sensors

- `binary_sensor.heating_control_everyone_away` - Are all tracked residents away

### Per-Schedule Binary Sensors

For each schedule configured:
- `binary_sensor.heating_schedule_<schedule_name>` - Is this schedule active

**Attributes:**
- `schedule_name` - Schedule name
- `in_time_window` - Is current time within schedule window
- `presence_ok` - Does presence requirement allow activation
- `hvac_mode` - HVAC mode requested by the schedule
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
- `hvac_mode` - HVAC mode currently requested
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
  Devices: [bedroom_ac, bedroom_ac_2]

Result:
  - Between 22:00-07:00 when someone is home: bedroom ACs on
  - All other times: bedroom ACs off
  - These ACs can also be in other schedules
```

### Scenario 2: Three-Room Morning/Evening Routine

This example mirrors a common setup with three air conditioners (`kitchen`, `bedroom1`, `bedroom2`):

| Start | Name | Devices | Target |
|-------|------|---------|--------|
| 07:00 | Morning Warmup | kitchen, bedroom1, bedroom2 | 20°C |
| 10:00 | Daytime Kitchen | kitchen | 20°C |
| 19:00 | Evening Kitchen | kitchen | 20°C |
| 19:00 | Evening Bedroom2 | bedroom2 | 22°C |
| 21:00 | Night Kitchen | kitchen | 20°C |
| 21:00 | Night Bedroom1 | bedroom1 | 20°C |
| 21:00 | Night Bedroom2 | bedroom2 | 22°C |
| 23:00 | Lights Out | *(no devices)* | — |

How it plays out:

- **07:00 → 10:00**: All three rooms warm up to 20 °C.
- **10:00 → 19:00**: Only the kitchen stays on; bedrooms idle.
- **19:00 → 21:00**: Kitchen stays at 20 °C while bedroom2 gets a 22 °C boost.
- **21:00 → 23:00**: Bedroom1 joins back at 20 °C, bedroom2 remains at 22 °C, kitchen unchanged.
- **After 23:00**: No active schedules, so every unit turns off thanks to the empty "Lights Out" schedule configured with HVAC mode `off`.

This pattern highlights how start-only schedules let you build a day by chaining “what happens next” blocks. If a device should continue past a later start time, create another schedule for it at that moment.

### Scenario 3: Device in Multiple Schedules

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

1. **Schedule Evaluation**: All schedules are evaluated based on current time and presence rules
2. **Decision Building**: Target HVAC state, temperature, and fan mode are computed for every managed climate device (highest temperature wins)
3. **Change Detection**: Decisions are compared against the last command sent to each entity to determine what actually needs to change
4. **Command Dispatch**: HVAC mode, temperature, and fan commands are sent only where differences are detected, with settle delays when toggling HVAC state

### Device Control Logic

- **Turn ON**: When a decision requires the device to heat
  - If the HVAC mode is not already `heat`, send `set_hvac_mode` and wait 5 seconds
  - Apply the target temperature whenever it differs from the previous command
  - Apply the fan mode when it differs and the device supports the requested mode
  - If the HVAC mode changed in this cycle, wait an additional 2 seconds for a final settle

- **Turn OFF**: When no active decision needs the device, send `set_hvac_mode: off`

- **State Tracking**: The coordinator records the last HVAC, temperature, and fan command per entity so the next cycle can skip redundant calls while still reacting to setpoint or fan changes

### Monitoring with Binary Sensors

Binary sensors are provided for monitoring and creating custom notifications or additional automations:

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

**Docker (recommended)**

```bash
docker build -t heating-control-tests .
docker run --rm heating-control-tests
```

**Local environment**

```bash
pip install -r requirements-test.txt
pytest -q
```

### Smart Heating Dashboard

Heating Control **automatically creates** a dashboard when you install the integration. The dashboard appears in your Home Assistant sidebar as **"Smart Heating"** (🌡️ icon) and provides instant access to your heating controls.

#### What's Included

The auto-generated dashboard includes:
- **Thermostat Cards**: For every managed climate device
- **Schedule Grid**: Toggle schedules on/off, see which are active
- **Live Status**: Real-time device states and diagnostics
- **Refresh Button**: Manually trigger coordinator updates
- **Auto-Updates**: Reflects changes when you modify schedules or devices

#### Finding Your Dashboard

After installation:
1. Look in your sidebar for **"Smart Heating"** (🌡️ icon)
2. Click to view your heating dashboard
3. Dashboard updates automatically as your config changes

#### If You Deleted the Dashboard

No problem! You can recreate it manually:

1. Go to *Settings → Dashboards → Add Dashboard*
2. Choose **Strategy**
3. Select **Heating Control: Smart Heating**
4. (Optional) Provide an `entry_id` if you have multiple Heating Control entries

The dashboard will regenerate based on your current configuration.

### Services

Heating Control exposes the `heating_control.set_schedule_enabled` service so automations and dashboards can enable or disable schedules programmatically. Provide either a `schedule_id` (preferred) or `schedule_name`, plus an optional `entry_id` when multiple integration instances exist.

### Example Lovelace YAML

Prefer manual control? The `examples/dashboards/smart_heating_dashboard.yaml` file mirrors the original sample layout. Copy it into a YAML dashboard and adjust the entity IDs for your environment.

### Project Structure

- `__init__.py` - Integration setup and entry point
- `config_flow.py` - Multi-step UI configuration wizard (global settings → devices → schedules)
- `coordinator.py` - Coordinates schedule evaluation and orchestrates control flow
- `models.py` - Dataclasses describing schedule/device decisions and diagnostics
- `controller.py` - Encapsulates climate service calls and device command history
- `binary_sensor.py` - Binary sensor entities (schedule and device sensors)
- `switch.py` - Schedule enable/disable switches
- `sensor.py` - Regular sensor entities for diagnostics
- `const.py` - Constants and configuration keys
- `manifest.json` - Integration metadata
- `strings.json` - UI translations
