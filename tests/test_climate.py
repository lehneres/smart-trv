"""Tests for Smart TRV Controller climate entity."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.climate import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State

from custom_components.smart_trv.climate import SmartTRVClimate, async_setup_entry
from custom_components.smart_trv.const import (
    ATTR_ROOM_TEMPERATURE,
    ATTR_TRV_ENTITIES,
    ATTR_VALVE_POSITION,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_PRECISION,
    CONF_TARGET_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_TRV_ENTITIES,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_PRECISION,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    VALVE_CLOSED_POSITION,
    VALVE_OPEN_POSITION,
)


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: coro)
    return hass


@pytest.fixture
def mock_config() -> dict[str, Any]:
    """Create mock configuration."""
    return {
        CONF_NAME: "Test Smart TRV",
        CONF_TEMPERATURE_SENSOR: "sensor.room_temperature",
        CONF_TRV_ENTITIES: ["climate.trv_living_room", "climate.trv_bedroom", "climate.trv_kids_room_left", "climate.trv_kids_room_right"],
        CONF_MIN_TEMP: DEFAULT_MIN_TEMP,
        CONF_MAX_TEMP: DEFAULT_MAX_TEMP,
        CONF_TARGET_TEMP: DEFAULT_TARGET_TEMP,
        CONF_PRECISION: DEFAULT_PRECISION,
        # IMC parameters for deterministic gains
        "imc_process_gain": 4.0,
        "imc_time_constant": 5400.0,
        "imc_dead_time": 900.0,
    }


@pytest.fixture
def climate_entity(mock_hass, mock_config) -> SmartTRVClimate:
    """Create a SmartTRVClimate entity."""
    return SmartTRVClimate(mock_hass, "test_entry_id", mock_config)


class TestAsyncSetupEntry:
    """Tests for async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_setup_creates_entity(self, mock_hass, mock_config):
        """Test that setup creates a climate entity."""
        config_entry = MagicMock()
        config_entry.entry_id = "test_entry"
        config_entry.data = mock_config
        
        entities_added = []
        
        def mock_add_entities(entities, update_before_add):
            entities_added.extend(entities)
        
        await async_setup_entry(mock_hass, config_entry, mock_add_entities)
        
        assert len(entities_added) == 1
        assert isinstance(entities_added[0], SmartTRVClimate)


class TestSmartTRVClimateInit:
    """Tests for SmartTRVClimate initialization."""

    def test_init_sets_basic_attributes(self, climate_entity, mock_config):
        """Test that initialization sets basic attributes."""
        assert climate_entity._name == mock_config[CONF_NAME]
        assert climate_entity._temperature_sensor == mock_config[CONF_TEMPERATURE_SENSOR]
        assert climate_entity._trv_entities == mock_config[CONF_TRV_ENTITIES]

    def test_init_sets_temperature_config(self, climate_entity, mock_config):
        """Test that initialization sets temperature configuration."""
        assert climate_entity._min_temp == mock_config[CONF_MIN_TEMP]
        assert climate_entity._max_temp == mock_config[CONF_MAX_TEMP]
        assert climate_entity._target_temp == mock_config[CONF_TARGET_TEMP]
        assert climate_entity._precision == mock_config[CONF_PRECISION]

    def test_init_sets_control_config(self, climate_entity):
        """Test that initialization computes IMC gains (positive)."""
        assert climate_entity._proportional_gain > 0.0
        assert climate_entity._integral_gain > 0.0

    def test_init_sets_default_state(self, climate_entity):
        """Test that initialization sets default state."""
        assert climate_entity._hvac_mode == HVACMode.AUTO
        assert climate_entity._current_temperature is None
        assert climate_entity._valve_position == VALVE_CLOSED_POSITION

    def test_init_sets_entity_attributes(self, climate_entity):
        """Test that initialization sets entity attributes."""
        assert climate_entity._attr_unique_id == f"{DOMAIN}_test_entry_id"
        assert climate_entity._attr_name == "Test Smart TRV"
        assert climate_entity._attr_has_entity_name is True

    def test_class_attributes(self, climate_entity):
        """Test class-level attributes."""
        assert climate_entity._attr_hvac_modes == [HVACMode.OFF, HVACMode.AUTO, HVACMode.HEAT]
        # Should support target temperature plus turn_on/turn_off services
        assert (
            climate_entity._attr_supported_features
            & ClimateEntityFeature.TARGET_TEMPERATURE
        )
        assert (
            climate_entity._attr_supported_features
            & ClimateEntityFeature.TURN_OFF
        )
        assert (
            climate_entity._attr_supported_features
            & ClimateEntityFeature.TURN_ON
        )
        assert climate_entity._attr_temperature_unit == UnitOfTemperature.CELSIUS


