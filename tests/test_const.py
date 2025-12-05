"""Tests for Smart TRV Controller constants."""
from custom_components.smart_trv.const import (
    ATTR_ROOM_TEMPERATURE,
    ATTR_TRV_ENTITIES,
    ATTR_VALVE_POSITION,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_NAME,
    CONF_PRECISION,
    CONF_TARGET_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_TRV_ENTITIES,
    CONF_IMC_PROCESS_GAIN,
    CONF_IMC_DEAD_TIME,
    CONF_IMC_TIME_CONSTANT,
    CONF_IMC_LAMBDA,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_NAME,
    DEFAULT_PRECISION,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    VALVE_CLOSED_POSITION,
    VALVE_OPEN_POSITION,
)


def test_domain():
    """Test the domain constant."""
    assert DOMAIN == "smart_trv"


def test_configuration_keys():
    """Test configuration key constants."""
    assert CONF_TEMPERATURE_SENSOR == "temperature_sensor"
    assert CONF_TRV_ENTITIES == "trv_entities"
    assert CONF_NAME == "name"
    assert CONF_MIN_TEMP == "min_temp"
    assert CONF_MAX_TEMP == "max_temp"
    assert CONF_TARGET_TEMP == "target_temp"
    assert CONF_PRECISION == "precision"


def test_default_values():
    """Test default value constants."""
    assert DEFAULT_NAME == "Smart TRV"
    assert DEFAULT_MIN_TEMP == 5.0
    assert DEFAULT_MAX_TEMP == 28.0
    assert DEFAULT_TARGET_TEMP == 21.0
    assert DEFAULT_PRECISION == 0.5


def test_valve_control_constants():
    """Test valve control constants."""
    assert VALVE_OPEN_POSITION == 255
    assert VALVE_CLOSED_POSITION == 0


def test_imc_parameters():
    """Test IMC parameter constants are present."""
    assert CONF_IMC_PROCESS_GAIN == "imc_process_gain"
    assert CONF_IMC_DEAD_TIME == "imc_dead_time"
    assert CONF_IMC_TIME_CONSTANT == "imc_time_constant"
    assert CONF_IMC_LAMBDA == "imc_lambda"




def test_attributes():
    """Test attribute constants."""
    assert ATTR_VALVE_POSITION == "valve_position"
    assert ATTR_ROOM_TEMPERATURE == "room_temperature"
    assert ATTR_TRV_ENTITIES == "trv_entities"


def test_default_temperature_range():
    """Test that default temperature range is valid."""
    assert DEFAULT_MIN_TEMP < DEFAULT_MAX_TEMP
    assert DEFAULT_MIN_TEMP <= DEFAULT_TARGET_TEMP <= DEFAULT_MAX_TEMP


def test_valve_position_range():
    """Test that valve position range is valid."""
    assert VALVE_CLOSED_POSITION < VALVE_OPEN_POSITION
    assert VALVE_CLOSED_POSITION >= 0
    assert VALVE_OPEN_POSITION <= 255
