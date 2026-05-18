"""Config flow for Stiebel DHE Connect."""

from __future__ import annotations

import asyncio
from ipaddress import IPv4Network
import logging
import os
from collections.abc import Sequence
from typing import Any, Protocol, cast

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import (
    DHEClient,
)
from .client_types import DHEError
from .config_flow_mapping import (
    filter_radio_results_by_text as _filter_radio_results_by_text,
    radio_catalog_options as _radio_catalog_options,
    radio_result_options as _radio_result_options,
    weather_country_options as _weather_country_options,
    weather_result_options as _weather_result_options,
)
from .config_flow_schemas import (
    ATTR_CO2_EMISSION,
    ATTR_COUNTRY_ID,
    ATTR_CURRENCY,
    ATTR_ELECTRICITY_PRICE,
    ATTR_RADIO_FILTER_TEXT,
    ATTR_RADIO_SEARCH_TYPE,
    ATTR_RADIO_SELECTION,
    ATTR_RESULT,
    ATTR_WATER_PRICE,
    CURRENCY_UNCHANGED,
    MAX_RADIO_RESULT_OPTIONS,
    MAX_WEATHER_RESULT_OPTIONS,
    RADIO_CATALOG_SEARCH_TYPES,
    RADIO_FILTER_SEARCH_TYPES,
    RADIO_SEARCH_TYPES,
    currency_options as _schema_currency_options,
    device_settings_defaults as _device_settings_defaults,
    device_settings_schema as _device_settings_schema,
    optional_float as _optional_float,
    radio_catalog_schema as _radio_catalog_schema,
    radio_search_type_schema as _radio_search_type_schema,
    schema as _schema,
    weather_search_schema as _weather_search_schema,
)
from .config_entry_helpers import merged_entry_data
from .connection_helpers import (
    host_for_url,
    normalize_host,
    target_changed,
    validate_port,
)
from .const import (
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
)
from .entity_state_helpers import (
    CONF_INTERNAL_SCALD_PROTECTION,
    INTERNAL_SCALD_PROTECTION_OPTIONS,
)
from .pairing_helpers import map_pairing_error
from .protocol import (
    CO2_EMISSION_MAX,
    ELECTRICITY_PRICE_MAX,
    ID_APP_CURRENCY as _ID_APP_CURRENCY,
    WATER_PRICE_MAX,
)
from .setup_scan import (
    DHEHostCandidate,
    async_scan_dhe_hosts,
    candidate_defaults,
    ipv4_scan_networks,
    local_ipv4_addresses_from_hass,
    parse_scan_subnet,
)
from .token_file_helpers import (
    LEGACY_TOKEN_FILE,
    legacy_token_file_for_entry,
    legacy_token_files_for_target,
    stale_unconfigured_token_paths,
    token_file_for_target,
)

SETUP_PAIRING_TIMEOUT_SECONDS = 180.0
ID_APP_CURRENCY = _ID_APP_CURRENCY
_currency_options = _schema_currency_options
CONF_SCAN_AUTOMATICALLY = "scan_automatically"
CONF_SCAN_NETWORK_ADDRESS = "scan_network_address"
CONF_SCAN_NETMASK = "scan_netmask"
CONF_SCAN_CIDR = "scan_cidr"
SETUP_SCAN_PROGRESS_ACTION = "scan_dhe"

_LOGGER = logging.getLogger(__name__)


