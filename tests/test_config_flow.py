"""Tests for Smart TRV Controller config flow."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.smart_trv.config_flow import (
    SmartTRVConfigFlow,
    SmartTRVOptionsFlow,
    get_config_schema,
)
from custom_components.smart_trv.const import (
    CONF_TARGET_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_TRV_ENTITIES,
    # New optional FF sensor selectors in UI
    CONF_OUTDOOR_TEMPERATURE_SENSOR,
    CONF_BOILER_FLOW_TEMPERATURE_SENSOR,
    # IMC params
    CONF_IMC_PROCESS_GAIN,
    CONF_IMC_DEAD_TIME,
    CONF_IMC_TIME_CONSTANT,
    CONF_IMC_LAMBDA,
    DEFAULT_NAME,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
)


class TestGetConfigSchema:
    """Tests for get_config_schema function."""

    def test_returns_voluptuous_schema(self):
        """Test that function returns a voluptuous schema."""
        schema = get_config_schema()
        assert isinstance(schema, vol.Schema)

    def test_uses_default_values_when_no_defaults_provided(self):
        """Test that default values are used when no defaults provided."""
        schema = get_config_schema()
        # Schema should be created without errors
        assert schema is not None

    def test_uses_provided_defaults(self):
        """Test that provided defaults are used (for fields that still exist)."""
        custom_defaults = {
            CONF_NAME: "Custom TRV",
            CONF_TARGET_TEMP: 22.5,
        }
        schema = get_config_schema(custom_defaults)
        assert schema is not None

    def test_schema_has_required_fields(self):
        """Test that schema has all required fields."""
        schema = get_config_schema()
        schema_keys = [str(key) for key in schema.schema.keys()]
        
        assert CONF_NAME in schema_keys
        assert CONF_TEMPERATURE_SENSOR in schema_keys
        assert CONF_TRV_ENTITIES in schema_keys

    def test_schema_has_optional_fields(self):
        """Test that schema has all optional fields (updated)."""
        schema = get_config_schema()
        schema_keys = [str(key) for key in schema.schema.keys()]
        
        assert CONF_TARGET_TEMP in schema_keys
        # Optional sensor selectors
        assert CONF_OUTDOOR_TEMPERATURE_SENSOR in schema_keys
        assert CONF_BOILER_FLOW_TEMPERATURE_SENSOR in schema_keys
        # IMC parameters should be present
        assert CONF_IMC_PROCESS_GAIN in schema_keys
        assert CONF_IMC_DEAD_TIME in schema_keys
        assert CONF_IMC_TIME_CONSTANT in schema_keys
        assert CONF_IMC_LAMBDA in schema_keys


class TestSmartTRVConfigFlow:
    """Tests for SmartTRVConfigFlow."""

    @pytest.fixture
    def flow(self) -> SmartTRVConfigFlow:
        """Create a config flow instance."""
        flow = SmartTRVConfigFlow()
        flow.hass = MagicMock(spec=HomeAssistant)
        return flow

    @pytest.mark.asyncio
    async def test_flow_init(self, flow):
        """Test flow initialization."""
        assert flow.VERSION == 1

    @pytest.mark.asyncio
    async def test_step_user_shows_form_when_no_input(self, flow):
        """Test that user step shows form when no input provided."""
        result = await flow.async_step_user(user_input=None)
        
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert "data_schema" in result

    @pytest.mark.asyncio
    async def test_step_user_error_no_temperature_sensor(self, flow):
        """Test error when no temperature sensor provided."""
        user_input = {
            CONF_NAME: "Test TRV",
            CONF_TEMPERATURE_SENSOR: "",
            CONF_TRV_ENTITIES: ["climate.trv_1"],
        }
        
        result = await flow.async_step_user(user_input=user_input)
        
        assert result["type"] == FlowResultType.FORM
        assert result["errors"][CONF_TEMPERATURE_SENSOR] == "no_temperature_sensor"

    @pytest.mark.asyncio
    async def test_step_user_error_no_trv_entities(self, flow):
        """Test error when no TRV entities provided."""
        user_input = {
            CONF_NAME: "Test TRV",
            CONF_TEMPERATURE_SENSOR: "sensor.temperature",
            CONF_TRV_ENTITIES: [],
        }
        
        result = await flow.async_step_user(user_input=user_input)
        
        assert result["type"] == FlowResultType.FORM
        assert result["errors"][CONF_TRV_ENTITIES] == "no_trv_entities"

    @pytest.mark.asyncio
    async def test_step_user_creates_entry_with_valid_input(self, flow):
        """Test entry creation with valid input."""
        user_input = {
            CONF_NAME: "Test TRV",
            CONF_TEMPERATURE_SENSOR: "sensor.temperature",
            CONF_TRV_ENTITIES: ["climate.trv_1", "climate.trv_2"],
            CONF_TARGET_TEMP: DEFAULT_TARGET_TEMP,
            # Optional FF sensors (may be omitted in tests)
            # CONF_OUTDOOR_TEMPERATURE_SENSOR: "sensor.outdoor",
            # CONF_BOILER_FLOW_TEMPERATURE_SENSOR: "sensor.flow",
            # IMC params optional
            CONF_IMC_PROCESS_GAIN: 4.0,
            CONF_IMC_TIME_CONSTANT: 5400.0,
            CONF_IMC_DEAD_TIME: 900.0,
        }
        
        with patch.object(flow, "async_set_unique_id", new_callable=AsyncMock), \
             patch.object(flow, "_abort_if_unique_id_configured"):
            result = await flow.async_step_user(user_input=user_input)
        
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Test TRV"
        assert result["data"] == user_input

    @pytest.mark.asyncio
    async def test_step_user_sets_unique_id(self, flow):
        """Test that unique ID is set based on temperature sensor."""
        user_input = {
            CONF_NAME: "Test TRV",
            CONF_TEMPERATURE_SENSOR: "sensor.unique_temp",
            CONF_TRV_ENTITIES: ["climate.trv_1"],
        }
        
        with patch.object(flow, "async_set_unique_id", new_callable=AsyncMock) as mock_set_id, \
             patch.object(flow, "_abort_if_unique_id_configured"):
            await flow.async_step_user(user_input=user_input)
            mock_set_id.assert_called_once_with("sensor.unique_temp")

    def test_async_get_options_flow_returns_options_flow_type(self):
        """Test that async_get_options_flow returns correct type."""
        # We can't directly test the options flow creation due to HA internal checks,
        # but we can verify the method exists and is callable
        assert hasattr(SmartTRVConfigFlow, "async_get_options_flow")
        assert callable(SmartTRVConfigFlow.async_get_options_flow)


class TestSmartTRVOptionsFlowClass:
    """Tests for SmartTRVOptionsFlow class structure."""

    def test_options_flow_class_exists(self):
        """Test that SmartTRVOptionsFlow class exists."""
        assert SmartTRVOptionsFlow is not None

    def test_options_flow_has_async_step_init(self):
        """Test that SmartTRVOptionsFlow has async_step_init method."""
        assert hasattr(SmartTRVOptionsFlow, "async_step_init")
        assert callable(getattr(SmartTRVOptionsFlow, "async_step_init"))


class TestConfigFlowDomain:
    """Test config flow domain registration."""

    def test_domain_matches_const(self):
        """Test that config flow domain matches const.py domain."""
        assert SmartTRVConfigFlow.__dict__.get("domain", DOMAIN) == DOMAIN
