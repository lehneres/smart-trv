### Smart TRV Controller — Logic Overview and Parameter Guide

This document summarizes the full control logic of the Smart TRV Controller as implemented in `custom_components/smart_trv/climate.py`, with average-to-low complexity explanations for every key parameter and formula.

---

### 1) High‑level behavior and modes

The controller exposes a single climate entity per room and drives one or more underlying physical TRVs (radiator valves). It operates in three modes:

- OFF: closes the valve immediately (0/255) and resets the controller state.
- HEAT (Boost): fully opens the valve (255/255) for a fixed boost window (default 15 minutes), then returns to AUTO.
- AUTO (normal control): computes a valve command from a PI controller with IMC tuning plus a feed‑forward correction using boiler flow and outdoor temperatures.

To protect TRVs, actual valve updates are throttled: the controller sends at most one update per minute unless an immediate (forced) update is required (OFF/HEAT transitions and a few special cases).

---

### 2) Signals and entities

- Room temperature (current): from a configured temperature `sensor.*`.
- Target temperature (setpoint): stored on the climate entity; adjustable via UI/automations.
- Underlying TRVs: a list of `climate.*` entities that receive commands derived from the controller’s valve output.
- Optional feed‑forward sensors:
  - Outdoor temperature `sensor.*`
  - Boiler flow temperature `sensor.*`

If some TRVs expose a `number.*_valve_position` entity, the controller writes valve position directly; otherwise it emulates valve control by adjusting the TRV’s own target temperature (“virtual setpoint”).

---

### 3) Key parameters (configuration and defaults)

- Temperature band and step
  - `min_temp`, `max_temp`, `precision` (defaults applied internally) define the allowed target range and step.
  - `target_temp` initial target (default 21.0 °C).

- IMC model parameters (per room)
  - `imc_process_gain` (Kp_proc): °C change per unit valve fraction (0..1). Default 4.0.
  - `imc_dead_time` (θ): transport delay [s]. Default 900 s.
  - `imc_time_constant` (τ): dominant process time constant [s]. Default 5400 s.
  - `imc_lambda` (λ): desired closed‑loop time constant [s]. Default 5400 s.

- Feed‑forward configuration (internal defaults used; sensor IDs configurable)
  - Sensors: `outdoor_temperature_sensor`, `boiler_flow_temperature_sensor`.
  - Coefficients and references:
    - `ff_k_flow` (default 0.02 per K), `ff_tflow_ref` (55 °C)
    - `ff_k_outdoor` (0.01 per K), `ff_tout_ref` (10 °C)
  - Robustness (defaults): enable smoothing, EWMA τ for flow (300 s) and outdoor (600 s), deadbands (0.5 K), rate limit 0.05 valve fraction per minute.

- Valve update throttling
  - `VALVE_UPDATE_MIN_INTERVAL_S = 60.0` seconds (max one update per minute unless forced).

- Action reporting
  - `HEATING_ACTION_THRESHOLD = int(0.1 * 255)`; report `heating` only if valve > 10% open (>25 on 0..255 scale), else `idle` in AUTO.

---

### 4) IMC‑based PI controller

The controller uses an Internal Model Control (IMC) approach to compute PI gains from a first‑order plus dead‑time (FOPDT) model of the room:

- Model parameters: process gain `Kp_proc`, time constant `τ`, dead time `θ`.
- Design parameter: `λ` (lambda), the desired closed‑loop time constant.
- Temperature normalization: the controller normalizes the room error to the configured temperature span to keep PI gains consistent across different target ranges.

PI gains are computed as:

```
Kc = (τ · TempRange) / (Kp_proc · (λ + θ))
Ki = TempRange / (Kp_proc · (λ + θ))
```

Where `TempRange = max(0.1, max_temp − min_temp)` to avoid division by zero.

Interpretation:
- Larger `Kp_proc` (room heats easily) yields smaller Kc and Ki (less aggressive PI).
- Larger `τ` or `θ` (sluggish or delayed room) yields larger Kc/Ki denominators; controller becomes slower/milder.
- Larger `λ` slows the closed loop intentionally (more damping/stability).

If any IMC parameter is invalid or missing, IMC is disabled and the valve remains closed in AUTO (fails safe rather than acting unpredictably).

---

### 5) Control loop in AUTO (orchestration)

Each control tick follows the same sequence:

1) Compute error, temperature span, normalized positive error, and `dt`:

