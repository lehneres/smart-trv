"""Sensor platform for Smart TRV Controller (minimal, focused).

Exposes four standalone sensors derived from the companion Smart TRV climate entity:
- Effective Setpoint (°C) computed from valve position mapping (0–255 → min..max)
- Target Temperature (°C) mirrored from the climate entity
- Temperature Error (°C) = target - room
- Valve Position (0–255)

Each sensor subscribes to the climate entity state and updates reactively.
"""
from __future__ import annotations

from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ATTR_ROOM_TEMPERATURE,
    ATTR_VALVE_POSITION,
    ATTR_ACTUAL_VALVE_POSITION,
    ATTR_DESIRED_VALVE_POSITION,
    ATTR_ERROR_C,
    ATTR_ERROR_NORM,
    ATTR_U_PI,
    ATTR_U_I,
    ATTR_U_FF,
    ATTR_U_TOTAL,
    ATTR_FLOW_FILTERED,
    ATTR_OUTDOOR_FILTERED,
    ATTR_IMC_KC,
    ATTR_IMC_KI,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_NAME,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DOMAIN,
    VALVE_OPEN_POSITION,
)


def _resolve_climate_entity_id(hass: HomeAssistant, entry: ConfigEntry) -> Optional[str]:
    registry = er.async_get(hass)
    climate_unique_id = f"{DOMAIN}_{entry.entry_id}"
    return registry.async_get_entity_id("climate", DOMAIN, climate_unique_id)


class _BaseSmartSensor(SensorEntity):
    """Base class that follows a companion climate entity and derives a value."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._name = entry.data.get(CONF_NAME, "Smart TRV")
        self._climate_entity_id: Optional[str] = None
        self._unsub = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=self._name,
        )
        self._native_value: Any = None

    @property
    def native_value(self) -> Any:
        return self._native_value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._climate_entity_id = _resolve_climate_entity_id(self.hass, self._entry)
        if self._climate_entity_id:
            self._unsub = async_track_state_change_event(
                self.hass, [self._climate_entity_id], self._handle_climate_state_change
            )
        await self._update_from_climate_state()

    async def async_will_remove_from_hass(self) -> None:
        if callable(self._unsub):
            try:
                self._unsub()
            except Exception:  # pragma: no cover - defensive
                pass
        self._unsub = None

    @callback
    def _handle_climate_state_change(self, _event) -> None:
        self.hass.async_create_task(self._update_from_climate_state())

    async def _update_from_climate_state(self) -> None:
        """Implemented by subclasses to compute native value from climate state."""
        raise NotImplementedError


class SmartTRVSetpointSensor(_BaseSmartSensor):
    """Effective setpoint derived from valve position mapping (0–255)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._min_temp: float = entry.data.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)
        self._max_temp: float = entry.data.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_setpoint"
        self._attr_name = f"{self._name} Setpoint"

        # Keep some recent climate values for attributes used by tests
        self._actual_setpoint: float | None = None
        self._room_temperature: float | None = None
        self._latest_valve_position: int | None = None

    async def _update_from_climate_state(self) -> None:  # type: ignore[override]
        st = self.hass.states.get(self._climate_entity_id) if self._climate_entity_id else None
        valve_pos: int | None = None
        actual_target: float | None = None
        room_temp: float | None = None
        if st is not None:
            vp = st.attributes.get(ATTR_VALVE_POSITION)
            if isinstance(vp, (int, float)):
                valve_pos = int(vp)
            tp = st.attributes.get(ATTR_TEMPERATURE)
            if isinstance(tp, (int, float)):
                actual_target = float(tp)
            rt = st.attributes.get(ATTR_ROOM_TEMPERATURE)
            if isinstance(rt, (int, float)):
                room_temp = float(rt)

        if valve_pos is None:
            self._native_value = None
        else:
            span = max(0.0, self._max_temp - self._min_temp)
            self._native_value = self._min_temp + (valve_pos / float(VALVE_OPEN_POSITION)) * span

        self._actual_setpoint = actual_target
        self._room_temperature = room_temp
        self._latest_valve_position = valve_pos
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._actual_setpoint is not None:
            attrs["target_temperature"] = self._actual_setpoint
        if self._actual_setpoint is not None and self._room_temperature is not None:
            attrs["error"] = float(self._actual_setpoint - self._room_temperature)
        if self._latest_valve_position is not None:
            attrs["target_valve_position"] = int(self._latest_valve_position)
        return attrs


class SmartTRVTargetTemperatureSensor(_BaseSmartSensor):
    """Mirrors the climate target temperature as a primary sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_target_temperature"
        self._attr_name = f"{self._name} Target Temperature"

    async def _update_from_climate_state(self) -> None:  # type: ignore[override]
        st = self.hass.states.get(self._climate_entity_id) if self._climate_entity_id else None
        val: float | None = None
        if st is not None:
            tp = st.attributes.get(ATTR_TEMPERATURE)
            if isinstance(tp, (int, float)):
                val = float(tp)
        self._native_value = val
        self.async_write_ha_state()


class SmartTRVTemperatureErrorSensor(_BaseSmartSensor):
    """Temperature error (target - room) in °C."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_temperature_error"
        self._attr_name = f"{self._name} Temperature Error"

    async def _update_from_climate_state(self) -> None:  # type: ignore[override]
        st = self.hass.states.get(self._climate_entity_id) if self._climate_entity_id else None
        val: float | None = None
        if st is not None:
            tp = st.attributes.get(ATTR_TEMPERATURE)
            rt = st.attributes.get(ATTR_ROOM_TEMPERATURE)
            if isinstance(tp, (int, float)) and isinstance(rt, (int, float)):
                val = float(tp) - float(rt)
        self._native_value = val
        self.async_write_ha_state()