class TestSmartTRVClimateProperties:
    """Tests for SmartTRVClimate properties."""

    def test_min_temp_property(self, climate_entity):
        """Test min_temp property."""
        assert climate_entity.min_temp == DEFAULT_MIN_TEMP

    def test_max_temp_property(self, climate_entity):
        """Test max_temp property."""
        assert climate_entity.max_temp == DEFAULT_MAX_TEMP

    def test_target_temperature_step_property(self, climate_entity):
        """Test target_temperature_step property."""
        assert climate_entity.target_temperature_step == DEFAULT_PRECISION

    def test_current_temperature_property(self, climate_entity):
        """Test current_temperature property."""
        assert climate_entity.current_temperature is None
        climate_entity._current_temperature = 21.5
        assert climate_entity.current_temperature == 21.5

    def test_target_temperature_property(self, climate_entity):
        """Test target_temperature property."""
        assert climate_entity.target_temperature == DEFAULT_TARGET_TEMP

    def test_hvac_mode_property(self, climate_entity):
        """Test hvac_mode property."""
        assert climate_entity.hvac_mode == HVACMode.AUTO
        climate_entity._hvac_mode = HVACMode.OFF
        assert climate_entity.hvac_mode == HVACMode.OFF


class TestSmartTRVClimateHvacAction:
    """Tests for hvac_action property."""

    def test_hvac_action_off_when_mode_off(self, climate_entity):
        """Test hvac_action returns OFF when mode is OFF."""
        climate_entity._hvac_mode = HVACMode.OFF
        assert climate_entity.hvac_action == HVACAction.OFF

    def test_hvac_action_heating_when_valve_open(self, climate_entity):
        """Test hvac_action returns HEATING when valve is open."""
        climate_entity._hvac_mode = HVACMode.HEAT
        climate_entity._valve_position = 50
        assert climate_entity.hvac_action == HVACAction.HEATING

    def test_hvac_action_idle_when_valve_closed(self, climate_entity):
        """Test hvac_action returns IDLE when valve is closed."""
        climate_entity._hvac_mode = HVACMode.HEAT
        climate_entity._valve_position = 0
        assert climate_entity.hvac_action == HVACAction.IDLE


class TestSmartTRVClimateExtraStateAttributes:
    """Tests for extra_state_attributes property."""

    def test_extra_state_attributes(self, climate_entity, mock_config):
        """Test extra_state_attributes returns correct values."""
        climate_entity._valve_position = 75
        climate_entity._current_temperature = 19.5
        
        attrs = climate_entity.extra_state_attributes
        
        assert attrs[ATTR_VALVE_POSITION] == 75
        assert attrs[ATTR_ROOM_TEMPERATURE] == 19.5
        assert attrs[ATTR_TRV_ENTITIES] == mock_config[CONF_TRV_ENTITIES]


class TestSmartTRVClimateTemperatureUpdate:
    """Tests for temperature update functionality."""

    @pytest.mark.asyncio
    async def test_update_temperature_success(self, climate_entity, mock_hass):
        """Test successful temperature update."""
        mock_state = MagicMock(spec=State)
        mock_state.state = "21.5"
        mock_hass.states.get.return_value = mock_state
        
        await climate_entity._async_update_temperature()
        
        assert climate_entity._current_temperature == 21.5

    @pytest.mark.asyncio
    async def test_update_temperature_unavailable(self, climate_entity, mock_hass):
        """Test temperature update when sensor unavailable."""
        mock_state = MagicMock(spec=State)
        mock_state.state = STATE_UNAVAILABLE
        mock_hass.states.get.return_value = mock_state
        
        climate_entity._current_temperature = 20.0  # Set initial value
        await climate_entity._async_update_temperature()
        
        # Temperature should remain unchanged
        assert climate_entity._current_temperature == 20.0

    @pytest.mark.asyncio
    async def test_update_temperature_unknown(self, climate_entity, mock_hass):
        """Test temperature update when sensor unknown."""
        mock_state = MagicMock(spec=State)
        mock_state.state = STATE_UNKNOWN
        mock_hass.states.get.return_value = mock_state
        
        climate_entity._current_temperature = 20.0
        await climate_entity._async_update_temperature()
        
        assert climate_entity._current_temperature == 20.0

    @pytest.mark.asyncio
    async def test_update_temperature_none_state(self, climate_entity, mock_hass):
        """Test temperature update when state is None."""
        mock_hass.states.get.return_value = None
        
        climate_entity._current_temperature = 20.0
        await climate_entity._async_update_temperature()
        
        assert climate_entity._current_temperature == 20.0

    @pytest.mark.asyncio
    async def test_update_temperature_invalid_value(self, climate_entity, mock_hass):
        """Test temperature update with invalid value."""
        mock_state = MagicMock(spec=State)
        mock_state.state = "invalid"
        mock_hass.states.get.return_value = mock_state
        
        climate_entity._current_temperature = 20.0
        await climate_entity._async_update_temperature()
        
        # Temperature should remain unchanged due to parse error
        assert climate_entity._current_temperature == 20.0


