# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant custom integration that automatically controls climate devices (heaters, air conditioners) based on schedules, presence detection, and time-based rules. The integration directly manages HVAC devices without requiring additional automations.

## Development Commands

### Testing

```bash
# Run tests locally
pip install -r requirements-test.txt
pytest

# Run tests in Docker (recommended)
docker build -t heating-control-tests .
docker run --rm -v "$(pwd)":/app heating-control-tests

# Run specific test file
pytest tests/test_config_flow_schedule_management.py

# Run with verbose output
pytest -v
```

### Home Assistant Integration

This is a custom component for Home Assistant. To test in a live environment:

1. Copy `custom_components/heating_control` to your Home Assistant `custom_components` folder
2. Restart Home Assistant
3. Add integration via Settings > Devices & Services > Add Integration > "Heating Control"

## Architecture Overview

### Core Decision Flow

The integration follows a clear decision pipeline that runs every 60 seconds:

```
Coordinator (_async_update_data)
    ↓
1. Calculate State (_calculate_heating_state)
   - Evaluate presence (anyone_home, everyone_away)
   - Evaluate all schedules → ScheduleDecisions
   - Aggregate per-device → DeviceDecisions
    ↓
2. Detect State Transitions (_detect_state_transitions)
   - Compare schedule active states vs previous cycle
   - Compare presence state vs previous cycle
   - If changed: trigger control application
    ↓
3. Apply Control (ClimateController.async_apply)
   - For each device: compare decision vs last command sent
   - Only send commands when state/temp/fan changes
   - Handle HVAC settle delays (5s after mode change, 2s final settle)
```

### Key Components

**`coordinator.py`** - The brain of the integration
- `HeatingControlCoordinator`: DataUpdateCoordinator that orchestrates the entire decision pipeline
- `_calculate_heating_state()`: Pure calculation function that evaluates schedules and builds decisions
- `_derive_auto_end_times()`: Calculates when schedules end based on per-device timelines
- `_detect_state_transitions()`: Determines if control application is needed (presence/schedule changes)
- Schedule evaluation uses "most recent start time wins" precedence when multiple schedules target same device

**`controller.py`** - Service call orchestration
- `ClimateController`: Encapsulates all Home Assistant climate service calls
- Tracks last command sent per device to avoid redundant calls
- Handles settle delays when toggling HVAC modes
- `_apply_device()`: Applies decisions with change detection (HVAC mode, temperature, fan)

**`models.py`** - Immutable data structures
- `HeatingStateSnapshot`: Complete state for one decision cycle
- `ScheduleDecision`: Per-schedule evaluation result
- `DeviceDecision`: Per-device target state (hvac_mode, temp, fan)
- `DiagnosticsSnapshot`: Metadata for debugging

**`config_flow.py`** - Multi-step configuration wizard
- Step 1: Global settings (device trackers, auto heating toggle)
- Step 2: Select climate devices to manage
- Step 3: Manage schedules (add/edit/delete)
- Schedule management includes validation and confirmation dialogs

**`binary_sensor.py`, `sensor.py`, `switch.py`** - Entity platform implementations
- Per-schedule binary sensors: shows if schedule is active
- Per-device binary sensors: shows if device should be active
- Global sensors: diagnostics, presence state
- Schedule switches: enable/disable individual schedules

**`dashboard.py`** - Auto-generated Lovelace dashboard
- `HeatingControlDashboardStrategy`: Generates single-column layout
- Shows thermostat cards, schedule status, diagnostics
- Automatically created on integration setup

### Schedule Precedence Logic

**Critical concept**: When multiple schedules target the same device, the **most recently started schedule** takes full control. This is implemented via `start_age` calculation in coordinator.py:

```python
start_age = (now_minutes - start_value) % MINUTES_PER_DAY
# Lower start_age = more recent schedule
# Selection: freshness = MINUTES_PER_DAY - start_age
# max(entries, key=freshness) → most recent wins
```

### Automatic End Time Derivation

Schedules without explicit end times use per-device timeline analysis:
1. Build timeline per device with all schedule start times
2. For each device: schedule ends when next schedule starts
3. For multi-device schedules: use LATEST end time across all devices
4. This allows overlapping schedules for different devices while maintaining sequential control per device

### State Transition Detection

Control is only applied when state changes (not every 60 seconds):
- Schedule activation/deactivation (time window changes)
- Presence changes (someone arrives/leaves)
- Configuration changes (via `force_update_on_next_refresh()`)
- First run initialization

This preserves manual user adjustments between transitions.

### Climate Control Commands

The controller tracks last command per entity and only sends changes:
1. **HVAC mode change**: Send `set_hvac_mode`, wait 5s settle
2. **Temperature change**: Send `set_temperature` (even if already on)
3. **Fan mode change**: Send `set_fan_mode` (if supported by device)
4. **Final settle**: Wait 2s after HVAC mode changes

## Configuration Structure

Configuration is stored in `config_entry.data` or `config_entry.options`:

```python
{
    "device_trackers": ["device_tracker.person1", "device_tracker.person2"],
    "automatic_heating_enabled": True,
    "climate_devices": ["climate.bedroom_ac", "climate.kitchen_ac"],
    "schedules": [
        {
            "id": "uuid-string",  # Unique identifier (preserved during edits)
            "name": "Morning Warmup",
            "enabled": True,
            "start_time": "07:00",
            "end_time": "10:00",  # Optional, auto-calculated if omitted
            "hvac_mode": "heat",  # or "cool", "off"
            "only_when_home": True,
            "schedule_device_trackers": [],  # Optional per-schedule trackers
            "away_hvac_mode": "off",  # Optional away mode
            "away_temperature": 18.0,  # Optional away temp
            "temperature": 20.0,
            "fan_mode": "auto",
            "device_entities": ["climate.bedroom_ac"]
        }
    ]
}
```