class SmartTRVValvePositionSensor(_BaseSmartSensor):
    """Current calculated valve position (0–255)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_valve_position"
        self._attr_name = f"{self._name} Valve Position"

    async def _update_from_climate_state(self) -> None:  # type: ignore[override]
        st = self.hass.states.get(self._climate_entity_id) if self._climate_entity_id else None
        val: int | None = None
        if st is not None:
            vp = st.attributes.get(ATTR_VALVE_POSITION)
            if isinstance(vp, (int, float)):
                val = int(vp)
        self._native_value = val
        self.async_write_ha_state()


class SmartTRVActualValvePositionSensor(_BaseSmartSensor):
    """Actual valve position read from underlying TRVs (max across TRVs)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_actual_valve_position"
        self._attr_name = f"{self._name} Actual Valve Position"

    async def _update_from_climate_state(self) -> None:  # type: ignore[override]
        st = self.hass.states.get(self._climate_entity_id) if self._climate_entity_id else None
        val: int | None = None
        if st is not None:
            vp = st.attributes.get(ATTR_ACTUAL_VALVE_POSITION)
            if isinstance(vp, (int, float)):
                val = int(vp)
        self._native_value = val
        self.async_write_ha_state()


class _AttrMirrorSensor(_BaseSmartSensor):
    """Base for simple 1:1 attribute mirror sensors."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, attr_key: str, name_suffix: str, unique_suffix: str) -> None:
        super().__init__(hass, entry)
        self._attr_key = attr_key
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unique_suffix}"
        self._attr_name = f"{self._name} {name_suffix}"

    async def _update_from_climate_state(self) -> None:  # type: ignore[override]
        st = self.hass.states.get(self._climate_entity_id) if self._climate_entity_id else None
        val = None
        if st is not None:
            raw = st.attributes.get(self._attr_key)
            if isinstance(raw, (int, float)):
                val = float(raw)
        self._native_value = val
        self.async_write_ha_state()


class SmartTRVDesiredValveSensor(_AttrMirrorSensor):
    """Desired valve position requested by controller (0–255)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_DESIRED_VALVE_POSITION, "Desired Valve", "desired_valve_position")


class SmartTRVUtotalSensor(_AttrMirrorSensor):
    """Total controller output u in [0,1]."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_U_TOTAL, "Controller u Total", "u_total")


class SmartTRVUpiSensor(_AttrMirrorSensor):
    """PI controller output (before FF) in [0,1]."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_U_PI, "Controller u PI", "u_pi")


class SmartTRVUiSensor(_AttrMirrorSensor):
    """Integral-only contribution to PI output in [0,1]."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_U_I, "Controller u I", "u_i")


class SmartTRVUffSensor(_AttrMirrorSensor):
    """Feed-forward term (after smoothing/deadband)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_U_FF, "FF", "u_ff")


class SmartTRVFilteredFlowTempSensor(_AttrMirrorSensor):
    """Filtered boiler flow temperature (°C)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_FLOW_FILTERED, "Flow Temp (filtered)", "flow_filtered")


class SmartTRVFilteredOutdoorTempSensor(_AttrMirrorSensor):
    """Filtered outdoor temperature (°C)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_OUTDOOR_FILTERED, "Outdoor Temp (filtered)", "outdoor_filtered")


class SmartTRVErrorCSensor(_AttrMirrorSensor):
    """Controller temperature error (°C)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_ERROR_C, "Error (°C)", "error_c")


class SmartTRVErrorNormSensor(_AttrMirrorSensor):
    """Normalized temperature error [0,1]."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_ERROR_NORM, "Error (norm)", "error_norm")


class SmartTRVImcKcSensor(_AttrMirrorSensor):
    """IMC proportional gain (unitless)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_IMC_KC, "IMC Kc", "imc_kc")


class SmartTRVImcKiSensor(_AttrMirrorSensor):
    """IMC integral gain (per second)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, ATTR_IMC_KI, "IMC Ki", "imc_ki")


class SmartTRVWindowOpenSensor(_BaseSmartSensor):
    """Mirror of window_open diagnostic (boolean)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_window_open"
        self._attr_name = f"{self._name} Window Open"

    async def _update_from_climate_state(self) -> None:  # type: ignore[override]
        st = self.hass.states.get(self._climate_entity_id) if self._climate_entity_id else None
        val: bool | None = None
        if st is not None:
            raw = st.attributes.get("window_open")
            if isinstance(raw, bool):
                val = raw
            elif isinstance(raw, (int, float)):
                # interpret nonzero as True
                val = bool(raw)
        self._native_value = val
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Smart TRV sensors from a config entry."""
    entities: list[SensorEntity] = [
        SmartTRVSetpointSensor(hass, entry),
        SmartTRVTargetTemperatureSensor(hass, entry),
        SmartTRVTemperatureErrorSensor(hass, entry),
        SmartTRVValvePositionSensor(hass, entry),
        SmartTRVActualValvePositionSensor(hass, entry),
        # Diagnostics
        SmartTRVDesiredValveSensor(hass, entry),
        SmartTRVUpiSensor(hass, entry),
        SmartTRVUiSensor(hass, entry),
        SmartTRVUffSensor(hass, entry),
        SmartTRVUtotalSensor(hass, entry),
        SmartTRVFilteredFlowTempSensor(hass, entry),
        SmartTRVFilteredOutdoorTempSensor(hass, entry),
        SmartTRVErrorCSensor(hass, entry),
        SmartTRVErrorNormSensor(hass, entry),
        SmartTRVImcKcSensor(hass, entry),
        SmartTRVImcKiSensor(hass, entry),
        SmartTRVWindowOpenSensor(hass, entry),
    ]
    async_add_entities(entities, True)
