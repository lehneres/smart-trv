"""Tests for Smart TRV Setpoint Sensor."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State

from custom_components.smart_trv.sensor import SmartTRVSetpointSensor
from custom_components.smart_trv.const import (
    ATTR_VALVE_POSITION,
    ATTR_ROOM_TEMPERATURE,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_NAME,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    VALVE_OPEN_POSITION,
)


@pytest.fixture
def hass() -> MagicMock:
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    hass.data = {}
    return hass


@pytest.fixture
def config_entry() -> MagicMock:
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "sensor_entry"
    entry.data = {
        CONF_NAME: "Test Smart TRV",
        CONF_MIN_TEMP: DEFAULT_MIN_TEMP,
        CONF_MAX_TEMP: DEFAULT_MAX_TEMP,
    }
    return entry


def _make_state(attrs: dict) -> MagicMock:
    st = MagicMock(spec=State)
    st.attributes = attrs
    st.state = "unknown"
    return st


@pytest.mark.asyncio
async def test_sensor_native_value_from_valve(hass: MagicMock, config_entry: MagicMock):
    """Sensor native value should map from valve position 0–255 to °C setpoint."""
    sensor = SmartTRVSetpointSensor(hass, config_entry)
    # Avoid touching HA internals
    sensor.async_write_ha_state = MagicMock()
    # Bypass registry resolution by setting climate entity id directly
    sensor._climate_entity_id = "climate.smart_trv_test"

    valve_pos = 128
    attrs = {
        ATTR_VALVE_POSITION: valve_pos,
    }
    hass.states.get.return_value = _make_state(attrs)

    await sensor._update_from_climate_state()

    span = DEFAULT_MAX_TEMP - DEFAULT_MIN_TEMP
    expected = DEFAULT_MIN_TEMP + (valve_pos / float(VALVE_OPEN_POSITION)) * span
    assert sensor.native_value is not None
    assert abs(sensor.native_value - expected) < 1e-6


@pytest.mark.asyncio
async def test_sensor_attributes_include_target_error_and_valve(hass: MagicMock, config_entry: MagicMock):
    """Attributes should include target_temperature, error, and target_valve_position when available."""
    sensor = SmartTRVSetpointSensor(hass, config_entry)
    sensor.async_write_ha_state = MagicMock()
    sensor._climate_entity_id = "climate.smart_trv_test"

    target = 22.0
    room = 20.5
    valve_pos = 200
    attrs = {
        ATTR_VALVE_POSITION: valve_pos,
        "temperature": target,  # ATTR_TEMPERATURE string literal to avoid HA import here
        ATTR_ROOM_TEMPERATURE: room,
    }
    hass.states.get.return_value = _make_state(attrs)

    await sensor._update_from_climate_state()

    state_attrs = sensor.extra_state_attributes
    assert state_attrs["target_temperature"] == target
    assert "error" in state_attrs
    assert abs(state_attrs["error"] - (target - room)) < 1e-6
    assert state_attrs["target_valve_position"] == valve_pos


@pytest.mark.asyncio
async def test_sensor_handles_missing_values(hass: MagicMock, config_entry: MagicMock):
    """Sensor should handle missing valve or temps gracefully."""
    sensor = SmartTRVSetpointSensor(hass, config_entry)
    sensor.async_write_ha_state = MagicMock()
    sensor._climate_entity_id = "climate.smart_trv_test"

    # Only target temperature present
    target = 21.0
    attrs = {
        "temperature": target,
    }
    hass.states.get.return_value = _make_state(attrs)

    await sensor._update_from_climate_state()

    # Native value unknown because valve missing
    assert sensor.native_value is None
    state_attrs = sensor.extra_state_attributes
    assert state_attrs["target_temperature"] == target
    # No error without room temperature
    assert "error" not in state_attrs
    # No target valve position without valve
    assert "target_valve_position" not in state_attrs
