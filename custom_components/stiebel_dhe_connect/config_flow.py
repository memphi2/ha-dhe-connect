"""Config flow for Stiebel DHE Connect."""

from __future__ import annotations

import asyncio
import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import (
    CO2_EMISSION_MAX,
    DHEClient,
    DHEError,
    ELECTRICITY_PRICE_MAX,
    ID_CO2_EMISSION,
    ID_ELECTRICITY_PRICE,
    ID_WATER_PRICE,
    WATER_PRICE_MAX,
)
from .config_flow_mapping import (
    default_radio_catalog_value as _default_radio_catalog_value,
    default_weather_country_id as _default_weather_country_id,
    filter_radio_results_by_text as _filter_radio_results_by_text,
    radio_catalog_options as _radio_catalog_options,
    radio_result_options as _radio_result_options,
    weather_country_options as _weather_country_options,
    weather_result_options as _weather_result_options,
)
from .config_entry_helpers import merged_entry_data
from .const import (
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
)
from .entity_state_helpers import (
    CONF_INTERNAL_SCALD_PROTECTION,
    INTERNAL_SCALD_PROTECTION_DEFAULT,
    INTERNAL_SCALD_PROTECTION_OPTIONS,
    normalize_internal_scald_protection,
)
from .pairing_helpers import map_pairing_error
from .token_file_helpers import token_file_for_target

ATTR_COUNTRY_ID = "country_id"
ATTR_RADIO_SELECTION = "selection"
ATTR_RADIO_SEARCH_TYPE = "search_type"
ATTR_RADIO_FILTER_TEXT = "filter_text"
ATTR_RESULT = "result"
ATTR_CO2_EMISSION = "co2_emission"
ATTR_CURRENCY = "currency"
ATTR_ELECTRICITY_PRICE = "electricity_price"
ATTR_WATER_PRICE = "water_price"
CURRENCY_UNCHANGED = "__unchanged__"
CURRENCY_OPTIONS = ("EUR", "GBP", "CZK", "PLN", "CNY", "USD", "AUD", "HKD")
DEFAULT_RADIO_GENRE = "Dekaden/Dekade 1980s"
DEFAULT_WEATHER_COUNTRY_ID = 34
SETUP_PAIRING_TIMEOUT_SECONDS = 180.0
MAX_RADIO_RESULT_OPTIONS = 50
MAX_WEATHER_RESULT_OPTIONS = 50
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

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def _normalize_host(host: str) -> str:
    """Normalize and validate the host value from UI input."""
    value = host.strip()
    if not value:
        raise ValueError("empty_host")

    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("invalid_scheme")
        if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("invalid_host")
        value = parsed.hostname or ""

    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip()
    value = value.rstrip(".")

    if not value or any(char in value for char in "/?#@\\"):
        raise ValueError("invalid_host")

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass

    # The port has a dedicated config field. Reject host:port to keep URL
    # construction deterministic and avoid ambiguity.
    if ":" in value:
        raise ValueError("embedded_port_not_supported")

    if not _HOST_RE.fullmatch(value):
        raise ValueError("invalid_host")

    return value.lower()


def _host_for_url(host: str) -> str:
    """Return host part suitable for URL construction (wrap IPv6 in brackets)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        return f"[{host}]"
    return host


def _validate_port(port: int) -> int:
    """Validate TCP port from UI input."""
    port = int(port)
    if port < 1 or port > 65535:
        raise ValueError("invalid_port")
    return port


def _apply_validation_error(errors: dict[str, str], err: ValueError) -> None:
    """Map validation exceptions to form fields."""
    code = str(err) or "invalid_host"
    if code == "invalid_port":
        errors[CONF_PORT] = code
    elif code == "embedded_port_not_supported":
        errors[CONF_HOST] = code
    else:
        errors[CONF_HOST] = "invalid_host"


def _target_unique_id(host: str, port: int) -> str:
    """Return stable unique_id for one DHE target."""
    return f"{DOMAIN}:{host}:{port}"


def _entry_target(entry: config_entries.ConfigEntry) -> tuple[str, int] | None:
    """Return normalized host/port from an existing config entry."""
    merged = merged_entry_data(entry)
    host_value = merged.get(CONF_HOST)
    if host_value is None:
        return None
    try:
        host = _normalize_host(str(host_value))
        port = _validate_port(int(merged.get(CONF_PORT, DEFAULT_PORT)))
    except (TypeError, ValueError):
        return None
    return host, port


def _is_target_used_by_other_entry(
    hass: HomeAssistant,
    host: str,
    port: int,
    *,
    exclude_entry_id: str | None = None,
) -> bool:
    """Return True when another config entry already uses host/port."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if exclude_entry_id is not None and entry.entry_id == exclude_entry_id:
            continue
        target = _entry_target(entry)
        if target == (host, port):
            return True
    return False


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build config/options schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
        }
    )


