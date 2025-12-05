
import pytest
from unittest.mock import MagicMock, patch
from homeassistant.components.climate import HVACMode
from homeassistant.core import HomeAssistant
from custom_components.smart_trv.climate import SmartTRVClimate
from custom_components.smart_trv.const import VALVE_OPEN_POSITION, VALVE_CLOSED_POSITION

@pytest.mark.asyncio
async def test_open_window_detection():
    """Test that a rapid temperature drop triggers window detection and closes the valve."""
    hass = MagicMock(spec=HomeAssistant)
    config = {
        "name": "Test TRV",
        "temperature_sensor": "sensor.temp",
        "trv_entities": ["climate.trv"],
        "imc_process_gain": 4.0,
        "imc_time_constant": 5400.0,
        "imc_lambda": 5400.0,
    }
    
    # Initialize entity
    climate = SmartTRVClimate(hass, "test_id", config)
    climate.hass = hass
    
    # Mock initial state
    climate._current_temperature = 20.0
    climate._target_temp = 21.0
    # Should be heating (error = 1.0 -> u ~ 0.25)
    climate._valve_position = 64 # approx 25%
    
    # 1. Normal update - small change
    # Temp drops 0.1 in 5 minutes (0.02/min) -> Normal
    import time
    now = time.monotonic()
    
    # We need to simulate the passage of time and temp change
    # We can't easily mock time.monotonic inside the class without patching, 
    # but we can inject the logic if we isolate the detection or manipulate the internal state.
    # Ideally, we should test the public behavior.
    
    # Let's assume we patch time.monotonic in the test execution context if needed, 
    # or we manually trigger the update logic.
    
    # Helper to simulate an update cycle
    async def run_control(temp, dt_seconds):
        climate._current_temperature = temp
        # Manually fudge the timing tracking
        if climate._last_window_check_time is not None:
            climate._last_window_check_time = now - dt_seconds # Set 'previous' time relative to now
        else:
            climate._last_window_check_time = now - dt_seconds
        
        # We also need to set _last_temp for the check
        # But the check updates _last_temp at the end. 
        # So we need to set the state "before" the call.
        
        # Actually, let's look at how we will implement it.
        # If we implement _check_window_open(current, now), it will compare with self._last_window_temp/time.
        pass

    # Since I haven't implemented it yet, I can't strictly test the implementation details.
    # But I can define the expected behavior.
    
    # Inject state for "Previous run"
    climate._last_window_check_temp = 20.0
    climate._last_window_check_time = 1000.0
    
    # Current run: 2 mins later, temp dropped to 18.0 (-2.0 deg in 2 mins = -1.0/min)
    # This is HUGE. Should trigger.
    current_time = 1000.0 + 120.0 
    current_temp = 18.0
    climate._current_temperature = current_temp
    
    # We need to patch time.monotonic to return current_time
    with patch("time.monotonic", return_value=current_time):
        # Run control
        await climate._async_control_heating()
        
    # Expectation: Valve should be CLOSED (0) despite large positive error (Target 21, Current 18 -> Error 3)
    # Without window detection, Error 3 -> u = 3/4 = 0.75 -> Valve ~191.
    # With window detection, Valve = 0.
    
    # Check that window detection triggered and valve is closed
    assert climate._desired_valve_position == VALVE_CLOSED_POSITION, f"Valve should be closed (0) due to window detection, but was {climate._desired_valve_position}"
    assert climate._window_open_until is not None, "Window open mode should be active"
    assert climate._window_open_until > current_time, "Window open timer should be in the future"

