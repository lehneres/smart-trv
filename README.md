# Smart TRV Controller

A custom Home Assistant integration that exposes a climate entity and controls one or more TRVs (Thermostatic Radiator Valves) in a room using a room temperature sensor, IMC‑tuned PI control, and optional feed‑forward from boiler flow and outdoor temperature.

## Features

- Room temperature–based control using any HA temperature sensor
- IMC/Lambda PI control with automatic gains (`imc_kc`, `imc_ki`) derived from process parameters
- Optional feed‑forward from boiler flow and outdoor temperature with EWMA filtering
- Soft blending around the setpoint to avoid abrupt flips: smoothly transitions between heating and decay‑to‑close within a small band
- Cool‑side handling that minimizes overshoot: when at/above target, any positive valve opening decays toward closed
- Open window detection: automatically closes valves when rapid temperature drops are detected
- Multi‑TRV control: coordinate several TRV climate entities as one room controller
- State persistence across restarts (target temperature, HVAC mode)
- Sensible throttling: minimum interval between valve updates to reduce chatter
- Clear diagnostics (rounded to two decimals) for tuning and analysis

## Installation

### HACS (if you use a custom repository)

1. Open HACS → Integrations
2. Three‑dots menu → Custom repositories
3. Add this repository URL as type “Integration”
4. Install “Smart TRV Controller”
5. Restart Home Assistant

### Manual installation

1. Copy `custom_components/smart_trv` to your HA `/config/custom_components/`
2. Restart Home Assistant

## Configuration

Add the integration via HA UI: Settings → Devices & Services → Add Integration → “Smart TRV Controller”.

Provide:
- Name
- Room temperature sensor entity
- One or more TRV climate entities to control
- Min/Max temperature, default target, precision

Advanced options (exposed as options in the integration):
- IMC (process model and closed‑loop target)
  - `imc_process_gain` (Kp_proc, °C per valve fraction)
  - `imc_dead_time` (s)
  - `imc_time_constant` (s)
  - `imc_lambda` (desired closed‑loop time constant, s)
- Feed‑forward (optional sensors and coefficients)
  - `outdoor_temperature_sensor`
  - `boiler_flow_temperature_sensor`
  - `ff_k_flow`, `ff_k_outdoor`, `ff_tflow_ref`, `ff_tout_ref`
  - Smoothing/robustness: `ff_enable_smoothing`, `ff_flow_filter_tau_s`, `ff_outdoor_filter_tau_s`, `ff_flow_deadband_k`, `ff_outdoor_deadband_k`
- Open window detection
  - `window_open_threshold_per_min` (K/min, default 0.3): temperature drop rate that triggers window open mode
  - `window_open_duration` (s, default 900): how long to suppress heating after detection

Operational behavior:
- Valve command range is 0–255 (closed…open).
- HVAC action reports HEATING only when valve position > 10% (positions 26–255), otherwise IDLE.
- A minimum update interval is enforced to avoid excessive commands to underlying TRVs.

## How it works (high‑level)

- The controller computes a desired valve fraction from the temperature error using IMC‑tuned PI gains. Optional feed‑forward nudges the command based on boiler flow/outdoor conditions. Around the setpoint, a soft blending zone (default half‑width 0.2 °C) smoothly transitions between the heating suggestion and an exponential decay‑to‑close, avoiding step changes. Commands are combined, saturated and mapped to 0–255, then frequency‑limited before being applied to member TRVs.
- If feed‑forward sensors are not configured, the controller operates purely on the temperature feedback path.

## Entity attributes

The climate entity exposes these base attributes:

| Attribute | Description |
|-----------|-------------|
| `valve_position` | Current valve command (0–255) applied to the group |
| `room_temperature` | Current room temperature from the selected sensor |
| `trv_entities` | List of controlled TRV climate entities |

### Diagnostics (extra state attributes)
In addition to the basic attributes above, the integration publishes diagnostic metrics to help tune and observe the controller. All numeric diagnostics are rounded to two decimals for readability.

| Attribute | Description |
|-----------|-------------|
| `desired_valve_position` | Internal target valve command (0–255) before throttling/hysteresis. |
| `imc_kc` | Proportional gain computed from IMC tuning. |
| `imc_ki` | Integral gain (per second) computed from IMC tuning. |
| (removed) | The `imc_valid` diagnostic has been removed. IMC parameters are now mandatory and gains are always computed. |
| `controller_error_c` | Control error in °C (`target_temperature - measured_temperature`). |
| `controller_error_norm` | Normalized control error (unitless). |
| `controller_u_pi` | PI controller output (fraction 0–1) before feed‑forward/limits. |
| `controller_u_i` | Integral-only contribution to PI output (`Ki * integral_state`, fraction 0–1). Helps analyze how much the integrator is driving the valve. |
| `controller_u_ff` | Feed‑forward after smoothing (fraction 0–1). |
| `controller_u_total` | Combined PI + feed‑forward (fraction 0–1) before mapping to 0–255. |
| `filtered_flow_temperature` | Boiler flow temperature after EWMA filtering (°C). |
| `filtered_outdoor_temperature` | Outdoor temperature after EWMA filtering (°C). |
| `window_open` | Whether open window mode is currently active (rapid temperature drop detected). |

Notes:
- Diagnostics are for analysis/visualization. The stable interface is the standard climate properties and `valve_position`.
- Rounding is for display only; values remain numeric in HA state attributes.

## Further details

For a deeper explanation of the control logic, defaults, and tuning guidance, see `documentation/controller_logic.md`.

## Example automation

```yaml
automation:
  - alias: "Boost heating when coming home"
    trigger:
      - platform: state
        entity_id: person.john
        to: "home"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.smart_living_room_trv
        data:
          temperature: 22
```

## Troubleshooting

- TRV not responding
  - Ensure TRV climate entities are available and not in an error/manual/locked state
  - Verify the integration has permission to control these entities
- Temperature not updating
  - Verify the selected room sensor exists and reports numeric Celsius values
- Valve position seems off
  - Check realistic min/max temperature bounds
  - Review diagnostics (`controller_error_c`, `controller_u_*`) to understand decisions