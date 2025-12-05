"""Config flow for Smart TRV Controller integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_IMC_DEAD_TIME,
    CONF_IMC_LAMBDA,
    CONF_IMC_PROCESS_GAIN,
    CONF_IMC_TIME_CONSTANT,
    # Optional FF sensors (UI-only fields to pick sensors)
    CONF_OUTDOOR_TEMPERATURE_SENSOR,
    CONF_BOILER_FLOW_TEMPERATURE_SENSOR,
    DEFAULT_IMC_DEAD_TIME,
    DEFAULT_IMC_LAMBDA,
    DEFAULT_IMC_PROCESS_GAIN,
    DEFAULT_IMC_TIME_CONSTANT,
    CONF_TARGET_TEMP,
    CONF_TEMPERATURE_SENSOR,
    CONF_TRV_ENTITIES,
    DEFAULT_NAME,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
)


def get_config_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Return the config schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME,
                default=defaults.get(CONF_NAME, DEFAULT_NAME),
            ): selector.TextSelector(),
            vol.Required(
                CONF_TEMPERATURE_SENSOR,
                default=defaults.get(CONF_TEMPERATURE_SENSOR),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Required(
                CONF_TRV_ENTITIES,
                default=defaults.get(CONF_TRV_ENTITIES, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True)
            ),
            vol.Optional(
                CONF_TARGET_TEMP,
                default=defaults.get(CONF_TARGET_TEMP, DEFAULT_TARGET_TEMP),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5, max=35, step=0.5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            # Optional: outdoor temperature sensor used by feed-forward internally
            vol.Optional(
                CONF_OUTDOOR_TEMPERATURE_SENSOR,
                default=defaults.get(CONF_OUTDOOR_TEMPERATURE_SENSOR),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="temperature"
                )
            ),
            # Optional: boiler flow temperature sensor used by feed-forward internally
            vol.Optional(
                CONF_BOILER_FLOW_TEMPERATURE_SENSOR,
                default=defaults.get(CONF_BOILER_FLOW_TEMPERATURE_SENSOR),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="temperature"
                )
            ),
            # IMC/Lambda tuning parameters
            vol.Optional(
                CONF_IMC_PROCESS_GAIN,
                default=defaults.get(CONF_IMC_PROCESS_GAIN, DEFAULT_IMC_PROCESS_GAIN),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.01, max=50.0, step=0.01, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_IMC_DEAD_TIME,
                default=defaults.get(CONF_IMC_DEAD_TIME, DEFAULT_IMC_DEAD_TIME),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=36000, step=60, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_IMC_TIME_CONSTANT,
                default=defaults.get(CONF_IMC_TIME_CONSTANT, DEFAULT_IMC_TIME_CONSTANT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=300, max=172800, step=300, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_IMC_LAMBDA,
                default=defaults.get(CONF_IMC_LAMBDA, DEFAULT_IMC_LAMBDA),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=300, max=172800, step=300, mode=selector.NumberSelectorMode.BOX
                )
            ),
        }
    )


class SmartTRVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart TRV Controller."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate inputs
            if not user_input.get(CONF_TEMPERATURE_SENSOR):
                errors[CONF_TEMPERATURE_SENSOR] = "no_temperature_sensor"
            elif not user_input.get(CONF_TRV_ENTITIES):
                errors[CONF_TRV_ENTITIES] = "no_trv_entities"
            else:
                # Create unique ID based on the temperature sensor
                await self.async_set_unique_id(user_input[CONF_TEMPERATURE_SENSOR])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=get_config_schema(user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return SmartTRVOptionsFlow(config_entry)


class SmartTRVOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Handle options flow for Smart TRV Controller."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # Use HA-provided base to store the config entry (avoids deprecated attribute set)
        super().__init__(config_entry)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Merge with existing data
            new_data = {**self.config_entry.data, **user_input}
            
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=get_config_schema(dict(self.config_entry.data)),
            errors=errors,
        )
