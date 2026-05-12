"""Persistent local Socket.IO/Engine.IO v3 client for Stiebel DHE Connect."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import random
import re
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client_mapping import (
    copy_json_like_value as _copy_json_like_value,
    device_status_key as _device_status_key,
    device_status_problem as _device_status_problem,
    normalize_radio_stations_value as _normalize_radio_stations_value,
    normalize_radio_string_catalog as _normalize_radio_string_catalog,
    normalize_weather_favorites_value as _normalize_weather_favorites_value,
    normalize_weather_locations_value as _normalize_weather_locations_value,
    normalize_weather_value as _normalize_weather_value,
    radio_station_id as _radio_station_id,
    radio_station_in_list as _radio_station_in_list,
    weather_location_id as _weather_location_id,
    weather_location_in_list as _weather_location_in_list,
)
from .pairing_helpers import (
    pairing_notification_text,
    pairing_result_success as _pairing_result_success,
)

_LOGGER = logging.getLogger(__name__)

NS = "1.0.0"
ODB_GET_COMMAND = "get:ste.common.odb:value"
ODB_SET_COMMAND = "set:ste.common.odb:value"
ODB_ASSIGN_COMMAND = "assign:ste.common.odb:value"
TEMP_MEMORY_GET_COMMAND = "get:ste.common.temperature:memory"
TEMP_MEMORY_SET_COMMAND = "set:ste.common.temperature:memory"
TEMP_MEMORY_ASSIGN_COMMAND = "assign:ste.common.temperature:memory"
CURRENCY_GET_COMMAND = "get:ste.common.currency:value"
CURRENCY_SET_COMMAND = "set:ste.common.currency:value"

ID_SETPOINT = 0
ID_BATH_FILL_ACTIVE = 1
ID_WELLNESS_SHOWER_PROGRAM = 2
ID_BATH_FILL_TARGET_VOLUME = 3
ID_CHILD_SAFETY_ACTIVE = 4
ID_CHILD_SAFETY_TEMPERATURE_LIMIT = 5
ID_ECO_MODE = 6
ID_ECO_FLOW_LIMIT = 7
ID_WELLNESS_ACTIVE = 10
WINTER_REFRESH_PROGRAM_ID = 2
WELLNESS_COLD_PREVENTION_PROGRAM_ID = 1
SUMMER_FITNESS_PROGRAM_ID = 3
CIRCULATION_SUPPORT_PROGRAM_ID = 4
ID_INLET_TEMPERATURE = 13
ID_OUTLET_TEMPERATURE = 14
ID_WATER_FLOW = 15
ID_POWER_PERCENT = 16
ID_OPERATING_DURATION = 18
ID_NOMINAL_POWER = 20
ID_SCALD_PROTECTION_ACTIVE = 22
ID_SCALD_PROTECTION_TEMPERATURE_LIMIT = 24
ID_HEATING_ENERGY_TOTAL = 29
ID_HOT_WATER_VOLUME_TOTAL = 30
ID_BATH_FILL_CURRENT_VOLUME = 31
ID_WELLNESS_TIME_NORMALIZED = 32
ID_WATER_HEATING_ENABLED = 33
ID_DEVICE_STATUS = 34
ID_ELECTRICITY_PRICE_EUROS = 61
ID_WATER_PRICE_EUROS = 62
ID_POSSIBLE_ENERGY_SAVING = 63
ID_POSSIBLE_WATER_SAVING = 64
ID_SETPOINT_REQUEST = 66
ID_PROTOCOL_VERSION = 67
ID_CURRENCY_MODE = 68
SET_REQ_OFF_VALUE = 10440
# Observed device behavior in field tests:
# - id 33 raw 1 => water heating OFF
# - id 33 raw 0 => water heating ON
WATER_HEATING_OFF_RAW = 1
WATER_HEATING_ON_RAW = 0
ID_CO2_EMISSION_RAW = 69
ID_ELECTRICITY_PRICE_CENTS = 70
ID_WATER_PRICE_CENTS = 71
ID_BRUSH_TIMER_ACTIVATION = 1001
ID_BRUSH_TIMER_DURATION = 1002
ID_BRUSH_TIMER_REMAINING = 1003
ID_SHOWER_TIMER_ACTIVATION = 1011
ID_SHOWER_TIMER_DURATION = 1012
ID_SHOWER_TIMER_REMAINING = 1013
ID_WATER_CONSUMPTION_WEEK = 1021
ID_WATER_CONSUMPTION_YEAR = 1022
ID_WATER_CONSUMPTION_YEARS = 1023
ID_ENERGY_CONSUMPTION_WEEK = 1031
ID_ENERGY_CONSUMPTION_YEAR = 1032
ID_ENERGY_CONSUMPTION_YEARS = 1033
ID_TEMPERATURE_MEMORY_1 = 1041
ID_TEMPERATURE_MEMORY_2 = 1042
ID_LAST_USAGE_WATER = 1051
ID_LAST_USAGE_ENERGY = 1052
ID_LAST_USAGE_TIME = 1053
ID_LAST_USAGE_COST = 1054
ID_SAVING_MONITOR_WATER = 1061
ID_SAVING_MONITOR_ENERGY = 1062
ID_SAVING_MONITOR_CO2 = 1063
ID_SAVING_MONITOR_ACTIVATION_RATE = 1064
ID_SAVING_MONITOR_POSSIBLE_WATER = 1065
ID_SAVING_MONITOR_POSSIBLE_ENERGY = 1066
ID_SAVING_MONITOR_POSSIBLE_CO2 = 1067
ID_SAVING_MONITOR_POSSIBLE_VALUE = 1068
ID_SAVING_MONITOR_REAL_WATER = 1069
ID_SAVING_MONITOR_REAL_ENERGY = 1070
ID_DEVICE_INFO = 1071
ID_SAVING_MONITOR_REAL_CO2 = 1072
ID_SAVING_MONITOR_REAL_VALUE = 1073
ID_BATH_FILL_REMAINING_VOLUME = 1082
ID_APP_CURRENCY = 1093
ID_ELECTRICITY_PRICE = 1101
ID_WATER_PRICE = 1102
ID_CO2_EMISSION = 1103
ID_TEMPERATURE_MEMORY_3 = 1111
ID_TEMPERATURE_MEMORY_4 = 1112
ID_TEMPERATURE_MEMORY_5 = 1113
ID_TEMPERATURE_MEMORY_6 = 1114
ID_TEMPERATURE_MEMORY_7 = 1115
ID_TEMPERATURE_MEMORY_8 = 1116
ID_TEMPERATURE_MEMORY_9 = 1117
ID_TEMPERATURE_MEMORY_10 = 1118
ID_TEMPERATURE_MEMORY_11 = 1119
ID_TEMPERATURE_MEMORY_12 = 1120
ODB_DEBUG_NAMES = {
    ID_SETPOINT: "ODB_So_WW_T",
    ID_BATH_FILL_ACTIVE: "ODB_VolBegr_Aktiv",
    ID_WELLNESS_SHOWER_PROGRAM: "ODB_Wellness_Ba",
    ID_BATH_FILL_TARGET_VOLUME: "ODB_VolBegr_Volumen_Grenz",
    ID_CHILD_SAFETY_ACTIVE: "ODB_KinderSich_Aktiv",
    ID_CHILD_SAFETY_TEMPERATURE_LIMIT: "ODB_KinderSich_T_Grenz",
    ID_ECO_MODE: "ODB_Eco_Aktiv",
    ID_ECO_FLOW_LIMIT: "ODB_Eco_VS_Grenz",
    ID_WELLNESS_ACTIVE: "ODB_Wellness_Aktiv",
    ID_INLET_TEMPERATURE: "ODB_Is_KW_T",
    ID_OUTLET_TEMPERATURE: "ODB_Is_WW_T",
    ID_WATER_FLOW: "ODB_Is_VS",
    ID_POWER_PERCENT: "ODB_Is_P_Norm",
    ID_OPERATING_DURATION: "ODB_Bdauer",
    ID_NOMINAL_POWER: "ODB_P_Nenn",
    ID_SCALD_PROTECTION_ACTIVE: "ODB_VerbrSchutz_Aktiv",
    ID_SCALD_PROTECTION_TEMPERATURE_LIMIT: "ODB_VerbrSchutz_T_Grenz",
    ID_HEATING_ENERGY_TOTAL: "ODB_Heizen_Energie",
    ID_HOT_WATER_VOLUME_TOTAL: "ODB_WW_Volumen",
    ID_BATH_FILL_CURRENT_VOLUME: "ODB_VolBegr_Volumen",
    ID_WELLNESS_TIME_NORMALIZED: "ODB_Wellness_Zeit_Norm",
    ID_WATER_HEATING_ENABLED: "ODB_Heizen_DeAktiv",
    ID_DEVICE_STATUS: "ODB_St_Geraet_Ba",
    ID_ELECTRICITY_PRICE_EUROS: "ODB_GZ_KWh_Energie_Kost",
    ID_WATER_PRICE_EUROS: "ODB_GZ_KW_Volumen_Kost",
    ID_POSSIBLE_ENERGY_SAVING: "ODB_Gsprt_Energie",
    ID_POSSIBLE_WATER_SAVING: "ODB_Gsprt_KW_Volumen",
    ID_SETPOINT_REQUEST: "ODB_So_WW_T_Anf",
    ID_PROTOCOL_VERSION: "ODB_Protokoll_Ver",
    ID_CURRENCY_MODE: "ODB_Waehrung_Ba",
    ID_CO2_EMISSION_RAW: "ODB_CO2_Energie",
    ID_ELECTRICITY_PRICE_CENTS: "ODB_Ct_KWh_Energie_Kost",
    ID_WATER_PRICE_CENTS: "ODB_Ct_KW_Volumen_Kost",
}
DEFAULT_NOMINAL_POWER_KW = 24.0
COMMAND_CONFIRMATION_TIMEOUT = 12.0
COMMAND_READBACK_INTERVAL = 1.0
APP_COMMAND_CONFIRMATION_TIMEOUT = 3.0
WEATHER_CATALOG_TIMEOUT = 8.0
AVAILABILITY_DROP_GRACE_SECONDS = 20.0
WEBSOCKET_UPGRADE_TIMEOUT = 8.0
AUTH_POLL_TIMEOUT_SECONDS = 10.0
MAX_PAIRING_AUTO_RETRIES = 3
DEFAULT_ENGINEIO_PING_INTERVAL_SECONDS = 25.0
PAIRING_NOTIFICATION_ID_PREFIX = "stiebel_dhe_connect_pairing"
PAIRING_CONFIRM_HINT_NOTIFICATION_ID_PREFIX = (
    "stiebel_dhe_connect_pairing_confirm"
)
PRICE_CENTS_COMPONENT_MAX = 99
ELECTRICITY_PRICE_EUROS_COMPONENT_MAX = 32767
WATER_PRICE_EUROS_COMPONENT_MAX = 32767
ELECTRICITY_PRICE_MAX = (
    ELECTRICITY_PRICE_EUROS_COMPONENT_MAX + PRICE_CENTS_COMPONENT_MAX / 100.0
)
WATER_PRICE_MAX = WATER_PRICE_EUROS_COMPONENT_MAX + PRICE_CENTS_COMPONENT_MAX / 100.0
PRICE_EUROS_COMPONENT_MAX_BY_ID = {
    ID_ELECTRICITY_PRICE_EUROS: ELECTRICITY_PRICE_EUROS_COMPONENT_MAX,
    ID_WATER_PRICE_EUROS: WATER_PRICE_EUROS_COMPONENT_MAX,
}
CO2_EMISSION_RAW_MAX = 32767
CO2_EMISSION_MAX = CO2_EMISSION_RAW_MAX / 1000.0
PRICE_COMPONENT_IDS = {
    ID_ELECTRICITY_PRICE_EUROS: (
        ID_ELECTRICITY_PRICE,
        ID_ELECTRICITY_PRICE_EUROS,
        ID_ELECTRICITY_PRICE_CENTS,
    ),
    ID_ELECTRICITY_PRICE_CENTS: (
        ID_ELECTRICITY_PRICE,
        ID_ELECTRICITY_PRICE_EUROS,
        ID_ELECTRICITY_PRICE_CENTS,
    ),
    ID_WATER_PRICE_EUROS: (ID_WATER_PRICE, ID_WATER_PRICE_EUROS, ID_WATER_PRICE_CENTS),
    ID_WATER_PRICE_CENTS: (ID_WATER_PRICE, ID_WATER_PRICE_EUROS, ID_WATER_PRICE_CENTS),
}
# DHE memory button payloads encode 38 C as 10620 and 41 C as 10650.
TEMPERATURE_MEMORY_BUTTON_ADDR = 10
TEMPERATURE_MEMORY_MAX_SLOTS = 12
DEFAULT_NEW_TEMPERATURE_MEMORY_C = 40.0
TEMPERATURE_MEMORY_SLOT_IDS = {
    slot: slot - 1 for slot in range(1, TEMPERATURE_MEMORY_MAX_SLOTS + 1)
}
TEMPERATURE_MEMORY_SLOT_MEASUREMENTS = {
    1: ID_TEMPERATURE_MEMORY_1,
    2: ID_TEMPERATURE_MEMORY_2,
    3: ID_TEMPERATURE_MEMORY_3,
    4: ID_TEMPERATURE_MEMORY_4,
    5: ID_TEMPERATURE_MEMORY_5,
    6: ID_TEMPERATURE_MEMORY_6,
    7: ID_TEMPERATURE_MEMORY_7,
    8: ID_TEMPERATURE_MEMORY_8,
    9: ID_TEMPERATURE_MEMORY_9,
    10: ID_TEMPERATURE_MEMORY_10,
    11: ID_TEMPERATURE_MEMORY_11,
    12: ID_TEMPERATURE_MEMORY_12,
}
TEMPERATURE_MEMORY_ID_TO_MEASUREMENT = {
    memory_id: TEMPERATURE_MEMORY_SLOT_MEASUREMENTS[slot]
    for slot, memory_id in TEMPERATURE_MEMORY_SLOT_IDS.items()
}
DEFAULT_TEMPERATURE_MEMORY_NAMES = {
    memory_id: f"%1 {slot}" for slot, memory_id in TEMPERATURE_MEMORY_SLOT_IDS.items()
}
INITIAL_VALUE_IDS = (
    ID_SETPOINT,
    ID_BATH_FILL_ACTIVE,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_CHILD_SAFETY_ACTIVE,
    ID_WELLNESS_SHOWER_PROGRAM,
    ID_CHILD_SAFETY_TEMPERATURE_LIMIT,
    ID_ECO_MODE,
    ID_ECO_FLOW_LIMIT,
    ID_WELLNESS_ACTIVE,
    ID_INLET_TEMPERATURE,
    ID_OUTLET_TEMPERATURE,
    ID_WATER_FLOW,
    ID_POWER_PERCENT,
    ID_OPERATING_DURATION,
    ID_NOMINAL_POWER,
    ID_SCALD_PROTECTION_ACTIVE,
    ID_SCALD_PROTECTION_TEMPERATURE_LIMIT,
    ID_HEATING_ENERGY_TOTAL,
    ID_HOT_WATER_VOLUME_TOTAL,
    ID_BATH_FILL_CURRENT_VOLUME,
    ID_WATER_HEATING_ENABLED,
    ID_DEVICE_STATUS,
    ID_ELECTRICITY_PRICE_EUROS,
    ID_ELECTRICITY_PRICE_CENTS,
    ID_WATER_PRICE_EUROS,
    ID_WATER_PRICE_CENTS,
    ID_POSSIBLE_ENERGY_SAVING,
    ID_POSSIBLE_WATER_SAVING,
    ID_PROTOCOL_VERSION,
    ID_CO2_EMISSION_RAW,
)
WRITABLE_OPTION_IDS = {
    ID_BATH_FILL_ACTIVE,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_CHILD_SAFETY_ACTIVE,
    ID_WELLNESS_SHOWER_PROGRAM,
    ID_CHILD_SAFETY_TEMPERATURE_LIMIT,
    ID_ECO_MODE,
    ID_ECO_FLOW_LIMIT,
    ID_WELLNESS_ACTIVE,
}
KNOWN_ODB_VALUE_IDS = (
    *INITIAL_VALUE_IDS,
    *WRITABLE_OPTION_IDS,
    *PRICE_COMPONENT_IDS,
    ID_SETPOINT_REQUEST,
    ID_BATH_FILL_CURRENT_VOLUME,
    ID_WELLNESS_TIME_NORMALIZED,
    ID_CURRENCY_MODE,
)

BRUSH_TIMER_PATH = "ste.app.brushTimer"
SHOWER_TIMER_PATH = "ste.app.showerTimer"
TIMER_PATH_IDS = {
    BRUSH_TIMER_PATH: {
        "activation": ID_BRUSH_TIMER_ACTIVATION,
        "durationMilliseconds": ID_BRUSH_TIMER_DURATION,
        "remainingMilliseconds": ID_BRUSH_TIMER_REMAINING,
    },
    SHOWER_TIMER_PATH: {
        "activation": ID_SHOWER_TIMER_ACTIVATION,
        "durationMilliseconds": ID_SHOWER_TIMER_DURATION,
        "remainingMilliseconds": ID_SHOWER_TIMER_REMAINING,
    },
}
APP_TIMER_SET_COMMANDS = {
    f"set:{path}:{property_name}"
    for path, property_ids in TIMER_PATH_IDS.items()
    for property_name in property_ids
}
APP_TIMER_ASSIGN_COMMANDS = {
    f"assign:{path}:{property_name}"
    for path, property_ids in TIMER_PATH_IDS.items()
    for property_name in property_ids
    if property_name != "remainingMilliseconds"
}
APP_TIMER_VALUE_COMMANDS = APP_TIMER_SET_COMMANDS | APP_TIMER_ASSIGN_COMMANDS
APP_TIMER_RESET_COMMANDS = {
    f"{action}:{path}:reset"
    for action in ("set", "assign")
    for path in TIMER_PATH_IDS
}
APP_TIMER_REQUEST_COMMANDS = tuple(
    f"get:{path}:{property_name}"
    for path, property_ids in TIMER_PATH_IDS.items()
    for property_name in property_ids
)
RADIO_PATH = "ste.app.radio"
RADIO_STATE_FIELDS = (
    "station",
    "volume",
    "play",
    "paired",
    "title",
)
RADIO_CATALOG_FIELDS = {"city", "country", "genre"}
RADIO_STATION_SEARCH_FIELDS = {*RADIO_CATALOG_FIELDS, "text"}
RADIO_STATIONS_GET_COMMAND = f"get:{RADIO_PATH}:stations"
RADIO_FAVORITES_GET_COMMAND = f"get:{RADIO_PATH}:favorites"
RADIO_CITY_GET_COMMAND = f"get:{RADIO_PATH}:city"
RADIO_COUNTRY_GET_COMMAND = f"get:{RADIO_PATH}:country"
RADIO_GENRE_GET_COMMAND = f"get:{RADIO_PATH}:genre"
RADIO_STATIONS_SET_COMMAND = f"set:{RADIO_PATH}:stations"
RADIO_FAVORITES_SET_COMMAND = f"set:{RADIO_PATH}:favorites"
RADIO_CITY_SET_COMMAND = f"set:{RADIO_PATH}:city"
RADIO_COUNTRY_SET_COMMAND = f"set:{RADIO_PATH}:country"
RADIO_GENRE_SET_COMMAND = f"set:{RADIO_PATH}:genre"
RADIO_CATALOG_GET_COMMANDS = {
    "city": RADIO_CITY_GET_COMMAND,
    "country": RADIO_COUNTRY_GET_COMMAND,
    "genre": RADIO_GENRE_GET_COMMAND,
}
RADIO_CATALOG_SET_COMMANDS = {
    "city": RADIO_CITY_SET_COMMAND,
    "country": RADIO_COUNTRY_SET_COMMAND,
    "genre": RADIO_GENRE_SET_COMMAND,
}
RADIO_FAVORITE_ASSIGN_COMMAND = f"assign:{RADIO_PATH}:favorite"
RADIO_STATION_ASSIGN_COMMAND = f"assign:{RADIO_PATH}:station"
RADIO_REQUEST_COMMANDS = (
    *(f"get:{RADIO_PATH}:{field}" for field in RADIO_STATE_FIELDS),
    RADIO_FAVORITES_GET_COMMAND,
)
RADIO_KNOWN_REQUEST_COMMANDS = {
    *RADIO_REQUEST_COMMANDS,
    RADIO_STATIONS_GET_COMMAND,
    RADIO_FAVORITES_GET_COMMAND,
    RADIO_CITY_GET_COMMAND,
    RADIO_COUNTRY_GET_COMMAND,
    RADIO_GENRE_GET_COMMAND,
}
RADIO_SET_COMMANDS = (
    {f"set:{RADIO_PATH}:{field}" for field in RADIO_STATE_FIELDS}
    | set(RADIO_CATALOG_SET_COMMANDS.values())
)
RADIO_ASSIGN_COMMANDS = {
    f"assign:{RADIO_PATH}:volume",
    f"assign:{RADIO_PATH}:play",
    f"assign:{RADIO_PATH}:paired",
    RADIO_FAVORITE_ASSIGN_COMMAND,
    RADIO_STATION_ASSIGN_COMMAND,
}
WEATHER_PATH = "ste.app.weather"
WEATHER_LOCATION_GET_COMMAND = f"get:{WEATHER_PATH}:location"
WEATHER_FAVORITES_GET_COMMAND = f"get:{WEATHER_PATH}:favorites"
WEATHER_COUNTRIES_GET_COMMAND = f"get:{WEATHER_PATH}:countries"
WEATHER_COUNTRY_GET_COMMAND = f"get:{WEATHER_PATH}:country"
WEATHER_FORECAST_GET_COMMAND = f"get:{WEATHER_PATH}:forecast"
WEATHER_LOCATION_SET_COMMAND = f"set:{WEATHER_PATH}:location"
WEATHER_FAVORITES_SET_COMMAND = f"set:{WEATHER_PATH}:favorites"
WEATHER_COUNTRIES_SET_COMMAND = f"set:{WEATHER_PATH}:countries"
WEATHER_COUNTRY_SET_COMMAND = f"set:{WEATHER_PATH}:country"
WEATHER_FORECAST_SET_COMMAND = f"set:{WEATHER_PATH}:forecast"
WEATHER_FAVORITE_ASSIGN_COMMAND = f"assign:{WEATHER_PATH}:favorite"
WEATHER_REQUEST_COMMANDS = (
    WEATHER_LOCATION_GET_COMMAND,
    WEATHER_FAVORITES_GET_COMMAND,
    WEATHER_COUNTRY_GET_COMMAND,
)
WEATHER_SET_COMMANDS = {
    WEATHER_LOCATION_SET_COMMAND,
    WEATHER_FAVORITES_SET_COMMAND,
    WEATHER_COUNTRIES_SET_COMMAND,
    WEATHER_COUNTRY_SET_COMMAND,
    WEATHER_FORECAST_SET_COMMAND,
}
WEATHER_ASSIGN_COMMANDS = {WEATHER_FAVORITE_ASSIGN_COMMAND}
CONSUMPTION_COMMAND_IDS = {
    "set:ste.app.consumption:waterWeek": ID_WATER_CONSUMPTION_WEEK,
    "set:ste.app.consumption:waterYear": ID_WATER_CONSUMPTION_YEAR,
    "set:ste.app.consumption:waterYears": ID_WATER_CONSUMPTION_YEARS,
    "set:ste.app.consumption:energyWeek": ID_ENERGY_CONSUMPTION_WEEK,
    "set:ste.app.consumption:energyYear": ID_ENERGY_CONSUMPTION_YEAR,
    "set:ste.app.consumption:energyYears": ID_ENERGY_CONSUMPTION_YEARS,
}
CONSUMPTION_REQUEST_COMMANDS = tuple(
    command.replace("set:", "get:", 1) for command in CONSUMPTION_COMMAND_IDS
)
LAST_USAGE_SET_COMMAND = "set:ste.app.consumption:lastUsage"
LAST_USAGE_GET_COMMAND = "get:ste.app.consumption:lastUsage"
SAVING_MONITOR_SET_COMMANDS = (
    "set:ste.app.savingMonitor:ActivationRate",
    "set:ste.app.savingMonitor:possible",
    "set:ste.app.savingMonitor:real",
    "set:ste.app.savingMonitor:consumption",
)
SAVING_MONITOR_COMMAND_IDS = set(SAVING_MONITOR_SET_COMMANDS)
SAVING_MONITOR_REQUEST_COMMANDS = tuple(
    command.replace("set:", "get:", 1) for command in SAVING_MONITOR_SET_COMMANDS
)
SAVING_MONITOR_SENSOR_FIELDS = {
    "consumption": {
        "water_l": ID_SAVING_MONITOR_WATER,
        "energy_kwh": ID_SAVING_MONITOR_ENERGY,
        "co2_kg": ID_SAVING_MONITOR_CO2,
    },
    "possible": {
        "water_l": ID_SAVING_MONITOR_POSSIBLE_WATER,
        "energy_kwh": ID_SAVING_MONITOR_POSSIBLE_ENERGY,
        "co2_kg": ID_SAVING_MONITOR_POSSIBLE_CO2,
        "value_eur": ID_SAVING_MONITOR_POSSIBLE_VALUE,
    },
    "real": {
        "water_l": ID_SAVING_MONITOR_REAL_WATER,
        "energy_kwh": ID_SAVING_MONITOR_REAL_ENERGY,
        "co2_kg": ID_SAVING_MONITOR_REAL_CO2,
        "value_eur": ID_SAVING_MONITOR_REAL_VALUE,
    },
}
DEVICE_INFO_SET_COMMANDS = (
    "set:ste.common.version:contactData",
    "set:ste.common.version:orderNumber",
    "set:ste.common.version:gadgetData",
    "set:ste.common.version:gadgetDataValid",
    "set:ste.common.version:controlunitName",
)
DEVICE_INFO_COMMAND_IDS = set(DEVICE_INFO_SET_COMMANDS)
DEVICE_INFO_REQUEST_COMMANDS = tuple(
    command.replace("set:", "get:", 1) for command in DEVICE_INFO_SET_COMMANDS
)
APP_SETTING_SET_COMMAND_IDS: dict[str, int] = {}
APP_SETTING_REQUEST_COMMANDS = tuple(
    command.replace("set:", "get:", 1) for command in APP_SETTING_SET_COMMAND_IDS
)
APP_STARTUP_REQUEST_COMMANDS = (
    *APP_SETTING_REQUEST_COMMANDS,
    *RADIO_REQUEST_COMMANDS,
    *WEATHER_REQUEST_COMMANDS,
    LAST_USAGE_GET_COMMAND,
    "get:ste.app.wellness:programs",
    *SAVING_MONITOR_REQUEST_COMMANDS,
    *DEVICE_INFO_REQUEST_COMMANDS,
)
APP_STARTUP_SET_COMMANDS = {
    command.replace("get:", "set:", 1) for command in APP_STARTUP_REQUEST_COMMANDS
}
OPTIONAL_STARTUP_APP_REQUEST_COMMANDS = (
    TEMP_MEMORY_GET_COMMAND,
    *APP_STARTUP_REQUEST_COMMANDS,
)
OPTIONAL_STARTUP_ODB_IDS: tuple[int, ...] = ()


ODBValue = bool | float
MeasurementValue = bool | float | str | None
SetpointCallback = Callable[[float], None]
AvailabilityCallback = Callable[[bool], None]
OnlineCallback = Callable[[bool], None]
MeasurementCallback = Callable[[int, MeasurementValue], None]
ReconnectCallback = Callable[[int], None]
RadioCallback = Callable[[dict[str, Any]], None]
WeatherCallback = Callable[[dict[str, Any]], None]
DiagnosticCallback = Callable[[dict[str, Any]], None]
CallbackRemover = Callable[[], None]


class DHEError(Exception):
    """Base DHE exception."""


class DHESessionClosed(DHEError):
    """DHE closed the Socket.IO namespace/session."""


@dataclass
class DHEEvent:
    """Parsed Socket.IO event."""

    name: str
    data: Any


@dataclass
class DHESession:
    """Open Engine.IO/Socket.IO session context."""

    sid: str
    url_token: str
    websocket_sid: str | None = None
    ping_interval: float = DEFAULT_ENGINEIO_PING_INTERVAL_SECONDS
    websocket: Any | None = None
    websocket_ping_task: asyncio.Task[None] | None = None


def _round_to_half_c(value: float) -> float:
    return round(value * 2.0) / 2.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _c_to_raw_tenths(value: float) -> int:
    return int(round(value * 10.0))


def _raw_tenths_to_c(value: int | float) -> float:
    return float(value) / 10.0


def _raw_to_float(value: Any) -> float:
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    return float(value)


def _build_req66(temp_c: float, addr: int) -> int:
    raw = _c_to_raw_tenths(temp_c) & 1023
    return int(raw | ((addr & 0xFF) << 10))


def _build_temperature_memory_button_value(temp_c: float) -> int:
    return _build_req66(temp_c, TEMPERATURE_MEMORY_BUTTON_ADDR)


def _raw_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "on", "yes"}:
            return True
        if lowered in {"false", "off", "no", ""}:
            return False
    return bool(int(_raw_to_float(value)))


def _raw_to_water_heating_enabled(value: Any) -> bool:
    """Decode ODB id 33 value to water-heating enabled state."""
    return int(_raw_to_float(value)) == WATER_HEATING_ON_RAW


def _water_heating_enabled_to_raw(enabled: bool) -> int:
    """Encode water-heating enabled state to ODB id 33 value."""
    return WATER_HEATING_ON_RAW if enabled else WATER_HEATING_OFF_RAW


def _values_equal(a: ODBValue | None, b: ODBValue | None) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    return abs(float(a) - float(b)) < 0.001


def _summarize_radio_value(value: Any) -> Any:
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return {
                "count": len(value),
                "stations": [
                    {
                        "Id": item.get("Id"),
                        "Name": item.get("Name"),
                        "City": item.get("City"),
                    }
                    for item in value[:10]
                ],
            }
        return {
            "count": len(value),
            "sample": value[:10],
        }
    if isinstance(value, dict):
        if "station" in value or "favorites" in value:
            return {
                key: _summarize_radio_value(item)
                for key, item in value.items()
            }
        if "Id" in value or "Name" in value or "StreamUrls" in value:
            return {
                "Id": value.get("Id"),
                "Name": value.get("Name"),
                "City": value.get("City"),
                "Country": value.get("Country"),
                "Genres": value.get("Genres"),
                "Logo44Url": value.get("Logo44Url"),
            }
        return {
            key: _summarize_radio_value(item)
            for key, item in value.items()
        }
    return value


def _summarize_weather_location(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in ("Name", "Country", "CountryId", "LocationId", "SearchType")
        if value.get(key) not in (None, "")
    }


def _summarize_weather_value(value: Any) -> Any:
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return {
                "count": len(value),
                "items": [
                    _summarize_weather_location(item)
                    for item in value[:10]
                ],
            }
        return {
            "count": len(value),
            "sample": value[:10],
        }
    if isinstance(value, dict):
        if "Location" in value or "CompleteDays" in value or "SimpleDays" in value:
            summary: dict[str, Any] = {}
            location = value.get("Location")
            if isinstance(location, dict):
                summary["location"] = _summarize_weather_location(location)
            for key in ("CompleteDays", "SimpleDays"):
                days = value.get(key)
                if isinstance(days, list):
                    summary[key[:1].lower() + key[1:]] = {
                        "count": len(days),
                        "dates": [
                            day.get("date")
                            for day in days[:10]
                            if isinstance(day, dict) and day.get("date")
                        ],
                    }
            return summary
        if "Country" in value or "LocationId" in value:
            return _summarize_weather_location(value)
        return {
            key: _summarize_weather_value(item)
            for key, item in value.items()
        }
    return value


def _diagnostic_error(error: BaseException) -> str:
    message = str(error)
    reason = type(error).__name__ if not message else f"{type(error).__name__}: {message}"
    return reason[:240]


def _diagnostic_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _summarize_diagnostic_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, dict):
        keys = list(value)[:8]
        summary = {
            str(key): _summarize_diagnostic_value(value[key], depth=depth + 1)
            for key in keys
        }
        if len(value) > len(keys):
            summary["_omitted_keys"] = len(value) - len(keys)
        return summary
    if isinstance(value, list):
        return {
            "type": "list",
            "count": len(value),
            "sample": [
                _summarize_diagnostic_value(item, depth=depth + 1)
                for item in value[:3]
            ],
        }
    if isinstance(value, str) and len(value) > 120:
        return f"{value[:117]}..."
    return value


def _host_for_url(host: str) -> str:
    """Return host part suitable for URL construction (wrap IPv6 in brackets)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        return f"[{host}]"
    return host


