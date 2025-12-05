"""Tests for Smart TRV Controller integration setup."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from custom_components.smart_trv import (
    PLATFORMS,
    async_setup_entry,
    async_unload_entry,
    async_update_options,
)
from custom_components.smart_trv.const import (
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_PRECISION,
    CONF_IMC_PROCESS_GAIN,
    CONF_IMC_TIME_CONSTANT,
    CONF_IMC_DEAD_TIME,
    CONF_TARGET_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_TRV_ENTITIES,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_PRECISION,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
)


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_reload = AsyncMock()
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.data = {
        CONF_NAME: "Test Smart TRV",
        CONF_TEMPERATURE_SENSOR: "sensor.room_temperature",
        CONF_TRV_ENTITIES: ["climate.trv_living_room"],
        CONF_MIN_TEMP: DEFAULT_MIN_TEMP,
        CONF_MAX_TEMP: DEFAULT_MAX_TEMP,
        CONF_TARGET_TEMP: DEFAULT_TARGET_TEMP,
        CONF_PRECISION: DEFAULT_PRECISION,
        # IMC parameters for controller
        CONF_IMC_PROCESS_GAIN: 4.0,
        CONF_IMC_TIME_CONSTANT: 5400.0,
        CONF_IMC_DEAD_TIME: 900.0,
    }
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock()
    return entry


class TestPlatforms:
    """Tests for platform configuration."""

    def test_platforms_contains_climate(self):
        """Test that PLATFORMS contains climate platform."""
        assert Platform.CLIMATE in PLATFORMS

    def test_platforms_is_list(self):
        """Test that PLATFORMS is a list."""
        assert isinstance(PLATFORMS, list)


class TestAsyncSetupEntry:
    """Tests for async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_setup_entry_initializes_domain_data(self, mock_hass, mock_config_entry):
        """Test that setup entry initializes domain data."""
        result = await async_setup_entry(mock_hass, mock_config_entry)
        
        assert DOMAIN in mock_hass.data
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_setup_entry_stores_config_data(self, mock_hass, mock_config_entry):
        """Test that setup entry stores configuration data."""
        await async_setup_entry(mock_hass, mock_config_entry)
        
        stored_data = mock_hass.data[DOMAIN][mock_config_entry.entry_id]
        assert stored_data == mock_config_entry.data

    @pytest.mark.asyncio
    async def test_setup_entry_forwards_to_platforms(self, mock_hass, mock_config_entry):
        """Test that setup entry forwards to climate platform."""
        await async_setup_entry(mock_hass, mock_config_entry)
        
        mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
            mock_config_entry, PLATFORMS
        )

    @pytest.mark.asyncio
    async def test_setup_entry_registers_update_listener(self, mock_hass, mock_config_entry):
        """Test that setup entry registers update listener."""
        await async_setup_entry(mock_hass, mock_config_entry)
        
        mock_config_entry.async_on_unload.assert_called_once()

    @pytest.mark.asyncio
    async def test_setup_entry_returns_true(self, mock_hass, mock_config_entry):
        """Test that setup entry returns True on success."""
        result = await async_setup_entry(mock_hass, mock_config_entry)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_setup_entry_handles_existing_domain_data(self, mock_hass, mock_config_entry):
        """Test that setup entry handles existing domain data."""
        # Pre-populate domain data
        mock_hass.data[DOMAIN] = {"existing_entry": {}}
        
        await async_setup_entry(mock_hass, mock_config_entry)
        
        # Should not overwrite existing entries
        assert "existing_entry" in mock_hass.data[DOMAIN]
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry function."""

    @pytest.mark.asyncio
    async def test_unload_entry_unloads_platforms(self, mock_hass, mock_config_entry):
        """Test that unload entry unloads platforms."""
        # Setup first
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_config_entry.data}
        
        await async_unload_entry(mock_hass, mock_config_entry)
        
        mock_hass.config_entries.async_unload_platforms.assert_called_once_with(
            mock_config_entry, PLATFORMS
        )

    @pytest.mark.asyncio
    async def test_unload_entry_removes_entry_data(self, mock_hass, mock_config_entry):
        """Test that unload entry removes entry data from hass.data."""
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_config_entry.data}
        
        await async_unload_entry(mock_hass, mock_config_entry)
        
        assert mock_config_entry.entry_id not in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_unload_entry_returns_true_on_success(self, mock_hass, mock_config_entry):
        """Test that unload entry returns True on success."""
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_config_entry.data}
        
        result = await async_unload_entry(mock_hass, mock_config_entry)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_unload_entry_returns_false_on_failure(self, mock_hass, mock_config_entry):
        """Test that unload entry returns False when platform unload fails."""
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_config_entry.data}
        mock_hass.config_entries.async_unload_platforms.return_value = False
        
        result = await async_unload_entry(mock_hass, mock_config_entry)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_unload_entry_keeps_data_on_failure(self, mock_hass, mock_config_entry):
        """Test that unload entry keeps data when platform unload fails."""
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_config_entry.data}
        mock_hass.config_entries.async_unload_platforms.return_value = False
        
        await async_unload_entry(mock_hass, mock_config_entry)
        
        # Data should still be present
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_unload_entry_preserves_other_entries(self, mock_hass, mock_config_entry):
        """Test that unload entry preserves other entries."""
        mock_hass.data[DOMAIN] = {
            mock_config_entry.entry_id: mock_config_entry.data,
            "other_entry": {"some": "data"},
        }
        
        await async_unload_entry(mock_hass, mock_config_entry)
        
        assert "other_entry" in mock_hass.data[DOMAIN]


class TestAsyncUpdateOptions:
    """Tests for async_update_options function."""

    @pytest.mark.asyncio
    async def test_update_options_reloads_entry(self, mock_hass, mock_config_entry):
        """Test that update options reloads the config entry."""
        await async_update_options(mock_hass, mock_config_entry)
        
        mock_hass.config_entries.async_reload.assert_called_once_with(
            mock_config_entry.entry_id
        )


class TestDomainConstant:
    """Tests for domain constant."""

    def test_domain_value(self):
        """Test that domain is correctly defined."""
        assert DOMAIN == "smart_trv"


class TestIntegrationFlow:
    """Integration tests for full setup/unload flow."""

    @pytest.mark.asyncio
    async def test_full_setup_and_unload_flow(self, mock_hass, mock_config_entry):
        """Test complete setup and unload flow."""
        # Setup
        setup_result = await async_setup_entry(mock_hass, mock_config_entry)
        assert setup_result is True
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]
        
        # Unload
        unload_result = await async_unload_entry(mock_hass, mock_config_entry)
        assert unload_result is True
        assert mock_config_entry.entry_id not in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_multiple_entries_setup(self, mock_hass):
        """Test setting up multiple config entries."""
        entry1 = MagicMock(spec=ConfigEntry)
        entry1.entry_id = "entry_1"
        entry1.data = {CONF_NAME: "TRV 1"}
        entry1.async_on_unload = MagicMock()
        
        entry2 = MagicMock(spec=ConfigEntry)
        entry2.entry_id = "entry_2"
        entry2.data = {CONF_NAME: "TRV 2"}
        entry2.async_on_unload = MagicMock()
        
        await async_setup_entry(mock_hass, entry1)
        await async_setup_entry(mock_hass, entry2)
        
        assert entry1.entry_id in mock_hass.data[DOMAIN]
        assert entry2.entry_id in mock_hass.data[DOMAIN]
        assert len(mock_hass.data[DOMAIN]) == 2

    @pytest.mark.asyncio
    async def test_unload_one_of_multiple_entries(self, mock_hass):
        """Test unloading one entry when multiple are setup."""
        entry1 = MagicMock(spec=ConfigEntry)
        entry1.entry_id = "entry_1"
        entry1.data = {CONF_NAME: "TRV 1"}
        entry1.async_on_unload = MagicMock()
        
        entry2 = MagicMock(spec=ConfigEntry)
        entry2.entry_id = "entry_2"
        entry2.data = {CONF_NAME: "TRV 2"}
        entry2.async_on_unload = MagicMock()
        
        await async_setup_entry(mock_hass, entry1)
        await async_setup_entry(mock_hass, entry2)
        
        # Unload first entry
        await async_unload_entry(mock_hass, entry1)
        
        assert entry1.entry_id not in mock_hass.data[DOMAIN]
        assert entry2.entry_id in mock_hass.data[DOMAIN]
