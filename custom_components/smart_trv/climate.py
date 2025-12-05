"""Climate platform for Smart TRV Controller."""
from __future__ import annotations

import logging
import math
import time
from typing import Any

from homeassistant.components.climate import (ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode, )
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (ATTR_TEMPERATURE, CONF_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature, )
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_call_later
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (ATTR_ROOM_TEMPERATURE, ATTR_TRV_ENTITIES, ATTR_VALVE_POSITION, HEATING_ACTION_THRESHOLD, CONF_MAX_TEMP, CONF_MIN_TEMP, CONF_PRECISION,
                    CONF_TARGET_TEMP, CONF_TEMPERATURE_SENSOR, CONF_TRV_ENTITIES,  # Feed-forward
                    CONF_OUTDOOR_TEMPERATURE_SENSOR, CONF_BOILER_FLOW_TEMPERATURE_SENSOR, CONF_FF_K_FLOW, CONF_FF_K_OUTDOOR, CONF_FF_TFLOW_REF,
                    CONF_FF_TOUT_REF, DEFAULT_FF_K_FLOW, DEFAULT_FF_K_OUTDOOR, DEFAULT_FF_TFLOW_REF, DEFAULT_FF_TOUT_REF,  # FF smoothing
                    CONF_FF_ENABLE_SMOOTHING, CONF_FF_FLOW_FILTER_TAU_S, CONF_FF_OUTDOOR_FILTER_TAU_S, CONF_FF_FLOW_DEADBAND_K, CONF_FF_OUTDOOR_DEADBAND_K,
                    DEFAULT_FF_ENABLE_SMOOTHING, DEFAULT_FF_FLOW_FILTER_TAU_S, DEFAULT_FF_OUTDOOR_FILTER_TAU_S, DEFAULT_FF_FLOW_DEADBAND_K,
                    DEFAULT_FF_OUTDOOR_DEADBAND_K, DEFAULT_MAX_TEMP, DEFAULT_MIN_TEMP, DEFAULT_PRECISION, DEFAULT_TARGET_TEMP, DOMAIN, VALVE_CLOSED_POSITION,
                    VALVE_OPEN_POSITION, VALVE_MIN_STEP, VALVE_UPDATE_MIN_INTERVAL_S,  # IMC additions
                    CONF_IMC_PROCESS_GAIN, CONF_IMC_DEAD_TIME, CONF_IMC_TIME_CONSTANT, CONF_IMC_LAMBDA,
                    DEFAULT_IMC_PROCESS_GAIN, DEFAULT_IMC_DEAD_TIME, DEFAULT_IMC_TIME_CONSTANT, DEFAULT_IMC_LAMBDA,  # Diagnostics and defaults
                    ATTR_DESIRED_VALVE_POSITION, ATTR_ERROR_C, ATTR_ERROR_NORM, ATTR_U_PI, ATTR_U_I, ATTR_U_FF, ATTR_U_TOTAL, ATTR_FLOW_FILTERED,
                    ATTR_OUTDOOR_FILTERED, ATTR_IMC_KC, ATTR_IMC_KI, ATTR_WINDOW_OPEN, ATTR_ACTUAL_VALVE_POSITION,  # Steady-state defaults and other defaults
                    DEFAULT_STEADY_DEADBAND_C, DEFAULT_DECAY_TAU_S, DEFAULT_NAME, MIN_TEMP_RANGE_C, WINDOW_CHECK_MIN_INTERVAL_S, DEFAULT_BOOST_DURATION_S,
                    CONF_WINDOW_OPEN_THRESHOLD_PER_MIN, CONF_WINDOW_OPEN_DURATION, DEFAULT_WINDOW_OPEN_THRESHOLD_PER_MIN, DEFAULT_WINDOW_OPEN_DURATION, )

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback, ) -> None:
    """Set up the Smart TRV Controller climate entity from a config entry."""
    config = config_entry.data

    async_add_entities([SmartTRVClimate(hass, config_entry.entry_id, config)], True, )


