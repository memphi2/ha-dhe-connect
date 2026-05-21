"""DHE Socket.IO command and ODB protocol constants."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

NS = "1.0.0"
ODB_GET_COMMAND = "get:ste.common.odb:value"
ODB_SET_COMMAND = "set:ste.common.odb:value"
ODB_ASSIGN_COMMAND = "assign:ste.common.odb:value"
TEMP_MEMORY_GET_COMMAND = "get:ste.common.temperature:memory"
TEMP_MEMORY_SET_COMMAND = "set:ste.common.temperature:memory"
TEMP_MEMORY_ASSIGN_COMMAND = "assign:ste.common.temperature:memory"

ID_SETPOINT = 0
ID_BATH_FILL_ACTIVE = 1
ID_WELLNESS_SHOWER_PROGRAM = 2
ID_BATH_FILL_TARGET_VOLUME = 3
ID_CHILD_SAFETY_ACTIVE = 4
ID_CHILD_SAFETY_TEMPERATURE_LIMIT = 5
ID_ECO_MODE = 6
ID_ECO_FLOW_LIMIT = 7
ID_WELLNESS_ACTIVE = 10
WELLNESS_COLD_PREVENTION_PROGRAM_ID = 1
WINTER_REFRESH_PROGRAM_ID = 2
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
ID_ODB_HEATING_ENERGY = 29
ID_ODB_HOT_WATER_VOLUME = 30
ID_BATH_FILL_CURRENT_VOLUME = 31
ID_WELLNESS_TIME_NORMALIZED = 32
ID_WATER_HEATING_ENABLED = 33
ID_DEVICE_STATUS = 34
ID_ELECTRICITY_PRICE_EUROS = 61
ID_WATER_PRICE_EUROS = 62
ID_ODB_POSSIBLE_ENERGY_SAVING = 63
ID_ODB_ACTUAL_WATER_SAVING = 64
ID_SETPOINT_REQUEST = 66
ID_PROTOCOL_VERSION = 67
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
    ID_ODB_HEATING_ENERGY: "ODB_Heizen_Energie",
    ID_ODB_HOT_WATER_VOLUME: "ODB_WW_Volumen",
    ID_BATH_FILL_CURRENT_VOLUME: "ODB_VolBegr_Volumen",
    ID_WELLNESS_TIME_NORMALIZED: "ODB_Wellness_Zeit_Norm",
    ID_WATER_HEATING_ENABLED: "ODB_Heizen_DeAktiv",
    ID_DEVICE_STATUS: "ODB_St_Geraet_Ba",
    ID_ELECTRICITY_PRICE_EUROS: "ODB_GZ_KWh_Energie_Kost",
    ID_WATER_PRICE_EUROS: "ODB_GZ_KW_Volumen_Kost",
    ID_ODB_POSSIBLE_ENERGY_SAVING: "ODB_Gsprt_Energie",
    ID_ODB_ACTUAL_WATER_SAVING: "ODB_Gsprt_KW_Volumen",
    ID_SETPOINT_REQUEST: "ODB_So_WW_T_Anf",
    ID_PROTOCOL_VERSION: "ODB_Protokoll_Ver",
    ID_CO2_EMISSION_RAW: "ODB_CO2_Energie",
    ID_ELECTRICITY_PRICE_CENTS: "ODB_Ct_KWh_Energie_Kost",
    ID_WATER_PRICE_CENTS: "ODB_Ct_KW_Volumen_Kost",
}
ODB_DEBUG_IDS = {name: odb_id for odb_id, name in ODB_DEBUG_NAMES.items()}
ODB_DEBUG_IDS_CASEFOLD = {name.casefold(): odb_id for name, odb_id in ODB_DEBUG_IDS.items()}
ODB_ID_FIELD_KEYS = ("id", "name", "debugName", "debug_name")
ODB_VALUE_COMMANDS = {
    ODB_GET_COMMAND,
    ODB_SET_COMMAND,
    ODB_ASSIGN_COMMAND,
}
ODB_COMMANDS_BY_ACTION = {
    "get": ODB_GET_COMMAND,
    "set": ODB_SET_COMMAND,
    "assign": ODB_ASSIGN_COMMAND,
}

ODB_ERROR_NAMES = {
    0: "ODB_ERR_OK",
    1: "ODB_ERR_OBJ_NOT_FOUND",
    2: "ODB_ERR_MIN_LIMIT",
    3: "ODB_ERR_MAX_LIMIT",
    4: "ODB_ERR_WRONG_OBJECT_STRUCTURE",
    5: "ODB_ERR_VALUE_INDEX_OUT_OF_RANGE",
    6: "ODB_ERR_WRONG_MAXIDX",
    7: "ODB_ERR_WRONG_PSAREA",
}
ODB_ERROR_CODES = {name: code for code, name in ODB_ERROR_NAMES.items()}
ODB_ERROR_CODES_CASEFOLD = {
    name.casefold(): code for name, code in ODB_ERROR_CODES.items()
}


def normalize_odb_id(value: Any) -> int:
    """Return a numeric ODB ID from a raw ID or known debug name."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid ODB id")
    if isinstance(value, int):
        odb_id = value
        if odb_id < 0:
            raise ValueError(f"negative ODB id {value!r}")
        return odb_id
    if isinstance(value, float):
        if value.is_integer():
            return normalize_odb_id(int(value))
        raise ValueError(f"non-integer ODB id {value!r}")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty ODB id")
        if text in ODB_DEBUG_IDS:
            return ODB_DEBUG_IDS[text]
        if text.casefold() in ODB_DEBUG_IDS_CASEFOLD:
            return ODB_DEBUG_IDS_CASEFOLD[text.casefold()]
        return normalize_odb_id(int(text))
    raise ValueError(f"unsupported ODB id {value!r}")