```
TempRange = max(0.1, max_temp − min_temp)
error = target_temp − current_temp
norm_error = clamp(error, 0, TempRange) / TempRange  # 0..1 (only positive demand heats)
dt = now − last_update_time  # seconds, or None on first run
```

2) Update feed‑forward (flow/outdoor) including smoothing and rate limit (see next section) to obtain `u_ff_raw` and `u_ff`.

3) Classify the operating region around the setpoint using a small symmetric steady‑state deadband `ε` (default 0.2 °C):

```
in_band  = |error| ≤ ε
heat_side = error >  ε     # clearly below target (cold side)
cool_side = error < −ε     # clearly above target (warm side)
```

4) Update the integral state (integral separation with improved anti-windup):

```
if dt > 0:
    u_p = Kc · norm_error
    u_i = Ki · i_accum
    u_pi_est = u_p + u_i
    u_total_est = u_pi_est + u_ff  # include feed-forward in saturation check

    if heat_side:
        # Anti-windup: only accumulate if neither PI nor total output is saturated
        if u_pi_est < 1.0 and u_total_est < 1.0:
            i_accum += norm_error · dt
    elif cool_side:
        # Bleed integral when clearly above target
        # Bleed rate is computed dynamically: 1/(3·τ) where τ is IMC time constant
        # This bleeds the integral fully in ~3·τ seconds (e.g., ~4.5 hours for τ=5400s)
        i_accum = max(0, i_accum − bleed_rate_per_s · dt)
    else:
        # in_band: freeze integral (no growth, no bleed)
        pass
prev_norm_error = norm_error
```

Note: The bleed rate is computed dynamically from the IMC time constant as `1/(3·τ)` to ensure the integral bleeds at a rate appropriate for the thermal system's dynamics. For the default τ=5400s, this gives a bleed rate of ~0.00006/s.

5) Form PI output (feedback only):

```
u_pi = Kc · norm_error + Ki · i_accum
```

6) Decide the final command `u_total` using soft blending around the setpoint and cool‑side decay (details in section 7):

```
prev_u   = clamp(last_desired_valve/255, 0, 1)
u_heat   = clamp(u_pi + u_ff, 0, 1)

eps_blend = steady_deadband_c  # default 0.2 °C
if eps_blend > 0 and |error| ≤ eps_blend:
    # Smoothly blend cool→heat over the blend zone using smoothstep weight w ∈ [0,1]
    x = clamp((error + eps_blend) / (2·eps_blend), 0, 1)
    w = x² · (3 − 2x)
    # Decay component toward closed
    alpha = 1 − exp(−dt / decay_tau_s)          # default decay_tau_s = 3600 s
    u_decay = max(0, prev_u + alpha · (0 − prev_u))
    u_total = clamp(w · u_heat + (1 − w) · u_decay, 0, 1)
elif heat_side:
    # Clearly below target → track heating suggestion
    u_total = u_heat
else:
    # Cool side (or warm side outside blend) → decay to closed
    alpha = 1 − exp(−dt / decay_tau_s)
    u_total = max(0, prev_u + alpha · (0 − prev_u))
```

7) Map to valve position and request a (possibly throttled) update:

```
valve_position = round(u_total · 255)
```

---

### 6) Feed‑forward path (flow + outdoor) with robustness

A feed‑forward term nudges the valve based on measured boiler flow and outdoor temperature deviations from reference operating points. It aims to compensate predictable disturbances (e.g., reduced night flow temperature) so PI doesn’t have to correct it all.

1) Filter raw sensor readings with EWMA (if enabled):

```
# Per sensor (boiler flow, outdoor)
alpha = 1 − exp(−dt / τ)
filtered = prev is None ? value : prev + alpha · (value − prev)
```

2) Compute deviations with deadbands:

```
ΔT_flow = (Tflow_ref − Tflow_filtered)  → apply deadband ±db_flow
ΔT_out  = (Tout_ref  − Tout_filtered)   → apply deadband ±db_out
# Deadband function:
apply_deadband(x, db) = 0               if |x| ≤ db
                      = x − db          if x > db
                      = x + db          if x < −db
```

3) Raw feed‑forward contribution:

```
u_ff_raw = ff_k_flow · ΔT_flow + ff_k_outdoor · ΔT_out
```

4) Combine with PI and clamp:

```
u_total = clamp(u + u_ff, 0, 1)
```

5) Convert to valve steps (0..255):

```
valve_position = round(u_total · 255)
```

Notes:
- If a sensor is missing/unavailable, that term contributes zero (graceful degradation).
- Defaults are conservative: small `k` gains, moderate EWMA filtering, and small deadbands to ignore jitter.