class SmartTRVClimate(ClimateEntity, RestoreEntity):
    """Smart TRV Controller Climate Entity."""

    _attr_has_entity_name = True
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.AUTO, HVACMode.HEAT]
    _attr_supported_features = (ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON)
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, hass: HomeAssistant, entry_id: str, config: dict[str, Any], ) -> None:
        """Initialize the Smart TRV Controller."""
        self.hass = hass
        self._entry_id = entry_id
        self._config = config

        # Configuration
        self._name = config.get(CONF_NAME, DEFAULT_NAME)
        self._temperature_sensor = config.get(CONF_TEMPERATURE_SENSOR)
        self._trv_entities: list[str] = config.get(CONF_TRV_ENTITIES, [])
        self._min_temp = float(config.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP))
        self._max_temp = float(config.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP))
        if self._min_temp >= self._max_temp:
            _LOGGER.error("Invalid configuration: min_temp (%.1f) >= max_temp (%.1f). Swapping them.", self._min_temp, self._max_temp)
            self._min_temp, self._max_temp = self._max_temp, self._min_temp

        self._target_temp = float(config.get(CONF_TARGET_TEMP, DEFAULT_TARGET_TEMP))
        # Clamp target temp to valid range
        self._target_temp = max(self._min_temp, min(self._max_temp, self._target_temp))

        self._precision = config.get(CONF_PRECISION, DEFAULT_PRECISION)
        # Optional feed-forward configuration
        self._outdoor_sensor: str | None = config.get(CONF_OUTDOOR_TEMPERATURE_SENSOR)
        self._boiler_flow_sensor: str | None = config.get(CONF_BOILER_FLOW_TEMPERATURE_SENSOR)
        self._ff_k_flow: float = float(config.get(CONF_FF_K_FLOW, DEFAULT_FF_K_FLOW))
        self._ff_k_outdoor: float = float(config.get(CONF_FF_K_OUTDOOR, DEFAULT_FF_K_OUTDOOR))
        self._ff_tflow_ref: float = float(config.get(CONF_FF_TFLOW_REF, DEFAULT_FF_TFLOW_REF))
        self._ff_tout_ref: float = float(config.get(CONF_FF_TOUT_REF, DEFAULT_FF_TOUT_REF))
        # Feed-forward smoothing & robustness
        self._ff_enable_smoothing: bool = bool(config.get(CONF_FF_ENABLE_SMOOTHING, DEFAULT_FF_ENABLE_SMOOTHING))
        self._ff_flow_tau_s: float = float(config.get(CONF_FF_FLOW_FILTER_TAU_S, DEFAULT_FF_FLOW_FILTER_TAU_S))
        self._ff_outdoor_tau_s: float = float(config.get(CONF_FF_OUTDOOR_FILTER_TAU_S, DEFAULT_FF_OUTDOOR_FILTER_TAU_S))
        self._ff_flow_deadband_k: float = float(config.get(CONF_FF_FLOW_DEADBAND_K, DEFAULT_FF_FLOW_DEADBAND_K))
        self._ff_outdoor_deadband_k: float = float(config.get(CONF_FF_OUTDOOR_DEADBAND_K, DEFAULT_FF_OUTDOOR_DEADBAND_K))
        # IMC/Lambda PI gains from process model (IMC-only controller)
        self._proportional_gain: float = 0.0
        self._integral_gain: float = 0.0
        self._last_u_total: float | None = None
        # IMC parameters are mandatory; controller always operates with computed gains

        # Open Window Detection
        self._window_threshold_per_min = abs(float(config.get(CONF_WINDOW_OPEN_THRESHOLD_PER_MIN, DEFAULT_WINDOW_OPEN_THRESHOLD_PER_MIN)))
        if self._window_threshold_per_min == 0:
            self._window_threshold_per_min = DEFAULT_WINDOW_OPEN_THRESHOLD_PER_MIN
        self._window_duration = float(config.get(CONF_WINDOW_OPEN_DURATION, DEFAULT_WINDOW_OPEN_DURATION))
        self._last_window_check_temp: float | None = None
        self._last_window_check_time: float | None = None
        self._window_open_until: float | None = None

        # Compute IMC gains unconditionally; fall back to sensible defaults
        kp_proc = float(config.get(CONF_IMC_PROCESS_GAIN, DEFAULT_IMC_PROCESS_GAIN))
        tau = float(config.get(CONF_IMC_TIME_CONSTANT, DEFAULT_IMC_TIME_CONSTANT))
        theta = float(config.get(CONF_IMC_DEAD_TIME, DEFAULT_IMC_DEAD_TIME) or 0.0)
        lam_raw = config.get(CONF_IMC_LAMBDA)
        lam_f = float(lam_raw) if lam_raw is not None else float(DEFAULT_IMC_LAMBDA)

        if kp_proc <= 0 or tau <= 0 or lam_f <= 0 or (lam_f + theta) <= 0:
            raise ValueError(f"Invalid IMC parameters: Kp_proc={kp_proc}, tau={tau}, theta={theta}, lambda={lam_f}")

        temp_range = max(MIN_TEMP_RANGE_C, self._max_temp - self._min_temp)
        kc = (tau * temp_range) / (kp_proc * (lam_f + theta))
        ki = temp_range / (kp_proc * (lam_f + theta))

        self._proportional_gain = kc
        self._integral_gain = ki
        _LOGGER.info(
            "IMC tuning: Kc=%.6f, Ki=%.8f (tau=%s s, theta=%s s, lambda=%s s, Kp_proc=%.4f, temp_range=%.2f)",
            self._proportional_gain,
            self._integral_gain,
            tau,
            theta,
            lam_f,
            kp_proc,
            temp_range,
        )

        # State
        # Default to AUTO as standard mode
        self._hvac_mode = HVACMode.AUTO
        self._current_temperature: float | None = None
        self._valve_position: int = VALVE_CLOSED_POSITION
        # Desired valve position (may differ from last sent due to throttling)
        self._desired_valve_position: int = VALVE_CLOSED_POSITION
        # Throttling state for valve updates
        self._last_valve_send_monotonic: float | None = None
        # Pending coalescing is not needed; we coalesce by skipping sends until interval
        # Controller integral state (IMC-PI)
        self._i_accum: float = 0.0  # integral over normalized error
        self._last_update_monotonic: float | None = None

        # Boost (HEAT) management
        self._boost_unsub = None  # type: ignore[assignment]
        self._boost_until: float | None = None

        # Entity attributes
        self._attr_unique_id = f"{DOMAIN}_{entry_id}"
        # Actual valve position reported by underlying TRVs (aggregated max)
        self._actual_valve_position: int | None = None
        # Per‑TRV actual valve cache {entity_id: position}
        self._actual_valve_map: dict[str, int] = {}
        self._attr_name = self._name
        # Feed-forward sensor state cache
        self._outdoor_temp: float | None = None
        self._boiler_flow_temp: float | None = None
        # Smoothed signals and FF state
        self._flow_filt: float | None = None
        self._outdoor_filt: float | None = None
        self._last_ff_update_monotonic: float | None = None

        # Steady-state handling near setpoint (internal defaults; not exposed in config flow)
        # Pulled from const.py to be consistent with other defaults
        self._steady_deadband_c: float = DEFAULT_STEADY_DEADBAND_C
        self._decay_tau_s: float = DEFAULT_DECAY_TAU_S
        # Bleed rate is derived from IMC tau during IMC setup

        # Diagnostics (initialized to None/zero)
        self._diag_error_c: float | None = None
        self._diag_error_norm: float | None = None
        self._diag_u_pi: float | None = None
        self._diag_u_i: float | None = None
        self._diag_u_ff: float | None = None
        self._diag_u_total: float | None = None

    # --- Small internal helpers for clarity and reuse ---
    @staticmethod
    def _clamp01(x: float) -> float:
        """Clamp a float to the [0, 1] range."""
        return SmartTRVClimate._clamp(x, 0, 1)

    @staticmethod
    def _clamp(x: float, lo: float, hi: float) -> float:
        """Clamp a float to the [lo, hi] range."""
        return lo if x < lo else hi if x > hi else x

    def _ewma(self, prev: float | None, val: float, tau: float, dt_s: float | None) -> float:
        """Exponentially-weighted moving average with time constant tau [s].

        If smoothing is disabled, tau<=0, or dt is invalid, returns the raw value.
        """
        if not self._ff_enable_smoothing or tau <= 0 or dt_s is None or dt_s <= 0:
            return val
        try:
            alpha = 1.0 - math.exp(-dt_s / max(1e-6, tau))
        except Exception:
            alpha = 1.0
        if prev is None:
            return val
        return prev + alpha * (val - prev)

    @staticmethod
    def _apply_deadband(x: float, db: float) -> float:
        """Apply a symmetric deadband to x; returns 0 within ±db and shrinks outside by db."""
        if db <= 0:
            return x
        if abs(x) <= db:
            return 0.0
        return x - db if x > 0 else x + db

    @staticmethod
    def _snap_to_step(value: int, step: int, lo: int, hi: int) -> int:
        """Round an integer to the nearest multiple of `step` and clamp to [lo, hi].

        Expects step >= 1. Uses the class clamp helper to keep bounds consistent.
        """
        if step <= 1:
            return int(SmartTRVClimate._clamp(int(value), lo, hi))
        v = int(SmartTRVClimate._clamp(int(value), lo, hi))
        snapped = int(round(v / step)) * step
        return int(SmartTRVClimate._clamp(snapped, lo, hi))

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return self._min_temp

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return self._max_temp

    @property
    def target_temperature_step(self) -> float:
        """Return the precision of the target temperature."""
        return self._precision

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._target_temp

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        return self._hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current HVAC action."""
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        # Report HEATING only when valve is opened more than 10% of full scale
        # (threshold defined in const.py for 0–255 scale).
        if self._valve_position > HEATING_ACTION_THRESHOLD:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {ATTR_VALVE_POSITION: self._valve_position, ATTR_ROOM_TEMPERATURE: self._current_temperature,
                                 ATTR_TRV_ENTITIES: self._trv_entities, }

        # Helper to round diagnostics to two decimals while keeping numeric types
        def _rd2(v: Any) -> Any:
            try:
                # Keep bools unchanged; they are instances of int in Python
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return round(float(v), 2)
            except Exception:
                pass
            return v

        # Also include the actual underlying TRVs valve position if known (max across TRVs)
        if self._actual_valve_position is not None:
            attrs[ATTR_ACTUAL_VALVE_POSITION] = int(self._actual_valve_position)

        # Enrich with diagnostics when available (rounded to 2 decimals)
        attrs[ATTR_DESIRED_VALVE_POSITION] = _rd2(self._desired_valve_position)
        attrs[ATTR_IMC_KC] = _rd2(self._proportional_gain)
        attrs[ATTR_IMC_KI] = _rd2(self._integral_gain)
        if self._diag_error_c is not None:
            attrs[ATTR_ERROR_C] = _rd2(self._diag_error_c)
        if self._diag_error_norm is not None:
            attrs[ATTR_ERROR_NORM] = _rd2(self._diag_error_norm)
        if self._diag_u_pi is not None:
            attrs[ATTR_U_PI] = _rd2(self._diag_u_pi)
        if self._diag_u_i is not None:
            attrs[ATTR_U_I] = _rd2(self._diag_u_i)
        if self._diag_u_ff is not None:
            attrs[ATTR_U_FF] = _rd2(self._diag_u_ff)
        if self._diag_u_total is not None:
            attrs[ATTR_U_TOTAL] = _rd2(self._diag_u_total)
        if self._flow_filt is not None:
            attrs[ATTR_FLOW_FILTERED] = _rd2(self._flow_filt)
        if self._outdoor_filt is not None:
            attrs[ATTR_OUTDOOR_FILTERED] = _rd2(self._outdoor_filt)
        attrs[ATTR_WINDOW_OPEN] = self._window_open_until is not None and time.monotonic() < self._window_open_until
        return attrs

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()

        # Restore previous state
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in (HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO):
                self._hvac_mode = HVACMode(last_state.state)
            if ATTR_TEMPERATURE in last_state.attributes:
                self._target_temp = last_state.attributes[ATTR_TEMPERATURE]

        # Subscribe to temperature sensor state changes
        self.async_on_remove(async_track_state_change_event(self.hass, [self._temperature_sensor], self._async_temperature_changed))
        # Subscribe to optional feed-forward sensors
        ff_entities: list[str] = []
        if self._outdoor_sensor:
            ff_entities.append(self._outdoor_sensor)
        if self._boiler_flow_sensor:
            ff_entities.append(self._boiler_flow_sensor)
        if ff_entities:
            self.async_on_remove(async_track_state_change_event(self.hass, ff_entities, self._async_ff_sensor_changed))

        # Get initial temperature
        await self._async_update_temperature()
        await self._async_control_heating()
        # Initialize actual valve readout and subscribe to underlying TRV/number changes
        await self._async_update_actual_valve_position()
        trv_listen_entities: list[str] = []
        for trv_entity_id in self._trv_entities:
            trv_listen_entities.append(trv_entity_id)
            valve_entity_id = trv_entity_id.replace("climate.", "number.") + "_valve_position"
            trv_listen_entities.append(valve_entity_id)
        if trv_listen_entities:
            self.async_on_remove(async_track_state_change_event(self.hass, trv_listen_entities, self._async_trv_state_changed))

    @callback
    def _async_temperature_changed(self, _event=None) -> None:
        """Handle temperature sensor state changes (HA event callback signature compatible)."""
        self.hass.async_create_task(self._async_update_temperature())
        self.hass.async_create_task(self._async_control_heating())
        self.async_write_ha_state()

    @callback
    def _async_ff_sensor_changed(self, _event=None) -> None:
        """Handle outdoor/boiler flow sensor state changes (HA event callback signature compatible)."""
        # Refresh FF sensor cache and re-run control
        self.hass.async_create_task(self._async_update_ff_sensors())
        self.hass.async_create_task(self._async_control_heating())
        self.async_write_ha_state()

    @callback
    def _async_trv_state_changed(self, _event=None) -> None:
        """Handle underlying TRV/valve number state changes."""
        self.hass.async_create_task(self._async_update_actual_valve_position())
        self.async_write_ha_state()

    async def _async_update_temperature(self) -> None:
        """Update the current temperature from the sensor."""
        state = self.hass.states.get(self._temperature_sensor)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.warning("Temperature sensor %s is unavailable", self._temperature_sensor)
            return

        try:
            self._current_temperature = float(state.state)
        except ValueError:
            _LOGGER.error("Unable to parse temperature from %s: %s", self._temperature_sensor, state.state, )

    async def _async_update_ff_sensors(self) -> None:
        """Update cached outdoor and boiler flow temperatures if configured."""
        # Outdoor
        if self._outdoor_sensor:
            st = self.hass.states.get(self._outdoor_sensor)
            if st is not None and st.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    self._outdoor_temp = float(st.state)
                except (TypeError, ValueError):
                    self._outdoor_temp = None
            else:
                self._outdoor_temp = None
        # Boiler flow
        if self._boiler_flow_sensor:
            st = self.hass.states.get(self._boiler_flow_sensor)
            if st is not None and st.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    self._boiler_flow_temp = float(st.state)
                except (TypeError, ValueError):
                    self._boiler_flow_temp = None
            else:
                self._boiler_flow_temp = None

    # --- Controller building blocks (extracted from _async_control_heating) ---
    async def _handle_off_mode(self) -> bool:
        """If HVAC is OFF, force valve closed and reset controller; return True if handled."""
        if self._hvac_mode != HVACMode.OFF:
            return False
        await self._async_request_valve_position(VALVE_CLOSED_POSITION, force=True)
        # Reset PI/internals
        self._i_accum = 0.0
        self._prev_norm_error = None
        self._last_update_monotonic = None
        # Reset diagnostics
        self._diag_error_c = None
        self._diag_error_norm = None
        self._diag_u_pi = None
        self._diag_u_i = None
        self._diag_u_ff = None
        self._diag_u_total = None
        return True

    async def _handle_boost_mode(self) -> bool:
        """If HVAC is HEAT (boost), fully open valve; return True if handled and possibly switch back to AUTO."""
        if self._hvac_mode != HVACMode.HEAT:
            return False
        await self._async_request_valve_position(VALVE_OPEN_POSITION, force=True)
        # Check boost expiry
        if self._boost_until is not None and time.monotonic() >= self._boost_until:
            await self.async_set_hvac_mode(HVACMode.AUTO)
        return True

    def _compute_error_and_timing(self) -> tuple[float, float, float, float | None]:
        """Compute error, temp_range, normalized positive error, and dt (s). Updates diagnostics and timing state."""
        error = self._target_temp - (self._current_temperature or self._target_temp)
        self._diag_error_c = float(error)
        temp_range = max(MIN_TEMP_RANGE_C, self._max_temp - self._min_temp)
        now = time.monotonic()
        dt: float | None = None
        if self._last_update_monotonic is not None:
            # Ensure a strictly positive dt when previous timestamp exists to progress filters/bleed
            dt = max(1e-6, now - self._last_update_monotonic)
        self._last_update_monotonic = now
        norm_error = max(0.0, min(error, temp_range)) / temp_range
        self._diag_error_norm = float(norm_error)
        return error, temp_range, norm_error, dt

    def _update_feedforward(self) -> tuple[float, float]:
        """Update FF filters and compute raw and final feed-forward (u_ff_raw, u_ff).

        Note: Rate limiting of the feed-forward component has been removed; smoothing
        is provided by EWMA filtering and deadbands only.
        """
        u_ff = 0.0
        ff_now = time.monotonic()
        ff_dt: float | None = None
        if self._last_ff_update_monotonic is not None:
            ff_dt = max(0.0, ff_now - self._last_ff_update_monotonic)
        self._last_ff_update_monotonic = ff_now

        if self._boiler_flow_temp is not None:
            self._flow_filt = self._ewma(self._flow_filt, self._boiler_flow_temp, self._ff_flow_tau_s, ff_dt)
        if self._outdoor_temp is not None:
            self._outdoor_filt = self._ewma(self._outdoor_filt, self._outdoor_temp, self._ff_outdoor_tau_s, ff_dt)

        u_ff_raw = 0.0
        if self._flow_filt is not None and self._ff_k_flow != 0.0:
            d_flow = self._ff_tflow_ref - self._flow_filt
            d_flow = self._apply_deadband(d_flow, self._ff_flow_deadband_k)
            u_ff_raw += self._ff_k_flow * d_flow
        if self._outdoor_filt is not None and self._ff_k_outdoor != 0.0:
            d_out = self._ff_tout_ref - self._outdoor_filt
            d_out = self._apply_deadband(d_out, self._ff_outdoor_deadband_k)
            u_ff_raw += self._ff_k_outdoor * d_out

        # No rate limiting: use raw feed-forward directly (still filtered by EWMA/deadbands)
        u_ff = u_ff_raw
        self._diag_u_ff = float(u_ff)
        return u_ff_raw, u_ff

    @staticmethod
    def _classify_band(error: float, eps: float) -> tuple[bool, bool, bool]:
        """Return (in_band, heat_side, cool_side) given error and deadband eps."""
        in_band = abs(error) <= eps
        cool_side = error < -eps
        heat_side = error > eps
        return in_band, heat_side, cool_side

    def _update_integral(self, norm_error: float, heat_side: bool, cool_side: bool, dt: float | None, u_ff: float = 0.0) -> None:
        """Integral separation and bleed behavior; updates internal integral state.

        Anti-windup: prevent integral growth when either the PI estimate or the
        actual clamped output (PI + FF) would exceed saturation (1.0).

        Bleed behavior (in-band and cool-side):
        - Instead of a fixed-rate bleed based on IMC tau, decay the integral
          contribution `u_i` exponentially toward zero using the steady-state
          decay time constant `self._decay_tau_s`. This aligns the in-band and
          cool-side behavior and uses the same conceptual time base as the
          output decay logic.
        """
        if dt is not None and dt > 0:
            u_p = self._proportional_gain * norm_error
            u_i = self._integral_gain * self._i_accum
            u_pi_est = u_p + u_i
            # Also check if actual output would saturate (includes feed-forward)
            u_total_est = u_pi_est + u_ff

            if heat_side:
                # Only accumulate if neither PI nor total output is saturated
                if u_pi_est < 1.0 and u_total_est < 1.0:
                    self._i_accum += norm_error * dt
            else:
                # Cool side or in-band: exponentially decay the integral
                # contribution u_i toward zero using the steady decay tau.
                # Apply the same alpha helper used by output decay.
                if self._decay_tau_s > 0:
                    alpha = self._alpha(dt, self._decay_tau_s)
                    # u_i_new = (1 - alpha) * u_i (toward 0)
                    u_i_new = (1.0 - alpha) * u_i
                    # Map back to internal accumulator (avoid division by 0)
                    if self._integral_gain > 0.0:
                        self._i_accum = max(0.0, u_i_new / self._integral_gain)
                    else:
                        # If Ki is zero (should not happen with valid IMC params), just zero it
                        self._i_accum = 0.0
                else:
                    # If decay tau is invalid, fall back to immediate zeroing
                    self._i_accum = 0.0
        # Finished integral update

    def _compute_pi(self, norm_error: float) -> tuple[float, float]:
        """Compute PI output and integral contribution (u_pi, u_i). Updates diagnostics."""
        u_i = self._integral_gain * self._i_accum
        u_pi = (self._proportional_gain * norm_error + u_i)
        self._diag_u_pi = float(u_pi)
        self._diag_u_i = float(u_i)
        return u_pi, u_i

    # Small math helper used by decision logic
    @staticmethod
    def _alpha(dt_s: float | None, tau_s: float) -> float:
        """Exponential step factor in [0,1] for time step dt and time constant tau.

        Returns 1.0 when timing or tau are invalid to fall back to immediate target.
        """
        if dt_s is None or dt_s <= 0 or tau_s <= 0:
            return 1.0
        try:
            return 1.0 - math.exp(-dt_s / tau_s)
        except Exception:
            return 1.0

    def _decide_u_total(self, u_pi: float, u_ff: float, error: float, heat_side: bool, dt: float | None) -> float:
        """Decide the final normalized command `u_total ∈ [0,1]`.

        Behavior summary:
        - Soft blending zone: for small |error| (≤ `self._steady_deadband_c`), blend smoothly between
          the heating suggestion (PI+FF) and an exponential decay toward closed. This removes sharp
          flips at the setpoint and yields a steady valve near steady-state.
        - Heat side (clearly below target): track `clamp01(u_pi + u_ff)`.
        - Otherwise (cool side or outside blend on the warm side): exponentially decay any positive
          opening toward 0.0. If timing is unknown, close immediately (0.0).
        """

        # Previous commanded opening (normalized)
        if self._last_u_total is not None:
            prev_u = self._last_u_total
        else:
            prev_u = (self._desired_valve_position if self._desired_valve_position is not None else self._valve_position) / float(VALVE_OPEN_POSITION)
            prev_u = self._clamp01(prev_u)

        # Suggested immediate command from PI + FF (normalized)
        u_suggest = self._clamp01(u_pi + u_ff)

        # Cache timing validity for decay calculations
        has_timing = (dt is not None and dt > 0 and self._decay_tau_s > 0)

        # Soft blending around setpoint: blend between heating command and decay-to-close
        # when error is small in magnitude. Uses the configured steady deadband as blend half-width.
        eps_blend = max(0.0, self._steady_deadband_c)
        if eps_blend > 0.0 and abs(error) <= eps_blend:
            # Smoothstep weight w ∈ [0,1] from cool-side (0) to heat-side (1)
            # Map error ∈ [-eps_blend, +eps_blend] → x ∈ [0,1]
            x = (error + eps_blend) / (2.0 * eps_blend)
            x = self._clamp(x, 0.0, 1.0)
            w = x * x * (3.0 - 2.0 * x)

            # Heat suggestion
            u_heat = u_suggest

            # Decay suggestion (toward fully closed)
            if has_timing:
                a = self._alpha(dt, self._decay_tau_s)
                u_decay = max(0.0, prev_u + a * (0.0 - prev_u))
            else:
                u_decay = 0.0

            u_blend = w * u_heat + (1.0 - w) * u_decay
            return self._clamp01(u_blend)

        # Heat side: track PI+FF
        if heat_side:
            return u_suggest

        # In-band and cool side: decay toward fully closed
        if has_timing:
            a = self._alpha(dt, self._decay_tau_s)
            return max(0.0, prev_u + a * (0.0 - prev_u))

        # Fallback when timing unknown: close immediately
        return 0.0

    def _check_window_open(self, current_temp: float, now: float) -> bool:
        """Detect if a window is open based on rapid temperature drop.

        Returns True if window open mode is active.
        """
        # Check if already in window open mode
        if self._window_open_until is not None:
            if now < self._window_open_until:
                return True
            else:
                # Expired
                self._window_open_until = None
                _LOGGER.info("Window open mode expired. Resuming normal control.")

        # Check for rapid drop
        if self._last_window_check_time is None:
            self._last_window_check_temp = current_temp
            self._last_window_check_time = now
            return False

        dt = now - self._last_window_check_time
        # Ignore too frequent updates to avoid noise amplification
        if dt < WINDOW_CHECK_MIN_INTERVAL_S:
            return False

        delta_t = current_temp - self._last_window_check_temp
        rate_per_min = (delta_t / dt) * 60.0

        # Update reference for next check
        self._last_window_check_temp = current_temp
        self._last_window_check_time = now

        # If rate is significantly negative (drop)
        if rate_per_min < -self._window_threshold_per_min:
            self._window_open_until = now + self._window_duration
            _LOGGER.warning("Window open detected! Temp dropped %.2f K in %.1f s (rate %.2f K/min). Suppressing heat for %.0f s.", delta_t, dt, rate_per_min,
                            self._window_duration)
            return True

        return False

    async def _async_control_heating(self) -> None:
        """Control the heating based on current and target temperature."""
        if await self._handle_off_mode():
            return

        # In HEAT mode, operate as a timed boost: fully open for the boost window
        if await self._handle_boost_mode():
            return

        if self._current_temperature is None:
            _LOGGER.debug("No current temperature available, skipping control")
            return

        now = time.monotonic()
        # Window open check (suppress heating if rapid drop detected)
        if self._check_window_open(self._current_temperature, now):
            # Force valve closed and reset integral to avoid stale accumulation
            self._i_accum = 0.0
            if self._valve_position != VALVE_CLOSED_POSITION:
                await self._async_request_valve_position(VALVE_CLOSED_POSITION, force=True)
            return

        # AUTO mode core loop components
        error, temp_range, norm_error, dt = self._compute_error_and_timing()

        # Feed-forward update (raw)
        _u_ff_raw, u_ff = self._update_feedforward()

        # Determine bands around setpoint
        eps = self._steady_deadband_c
        in_band, heat_side, cool_side = self._classify_band(error, eps)

        # Integral update with separation/bleed (pass u_ff for improved anti-windup)
        self._update_integral(norm_error, heat_side, cool_side, dt, u_ff)

        # Compute PI and decide final command
        u_pi, _u_i = self._compute_pi(norm_error)
        u_total = self._decide_u_total(u_pi, u_ff, error, heat_side, dt)
        self._diag_u_total = float(u_total)
        self._last_u_total = u_total
        valve_position = int(round(u_total * VALVE_OPEN_POSITION))

        await self._async_request_valve_position(valve_position)

    async def _async_request_valve_position(self, position: int, force: bool = False) -> None:
        """Request a valve update, throttled to at most once per minute unless forced.

        - force=True: send immediately (used for OFF/HEAT transitions and critical changes).
        - force=False: coalesce and delay so that sends occur at most once per minute.
        """
        # Clamp to valid range
        position = max(VALVE_CLOSED_POSITION, min(VALVE_OPEN_POSITION, int(position)))
        self._desired_valve_position = position

        now = time.monotonic()

        # Decide whether to send now
        send_now = force
        if not send_now:
            if self._last_valve_send_monotonic is None:
                send_now = True
            else:
                elapsed = now - self._last_valve_send_monotonic
                if elapsed >= VALVE_UPDATE_MIN_INTERVAL_S:
                    send_now = True

        if send_now:
            await self._async_set_valve_position(position)
            self._last_valve_send_monotonic = time.monotonic()
            return

        # Otherwise, skip sending now; the next control tick will re-evaluate and send when allowed

    async def _async_set_valve_position(self, position: int) -> None:
        """Immediately set the valve position on all TRVs (no throttling).

        Note: external callers should use _async_request_valve_position.
        """
        # Enforce minimum step size to reduce chattering at the TRV layer
        try:
            step = max(1, int(VALVE_MIN_STEP))
        except Exception:
            step = 5
        # Clamp and optionally snap to step using existing helpers
        if step > 1:
            position = self._snap_to_step(int(position), step, VALVE_CLOSED_POSITION, VALVE_OPEN_POSITION)
        else:
            position = int(self._clamp(int(position), VALVE_CLOSED_POSITION, VALVE_OPEN_POSITION))
        
        # If requested equals last commanded, we may still need to resend selectively
        # to any underlying TRV whose actual does not match the target.
        resend_selectively = False
        if position == self._valve_position:
            # Determine if any individual TRV differs from target
            for trv_entity_id in self._trv_entities:
                trv_actual = self._actual_valve_map.get(trv_entity_id)
                # Only treat as mismatch when we have an actual reading and it differs
                if trv_actual is not None and trv_actual != position:
                    resend_selectively = True
                    break
            # If no per‑TRV mismatch found but aggregated actual differs, resend to all
            if not resend_selectively and self._actual_valve_position is not None and self._actual_valve_position != position:
                resend_selectively = True
            if not resend_selectively:
                _LOGGER.debug("Skipping valve position update, all TRVs already at %d", position)
                return

        # Propagate to underlying TRVs; reflect last commanded locally
        self._valve_position = position

        for trv_entity_id in self._trv_entities:
            try:
                # Get the TRV's current state to determine how to control it
                trv_state = self.hass.states.get(trv_entity_id)
                if trv_state is None:
                    _LOGGER.warning("TRV entity %s not found", trv_entity_id)
                    continue

                # If we are in selective resend mode, skip TRVs already at target
                if resend_selectively:
                    trv_actual = self._actual_valve_map.get(trv_entity_id)
                    if trv_actual is not None and trv_actual == position:
                        continue

                # Try to set valve position via number entity if available
                # Many TRVs expose a separate number entity for valve position
                valve_entity_id = trv_entity_id.replace("climate.", "number.") + "_valve_position"
                valve_state = self.hass.states.get(valve_entity_id)

                if valve_state is not None:
                    # Use number service to set valve position directly
                    await self.hass.services.async_call(
                        "number",
                        "set_value",
                        {"entity_id": valve_entity_id, "value": position},
                        blocking=True,
                    )
                    _LOGGER.debug("Set valve position to %d on %s via number entity", position, valve_entity_id, )
                else:
                    # Fall back to controlling the TRV via temperature
                    # Calculate an effective temperature setpoint based on valve position
                    if position == VALVE_CLOSED_POSITION:
                        # Turn off the TRV
                        await self.hass.services.async_call("climate", "set_hvac_mode", {"entity_id": trv_entity_id, "hvac_mode": HVACMode.OFF, },
                                                            blocking=True, )
                    else:
                        # Ensure TRV is in heat mode
                        if trv_state.state == HVACMode.OFF:
                            await self.hass.services.async_call("climate", "set_hvac_mode", {"entity_id": trv_entity_id, "hvac_mode": HVACMode.HEAT, },
                                                                blocking=True, )

                        # Map valve position (0-255) to a temperature offset
                        # This creates a virtual setpoint to trick the TRV
                        temp_range = self._max_temp - self._min_temp
                        virtual_setpoint = self._min_temp + (position / float(VALVE_OPEN_POSITION)) * temp_range

                        await self.hass.services.async_call("climate", "set_temperature", {"entity_id": trv_entity_id, ATTR_TEMPERATURE: virtual_setpoint, },
                                                            blocking=True, )

                    _LOGGER.debug("Controlled TRV %s based on valve position %d", trv_entity_id, position, )

            except Exception as err:
                _LOGGER.error("Failed to set valve position on %s: %s", trv_entity_id, err, )
        # After commanding, try to refresh the actual position reading
        await self._async_update_actual_valve_position()

    async def _async_update_actual_valve_position(self) -> None:
        """Read actual valve opening from underlying TRVs and cache the aggregated max (0..255)."""
        max_pos: int | None = None
        local_map: dict[str, int] = {}
        for trv_entity_id in self._trv_entities:
            # Prefer number.<trv>_valve_position if present
            valve_entity_id = trv_entity_id.replace("climate.", "number.") + "_valve_position"
            try:
                valve_state = self.hass.states.get(valve_entity_id)
                if valve_state is not None and valve_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                    try:
                        v = float(valve_state.state)
                        v_clamped = max(VALVE_CLOSED_POSITION, min(VALVE_OPEN_POSITION, int(round(v))))
                        max_pos = v_clamped if max_pos is None else max(max_pos, v_clamped)
                        local_map[trv_entity_id] = v_clamped
                        continue
                    except (TypeError, ValueError):
                        pass

                # Fallback: check climate attribute `valve_position` if exposed by the TRV
                trv_state = self.hass.states.get(trv_entity_id)
                if trv_state is not None:
                    vp = trv_state.attributes.get("valve_position")
                    if vp is not None:
                        try:
                            v = float(vp)
                            v_clamped = max(VALVE_CLOSED_POSITION, min(VALVE_OPEN_POSITION, int(round(v))))
                            max_pos = v_clamped if max_pos is None else max(max_pos, v_clamped)
                            local_map[trv_entity_id] = v_clamped
                        except (TypeError, ValueError):
                            pass
            except Exception as err:
                _LOGGER.debug("While reading actual valve from %s: %s", trv_entity_id, err)

        self._actual_valve_position = max_pos
        self._actual_valve_map = local_map

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        self._target_temp = temperature
        await self._async_control_heating()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        if hvac_mode not in self._attr_hvac_modes:
            _LOGGER.warning("Unsupported HVAC mode: %s", hvac_mode)
            return

        # Cancel any existing boost timer when changing modes
        self._cancel_boost()

        if hvac_mode == HVACMode.HEAT:
            # Start 15-minute boost: set fully open and schedule fallback to AUTO
            self._hvac_mode = HVACMode.HEAT
            # Set valve immediately
            await self._async_request_valve_position(VALVE_OPEN_POSITION, force=True)
            # Set boost window end
            self._boost_until = time.monotonic() + DEFAULT_BOOST_DURATION_S
            # Schedule fallback using HA helper; store unsubscribe handle
            try:
                self._boost_unsub = async_call_later(self.hass, DEFAULT_BOOST_DURATION_S, self._handle_boost_timeout)  # type: ignore[assignment]
            except Exception:  # pragma: no cover - defensive
                self._boost_unsub = None
            self.async_write_ha_state()
            return

        # For AUTO and OFF proceed with normal flow
        self._hvac_mode = hvac_mode
        await self._async_control_heating()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup when entity is being removed."""
        return

    async def _handle_boost_timeout(self, _now) -> None:
        """Callback for boost timeout to revert to AUTO mode."""
        # Clear timer state first to avoid re-entrancy issues
        self._cancel_boost()
        await self.async_set_hvac_mode(HVACMode.AUTO)

    def _cancel_boost(self) -> None:
        """Cancel a running boost timer and clear state."""
        if self._boost_unsub is not None:
            try:
                self._boost_unsub()
            except Exception:  # pragma: no cover - defensive
                pass
        self._boost_unsub = None
        self._boost_until = None

    async def async_turn_off(self) -> None:
        """Turn the entity off (map to HVACMode.OFF)."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self) -> None:
        """Turn the entity on (map to HVACMode.AUTO as standard mode)."""
        await self.async_set_hvac_mode(HVACMode.AUTO)
