"""Form schema helpers for the DHE config and options flows."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .config_flow_mapping import (
    default_radio_catalog_value as _default_radio_catalog_value,
    default_weather_country_id as _default_weather_country_id,
)
from .const import DEFAULT_NAME, DEFAULT_PORT
from .entity_state_helpers import (
    CONF_INTERNAL_SCALD_PROTECTION,
    INTERNAL_SCALD_PROTECTION_DEFAULT,
    normalize_internal_scald_protection,
)
from .protocol import (
    ID_CO2_EMISSION,
    ID_ELECTRICITY_PRICE,
    ID_WATER_PRICE,
)
from .service_helpers import WEATHER_RESULT_NUMBER_MAX

from .error_codes import INVALID_RANGE

ATTR_COUNTRY_ID = "country_id"
ATTR_RADIO_SELECTION = "selection"
ATTR_RADIO_SEARCH_TYPE = "search_type"
ATTR_RADIO_FILTER_TEXT = "filter_text"
ATTR_RESULT = "result"
ATTR_CO2_EMISSION = "co2_emission"
ATTR_ELECTRICITY_PRICE = "electricity_price"
ATTR_WATER_PRICE = "water_price"
DEFAULT_RADIO_GENRE = "Dekaden/Dekade 1980s"
DEFAULT_WEATHER_COUNTRY_ID = 34
MAX_RADIO_RESULT_OPTIONS = 50
MAX_WEATHER_RESULT_OPTIONS = WEATHER_RESULT_NUMBER_MAX
RADIO_CATALOG_SEARCH_TYPES = ("genre", "country", "city")
RADIO_FILTER_SEARCH_TYPES = ("country", "city")
RADIO_SEARCH_TYPES = ("text", *RADIO_CATALOG_SEARCH_TYPES)
DEFAULT_RADIO_CATALOG_VALUES = {
    "genre": DEFAULT_RADIO_GENRE,
    "country": "Deutschland",
    "city": "Düsseldorf/Nordrhein-Westfalen",
}
DEFAULT_RADIO_SEARCH_TEXTS = {
    "text": "1Live",
    "country": "*",
    "city": "*",
}


def schema(
    hass: HomeAssistant,
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build config/options schema."""
    defaults = defaults or {}
    internal_scald_protection = normalize_internal_scald_protection(
        defaults.get(
            CONF_INTERNAL_SCALD_PROTECTION,
            INTERNAL_SCALD_PROTECTION_DEFAULT,
        )
    )
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Optional(
                CONF_INTERNAL_SCALD_PROTECTION,
                default=internal_scald_protection,
            ): vol.In(internal_scald_protection_options(hass)),
        }
    )


def string_default(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def optional_float(value: Any, min_value: float, max_value: float) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    parsed = float(text)
    if parsed < min_value or parsed > max_value:
        raise ValueError(INVALID_RANGE)
    return parsed


def format_number_default(value: Any, *, precision: int = 2) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.{precision}f}".rstrip("0").rstrip(".")


def internal_scald_protection_options(hass: HomeAssistant) -> dict[str, str]:
    """Build jumper position labels for the options flow."""
    language = str(getattr(hass.config, "language", "") or "").lower()
    if language.startswith("de"):
        return {
            "43": "43 \u00b0C",
            "50": "50 \u00b0C",
            "55": "55 \u00b0C",
            "60": "60 \u00b0C",
            "no_jumper": "ohne Jumper (43 \u00b0C)",
        }
    return {
        "43": "43 \u00b0C",
        "50": "50 \u00b0C",
        "55": "55 \u00b0C",
        "60": "60 \u00b0C",
        "no_jumper": "No jumper (43 \u00b0C)",
    }


def device_settings_defaults(client: Any) -> dict[str, Any]:
    measurements = getattr(client, "last_measurements", {})
    return {
        ATTR_ELECTRICITY_PRICE: format_number_default(
            measurements.get(ID_ELECTRICITY_PRICE)
        ),
        ATTR_WATER_PRICE: format_number_default(measurements.get(ID_WATER_PRICE)),
        ATTR_CO2_EMISSION: format_number_default(
            measurements.get(ID_CO2_EMISSION),
            precision=3,
        ),
    }