class TestSmartTRVClimateValvePositionCalculation:
    """Tests for valve position calculation."""

    @pytest.mark.asyncio
    async def test_valve_position_when_mode_off(self, climate_entity, mock_hass):
        """Test valve position is 0 when mode is OFF."""
        climate_entity._hvac_mode = HVACMode.OFF
        climate_entity._current_temperature = 18.0
        
        await climate_entity._async_control_heating()
        
        assert climate_entity._valve_position == VALVE_CLOSED_POSITION

    @pytest.mark.asyncio
    async def test_valve_position_when_no_temperature(self, climate_entity, mock_hass):
        """Test valve position unchanged when no temperature available."""
        climate_entity._hvac_mode = HVACMode.AUTO
        climate_entity._current_temperature = None
        climate_entity._valve_position = 50
        
        await climate_entity._async_control_heating()
        
        # Valve position should remain unchanged
        assert climate_entity._valve_position == 50

    @pytest.mark.asyncio
    async def test_valve_position_proportional_control_heating_needed(self, climate_entity, mock_hass):
        """Test valve position calculation when heating is needed."""
        climate_entity._hvac_mode = HVACMode.AUTO
        climate_entity._target_temp = 22.0
        climate_entity._current_temperature = 20.0
        climate_entity._proportional_gain = 10.0
        
        # Mock TRV states
        mock_trv_state = MagicMock(spec=State)
        mock_trv_state.state = HVACMode.HEAT
        mock_hass.states.get.return_value = mock_trv_state
        
        await climate_entity._async_control_heating()

        # IMC-only PI controller: with i_accum=0 on first call, output is
        # u = clamp(kp * norm_error, 0..1), so expected valve is:
        span = max(0.1, climate_entity._max_temp - climate_entity._min_temp)
        norm = min(climate_entity._target_temp - climate_entity._current_temperature, span) / span
        u = min(1.0, max(0.0, climate_entity._proportional_gain * norm))
        expected = int(round(u * VALVE_OPEN_POSITION))
        assert climate_entity._valve_position == expected

    @pytest.mark.asyncio
    async def test_valve_position_proportional_control_no_heating_needed(self, climate_entity, mock_hass):
        """Test valve position calculation when no heating is needed."""
        climate_entity._hvac_mode = HVACMode.AUTO
        climate_entity._target_temp = 20.0
        climate_entity._current_temperature = 22.0
        climate_entity._proportional_gain = 10.0
        
        mock_trv_state = MagicMock(spec=State)
        mock_trv_state.state = HVACMode.HEAT
        mock_hass.states.get.return_value = mock_trv_state
        
        await climate_entity._async_control_heating()
        
        # Error = 20 - 22 = -2, valve = -2 * 10 = -20, clamped to 0
        assert climate_entity._valve_position == VALVE_CLOSED_POSITION

    @pytest.mark.asyncio
    async def test_valve_position_clamped_to_max(self, climate_entity, mock_hass):
        """Test valve position is clamped to maximum."""
        climate_entity._hvac_mode = HVACMode.AUTO
        # Set error to cover the full configured temperature range so it reaches 255
        climate_entity._target_temp = climate_entity._max_temp
        climate_entity._current_temperature = climate_entity._min_temp
        
        mock_trv_state = MagicMock(spec=State)
        mock_trv_state.state = HVACMode.HEAT
        mock_hass.states.get.return_value = mock_trv_state
        
        await climate_entity._async_control_heating()
        
        # Error equals the configured temperature range -> normalized to 1.0 -> 255
        assert climate_entity._valve_position == VALVE_OPEN_POSITION


