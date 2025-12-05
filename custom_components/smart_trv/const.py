"""Constants for the Smart TRV Controller integration."""

DOMAIN = "smart_trv"

# Configuration keys
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_TRV_ENTITIES = "trv_entities"
CONF_NAME = "name"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP = "target_temp"
CONF_PRECISION = "precision"

# Optional feed-forward sensors and coefficients
CONF_OUTDOOR_TEMPERATURE_SENSOR = "outdoor_temperature_sensor"
CONF_BOILER_FLOW_TEMPERATURE_SENSOR = "boiler_flow_temperature_sensor"
CONF_FF_K_FLOW = "ff_k_flow"  # feed-forward gain per K of flow temperature delta
CONF_FF_K_OUTDOOR = "ff_k_outdoor"  # feed-forward gain per K of outdoor temp delta
CONF_FF_TFLOW_REF = "ff_tflow_ref"  # reference flow temperature [°C]
CONF_FF_TOUT_REF = "ff_tout_ref"  # reference outdoor temperature [°C]

# Feed-forward robustness and smoothing options
CONF_FF_ENABLE_SMOOTHING = "ff_enable_smoothing"  # master toggle for FF smoothing
CONF_FF_FLOW_FILTER_TAU_S = "ff_flow_filter_tau_s"  # EWMA time constant for boiler flow [s]
CONF_FF_OUTDOOR_FILTER_TAU_S = "ff_outdoor_filter_tau_s"  # EWMA time constant for outdoor [s]
CONF_FF_FLOW_DEADBAND_K = "ff_flow_deadband_k"  # ignore small |ΔTflow| around 0
CONF_FF_OUTDOOR_DEADBAND_K = "ff_outdoor_deadband_k"  # ignore small |ΔTout| around 0

# Default values
DEFAULT_NAME = "Smart TRV"
DEFAULT_MIN_TEMP = 5.0
DEFAULT_MAX_TEMP = 28.0
DEFAULT_TARGET_TEMP = 21.0
DEFAULT_PRECISION = 0.5

# Feed-forward sensible defaults
# These provide a gentle adjustment of the valve command based on boiler flow and
# outdoor temperature deviations from nominal operating points.
DEFAULT_FF_K_FLOW = 0.02        # +0.02 valve fraction per 1 K flow below reference
DEFAULT_FF_K_OUTDOOR = 0.01     # +0.01 valve fraction per 1 K colder than reference
# IMPORTANT: The reference temperatures below should be calibrated to your typical
# operating conditions to avoid a constant bias in the feed-forward term.
# - FF_TFLOW_REF: Set to your boiler's typical flow temperature during normal heating.
#   If actual flow is typically 45°C but reference is 55°C, FF will always add ~+0.2.
# - FF_TOUT_REF: Set to your region's typical outdoor temperature during heating season.
#   If actual outdoor temp is typically 5°C but reference is 10°C, FF will always add ~+0.05.
DEFAULT_FF_TFLOW_REF = 55.0     # Typical radiator flow setpoint [°C] - calibrate to your system
DEFAULT_FF_TOUT_REF = 10.0      # Mild outdoor temperature [°C] - calibrate to your region

# Smoothing defaults to prevent overreaction to fast boiler flow swings
DEFAULT_FF_ENABLE_SMOOTHING = True
DEFAULT_FF_FLOW_FILTER_TAU_S = 300.0      # 5 minutes EWMA on boiler flow
DEFAULT_FF_OUTDOOR_FILTER_TAU_S = 600.0   # 10 minutes EWMA on outdoor
DEFAULT_FF_FLOW_DEADBAND_K = 0.5          # ignore ±0.5 K around zero delta
DEFAULT_FF_OUTDOOR_DEADBAND_K = 0.5       # ignore ±0.5 K around zero delta

# Valve control constants
VALVE_OPEN_POSITION = 255
VALVE_CLOSED_POSITION = 0

# Minimum interval between issuing valve updates to underlying TRVs (seconds)
# Requirement: update valve position only on demand or max once per minute.
VALVE_UPDATE_MIN_INTERVAL_S = 60.0

