from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.climate import HVACMode

from custom_components.smart_trv.climate import SmartTRVClimate
from custom_components.smart_trv.const import (
    VALVE_OPEN_POSITION,
)


@pytest.fixture
def hass_mock():
    from homeassistant.core import HomeAssistant

    hass = MagicMock(spec=HomeAssistant)
    # Some HA helpers expect hass.data and an integrations cache to exist
    hass.data = {"integrations": {}}
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    return hass


@pytest.fixture
def cfg_defaults():
    return {
        "name": "TRV",
        "temperature_sensor": "sensor.room",
        "trv_entities": ["climate.trv"],
        # IMC parameters for deterministic, valid controller
        "imc_process_gain": 4.0,
        "imc_time_constant": 5400.0,
        "imc_dead_time": 900.0,
    }


def _set_temp(entity: SmartTRVClimate, current: float, target: float | None = None) -> None:
    entity._current_temperature = current
    if target is not None:
        entity._target_temp = target


@pytest.mark.asyncio
async def test_in_band_decays_toward_zero(hass_mock, cfg_defaults):
    ent = SmartTRVClimate(hass_mock, "e1", cfg_defaults)
    # equal to setpoint -> error 0 (in band)
    _set_temp(ent, current=21.0, target=21.0)

    # Start from a previously open valve (~20%)
    ent._desired_valve_position = int(0.2 * VALVE_OPEN_POSITION)
    ent._valve_position = ent._desired_valve_position

    # Ensure dt > 0 by setting last update to the past
    import time as _t

    ent._last_update_monotonic = _t.monotonic() - 600.0  # 10 minutes

    # Patch FF to zero; in-band should decay toward 0
    with patch.object(ent, "_update_feedforward", return_value=(0.0, 0.0)):
        await ent._async_control_heating()

    new_u = ent._desired_valve_position / VALVE_OPEN_POSITION
    assert 0.0 <= new_u < 0.2


@pytest.mark.asyncio
async def test_in_band_negative_error_decays_toward_zero(hass_mock, cfg_defaults):
    ent = SmartTRVClimate(hass_mock, "e2", cfg_defaults)
    # Slightly above target (negative error, still in band)
    ent._steady_deadband_c = 0.2
    _set_temp(ent, current=21.05, target=21.0)  # error = -0.05
    # Start from a previously higher opening (~20%)
    ent._desired_valve_position = int(0.2 * VALVE_OPEN_POSITION)
    ent._valve_position = ent._desired_valve_position

    # Ensure dt > 0 by setting last update to the past
    import time as _t

    ent._last_update_monotonic = _t.monotonic() - 600.0  # 10 minutes

    with patch.object(ent, "_update_feedforward", return_value=(0.0, 0.0)):
        await ent._async_control_heating()

    prev_u = 0.2
    # New u should be strictly less than previous and >= 0
    new_u = ent._desired_valve_position / VALVE_OPEN_POSITION
    assert 0.0 <= new_u < prev_u


@pytest.mark.asyncio
async def test_cool_side_positive_u_decays_toward_zero(hass_mock, cfg_defaults):
    ent = SmartTRVClimate(hass_mock, "e3", cfg_defaults)
    # Make error clearly on cool side (above target by > eps)
    ent._steady_deadband_c = 0.1
    _set_temp(ent, current=21.5, target=21.0)  # error = -0.5 -> cool_side

    # Start from a previously open valve (~20%)
    ent._desired_valve_position = int(0.2 * VALVE_OPEN_POSITION)
    ent._valve_position = ent._desired_valve_position

    # Ensure dt > 0 by setting last update to the past
    import time as _t

    ent._last_update_monotonic = _t.monotonic() - 600.0  # 10 minutes

    # Force FF to a small positive value; cool side should ignore FF floor and decay to 0
    with patch.object(ent, "_update_feedforward", return_value=(0.1, 0.1)):
        await ent._async_control_heating()

    new_u = ent._desired_valve_position / VALVE_OPEN_POSITION
    # Should be strictly less than previous and greater or equal to 0
    assert 0.0 <= new_u < 0.2


@pytest.mark.asyncio
async def test_heat_side_uses_pi_plus_ff(hass_mock, cfg_defaults):
    ent = SmartTRVClimate(hass_mock, "e4", cfg_defaults)
    _set_temp(ent, current=20.0, target=21.0)  # error = +1.0 -> heat_side

    # Stub PI and FF to predictable values
    with patch.object(ent, "_compute_pi", return_value=(0.4, 0.0)):
        with patch.object(ent, "_update_feedforward", return_value=(0.1, 0.1)):
            await ent._async_control_heating()

    u = ent._desired_valve_position / VALVE_OPEN_POSITION
    assert pytest.approx(u, rel=0.01) == 0.5