def _string_default(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def _optional_float(value: Any, min_value: float, max_value: float) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    parsed = float(text)
    if parsed < min_value or parsed > max_value:
        raise ValueError("invalid_range")
    return parsed


def _currency_options(hass: HomeAssistant, current: str = "") -> dict[str, str]:
    language = str(getattr(hass.config, "language", "") or "").lower()
    options = {
        CURRENCY_UNCHANGED: (
            "Nicht ändern" if language.startswith("de") else "Do not change"
        )
    }
    options.update({currency: currency for currency in CURRENCY_OPTIONS})
    current_value = str(current or "").strip()
    if current_value and current_value != CURRENCY_UNCHANGED:
        current_value = current_value.upper()
    if current_value and current_value not in options:
        options[current_value] = current_value
    return options


def _format_number_default(value: Any, *, precision: int = 2) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.{precision}f}".rstrip("0").rstrip(".")


def _internal_scald_protection_options(hass: HomeAssistant) -> dict[str, str]:
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


def _device_settings_defaults(
    client: Any,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    measurements = getattr(client, "last_measurements", {})
    options = options or {}
    return {
        CONF_INTERNAL_SCALD_PROTECTION: normalize_internal_scald_protection(
            options.get(CONF_INTERNAL_SCALD_PROTECTION)
        ),
        # Requested UX: keep currency default at EUR.
        ATTR_CURRENCY: "EUR",
        ATTR_ELECTRICITY_PRICE: _format_number_default(
            measurements.get(ID_ELECTRICITY_PRICE)
        ),
        ATTR_WATER_PRICE: _format_number_default(measurements.get(ID_WATER_PRICE)),
        ATTR_CO2_EMISSION: _format_number_default(
            measurements.get(ID_CO2_EMISSION),
            precision=3,
        ),
    }


def _device_settings_schema(
    hass: HomeAssistant,
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    defaults = defaults or {}
    internal_scald_protection = normalize_internal_scald_protection(
        defaults.get(
            CONF_INTERNAL_SCALD_PROTECTION,
            INTERNAL_SCALD_PROTECTION_DEFAULT,
        )
    )
    currency = str(defaults.get(ATTR_CURRENCY) or CURRENCY_UNCHANGED).strip()
    if currency != CURRENCY_UNCHANGED:
        currency = currency.upper()
    return vol.Schema(
        {
            vol.Optional(
                CONF_INTERNAL_SCALD_PROTECTION,
                default=internal_scald_protection,
            ): vol.In(_internal_scald_protection_options(hass)),
            vol.Optional(ATTR_CURRENCY, default=currency): vol.In(
                _currency_options(hass, currency)
            ),
            vol.Optional(
                ATTR_ELECTRICITY_PRICE,
                default=_string_default(defaults.get(ATTR_ELECTRICITY_PRICE, "")),
            ): str,
            vol.Optional(
                ATTR_WATER_PRICE,
                default=_string_default(defaults.get(ATTR_WATER_PRICE, "")),
            ): str,
            vol.Optional(
                ATTR_CO2_EMISSION,
                default=_string_default(defaults.get(ATTR_CO2_EMISSION, "")),
            ): str,
        }
    )


def _weather_search_schema(
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

    country_validator: Any
    if country_options:
        country_validator = vol.In(country_options)
    else:
        country_validator = str

    return vol.Schema(
        {
            vol.Required(ATTR_COUNTRY_ID, default=default_country): country_validator,
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
        }
    )


def _radio_search_type_options(hass: HomeAssistant) -> dict[str, str]:
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


def _radio_search_type_schema(
    hass: HomeAssistant,
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the radio station search type form."""
    defaults = defaults or {}
    search_type_options = _radio_search_type_options(hass)
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


def _radio_catalog_schema(
    search_type: str,
    catalog_options: dict[str, str],
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the radio station catalog value form."""
    defaults = defaults or {}
    schema: dict[Any, Any] = {}
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
        schema[
            vol.Required(
                ATTR_RADIO_SELECTION,
                default=default_value,
            )
        ] = value_validator

    if search_type == "text" or search_type in RADIO_FILTER_SEARCH_TYPES:
        schema[
            vol.Required(
                ATTR_RADIO_FILTER_TEXT,
                default=str(
                    defaults.get(ATTR_RADIO_FILTER_TEXT)
                    or DEFAULT_RADIO_SEARCH_TEXTS.get(search_type, "")
                ),
            )
        ] = str

    return vol.Schema(schema)


async def _can_connect(hass: HomeAssistant, host: str, port: int) -> bool:
    """Check if the DHE web endpoint is reachable before creating the config entry."""
    session = async_get_clientsession(hass)
    url = f"http://{_host_for_url(host)}:{port}/"

    try:
        async with session.get(url, timeout=8) as resp:
            await resp.read()
            return 200 <= resp.status < 500
    except Exception:  # noqa: BLE001
        return False


async def _validate_setup_pairing(
    hass: HomeAssistant,
    host: str,
    port: int,
    token_file: str,
) -> str | None:
    """Run one-shot pairing/auth validation before creating the config entry."""
    probe_client = DHEClient(
        hass=hass,
        host=host,
        port=port,
        token_file=token_file,
        name="Home Assistant",
    )
    try:
        await probe_client.validate_setup_authentication(
            timeout_seconds=SETUP_PAIRING_TIMEOUT_SECONDS
        )
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001
        pairing_state = str(probe_client.diagnostic_state.get("pairing_state") or "")
        return map_pairing_error(err, pairing_state)
    return None


class StiebelDHEConnectConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Stiebel DHE Connect."""

    VERSION = 1
    _pending_setup_data: dict[str, Any] | None

    def __init__(self) -> None:
        self._pending_setup_data = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                host = _normalize_host(user_input[CONF_HOST])
                port = _validate_port(user_input.get(CONF_PORT, DEFAULT_PORT))
            except ValueError as err:
                _apply_validation_error(errors, err)
            else:
                if _is_target_used_by_other_entry(self.hass, host, port):
                    return self.async_abort(reason="already_configured")
                await self.async_set_unique_id(_target_unique_id(host, port))
                self._abort_if_unique_id_configured()
                name = str(user_input.get(CONF_NAME, DEFAULT_NAME)).strip() or DEFAULT_NAME

                if not await _can_connect(self.hass, host, port):
                    errors["base"] = "cannot_connect"
                else:
                    token_file = token_file_for_target(host, port)
                    self._pending_setup_data = {
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: name,
                        "token_file": token_file,
                    }
                    return await self.async_step_pairing_confirm()

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(),
            errors=errors,
        )

    async def async_step_pairing_confirm(
        self, user_input: dict[str, Any] | None = None
    ):
        """Validate pairing/authentication before creating the entry."""
        if self._pending_setup_data is None:
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            setup_data = dict(self._pending_setup_data)
            error_key = await _validate_setup_pairing(
                self.hass,
                setup_data[CONF_HOST],
                setup_data[CONF_PORT],
                setup_data["token_file"],
            )
            if error_key is None:
                self._pending_setup_data = None
                setup_data.pop("token_file", None)
                return self.async_create_entry(
                    title=setup_data[CONF_NAME],
                    data=setup_data,
                )
            errors["base"] = error_key

        return self.async_show_form(
            step_id="pairing_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: config_entries.ConfigEntry):
        """Return the options flow handler."""
        return StiebelDHEConnectOptionsFlow()


class StiebelDHEConnectOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Stiebel DHE Connect."""

    def __init__(self) -> None:
        self._radio_catalogs: dict[str, list[str]] = {}
        self._radio_favorites: list[dict[str, Any]] = []
        self._radio_results: list[dict[str, Any]] = []
        self._radio_search_type = "text"
        self._weather_countries: list[dict[str, Any]] = []
        self._weather_favorites: list[dict[str, Any]] = []
        self._weather_results: list[dict[str, Any]] = []
        self._menu_options = [
            "connection",
            "device_settings",
            "weather_favorite",
            "remove_weather_favorite",
            "radio_favorite",
            "remove_radio_favorite",
        ]

    def _finish_options(self) -> config_entries.ConfigFlowResult:
        """Return success result without changing options payload."""
        return self.async_create_entry(
            title="",
            data=dict(self.config_entry.options),
        )

    def _client_or_mark_not_loaded(self, errors: dict[str, str]) -> Any | None:
        """Return runtime client or mark the step as not loaded."""
        client = self._client()
        if client is None:
            errors["base"] = "not_loaded"
        return client

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=self._menu_options,
        )

    async def async_step_connection(self, user_input: dict[str, Any] | None = None):
        """Manage connection options."""
        current = merged_entry_data(self.config_entry)
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                host = _normalize_host(user_input[CONF_HOST])
                port = _validate_port(user_input.get(CONF_PORT, DEFAULT_PORT))
            except ValueError as err:
                _apply_validation_error(errors, err)
            else:
                name = str(user_input.get(CONF_NAME, DEFAULT_NAME)).strip() or DEFAULT_NAME

                if _is_target_used_by_other_entry(
                    self.hass,
                    host,
                    port,
                    exclude_entry_id=self.config_entry.entry_id,
                ):
                    errors["base"] = "already_configured"
                elif not await _can_connect(self.hass, host, port):
                    errors["base"] = "cannot_connect"
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        unique_id=_target_unique_id(host, port),
                    )
                    return self.async_create_entry(
                        title="",
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_NAME: name,
                        },
                    )

        return self.async_show_form(
            step_id="connection",
            data_schema=_schema(current),
            errors=errors,
        )

    async def async_step_device_settings(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Manage DHE cost and emission settings."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)

        defaults = (
            _device_settings_defaults(client, dict(self.config_entry.options))
            if client is not None
            else dict(self.config_entry.options)
        )
        if user_input is not None and not errors:
            try:
                internal_scald_protection = str(
                    user_input.get(CONF_INTERNAL_SCALD_PROTECTION) or ""
                ).strip()
                if internal_scald_protection not in INTERNAL_SCALD_PROTECTION_OPTIONS:
                    raise ValueError("invalid_internal_scald_protection")
                currency = str(
                    user_input.get(ATTR_CURRENCY) or CURRENCY_UNCHANGED
                ).strip()
                electricity_price = _optional_float(
                    user_input.get(ATTR_ELECTRICITY_PRICE),
                    0.0,
                    ELECTRICITY_PRICE_MAX,
                )
                water_price = _optional_float(
                    user_input.get(ATTR_WATER_PRICE),
                    0.0,
                    WATER_PRICE_MAX,
                )
                co2_emission = _optional_float(
                    user_input.get(ATTR_CO2_EMISSION),
                    0.0,
                    CO2_EMISSION_MAX,
                )

                if currency and currency != CURRENCY_UNCHANGED:
                    await client.set_currency(currency)
                if electricity_price is not None:
                    await client.set_electricity_price(electricity_price)
                if water_price is not None:
                    await client.set_water_price(water_price)
                if co2_emission is not None:
                    await client.set_co2_emission(co2_emission)
            except (TypeError, ValueError):
                errors["base"] = "invalid_device_setting"
            except DHEError:
                errors["base"] = "device_settings_failed"
            else:
                updated_options = dict(self.config_entry.options)
                updated_options[CONF_INTERNAL_SCALD_PROTECTION] = (
                    internal_scald_protection
                )
                return self.async_create_entry(title="", data=updated_options)

        return self.async_show_form(
            step_id="device_settings",
            data_schema=_device_settings_schema(self.hass, user_input or defaults),
            errors=errors,
        )

    async def async_step_weather_favorite(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Search DHE weather locations to add a favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        if client is not None and not self._weather_countries:
            try:
                self._weather_countries = await client.list_weather_countries()
            except DHEError:
                errors["base"] = "cannot_connect"

        country_options = _weather_country_options(self._weather_countries)
        defaults = user_input or {}

        if user_input is not None and not errors:
            search_name = str(user_input.get(CONF_NAME, "")).strip()
            if not search_name:
                errors[CONF_NAME] = "required"
            else:
                try:
                    country_id = int(user_input[ATTR_COUNTRY_ID])
                    self._weather_results = await client.search_weather_locations(
                        search_name,
                        country_id,
                    )
                except (TypeError, ValueError):
                    errors[ATTR_COUNTRY_ID] = "invalid_country"
                except DHEError:
                    errors["base"] = "search_failed"
                else:
                    if not self._weather_results:
                        errors["base"] = "no_results"
                    else:
                        return await self.async_step_weather_favorite_result()

        if not country_options and not errors:
            errors["base"] = "no_countries"

        return self.async_show_form(
            step_id="weather_favorite",
            data_schema=_weather_search_schema(country_options, defaults),
            errors=errors,
        )

    async def async_step_weather_favorite_result(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Select one weather search result and save it as favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        result_options = _weather_result_options(
            self._weather_results,
            max_options=MAX_WEATHER_RESULT_OPTIONS,
        )

        if not result_options and "base" not in errors:
            errors["base"] = "no_results"

        if user_input is not None and not errors:
            try:
                selected = int(user_input[ATTR_RESULT])
                location = self._weather_results[selected]
                await client.add_weather_favorite(location)
            except (IndexError, TypeError, ValueError):
                errors[ATTR_RESULT] = "invalid_result"
            except DHEError:
                errors["base"] = "favorite_failed"
            else:
                return self._finish_options()

        return self.async_show_form(
            step_id="weather_favorite_result",
            data_schema=vol.Schema({vol.Required(ATTR_RESULT): vol.In(result_options)}),
            errors=errors,
        )

    async def async_step_remove_weather_favorite(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Remove a DHE weather favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        if client is not None:
            try:
                self._weather_favorites = await client.list_weather_favorites()
            except DHEError:
                errors["base"] = "cannot_connect"

        favorite_options = _weather_result_options(
            self._weather_favorites,
            max_options=MAX_WEATHER_RESULT_OPTIONS,
        )
        if not favorite_options and not errors:
            errors["base"] = "no_favorites"

        if user_input is not None and not errors:
            try:
                selected = int(user_input[ATTR_RESULT])
                location = self._weather_favorites[selected]
                await client.toggle_weather_favorite(location)
            except (IndexError, TypeError, ValueError):
                errors[ATTR_RESULT] = "invalid_result"
            except DHEError:
                errors["base"] = "remove_favorite_failed"
            else:
                return self._finish_options()

        return self.async_show_form(
            step_id="remove_weather_favorite",
            data_schema=vol.Schema({vol.Required(ATTR_RESULT): vol.In(favorite_options)}),
            errors=errors,
        )

    async def async_step_radio_favorite(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Select how DHE radio stations should be searched."""
        errors: dict[str, str] = {}
        defaults = user_input or {}

        if user_input is not None:
            search_type = str(user_input.get(ATTR_RADIO_SEARCH_TYPE, "")).strip()
            if search_type not in RADIO_SEARCH_TYPES:
                errors[ATTR_RADIO_SEARCH_TYPE] = "invalid_radio_search_type"
            else:
                self._radio_search_type = search_type
                self._radio_results = []
                return await self.async_step_radio_favorite_catalog()

        return self.async_show_form(
            step_id="radio_favorite",
            data_schema=_radio_search_type_schema(self.hass, defaults),
            errors=errors,
        )

    async def async_step_radio_favorite_catalog(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Search DHE radio stations by a selected catalog value."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        defaults = user_input or {}
        search_type = (
            self._radio_search_type
            if self._radio_search_type in RADIO_SEARCH_TYPES
            else "text"
        )

        if (
            client is not None
            and
            search_type in RADIO_CATALOG_SEARCH_TYPES
            and search_type not in self._radio_catalogs
        ):
            try:
                self._radio_catalogs[search_type] = await client.list_radio_catalog(
                    search_type
                )
            except DHEError:
                errors["base"] = "radio_catalog_failed"

        catalog_options = (
            _radio_catalog_options(self._radio_catalogs.get(search_type, []))
            if search_type in RADIO_CATALOG_SEARCH_TYPES
            else {}
        )
        if (
            search_type in RADIO_CATALOG_SEARCH_TYPES
            and not catalog_options
            and not errors
        ):
            errors["base"] = "no_radio_catalog"

        if user_input is not None and not errors:
            catalog_value = str(user_input.get(ATTR_RADIO_SELECTION, "")).strip()
            search_text = str(user_input.get(ATTR_RADIO_FILTER_TEXT, "")).strip()
            if search_type in RADIO_CATALOG_SEARCH_TYPES and not catalog_value:
                errors[ATTR_RADIO_SELECTION] = "required"
            elif (
                search_type in RADIO_CATALOG_SEARCH_TYPES
                and catalog_options
                and catalog_value not in catalog_options
            ):
                errors[ATTR_RADIO_SELECTION] = "invalid_radio_catalog_value"
            elif (
                search_type == "text" or search_type in RADIO_FILTER_SEARCH_TYPES
            ) and not search_text:
                errors[ATTR_RADIO_FILTER_TEXT] = "required"
            else:
                station_search_value = (
                    search_text if search_type == "text" else catalog_value
                )
                station_search_text = (
                    search_text if search_type in RADIO_FILTER_SEARCH_TYPES else None
                )
                try:
                    self._radio_results = await client.search_radio_stations(
                        search_type,
                        station_search_value,
                        search_text=station_search_text,
                    )
                    if station_search_text:
                        self._radio_results = _filter_radio_results_by_text(
                            self._radio_results,
                            station_search_text,
                        )
                except DHEError:
                    errors["base"] = "radio_search_failed"
                else:
                    if not self._radio_results:
                        errors["base"] = "no_results"
                    else:
                        return await self.async_step_radio_favorite_result()

        return self.async_show_form(
            step_id="radio_favorite_catalog",
            data_schema=_radio_catalog_schema(search_type, catalog_options, defaults),
            errors=errors,
        )

    async def async_step_radio_favorite_result(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Select one radio station search result and save it as favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        result_options = _radio_result_options(
            self._radio_results,
            max_options=MAX_RADIO_RESULT_OPTIONS,
        )

        if not result_options and "base" not in errors:
            errors["base"] = "no_results"

        if user_input is not None and not errors:
            try:
                selected = int(user_input[ATTR_RESULT])
                station = self._radio_results[selected]
                await client.add_radio_favorite(station, select=True)
            except (IndexError, TypeError, ValueError):
                errors[ATTR_RESULT] = "invalid_result"
            except DHEError:
                errors["base"] = "radio_favorite_failed"
            else:
                return self._finish_options()

        return self.async_show_form(
            step_id="radio_favorite_result",
            data_schema=vol.Schema({vol.Required(ATTR_RESULT): vol.In(result_options)}),
            errors=errors,
        )

    async def async_step_remove_radio_favorite(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Remove a DHE radio favorite."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)
        if client is not None:
            try:
                self._radio_favorites = await client.list_radio_favorites()
            except DHEError:
                errors["base"] = "cannot_connect"

        favorite_options = _radio_result_options(
            self._radio_favorites,
            max_options=MAX_RADIO_RESULT_OPTIONS,
        )
        if not favorite_options and not errors:
            errors["base"] = "no_radio_favorites"

        if user_input is not None and not errors:
            try:
                selected = int(user_input[ATTR_RESULT])
                station = self._radio_favorites[selected]
                await client.remove_radio_favorite(station)
            except (IndexError, TypeError, ValueError):
                errors[ATTR_RESULT] = "invalid_result"
            except DHEError:
                errors["base"] = "remove_radio_favorite_failed"
            else:
                return self._finish_options()

        return self.async_show_form(
            step_id="remove_radio_favorite",
            data_schema=vol.Schema({vol.Required(ATTR_RESULT): vol.In(favorite_options)}),
            errors=errors,
        )

    def _client(self) -> Any | None:
        """Return the runtime DHE client for this config entry."""
        runtime = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        return getattr(runtime, "client", None)