---

### 7) Near‑setpoint steady‑state behavior (soft blending and decay)

To avoid on/off chattering and to maintain comfort tightly around the setpoint, the controller uses a soft blending zone of half‑width `ε` around the setpoint:

- Blend zone `ε` (default 0.2 °C): within `|error| ≤ ε`, the final command is a smooth blend between
  the heating suggestion (PI+FF) and a decay‑to‑close component. This ensures continuity and avoids
  abrupt flips as error crosses zero.
- Cool/warm side outside the blend: any positive opening decays exponentially toward fully closed
  (target 0), minimizing overshoot when the room is at or above target.
- Integral hygiene: integral is updated with separation and gentle bleed on the warm side as described in section 5.

Defaults (from `const.py`):
- `DEFAULT_STEADY_DEADBAND_C = 0.2`
- `DEFAULT_DECAY_TAU_S = 600.0` (10 minutes)

Notes:
- These are internal defaults and not exposed in the user configuration flow.

---

### 8) Valve update throttling

To avoid chattering and device wear, updates to physical TRVs are limited:

- Immediate (forced) updates on OFF or HEAT transitions, and at initial conditions.
- Otherwise, at most one update per `VALVE_UPDATE_MIN_INTERVAL_S = 60` seconds. If the controller computes multiple valve positions within a minute, it retains the latest desired value and sends it on the next allowed opportunity.

Internally, the controller tracks:
- `_last_valve_send_monotonic`: time of last successful send
- `_desired_valve_position`: latest computed request (coalesced until send allowed)

---

### 9) Driving underlying TRVs

For each target TRV:

- Preferred: if a `number.*_valve_position` entity exists, call `number.set_value` with the valve position (0..255).
- Fallback: emulate valve via a “virtual setpoint” on the TRV:

```
TempRange = max_temp − min_temp
virtual_setpoint = min_temp + (valve_position / 255) · TempRange
# Ensure TRV is in HEAT if non‑zero; set HVAC OFF when valve_position == 0
```

This fallback lets the controller bias the TRV’s own built‑in control to approximate a target valve opening even when direct valve control is unavailable.

---

### 10) HVAC action reporting

- `OFF` mode → `hvac_action = off`.
- `AUTO/HEAT` → `heating` only when `valve_position > 10% of 255` (i.e., >25), otherwise `idle`.

This prevents the UI from flickering between heating/idle due to minor valve corrections.

---

### 11) Boost (HEAT) handling

- Entering HEAT immediately forces the valve fully open (255) and starts a 15‑minute timer.
- When the timer elapses (or HEAT is turned off), the controller returns to AUTO.

---

### 12) Open window detection

The controller includes automatic open window detection to prevent wasting energy when a window is opened:

- Detection: monitors the rate of temperature change. If temperature drops faster than `window_open_threshold_per_min` (default 0.3 K/min), window open mode is triggered.
- Response: immediately closes the valve (position 0) and resets the integral accumulator to avoid stale integral buildup.
- Duration: heating is suppressed for `window_open_duration` seconds (default 900s = 15 minutes).
- After the suppression period expires, normal control resumes automatically.

The `window_open` attribute in entity state indicates whether window open mode is currently active.

Configuration parameters (from `const.py`):
- `CONF_WINDOW_OPEN_THRESHOLD_PER_MIN`: temperature drop rate threshold (K/min)
- `CONF_WINDOW_OPEN_DURATION`: suppression duration (seconds)
- `DEFAULT_WINDOW_OPEN_THRESHOLD_PER_MIN = 0.3`
- `DEFAULT_WINDOW_OPEN_DURATION = 900.0`

Notes:
- Checks are rate-limited (minimum 30s between checks) to avoid noise amplification.
- The threshold is applied as an absolute value; only temperature drops (negative rate) trigger detection.

---

### 13) State restoration and safety

- On HA restart, the climate entity restores the previous HVAC mode and target temperature if available, subscribes to sensors, refreshes readings, and immediately re‑evaluates control.
- Robustness: if the current temperature is missing/unavailable, the controller defers control (no valve changes) and logs a debug message.
- IMC validity checks: if computed gains are invalid (e.g., non‑positive), control in AUTO is disabled and the valve is kept closed; errors are logged to prompt correction.
- Window open detection: resets integral accumulator to prevent stale buildup during suppression period.

---

### 14) Parameter glossary (quick reference)

