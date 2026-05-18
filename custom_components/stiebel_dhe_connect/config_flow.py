"""Config flow for Stiebel DHE Connect."""

from __future__ import annotations

import asyncio
from ipaddress import IPv4Network
import logging
import os
from collections.abc import Mapping, Sequence
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
    internal_scald_protection_options as _internal_scald_protection_options,
    optional_float as _optional_float,
    radio_catalog_schema as _radio_catalog_schema,
    radio_search_type_schema as _radio_search_type_schema,
    schema as _schema,
    weather_search_schema as _weather_search_schema,
)
from .config_flow_setup import (
    CONF_SCAN_AUTOMATICALLY,
    CONF_SCAN_CIDR,
    CONF_SCAN_NETMASK,
    CONF_SCAN_NETWORK_ADDRESS,
    CONF_SCAN_SUBNET_MODE,
    CONF_SETUP_MODE,
    SETUP_SCAN_PROGRESS_ACTION,
    apply_validation_error as _apply_validation_error,
    language_from_hass as _language_from_hass,
    required_scan_subnet as _required_scan_subnet,
    scan_subnet_cidr_input as _scan_subnet_cidr_input,
    scan_subnet_network_mask_error_field as _scan_subnet_network_mask_error_field,
    scan_subnet_network_mask_input as _scan_subnet_network_mask_input,
    scan_subnet_suggested_values as _scan_subnet_suggested_values,
    setup_mode_labels as _setup_mode_labels,
)
from .config_entry_helpers import merged_entry_data
from .config_entry_helpers import entry_target as _entry_target
from .config_entry_helpers import (
    is_target_used_by_other_entry as _is_target_used_by_other_entry,
)
from .config_flow_discovery import (
    FLOW_CONTEXT_DISCOVERED_HOST,
    FLOW_CONTEXT_DISCOVERED_PORT,
    FLOW_CONTEXT_DISCOVERY_NAME,
    SETUP_MODE_MANUAL,
    SETUP_MODE_SCAN,
    SetupPairingResult,
    ZeroconfSetupChoice,
    coerce_setup_pairing_result as _coerce_setup_pairing_result,
    device_unique_id_from_info as _device_unique_id_from_info,
    discovery_info_name as _discovery_info_name,
    is_matching_flow_in_progress as _is_matching_flow_in_progress,
    zeroconf_setup_choices_from_progress as _zeroconf_setup_choices_from_progress,
)
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
    INTERNAL_SCALD_PROTECTION_DEFAULT,
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
    SCAN_SUBNET_MODE_CIDR,
    SCAN_SUBNET_MODE_CURRENT,
    SCAN_SUBNET_MODE_NETWORK_MASK,
    async_scan_dhe_hosts,
    candidate_defaults,
    ipv4_scan_networks,
    local_ipv4_addresses_from_hass,
    setup_scan_mode_options,
    setup_scan_status_text,
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
) -> SetupPairingResult:
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
        return SetupPairingResult(error_key=map_pairing_error(err, pairing_state))
    device_info = getattr(probe_client, "last_device_info", {})
    return SetupPairingResult(
        unique_id=_device_unique_id_from_info(device_info)
        if isinstance(device_info, Mapping)
        else None
    )


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
            "scan_status": setup_scan_status_text(
                _language_from_hass(self.hass),
                scanned=self._setup_scan_done,
                found=len(self._setup_scan_candidates),
                available=len(available),
                failed=self._setup_scan_failed,
            )
        }

    def _available_zeroconf_choices(self) -> list[ZeroconfSetupChoice]:
        """Return discovered Zeroconf choices not already configured."""
        return [
            choice
            for choice in _zeroconf_setup_choices_from_progress(
                self.hass,
                current_flow_id=getattr(self, "flow_id", None),
            )
            if not _is_target_used_by_other_entry(self.hass, choice.host, choice.port)
        ]

    def _setup_choice_options(self) -> dict[str, str]:
        """Return initial setup choices: Zeroconf discoveries, scan, manual."""
        options = {choice.key: choice.label for choice in self._available_zeroconf_choices()}
        options.update(_setup_mode_labels(_language_from_hass(self.hass)))
        return options

    def _show_setup_choice_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show Zeroconf discoveries, subnet scan and manual setup choices."""
        options = self._setup_choice_options()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SETUP_MODE, default=SETUP_MODE_SCAN): vol.In(
                        options
                    ),
                }
            ),
            errors=errors or {},
        )

    def _show_subnet_scan_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show subnet selection mode before running the setup scan."""
        mode_options = setup_scan_mode_options(_language_from_hass(self.hass))
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_SUBNET_MODE,
                    default=SCAN_SUBNET_MODE_CURRENT,
                ): vol.In(mode_options),
            }
        )
        return self.async_show_form(
            step_id="subnet_scan",
            data_schema=data_schema,
            errors=errors or {},
        )

    def _show_subnet_scan_network_mask_form(
        self,
        errors: dict[str, str] | None = None,
        suggested_values: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show network-address and subnet-mask fields before scanning."""
        return self._show_subnet_scan_value_form(
            "subnet_scan_network_mask",
            vol.Schema(
                {
                    vol.Required(CONF_SCAN_NETWORK_ADDRESS): str,
                    vol.Required(CONF_SCAN_NETMASK): str,
                }
            ),
            errors=errors,
            suggested_values=suggested_values,
        )

    def _show_subnet_scan_cidr_form(
        self,
        errors: dict[str, str] | None = None,
        suggested_values: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show a CIDR-only subnet field before scanning."""
        return self._show_subnet_scan_value_form(
            "subnet_scan_cidr",
            vol.Schema({vol.Required(CONF_SCAN_CIDR): str}),
            errors=errors,
            suggested_values=suggested_values,
        )

    def _show_subnet_scan_value_form(
        self,
        step_id: str,
        data_schema: vol.Schema,
        *,
        errors: dict[str, str] | None = None,
        suggested_values: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show one subnet value form with optional suggested values."""
        if suggested_values:
            data_schema = self.add_suggested_values_to_schema(
                data_schema,
                suggested_values,
            )
        return self.async_show_form(
            step_id=step_id,
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
        return _scan_subnet_suggested_values(networks[0])

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

    def _show_zeroconf_confirm_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show the only setup value not provided by Zeroconf."""
        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_INTERNAL_SCALD_PROTECTION,
                        default=INTERNAL_SCALD_PROTECTION_DEFAULT,
                    ): vol.In(_internal_scald_protection_options(self.hass)),
                }
            ),
            errors=errors or {},
        )

    def _set_pending_setup_data(
        self,
        *,
        host: str,
        port: int,
        name: str,
        token_file: str,
        internal_scald_protection: str | None = None,
    ) -> None:
        """Store validated setup data until pairing succeeds."""
        self._pending_setup_data = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_NAME: name,
            "token_file": token_file,
        }
        if internal_scald_protection is not None:
            self._pending_setup_data[CONF_INTERNAL_SCALD_PROTECTION] = (
                internal_scald_protection
            )

    async def _async_start_discovered_setup(
        self,
        host: str,
        port: int,
        name: str,
        *,
        source_flow_id: str | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Start the setup path for a discovered DHE target."""
        if _is_target_used_by_other_entry(self.hass, host, port):
            return self.async_abort(reason="already_configured")
        self.context[FLOW_CONTEXT_DISCOVERED_HOST] = host
        self.context[FLOW_CONTEXT_DISCOVERED_PORT] = port
        self.context[FLOW_CONTEXT_DISCOVERY_NAME] = name
        if not await _can_connect(self.hass, host, port):
            return self.async_abort(reason="cannot_connect")
        if source_flow_id is not None:
            self.hass.config_entries.flow.async_abort(source_flow_id)

        self._set_pending_setup_data(
            host=host,
            port=port,
            name=name,
            token_file=token_file_for_target(host, port),
        )
        return await self.async_step_zeroconf_confirm()

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

        if CONF_SCAN_AUTOMATICALLY in user_input:
            if user_input.get(CONF_SCAN_AUTOMATICALLY):
                return await self.async_step_subnet_scan()
            return await self.async_step_manual()

        setup_mode = str(user_input.get(CONF_SETUP_MODE) or "").strip()
        if setup_mode == SETUP_MODE_SCAN:
            return await self.async_step_subnet_scan()
        if setup_mode == SETUP_MODE_MANUAL:
            return await self.async_step_manual()

        for choice in self._available_zeroconf_choices():
            if setup_mode == choice.key:
                return await self._async_start_discovered_setup(
                    choice.host,
                    choice.port,
                    choice.name,
                    source_flow_id=choice.flow_id,
                )

        return self._show_setup_choice_form({CONF_SETUP_MODE: "invalid_setup_mode"})

    async def async_step_zeroconf(self, discovery_info: Any):
        """Handle a DHE discovered by Zeroconf/mDNS."""
        try:
            host_value = (
                getattr(discovery_info, "host", None)
                or getattr(discovery_info, "hostname", None)
                or getattr(discovery_info, "ip_address", None)
            )
            host = normalize_host(str(host_value or ""))
            port = validate_port(getattr(discovery_info, "port", None) or DEFAULT_PORT)
        except (TypeError, ValueError):
            return self.async_abort(reason="invalid_discovery_parameters")

        if _is_target_used_by_other_entry(self.hass, host, port):
            return self.async_abort(reason="already_configured")
        if _is_matching_flow_in_progress(
            self.hass,
            host,
            port,
            current_flow_id=getattr(self, "flow_id", None),
        ):
            return self.async_abort(reason="already_in_progress")

        name = _discovery_info_name(discovery_info)
        return await self._async_start_discovered_setup(host, port, name)

    async def async_step_zeroconf_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Collect physical Tmax jumper setting for a Zeroconf setup flow."""
        if self._pending_setup_data is None:
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            internal_scald_protection = str(
                user_input.get(CONF_INTERNAL_SCALD_PROTECTION) or ""
            ).strip()
            if internal_scald_protection not in INTERNAL_SCALD_PROTECTION_OPTIONS:
                errors[CONF_INTERNAL_SCALD_PROTECTION] = (
                    "invalid_internal_scald_protection"
                )
            else:
                self._pending_setup_data[CONF_INTERNAL_SCALD_PROTECTION] = (
                    internal_scald_protection
                )
                return await self.async_step_pairing_confirm()

        return self._show_zeroconf_confirm_form(errors)

    async def async_step_subnet_scan(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Choose how the setup scan subnet should be selected."""
        if user_input is None:
            return self._show_subnet_scan_form()
        mode = user_input.get(CONF_SCAN_SUBNET_MODE)
        if mode == SCAN_SUBNET_MODE_CURRENT:
            self._setup_scan_networks = None
            return await self.async_step_network_scan()
        if mode == SCAN_SUBNET_MODE_NETWORK_MASK:
            return await self.async_step_subnet_scan_network_mask()
        if mode == SCAN_SUBNET_MODE_CIDR:
            return await self.async_step_subnet_scan_cidr()
        return self._show_subnet_scan_form(
            {CONF_SCAN_SUBNET_MODE: "invalid_scan_subnet_mode"}
        )

    async def async_step_subnet_scan_network_mask(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Collect a network address and subnet mask before scanning."""
        if user_input is None:
            return self._show_subnet_scan_network_mask_form(
                suggested_values=await self._async_subnet_scan_form_defaults()
            )
        scan_input = _scan_subnet_network_mask_input(user_input)
        try:
            scan_subnet = _required_scan_subnet(scan_input)
        except ValueError as err:
            return self._show_subnet_scan_network_mask_form(
                {_scan_subnet_network_mask_error_field(scan_input): str(err)},
                suggested_values=user_input,
            )
        self._setup_scan_networks = [scan_subnet]
        return await self.async_step_network_scan()

    async def async_step_subnet_scan_cidr(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Collect a CIDR subnet before scanning."""
        if user_input is None:
            return self._show_subnet_scan_cidr_form(
                suggested_values=await self._async_subnet_scan_form_defaults()
            )
        scan_input = _scan_subnet_cidr_input(user_input)
        try:
            scan_subnet = _required_scan_subnet(scan_input)
        except ValueError as err:
            return self._show_subnet_scan_cidr_form(
                {CONF_SCAN_CIDR: str(err)},
                suggested_values=user_input,
            )
        self._setup_scan_networks = [scan_subnet]
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
                    self._set_pending_setup_data(
                        host=host,
                        port=port,
                        name=name,
                        token_file=token_file_for_target(host, port),
                        internal_scald_protection=internal_scald_protection,
                    )
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
            pairing_result = _coerce_setup_pairing_result(
                await _validate_setup_pairing(
                    self.hass,
                    setup_data[CONF_HOST],
                    setup_data[CONF_PORT],
                    setup_data["token_file"],
                )
            )
            if pairing_result.error_key is None:
                if pairing_result.unique_id is not None:
                    await self.async_set_unique_id(pairing_result.unique_id)
                    self._abort_if_unique_id_configured()
                self._pending_setup_data = None
                setup_data.pop("token_file", None)
                return self.async_create_entry(
                    title=setup_data[CONF_NAME],
                    data=setup_data,
                )
            errors["base"] = pairing_result.error_key

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
                    data = {
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_NAME: name,
                        CONF_INTERNAL_SCALD_PROTECTION: internal_scald_protection,
                    }
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
                            data_schema=_schema(self.hass, data),
                            errors=errors,
                        )

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
            pairing_result = _coerce_setup_pairing_result(
                await _validate_setup_pairing(
                    self.hass,
                    data[CONF_HOST],
                    data[CONF_PORT],
                    token_file_for_target(data[CONF_HOST], data[CONF_PORT]),
                )
            )
            if pairing_result.error_key is None:
                self._pending_connection_data = None
                return self.async_create_entry(title="", data=data)
            errors["base"] = pairing_result.error_key

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
