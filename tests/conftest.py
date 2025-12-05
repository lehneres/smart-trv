"""Fixtures for Smart TRV Controller tests."""
from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.climate import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State

from custom_components.smart_trv.const import (
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_PRECISION,
    CONF_TARGET_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_TRV_ENTITIES,
    CONF_IMC_PROCESS_GAIN,
    CONF_IMC_TIME_CONSTANT,
    CONF_IMC_DEAD_TIME,
    CONF_IMC_LAMBDA,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_PRECISION,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
)


@pytest.fixture
def hass() -> Generator[MagicMock, None, None]:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_reload = AsyncMock()
    hass.config_entries.async_update_entry = MagicMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    return hass


@pytest.fixture
def mock_config_entry() -> ConfigEntry:
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.data = {
        CONF_NAME: "Test Smart TRV",
        CONF_TEMPERATURE_SENSOR: "sensor.room_temperature",
        CONF_TRV_ENTITIES: ["climate.trv_living_room", "climate.trv_bedroom"],
        CONF_MIN_TEMP: DEFAULT_MIN_TEMP,
        CONF_MAX_TEMP: DEFAULT_MAX_TEMP,
        CONF_TARGET_TEMP: DEFAULT_TARGET_TEMP,
        CONF_PRECISION: DEFAULT_PRECISION,
        # IMC parameters (deterministic for tests)
        CONF_IMC_PROCESS_GAIN: 4.0,
        CONF_IMC_TIME_CONSTANT: 5400.0,
        CONF_IMC_DEAD_TIME: 900.0,
        # Leave lambda unset to default to tau
        # CONF_IMC_LAMBDA: 5400.0,
    }
    entry.options = {}
    entry.add_update_listener = MagicMock()
    entry.async_on_unload = MagicMock()
    return entry


@pytest.fixture
def mock_config_data() -> dict[str, Any]:
    """Return mock configuration data."""
    return {
        CONF_NAME: "Test Smart TRV",
        CONF_TEMPERATURE_SENSOR: "sensor.room_temperature",
        CONF_TRV_ENTITIES: ["climate.trv_living_room", "climate.trv_bedroom"],
        CONF_MIN_TEMP: DEFAULT_MIN_TEMP,
        CONF_MAX_TEMP: DEFAULT_MAX_TEMP,
        CONF_TARGET_TEMP: DEFAULT_TARGET_TEMP,
        CONF_PRECISION: DEFAULT_PRECISION,
        CONF_IMC_PROCESS_GAIN: 4.0,
        CONF_IMC_TIME_CONSTANT: 5400.0,
        CONF_IMC_DEAD_TIME: 900.0,
        # CONF_IMC_LAMBDA intentionally omitted
    }


@pytest.fixture
def mock_temperature_state() -> State:
    """Create a mock temperature sensor state."""
    state = MagicMock(spec=State)
    state.state = "20.0"
    state.attributes = {}
    return state


@pytest.fixture
def mock_trv_state() -> State:
    """Create a mock TRV state."""
    state = MagicMock(spec=State)
    state.state = HVACMode.HEAT
    state.attributes = {}
    return state


@pytest.fixture
def mock_unavailable_state() -> State:
    """Create a mock unavailable state."""
    state = MagicMock(spec=State)
    state.state = STATE_UNAVAILABLE
    state.attributes = {}
    return state


@pytest.fixture
def mock_last_state() -> State:
    """Create a mock last state for restore."""
    state = MagicMock(spec=State)
    state.state = HVACMode.HEAT
    state.attributes = {"temperature": 21.0}
    return state