class TestSmartTRVClimateSetValvePosition:
    """Tests for setting valve position on TRVs."""

    @pytest.mark.asyncio
    async def test_set_valve_position_via_number_entity(self, climate_entity, mock_hass):
        """Test setting valve position via number entity."""
        mock_trv_state = MagicMock(spec=State)
        mock_trv_state.state = HVACMode.HEAT
        
        mock_valve_state = MagicMock(spec=State)
        
        def mock_get_state(entity_id):
            if "valve_position" in entity_id:
                return mock_valve_state
            return mock_trv_state
        
        mock_hass.states.get.side_effect = mock_get_state
        
        await climate_entity._async_set_valve_position(50)
        
        # Should call number.set_value service
        mock_hass.services.async_call.assert_called()
        call_args = mock_hass.services.async_call.call_args_list
        assert any(
            call[0][0] == "number" and call[0][1] == "set_value"
            for call in call_args
        )

    @pytest.mark.asyncio
    async def test_set_valve_position_via_climate_off(self, climate_entity, mock_hass):
        """Test setting valve position to 0 turns off TRV."""
        mock_trv_state = MagicMock(spec=State)
        mock_trv_state.state = HVACMode.HEAT
        
        def mock_get_state(entity_id):
            if "valve_position" in entity_id:
                return None  # No number entity
            return mock_trv_state
        
        mock_hass.states.get.side_effect = mock_get_state
        
        # Set initial valve position to non-zero so the update is not skipped
        climate_entity._valve_position = 50
        
        await climate_entity._async_set_valve_position(0)
        
        # Should call climate.set_hvac_mode with OFF
        mock_hass.services.async_call.assert_called()
        call_args = mock_hass.services.async_call.call_args_list
        assert any(
            call[0][0] == "climate" and call[0][1] == "set_hvac_mode"
            for call in call_args
        )

    @pytest.mark.asyncio
    async def test_set_valve_position_via_climate_temperature(self, climate_entity, mock_hass):
        """Test setting valve position via climate temperature."""
        mock_trv_state = MagicMock(spec=State)
        mock_trv_state.state = HVACMode.HEAT
        
        def mock_get_state(entity_id):
            if "valve_position" in entity_id:
                return None  # No number entity
            return mock_trv_state
        
        mock_hass.states.get.side_effect = mock_get_state
        
        await climate_entity._async_set_valve_position(50)
        
        # Should call climate.set_temperature
        mock_hass.services.async_call.assert_called()
        call_args = mock_hass.services.async_call.call_args_list
        assert any(
            call[0][0] == "climate" and call[0][1] == "set_temperature"
            for call in call_args
        )

    @pytest.mark.asyncio
    async def test_set_valve_position_turns_on_trv_if_off(self, climate_entity, mock_hass):
        """Test that setting valve position turns on TRV if it's off."""
        mock_trv_state = MagicMock(spec=State)
        mock_trv_state.state = HVACMode.OFF
        
        def mock_get_state(entity_id):
            if "valve_position" in entity_id:
                return None
            return mock_trv_state
        
        mock_hass.states.get.side_effect = mock_get_state
        
        await climate_entity._async_set_valve_position(50)
        
        # Should call climate.set_hvac_mode with HEAT first
        call_args = mock_hass.services.async_call.call_args_list
        hvac_mode_calls = [
            call for call in call_args
            if call[0][0] == "climate" and call[0][1] == "set_hvac_mode"
        ]
        assert len(hvac_mode_calls) > 0

    @pytest.mark.asyncio
    async def test_set_valve_position_trv_not_found(self, climate_entity, mock_hass):
        """Test handling when TRV entity not found."""
        mock_hass.states.get.return_value = None
        
        # Should not raise exception
        await climate_entity._async_set_valve_position(50)
        
        # Services should not be called for missing TRVs
        assert climate_entity._valve_position == 50