## Testing Philosophy

See `tests/TEST_DOCUMENTATION.md` for comprehensive testing documentation.

Key test suites:
- **test_config_flow_schedule_management.py**: 19 tests covering add/edit/delete schedules with edge cases
- **test_climate_controller.py**: Controller command logic and settle delays
- **test_state_transitions.py**: Coordinator state transition detection
- **test_calculate_heating_state.py**: Schedule evaluation and decision building
- **test_dashboard_strategy.py**: Dashboard layout generation

Tests use `pytest` with `pytest-asyncio` and mock Home Assistant core.

## Important Implementation Notes

### Schedule ID Preservation

**Critical**: When editing schedules, preserve the `id` field to maintain sensor continuity. Binary sensors use schedule ID for entity naming. Changing IDs breaks historical data and sensor references.

```python
# CORRECT: Preserve ID during edit
schedule_config["id"] = self._schedules[index].get("id", str(uuid.uuid4()))

# WRONG: Generate new ID
schedule_config["id"] = str(uuid.uuid4())  # This breaks sensors!
```

### Presence Logic

- Global trackers: `device_trackers` in config
- Per-schedule trackers: `schedule_device_trackers` in schedule config
- Per-schedule trackers override global presence for that schedule
- No trackers configured = assume always home (schedules always eligible)

### Away Mode Behavior

Each schedule can define optional away settings:
- If `away_hvac_mode` and `away_temperature` are set: use when nobody home
- If only `only_when_home=True`: turn devices off when away
- If `only_when_home=False` and no away settings: use home settings even when away

### Dashboard Auto-Creation

The integration automatically creates a dashboard on setup:
- Dashboard URL stored in `config_entry.data["dashboard_url"]`
- Uses Lovelace strategy pattern (`custom:heating_control-smart-heating`)
- Falls back to storage-mode for older Home Assistant versions
- Dashboard removed automatically on integration uninstall

### Services

`heating_control.set_schedule_enabled` - Enable/disable schedules programmatically
- Parameters: `entry_id` (optional), `schedule_id` or `schedule_name`, `enabled` (bool)
- Persists to config_entry and triggers `force_update` for immediate application

### Schedule Selection Bug Fix (2025-01)

**Issue**: Dashboard could show the wrong active schedule for a device, potentially displaying a future schedule that hasn't started yet or a schedule that's no longer in its time window.

**Root Cause**: The `_select_device_targets()` function in coordinator.py selected schedules based on "freshness" (most recent start time) but didn't validate that the current time was actually within the selected schedule's time window. This created edge cases where:
- Schedule end times derived via `_derive_auto_end_times()` might not be perfectly synchronized with the selection logic
- Boundary conditions at schedule transitions could select the wrong schedule momentarily
- The dashboard would display incorrect "Active Schedule" information for devices

**Fix Applied** (coordinator.py lines 541-614):
1. Added `start_time` and `end_time` to device_builder entries (line 498-499)
2. Modified `_select_device_targets()` to accept `now_hm` parameter
3. Added explicit time window validation before schedule selection using `_is_time_in_schedule()`
4. Filter out any schedules not currently in their time window before picking the "best" one
5. Added debug logging to trace schedule selection decisions

**Validation**: All 53 existing tests continue to pass, confirming no regressions.

### Dashboard Presence Indicator Bug Fix (2025-01)

**Issue**: Dashboard schedule cards showed inverted presence indicators:
- Showed ✖ (X mark) when people were home
- Showed ✓ (check mark) when nobody was home

**Root Cause**: The `_format_schedule_label()` function in dashboard.py (line 640) had inverted logic checking `if not decision.presence_ok` instead of `if decision.presence_ok`.

The `presence_ok` field means "presence requirement is satisfied" (True = someone is home when required, or home not required). The dashboard was displaying the opposite of what it should.

**Fix Applied** (dashboard.py lines 638-644):
Changed from:
```python
if not decision.presence_ok and decision.enabled:
    presence_status += " ❌"
else:
    presence_status += " ✓"
```

To:
```python
if decision.presence_ok:
    presence_status += " ✓"
elif decision.enabled:
    presence_status += " ❌"
```

This now matches the correct logic already present in lines 498-501 of the same file.

**Validation**: All 53 existing tests continue to pass.

## Code Patterns to Follow

### Error Handling in Config Flow

Always validate indices before array access:
```python
if self._schedule_index is None or not (0 <= self._schedule_index < len(self._schedules)):
    _LOGGER.error("Invalid schedule index: %s", self._schedule_index)
    self._schedule_index = None
    return await self.async_step_manage_schedules()
```

### Coordinator Update Pattern

Keep calculation and application separate:
```python
snapshot = await self.hass.async_add_executor_job(self._calculate_heating_state)
if self._detect_state_transitions(snapshot):
    await self._controller.async_apply(snapshot.device_decisions.values())
```

### Service Call Pattern

Always use `blocking=True` for climate commands to ensure sequential execution:
```python
await self._hass.services.async_call(
    "climate",
    "set_hvac_mode",
    {"entity_id": entity_id, "hvac_mode": hvac_mode},
    blocking=True,
)
```

## Version Information

- Home Assistant: 2024.4.4 (minimum)
- Config Version: 2.1
- Version 1 configs are incompatible and trigger reconfiguration flow