def normalize_odb_error_code(value: Any) -> int:
    """Return a numeric ODB error code from a raw code or DHE debug name."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid ODB error code")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"negative ODB error code {value!r}")
        return value
    if isinstance(value, float):
        if value.is_integer():
            return normalize_odb_error_code(int(value))
        raise ValueError(f"non-integer ODB error code {value!r}")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty ODB error code")
        if text in ODB_ERROR_CODES:
            return ODB_ERROR_CODES[text]
        if text.casefold() in ODB_ERROR_CODES_CASEFOLD:
            return ODB_ERROR_CODES_CASEFOLD[text.casefold()]
        return normalize_odb_error_code(int(text))
    raise ValueError(f"unsupported ODB error code {value!r}")


def odb_error_name(value: Any) -> str:
    """Return the DHE debug name for an ODB error code."""
    try:
        code = normalize_odb_error_code(value)
    except (TypeError, ValueError):
        return "unknown"
    return ODB_ERROR_NAMES.get(code, f"ODB_ERR_{code}")


def normalize_odb_command(command: str, value: Any) -> tuple[str, int] | None:
    """Normalize generic or named ODB commands to a value command and numeric ID."""
    if command in ODB_VALUE_COMMANDS:
        if not isinstance(value, Mapping):
            return None
        odb_id = _normalize_odb_id_fields(value)
        return (command, odb_id) if odb_id is not None else None

    try:
        action, path, name = command.split(":", 2)
    except ValueError:
        return None
    normalized_command = ODB_COMMANDS_BY_ACTION.get(action)
    if normalized_command is None or path != "ste.common.odb" or name == "value":
        return None
    command_odb_id = normalize_odb_id(name)
    if isinstance(value, Mapping):
        payload_odb_id = _normalize_odb_id_fields(value)
        if payload_odb_id is not None and payload_odb_id != command_odb_id:
            raise ValueError(
                f"conflicting ODB command name {name!r} and payload id "
                f"{payload_odb_id!r}"
            )
    return normalized_command, command_odb_id


def _normalize_odb_id_fields(value: Mapping[str, Any]) -> int | None:
    """Return one normalized ODB ID from a payload's possible ID fields."""
    normalized: dict[str, int] = {}
    for key in ODB_ID_FIELD_KEYS:
        if key not in value or _is_empty_odb_id_field(value[key]):
            continue
        try:
            normalized[key] = normalize_odb_id(value[key])
        except ValueError as err:
            raise ValueError(f"invalid ODB {key} {value[key]!r}") from err
    if not normalized:
        return None
    unique_ids = set(normalized.values())
    if len(unique_ids) > 1:
        raise ValueError(f"conflicting ODB id fields {normalized!r}")
    return next(iter(unique_ids))