class _OptionsFlowClient(Protocol):
    """Client surface used by the options flow."""

    async def set_currency(self, currency: str) -> str: ...

    async def set_electricity_price(self, euros_per_kwh: float) -> float: ...

    async def set_water_price(self, euros_per_m3: float) -> float: ...

    async def set_co2_emission(self, kg_per_kwh: float) -> float: ...

    async def list_weather_countries(self) -> list[dict[str, Any]]: ...

    async def search_weather_locations(
        self,
        name: str,
        country_id: int | float | str,
    ) -> list[dict[str, Any]]: ...

    async def list_weather_favorites(self) -> list[dict[str, Any]]: ...

    async def add_weather_favorite(self, location: dict[str, Any]) -> bool: ...

    async def remove_weather_favorite(self, location: dict[str, Any]) -> bool: ...

    async def list_radio_catalog(self, attribute: str) -> list[str]: ...

    async def search_radio_stations(
        self,
        attribute: str,
        value: str,
        *,
        search_text: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def list_radio_favorites(self) -> list[dict[str, Any]]: ...

    async def add_radio_favorite(
        self,
        station: dict[str, Any] | int | str,
        *,
        select: bool = True,
    ) -> bool: ...

    async def remove_radio_favorite(self, station: dict[str, Any] | int | str) -> bool:
        ...


def _apply_validation_error(errors: dict[str, str], err: ValueError) -> None:
    """Map validation exceptions to form fields."""
    code = str(err) or "invalid_host"
    if code == "invalid_port":
        errors[CONF_PORT] = code
    elif code == "invalid_internal_scald_protection":
        errors[CONF_INTERNAL_SCALD_PROTECTION] = code
    elif code == "embedded_port_not_supported":
        errors[CONF_HOST] = code
    else:
        errors[CONF_HOST] = "invalid_host"


def _scan_subnet_from_input(user_input: dict[str, Any]) -> IPv4Network | None:
    """Return the optional setup-scan subnet from split form fields."""
    cidr = str(user_input.get(CONF_SCAN_CIDR) or "").strip()
    network_address = str(user_input.get(CONF_SCAN_NETWORK_ADDRESS) or "").strip()
    netmask = str(user_input.get(CONF_SCAN_NETMASK) or "").strip()

    if cidr:
        if network_address or netmask:
            raise ValueError("invalid_scan_subnet")
        return parse_scan_subnet(cidr)
    if network_address or netmask:
        if not network_address or not netmask:
            raise ValueError("invalid_scan_subnet")
        return parse_scan_subnet(f"{network_address} {netmask}")
    return None


def _scan_subnet_error_field(user_input: dict[str, Any]) -> str:
    """Return the most helpful form field for a setup-scan subnet error."""
    if str(user_input.get(CONF_SCAN_CIDR) or "").strip():
        return CONF_SCAN_CIDR
    if str(user_input.get(CONF_SCAN_NETMASK) or "").strip() and not str(
        user_input.get(CONF_SCAN_NETWORK_ADDRESS) or ""
    ).strip():
        return CONF_SCAN_NETWORK_ADDRESS
    if str(user_input.get(CONF_SCAN_NETWORK_ADDRESS) or "").strip():
        return CONF_SCAN_NETMASK
    return CONF_SCAN_CIDR


def _scan_subnet_form_defaults(network: IPv4Network) -> dict[str, str]:
    """Return split setup-scan form defaults for one IPv4 network."""
    return {
        CONF_SCAN_NETWORK_ADDRESS: str(network.network_address),
        CONF_SCAN_NETMASK: str(network.netmask),
        CONF_SCAN_CIDR: "",
    }


def _entry_target(entry: config_entries.ConfigEntry) -> tuple[str, int] | None:
    """Return normalized host/port from an existing config entry."""
    merged = merged_entry_data(entry)
    host_value = merged.get(CONF_HOST)
    if host_value is None:
        return None
    try:
        host = normalize_host(str(host_value))
        port = validate_port(int(merged.get(CONF_PORT, DEFAULT_PORT)))
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


def _scan_status_text(
    hass: HomeAssistant,
    *,
    scanned: bool,
    found: int,
    available: int,
    failed: bool = False,
) -> str:
    """Return localized setup-scan status text for the setup form."""
    language = str(getattr(hass.config, "language", "") or "").lower()
    if language.startswith("de"):
        if not scanned and not failed:
            return "Host/IP, Port und Tmax-Jumperposition eintragen."
        if failed:
            return "Die automatische Suche ist fehlgeschlagen; bitte Host und Port manuell eintragen."
        if found == 0:
            return "Es wurde kein DHE gefunden; bitte Host und Port manuell eintragen."
        if available == 0:
            return "Gefundene DHE-Ziele sind bereits konfiguriert; bitte bei Bedarf ein anderes Ziel manuell eintragen."
        if available == 1:
            return "Ein DHE wurde gefunden und Host/Port sind vorbelegt."
        return f"{available} DHE-Kandidaten wurden gefunden; der erste ist vorbelegt."
    if failed:
        return "Automatic search failed; enter host and port manually."
    if not scanned:
        return "Enter host/IP, port and physical Tmax jumper position."
    if found == 0:
        return "No DHE was found; enter host and port manually."
    if available == 0:
        return "Found DHE targets are already configured; enter another target manually if needed."
    if available == 1:
        return "Found one DHE and prefilled host/port."
    return f"Found {available} DHE candidates; the first one is prefilled."


def _abs_config_path(hass: HomeAssistant, path: str) -> str:
    """Return a normalized absolute Home Assistant config path."""
    return os.path.normcase(os.path.abspath(hass.config.path(path)))


def _configured_token_paths(hass: HomeAssistant) -> set[str]:
    """Return token paths that belong to currently configured DHE entries."""
    paths: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        paths.add(_abs_config_path(hass, legacy_token_file_for_entry(entry.entry_id)))
        target = _entry_target(entry)
        if target is None:
            continue
        entry_host, entry_port = target
        paths.add(_abs_config_path(hass, token_file_for_target(entry_host, entry_port)))
        for legacy_path in legacy_token_files_for_target(entry_host, entry_port):
            paths.add(_abs_config_path(hass, legacy_path))
    return paths


def _setup_token_cleanup_context(
    hass: HomeAssistant,
    host: str,
    port: int,
    token_file: str,
) -> tuple[set[str], str, set[str]]:
    """Return token cleanup data without touching the filesystem."""
    explicit_paths = {
        _abs_config_path(hass, token_file),
        _abs_config_path(hass, LEGACY_TOKEN_FILE),
    }
    explicit_paths.update(
        _abs_config_path(hass, legacy_path)
        for legacy_path in legacy_token_files_for_target(host, port)
    )

    configured_paths = _configured_token_paths(hass)
    storage_path = hass.config.path(".storage")
    return explicit_paths, storage_path, configured_paths


async def _async_clear_setup_token_files(
    hass: HomeAssistant,
    host: str,
    port: int,
    token_file: str,
) -> None:
    """Remove stale setup tokens before requesting a fresh DHE pairing token."""
    explicit_paths, storage_path, configured_paths = _setup_token_cleanup_context(
        hass,
        host,
        port,
        token_file,
    )

    def _delete() -> list[str]:
        paths = set(explicit_paths)
        token_file_names: Sequence[str]
        try:
            token_file_names = os.listdir(storage_path)
        except OSError:
            token_file_names = ()
        paths.update(
            stale_unconfigured_token_paths(
                storage_path,
                token_file_names,
                configured_paths,
            )
        )
        removed: list[str] = []
        for path in paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                continue
            except OSError:
                continue
            removed.append(path)
        return removed

    removed_paths = await hass.async_add_executor_job(_delete)
    if removed_paths:
        _LOGGER.debug(
            "Removed stale DHE setup token files before pairing: %s",
            ", ".join(sorted(removed_paths)),
        )


async def _can_connect(hass: HomeAssistant, host: str, port: int) -> bool:
    """Check if the DHE web endpoint is reachable before creating the config entry."""
    session = async_get_clientsession(hass)
    url = f"http://{host_for_url(host)}:{port}/"

    try:
        async with session.get(url, timeout=8) as resp:
            await resp.read()
            return 200 <= resp.status < 500
    except (aiohttp.ClientError, TimeoutError, OSError):
        return False


async def _validate_setup_pairing(
    hass: HomeAssistant,
    host: str,
    port: int,
    token_file: str,
) -> str | None:
    """Run one-shot pairing/auth validation before creating the config entry."""
    await _async_clear_setup_token_files(hass, host, port, token_file)
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
    except (DHEError, TimeoutError, OSError, RuntimeError, aiohttp.ClientError) as err:
        pairing_state = str(probe_client.diagnostic_state.get("pairing_state") or "")
        return map_pairing_error(err, pairing_state)
    return None


class StiebelDHEConnectConfigFlow(  # type: ignore[call-arg]
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle a config flow for Stiebel DHE Connect."""

    VERSION = 1
    _pending_setup_data: dict[str, Any] | None
    _setup_scan_task: asyncio.Task[list[DHEHostCandidate]] | None
    _setup_scan_candidates: list[DHEHostCandidate]
    _setup_scan_done: bool
    _setup_scan_failed: bool
    _setup_scan_networks: list[IPv4Network] | None

    def __init__(self) -> None:
        self._pending_setup_data = None
        self._setup_scan_task = None
        self._setup_scan_candidates = []
        self._setup_scan_done = False
        self._setup_scan_failed = False
        self._setup_scan_networks = None

    def _available_scan_candidates(self) -> list[DHEHostCandidate]:
        """Return scan candidates not already configured."""
        return [
            candidate
            for candidate in self._setup_scan_candidates
            if not _is_target_used_by_other_entry(
                self.hass,
                candidate.host,
                candidate.port,
            )
        ]

    def _setup_scan_defaults(self) -> dict[str, Any]:
        """Return user-form defaults based on setup scan results."""
        available = self._available_scan_candidates()
        if not available:
            return {}
        return candidate_defaults(available[0])

    def _setup_scan_placeholders(self) -> dict[str, str]:
        """Return description placeholders for the setup form."""
        available = self._available_scan_candidates()
        return {
            "scan_status": _scan_status_text(
                self.hass,
                scanned=self._setup_scan_done,
                found=len(self._setup_scan_candidates),
                available=len(available),
                failed=self._setup_scan_failed,
            )
        }

    def _show_setup_choice_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show automatic subnet scan vs manual setup choice."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_AUTOMATICALLY, default=False): bool,
                }
            ),
            errors=errors or {},
        )

    def _show_subnet_scan_form(
        self,
        errors: dict[str, str] | None = None,
        suggested_values: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show optional subnet fields before running the setup scan."""
        data_schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_NETWORK_ADDRESS): str,
                vol.Optional(CONF_SCAN_NETMASK): str,
                vol.Optional(CONF_SCAN_CIDR): str,
            }
        )
        if suggested_values:
            data_schema = self.add_suggested_values_to_schema(
                data_schema,
                suggested_values,
            )
        return self.async_show_form(
            step_id="subnet_scan",
            data_schema=data_schema,
            errors=errors or {},
        )

    async def _async_subnet_scan_form_defaults(self) -> dict[str, str]:
        """Return setup-scan defaults from Home Assistant's local IPv4 subnet."""
        try:
            addresses = await self.hass.async_add_executor_job(
                local_ipv4_addresses_from_hass,
                self.hass,
            )
        except (AttributeError, OSError, RuntimeError):
            return {}
        networks = ipv4_scan_networks(addresses)
        if not networks:
            return {}
        return _scan_subnet_form_defaults(networks[0])

    def _show_user_form(
        self,
        *,
        step_id: str = "manual",
        errors: dict[str, str] | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show the manual setup form with optional scan defaults."""
        merged_defaults = dict(self._setup_scan_defaults())
        if defaults:
            merged_defaults.update(defaults)
        return self.async_show_form(
            step_id=step_id,
            data_schema=_schema(self.hass, merged_defaults),
            errors=errors or {},
            description_placeholders=self._setup_scan_placeholders(),
        )

    async def _async_handle_setup_scan(self) -> config_entries.ConfigFlowResult | None:
        """Start or finish the optional setup scan."""
        if self._setup_scan_done:
            return None
        if self._setup_scan_task is None:
            self._setup_scan_task = self.hass.async_create_task(
                async_scan_dhe_hosts(self.hass, networks=self._setup_scan_networks),
            )
            return self.async_show_progress(
                step_id="network_scan",
                progress_action=SETUP_SCAN_PROGRESS_ACTION,
                progress_task=self._setup_scan_task,
            )
        if not self._setup_scan_task.done():
            return self.async_show_progress(
                step_id="network_scan",
                progress_action=SETUP_SCAN_PROGRESS_ACTION,
                progress_task=self._setup_scan_task,
            )
        try:
            self._setup_scan_candidates = self._setup_scan_task.result()
        except (aiohttp.ClientError, OSError, RuntimeError, TimeoutError) as err:
            self._setup_scan_candidates = []
            self._setup_scan_failed = True
            _LOGGER.debug("DHE setup scan failed: %s", err)
        self._setup_scan_done = True
        self._setup_scan_task = None
        return self.async_show_progress_done(next_step_id="manual")

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial setup choice."""
        if not user_input:
            return self._show_setup_choice_form()

        if CONF_HOST in user_input:
            return await self.async_step_manual(user_input)

        if user_input.get(CONF_SCAN_AUTOMATICALLY):
            return await self.async_step_subnet_scan()

        return await self.async_step_manual()

    async def async_step_subnet_scan(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Collect optional subnet input before running the setup scan."""
        if user_input is None:
            return self._show_subnet_scan_form(
                suggested_values=await self._async_subnet_scan_form_defaults()
            )
        try:
            scan_subnet = _scan_subnet_from_input(user_input)
        except ValueError as err:
            return self._show_subnet_scan_form(
                {_scan_subnet_error_field(user_input): str(err)},
                suggested_values=user_input,
            )
        self._setup_scan_networks = [scan_subnet] if scan_subnet else None
        return await self.async_step_network_scan()

    async def async_step_network_scan(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Scan the current local subnet when the user explicitly requests it."""
        scan_result = await self._async_handle_setup_scan()
        if scan_result is not None:
            return scan_result
        return await self.async_step_manual()

    async def async_step_manual(self, user_input: dict[str, Any] | None = None):
        """Handle manual setup, optionally prefilled by a completed scan."""
        errors: dict[str, str] = {}

        if not user_input:
            return self._show_user_form(errors=errors)

        if user_input is not None:
            try:
                host = normalize_host(user_input[CONF_HOST])
                port = validate_port(user_input.get(CONF_PORT, DEFAULT_PORT))
                internal_scald_protection = str(
                    user_input.get(CONF_INTERNAL_SCALD_PROTECTION) or ""
                ).strip()
                if internal_scald_protection not in INTERNAL_SCALD_PROTECTION_OPTIONS:
                    raise ValueError("invalid_internal_scald_protection")
            except ValueError as err:
                _apply_validation_error(errors, err)
            else:
                if _is_target_used_by_other_entry(self.hass, host, port):
                    return self.async_abort(reason="already_configured")
                name = str(user_input.get(CONF_NAME, DEFAULT_NAME)).strip() or DEFAULT_NAME

                if not await _can_connect(self.hass, host, port):
                    errors["base"] = "cannot_connect"
                else:
                    token_file = token_file_for_target(host, port)
                    self._pending_setup_data = {
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: name,
                        CONF_INTERNAL_SCALD_PROTECTION: internal_scald_protection,
                        "token_file": token_file,
                    }
                    return await self.async_step_pairing_confirm()

        return self._show_user_form(errors=errors, defaults=user_input)

    @callback
    def async_remove(self) -> None:
        """Cancel a running setup scan when the flow is removed."""
        if self._setup_scan_task is not None and not self._setup_scan_task.done():
            self._setup_scan_task.cancel()
        self._setup_scan_task = None

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
        self._pending_connection_data: dict[str, Any] | None = None
        self._menu_options: list[str] = [
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

    def _client_or_mark_not_loaded(
        self,
        errors: dict[str, str],
    ) -> _OptionsFlowClient | None:
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
                host = normalize_host(user_input[CONF_HOST])
                port = validate_port(user_input.get(CONF_PORT, DEFAULT_PORT))
                internal_scald_protection = str(
                    user_input.get(CONF_INTERNAL_SCALD_PROTECTION) or ""
                ).strip()
                if internal_scald_protection not in INTERNAL_SCALD_PROTECTION_OPTIONS:
                    raise ValueError("invalid_internal_scald_protection")
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
                else:
                    changed = target_changed(
                        current,
                        host,
                        port,
                        default_port=DEFAULT_PORT,
                    )
                    if changed and not await _can_connect(self.hass, host, port):
                        errors["base"] = "cannot_connect"
                        return self.async_show_form(
                            step_id="connection",
                            data_schema=_schema(self.hass, current),
                            errors=errors,
                        )

                    data = {
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: name,
                        CONF_INTERNAL_SCALD_PROTECTION: internal_scald_protection,
                    }
                    if changed:
                        self._pending_connection_data = data
                        return await self.async_step_connection_pairing_confirm()
                    return self.async_create_entry(
                        title="",
                        data=data,
                    )

        return self.async_show_form(
            step_id="connection",
            data_schema=_schema(self.hass, current),
            errors=errors,
        )

    async def async_step_connection_pairing_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Confirm pairing/authentication after changing host or port."""
        if self._pending_connection_data is None:
            return await self.async_step_connection()

        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(self._pending_connection_data)
            error_key = await _validate_setup_pairing(
                self.hass,
                data[CONF_HOST],
                data[CONF_PORT],
                token_file_for_target(data[CONF_HOST], data[CONF_PORT]),
            )
            if error_key is None:
                self._pending_connection_data = None
                return self.async_create_entry(title="", data=data)
            errors["base"] = error_key

        return self.async_show_form(
            step_id="connection_pairing_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_device_settings(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Manage DHE cost and emission settings."""
        errors: dict[str, str] = {}
        client = self._client_or_mark_not_loaded(errors)

        defaults = _device_settings_defaults(client) if client is not None else {}
        if user_input is not None and not errors and client is not None:
            try:
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
                return self._finish_options()

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

        if user_input is not None and not errors and client is not None:
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

        if user_input is not None and not errors and client is not None:
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
        if client is not None and user_input is None:
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

        if user_input is not None and not errors and client is not None:
            try:
                selected = int(user_input[ATTR_RESULT])
                location = self._weather_favorites[selected]
                await client.remove_weather_favorite(location)
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

        if user_input is not None and not errors and client is not None:
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

        if user_input is not None and not errors and client is not None:
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
        if client is not None and user_input is None:
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

        if user_input is not None and not errors and client is not None:
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

    def _client(self) -> _OptionsFlowClient | None:
        """Return the runtime DHE client for this config entry."""
        runtime = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        return cast(_OptionsFlowClient | None, getattr(runtime, "client", None))