@pytest.mark.asyncio
async def test_integral_separation_no_growth_in_band(hass_mock, cfg_defaults):
    ent = SmartTRVClimate(hass_mock, "e5", cfg_defaults)
    _set_temp(ent, current=21.02, target=21.0)  # small negative error in band
    ent._i_accum = 5.0
    # Ensure dt positive
    import time as _t

    ent._last_update_monotonic = _t.monotonic() - 120.0

    with patch.object(ent, "_update_feedforward", return_value=(0.0, 0.0)):
        await ent._async_control_heating()

    # In band, integral should be frozen (no increase)
    assert ent._i_accum <= 5.0


@pytest.mark.asyncio
async def test_integral_bleed_on_cool_side(hass_mock, cfg_defaults):
    ent = SmartTRVClimate(hass_mock, "e6", cfg_defaults)
    _set_temp(ent, current=21.5, target=21.0)  # cool_side
    ent._i_accum = 5.0
    # dt known
    import time as _t

    ent._last_update_monotonic = _t.monotonic() - 100.0

    with patch.object(ent, "_update_feedforward", return_value=(0.0, 0.0)):
        await ent._async_control_heating()

    # Bleed rate per s should reduce accumulator
    assert ent._i_accum < 5.0


@pytest.mark.asyncio
async def test_integral_grows_on_heat_side(hass_mock, cfg_defaults):
    ent = SmartTRVClimate(hass_mock, "e7", cfg_defaults)
    _set_temp(ent, current=20.0, target=21.0)  # heat_side
    ent._i_accum = 0.0
    import time as _t

    ent._last_update_monotonic = _t.monotonic() - 60.0

    # Ensure tentative_u < 1 so integration occurs
    with patch.object(ent, "_update_feedforward", return_value=(0.0, 0.0)):
        await ent._async_control_heating()

    assert ent._i_accum > 0.0


@pytest.mark.asyncio
async def test_boost_mode_opens_valve_and_sets_timer(hass_mock, cfg_defaults):
    ent = SmartTRVClimate(hass_mock, "e8", cfg_defaults)

    # Patch scheduler to observe calls
    with patch("custom_components.smart_trv.climate.async_call_later", return_value=lambda: None) as mock_call_later:
        # Avoid HA entity_id requirement in async_write_ha_state during unit test
        ent.async_write_ha_state = MagicMock()
        await ent.async_set_hvac_mode(HVACMode.HEAT)
        # Immediate open command was issued (force=True bypasses throttle)
        assert ent._desired_valve_position == VALVE_OPEN_POSITION
        assert ent._hvac_mode == HVACMode.HEAT
        mock_call_later.assert_called()
        assert ent._boost_until is not None


@pytest.mark.asyncio
async def test_valve_update_throttling(hass_mock, cfg_defaults):
    ent = SmartTRVClimate(hass_mock, "e9", cfg_defaults)

    calls = []

    async def _spy_set(pos: int):
        calls.append(pos)
        # Simulate the underlying immediate set updating internal state
        ent._valve_position = pos

    # Spy the immediate setter
    with patch.object(ent, "_async_set_valve_position", side_effect=_spy_set):
        # First send should go through immediately
        await ent._async_request_valve_position(100)
        # Second send within min interval should be coalesced (no immediate call)
        import time as _t

        ent._last_valve_send_monotonic = _t.monotonic()  # just sent now
        await ent._async_request_valve_position(120)

    assert calls == [100]


@pytest.mark.asyncio
async def test_set_valve_resends_when_actual_differs(hass_mock, cfg_defaults):
    """If requested equals last commanded but actual differs, do NOT skip update."""
    ent = SmartTRVClimate(hass_mock, "e10", cfg_defaults)
    ent._trv_entities = ["climate.trv"]
    # Last commanded equals requested
    ent._valve_position = 100
    # Actual aggregated position differs
    ent._actual_valve_position = 80

    # Provide number entity so we hit number.set_value path
    mock_trv_state = MagicMock()
    mock_trv_state.state = HVACMode.HEAT
    mock_number_state = MagicMock()
    mock_number_state.state = "80"

    def _get_state(eid: str):
        if eid == "climate.trv":
            return mock_trv_state
        if eid == "number.trv_valve_position":
            return mock_number_state
        return None

    hass_mock.states.get.side_effect = _get_state

    # Track calls
    hass_mock.services.async_call.reset_mock()

    await ent._async_set_valve_position(100)

    # Should have issued a service call to update despite same requested value
    assert hass_mock.services.async_call.await_count >= 1


