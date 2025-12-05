import pytest
from unittest.mock import MagicMock, patch
from custom_components.smart_trv.climate import SmartTRVClimate
from custom_components.smart_trv.const import VALVE_OPEN_POSITION, DEFAULT_DECAY_TAU_S

@pytest.fixture
def mock_trv():
    hass = MagicMock()
    config = {}
    # Mock config entry
    entry = MagicMock()
    entry.entry_id = "test_id"
    
    trv = SmartTRVClimate(hass, "test_id", config)
    # Manually set defaults normally handled in __init__
    trv._decay_tau_s = DEFAULT_DECAY_TAU_S
    trv._last_u_total = None
    trv._desired_valve_position = None
    trv._valve_position = 0
    return trv

def test_decay_with_float_state(mock_trv):
    """Verify that _last_u_total allows decay even when quantization would stall it."""
    
    # Start at a small value where quantization is tricky
    # 20/255 = 0.0784
    start_val = 20
    start_u = start_val / VALVE_OPEN_POSITION
    
    mock_trv._last_u_total = start_u
    mock_trv._desired_valve_position = start_val
    mock_trv._valve_position = start_val
    
    # Simulate dt = 60s
    dt = 60.0
    
    # Cool side condition: error < -eps (e.g. -1.0 error, heat_side=False)
    # _decide_u_total(u_pi, u_ff, error, heat_side, dt)
    
    # First step
    u_next = mock_trv._decide_u_total(u_pi=0.0, u_ff=0.0, error=-1.0, heat_side=False, dt=dt)
    
    # Check it decreased
    assert u_next < start_u
    print(f"Step 1: {start_u:.5f} -> {u_next:.5f}")
    
    # Update internal state as the main loop would
    mock_trv._last_u_total = u_next
    
    # If we were using integer quantization, let's see what would happen
    quantized_next = int(round(u_next * VALVE_OPEN_POSITION))
    print(f"Quantized next: {quantized_next}")
    
    # Run loop until close to 0
    steps = 0
    curr_u = u_next
    while curr_u > 0.0001 and steps < 100:
        curr_u = mock_trv._decide_u_total(u_pi=0.0, u_ff=0.0, error=-1.0, heat_side=False, dt=dt)
        mock_trv._last_u_total = curr_u
        steps += 1
        if steps % 10 == 0:
             print(f"Step {steps}: {curr_u:.5f}")
    
    assert curr_u < 0.01, "Should decay to near zero"
    assert steps < 100, "Should decay reasonably fast with Tau=600"

def test_quantization_stuck_reproduction(mock_trv):
    """Demonstrate that WITHOUT _last_u_total, it would stick (Simulated)."""
    # Temporarily force _last_u_total to None to simulate old behavior
    mock_trv._last_u_total = None
    
    start_val = 20
    mock_trv._desired_valve_position = start_val
    
    # Use OLD Tau for reproduction (3600s)
    mock_trv._decay_tau_s = 3600.0
    dt = 60.0
    
    # Calculate next u
    u_next = mock_trv._decide_u_total(u_pi=0.0, u_ff=0.0, error=-1.0, heat_side=False, dt=dt)
    
    # Convert back to int
    next_val = int(round(u_next * VALVE_OPEN_POSITION))
    
    print(f"Old Logic (Tau=3600): Start {start_val} -> Next {next_val}")
    
    # With old logic, it often rounded back to 20
    # Here we just verify if it drops.
    # 20/255 * (1 - exp(-60/3600)) -> drop is small
    
    assert next_val == start_val, "With old Tau and int quantization, it should stick at 20"
