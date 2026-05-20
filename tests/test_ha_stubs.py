"""Shared lightweight stubs for Home Assistant modules in unit tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
import sys
import types


def ensure_homeassistant_stubs() -> None:
    """Install a tiny Home Assistant stub when dependency is unavailable.

    These stubs are intentionally minimal and only provide objects needed for
    module import and lightweight behavior assertions in this test suite.
    """
    def _module(*parts: str) -> types.ModuleType:
        name = ".".join(parts)
        module = types.ModuleType(name)
        sys.modules[name] = module
        return module

    class _Units(str):
        def __new__(cls, value: str) -> _Units:
            return str.__new__(cls, value)

    def _ensure_constant(module: types.ModuleType, name: str, value: Any) -> None:
        if not hasattr(module, name):
            setattr(module, name, value)

    def _ensure_units(
        module: types.ModuleType,
        name: str,
        attrs: dict[str, Any],
    ) -> None:
        existing = getattr(module, name, None)
        if existing is None:
            existing = type(name, (_Units,), {})
            setattr(module, name, existing)
        for attr_name, attr_value in attrs.items():
            if not hasattr(existing, attr_name):
                setattr(existing, attr_name, attr_value)

    if "homeassistant" in sys.modules:
        homeassistant = sys.modules["homeassistant"]
        if not hasattr(homeassistant, "__path__"):
            homeassistant.__path__ = []

        const = sys.modules.get("homeassistant.const")
        if const is None:
            const = _module("homeassistant.const")
            homeassistant.const = const
        homeassistant.const = const

        _ensure_constant(const, "PERCENTAGE", "%")
        _ensure_constant(const, "CONF_HOST", "host")
        _ensure_constant(const, "CONF_NAME", "name")
        _ensure_constant(const, "CONF_PORT", "port")
        _ensure_constant(const, "ATTR_TEMPERATURE", "temperature")
        _ensure_units(const, "UnitOfEnergy", {"KILO_WATT_HOUR": "kWh"})
        _ensure_units(const, "UnitOfMass", {"KILOGRAMS": "kg"})
        _ensure_units(const, "UnitOfPower", {"KILO_WATT": "kW"})
        _ensure_units(const, "UnitOfTemperature", {"CELSIUS": "°C", "C": "°C"})
        _ensure_units(const, "UnitOfTime", {"HOURS": "h", "SECONDS": "s"})
        _ensure_units(const, "UnitOfVolume", {"LITERS": "l", "CUBIC_METERS": "m3"})
        _ensure_units(
            const,
            "UnitOfVolumeFlowRate",
            {"LITERS_PER_MINUTE": "L/min", "CUBIC_METERS_PER_HOUR": "m3/h"},
        )

        if not hasattr(const, "Platform"):

            class Platform(str):
                BINARY_SENSOR = "binary_sensor"
                CLIMATE = "climate"
                MEDIA_PLAYER = "media_player"
                WEATHER = "weather"
                SENSOR = "sensor"
                SELECT = "select"
                TEXT = "text"
                NUMBER = "number"
                SWITCH = "switch"
                BUTTON = "button"

            const.Platform = Platform

        components = sys.modules.get("homeassistant.components")
        if components is None:
            components = _module("homeassistant.components")
        homeassistant.components = components
        if not hasattr(components, "__path__"):
            components.__path__ = []
        if not hasattr(components, "persistent_notification"):
            persistent_notification = _module(
                "homeassistant.components.persistent_notification"
            )

            async def async_create(*_args: Any, **_kwargs: Any) -> None:
                return None

            persistent_notification.async_create = async_create
            components.persistent_notification = persistent_notification
        if not hasattr(components, "diagnostics"):
            diagnostics = _module("homeassistant.components.diagnostics")
            diagnostics.REDACTED = "**REDACTED**"

            def async_redact_data(value: Any, keys: set[str]) -> Any:
                if isinstance(value, dict):
                    return {
                        key: (
                            diagnostics.REDACTED
                            if str(key) in keys
                            else async_redact_data(item, keys)
                        )
                        for key, item in value.items()
                    }
                if isinstance(value, list):
                    return [async_redact_data(item, keys) for item in value]
                return value

            diagnostics.async_redact_data = async_redact_data
            components.diagnostics = diagnostics
        if not hasattr(components, "sensor"):
            from dataclasses import dataclass, field

            sensor = _module("homeassistant.components.sensor")

            class SensorDeviceClass:
                ENUM = "enum"
                WATER = "water"
                DURATION = "duration"
                TEMPERATURE = "temperature"
                VOLUME_FLOW_RATE = "volume_flow_rate"
                POWER = "power"
                ENERGY = "energy"
                MONETARY = "monetary"

            class SensorStateClass:
                MEASUREMENT = "measurement"
                TOTAL = "total"
                TOTAL_INCREASING = "total_increasing"

            class SensorEntity:
                pass

            @dataclass(frozen=True, kw_only=True)
            class SensorEntityDescription:
                key: str | None = None
                name: str | None = None
                translation_key: str | None = None
                icon: str | None = None
                device_class: str | None = None
                state_class: str | None = None
                unit_of_measurement: str | None = None
                native_unit_of_measurement: str | None = None
                entity_registry_enabled_default: bool = True
                entity_category: str | None = None
                options: list[str] | tuple[str, ...] | None = None
                suggested_display_precision: int | None = None
                device_class_enum: str | None = None
                class_: str | None = None
                has_entity_name: bool | None = None
                icon_disabled: str | None = None
                entity_registry_disabled_default: bool = field(
                    default=False,
                    repr=False,
                )

            sensor.SensorDeviceClass = SensorDeviceClass
            sensor.SensorStateClass = SensorStateClass
            sensor.SensorEntity = SensorEntity
            sensor.SensorEntityDescription = SensorEntityDescription
            components.sensor = sensor
        if not hasattr(components, "climate"):
            climate = _module("homeassistant.components.climate")
            climate_const = _module("homeassistant.components.climate.const")

            class ClimateEntity:
                pass

            class ClimateEntityFeature:
                TARGET_TEMPERATURE = 1
                TURN_ON = 2
                TURN_OFF = 4

            class HVACMode:
                HEAT = "heat"
                OFF = "off"

            climate.ClimateEntity = ClimateEntity
            climate_const.ClimateEntityFeature = ClimateEntityFeature
            climate_const.HVACMode = HVACMode
            components.climate = climate

        if not hasattr(components, "switch"):
            from dataclasses import dataclass

            switch = _module("homeassistant.components.switch")

            class SwitchEntity:
                pass

            @dataclass(frozen=True, kw_only=True)
            class SwitchEntityDescription:
                key: str | None = None
                name: str | None = None
                translation_key: str | None = None
                icon: str | None = None
                entity_category: str | None = None

            switch.SwitchEntity = SwitchEntity
            switch.SwitchEntityDescription = SwitchEntityDescription
            components.switch = switch

        helpers = sys.modules.get("homeassistant.helpers")
        if helpers is None:
            helpers = _module("homeassistant.helpers")
        homeassistant.helpers = helpers
        if not hasattr(helpers, "__path__"):
            helpers.__path__ = []

        if "homeassistant.helpers.entity" not in sys.modules:
            entity = _module("homeassistant.helpers.entity")

            class EntityCategory:
                CONFIG = "config"
                DIAGNOSTIC = "diagnostic"

            entity.EntityCategory = EntityCategory
            helpers.entity = entity

        if "homeassistant.helpers.entity_platform" not in sys.modules:
            entity_platform = _module("homeassistant.helpers.entity_platform")
            AddEntitiesCallback = Callable[[list[Any]], None]
            entity_platform.AddEntitiesCallback = AddEntitiesCallback
            helpers.entity_platform = entity_platform

        if "homeassistant.helpers.aiohttp_client" not in sys.modules:
            aiohttp_client = _module("homeassistant.helpers.aiohttp_client")

            async def async_get_clientsession(*_args: Any, **_kwargs: Any) -> Any:
                return object()

            aiohttp_client.async_get_clientsession = async_get_clientsession
            helpers.aiohttp_client = aiohttp_client

        if not hasattr(homeassistant, "config_entries"):
            config_entries = _module("homeassistant.config_entries")

            class ConfigEntry:
                pass

            config_entries.ConfigEntry = ConfigEntry
            homeassistant.config_entries = config_entries

        if not hasattr(homeassistant, "core"):
            core = _module("homeassistant.core")

            class HomeAssistant:
                """Marker type used for annotations."""

            def callback(func: Callable[..., Any]) -> Callable[..., Any]:
                return func

            core.HomeAssistant = HomeAssistant
            core.callback = callback
            homeassistant.core = core

        if "homeassistant.exceptions" not in sys.modules:
            exceptions = _module("homeassistant.exceptions")

            class HomeAssistantError(Exception):
                """Minimal HA exception stub."""

            exceptions.HomeAssistantError = HomeAssistantError
            homeassistant.exceptions = exceptions

        return
    homeassistant = types.ModuleType("homeassistant")
    components = _module("homeassistant.components")
    helpers = _module("homeassistant.helpers")

    homeassistant.components = components
    homeassistant.helpers = helpers
    homeassistant.__path__ = []
    components.__path__ = []
    helpers.__path__ = []

    # core
    core = _module("homeassistant.core")

    class HomeAssistant:
        """Marker type used for annotations."""

    def callback(func: Callable[..., Any]) -> Callable[..., Any]:
        return func

    core.HomeAssistant = HomeAssistant
    core.callback = callback

    # exceptions
    exceptions = _module("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        """Minimal HA exception stub."""

    exceptions.HomeAssistantError = HomeAssistantError

    # components
    persistent_notification = _module(
        "homeassistant.components.persistent_notification"
    )

    async def async_create(*_args: Any, **_kwargs: Any) -> None:
        return None

    persistent_notification.async_create = async_create
    components.persistent_notification = persistent_notification

    diagnostics = _module("homeassistant.components.diagnostics")
    diagnostics.REDACTED = "**REDACTED**"

    def async_redact_data(value: Any, keys: set[str]) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    diagnostics.REDACTED
                    if str(key) in keys
                    else async_redact_data(item, keys)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [async_redact_data(item, keys) for item in value]
        return value

    diagnostics.async_redact_data = async_redact_data
    components.diagnostics = diagnostics

    sensor = _module("homeassistant.components.sensor")

    class SensorDeviceClass:
        ENUM = "enum"
        WATER = "water"
        DURATION = "duration"
        TEMPERATURE = "temperature"
        VOLUME_FLOW_RATE = "volume_flow_rate"
        POWER = "power"
        ENERGY = "energy"
        MONETARY = "monetary"

    class SensorStateClass:
        MEASUREMENT = "measurement"
        TOTAL = "total"
        TOTAL_INCREASING = "total_increasing"

    class SensorEntity:
        pass

    from dataclasses import dataclass, field

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        """Minimal stand-in for HA SensorEntityDescription.

        The real class is a dataclass with keyword-only arguments. A lightweight
        version is required here so integration imports can build dataclass
        subclasses in tests.
        """

        key: str | None = None
        name: str | None = None
        translation_key: str | None = None
        icon: str | None = None
        device_class: str | None = None
        state_class: str | None = None
        unit_of_measurement: str | None = None
        native_unit_of_measurement: str | None = None
        entity_registry_enabled_default: bool = True
        entity_category: str | None = None
        options: list[str] | tuple[str, ...] | None = None
        suggested_display_precision: int | None = None
        device_class_enum: str | None = None
        class_: str | None = None
        has_entity_name: bool | None = None
        icon_disabled: str | None = None
        entity_registry_disabled_default: bool = field(default=False, repr=False)

    sensor.SensorDeviceClass = SensorDeviceClass
    sensor.SensorStateClass = SensorStateClass
    sensor.SensorEntity = SensorEntity
    sensor.SensorEntityDescription = SensorEntityDescription
    components.sensor = sensor

    climate = _module("homeassistant.components.climate")
    climate_const = _module("homeassistant.components.climate.const")

    class ClimateEntity:
        pass

    class ClimateEntityFeature:
        TARGET_TEMPERATURE = 1
        TURN_ON = 2
        TURN_OFF = 4

    class HVACMode:
        HEAT = "heat"
        OFF = "off"

    climate.ClimateEntity = ClimateEntity
    climate_const.ClimateEntityFeature = ClimateEntityFeature
    climate_const.HVACMode = HVACMode
    components.climate = climate

    switch = _module("homeassistant.components.switch")

    class SwitchEntity:
        pass

    @dataclass(frozen=True, kw_only=True)
    class SwitchEntityDescription:
        key: str | None = None
        name: str | None = None
        translation_key: str | None = None
        icon: str | None = None
        entity_category: str | None = None

    switch.SwitchEntity = SwitchEntity
    switch.SwitchEntityDescription = SwitchEntityDescription
    components.switch = switch

    # constants
    const = _module("homeassistant.const")

    class _Energy(_Units):
        KILO_WATT_HOUR = "kWh"

    class _Mass(_Units):
        KILOGRAMS = "kg"

    class _Power(_Units):
        KILO_WATT = "kW"

    class _Temperature(_Units):
        CELSIUS = "°C"

    class _Time(_Units):
        HOURS = "h"
        SECONDS = "s"

    class _Volume(_Units):
        LITERS = "l"
        CUBIC_METERS = "m3"

    class _VolumeFlowRate(_Units):
        LITERS_PER_MINUTE = "L/min"
        CUBIC_METERS_PER_HOUR = "m3/h"

    const.PERCENTAGE = "%"
    const.CONF_HOST = "host"
    const.CONF_NAME = "name"
    const.CONF_PORT = "port"
    const.ATTR_TEMPERATURE = "temperature"
    const.UnitOfEnergy = _Energy
    const.UnitOfMass = _Mass
    const.UnitOfPower = _Power
    const.UnitOfTemperature = _Temperature
    const.UnitOfTime = _Time
    const.UnitOfVolume = _Volume
    const.UnitOfVolumeFlowRate = _VolumeFlowRate
    class Platform(str):
        BINARY_SENSOR = "binary_sensor"
        CLIMATE = "climate"
        MEDIA_PLAYER = "media_player"
        WEATHER = "weather"
        SENSOR = "sensor"
        SELECT = "select"
        TEXT = "text"
        NUMBER = "number"
        SWITCH = "switch"
        BUTTON = "button"

    const.Platform = Platform

    # helpers
    entity = _module("homeassistant.helpers.entity")

    class EntityCategory:
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    entity.EntityCategory = EntityCategory
    entity_platform = _module("homeassistant.helpers.entity_platform")

    AddEntitiesCallback = Callable[[list[Any]], None]
    entity_platform.AddEntitiesCallback = AddEntitiesCallback

    aiohttp_client = _module("homeassistant.helpers.aiohttp_client")

    async def async_get_clientsession(*_args: Any, **_kwargs: Any) -> Any:
        return object()

    aiohttp_client.async_get_clientsession = async_get_clientsession
    helpers.entity = entity
    helpers.entity_platform = entity_platform
    helpers.aiohttp_client = aiohttp_client

    # config_entries
    config_entries = _module("homeassistant.config_entries")

    class ConfigEntry:
        pass

    config_entries.ConfigEntry = ConfigEntry

    # wire package graph
    homeassistant.components = components
    homeassistant.helpers = helpers
    homeassistant.config_entries = config_entries
    homeassistant.const = const
    homeassistant.core = core
    homeassistant.exceptions = exceptions
    sys.modules["homeassistant"] = homeassistant