@pytest.mark.asyncio
async def test_set_valve_skips_when_actual_matches(hass_mock, cfg_defaults):
    """If requested equals last commanded and actual matches, skip update."""
    ent = SmartTRVClimate(hass_mock, "e11", cfg_defaults)
    ent._trv_entities = ["climate.trv"]
    ent._valve_position = 120
    ent._actual_valve_position = 120

    # Even if states are available, method should return early and not call services
    mock_trv_state = MagicMock()
    mock_trv_state.state = HVACMode.HEAT
    hass_mock.states.get.return_value = mock_trv_state

    hass_mock.services.async_call.reset_mock()

    await ent._async_set_valve_position(120)

    hass_mock.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_multi_trv_selective_resend_only_mismatched(hass_mock, cfg_defaults):
    """With multiple TRVs: when requested equals last commanded, resend only to TRVs not at target."""
    ent = SmartTRVClimate(hass_mock, "e12", cfg_defaults)
    ent._trv_entities = ["climate.trv_a", "climate.trv_b"]
    # Last commanded equals requested
    ent._valve_position = 150
    # Actuals: A at 150 (match), B at 100 (mismatch)
    ent._actual_valve_map = {"climate.trv_a": 150, "climate.trv_b": 100}
    ent._actual_valve_position = 150

    # Provide number entities for both TRVs
    mock_trv_a = MagicMock(); mock_trv_a.state = HVACMode.HEAT
    mock_trv_b = MagicMock(); mock_trv_b.state = HVACMode.HEAT
    mock_num_a = MagicMock(); mock_num_a.state = "150"
    mock_num_b = MagicMock(); mock_num_b.state = "100"

    def _get_state(eid: str):
        if eid == "climate.trv_a":
            return mock_trv_a
        if eid == "climate.trv_b":
            return mock_trv_b
        if eid == "number.trv_a_valve_position":
            return mock_num_a
        if eid == "number.trv_b_valve_position":
            return mock_num_b
        return None

    hass_mock.states.get.side_effect = _get_state
    hass_mock.services.async_call.reset_mock()

    await ent._async_set_valve_position(150)

    # Should have issued a service call only for TRV B's number entity
    calls = [args for args, _ in getattr(hass_mock.services.async_call, 'await_args_list', [])]
    # Extract entity_ids from service data (3rd positional arg)
    entity_ids = [args[2].get("entity_id") if len(args) >= 3 and isinstance(args[2], dict) else None for args in calls]
    assert "number.trv_b_valve_position" in entity_ids
    assert "number.trv_a_valve_position" not in entity_ids


@pytest.mark.asyncio
async def test_multi_trv_all_match_skip(hass_mock, cfg_defaults):
    """With multiple TRVs: when all actuals equal requested and last commanded, skip updates."""
    ent = SmartTRVClimate(hass_mock, "e13", cfg_defaults)
    ent._trv_entities = ["climate.trv_a", "climate.trv_b"]
    ent._valve_position = 90
    ent._actual_valve_map = {"climate.trv_a": 90, "climate.trv_b": 90}
    ent._actual_valve_position = 90

    # States exist but should not be called
    hass_mock.services.async_call.reset_mock()

    await ent._async_set_valve_position(90)

    hass_mock.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_position_changed_sends_to_all_trvs(hass_mock, cfg_defaults):
    """When requested differs from last commanded, send to all TRVs regardless of actuals."""
    ent = SmartTRVClimate(hass_mock, "e14", cfg_defaults)
    ent._trv_entities = ["climate.trv_a", "climate.trv_b"]
    ent._valve_position = 80  # last commanded
    # Actuals arbitrary
    ent._actual_valve_map = {"climate.trv_a": 80, "climate.trv_b": 120}

    mock_trv_a = MagicMock(); mock_trv_a.state = HVACMode.HEAT
    mock_trv_b = MagicMock(); mock_trv_b.state = HVACMode.HEAT
    mock_num_a = MagicMock(); mock_num_a.state = "80"
    mock_num_b = MagicMock(); mock_num_b.state = "120"

    def _get_state(eid: str):
        if eid == "climate.trv_a":
            return mock_trv_a
        if eid == "climate.trv_b":
            return mock_trv_b
        if eid == "number.trv_a_valve_position":
            return mock_num_a
        if eid == "number.trv_b_valve_position":
            return mock_num_b
        return None

    hass_mock.states.get.side_effect = _get_state
    hass_mock.services.async_call.reset_mock()

    await ent._async_set_valve_position(100)

    # Expect two number.set_value calls
    count_number_calls = sum(1 for (args, kwargs) in getattr(hass_mock.services.async_call, 'await_args_list', []) if args and args[0] == "number")
    assert count_number_calls == 2