class TestSmartTRVClimateSetTemperature:
    """Tests for async_set_temperature method."""

    @pytest.mark.asyncio
    async def test_set_temperature_updates_target(self, climate_entity, mock_hass):
        """Test that set_temperature updates target temperature."""
        mock_state = MagicMock(spec=State)
        mock_state.state = "20.0"
        mock_hass.states.get.return_value = mock_state
        
        climate_entity._current_temperature = 20.0
        climate_entity.async_write_ha_state = MagicMock()
        
        await climate_entity.async_set_temperature(temperature=22.0)
        
        assert climate_entity._target_temp == 22.0
        climate_entity.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_temperature_no_temperature_provided(self, climate_entity, mock_hass):
        """Test set_temperature does nothing when no temperature provided."""
        original_target = climate_entity._target_temp
        
        await climate_entity.async_set_temperature()
        
        assert climate_entity._target_temp == original_target

    @pytest.mark.asyncio
    async def test_set_temperature_triggers_control(self, climate_entity, mock_hass):
        """Test that set_temperature triggers heating control."""
        mock_state = MagicMock(spec=State)
        mock_state.state = HVACMode.HEAT
        mock_hass.states.get.return_value = mock_state
        
        climate_entity._current_temperature = 20.0
        climate_entity.async_write_ha_state = MagicMock()
        
        await climate_entity.async_set_temperature(temperature=25.0)
        
        # Valve position should be updated based on new target
        assert climate_entity._valve_position > 0


class TestSmartTRVClimateSetHvacMode:
    """Tests for async_set_hvac_mode method."""

    @pytest.mark.asyncio
    async def test_set_hvac_mode_heat(self, climate_entity, mock_hass):
        """Test setting HVAC mode to HEAT."""
        mock_state = MagicMock(spec=State)
        mock_state.state = HVACMode.HEAT
        mock_hass.states.get.return_value = mock_state
        
        climate_entity._hvac_mode = HVACMode.OFF
        climate_entity.async_write_ha_state = MagicMock()
        
        await climate_entity.async_set_hvac_mode(HVACMode.HEAT)
        
        assert climate_entity._hvac_mode == HVACMode.HEAT
        climate_entity.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_off(self, climate_entity, mock_hass):
        """Test setting HVAC mode to OFF."""
        mock_state = MagicMock(spec=State)
        mock_state.state = HVACMode.HEAT
        mock_hass.states.get.return_value = mock_state
        
        climate_entity._hvac_mode = HVACMode.HEAT
        climate_entity.async_write_ha_state = MagicMock()
        
        await climate_entity.async_set_hvac_mode(HVACMode.OFF)
        
        assert climate_entity._hvac_mode == HVACMode.OFF
        climate_entity.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_unsupported(self, climate_entity, mock_hass):
        """Test setting unsupported HVAC mode."""
        original_mode = climate_entity._hvac_mode
        climate_entity.async_write_ha_state = MagicMock()
        
        await climate_entity.async_set_hvac_mode(HVACMode.COOL)
        
        # Mode should remain unchanged
        assert climate_entity._hvac_mode == original_mode

    @pytest.mark.asyncio
    async def test_set_hvac_mode_off_closes_valves(self, climate_entity, mock_hass):
        """Test that setting mode to OFF closes all valves."""
        mock_state = MagicMock(spec=State)
        mock_state.state = HVACMode.HEAT
        mock_hass.states.get.return_value = mock_state
        
        climate_entity._valve_position = 50
        climate_entity.async_write_ha_state = MagicMock()
        
        await climate_entity.async_set_hvac_mode(HVACMode.OFF)
        
        assert climate_entity._valve_position == VALVE_CLOSED_POSITION