# Threshold for reporting HEATING hvac_action based on valve opening.
# Requirement: return HEATING only when valve position > 10% of full scale.
# With 0–255 scale, 10% is 25.5, so integer positions 26..255 should be HEATING.
# Comparing `> HEATING_ACTION_THRESHOLD` where threshold=int(0.1*255)=25 achieves that.
HEATING_ACTION_THRESHOLD = int(0.10 * VALVE_OPEN_POSITION)

# IMC/Lambda tuning parameters (compute PI gains from process model)
CONF_IMC_PROCESS_GAIN = "imc_process_gain"  # Kp_proc [°C per unit valve fraction]
CONF_IMC_DEAD_TIME = "imc_dead_time"  # theta [s]
CONF_IMC_TIME_CONSTANT = "imc_time_constant"  # tau [s]
CONF_IMC_LAMBDA = "imc_lambda"  # desired closed-loop time constant [s]

# Defaults for IMC/Lambda tuning parameters
# These provide sensible starting points for typical radiator/TRV systems.
# Kp_proc relates valve opening (0..1) to steady-state temperature change [°C].
DEFAULT_IMC_PROCESS_GAIN = 4.0
# Dead time (transport delay) in seconds
DEFAULT_IMC_DEAD_TIME = 900.0          # 15 minutes
# Process time constant (dominant) in seconds
DEFAULT_IMC_TIME_CONSTANT = 5400.0     # 90 minutes
# Desired closed-loop time constant (often chosen similar to tau)
DEFAULT_IMC_LAMBDA = 5400.0            # 90 minutes

# Steady-state handling near setpoint (internal defaults; not exposed via config flow)
# - small symmetric band around the target used for soft blending between "heat" and
#   "decay-to-close" behaviors (see climate._decide_u_total)
# - note: the earlier "keep-alive" floor strategy is no longer used by the controller
#   logic; the constant is retained for compatibility and potential future tuning,
#   but soft blending + exponential decay toward 0 is the current behavior.
DEFAULT_STEADY_DEADBAND_C = 0.5       # °C
DEFAULT_DECAY_TAU_S = 900.0          # seconds
# Integral bleed rate when clearly above target is computed dynamically in
# climate.py as 1/(3*tau) where tau is the IMC time constant.

# Open Window Detection Defaults
CONF_WINDOW_OPEN_THRESHOLD_PER_MIN = "window_open_threshold_per_min"  # K/min
CONF_WINDOW_OPEN_DURATION = "window_open_duration"  # seconds
DEFAULT_WINDOW_OPEN_THRESHOLD_PER_MIN = 1.0
DEFAULT_WINDOW_OPEN_DURATION = 900.0  # 15 minutes

# Legacy PID defaults removed; IMC is the only control strategy

# Attributes
ATTR_VALVE_POSITION = "valve_position"
ATTR_ROOM_TEMPERATURE = "room_temperature"
ATTR_TRV_ENTITIES = "trv_entities"
# New: actual valve reading from underlying TRVs (max across all where available)
ATTR_ACTUAL_VALVE_POSITION = "actual_valve_position"

# Diagnostic attribute keys (for optimization/analysis)
ATTR_DESIRED_VALVE_POSITION = "desired_valve_position"
ATTR_ERROR_C = "controller_error_c"
ATTR_ERROR_NORM = "controller_error_norm"
ATTR_U_PI = "controller_u_pi"
ATTR_U_FF = "controller_u_ff"  # feed-forward after smoothing
ATTR_U_TOTAL = "controller_u_total"
# New: Integral-only contribution of PI controller (Ki * integral state)
ATTR_U_I = "controller_u_i"
ATTR_FLOW_FILTERED = "filtered_flow_temperature"
ATTR_OUTDOOR_FILTERED = "filtered_outdoor_temperature"
ATTR_IMC_KC = "imc_kc"
ATTR_IMC_KI = "imc_ki"
ATTR_WINDOW_OPEN = "window_open"

# Controller timing and safety constants
# Minimum floor for temperature range used in normalization (to avoid divide by zero)
MIN_TEMP_RANGE_C = 0.1
# Minimum interval between successive window-rate checks to reduce noise amplification
WINDOW_CHECK_MIN_INTERVAL_S = 30.0
# Default boost duration for HVACMode.HEAT (seconds)
DEFAULT_BOOST_DURATION_S = 15 * 60