def device_settings_schema(
    _hass: HomeAssistant,
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(
                ATTR_ELECTRICITY_PRICE,
                default=string_default(defaults.get(ATTR_ELECTRICITY_PRICE, "")),
            ): str,
            vol.Optional(
                ATTR_WATER_PRICE,
                default=string_default(defaults.get(ATTR_WATER_PRICE, "")),
            ): str,
            vol.Optional(
                ATTR_CO2_EMISSION,
                default=string_default(defaults.get(ATTR_CO2_EMISSION, "")),
            ): str,
        }
    )


def weather_search_schema(
    country_options: dict[str, str],
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the weather favorite search form."""
    defaults = defaults or {}
    default_country = str(
        defaults.get(ATTR_COUNTRY_ID)
        or _default_weather_country_id(country_options, DEFAULT_WEATHER_COUNTRY_ID)
    )
    if country_options and default_country not in country_options:
        default_country = _default_weather_country_id(
            country_options,
            DEFAULT_WEATHER_COUNTRY_ID,
        )

    country_validator: Any = vol.In(country_options) if country_options else str

    return vol.Schema(
        {
            vol.Required(ATTR_COUNTRY_ID, default=default_country): country_validator,
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
        }
    )


def radio_search_type_options(hass: HomeAssistant) -> dict[str, str]:
    """Build radio search type options."""
    language = str(getattr(hass.config, "language", "") or "").lower()
    if language.startswith("de"):
        return {
            "text": "Volltext",
            "genre": "Musikrichtung",
            "country": "Land",
            "city": "Stadt",
        }
    return {
        "text": "Text",
        "genre": "Genre",
        "country": "Country",
        "city": "City",
    }


def radio_search_type_schema(
    hass: HomeAssistant,
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the radio station search type form."""
    defaults = defaults or {}
    search_type_options = radio_search_type_options(hass)
    default_search_type = str(defaults.get(ATTR_RADIO_SEARCH_TYPE) or "text")
    if default_search_type not in search_type_options:
        default_search_type = "text"

    return vol.Schema(
        {
            vol.Required(
                ATTR_RADIO_SEARCH_TYPE,
                default=default_search_type,
            ): vol.In(search_type_options),
        }
    )


def radio_catalog_schema(
    search_type: str,
    catalog_options: dict[str, str],
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the radio station catalog value form."""
    defaults = defaults or {}
    schema_data: dict[Any, Any] = {}
    default_value = str(
        defaults.get(ATTR_RADIO_SELECTION)
        or _default_radio_catalog_value(
            search_type,
            catalog_options,
            DEFAULT_RADIO_CATALOG_VALUES,
        )
    )
    if (
        search_type in RADIO_CATALOG_SEARCH_TYPES
        and catalog_options
        and default_value not in catalog_options
    ):
        default_value = _default_radio_catalog_value(
            search_type,
            catalog_options,
            DEFAULT_RADIO_CATALOG_VALUES,
        )

    value_validator: Any
    if search_type in RADIO_CATALOG_SEARCH_TYPES and catalog_options:
        value_validator = vol.In(catalog_options)
    else:
        value_validator = str

    if search_type in RADIO_CATALOG_SEARCH_TYPES:
        schema_data[
            vol.Required(
                ATTR_RADIO_SELECTION,
                default=default_value,
            )
        ] = value_validator

    if search_type == "text" or search_type in RADIO_FILTER_SEARCH_TYPES:
        schema_data[
            vol.Required(
                ATTR_RADIO_FILTER_TEXT,
                default=str(
                    defaults.get(ATTR_RADIO_FILTER_TEXT)
                    or DEFAULT_RADIO_SEARCH_TEXTS.get(search_type, "")
                ),
            )
        ] = str

    return vol.Schema(schema_data)