class TestSmartTRVClimateStateRestoration:
    """Tests for state restoration functionality."""

    @pytest.mark.asyncio
    async def test_restore_hvac_mode(self, climate_entity, mock_hass):
        """Test restoring HVAC mode from last state."""
        mock_last_state = MagicMock()
        mock_last_state.state = HVACMode.OFF
        mock_last_state.attributes = {}
        
        mock_temp_state = MagicMock(spec=State)
        mock_temp_state.state = "20.0"
        mock_hass.states.get.return_value = mock_temp_state
        
        with patch.object(climate_entity, "async_get_last_state", new_callable=AsyncMock) as mock_get_last, \
             patch.object(climate_entity, "async_on_remove") as mock_on_remove, \
             patch("custom_components.smart_trv.climate.async_track_state_change_event") as mock_track:
            mock_get_last.return_value = mock_last_state
            await climate_entity.async_added_to_hass()
        
        assert climate_entity._hvac_mode == HVACMode.OFF

    @pytest.mark.asyncio
    async def test_restore_target_temperature(self, climate_entity, mock_hass):
        """Test restoring target temperature from last state."""
        mock_last_state = MagicMock()
        mock_last_state.state = HVACMode.HEAT
        mock_last_state.attributes = {ATTR_TEMPERATURE: 23.5}
        
        mock_temp_state = MagicMock(spec=State)
        mock_temp_state.state = "20.0"
        mock_hass.states.get.return_value = mock_temp_state
        
        with patch.object(climate_entity, "async_get_last_state", new_callable=AsyncMock) as mock_get_last, \
             patch.object(climate_entity, "async_on_remove") as mock_on_remove, \
             patch("custom_components.smart_trv.climate.async_track_state_change_event") as mock_track:
            mock_get_last.return_value = mock_last_state
            await climate_entity.async_added_to_hass()
        
        assert climate_entity._target_temp == 23.5

    @pytest.mark.asyncio
    async def test_no_restore_when_no_last_state(self, climate_entity, mock_hass):
        """Test behavior when no last state available."""
        mock_temp_state = MagicMock(spec=State)
        mock_temp_state.state = "20.0"
        mock_hass.states.get.return_value = mock_temp_state
        
        original_hvac_mode = climate_entity._hvac_mode
        original_target_temp = climate_entity._target_temp
        
        with patch.object(climate_entity, "async_get_last_state", new_callable=AsyncMock) as mock_get_last, \
             patch.object(climate_entity, "async_on_remove") as mock_on_remove, \
             patch("custom_components.smart_trv.climate.async_track_state_change_event") as mock_track:
            mock_get_last.return_value = None
            await climate_entity.async_added_to_hass()
        
        assert climate_entity._hvac_mode == original_hvac_mode
        assert climate_entity._target_temp == original_target_temp


class TestSmartTRVClimateTemperatureChanged:
    """Tests for temperature change callback."""

    def test_temperature_changed_creates_tasks(self, climate_entity, mock_hass):
        """Test that temperature change callback creates update tasks."""
        mock_event = MagicMock()
        climate_entity.async_write_ha_state = MagicMock()
        
        climate_entity._async_temperature_changed(mock_event)
        
        # Should create tasks for update and control
        assert mock_hass.async_create_task.call_count == 2
        climate_entity.async_write_ha_state.assert_called_once()


class TestSmartTRVClimateEdgeCases:
    """Tests for edge cases."""

    def test_custom_min_max_temp(self, mock_hass):
        """Test climate entity with custom min/max temperatures."""
        config = {
            CONF_NAME: "Custom TRV",
            CONF_TEMPERATURE_SENSOR: "sensor.temp",
            CONF_TRV_ENTITIES: ["climate.trv"],
            CONF_MIN_TEMP: 10.0,
            CONF_MAX_TEMP: 25.0,
            CONF_TARGET_TEMP: 18.0,
            CONF_PRECISION: 1.0,
            # IMC parameters to allow controller to initialize
            "imc_process_gain": 4.0,
            "imc_time_constant": 3600.0,
            "imc_dead_time": 600.0,
        }
        
        entity = SmartTRVClimate(mock_hass, "custom_entry", config)
        
        assert entity.min_temp == 10.0
        assert entity.max_temp == 25.0
        assert entity.target_temperature == 18.0
        assert entity.target_temperature_step == 1.0

    def test_empty_trv_list(self, mock_hass):
        """Test climate entity with empty TRV list."""
        config = {
            CONF_NAME: "Empty TRV",
            CONF_TEMPERATURE_SENSOR: "sensor.temp",
            CONF_TRV_ENTITIES: [],
            # IMC parameters are mandatory
            "imc_process_gain": 4.0,
            "imc_time_constant": 5400.0,
            "imc_dead_time": 900.0,
        }
        
        entity = SmartTRVClimate(mock_hass, "empty_entry", config)
        
        assert entity._trv_entities == []

    @pytest.mark.asyncio
    async def test_service_call_exception_handling(self, climate_entity, mock_hass):
        """Test that service call exceptions are handled gracefully."""
        mock_trv_state = MagicMock(spec=State)
        mock_trv_state.state = HVACMode.HEAT
        
        def mock_get_state(entity_id):
            if "valve_position" in entity_id:
                return None
            return mock_trv_state
        
        mock_hass.states.get.side_effect = mock_get_state
        mock_hass.services.async_call.side_effect = Exception("Service error")
        
        # Should not raise exception
        await climate_entity._async_set_valve_position(50)
        
        # Valve position should still be updated internally
        assert climate_entity._valve_position == 50