class DHEClient:
    """Persistent Engine.IO v3 WebSocket client for DHE Connect."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, token_file: str, name: str) -> None:
        self.hass = hass
        normalized_host = host.strip().removeprefix("http://").removeprefix("https://").rstrip("/")
        if normalized_host.startswith("[") and normalized_host.endswith("]"):
            normalized_host = normalized_host[1:-1].strip()
        self.host = normalized_host
        self._url_host = _host_for_url(self.host)
        self.port = int(port)
        self.name = name
        self.legacy_device_identifier: str | None = None
        self.base_url = f"http://{self._url_host}:{self.port}"
        self.token_path = token_file if os.path.isabs(token_file) else hass.config.path(token_file)
        self._session = async_get_clientsession(hass)
        self._ctx: DHESession | None = None
        self._token: str | None = None
        self._runner: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._ready = asyncio.Event()
        self._command_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._setpoint_callbacks: set[SetpointCallback] = set()
        self._availability_callbacks: set[AvailabilityCallback] = set()
        self._online_callbacks: set[OnlineCallback] = set()
        self._measurement_callbacks: set[MeasurementCallback] = set()
        self._reconnect_callbacks: set[ReconnectCallback] = set()
        self._radio_callbacks: set[RadioCallback] = set()
        self._weather_callbacks: set[WeatherCallback] = set()
        self._diagnostic_callbacks: set[DiagnosticCallback] = set()
        self._available = False
        self._online = False
        self._has_connected = False
        self._reconnect_count = 0
        self._last_message_monotonic: float | None = None
        self._message_count = 0
        self._diagnostic_state: dict[str, Any] = {"connection_state": "starting"}
        self._availability_drop_task: asyncio.Task[None] | None = None
        self._last_setpoint: float | None = None
        self._last_measurements: dict[int, MeasurementValue] = {}
        self._last_measurement_attributes: dict[int, dict[str, Any]] = {}
        self._last_app_values: dict[str, Any] = {}
        self._last_radio_state: dict[str, Any] = {}
        self._last_radio_stations: list[dict[str, Any]] = []
        self._last_radio_favorites: list[dict[str, Any]] = []
        self._last_radio_catalogs: dict[str, list[str]] = {
            field: [] for field in RADIO_CATALOG_FIELDS
        }
        self._last_radio_genres: list[str] = []
        self._radio_catalog_generations: dict[str, int] = {
            field: 0 for field in RADIO_CATALOG_FIELDS
        }
        self._radio_stations_generation = 0
        self._radio_favorites_generation = 0
        self._radio_genres_generation = 0
        self._last_weather_state: dict[str, Any] = {}
        self._weather_search_generation = 0
        self._weather_favorites_generation = 0
        self._weather_countries_generation = 0
        self._last_weather_countries: list[dict[str, Any]] = []
        self._last_saving_monitor_values: dict[str, Any] = {}
        self._last_device_info: dict[str, Any] = {}
        self._temperature_memory_ids_seen: set[int] = set()
        self._temperature_memory_generation = 0
        self._temperature_memory_full_list_seen = False
        self._nominal_power_kw = DEFAULT_NOMINAL_POWER_KW
        self._last_power_fraction: float | None = None
        self._pairing_active = False
        self._require_pairing_confirmation = False
        self._pairing_request_seen = False
        self._pairing_confirmed_success = False
        self._pairing_failed_explicit = False
        self._manual_pairing_requested = False
        self._pause_auto_reconnect_for_pairing = False
        self._pairing_retry_attempts = 0
        self._pending_setpoint_future: asyncio.Future[float] | None = None
        self._pending_expected_setpoint: float | None = None
        self._pending_write_future: asyncio.Future[ODBValue] | None = None
        self._pending_write_id: int | None = None
        self._pending_write_expected: ODBValue | None = None
        self._socketio_message_id = random.randint(1, 99)

    @property
    def last_setpoint(self) -> float | None:
        return self._last_setpoint

    @property
    def available(self) -> bool:
        return self._available

    @property
    def online(self) -> bool:
        return self._online

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def last_measurements(self) -> dict[int, MeasurementValue]:
        return dict(self._last_measurements)

    @property
    def last_measurement_attributes(self) -> dict[int, dict[str, Any]]:
        return {
            key: {
                attr_key: list(attr_value) if isinstance(attr_value, list) else attr_value
                for attr_key, attr_value in value.items()
            }
            for key, value in self._last_measurement_attributes.items()
        }

    @property
    def last_app_values(self) -> dict[str, Any]:
        return dict(self._last_app_values)

    @property
    def last_radio_state(self) -> dict[str, Any]:
        return self._copy_radio_state()

    @property
    def last_weather_state(self) -> dict[str, Any]:
        return self._copy_weather_state()

    @property
    def diagnostic_state(self) -> dict[str, Any]:
        return self._copy_diagnostic_state()

    def add_setpoint_callback(self, callback: SetpointCallback) -> CallbackRemover:
        remove = self._add_callback(self._setpoint_callbacks, callback)
        if self._last_setpoint is not None:
            try:
                callback(self._last_setpoint)
            except Exception:  # noqa: BLE001
                pass
        return remove

    def add_availability_callback(self, callback: AvailabilityCallback) -> CallbackRemover:
        remove = self._add_callback(self._availability_callbacks, callback)
        try:
            callback(self._available)
        except Exception:  # noqa: BLE001
            pass
        return remove

    def add_online_callback(self, callback: OnlineCallback) -> CallbackRemover:
        remove = self._add_callback(self._online_callbacks, callback)
        try:
            callback(self._online)
        except Exception:  # noqa: BLE001
            pass
        return remove

    def add_measurement_callback(self, callback: MeasurementCallback) -> CallbackRemover:
        remove = self._add_callback(self._measurement_callbacks, callback)
        for odb_id, value in self._last_measurements.items():
            try:
                callback(odb_id, value)
            except Exception:  # noqa: BLE001
                pass
        if self._temperature_memory_full_list_seen:
            for measurement_id in TEMPERATURE_MEMORY_SLOT_MEASUREMENTS.values():
                if measurement_id in self._last_measurements:
                    continue
                try:
                    callback(measurement_id, None)
                except Exception:  # noqa: BLE001
                    pass
        return remove

    def add_reconnect_callback(self, callback: ReconnectCallback) -> CallbackRemover:
        remove = self._add_callback(self._reconnect_callbacks, callback)
        try:
            callback(self._reconnect_count)
        except Exception:  # noqa: BLE001
            pass
        return remove

    def add_radio_callback(self, callback: RadioCallback) -> CallbackRemover:
        remove = self._add_callback(self._radio_callbacks, callback)
        try:
            callback(self._copy_radio_state())
        except Exception:  # noqa: BLE001
            pass
        return remove

    def add_weather_callback(self, callback: WeatherCallback) -> CallbackRemover:
        remove = self._add_callback(self._weather_callbacks, callback)
        try:
            callback(self._copy_weather_state())
        except Exception:  # noqa: BLE001
            pass
        return remove

    def add_diagnostic_callback(self, callback: DiagnosticCallback) -> CallbackRemover:
        remove = self._add_callback(self._diagnostic_callbacks, callback)
        try:
            callback(self._copy_diagnostic_state())
        except Exception:  # noqa: BLE001
            pass
        return remove

    @staticmethod
    def _add_callback(callbacks: set[Callable[..., None]], callback: Callable[..., None]) -> CallbackRemover:
        callbacks.add(callback)

        def _remove_callback() -> None:
            callbacks.discard(callback)

        return _remove_callback

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._stopped.clear()
        self._runner = self._create_background_task(
            self._run_loop(),
            "stiebel_dhe_connect_session_loop",
        )

    def _create_background_task(self, coro: Any, name: str) -> asyncio.Task[Any]:
        create_background_task = getattr(self.hass, "async_create_background_task", None)
        if create_background_task is not None:
            return create_background_task(coro, name)
        return self.hass.async_create_task(coro, name=name)

    async def stop(self) -> None:
        self._stopped.set()
        self._update_diagnostics(connection_state="stopping")
        runner = self._runner
        self._runner = None
        if runner:
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
        ctx = self._ctx
        self._ctx = None
        self._ready.clear()
        if ctx is not None:
            await self._close_session(ctx)
        self._set_online(False)
        self._set_available(False, immediate=True)
        self._update_diagnostics(connection_state="stopped")

    async def validate_setup_authentication(self, *, timeout_seconds: float = 180.0) -> None:
        """Run a one-shot pairing/authentication check used during config setup."""
        self._stopped.clear()
        ctx: DHESession | None = None
        try:
            self._begin_manual_pairing(
                "setup_requested",
                "Initial setup pairing started; waiting for DHE confirmation.",
                notify=True,
            )
            await self._clear_token()
            ctx = await asyncio.wait_for(
                self._open_authenticated_session(
                    token_request_timeout_seconds=timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
        finally:
            if ctx is not None:
                try:
                    await self._close_session(ctx)
                except Exception:  # noqa: BLE001
                    pass
            self._ctx = None
            self._ready.clear()
            self._set_online(False)
            self._set_available(False, immediate=True)

    async def repair_pairing(self) -> bool:
        """Discard the local pairing token and start a fresh pairing attempt."""
        async with self._command_lock:
            _LOGGER.info(
                "DHE pairing repair requested. Stored token will be cleared; "
                "confirm pairing on the DHE display when prompted."
            )
            self._begin_manual_pairing(
                "repair_requested",
                "Stored token cleared; waiting for DHE pairing confirmation.",
                notify=True,
            )
            await self._clear_token()
            was_running = self._runner is not None and not self._runner.done()
            if was_running:
                await self.stop()
            await self.start()
        return True

    def _begin_manual_pairing(self, state: str, message: str, *, notify: bool) -> None:
        """Prepare a pairing attempt that must end with an explicit DHE result."""
        self._pairing_active = True
        self._require_pairing_confirmation = True
        self._pairing_request_seen = False
        self._pairing_confirmed_success = False
        self._pairing_failed_explicit = False
        self._manual_pairing_requested = True
        self._pause_auto_reconnect_for_pairing = False
        self._pairing_retry_attempts = 0
        self._record_pairing_progress(
            state,
            message,
            notify=notify,
        )

    async def set_temperature(self, temperature: float) -> float:
        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    addr = random.randint(1, 63)
                    req_value = _build_req66(requested, addr)
                    future = self._new_setpoint_future(requested)
                    await self._post_packet(ctx, self._message_packet({
                        "command": ODB_ASSIGN_COMMAND,
                        "value": {"id": ID_SETPOINT_REQUEST, "value": req_value},
                    }))
                    readback = await self._wait_for_setpoint_confirmation(ctx, future)
                    if abs(readback - requested) < 0.01:
                        return readback
                    raise DHEError(f"readback was {readback:.1f} C, expected {requested:.1f} C")
                except Exception as err:  # noqa: BLE001
                    self._clear_pending_future(None)
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not set DHE setpoint: {err}") from err
        raise DHEError("Could not set DHE setpoint")

    async def set_heating_off(self) -> None:
        """Backward-compatible wrapper for the known DHE sync request."""
        await self._send_set_req_sync()

    async def set_water_heating_enabled(self, enabled: bool) -> bool:
        """Enable or disable water heating via ODB id 33 and sync request."""
        requested = bool(enabled)
        confirmed = bool(
            await self.write_odb_value(
                ID_WATER_HEATING_ENABLED,
                _water_heating_enabled_to_raw(requested),
            )
        )
        await self._send_set_req_sync()
        return confirmed

    async def _send_set_req_sync(self) -> None:
        """Send the observed ID 66 sync request used by the native app."""
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    await self._post_packet(
                        ctx,
                        self._message_packet(
                            {
                                "command": ODB_ASSIGN_COMMAND,
                                "value": {
                                    "id": ID_SETPOINT_REQUEST,
                                    "value": SET_REQ_OFF_VALUE,
                                },
                            }
                        ),
                    )
                    return
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not send DHE set-req sync: {err}") from err
        raise DHEError("Could not send DHE set-req sync")

    async def write_odb_value(self, odb_id: int, value: Any) -> ODBValue:
        expected = self._convert_odb_value(odb_id, value)
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    future = self._new_write_future(odb_id, expected)
                    await self._post_packet(ctx, self._message_packet({
                        "command": ODB_ASSIGN_COMMAND,
                        "value": {"id": int(odb_id), "value": value},
                    }))
                    confirmed = await self._wait_for_write_confirmation(ctx, future, odb_id)
                    if _values_equal(confirmed, expected):
                        return confirmed
                    raise DHEError(f"write confirmation was {confirmed!r}, expected {expected!r}")
                except Exception as err:  # noqa: BLE001
                    self._clear_pending_write_future(None)
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not write DHE ODB id {odb_id}: {err}") from err
        raise DHEError(f"Could not write DHE ODB id {odb_id}")

    async def start_bath_fill(self) -> bool:
        return bool(await self.write_odb_value(ID_BATH_FILL_ACTIVE, True))

    async def stop_bath_fill(self) -> bool:
        return bool(await self.write_odb_value(ID_BATH_FILL_ACTIVE, False))

    async def set_bath_fill_target_volume(self, liters: float) -> float:
        requested = int(round(_clamp(float(liters), 5.0, 200.0)))
        return float(await self.write_odb_value(ID_BATH_FILL_TARGET_VOLUME, requested))

    async def set_child_safety_temperature_limit(self, temperature: float) -> float:
        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))
        return float(
            await self.write_odb_value(
                ID_CHILD_SAFETY_TEMPERATURE_LIMIT,
                _c_to_raw_tenths(requested),
            )
        )

    async def set_child_safety_active(self, enabled: bool) -> bool:
        return bool(await self.write_odb_value(ID_CHILD_SAFETY_ACTIVE, bool(enabled)))

    async def set_eco_mode(self, enabled: bool) -> bool:
        return bool(await self.write_odb_value(ID_ECO_MODE, bool(enabled)))

    async def set_eco_flow_limit(self, liters_per_minute: float) -> float:
        requested_l_min = _round_to_half_c(_clamp(float(liters_per_minute), 4.0, 15.0))
        raw_value = int(round(requested_l_min * 10.0))
        return float(await self.write_odb_value(ID_ECO_FLOW_LIMIT, raw_value))

    async def set_electricity_price(self, euros_per_kwh: float) -> float:
        return await self._set_price(
            euros_per_kwh,
            ID_ELECTRICITY_PRICE_EUROS,
            ID_ELECTRICITY_PRICE_CENTS,
            max_value=ELECTRICITY_PRICE_MAX,
        )

    async def set_water_price(self, euros_per_m3: float) -> float:
        return await self._set_price(
            euros_per_m3,
            ID_WATER_PRICE_EUROS,
            ID_WATER_PRICE_CENTS,
            max_value=WATER_PRICE_MAX,
        )

    async def set_co2_emission(self, kg_per_kwh: float) -> float:
        value = round(_clamp(float(kg_per_kwh), 0.0, CO2_EMISSION_MAX), 3)
        raw_value = self._co2_emission_to_raw(value)
        await self.write_odb_value(ID_CO2_EMISSION_RAW, raw_value)
        return value

    async def set_currency(self, currency: str) -> str:
        requested = str(currency).strip().lower()
        if not requested:
            raise DHEError("Currency must not be empty")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    await self._post_packet(ctx, self._message_packet({
                        "command": CURRENCY_GET_COMMAND,
                        "value": requested,
                    }))
                    self._handle_currency_value(requested, source_command=CURRENCY_GET_COMMAND)
                    return requested.upper()
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not set DHE currency: {err}") from err
        raise DHEError("Could not set DHE currency")

    async def set_radio_play(self, play: bool) -> bool:
        requested = bool(play)
        await self._assign_radio_value("play", requested)
        self._handle_radio_value(f"assign:{RADIO_PATH}:play", requested)
        return requested

    async def set_radio_volume(self, volume_level: float) -> float:
        volume = int(round(_clamp(float(volume_level), 0.0, 1.0) * 100.0))
        await self._assign_radio_value("volume", volume)
        self._handle_radio_value(f"assign:{RADIO_PATH}:volume", volume)
        return volume / 100.0

    async def disconnect_radio_pairing(self) -> bool:
        """Send the DHE radio pairing disconnect action."""
        await self._assign_radio_value("paired", False)
        self._handle_radio_value(f"assign:{RADIO_PATH}:paired", False)
        return True

    async def list_radio_genres(self) -> list[str]:
        """Return the DHE radio genre catalog."""
        return await self.list_radio_catalog("genre")

    async def list_radio_catalog(self, attribute: str) -> list[str]:
        """Return a DHE radio station search catalog."""
        requested_attribute = str(attribute).strip().lower()
        command = RADIO_CATALOG_GET_COMMANDS.get(requested_attribute)
        if command is None:
            raise DHEError(f"Unsupported DHE radio catalog: {attribute}")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    generation = self._radio_catalog_generations[requested_attribute]
                    await self._request_app_value(ctx, command)
                    return await self._wait_for_radio_catalog(
                        requested_attribute,
                        generation,
                    )
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(
                        f"Could not read DHE radio {requested_attribute} catalog: {err}"
                    ) from err
        raise DHEError(f"Could not read DHE radio {requested_attribute} catalog")

    async def search_radio_stations_by_genre(self, genre: str) -> list[dict[str, Any]]:
        """Search radio stations by DHE radio genre path."""
        return await self.search_radio_stations("genre", genre)

    async def search_radio_stations(
        self,
        attribute: str,
        value: str,
        *,
        search_text: str | None = None,
    ) -> list[dict[str, Any]]:
        requested_attribute = str(attribute).strip().lower()
        requested_value = str(value).strip()
        requested_search_text = (
            str(search_text).strip() if search_text is not None else ""
        )
        if requested_attribute not in RADIO_STATION_SEARCH_FIELDS:
            raise DHEError(f"Unsupported DHE radio station search: {attribute}")
        if not requested_value:
            raise DHEError("Radio station search value must not be empty")
        if search_text is not None and not requested_search_text:
            raise DHEError("Radio station search text must not be empty")
        search_payload = {
            "attribute": requested_attribute,
            "value": requested_value,
        }
        if requested_search_text:
            search_payload["text"] = requested_search_text

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    generation = self._radio_stations_generation
                    await self._post_packet(ctx, self._message_packet({
                        "command": RADIO_STATIONS_GET_COMMAND,
                        "value": search_payload,
                    }))
                    return await self._wait_for_radio_stations(generation)
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not search DHE radio stations: {err}") from err
        raise DHEError("Could not search DHE radio stations")

    async def list_radio_favorites(self) -> list[dict[str, Any]]:
        """Return DHE radio favorites."""
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    generation = self._radio_favorites_generation
                    await self._request_app_value(ctx, RADIO_FAVORITES_GET_COMMAND)
                    return await self._wait_for_radio_favorites(generation)
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not read DHE radio favorites: {err}") from err
        raise DHEError("Could not read DHE radio favorites")

    async def add_radio_favorite(
        self,
        station: dict[str, Any] | int | str,
        *,
        select: bool = True,
    ) -> bool:
        """Add a radio station favorite and optionally select it."""
        if isinstance(station, dict):
            station_id = _radio_station_id(station)
        else:
            try:
                station_id = int(station)
            except (TypeError, ValueError) as err:
                raise DHEError("Radio station must include Id") from err
        if station_id is None:
            raise DHEError("Radio station must include Id")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")

                    favorites = self._radio_favorites()
                    favorites_known = bool(favorites)
                    try:
                        favorites_generation = self._radio_favorites_generation
                        await self._request_app_value(ctx, RADIO_FAVORITES_GET_COMMAND)
                        favorites = await self._wait_for_radio_favorites(
                            favorites_generation
                        )
                        favorites_known = True
                    except DHEError:
                        if not favorites_known:
                            raise

                    if not _radio_station_in_list(station_id, favorites):
                        favorites_generation = self._radio_favorites_generation
                        await self._post_packet(ctx, self._message_packet({
                            "command": RADIO_FAVORITE_ASSIGN_COMMAND,
                            "value": station_id,
                        }))
                        try:
                            await self._wait_for_radio_favorites(favorites_generation)
                        except DHEError:
                            await self._request_app_value(ctx, RADIO_FAVORITES_GET_COMMAND)
                            await self._wait_for_radio_favorites(favorites_generation)

                    if select:
                        await self._post_packet(ctx, self._message_packet({
                            "command": RADIO_STATION_ASSIGN_COMMAND,
                            "value": station_id,
                        }))
                        try:
                            await self._wait_for_radio_station(station_id)
                        except DHEError:
                            pass
                    return True
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not add DHE radio favorite: {err}") from err
        raise DHEError("Could not add DHE radio favorite")

    async def remove_radio_favorite(self, station: dict[str, Any] | int | str) -> bool:
        """Remove a radio station favorite."""
        if isinstance(station, dict):
            station_id = _radio_station_id(station)
        else:
            try:
                station_id = int(station)
            except (TypeError, ValueError) as err:
                raise DHEError("Radio station must include Id") from err
        if station_id is None:
            raise DHEError("Radio station must include Id")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")

                    favorites_generation = self._radio_favorites_generation
                    await self._request_app_value(ctx, RADIO_FAVORITES_GET_COMMAND)
                    favorites = await self._wait_for_radio_favorites(
                        favorites_generation
                    )
                    if not _radio_station_in_list(station_id, favorites):
                        return True

                    favorites_generation = self._radio_favorites_generation
                    await self._post_packet(ctx, self._message_packet({
                        "command": RADIO_FAVORITE_ASSIGN_COMMAND,
                        "value": station_id,
                    }))
                    try:
                        favorites = await self._wait_for_radio_favorites(
                            favorites_generation
                        )
                    except DHEError:
                        await self._request_app_value(ctx, RADIO_FAVORITES_GET_COMMAND)
                        favorites = await self._wait_for_radio_favorites(
                            favorites_generation
                        )
                    if _radio_station_in_list(station_id, favorites):
                        raise DHEError("DHE radio favorite did not change")
                    return True
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(
                        f"Could not remove DHE radio favorite: {err}"
                    ) from err
        raise DHEError("Could not remove DHE radio favorite")

    async def select_radio_station(self, station: dict[str, Any] | int | str) -> bool:
        """Select/play a radio station by station payload or station ID."""
        if isinstance(station, dict):
            station_id = _radio_station_id(station)
        else:
            try:
                station_id = int(station)
            except (TypeError, ValueError) as err:
                raise DHEError("Radio station must include Id") from err
        if station_id is None:
            raise DHEError("Radio station must include Id")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    await self._post_packet(ctx, self._message_packet({
                        "command": RADIO_STATION_ASSIGN_COMMAND,
                        "value": station_id,
                    }))
                    try:
                        await self._wait_for_radio_station(station_id)
                    except DHEError:
                        pass
                    return True
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not select DHE radio station: {err}") from err
        raise DHEError("Could not select DHE radio station")

    async def search_weather_locations(
        self,
        name: str,
        country_id: int | float | str,
    ) -> list[dict[str, Any]]:
        requested_name = str(name).strip()
        if not requested_name:
            raise DHEError("Weather location search name must not be empty")
        requested_country_id = int(_raw_to_float(country_id))

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    generation = self._weather_search_generation
                    await self._post_packet(ctx, self._message_packet({
                        "command": WEATHER_FORECAST_GET_COMMAND,
                        "value": {
                            "name": requested_name,
                            "countryId": requested_country_id,
                        },
                    }))
                    return await self._wait_for_weather_search_results(generation)
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not search DHE weather locations: {err}") from err
        raise DHEError("Could not search DHE weather locations")

    async def list_weather_countries(self) -> list[dict[str, Any]]:
        """Return the weather country catalog from the DHE."""
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    generation = self._weather_countries_generation
                    await self._request_app_value(ctx, WEATHER_COUNTRIES_GET_COMMAND)
                    return await self._wait_for_weather_countries(generation)
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not read DHE weather countries: {err}") from err
        raise DHEError("Could not read DHE weather countries")

    async def toggle_weather_favorite(self, location: dict[str, Any]) -> bool:
        if not isinstance(location, dict) or not location.get("LocationId"):
            raise DHEError("Weather favorite location must include LocationId")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    payload = _copy_json_like_value(location)
                    await self._post_packet(ctx, self._message_packet({
                        "command": WEATHER_FAVORITE_ASSIGN_COMMAND,
                        "value": payload,
                    }))
                    await self._request_app_value(ctx, WEATHER_FAVORITES_GET_COMMAND)
                    return True
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not toggle DHE weather favorite: {err}") from err
        raise DHEError("Could not toggle DHE weather favorite")

    async def list_weather_favorites(self) -> list[dict[str, Any]]:
        """Return the weather favorites from the DHE."""
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    favorites_generation = self._weather_favorites_generation
                    await self._request_app_value(ctx, WEATHER_FAVORITES_GET_COMMAND)
                    return await self._wait_for_weather_favorites(favorites_generation)
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not read DHE weather favorites: {err}") from err
        raise DHEError("Could not read DHE weather favorites")

    async def add_weather_favorite(self, location: dict[str, Any]) -> bool:
        """Add a weather favorite without toggling an existing favorite off."""
        if not isinstance(location, dict) or not location.get("LocationId"):
            raise DHEError("Weather favorite location must include LocationId")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    payload = _copy_json_like_value(location)

                    favorites = self._weather_favorites()
                    try:
                        favorites_generation = self._weather_favorites_generation
                        await self._request_app_value(ctx, WEATHER_FAVORITES_GET_COMMAND)
                        favorites = await self._wait_for_weather_favorites(favorites_generation)
                    except DHEError:
                        pass
                    if _weather_location_in_list(payload, favorites):
                        return True

                    location_id = _weather_location_id(payload)
                    favorites_generation = self._weather_favorites_generation
                    await self._post_packet(ctx, self._message_packet({
                        "command": WEATHER_FAVORITE_ASSIGN_COMMAND,
                        "value": payload,
                    }))
                    await self._post_packet(ctx, self._message_packet({
                        "command": WEATHER_LOCATION_GET_COMMAND,
                        "value": location_id,
                    }))
                    await self._wait_for_weather_location(location_id)
                    try:
                        await self._wait_for_weather_favorites(favorites_generation)
                    except DHEError:
                        await self._request_app_value(ctx, WEATHER_FAVORITES_GET_COMMAND)
                        await self._wait_for_weather_favorites(favorites_generation)
                    return True
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not add DHE weather favorite: {err}") from err
        raise DHEError("Could not add DHE weather favorite")

    async def select_weather_location(self, location: dict[str, Any] | str) -> bool:
        if isinstance(location, dict):
            location_id = location.get("LocationId")
        else:
            location_id = location
        requested_location_id = str(location_id or "").strip()
        if not requested_location_id:
            raise DHEError("Weather location must include LocationId")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    await self._post_packet(ctx, self._message_packet({
                        "command": WEATHER_LOCATION_GET_COMMAND,
                        "value": requested_location_id,
                    }))
                    await self._wait_for_weather_location(requested_location_id)
                    return True
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not select DHE weather location: {err}") from err
        raise DHEError("Could not select DHE weather location")

    async def _assign_radio_value(self, field: str, value: Any) -> None:
        command = f"assign:{RADIO_PATH}:{field}"
        if command not in RADIO_ASSIGN_COMMANDS:
            raise DHEError(f"Unsupported DHE radio assignment: {field}")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    await self._post_packet(ctx, self._message_packet({
                        "command": command,
                        "value": value,
                    }))
                    return
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not write DHE radio {field}: {err}") from err
        raise DHEError(f"Could not write DHE radio {field}")

    async def _set_price(
        self,
        value: float,
        euros_odb_id: int,
        cents_odb_id: int,
        *,
        max_value: float,
    ) -> float:
        total_cents = int(round(_clamp(float(value), 0.0, max_value) * 100))
        euros, cents = divmod(total_cents, 100)
        await self.write_odb_value(euros_odb_id, euros)
        await self.write_odb_value(cents_odb_id, cents)
        return total_cents / 100.0

    async def press_temperature_memory(self, memory_slot: int) -> bool:
        try:
            memory_id = TEMPERATURE_MEMORY_SLOT_IDS[int(memory_slot)]
            measurement_id = TEMPERATURE_MEMORY_ID_TO_MEASUREMENT[memory_id]
        except KeyError as err:
            raise DHEError(f"Unsupported temperature memory slot: {memory_slot}") from err

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    temperature = await self._get_temperature_memory_temperature(
                        ctx,
                        memory_slot,
                        measurement_id,
                    )
                    request_value = _build_temperature_memory_button_value(temperature)
                    await self._post_packet(ctx, self._message_packet({
                        "command": ODB_ASSIGN_COMMAND,
                        "value": {"id": ID_SETPOINT_REQUEST, "value": request_value},
                    }))
                    try:
                        await self._request_setpoint(ctx)
                    except Exception:  # noqa: BLE001
                        pass
                    return True
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not press DHE temperature memory {memory_slot}: {err}") from err
        raise DHEError(f"Could not press DHE temperature memory {memory_slot}")

    async def _get_temperature_memory_temperature(
        self,
        ctx: DHESession,
        memory_slot: int,
        measurement_id: int,
    ) -> float:
        temperature = self._cached_temperature_memory_temperature(measurement_id)
        if temperature is not None:
            return temperature

        await self._request_app_value(ctx, TEMP_MEMORY_GET_COMMAND)
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            temperature = self._cached_temperature_memory_temperature(measurement_id)
            if temperature is not None:
                return temperature
            await asyncio.sleep(0.1)
        raise DHEError(f"DHE temperature memory {memory_slot} is not available yet")

    async def _refresh_temperature_memories(self, ctx: DHESession) -> None:
        generation = self._temperature_memory_generation
        await self._request_app_value(ctx, TEMP_MEMORY_GET_COMMAND)
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            if self._temperature_memory_generation != generation:
                return
            await asyncio.sleep(0.1)

    def _cached_temperature_memory_temperature(self, measurement_id: int) -> float | None:
        value = self._last_measurements.get(measurement_id)
        if value is None or isinstance(value, bool):
            return None
        return _round_to_half_c(_clamp(float(value), 20.0, 60.0))

    def _temperature_memory_ids(self, memory_slot: int) -> tuple[int, int]:
        try:
            slot = int(memory_slot)
            memory_id = TEMPERATURE_MEMORY_SLOT_IDS[slot]
            measurement_id = TEMPERATURE_MEMORY_SLOT_MEASUREMENTS[slot]
        except KeyError as err:
            raise DHEError(f"Unsupported temperature memory slot: {memory_slot}") from err
        return memory_id, measurement_id

    def _temperature_memory_exists(self, memory_id: int, measurement_id: int) -> bool:
        return memory_id in self._temperature_memory_ids_seen or measurement_id in self._last_measurements

    def _can_create_temperature_memory(self, memory_id: int) -> bool:
        if len(self._temperature_memory_ids_seen) >= TEMPERATURE_MEMORY_MAX_SLOTS:
            return False
        if not self._temperature_memory_ids_seen:
            return memory_id == 0
        return memory_id == max(self._temperature_memory_ids_seen) + 1

    def _temperature_memory_payload(
        self,
        memory_id: int,
        measurement_id: int,
        name: str,
        temperature: float,
    ) -> dict[str, Any]:
        exists = self._temperature_memory_exists(memory_id, measurement_id)
        if not exists and not self._can_create_temperature_memory(memory_id):
            raise DHEError("Temperature memories must be created in order")

        payload: dict[str, Any] = {
            "name": name,
            "temperature": temperature,
            "operation": "add_change",
        }
        if exists:
            payload["id"] = memory_id
        return payload

    async def set_temperature_memory(self, memory_slot: int, temperature: float) -> float:
        memory_id, measurement_id = self._temperature_memory_ids(memory_slot)

        requested = _round_to_half_c(_clamp(float(temperature), 20.0, 60.0))

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    await self._refresh_temperature_memories(ctx)
                    attributes = self._last_measurement_attributes.get(measurement_id, {})
                    name = str(attributes.get("name", DEFAULT_TEMPERATURE_MEMORY_NAMES[memory_id]))
                    payload = self._temperature_memory_payload(
                        memory_id,
                        measurement_id,
                        name,
                        requested,
                    )
                    await self._post_packet(ctx, self._message_packet({
                        "command": TEMP_MEMORY_ASSIGN_COMMAND,
                        "value": payload,
                    }))
                    if "id" in payload:
                        self._handle_temperature_memory_item(payload, source_command=TEMP_MEMORY_ASSIGN_COMMAND)
                    await self._refresh_temperature_memories(ctx)
                    return self._cached_temperature_memory_temperature(measurement_id) or requested
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not set DHE temperature memory {memory_slot}: {err}") from err
        raise DHEError(f"Could not set DHE temperature memory {memory_slot}")

    async def set_temperature_memory_name(self, memory_slot: int, name: str) -> str:
        memory_id, measurement_id = self._temperature_memory_ids(memory_slot)

        requested_name = str(name).strip()
        if not requested_name:
            raise DHEError(f"DHE temperature memory {memory_slot} name must not be empty")

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    await self._refresh_temperature_memories(ctx)
                    temperature = (
                        self._cached_temperature_memory_temperature(measurement_id)
                        or DEFAULT_NEW_TEMPERATURE_MEMORY_C
                    )
                    payload = self._temperature_memory_payload(
                        memory_id,
                        measurement_id,
                        requested_name,
                        temperature,
                    )
                    await self._post_packet(ctx, self._message_packet({
                        "command": TEMP_MEMORY_ASSIGN_COMMAND,
                        "value": payload,
                    }))
                    if "id" in payload:
                        self._handle_temperature_memory_item(payload, source_command=TEMP_MEMORY_ASSIGN_COMMAND)
                    await self._refresh_temperature_memories(ctx)
                    attributes = self._last_measurement_attributes.get(measurement_id, {})
                    return str(attributes.get("name", requested_name))
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not set DHE temperature memory {memory_slot} name: {err}") from err
        raise DHEError(f"Could not set DHE temperature memory {memory_slot} name")

    async def delete_temperature_memory(self, memory_slot: int) -> bool:
        memory_id, measurement_id = self._temperature_memory_ids(memory_slot)

        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    await self._refresh_temperature_memories(ctx)
                    if not self._temperature_memory_exists(memory_id, measurement_id):
                        raise DHEError(f"DHE temperature memory {memory_slot} is not available")
                    await self._post_packet(ctx, self._message_packet({
                        "command": TEMP_MEMORY_ASSIGN_COMMAND,
                        "value": {
                            "id": memory_id,
                            "operation": "delete",
                        },
                    }))
                    await self._refresh_temperature_memories(ctx)
                    if self._temperature_memory_exists(memory_id, measurement_id):
                        raise DHEError(f"DHE temperature memory {memory_slot} was not deleted")
                    return True
                except Exception as err:  # noqa: BLE001
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not delete DHE temperature memory {memory_slot}: {err}") from err
        raise DHEError(f"Could not delete DHE temperature memory {memory_slot}")

    async def set_wellness_cold_prevention(self, enabled: bool) -> bool:
        if enabled:
            await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, WELLNESS_COLD_PREVENTION_PROGRAM_ID)
            await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
            return True

        await self.write_odb_value(ID_WELLNESS_ACTIVE, False)
        self._handle_measurement(ID_WELLNESS_ACTIVE, False, force_update=True)
        self._handle_measurement(ID_WELLNESS_SHOWER_PROGRAM, 0.0, force_update=True)
        return False

    async def set_wellness_shower_program(self, program_id: int) -> bool:
        await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, int(program_id))
        await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
        return True

    async def stop_wellness_shower_program(self) -> bool:
        await self.write_odb_value(ID_WELLNESS_ACTIVE, False)
        self._handle_measurement(ID_WELLNESS_ACTIVE, False, force_update=True)
        self._handle_measurement(ID_WELLNESS_SHOWER_PROGRAM, 0.0, force_update=True)
        return False

    async def set_brush_timer_duration_minutes(self, minutes: float) -> float:
        return await self._set_app_timer_duration_minutes(
            BRUSH_TIMER_PATH,
            ID_BRUSH_TIMER_DURATION,
            minutes,
        )

    async def set_brush_timer_activation(self, enabled: bool) -> bool:
        return await self._set_app_timer_activation(
            BRUSH_TIMER_PATH,
            ID_BRUSH_TIMER_ACTIVATION,
            enabled,
        )

    async def set_shower_timer_duration_minutes(self, minutes: float) -> float:
        return await self._set_app_timer_duration_minutes(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_DURATION,
            minutes,
        )

    async def set_shower_timer_activation(self, enabled: bool) -> bool:
        return await self._set_app_timer_activation(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_ACTIVATION,
            enabled,
        )

    async def reset_brush_timer(self) -> bool:
        return await self._reset_app_timer(
            BRUSH_TIMER_PATH,
            ID_BRUSH_TIMER_ACTIVATION,
            ID_BRUSH_TIMER_REMAINING,
        )

    async def reset_shower_timer(self) -> bool:
        return await self._reset_app_timer(
            SHOWER_TIMER_PATH,
            ID_SHOWER_TIMER_ACTIVATION,
            ID_SHOWER_TIMER_REMAINING,
        )

    async def run_wellness_shower_program_winter_refresh(self) -> bool:
        """Trigger the wellness shower program 'Winter refresh'."""
        for _ in range(2):
            await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, WINTER_REFRESH_PROGRAM_ID)
            await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
        return True

    async def run_wellness_shower_program_summer_fitness(self) -> bool:
        """Trigger the wellness shower program 'Summer fitness'."""
        for _ in range(2):
            await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, SUMMER_FITNESS_PROGRAM_ID)
            await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
        return True

    async def run_wellness_shower_program_circulation_support(self) -> bool:
        """Trigger the wellness shower program 'Circulation support'."""
        for _ in range(2):
            await self.write_odb_value(ID_WELLNESS_SHOWER_PROGRAM, CIRCULATION_SUPPORT_PROGRAM_ID)
            await self.write_odb_value(ID_WELLNESS_ACTIVE, True)
        return True

    async def _set_app_timer_duration_minutes(
        self,
        path: str,
        measurement_id: int,
        minutes: float,
    ) -> float:
        requested_minutes = _clamp(float(minutes), 1.0, 20.0)
        milliseconds = int(round(requested_minutes * 60000.0))
        confirmed = await self._write_app_value(
            f"assign:{path}:durationMilliseconds",
            milliseconds,
            measurement_id,
            float(requested_minutes),
        )
        return float(confirmed)

    async def _set_app_timer_activation(self, path: str, measurement_id: int, enabled: bool) -> bool:
        confirmed = await self._write_app_value(
            f"assign:{path}:activation",
            bool(enabled),
            measurement_id,
            bool(enabled),
        )
        return bool(confirmed)

    async def _reset_app_timer(self, path: str, activation_id: int, remaining_id: int) -> bool:
        await self._write_app_value(
            f"assign:{path}:reset",
            True,
            remaining_id,
            0.0,
        )
        self._handle_measurement(remaining_id, 0.0, force_update=True)
        self._handle_measurement(activation_id, False, force_update=True)
        return True

    async def _write_app_value(self, command: str, value: Any, measurement_id: int, expected: ODBValue) -> ODBValue:
        async with self._command_lock:
            for attempt in range(2):
                try:
                    await self._ensure_ready(timeout=45)
                    ctx = self._ctx
                    if ctx is None:
                        raise DHEError("DHE session is not connected")
                    future = self._new_write_future(measurement_id, expected)
                    await self._post_packet(ctx, self._message_packet({"command": command, "value": value}))
                    try:
                        return await self._wait_for_app_write_confirmation(future)
                    except TimeoutError as err:
                        self._clear_pending_write_future(None)
                        raise DHEError(
                            f"No DHE app confirmation for {command} within "
                            f"{APP_COMMAND_CONFIRMATION_TIMEOUT:.1f}s"
                        ) from err
                except Exception as err:  # noqa: BLE001
                    self._clear_pending_write_future(None)
                    if attempt == 0:
                        await self._force_reconnect(reason=_diagnostic_error(err))
                        await asyncio.sleep(1)
                        continue
                    raise DHEError(f"Could not write DHE app command {command}: {err}") from err
        raise DHEError(f"Could not write DHE app command {command}")

    async def _run_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                self._ctx = await self._open_authenticated_session()
                self._record_session_connected()
                self._update_diagnostics(
                    connection_state="connected",
                    ping_interval_seconds=self._ctx.ping_interval,
                    session_id=self._ctx.sid,
                    websocket_sid=self._ctx.websocket_sid,
                )
                self._set_online(True)
                self._ready.set()
                self._set_available(True)
                await self._request_initial_values(self._ctx)
                while not self._stopped.is_set() and self._ctx is not None:
                    for event in await self._read_events_once(self._ctx):
                        await self._handle_runtime_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                self._update_diagnostics(
                    connection_state="reconnecting",
                    last_reconnect_reason=_diagnostic_error(err),
                )
                self._clear_pending_future(err)
                self._clear_pending_write_future(err)
                self._ready.clear()
                self._set_online(False)
                self._set_available(False)
                ctx = self._ctx
                self._ctx = None
                if ctx is not None:
                    await self._close_session(ctx)
                if self._pause_auto_reconnect_for_pairing:
                    self._update_diagnostics(
                        connection_state="pairing_failed_waiting_manual_retry",
                        last_reconnect_reason=(
                            "Pairing failed; waiting for manual retry via "
                            "'Pairing erneuern'."
                        ),
                    )
                    await self._stopped.wait()
                    return
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=10)
                except TimeoutError:
                    pass

    async def _open_authenticated_session(
        self,
        *,
        token_request_timeout_seconds: float = 120.0,
    ) -> DHESession:
        token = await self._load_token()
        if self._require_pairing_confirmation and token:
            _LOGGER.warning(
                "Pairing confirmation is required; ignoring existing token and "
                "requesting a fresh one."
            )
            token = ""
        if not token:
            _LOGGER.info("No stored DHE token. Requesting new token; confirm pairing on DHE if prompted.")
            self._pairing_active = True
            self._require_pairing_confirmation = True
            self._pairing_request_seen = False
            self._pairing_confirmed_success = False
            self._pairing_failed_explicit = False
            self._record_pairing_progress(
                "requesting_token",
                "No stored DHE token; requesting a new pairing token.",
                notify=True,
            )
            token = await self._request_initial_token(
                timeout_seconds=token_request_timeout_seconds,
            )
            if not token:
                raise DHEError("No token received. Pairing may be required on the DHE.")
        ctx = await self._open_session(token)
        try:
            await self._post_packet(ctx, self._event_packet("token_request", {"token": token, "name": self.name}))
            deadline = time.monotonic() + 120.0
            authenticated_received = False
            while time.monotonic() < deadline and not self._stopped.is_set():
                for event in await self._read_polling_events_once(ctx):
                    if event.name == "__closed":
                        raise DHESessionClosed("DHE closed Socket.IO session during authentication")
                    if event.name == "token_response" and isinstance(event.data, str) and len(event.data) > 20:
                        _LOGGER.debug(
                            "DHE auth event: token_response (pairing_active=%s, require_confirmation=%s, pairing_confirmed=%s)",
                            self._pairing_active,
                            self._require_pairing_confirmation,
                            self._pairing_confirmed_success,
                        )
                        token = event.data
                        await self._save_token(token)
                        if self._pairing_active:
                            self._record_pairing_progress(
                                "token_received",
                                "DHE pairing token received.",
                                notify=True,
                            )
                        await self._post_packet(ctx, self._event_packet("authenticate", {"token": token}))
                    elif event.name == "authenticated":
                        _LOGGER.debug(
                            "DHE auth event: authenticated (pairing_active=%s, require_confirmation=%s, pairing_confirmed=%s)",
                            self._pairing_active,
                            self._require_pairing_confirmation,
                            self._pairing_confirmed_success,
                        )
                        if self._pairing_failed_explicit:
                            raise DHEError("Pairing was rejected on the DHE")
                        if self._pairing_active:
                            if (
                                self._require_pairing_confirmation
                                and not self._pairing_confirmed_success
                            ):
                                authenticated_received = True
                                self._record_pairing_progress(
                                    "authenticated_pending_confirmation",
                                    "Authenticated, waiting for device pairing confirmation.",
                                    notify=True,
                                )
                                continue
                            if (
                                not self._require_pairing_confirmation
                                and not self._pairing_confirmed_success
                            ):
                                self._record_pairing_progress(
                                    "authenticated_without_device_confirmation",
                                    "DHE authentication completed without on-device pairing confirmation request.",
                                    notify=True,
                                )
                                self._pairing_active = False
                                self._pause_auto_reconnect_for_pairing = False
                                await self._upgrade_to_websocket(ctx)
                                return ctx
                            self._record_pairing_progress(
                                "authenticated",
                                "DHE pairing and authentication completed.",
                                notify=True,
                            )
                            self._pairing_active = False
                            self._require_pairing_confirmation = False
                            self._manual_pairing_requested = False
                            self._pause_auto_reconnect_for_pairing = False
                        await self._upgrade_to_websocket(ctx)
                        return ctx
                    elif event.name == "pairing_request":
                        _LOGGER.debug("DHE auth event: pairing_request")
                        self._record_pairing_requested()
                    elif event.name == "pairing_result":
                        _LOGGER.info("DHE auth event: pairing_result=%r", event.data)
                        self._record_pairing_result(event.data)
                if (
                    authenticated_received
                    and self._pairing_active
                    and self._require_pairing_confirmation
                    and self._pairing_confirmed_success
                ):
                    self._record_pairing_progress(
                        "authenticated",
                        "DHE pairing and authentication completed.",
                        notify=True,
                    )
                    self._pairing_active = False
                    self._require_pairing_confirmation = False
                    self._pause_auto_reconnect_for_pairing = False
                    await self._upgrade_to_websocket(ctx)
                    return ctx
                await asyncio.sleep(0.25)
            if authenticated_received and self._require_pairing_confirmation:
                raise DHEError(
                    "Authenticated, but DHE pairing confirmation was not completed in time"
                )
            raise DHEError("Auth timeout: no authenticated event received")
        except asyncio.CancelledError:
            await self._close_session(ctx)
            raise
        except Exception as err:
            if self._pairing_active:
                self._record_pairing_failed(err)
            await self._close_session(ctx)
            raise

    async def _request_initial_token(self, *, timeout_seconds: float = 120.0) -> str:
        ctx = await self._open_session("")
        require_confirmation = self._require_pairing_confirmation
        pairing_confirmed = not require_confirmation
        saw_pairing_request = False
        candidate_token: str | None = None
        manual_auth_sent = False
        manual_websocket_attempted = False
        try:
            _LOGGER.debug(
                "DHE token request started (require_confirmation=%s).",
                require_confirmation,
            )
            await self._post_packet(ctx, self._event_packet("token_request", {"token": "", "name": self.name}))
            token_timeout = max(1.0, float(timeout_seconds))
            deadline = time.monotonic() + token_timeout
            while time.monotonic() < deadline and not self._stopped.is_set():
                try:
                    if ctx.websocket is not None:
                        events = await asyncio.wait_for(
                            self._read_events_once(ctx),
                            timeout=AUTH_POLL_TIMEOUT_SECONDS,
                        )
                    else:
                        events = await self._read_polling_events_once(ctx)
                except TimeoutError:
                    events = []
                for event in events:
                    if event.name == "__closed":
                        raise DHESessionClosed("DHE closed Socket.IO session while requesting token")
                    if event.name == "authenticated":
                        _LOGGER.debug(
                            "DHE event: authenticated while waiting for pairing_result "
                            "(pairing_confirmed=%s).",
                            pairing_confirmed,
                        )
                    if event.name == "pairing_request":
                        _LOGGER.debug("DHE event: pairing_request")
                        saw_pairing_request = True
                        self._record_pairing_requested()
                    if event.name == "pairing_result":
                        _LOGGER.info("DHE event: pairing_result=%r", event.data)
                        self._record_pairing_result(event.data)
                        if require_confirmation:
                            success = _pairing_result_success(event.data)
                            if success is False:
                                raise DHEError("Pairing confirmation rejected on DHE")
                            if success is True:
                                pairing_confirmed = True
                    if event.name == "token_response" and isinstance(event.data, str) and len(event.data) > 20:
                        _LOGGER.debug(
                            "DHE event: token_response (require_confirmation=%s, saw_pairing_request=%s, pairing_confirmed=%s)",
                            require_confirmation,
                            saw_pairing_request,
                            pairing_confirmed,
                        )
                        candidate_token = event.data
                        if not require_confirmation:
                            self._record_pairing_progress(
                                "token_received",
                                "DHE pairing token received.",
                                notify=True,
                            )
                            await self._save_token(candidate_token)
                            return candidate_token
                        if pairing_confirmed:
                            _LOGGER.debug(
                                "Token received after explicit pairing confirmation "
                                "(saw_pairing_request=%s).",
                                saw_pairing_request,
                            )
                            self._record_pairing_progress(
                                "token_received",
                                "DHE pairing token received.",
                                notify=True,
                            )
                            await self._save_token(candidate_token)
                            return candidate_token
                        if not saw_pairing_request:
                            if self._manual_pairing_requested:
                                if not manual_auth_sent:
                                    manual_auth_sent = True
                                    _LOGGER.info(
                                        "Manual pairing token received; authenticating "
                                        "same session while waiting for explicit pairing_result."
                                    )
                                    await self._post_packet(
                                        ctx,
                                        self._event_packet(
                                            "authenticate",
                                            {"token": candidate_token},
                                        ),
                                    )
                                if not manual_websocket_attempted:
                                    manual_websocket_attempted = True
                                    try:
                                        await self._upgrade_to_websocket(ctx)
                                        _LOGGER.debug(
                                            "Manual pairing session upgraded to websocket "
                                            "while waiting for pairing_result."
                                        )
                                    except Exception as err:  # noqa: BLE001
                                        _LOGGER.debug(
                                            "Manual pairing websocket upgrade unavailable; "
                                            "continuing polling while waiting for pairing_result: %s",
                                            _diagnostic_error(err),
                                        )
                                _LOGGER.debug(
                                    "Token received without pairing_request during manual pairing; "
                                    "waiting for explicit pairing_result from DHE."
                                )
                                continue
                            _LOGGER.debug(
                                "Token received without pairing_request; waiting for explicit pairing confirmation events."
                            )
                            continue
                        if not pairing_confirmed:
                            _LOGGER.debug(
                                "Token received, waiting for DHE pairing confirmation."
                            )
                            continue
                        await self._save_token(candidate_token)
                        return candidate_token
                    if (
                        require_confirmation
                        and candidate_token
                        and pairing_confirmed
                    ):
                        _LOGGER.debug(
                            "Pairing confirmed after token_response; proceeding "
                            "(saw_pairing_request=%s).",
                            saw_pairing_request,
                        )
                        self._record_pairing_progress(
                            "token_received",
                            "DHE pairing token received.",
                            notify=True,
                        )
                        await self._save_token(candidate_token)
                        return candidate_token
                await asyncio.sleep(0.3)
            if require_confirmation and candidate_token:
                raise DHEError("Token received but DHE pairing confirmation did not complete in time")
            raise DHEError("Token request timeout")
        except Exception as err:
            self._record_pairing_failed(err)
            raise
        finally:
            await self._close_session(ctx)

    async def _open_session(self, token_for_url: str) -> DHESession:
        open_payload = await self._get_text(self._poll_url(token_for_url, None, None))
        sid_match = re.search(r'"sid":"([^"]+)"', open_payload)
        if not sid_match:
            raise DHEError(f"Could not extract sid from open payload: {open_payload!r}")
        websocket_sid_match = re.search(r'"websocketSid":"([^"]+)"', open_payload)
        ctx = DHESession(
            sid=sid_match.group(1),
            url_token=token_for_url,
            websocket_sid=websocket_sid_match.group(1) if websocket_sid_match else None,
            ping_interval=self._engineio_ping_interval(open_payload),
        )
        await self._post_packet(ctx, f"40/{NS}")
        return ctx

    async def _close_session(self, ctx: DHESession) -> None:
        ping_task = ctx.websocket_ping_task
        ctx.websocket_ping_task = None
        if (
            ping_task is not None
            and ping_task is not asyncio.current_task()
            and not ping_task.done()
        ):
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
        try:
            await self._post_packet(ctx, f"41/{NS}")
        except Exception:  # noqa: BLE001
            pass
        websocket = ctx.websocket
        ctx.websocket = None
        if websocket is not None and not websocket.closed:
            await websocket.close()

    async def _force_reconnect(
        self,
        ctx: DHESession | None = None,
        *,
        immediate_availability: bool = False,
        reason: str | None = None,
    ) -> None:
        if ctx is not None and self._ctx is not ctx:
            await self._close_session(ctx)
            return

        ctx = self._ctx
        self._ctx = None
        self._ready.clear()
        self._set_online(False)
        self._set_available(False, immediate=immediate_availability)
        self._update_diagnostics(
            connection_state="reconnecting",
            last_reconnect_reason=reason or "Forced reconnect requested",
        )
        if ctx is not None:
            await self._close_session(ctx)

    async def _ensure_ready(self, timeout: float) -> None:
        if self._ctx is not None and self._available:
            return
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    def _record_session_connected(self) -> None:
        self._pairing_retry_attempts = 0
        self._pause_auto_reconnect_for_pairing = False
        if not self._has_connected:
            self._has_connected = True
            return

        self._reconnect_count += 1
        for callback in tuple(self._reconnect_callbacks):
            callback(self._reconnect_count)

    async def _handle_runtime_event(self, event: DHEEvent) -> None:
        if event.name == "__closed":
            self._update_diagnostics(
                connection_state="reconnecting",
                last_reconnect_reason="DHE closed Socket.IO session",
            )
            raise DHESessionClosed("DHE closed Socket.IO session")
        if event.name != "message" or not isinstance(event.data, dict):
            return
        data = event.data
        command = data.get("command")
        value = data.get("value")
        self._record_runtime_message(command, value)
        is_radio_command = isinstance(command, str) and RADIO_PATH in command
        if command in APP_TIMER_RESET_COMMANDS:
            self._handle_app_timer_reset(command)
            return
        if command in APP_TIMER_VALUE_COMMANDS:
            self._handle_app_timer_value(command, value)
            return
        if command in RADIO_KNOWN_REQUEST_COMMANDS:
            self._last_app_values[command] = _summarize_radio_value(value)
            return
        if command == RADIO_STATIONS_SET_COMMAND:
            self._handle_radio_stations_value(value)
            return
        if command == RADIO_FAVORITES_SET_COMMAND:
            self._handle_radio_favorites_value(value)
            return
        if command in RADIO_ASSIGN_COMMANDS:
            self._last_app_values[command] = _summarize_radio_value(value)
            return
        if command in RADIO_SET_COMMANDS:
            self._handle_radio_value(command, value)
            return
        if command in WEATHER_SET_COMMANDS:
            self._handle_weather_value(command, value)
            return
        if command in WEATHER_ASSIGN_COMMANDS:
            self._last_app_values[command] = _summarize_weather_value(value)
            return
        if command in CONSUMPTION_COMMAND_IDS:
            self._handle_consumption_value(command, value)
            return
        if command == LAST_USAGE_SET_COMMAND:
            self._handle_last_usage_value(value)
            return
        if command in SAVING_MONITOR_COMMAND_IDS:
            self._handle_saving_monitor_value(command, value)
            return
        if command in {TEMP_MEMORY_SET_COMMAND, TEMP_MEMORY_ASSIGN_COMMAND}:
            self._handle_temperature_memory_value(value, source_command=command)
            return
        if command in DEVICE_INFO_COMMAND_IDS:
            self._handle_device_info_value(command, value)
            return
        if command in {CURRENCY_GET_COMMAND, CURRENCY_SET_COMMAND}:
            self._handle_currency_value(value, source_command=command)
            return
        if command in APP_STARTUP_SET_COMMANDS:
            self._handle_app_startup_value(command, value)
            return
        if is_radio_command:
            _LOGGER.debug(
                "DHE radio unhandled command=%s value_summary=%r",
                command,
                _summarize_radio_value(value),
            )
            return
        if command not in {ODB_SET_COMMAND, ODB_ASSIGN_COMMAND}:
            self._log_unhandled_ste_command(command, value)
            return
        if not isinstance(value, dict):
            self._log_unhandled_ste_command(command, value)
            return
        try:
            odb_id = int(value.get("id", -1))
        except (TypeError, ValueError):
            self._log_unhandled_ste_command(command, value)
            return
        self._handle_odb_value(
            odb_id,
            value.get("value"),
            is_valid=value.get("isValid"),
        )

    def _handle_app_timer_value(self, command: str, raw_value: Any) -> None:
        try:
            _action, path, property_name = command.split(":", 2)
            measurement_id = TIMER_PATH_IDS.get(path, {}).get(property_name)
            if measurement_id is None:
                return
            if property_name == "activation":
                self._handle_measurement(measurement_id, _raw_to_bool(raw_value))
            elif property_name in {"durationMilliseconds", "remainingMilliseconds"}:
                self._handle_measurement(measurement_id, _raw_to_float(raw_value) / 60000.0)
        except (TypeError, ValueError):
            return

    def _handle_app_timer_reset(self, command: str) -> None:
        try:
            _action, path, _property_name = command.split(":", 2)
        except ValueError:
            return
        if path == BRUSH_TIMER_PATH:
            self._handle_measurement(ID_BRUSH_TIMER_REMAINING, 0.0, force_update=True)
            self._handle_measurement(ID_BRUSH_TIMER_ACTIVATION, False, force_update=True)
        elif path == SHOWER_TIMER_PATH:
            self._handle_measurement(ID_SHOWER_TIMER_REMAINING, 0.0, force_update=True)
            self._handle_measurement(ID_SHOWER_TIMER_ACTIVATION, False, force_update=True)

    def _handle_radio_value(self, command: str, raw_value: Any) -> None:
        field = command.rsplit(":", 1)[-1]
        if field == "volume":
            try:
                value = int(_clamp(round(_raw_to_float(raw_value)), 0, 100))
            except (TypeError, ValueError):
                return
        elif field in {"play", "paired"}:
            try:
                value = _raw_to_bool(raw_value)
            except (TypeError, ValueError):
                return
        elif field == "station":
            if not isinstance(raw_value, dict):
                return
            value = dict(raw_value)
        elif field in RADIO_CATALOG_FIELDS and isinstance(raw_value, list):
            self._handle_radio_catalog_value(command, raw_value)
            return
        else:
            value = "" if raw_value is None else str(raw_value)

        self._last_app_values[command] = raw_value
        if self._last_radio_state.get(field) == value:
            return
        self._last_radio_state[field] = value
        for callback in tuple(self._radio_callbacks):
            callback(self._copy_radio_state())

    def _handle_radio_catalog_value(self, command: str, raw_value: Any) -> None:
        self._last_app_values[command] = _summarize_radio_value(raw_value)
        field = command.rsplit(":", 1)[-1]
        if field not in RADIO_CATALOG_FIELDS:
            return

        catalog = _normalize_radio_string_catalog(raw_value)
        if catalog is None:
            return
        self._last_radio_catalogs[field] = catalog
        self._radio_catalog_generations[field] += 1
        if command == RADIO_GENRE_SET_COMMAND:
            self._last_radio_genres = catalog
            self._radio_genres_generation = self._radio_catalog_generations[field]

    def _handle_radio_stations_value(self, raw_value: Any) -> None:
        self._last_app_values[RADIO_STATIONS_SET_COMMAND] = _summarize_radio_value(
            raw_value
        )
        stations = _normalize_radio_stations_value(raw_value)
        if stations is None:
            return
        self._last_radio_stations = stations
        self._radio_stations_generation += 1

    def _handle_radio_favorites_value(self, raw_value: Any) -> None:
        self._last_app_values[RADIO_FAVORITES_SET_COMMAND] = _summarize_radio_value(
            raw_value
        )
        favorites = _normalize_radio_stations_value(raw_value)
        if favorites is None:
            return
        self._last_radio_favorites = favorites
        self._radio_favorites_generation += 1

        state = self._copy_radio_state()
        state["favorites"] = favorites
        if state != self._last_radio_state:
            self._last_radio_state = state
            for callback in tuple(self._radio_callbacks):
                callback(self._copy_radio_state())

    def _copy_radio_state(self) -> dict[str, Any]:
        state = {
            key: _copy_json_like_value(value)
            for key, value in self._last_radio_state.items()
        }
        if self._radio_favorites_generation > 0 and "favorites" not in state:
            state["favorites"] = self._radio_favorites()
        return state

    def _radio_favorites(self) -> list[dict[str, Any]]:
        return [
            _copy_json_like_value(favorite)
            for favorite in self._last_radio_favorites
            if isinstance(favorite, dict)
        ]

    def _handle_weather_value(self, command: str, raw_value: Any) -> None:
        self._last_app_values[command] = _summarize_weather_value(raw_value)

        if command == WEATHER_FAVORITES_SET_COMMAND:
            favorites = _normalize_weather_favorites_value(raw_value)
            if favorites is None:
                return
            state = self._copy_weather_state()
            state["favorites"] = favorites
            self._weather_favorites_generation += 1
            self._set_weather_state(state)
            return

        if command == WEATHER_COUNTRY_SET_COMMAND:
            state = self._copy_weather_state()
            try:
                state["country_id"] = int(_raw_to_float(raw_value))
            except (TypeError, ValueError):
                state.pop("country_id", None)
            self._set_weather_state(state)
            return

        if command == WEATHER_FORECAST_SET_COMMAND:
            results = _normalize_weather_locations_value(raw_value)
            if results is None:
                return
            state = self._copy_weather_state()
            state["forecast_results"] = results
            self._weather_search_generation += 1
            self._set_weather_state(state)
            return

        if command == WEATHER_COUNTRIES_SET_COMMAND:
            countries = _normalize_weather_locations_value(raw_value)
            if countries is None:
                return
            self._last_weather_countries = countries
            self._weather_countries_generation += 1
            return

        if command != WEATHER_LOCATION_SET_COMMAND:
            return

        if not isinstance(raw_value, dict):
            self._set_weather_state({})
            return
        state = _normalize_weather_value(raw_value)

        existing = self._copy_weather_state()
        for key in ("favorites", "country_id", "forecast_results"):
            if key in existing and key not in state:
                state[key] = existing[key]
        self._set_weather_state(state)

    def _set_weather_state(self, state: dict[str, Any]) -> None:
        if self._last_weather_state == state:
            return
        self._last_weather_state = state
        for callback in tuple(self._weather_callbacks):
            callback(self._copy_weather_state())

    def _copy_weather_state(self) -> dict[str, Any]:
        return {
            key: _copy_json_like_value(value)
            for key, value in self._last_weather_state.items()
        }

    def _weather_favorites(self) -> list[dict[str, Any]]:
        favorites = self._last_weather_state.get("favorites")
        if not isinstance(favorites, list):
            return []
        return [
            _copy_json_like_value(favorite)
            for favorite in favorites
            if isinstance(favorite, dict)
        ]

    def _copy_diagnostic_state(self) -> dict[str, Any]:
        state = {
            key: _copy_json_like_value(value)
            for key, value in self._diagnostic_state.items()
        }
        if self._last_message_monotonic is not None:
            state["last_message_age_seconds"] = max(
                0,
                int(round(time.monotonic() - self._last_message_monotonic)),
            )
        return state

    def _update_diagnostics(self, **updates: Any) -> None:
        changed = False
        for key, value in updates.items():
            if value is None:
                if key in self._diagnostic_state:
                    self._diagnostic_state.pop(key)
                    changed = True
                continue
            if self._diagnostic_state.get(key) != value:
                self._diagnostic_state[key] = value
                changed = True
        if not changed:
            return
        state = self._copy_diagnostic_state()
        for callback in tuple(self._diagnostic_callbacks):
            callback(state)

    def _record_pairing_progress(
        self,
        state: str,
        message: str,
        *,
        notify: bool = False,
        result: Any | None = None,
    ) -> None:
        previous_state = self._diagnostic_state.get("pairing_state")
        previous_message = self._diagnostic_state.get("pairing_message")
        previous_result = self._diagnostic_state.get("pairing_result")
        next_result = _summarize_diagnostic_value(result) if result is not None else previous_result
        notify_now = notify and (
            state != previous_state
            or message != previous_message
            or next_result != previous_result
        )
        updates: dict[str, Any] = {
            "pairing_state": state,
            "pairing_message": message,
            "pairing_updated_at": _diagnostic_timestamp(),
        }
        if result is not None:
            updates["pairing_result"] = next_result
        self._update_diagnostics(**updates)
        if notify_now:
            self._notify_pairing_progress(state)

    def _record_pairing_requested(self) -> None:
        self._pairing_request_seen = True
        self._pairing_confirmed_success = False
        self._pairing_failed_explicit = False
        if self._diagnostic_state.get("pairing_state") == "waiting_for_confirmation":
            return
        _LOGGER.info("DHE pairing requested. Confirm the request on the DHE display.")
        self._pairing_active = True
        self._record_pairing_progress(
            "waiting_for_confirmation",
            "DHE requested pairing confirmation.",
            notify=True,
        )

    def _record_pairing_result(self, result: Any) -> None:
        success = _pairing_result_success(result)
        if success is False:
            _LOGGER.warning("DHE pairing was rejected or failed: %r", result)
            self._pairing_confirmed_success = False
            self._pairing_failed_explicit = True
            self._record_pairing_progress(
                "failed",
                "DHE pairing was rejected or failed.",
                notify=True,
                result=result,
            )
            self._pairing_active = False
            return

        state = "confirmed" if success is True else "result_received"
        if success is True:
            self._pairing_confirmed_success = True
            self._pairing_failed_explicit = False
        message = (
            "DHE pairing confirmed; waiting for token."
            if success is True
            else "DHE pairing result received; waiting for token."
        )
        _LOGGER.info("DHE pairing result received: %r", result)
        self._record_pairing_progress(
            state,
            message,
            notify=True,
            result=result,
        )

    def _record_pairing_failed(self, error: BaseException) -> None:
        self._manual_pairing_requested = False
        self._pairing_retry_attempts += 1
        attempts = self._pairing_retry_attempts
        auto_retry_allowed = attempts < MAX_PAIRING_AUTO_RETRIES
        retry_hint = (
            f"Pairing attempt {attempts}/{MAX_PAIRING_AUTO_RETRIES} failed; retrying automatically."
            if auto_retry_allowed
            else (
                f"Pairing attempt {attempts}/{MAX_PAIRING_AUTO_RETRIES} failed; waiting for manual retry."
            )
        )
        self._record_pairing_progress(
            "failed",
            f"{_diagnostic_error(error)} ({retry_hint})",
            notify=True,
        )
        # Allow bounded automatic retries before switching to manual-only mode.
        self._pause_auto_reconnect_for_pairing = not auto_retry_allowed
        self._pairing_active = False

    def _notify_pairing_progress(self, state: str) -> None:
        # Legacy cleanup: remove old standalone hint notification if present.
        try:
            persistent_notification.async_dismiss(
                self.hass,
                self._pairing_confirmation_notification_id,
            )
        except Exception:  # noqa: BLE001
            pass
        title, message = self._pairing_notification_text(state)
        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=self._pairing_notification_id,
        )

    @property
    def _pairing_notification_id(self) -> str:
        safe_host = re.sub(r"[^A-Za-z0-9_-]+", "_", self.host)
        return f"{PAIRING_NOTIFICATION_ID_PREFIX}_{safe_host}"

    @property
    def _pairing_confirmation_notification_id(self) -> str:
        safe_host = re.sub(r"[^A-Za-z0-9_-]+", "_", self.host)
        return f"{PAIRING_CONFIRM_HINT_NOTIFICATION_ID_PREFIX}_{safe_host}"

    def _pairing_notification_text(self, state: str) -> tuple[str, str]:
        language = str(getattr(self.hass.config, "language", "") or "").lower()
        return pairing_notification_text(state, language)

    def _record_runtime_message(self, command: Any, value: Any) -> None:
        if not isinstance(command, str):
            return
        self._last_message_monotonic = time.monotonic()
        self._message_count += 1
        self._update_diagnostics(
            last_message_command=command,
            last_message_received_at=_diagnostic_timestamp(),
            last_message_summary=_summarize_diagnostic_value(value),
            message_count=self._message_count,
        )

    def _handle_consumption_value(self, command: str, raw_value: Any) -> None:
        if not isinstance(raw_value, dict):
            return
        measurement_id = CONSUMPTION_COMMAND_IDS[command]
        raw_chart = raw_value.get("chart", [])
        if not isinstance(raw_chart, list):
            return
        try:
            chart = [_raw_to_float(value) for value in raw_chart]
            cost_eur = _raw_to_float(raw_value["sum"]) if raw_value.get("sum") is not None else None
        except (TypeError, ValueError):
            return

        attributes = {
            "chart": chart,
            "cost_eur": cost_eur,
            "source_command": command,
        }
        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            sum(chart),
            force_update=previous_attributes != attributes,
        )

    def _handle_last_usage_value(self, raw_value: Any) -> None:
        if not isinstance(raw_value, dict):
            return

        fields = {
            "water": ID_LAST_USAGE_WATER,
            "energy": ID_LAST_USAGE_ENERGY,
            "time": ID_LAST_USAGE_TIME,
            "costs": ID_LAST_USAGE_COST,
        }
        for field, measurement_id in fields.items():
            item = raw_value.get(field)
            if not isinstance(item, dict):
                continue
            try:
                value = _raw_to_float(item.get("value"))
            except (TypeError, ValueError):
                continue
            if field in {"water", "energy"}:
                value = round(value, 2)

            attributes = {
                "source_command": LAST_USAGE_SET_COMMAND,
                "last_usage_field": field,
            }
            for key in ("min", "max"):
                if item.get(key) is None:
                    continue
                try:
                    attributes[key] = _raw_to_float(item[key])
                except (TypeError, ValueError):
                    attributes[key] = item[key]

            previous_attributes = self._last_measurement_attributes.get(measurement_id)
            self._last_measurement_attributes[measurement_id] = attributes
            self._handle_measurement(
                measurement_id,
                value,
                force_update=previous_attributes != attributes,
            )

    def _handle_saving_monitor_value(self, command: str, raw_value: Any) -> None:
        key = command.rsplit(":", 1)[-1]
        if key == "ActivationRate":
            try:
                activation_rate = round(_raw_to_float(raw_value), 1)
            except (TypeError, ValueError):
                return
            self._last_saving_monitor_values["activation_rate"] = activation_rate
            self._update_saving_monitor_sensor(
                ID_SAVING_MONITOR_ACTIVATION_RATE,
                activation_rate,
                "activation_rate",
                "activation_rate",
            )
            self._refresh_saving_monitor_sensors()
            return

        if not isinstance(raw_value, dict):
            return
        try:
            values = {
                "water_l": round(_raw_to_float(raw_value["water_l"]), 2),
                "energy_kwh": round(_raw_to_float(raw_value["energy_Wh"]) / 1000.0, 2),
                "co2_kg": round(_raw_to_float(raw_value["emission_Co2Kg"]), 2),
            }
            if raw_value.get("value_E") is not None:
                values["value_eur"] = round(_raw_to_float(raw_value["value_E"]), 2)
        except (KeyError, TypeError, ValueError):
            return

        self._last_saving_monitor_values[key.lower()] = values
        self._refresh_saving_monitor_sensors()

    def _refresh_saving_monitor_sensors(self) -> None:
        for category, field_ids in SAVING_MONITOR_SENSOR_FIELDS.items():
            values = self._last_saving_monitor_values.get(category)
            if not isinstance(values, dict):
                continue
            for field, measurement_id in field_ids.items():
                value = values.get(field)
                if value is not None:
                    self._update_saving_monitor_sensor(measurement_id, value, category, field)

    def _update_saving_monitor_sensor(
        self,
        measurement_id: int,
        value: float,
        category: str,
        field: str,
    ) -> None:
        command_category = "ActivationRate" if category == "activation_rate" else category
        source_command = (
            f"set:ste.app.savingMonitor:{command_category}"
        )
        attributes: dict[str, Any] = {
            "source_command": source_command,
            "saving_monitor_category": category,
            "saving_monitor_field": field,
        }
        for key in ("activation_rate", "possible", "real", "consumption"):
            stored_value = self._last_saving_monitor_values.get(key)
            if stored_value is not None:
                attributes[key] = stored_value

        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            value,
            force_update=previous_attributes != attributes,
        )

    def _handle_app_startup_value(self, command: str, raw_value: Any) -> None:
        self._last_app_values[command] = raw_value
        measurement_id = APP_SETTING_SET_COMMAND_IDS.get(command)
        if measurement_id is None:
            return

        attributes = {
            "source_command": command,
            "raw_value": raw_value,
        }
        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            self._format_app_setting_value(raw_value),
            force_update=previous_attributes != attributes,
        )

    def _handle_currency_value(self, raw_value: Any, *, source_command: str) -> None:
        if raw_value in (None, ""):
            return
        value = str(raw_value).strip().upper()
        if not value or value == "UNSET":
            return

        self._last_app_values[source_command] = raw_value
        attributes = {
            "source_command": source_command,
            "raw_value": raw_value,
        }
        previous_attributes = self._last_measurement_attributes.get(ID_APP_CURRENCY)
        self._last_measurement_attributes[ID_APP_CURRENCY] = attributes
        self._handle_measurement(
            ID_APP_CURRENCY,
            value,
            force_update=previous_attributes != attributes,
        )

    @staticmethod
    def _format_app_setting_value(raw_value: Any) -> str:
        if raw_value in (None, ""):
            return "unset"
        if isinstance(raw_value, bool):
            return "on" if raw_value else "off"
        if isinstance(raw_value, (dict, list)):
            return json.dumps(raw_value, sort_keys=True)
        return str(raw_value)

    def _handle_device_info_value(self, command: str, raw_value: Any) -> None:
        self._last_app_values[command] = raw_value
        key = command.rsplit(":", 1)[-1]
        if key == "gadgetData" and isinstance(raw_value, dict):
            self._last_device_info.update({
                "device_type": self._nested_value(raw_value, "type"),
                "device_id": self._nested_value(raw_value, "id"),
                "wlan_mac": self._nested_value(raw_value, "wlan"),
                "bluetooth_mac": self._nested_value(raw_value, "bluetooth"),
            })
        elif key == "controlunitName":
            self._last_device_info["controlunit_name"] = str(raw_value)
        elif key == "gadgetDataValid":
            try:
                self._last_device_info["gadget_data_valid"] = _raw_to_bool(raw_value)
            except (TypeError, ValueError):
                self._last_device_info["gadget_data_valid"] = bool(raw_value)
        elif key == "orderNumber":
            self._last_device_info["order_number"] = str(raw_value)
        elif key == "contactData" and isinstance(raw_value, dict):
            self._last_device_info["service_contact"] = {
                contact_key: self._nested_value(raw_value, contact_key)
                for contact_key in ("company", "mail", "phone")
            }
        else:
            self._last_device_info[key] = raw_value

        state = str(
            self._last_device_info.get("device_type")
            or self._last_device_info.get("controlunit_name")
            or "DHE Connect"
        )
        attributes = {
            key: value
            for key, value in self._last_device_info.items()
            if value not in (None, "")
        }
        attributes["source_commands"] = list(DEVICE_INFO_SET_COMMANDS)
        previous_attributes = self._last_measurement_attributes.get(ID_DEVICE_INFO)
        self._last_measurement_attributes[ID_DEVICE_INFO] = attributes
        self._handle_measurement(
            ID_DEVICE_INFO,
            state,
            force_update=previous_attributes != attributes,
        )

    @staticmethod
    def _nested_value(raw_value: dict[str, Any], key: str) -> Any:
        value = raw_value.get(key)
        if isinstance(value, dict) and "value" in value:
            return value["value"]
        return value

    def _handle_temperature_memory_value(self, raw_value: Any, *, source_command: str) -> None:
        if isinstance(raw_value, dict):
            if str(raw_value.get("operation", "")).lower() == "delete":
                self._handle_temperature_memory_delete_item(raw_value, source_command=source_command)
                self._temperature_memory_generation += 1
                return
            memory_id = self._handle_temperature_memory_item(raw_value, source_command=source_command)
            if memory_id is not None:
                self._temperature_memory_ids_seen.add(memory_id)
                self._temperature_memory_generation += 1
            return
        if not isinstance(raw_value, list):
            return

        memory_ids: set[int] = set()
        for item in raw_value:
            memory_id = self._handle_temperature_memory_item(item, source_command=source_command)
            if memory_id is not None:
                memory_ids.add(memory_id)
        stale_memory_ids = self._temperature_memory_ids_seen - memory_ids
        if not self._temperature_memory_full_list_seen:
            stale_memory_ids = set(TEMPERATURE_MEMORY_ID_TO_MEASUREMENT) - memory_ids
        for stale_memory_id in stale_memory_ids:
            self._clear_temperature_memory(stale_memory_id, source_command=source_command)
        self._temperature_memory_ids_seen = memory_ids
        self._temperature_memory_full_list_seen = True
        self._temperature_memory_generation += 1

    def _handle_temperature_memory_delete_item(self, item: dict[str, Any], *, source_command: str) -> None:
        try:
            memory_id = int(item.get("id"))
        except (TypeError, ValueError):
            return
        self._temperature_memory_ids_seen.discard(memory_id)
        self._clear_temperature_memory(memory_id, source_command=source_command)

    def _handle_temperature_memory_item(self, item: Any, *, source_command: str) -> int | None:
        if not isinstance(item, dict):
            return None
        try:
            memory_id = int(item.get("id"))
            temperature = _raw_to_float(item.get("temperature"))
        except (TypeError, ValueError):
            return None
        measurement_id = TEMPERATURE_MEMORY_ID_TO_MEASUREMENT.get(memory_id)
        if measurement_id is None:
            return None
        attributes = {
            "memory_id": memory_id,
            "name": str(item.get("name", DEFAULT_TEMPERATURE_MEMORY_NAMES.get(memory_id, ""))),
            "source_command": source_command,
        }
        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            temperature,
            force_update=previous_attributes != attributes,
        )
        return memory_id

    def _clear_temperature_memory(self, memory_id: int, *, source_command: str) -> None:
        measurement_id = TEMPERATURE_MEMORY_ID_TO_MEASUREMENT.get(memory_id)
        if measurement_id is None:
            return
        self._last_measurements.pop(measurement_id, None)
        self._last_measurement_attributes[measurement_id] = {
            "memory_id": memory_id,
            "source_command": source_command,
            "operation": "delete",
        }
        for callback in tuple(self._measurement_callbacks):
            callback(measurement_id, None)

    def _handle_odb_value(self, odb_id: int, raw_value: Any, *, is_valid: Any = None) -> None:
        if is_valid is False:
            if int(odb_id) not in KNOWN_ODB_VALUE_IDS:
                self._log_unknown_odb_value(odb_id, raw_value, is_valid=False)
            return
        try:
            if odb_id == ID_SETPOINT:
                self._handle_setpoint(_raw_tenths_to_c(_raw_to_float(raw_value)))
            elif odb_id == ID_WATER_FLOW:
                self._handle_measurement(odb_id, _raw_to_float(raw_value) / 10.0)
            elif odb_id == ID_POWER_PERCENT:
                self._last_power_fraction = _raw_to_float(raw_value) / 100.0
                self._handle_measurement(odb_id, self._last_power_fraction * self._nominal_power_kw)
            elif odb_id == ID_OPERATING_DURATION:
                self._handle_measurement(odb_id, max(0.0, _raw_to_float(raw_value)))
            elif odb_id == ID_NOMINAL_POWER:
                self._nominal_power_kw = self._raw_nominal_power_to_kw(_raw_to_float(raw_value))
                self._handle_measurement(odb_id, self._nominal_power_kw)
                if self._last_power_fraction is not None:
                    self._handle_measurement(
                        ID_POWER_PERCENT,
                        self._last_power_fraction * self._nominal_power_kw,
                    )
            elif odb_id == ID_BATH_FILL_TARGET_VOLUME:
                self._handle_measurement(odb_id, self._convert_odb_value(odb_id, raw_value))
                self._refresh_bath_fill_remaining()
            elif odb_id == ID_BATH_FILL_CURRENT_VOLUME:
                self._handle_measurement(odb_id, max(0.0, _raw_to_float(raw_value)))
                self._refresh_bath_fill_remaining()
            elif odb_id == ID_WELLNESS_TIME_NORMALIZED:
                self._handle_measurement(odb_id, max(0.0, _raw_to_float(raw_value)))
            elif odb_id in {
                ID_INLET_TEMPERATURE,
                ID_OUTLET_TEMPERATURE,
            }:
                self._handle_measurement(odb_id, _raw_tenths_to_c(_raw_to_float(raw_value)))
            elif odb_id == ID_SCALD_PROTECTION_TEMPERATURE_LIMIT:
                self._handle_measurement(odb_id, _raw_tenths_to_c(_raw_to_float(raw_value)))
            elif odb_id == ID_HEATING_ENERGY_TOTAL:
                self._handle_measurement(odb_id, max(0.0, _raw_to_float(raw_value)))
            elif odb_id == ID_HOT_WATER_VOLUME_TOTAL:
                self._handle_measurement(odb_id, max(0.0, _raw_to_float(raw_value)) / 10.0)
            elif odb_id == ID_POSSIBLE_ENERGY_SAVING:
                self._handle_measurement(odb_id, max(0.0, _raw_to_float(raw_value)))
            elif odb_id == ID_POSSIBLE_WATER_SAVING:
                self._handle_measurement(odb_id, max(0.0, _raw_to_float(raw_value)) / 10.0)
            elif odb_id == ID_PROTOCOL_VERSION:
                self._handle_measurement(odb_id, int(round(max(0.0, _raw_to_float(raw_value)))))
            elif odb_id == ID_WATER_HEATING_ENABLED:
                self._handle_measurement(odb_id, _raw_to_water_heating_enabled(raw_value))
            elif odb_id == ID_SCALD_PROTECTION_ACTIVE:
                self._handle_measurement(odb_id, _raw_to_bool(raw_value))
            elif odb_id == ID_DEVICE_STATUS:
                self._handle_device_status(raw_value)
            elif odb_id in PRICE_COMPONENT_IDS:
                self._handle_price_component(odb_id, raw_value)
            elif odb_id == ID_CO2_EMISSION_RAW:
                self._handle_co2_emission(raw_value)
            elif odb_id == ID_CHILD_SAFETY_ACTIVE:
                self._handle_measurement(odb_id, _raw_to_bool(raw_value))
            elif odb_id == ID_CURRENCY_MODE:
                return
            elif odb_id == ID_SETPOINT_REQUEST:
                return
            elif odb_id in WRITABLE_OPTION_IDS:
                self._handle_measurement(odb_id, self._convert_odb_value(odb_id, raw_value))
            else:
                self._log_unknown_odb_value(odb_id, raw_value, is_valid=is_valid)
        except (TypeError, ValueError):
            return

    def _log_unhandled_ste_command(self, command: Any, value: Any) -> None:
        if not isinstance(command, str) or not command.startswith(
            ("get:ste", "set:ste", "assign:ste")
        ):
            return
        _LOGGER.debug(
            "Unhandled DHE ste command=%s value_summary=%r",
            command,
            _summarize_diagnostic_value(value),
        )

    def _refresh_bath_fill_remaining(self) -> None:
        target = self._last_measurements.get(ID_BATH_FILL_TARGET_VOLUME)
        current = self._last_measurements.get(ID_BATH_FILL_CURRENT_VOLUME)
        if target is None or current is None:
            return
        try:
            target_l = max(0.0, _raw_to_float(target))
            current_l = max(0.0, _raw_to_float(current))
        except (TypeError, ValueError):
            return

        attributes = {
            "source": "derived",
            "target_l": target_l,
            "filled_l": current_l,
            "target_odb_id": ID_BATH_FILL_TARGET_VOLUME,
            "filled_odb_id": ID_BATH_FILL_CURRENT_VOLUME,
        }
        previous_attributes = self._last_measurement_attributes.get(ID_BATH_FILL_REMAINING_VOLUME)
        self._last_measurement_attributes[ID_BATH_FILL_REMAINING_VOLUME] = attributes
        self._handle_measurement(
            ID_BATH_FILL_REMAINING_VOLUME,
            int(round(max(target_l - current_l, 0.0))),
            force_update=previous_attributes != attributes,
        )

    def _handle_price_component(self, odb_id: int, raw_value: Any) -> None:
        value = int(round(_raw_to_float(raw_value)))
        measurement_id, euros_odb_id, cents_odb_id = PRICE_COMPONENT_IDS[odb_id]
        if odb_id == cents_odb_id:
            value = int(_clamp(value, 0, PRICE_CENTS_COMPONENT_MAX))
        else:
            max_euros = PRICE_EUROS_COMPONENT_MAX_BY_ID.get(euros_odb_id, 9)
            value = int(_clamp(value, 0, max_euros))
        self._handle_measurement(odb_id, float(value))

        euros_value = self._last_measurements.get(euros_odb_id)
        cents_value = self._last_measurements.get(cents_odb_id)
        if euros_value is None or cents_value is None:
            return
        price = float(int(euros_value)) + (float(int(cents_value)) / 100.0)
        attributes = {
            "source_odb_ids": {
                "euros": euros_odb_id,
                "cents": cents_odb_id,
            },
            "euros": int(euros_value),
            "cents": int(cents_value),
        }
        previous_attributes = self._last_measurement_attributes.get(measurement_id)
        self._last_measurement_attributes[measurement_id] = attributes
        self._handle_measurement(
            measurement_id,
            price,
            force_update=previous_attributes != attributes,
        )

    def _handle_co2_emission(self, raw_value: Any) -> None:
        raw = _raw_to_float(raw_value)
        value = self._raw_to_co2_emission(raw)
        self._handle_measurement(ID_CO2_EMISSION_RAW, raw)
        attributes = {
            "source_odb_id": ID_CO2_EMISSION_RAW,
            "raw_value": raw,
        }
        previous_attributes = self._last_measurement_attributes.get(ID_CO2_EMISSION)
        self._last_measurement_attributes[ID_CO2_EMISSION] = attributes
        self._handle_measurement(
            ID_CO2_EMISSION,
            value,
            force_update=previous_attributes != attributes,
        )

    def _handle_device_status(self, raw_value: Any) -> None:
        raw = int(_raw_to_float(raw_value))
        status = _device_status_key(raw)
        attributes = {
            "raw_value": raw,
            "status": status,
            "service_required": _device_status_problem(raw),
        }
        previous_attributes = self._last_measurement_attributes.get(ID_DEVICE_STATUS)
        self._last_measurement_attributes[ID_DEVICE_STATUS] = attributes
        self._handle_measurement(
            ID_DEVICE_STATUS,
            status,
            force_update=previous_attributes != attributes,
        )

    @staticmethod
    def _co2_emission_to_raw(kg_per_kwh: float) -> int:
        return int(round(float(kg_per_kwh) * 1000))

    @staticmethod
    def _raw_to_co2_emission(raw_value: float) -> float:
        return round(_clamp(float(raw_value), 0.0, CO2_EMISSION_RAW_MAX) / 1000.0, 3)

    @staticmethod
    def _odb_debug_name(odb_id: Any) -> str:
        try:
            return ODB_DEBUG_NAMES.get(int(odb_id), "unknown")
        except (TypeError, ValueError):
            return "unknown"

    @staticmethod
    def _log_unknown_odb_value(odb_id: int, raw_value: Any, *, is_valid: Any = None) -> None:
        _LOGGER.debug(
            "Unknown DHE ODB value id=%s name=%s value=%r is_valid=%r",
            odb_id,
            DHEClient._odb_debug_name(odb_id),
            raw_value,
            is_valid,
        )

    def _handle_setpoint(self, value: float) -> None:
        previous = self._last_setpoint
        self._last_setpoint = value
        if previous is None or abs(previous - value) >= 0.01:
            for callback in tuple(self._setpoint_callbacks):
                callback(value)
        future = self._pending_setpoint_future
        expected = self._pending_expected_setpoint
        if future is not None and not future.done() and (expected is None or abs(value - expected) < 0.01):
            future.set_result(value)
            self._pending_setpoint_future = None
            self._pending_expected_setpoint = None

    def _handle_measurement(self, odb_id: int, value: MeasurementValue, *, force_update: bool = False) -> None:
        previous = self._last_measurements.get(odb_id)
        self._last_measurements[odb_id] = value
        if value is not None and not isinstance(value, str):
            self._maybe_complete_write_future(odb_id, value)
        if not force_update and previous is not None:
            if isinstance(previous, str) or isinstance(value, str):
                if previous == value:
                    return
            elif _values_equal(previous, value):
                return
        for callback in tuple(self._measurement_callbacks):
            callback(odb_id, value)

    def _maybe_complete_write_future(self, odb_id: int, value: ODBValue) -> None:
        future = self._pending_write_future
        if future is None or future.done() or self._pending_write_id != odb_id:
            return
        expected = self._pending_write_expected
        if expected is None or _values_equal(value, expected):
            future.set_result(value)
            self._pending_write_future = None
            self._pending_write_id = None
            self._pending_write_expected = None

    async def _wait_for_setpoint_confirmation(
        self,
        ctx: DHESession,
        future: asyncio.Future[float],
    ) -> float:
        deadline = time.monotonic() + COMMAND_CONFIRMATION_TIMEOUT
        next_readback = 0.0
        while not future.done():
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_readback:
                await self._request_setpoint(ctx)
                next_readback = now + COMMAND_READBACK_INTERVAL
            timeout = min(COMMAND_READBACK_INTERVAL, max(0.1, deadline - now))
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except TimeoutError:
                continue
        if future.done():
            return future.result()
        raise DHEError("setpoint confirmation timed out")

    async def _wait_for_write_confirmation(
        self,
        ctx: DHESession,
        future: asyncio.Future[ODBValue],
        odb_id: int,
    ) -> ODBValue:
        deadline = time.monotonic() + COMMAND_CONFIRMATION_TIMEOUT
        next_readback = 0.0
        while not future.done():
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_readback:
                await self._request_odb_value(ctx, odb_id)
                next_readback = now + COMMAND_READBACK_INTERVAL
            timeout = min(COMMAND_READBACK_INTERVAL, max(0.1, deadline - now))
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except TimeoutError:
                continue
        if future.done():
            return future.result()
        raise DHEError(f"write confirmation timed out for DHE ODB id {odb_id}")

    async def _wait_for_app_write_confirmation(
        self,
        future: asyncio.Future[ODBValue],
    ) -> ODBValue:
        return await asyncio.wait_for(
            asyncio.shield(future),
            timeout=APP_COMMAND_CONFIRMATION_TIMEOUT,
        )

    async def _wait_for_radio_stations(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            if self._radio_stations_generation != previous_generation:
                return [
                    _copy_json_like_value(station)
                    for station in self._last_radio_stations
                    if isinstance(station, dict)
                ]
            await asyncio.sleep(0.1)
        raise DHEError("radio station search timed out")

    async def _wait_for_radio_favorites(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            if self._radio_favorites_generation != previous_generation:
                return self._radio_favorites()
            await asyncio.sleep(0.1)
        raise DHEError("radio favorites timed out")

    async def _wait_for_radio_catalog(
        self,
        attribute: str,
        previous_generation: int,
    ) -> list[str]:
        requested_attribute = str(attribute).strip().lower()
        deadline = time.monotonic() + WEATHER_CATALOG_TIMEOUT
        while time.monotonic() < deadline:
            if (
                self._radio_catalog_generations.get(requested_attribute, 0)
                != previous_generation
            ):
                return list(self._last_radio_catalogs.get(requested_attribute, []))
            await asyncio.sleep(0.1)
        catalog = self._last_radio_catalogs.get(requested_attribute, [])
        if catalog:
            return list(catalog)
        raise DHEError(f"radio {requested_attribute} catalog timed out")

    async def _wait_for_radio_genres(self, previous_generation: int) -> list[str]:
        return await self._wait_for_radio_catalog("genre", previous_generation)

    async def _wait_for_radio_station(self, station_id: int) -> None:
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            station = self._last_radio_state.get("station")
            if isinstance(station, dict) and _radio_station_id(station) == station_id:
                return
            await asyncio.sleep(0.1)
        raise DHEError("radio station selection timed out")

    async def _wait_for_weather_search_results(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            if self._weather_search_generation != previous_generation:
                results = self._last_weather_state.get("forecast_results")
                if isinstance(results, list):
                    return [
                        _copy_json_like_value(result)
                        for result in results
                        if isinstance(result, dict)
                    ]
                return []
            await asyncio.sleep(0.1)
        raise DHEError("weather location search timed out")

    async def _wait_for_weather_countries(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + WEATHER_CATALOG_TIMEOUT
        while time.monotonic() < deadline:
            if self._weather_countries_generation != previous_generation:
                return [
                    _copy_json_like_value(country)
                    for country in self._last_weather_countries
                    if isinstance(country, dict)
                ]
            await asyncio.sleep(0.1)
        if self._last_weather_countries:
            return [
                _copy_json_like_value(country)
                for country in self._last_weather_countries
                if isinstance(country, dict)
            ]
        raise DHEError("weather country catalog timed out")

    async def _wait_for_weather_favorites(
        self,
        previous_generation: int,
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            if self._weather_favorites_generation != previous_generation:
                favorites = self._last_weather_state.get("favorites")
                if isinstance(favorites, list):
                    return [
                        _copy_json_like_value(favorite)
                        for favorite in favorites
                        if isinstance(favorite, dict)
                    ]
                return []
            await asyncio.sleep(0.1)
        raise DHEError("weather favorites timed out")

    async def _wait_for_weather_location(
        self,
        location_id: str,
    ) -> None:
        deadline = time.monotonic() + APP_COMMAND_CONFIRMATION_TIMEOUT
        while time.monotonic() < deadline:
            location = self._last_weather_state.get("location")
            if (
                isinstance(location, dict)
                and str(location.get("LocationId", "")) == location_id
            ):
                return
            await asyncio.sleep(0.1)
        raise DHEError("weather location selection timed out")

    @staticmethod
    def _convert_odb_value(odb_id: int, raw_value: Any) -> ODBValue:
        if odb_id in {ID_BATH_FILL_ACTIVE, ID_CHILD_SAFETY_ACTIVE, ID_ECO_MODE, ID_WELLNESS_ACTIVE}:
            return _raw_to_bool(raw_value)
        if odb_id == ID_WATER_HEATING_ENABLED:
            return _raw_to_water_heating_enabled(raw_value)
        if odb_id == ID_CHILD_SAFETY_TEMPERATURE_LIMIT:
            value = _raw_to_float(raw_value)
            if 200.0 <= value <= 600.0:
                return _raw_tenths_to_c(value)
            return value
        if odb_id == ID_ECO_FLOW_LIMIT:
            value = _raw_to_float(raw_value)
            if 40.0 <= value <= 150.0:
                return value / 10.0
            return value
        return _raw_to_float(raw_value)

    @staticmethod
    def _raw_nominal_power_to_kw(raw: int | float) -> float:
        value = float(raw)
        if 12.0 <= value <= 36.0:
            return value
        if 120.0 <= value <= 360.0:
            return value / 10.0
        if 1200.0 <= value <= 3600.0:
            return value / 100.0
        _LOGGER.warning("Ignoring unexpected nominal DHE power value from ODB id 20: %s", raw)
        return DEFAULT_NOMINAL_POWER_KW

    async def _request_setpoint(self, ctx: DHESession) -> None:
        await self._request_odb_value(ctx, ID_SETPOINT)

    async def _request_initial_values(self, ctx: DHESession) -> None:
        for odb_id in INITIAL_VALUE_IDS:
            if odb_id != ID_NOMINAL_POWER or odb_id not in self._last_measurements:
                await self._request_odb_value(ctx, odb_id)
        for command in APP_TIMER_REQUEST_COMMANDS:
            await self._request_app_value(ctx, command)
        for command in CONSUMPTION_REQUEST_COMMANDS:
            await self._request_app_value(ctx, command)
        for odb_id in OPTIONAL_STARTUP_ODB_IDS:
            await self._request_optional_odb_value(ctx, odb_id)
        for command in OPTIONAL_STARTUP_APP_REQUEST_COMMANDS:
            await self._request_optional_app_value(ctx, command)

    async def _request_odb_value(self, ctx: DHESession, odb_id: int) -> None:
        await self._post_packet(
            ctx,
            self._message_packet({"command": ODB_GET_COMMAND, "value": {"id": odb_id, "value": ""}}),
        )

    async def _request_app_value(self, ctx: DHESession, command: str) -> None:
        await self._post_packet(ctx, self._message_packet({"command": command, "value": ""}))

    async def _request_optional_odb_value(self, ctx: DHESession, odb_id: int) -> None:
        try:
            await self._request_odb_value(ctx, odb_id)
        except Exception:  # noqa: BLE001
            pass

    async def _request_optional_app_value(self, ctx: DHESession, command: str) -> None:
        try:
            await self._request_app_value(ctx, command)
        except Exception:  # noqa: BLE001
            pass

    def _new_setpoint_future(self, expected: float | None = None) -> asyncio.Future[float]:
        self._clear_pending_future(None)
        future: asyncio.Future[float] = self.hass.loop.create_future()
        self._pending_setpoint_future = future
        self._pending_expected_setpoint = expected
        return future

    def _clear_pending_future(self, err: Exception | None) -> None:
        future = self._pending_setpoint_future
        self._pending_setpoint_future = None
        self._pending_expected_setpoint = None
        if future is not None and not future.done():
            if err is not None:
                future.set_exception(err)
            else:
                future.cancel()

    def _new_write_future(self, odb_id: int, expected: ODBValue | None = None) -> asyncio.Future[ODBValue]:
        self._clear_pending_write_future(None)
        future: asyncio.Future[ODBValue] = self.hass.loop.create_future()
        self._pending_write_future = future
        self._pending_write_id = int(odb_id)
        self._pending_write_expected = expected
        return future

    def _clear_pending_write_future(self, err: Exception | None) -> None:
        future = self._pending_write_future
        self._pending_write_future = None
        self._pending_write_id = None
        self._pending_write_expected = None
        if future is not None and not future.done():
            if err is not None:
                future.set_exception(err)
            else:
                future.cancel()

    def _set_available(self, available: bool, *, immediate: bool = False) -> None:
        if available:
            self._cancel_delayed_unavailable()
            self._emit_availability(True)
            return

        if immediate:
            self._cancel_delayed_unavailable()
            self._emit_availability(False)
            return

        if self._availability_drop_task is not None and not self._availability_drop_task.done():
            return
        self._availability_drop_task = self.hass.async_create_task(
            self._delayed_set_unavailable(),
            name="stiebel_dhe_connect_delayed_unavailable",
        )

    def _emit_availability(self, available: bool) -> None:
        if self._available == available:
            return
        self._available = available
        for callback in tuple(self._availability_callbacks):
            callback(available)

    def _set_online(self, online: bool) -> None:
        if self._online == online:
            return
        self._online = online
        for callback in tuple(self._online_callbacks):
            callback(online)

    def _cancel_delayed_unavailable(self) -> None:
        task = self._availability_drop_task
        self._availability_drop_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _delayed_set_unavailable(self) -> None:
        try:
            await asyncio.sleep(AVAILABILITY_DROP_GRACE_SECONDS)
            if self._ctx is None and not self._ready.is_set() and not self._stopped.is_set():
                self._emit_availability(False)
        except asyncio.CancelledError:
            return
        finally:
            self._availability_drop_task = None

    async def _upgrade_to_websocket(self, ctx: DHESession) -> None:
        websocket = None
        try:
            errors: list[str] = []
            for label, sid, url in self._websocket_url_candidates(ctx):
                websocket = None
                try:
                    websocket = await self._session.ws_connect(
                        url,
                        autoping=True,
                        heartbeat=None,
                        headers=self._websocket_headers(sid),
                        timeout=WEBSOCKET_UPGRADE_TIMEOUT,
                    )
                    await websocket.send_str("2probe")
                    deadline = time.monotonic() + WEBSOCKET_UPGRADE_TIMEOUT
                    while time.monotonic() < deadline:
                        timeout = max(0.1, deadline - time.monotonic())
                        message = await asyncio.wait_for(websocket.receive(), timeout=timeout)
                        packet = self._websocket_message_packet(message)
                        if packet == "3probe":
                            async with self._send_lock:
                                await websocket.send_str("5")
                            ctx.websocket = websocket
                            ctx.websocket_ping_task = self._create_background_task(
                                self._websocket_ping_loop(ctx),
                                "stiebel_dhe_connect_websocket_ping",
                            )
                            return
                        if packet == "2":
                            await websocket.send_str("3")
                            continue
                        if message.type in {
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        }:
                            break
                        if packet == "3" or not packet:
                            continue
                        _LOGGER.debug("Ignoring unexpected DHE websocket probe packet: %r", packet)
                    raise DHEError("probe timeout")
                except Exception as err:  # noqa: BLE001
                    errors.append(f"{label}: {type(err).__name__}")
                    if websocket is not None and not websocket.closed:
                        await websocket.close()
            raise DHEError("; ".join(errors) or "probe timeout")
        except Exception as err:  # noqa: BLE001
            if websocket is not None and not websocket.closed:
                await websocket.close()
            raise DHEError(f"DHE websocket upgrade failed: {err}") from err

    async def _websocket_ping_loop(self, ctx: DHESession) -> None:
        try:
            while not self._stopped.is_set() and ctx.websocket is not None and not ctx.websocket.closed:
                await asyncio.sleep(ctx.ping_interval)
                if self._stopped.is_set() or ctx.websocket is None or ctx.websocket.closed:
                    return
                await self._send_websocket_packet(ctx, "2")
        except asyncio.CancelledError:
            return
        except Exception as err:  # noqa: BLE001
            if not self._stopped.is_set():
                await self._force_reconnect(
                    ctx,
                    immediate_availability=True,
                    reason=f"Heartbeat failed: {_diagnostic_error(err)}",
                )

    async def _read_events_once(self, ctx: DHESession) -> list[DHEEvent]:
        if ctx.websocket is None:
            raise DHESessionClosed("DHE websocket transport is not connected")
        return await self._read_websocket_events_once(ctx)

    async def _read_polling_events_once(self, ctx: DHESession) -> list[DHEEvent]:
        try:
            raw = await self._get_text(
                self._poll_url(ctx.url_token, ctx.sid, ctx.websocket_sid),
                timeout=AUTH_POLL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            return []
        if not raw:
            return []
        if re.search(r"(^|[\ufffd\x1e])41(?:/1\.0\.0)?", raw):
            return [DHEEvent("__closed", None)]
        packets = self._decode_engineio_payload(raw)
        app_packets: list[str] = []
        for packet in packets:
            stripped = packet.strip("\x00\x1e\ufffd")
            if stripped == "1" or stripped == "41" or stripped.startswith("41/"):
                return [DHEEvent("__closed", None)]
            if stripped == "2":
                await self._post_packet(ctx, "3")
                continue
            if stripped == "3" or not stripped:
                continue
            app_packets.append(packet)
        return self._parse_socketio_events(app_packets)

    async def _read_websocket_events_once(self, ctx: DHESession) -> list[DHEEvent]:
        websocket = ctx.websocket
        if websocket is None:
            return []
        message = await websocket.receive()
        if message.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.ERROR,
        }:
            return [DHEEvent("__closed", None)]
        raw = self._websocket_message_packet(message)
        if not raw:
            return []

        packets = self._decode_engineio_payload(raw)
        app_packets: list[str] = []
        for packet in packets:
            stripped = packet.strip("\x00\x1e\ufffd")
            if stripped == "1" or stripped == "41" or stripped.startswith("41/"):
                return [DHEEvent("__closed", None)]
            if stripped == "2":
                await self._send_websocket_packet(ctx, "3")
                continue
            if stripped == "3" or not stripped:
                continue
            app_packets.append(packet)
        return self._parse_socketio_events(app_packets)

    def _poll_url(self, token: str, sid: str | None, websocket_sid: str | None = None) -> str:
        token_q = quote(token or "", safe="")
        t = format(int(time.time() * 1000), "x")
        websocket_part = ""
        if websocket_sid:
            websocket_part = f"&websocketSid={quote(websocket_sid, safe='')}"
        if sid:
            return f"{self.base_url}/socket.io/?EIO=3&transport=polling&sid={quote(sid, safe='')}{websocket_part}&token={token_q}&t={t}"
        return f"{self.base_url}/socket.io/?EIO=3&transport=polling{websocket_part}&token={token_q}&t={t}"

    def _websocket_url_candidates(self, ctx: DHESession) -> tuple[tuple[str, str, str], ...]:
        websocket_sid = ctx.websocket_sid or ctx.sid
        candidates = [
            ("websocket-sid", websocket_sid, self._websocket_url(ctx.url_token, websocket_sid)),
        ]
        if ctx.websocket_sid:
            candidates.extend([
                ("polling-sid", ctx.sid, self._websocket_url(ctx.url_token, ctx.sid)),
            ])
        return tuple(candidates)

    def _websocket_url(self, token: str, sid: str) -> str:
        token_q = quote(token or "", safe="")
        sid_q = quote(sid, safe="")
        return f"ws://{self._url_host}:{self.port}/socket.io/?token={token_q}&EIO=3&transport=websocket&sid={sid_q}"

    def _websocket_headers(self, sid: str) -> dict[str, str]:
        return {
            "Cache-Control": "no-cache",
            "Cookie": f"io={sid}",
            "Origin": self.base_url,
            "Pragma": "no-cache",
        }

    @staticmethod
    def _engineio_ping_interval(open_payload: str) -> float:
        match = re.search(r'"pingInterval"\s*:\s*(\d+(?:\.\d+)?)', open_payload)
        if not match:
            return DEFAULT_ENGINEIO_PING_INTERVAL_SECONDS
        return max(1.0, float(match.group(1)) / 1000.0)

    async def _get_text(self, url: str, *, timeout: float = 70.0) -> str:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with self._session.get(url, timeout=client_timeout) as resp:
            body = await resp.read()
            if resp.status < 200 or resp.status >= 300:
                text = body.decode("utf-8", errors="replace")
                raise DHEError(f"GET {resp.status}: {text[:200]}")
            return body.decode("utf-8", errors="replace")

    async def _post_packet(self, ctx: DHESession, packet: str) -> str:
        if ctx.websocket is not None:
            await self._send_websocket_packet(ctx, packet)
            return ""

        body = f"{len(packet)}:{packet}"
        timeout = aiohttp.ClientTimeout(total=40)
        async with self._session.post(
            self._poll_url(ctx.url_token, ctx.sid, ctx.websocket_sid),
            data=body.encode("utf-8"),
            headers={"Content-Type": "text/plain;charset=UTF-8"},
            timeout=timeout,
        ) as resp:
            response_body = await resp.read()
            if resp.status < 200 or resp.status >= 300:
                text = response_body.decode("utf-8", errors="replace")
                raise DHEError(f"POST {resp.status}: {text[:200]}")
            return response_body.decode("utf-8", errors="replace")

    async def _send_websocket_packet(self, ctx: DHESession, packet: str) -> None:
        websocket = ctx.websocket
        if websocket is None or websocket.closed:
            raise DHESessionClosed("DHE websocket transport is closed")
        async with self._send_lock:
            await websocket.send_str(packet)

    @staticmethod
    def _websocket_message_packet(message: Any) -> str:
        if message.type == aiohttp.WSMsgType.TEXT:
            return str(message.data)
        if message.type == aiohttp.WSMsgType.BINARY:
            return bytes(message.data).decode("utf-8", errors="replace")
        return ""

    def _event_packet(self, event: str, data: Any) -> str:
        return f"42/{NS},{json.dumps([event, data], separators=(',', ':'))}"

    def _message_packet(self, payload: dict[str, Any]) -> str:
        message_id = self._next_socketio_message_id()
        return f"42/{NS},{message_id}{json.dumps(['message', payload], separators=(',', ':'))}"

    def _next_socketio_message_id(self) -> int:
        message_id = self._socketio_message_id
        self._socketio_message_id = 1 if message_id >= 999 else message_id + 1
        return message_id

    @staticmethod
    def _decode_engineio_payload(text: str) -> list[str]:
        if "\x1e" in text:
            return [part for part in text.split("\x1e") if part.strip()]
        if "\ufffd" in text:
            return [part for part in text.split("\ufffd") if part.strip()]
        packets: list[str] = []
        i = 0
        try:
            while i < len(text):
                if not text[i].isdigit():
                    if packets:
                        i += 1
                        continue
                    return [text]
                j = i
                while j < len(text) and text[j].isdigit():
                    j += 1
                if j >= len(text) or text[j] != ":":
                    return [text]
                length = int(text[i:j])
                start = j + 1
                end = start + length
                if end > len(text):
                    return [text]
                packets.append(text[start:end])
                i = end
            return packets or [text]
        except Exception:  # noqa: BLE001
            return [text]

    @staticmethod
    def _balanced_json_array(text: str, start_index: int) -> tuple[str | None, int]:
        start = text.find("[", start_index)
        if start < 0:
            return None, -1
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1], idx + 1
        return None, -1

    def _parse_socketio_events(self, packets: list[str]) -> list[DHEEvent]:
        out: list[DHEEvent] = []
        for raw_packet in packets:
            packet = raw_packet.strip("\x00\x1e\ufffd")
            if not packet:
                continue
            pos = 0
            while pos < len(packet):
                match = re.search(r"42(?:/1\.0\.0,)?\d*", packet[pos:])
                if not match:
                    break
                frame_start = pos + match.start()
                json_text, next_pos = self._balanced_json_array(packet, frame_start)
                if not json_text:
                    break
                try:
                    parsed = json.loads(json_text)
                    if isinstance(parsed, list) and parsed:
                        name = str(parsed[0])
                        data = parsed[1] if len(parsed) > 1 else None
                        out.append(DHEEvent(name, data))
                except json.JSONDecodeError:
                    _LOGGER.debug(
                        "Could not parse Socket.IO JSON frame: %r",
                        _summarize_diagnostic_value(json_text),
                    )
                pos = next_pos
        return out

    async def _load_token(self) -> str:
        if self._token:
            return self._token

        def _read() -> str:
            if not os.path.exists(self.token_path):
                return ""
            with open(self.token_path, "r", encoding="utf-8") as file:
                return file.read().strip()

        token = await self.hass.async_add_executor_job(_read)
        if token and (len(token) < 20 or any(ch.isspace() for ch in token)):
            _LOGGER.warning("Ignoring malformed stored DHE token at %s", self.token_path)
            token = ""
        self._token = token
        return self._token or ""

    async def _save_token(self, token: str) -> None:
        self._token = token

        def _write() -> None:
            token_dir = os.path.dirname(self.token_path)
            os.makedirs(token_dir, exist_ok=True)
            tmp_path = f"{self.token_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as file:
                file.write(token)
            try:
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(tmp_path, self.token_path)

        await self.hass.async_add_executor_job(_write)

    async def _clear_token(self) -> None:
        self._token = ""

        def _delete() -> None:
            try:
                os.remove(self.token_path)
            except FileNotFoundError:
                pass

        await self.hass.async_add_executor_job(_delete)