- Targeting
  - `target_temp` (°C): desired room temp.
  - `min_temp`, `max_temp` (°C): allowed range for target.
  - `precision` (°C): UI step size for target.

- IMC (process model + design)
  - `imc_process_gain` (Kp_proc, °C per valve fraction)
  - `imc_dead_time` (θ, s)
  - `imc_time_constant` (τ, s)
  - `imc_lambda` (λ, s)
  - Derived PI: `Kc`, `Ki` as above.

- Feed‑forward
  - `ff_k_flow` (per K), `ff_tflow_ref` (°C)
  - `ff_k_outdoor` (per K), `ff_tout_ref` (°C)
  - `ff_enable_smoothing` (bool)
  - `ff_flow_filter_tau_s`, `ff_outdoor_filter_tau_s` (s)
  - `ff_flow_deadband_k`, `ff_outdoor_deadband_k` (K)
  - `ff_rate_limit_per_min` (fraction/min)

- Valve and actions
  - `VALVE_OPEN_POSITION = 255`, `VALVE_CLOSED_POSITION = 0`
  - `VALVE_UPDATE_MIN_INTERVAL_S = 60 s`
  - `HEATING_ACTION_THRESHOLD ≈ 26` (10% of 255)

- Window detection
  - `window_open_threshold_per_min` (K/min, default 0.3)
  - `window_open_duration` (s, default 900)

---

### 15) Practical tuning guidance

- Start with defaults: Kp_proc=4, θ=900 s, τ=5400 s, λ=5400 s. These are stable for most radiator systems.
- If the room is too slow: reduce λ (e.g., 3600 s) gradually; watch for overshoot.
- If the room overshoots or oscillates: increase λ (slower), or check that Kp_proc is not underestimated.
- Feed‑forward: if nights run cooler (flow temp drops), consider slightly increasing `ff_k_flow`; keep smoothing (τ) and rate‑limit conservative to avoid noise‑induced jitter.

---

### 16) Summary formula block

```
# Normalized error
TempRange = max(0.1, max_temp − min_temp)
error = target_temp − current_temp
norm_error = clamp(error, 0, TempRange) / TempRange

# IMC gains
Kc = (τ · TempRange) / (Kp_proc · (λ + θ))
Ki = TempRange / (Kp_proc · (λ + θ))

# PI with improved anti‑windup + integral separation
# bleed_rate_per_s = 1/(3·τ)  # computed dynamically from IMC time constant
if dt > 0:
    u_p = Kc · norm_error
    u_i = Ki · i_accum
    u_pi_est = u_p + u_i
    u_total_est = u_pi_est + u_ff
    if heat_side and u_pi_est < 1.0 and u_total_est < 1.0:
        i_accum += norm_error · dt
    elif cool_side:
        i_accum = max(0, i_accum − bleed_rate_per_s · dt)
    # in_band: freeze integral
u_pi = Kc · norm_error + Ki · i_accum

# Feed‑forward
Tflow_dev = deadband(Tflow_ref − Tflow_filt, db_flow)
Tout_dev  = deadband(Tout_ref  − Tout_filt,  db_out)
u_ff_raw  = ff_k_flow · Tflow_dev + ff_k_outdoor · Tout_dev
du_limit  = (ff_rate_limit_per_min / 60) · dt
du        = u_ff_raw − u_ff_prev
u_ff      = u_ff_prev + clamp(du, −du_limit, +du_limit)
u_ff_prev = clamp(u_ff, −1, +1)

# Band logic near setpoint
in_band  = |error| ≤ ε
heat_side = error >  ε
cool_side = error < −ε

if heat_side:
    u_total = clamp(u_pi + u_ff, 0, 1)
elif in_band:
    floor = max(u_min_keepalive, max(0, u_ff))
    prev_u = clamp(last_desired_valve/255, 0, 1)
    if error < 0 and dt > 0:
        alpha = 1 − exp(−dt / decay_tau_s)
        u_total = prev_u + alpha · (max(floor,0) − prev_u)
    else:
        u_total = max(floor, min(prev_u, clamp(u_pi + u_ff, 0, 1)))
else:
    u_total = clamp(max(0, u_ff), 0, 1)

valve_position = round(u_total · 255)
```

This encapsulates the complete control philosophy: a normalized, IMC‑tuned PI loop for feedback stability, enhanced by a robust, smoothed, and rate‑limited feed‑forward that anticipates predictable thermal disturbances, all while respecting actuation limits and update throttling to keep TRV hardware healthy.