def _is_empty_odb_id_field(value: Any) -> bool:
    """Return whether a raw ODB ID field is an empty placeholder."""
    return value is None or (isinstance(value, str) and not value.strip())

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
    ID_WATER_PRICE_EUROS: (
        ID_WATER_PRICE,
        ID_WATER_PRICE_EUROS,
        ID_WATER_PRICE_CENTS,
    ),
    ID_WATER_PRICE_CENTS: (
        ID_WATER_PRICE,
        ID_WATER_PRICE_EUROS,
        ID_WATER_PRICE_CENTS,
    ),
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
    ID_ODB_HEATING_ENERGY,
    ID_ODB_HOT_WATER_VOLUME,
    ID_BATH_FILL_CURRENT_VOLUME,
    ID_WATER_HEATING_ENABLED,
    ID_DEVICE_STATUS,
    ID_ELECTRICITY_PRICE_EUROS,
    ID_ELECTRICITY_PRICE_CENTS,
    ID_WATER_PRICE_EUROS,
    ID_WATER_PRICE_CENTS,
    ID_ODB_POSSIBLE_ENERGY_SAVING,
    ID_ODB_ACTUAL_WATER_SAVING,
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
)

ODB_DIRECT_HANDLER_IDS = (
    ID_SETPOINT,
    ID_WATER_FLOW,
    ID_POWER_PERCENT,
    ID_NOMINAL_POWER,
    ID_BATH_FILL_TARGET_VOLUME,
    ID_BATH_FILL_CURRENT_VOLUME,
    ID_PROTOCOL_VERSION,
    ID_WATER_HEATING_ENABLED,
    ID_SCALD_PROTECTION_ACTIVE,
    ID_DEVICE_STATUS,
    ID_CO2_EMISSION_RAW,
    ID_CHILD_SAFETY_ACTIVE,
)
ODB_TENTHS_TEMPERATURE_IDS = (
    ID_INLET_TEMPERATURE,
    ID_OUTLET_TEMPERATURE,
    ID_SCALD_PROTECTION_TEMPERATURE_LIMIT,
)
ODB_NONNEGATIVE_VALUE_IDS = (
    ID_OPERATING_DURATION,
    ID_WELLNESS_TIME_NORMALIZED,
    ID_ODB_HEATING_ENERGY,
    ID_ODB_POSSIBLE_ENERGY_SAVING,
)
ODB_DECILITER_VALUE_IDS = (
    ID_ODB_HOT_WATER_VOLUME,
    ID_ODB_ACTUAL_WATER_SAVING,
)
ODB_ZERO_REQUEST_READBACK_IGNORE_IDS = (
    ID_ODB_HEATING_ENERGY,
    ID_ODB_HOT_WATER_VOLUME,
    ID_ODB_POSSIBLE_ENERGY_SAVING,
    ID_ODB_ACTUAL_WATER_SAVING,
    ID_WELLNESS_TIME_NORMALIZED,
)
ODB_IGNORED_VALUE_IDS = (
    ID_SETPOINT_REQUEST,
)

BRUSH_TIMER_PATH = "ste.app.brushTimer"
SHOWER_TIMER_PATH = "ste.app.showerTimer"
BRUSH_TIMER_DEFAULT_DURATION_MINUTES = 3.0
SHOWER_TIMER_DEFAULT_DURATION_MINUTES = 5.0
TIMER_DEFAULT_DURATIONS = {
    BRUSH_TIMER_PATH: BRUSH_TIMER_DEFAULT_DURATION_MINUTES,
    SHOWER_TIMER_PATH: SHOWER_TIMER_DEFAULT_DURATION_MINUTES,
}
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
APP_TIMER_VALUE_COMMANDS = (
    APP_TIMER_SET_COMMANDS
    | APP_TIMER_ASSIGN_COMMANDS
    | set(APP_TIMER_REQUEST_COMMANDS)
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

WELLNESS_PROGRAMS_GET_COMMAND = "get:ste.app.wellness:programs"
WELLNESS_PROGRAMS_SET_COMMAND = "set:ste.app.wellness:programs"

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

CONTROLUNIT_NAME_GET_COMMAND = "get:ste.common.version:controlunitName"
CONTROLUNIT_NAME_SET_COMMAND = "set:ste.common.version:controlunitName"
CONTROLUNIT_NAME_ASSIGN_COMMAND = "assign:ste.common.version:controlunitName"
CONTROLUNIT_NAME_MAX_LENGTH = 30

DEVICE_INFO_SET_COMMANDS = (
    "set:ste.common.version:contactData",
    "set:ste.common.version:orderNumber",
    "set:ste.common.version:gadgetData",
    "set:ste.common.version:gadgetDataValid",
    CONTROLUNIT_NAME_SET_COMMAND,
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
    WELLNESS_PROGRAMS_GET_COMMAND,
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

__all__ = tuple(
    sorted(name for name in globals() if name.isupper() or name.startswith("ID_"))
)
