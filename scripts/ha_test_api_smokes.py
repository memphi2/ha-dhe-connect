"""Live Home Assistant API smoke flows for the DHE test installation."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import time
from typing import Any, Protocol

DEFAULT_CLIMATE_ENTITY = "climate.dhe_connect_water_heating"
DEFAULT_RADIO_ENTITY = "media_player.dhe_connect_radio"
DEFAULT_TIMER_SWITCH_ENTITY = "switch.dhe_connect_brush_timer"
DEFAULT_TIMER_REMAINING_ENTITY = "sensor.dhe_connect_brush_timer_remaining"
DEFAULT_TIMER_DURATION_ENTITY = "number.dhe_connect_brush_timer_seconds"
DEFAULT_ENTITY_SMOKE_ENTITIES = (
    DEFAULT_CLIMATE_ENTITY,
    DEFAULT_RADIO_ENTITY,
    "weather.dhe_connect",
    "sensor.dhe_connect_connection_state",
    "sensor.dhe_connect_device_status",
    "sensor.dhe_connect_current_water_flow",
    "sensor.dhe_connect_current_power_consumption",
    DEFAULT_TIMER_REMAINING_ENTITY,
    "sensor.dhe_connect_shower_timer_remaining",
    DEFAULT_TIMER_SWITCH_ENTITY,
    "switch.dhe_connect_shower_timer",
    DEFAULT_TIMER_DURATION_ENTITY,
    "number.dhe_connect_shower_timer_seconds",
)
RADIO_SOURCE_SETTLE_SECONDS = 5.0
DEFAULT_RADIO_AUTO_OFF_SECONDS = 30.0
DEFAULT_TIMER_SMOKE_DURATION_SECONDS = 60.0
DEFAULT_TIMER_SMOKE_OBSERVE_SECONDS = 8.0
DEFAULT_TIMER_SMOKE_EXPIRY_GRACE_SECONDS = 12.0
BAD_ENTITY_STATES = {"unavailable", "unknown"}
WATER_RUNNING_DEVICE_STATES = {"status_2", "status_4"}


class HomeAssistantApiLike(Protocol):
    """Small protocol used by live API smoke flows."""

    def get_state(self, access_token: str, entity_id: str) -> dict[str, Any]:
        """Return one HA state object."""

    def get_states(self, access_token: str) -> list[dict[str, Any]]:
        """Return all HA state objects."""

    def call_service(
        self,
        access_token: str,
        domain: str,
        service: str,
        payload: dict[str, Any],
        *,
        timeout: float = 20.0,
    ) -> list[dict[str, Any]]:
        """Call a HA service and return changed states."""


@dataclass(frozen=True)
class ServiceSmokeResult:
    """One HA service-smoke result line."""

    ok: bool
    message: str
    level: str = "PASS"


def run_service_smoke(
    api: HomeAssistantApiLike,
    access_token: str,
    *,
    climate_entity: str,
    radio_entity: str,
    radio_auto_off_seconds: float = DEFAULT_RADIO_AUTO_OFF_SECONDS,
) -> list[ServiceSmokeResult]:
    """Exercise the DHE climate and radio services."""
    results: list[ServiceSmokeResult] = [
        _info("SERVICE smoke: checking DHE device status before active service calls")
    ]
    device_status = _dhe_device_status(api, access_token)
    if device_status in WATER_RUNNING_DEVICE_STATES:
        return [
            *results,
            ServiceSmokeResult(
                True,
                "SERVICE skipped because water is running "
                f"device_status={device_status!r}",
            ),
        ]

    results.append(_info("SERVICE smoke: toggling water-heating climate off and on"))
    climate_before = api.get_state(access_token, climate_entity)
    climate_before_state = str(climate_before.get("state") or "")
    results.append(
        ServiceSmokeResult(
            True,
            "CLIMATE before "
            f"state={climate_before.get('state')} "
            f"target={climate_before.get('attributes', {}).get('temperature')}",
        )
    )
    changed = api.call_service(
        access_token,
        "climate",
        "turn_off",
        {"entity_id": climate_entity},
    )
    results.append(
        ServiceSmokeResult(True, f"SERVICE climate.turn_off changed={len(changed)}")
    )
    time.sleep(5)
    climate_off = api.get_state(access_token, climate_entity)
    climate_off_state = climate_off.get("state")
    results.append(
        ServiceSmokeResult(
            climate_off_state == "off",
            f"CLIMATE off state={climate_off_state}",
        )
    )
    changed = api.call_service(
        access_token,
        "climate",
        "turn_on",
        {"entity_id": climate_entity},
    )
    results.append(
        ServiceSmokeResult(True, f"SERVICE climate.turn_on changed={len(changed)}")
    )
    time.sleep(5)
    climate_on = api.get_state(access_token, climate_entity)
    climate_on_state = climate_on.get("state")
    results.append(
        ServiceSmokeResult(
            climate_on_state not in {"off", "unavailable", "unknown"},
            f"CLIMATE on state={climate_on_state}",
        )
    )

    results.append(_info("SERVICE smoke: selecting a radio source and restoring state"))
    radio_before = api.get_state(access_token, radio_entity)
    radio_before_state = str(radio_before.get("state") or "")
    radio_attrs = radio_before.get("attributes", {})
    sources = radio_attrs.get("source_list") or []
    current_source = radio_attrs.get("source")
    results.append(
        ServiceSmokeResult(
            True,
            "RADIO before "
            f"state={radio_before.get('state')} source={current_source!r} "
            f"sources={len(sources)}",
        )
    )
    if not sources:
        results.append(ServiceSmokeResult(True, "RADIO skipped: no sources"))
        _restore_climate_if_needed(api, access_token, climate_entity, climate_before_state)
        return results

    selected_source = next((source for source in sources if source != current_source), sources[0])
    try:
        results.extend(
            _exercise_radio_source(
                api,
                access_token,
                radio_entity,
                selected_source,
                radio_auto_off_seconds,
            )
        )
    finally:
        results.append(
            _restore_radio(
                api,
                access_token,
                radio_entity,
                current_source,
                sources,
                radio_before_state,
            )
        )
        _restore_climate_if_needed(api, access_token, climate_entity, climate_before_state)
    return results


def _exercise_radio_source(
    api: HomeAssistantApiLike,
    access_token: str,
    radio_entity: str,
    selected_source: str,
    radio_auto_off_seconds: float,
) -> list[ServiceSmokeResult]:
    results: list[ServiceSmokeResult] = []
    changed = api.call_service(
        access_token,
        "media_player",
        "turn_off",
        {"entity_id": radio_entity},
    )
    results.append(
        ServiceSmokeResult(True, f"SERVICE media_player.turn_off changed={len(changed)}")
    )
    time.sleep(3)
    changed = api.call_service(
        access_token,
        "media_player",
        "select_source",
        {"entity_id": radio_entity, "source": selected_source},
    )
    results.append(
        ServiceSmokeResult(
            True,
            f"SERVICE media_player.select_source changed={len(changed)}",
        )
    )
    time.sleep(RADIO_SOURCE_SETTLE_SECONDS)
    radio_after = api.get_state(access_token, radio_entity)
    radio_after_attrs = radio_after.get("attributes", {})
    radio_after_state = radio_after.get("state")
    radio_after_source = radio_after_attrs.get("source")
    results.append(
        ServiceSmokeResult(
            radio_after_source == selected_source
            and radio_after_state not in {"off", "unavailable", "unknown"},
            "RADIO after "
            f"state={radio_after_state} "
            f"source={radio_after_source!r} selected={selected_source!r}",
        )
    )
    remaining_radio_on_seconds = max(
        0.0,
        float(radio_auto_off_seconds) - RADIO_SOURCE_SETTLE_SECONDS,
    )
    if remaining_radio_on_seconds > 0:
        time.sleep(remaining_radio_on_seconds)
    return results


def _restore_radio(
    api: HomeAssistantApiLike,
    access_token: str,
    radio_entity: str,
    current_source: object,
    sources: object,
    radio_before_state: str,
) -> ServiceSmokeResult:
    if (
        isinstance(current_source, str)
        and isinstance(sources, list)
        and current_source in sources
    ):
        with contextlib.suppress(Exception):  # noqa: BLE001
            api.call_service(
                access_token,
                "media_player",
                "select_source",
                {"entity_id": radio_entity, "source": current_source},
            )
            time.sleep(RADIO_SOURCE_SETTLE_SECONDS)
    restore_service = (
        "turn_off"
        if radio_before_state in {"off", "idle", "standby", "unknown", "unavailable"}
        else "turn_on"
    )
    changed = api.call_service(
        access_token,
        "media_player",
        restore_service,
        {"entity_id": radio_entity},
    )
    time.sleep(3)
    restored_radio = api.get_state(access_token, radio_entity)
    restored_radio_state = restored_radio.get("state")
    restored_ok = (
        restored_radio_state == "off"
        if restore_service == "turn_off"
        else restored_radio_state not in {"off", "unavailable", "unknown"}
    )
    return ServiceSmokeResult(
        restored_ok,
        "SERVICE media_player.restore_after_smoke "
        f"service={restore_service} changed={len(changed)} "
        f"state={restored_radio_state!r}",
    )


def _restore_climate_if_needed(
    api: HomeAssistantApiLike,
    access_token: str,
    climate_entity: str,
    climate_before_state: str,
) -> None:
    if climate_before_state == "off":
        with contextlib.suppress(Exception):  # noqa: BLE001
            api.call_service(
                access_token,
                "climate",
                "turn_off",
                {"entity_id": climate_entity},
            )


def run_entity_smoke(
    api: HomeAssistantApiLike,
    access_token: str,
    *,
    entity_ids: tuple[str, ...] = DEFAULT_ENTITY_SMOKE_ENTITIES,
    disabled_entity_ids: set[str] | None = None,
) -> list[ServiceSmokeResult]:
    """Check important DHE entities through the live HA state API."""
    disabled_entity_ids = disabled_entity_ids or set()
    results: list[ServiceSmokeResult] = [
        _info(f"ENTITY smoke: reading {len(entity_ids)} core DHE states from HA")
    ]
    states = {
        str(state.get("entity_id")): state
        for state in api.get_states(access_token)
        if state.get("entity_id")
    }
    for entity_id in entity_ids:
        state = states.get(entity_id)
        if state is None:
            if entity_id in disabled_entity_ids:
                results.append(
                    ServiceSmokeResult(
                        True,
                        f"ENTITY skipped disabled-by-integration {entity_id}",
                    )
                )
                continue
            results.append(ServiceSmokeResult(False, f"ENTITY missing {entity_id}"))
            continue
        results.extend(_entity_smoke_results(entity_id, state))
    return results


def _entity_smoke_results(
    entity_id: str,
    state: dict[str, Any],
) -> list[ServiceSmokeResult]:
    state_value = str(state.get("state") or "")
    attributes = state.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}

    results = [
        ServiceSmokeResult(
            state_value not in BAD_ENTITY_STATES,
            f"ENTITY {entity_id} state={state_value!r}",
        )
    ]
    if entity_id.startswith("media_player."):
        sources = attributes.get("source_list") or []
        results.append(
            ServiceSmokeResult(
                isinstance(sources, list) and len(sources) > 0,
                f"ENTITY {entity_id} source_list={len(sources) if isinstance(sources, list) else 0}",
            )
        )
    elif entity_id.startswith("climate."):
        results.append(
            ServiceSmokeResult(
                _state_float(attributes.get("temperature")) is not None,
                f"ENTITY {entity_id} target={attributes.get('temperature')!r}",
            )
        )
    elif entity_id.startswith("number."):
        results.append(
            ServiceSmokeResult(
                _state_float(state_value) is not None,
                f"ENTITY {entity_id} numeric={state_value!r}",
            )
        )
    elif entity_id.startswith("switch."):
        results.append(
            ServiceSmokeResult(
                state_value in {"off", "on"},
                f"ENTITY {entity_id} switch_state={state_value!r}",
            )
        )
    elif entity_id.endswith("_timer_remaining"):
        results.append(
            ServiceSmokeResult(
                _timer_state_seconds(state_value) is not None,
                f"ENTITY {entity_id} timer={state_value!r}",
            )
        )
    elif entity_id.endswith("_connection_state"):
        results.append(
            ServiceSmokeResult(
                state_value == "connected",
                f"ENTITY {entity_id} connected={state_value!r}",
            )
        )
    elif entity_id.endswith(("_current_water_flow", "_current_power_consumption")):
        results.append(
            ServiceSmokeResult(
                _state_float(state_value) is not None,
                f"ENTITY {entity_id} numeric={state_value!r}",
            )
        )
    return results


def run_timer_smoke(
    api: HomeAssistantApiLike,
    access_token: str,
    *,
    switch_entity: str,
    remaining_entity: str,
    duration_entity: str,
    duration_seconds: float = DEFAULT_TIMER_SMOKE_DURATION_SECONDS,
    observe_seconds: float = DEFAULT_TIMER_SMOKE_OBSERVE_SECONDS,
    expiry_grace_seconds: float = DEFAULT_TIMER_SMOKE_EXPIRY_GRACE_SECONDS,
) -> list[ServiceSmokeResult]:
    """Exercise a DHE timer countdown, expiry and reset-to-duration behavior."""
    results: list[ServiceSmokeResult] = [
        _info("TIMER smoke: reading original duration and checking water status")
    ]
    duration_before = api.get_state(access_token, duration_entity)
    original_duration = _state_float(duration_before.get("state"))
    changed_timer = False
    results.append(
        ServiceSmokeResult(
            original_duration is not None,
            f"TIMER duration before state={duration_before.get('state')!r}",
        )
    )

    try:
        device_status = _dhe_device_status(api, access_token)
        if device_status in WATER_RUNNING_DEVICE_STATES:
            results.append(
                ServiceSmokeResult(
                    True,
                    "TIMER skipped because water is running "
                    f"device_status={device_status!r}",
                )
            )
            return results

        changed_timer = True
        results.extend(
            _exercise_timer(
                api,
                access_token,
                switch_entity,
                remaining_entity,
                duration_entity,
                duration_seconds,
                observe_seconds,
                expiry_grace_seconds,
            )
        )
    finally:
        if changed_timer:
            _restore_timer(
                api,
                access_token,
                switch_entity,
                duration_entity,
                original_duration,
            )
    return results


def _exercise_timer(
    api: HomeAssistantApiLike,
    access_token: str,
    switch_entity: str,
    remaining_entity: str,
    duration_entity: str,
    duration_seconds: float,
    observe_seconds: float,
    expiry_grace_seconds: float,
) -> list[ServiceSmokeResult]:
    results = _prepare_timer(
        api,
        access_token,
        remaining_entity,
        duration_entity,
        duration_seconds,
    )
    results.extend(
        _observe_timer_countdown(
            api,
            access_token,
            switch_entity,
            remaining_entity,
            duration_seconds,
            observe_seconds,
        )
    )
    results.extend(
        _stop_and_restart_timer(
            api,
            access_token,
            switch_entity,
            remaining_entity,
            duration_seconds,
        )
    )
    results.extend(
        _wait_timer_expiry(
            api,
            access_token,
            switch_entity,
            remaining_entity,
            duration_entity,
            duration_seconds,
            expiry_grace_seconds,
        )
    )
    return results


def _prepare_timer(
    api: HomeAssistantApiLike,
    access_token: str,
    remaining_entity: str,
    duration_entity: str,
    duration_seconds: float,
) -> list[ServiceSmokeResult]:
    results = [_info("TIMER smoke: setting a temporary short duration")]
    api.call_service(
        access_token,
        "number",
        "set_value",
        {"entity_id": duration_entity, "value": duration_seconds},
    )
    time.sleep(2)
    prepared = api.get_state(access_token, remaining_entity)
    prepared_seconds = _timer_state_seconds(prepared.get("state"))
    results.append(
        ServiceSmokeResult(
            prepared_seconds is not None and abs(prepared_seconds - duration_seconds) <= 2,
            (
                "TIMER prepared "
                f"remaining={prepared.get('state')!r} duration={duration_seconds:g}s"
            ),
        )
    )
    return results


def _observe_timer_countdown(
    api: HomeAssistantApiLike,
    access_token: str,
    switch_entity: str,
    remaining_entity: str,
    duration_seconds: float,
    observe_seconds: float,
) -> list[ServiceSmokeResult]:
    results = [_info("TIMER smoke: starting timer and observing countdown")]
    api.call_service(
        access_token,
        "switch",
        "turn_on",
        {"entity_id": switch_entity},
    )
    observed: list[int] = []
    deadline = time.monotonic() + max(1.0, observe_seconds)
    while time.monotonic() <= deadline:
        state = api.get_state(access_token, remaining_entity)
        seconds = _timer_state_seconds(state.get("state"))
        if seconds is not None:
            observed.append(seconds)
        time.sleep(1)
    descending_pairs = sum(
        1 for left, right in zip(observed, observed[1:]) if right < left
    )
    results.append(
        ServiceSmokeResult(
            len(set(observed)) >= 3 and descending_pairs >= 2,
            f"TIMER countdown observed={observed}",
        )
    )
    return results


def _stop_and_restart_timer(
    api: HomeAssistantApiLike,
    access_token: str,
    switch_entity: str,
    remaining_entity: str,
    duration_seconds: float,
) -> list[ServiceSmokeResult]:
    results = [_info("TIMER smoke: stopping timer and waiting for DHE readback sync")]
    api.call_service(
        access_token,
        "switch",
        "turn_off",
        {"entity_id": switch_entity},
    )
    time.sleep(3)
    stopped_remaining = api.get_state(access_token, remaining_entity)
    stopped_switch = api.get_state(access_token, switch_entity)
    stopped_seconds = _timer_state_seconds(stopped_remaining.get("state"))
    results.append(
        ServiceSmokeResult(
            stopped_switch.get("state") == "off"
            and stopped_seconds is not None
            and 0 < stopped_seconds < duration_seconds,
            (
                "TIMER stopped after DHE sync "
                f"switch={stopped_switch.get('state')!r} "
                f"remaining={stopped_remaining.get('state')!r}"
            ),
        )
    )

    results.append(_info("TIMER smoke: rapidly restarting timer after stop"))
    api.call_service(
        access_token,
        "switch",
        "turn_on",
        {"entity_id": switch_entity},
    )
    time.sleep(1)
    rapid_on_remaining = api.get_state(access_token, remaining_entity)
    rapid_on_seconds = _timer_state_seconds(rapid_on_remaining.get("state"))
    time.sleep(2)
    rapid_after_remaining = api.get_state(access_token, remaining_entity)
    rapid_after_seconds = _timer_state_seconds(rapid_after_remaining.get("state"))
    results.append(
        ServiceSmokeResult(
            rapid_on_seconds is not None
            and rapid_after_seconds is not None
            and rapid_after_seconds < rapid_on_seconds,
            (
                "TIMER rapid restart countdown "
                f"from={rapid_on_remaining.get('state')!r} "
                f"to={rapid_after_remaining.get('state')!r}"
            ),
        )
    )
    api.call_service(
        access_token,
        "switch",
        "turn_off",
        {"entity_id": switch_entity},
    )
    time.sleep(2)
    return results


def _wait_timer_expiry(
    api: HomeAssistantApiLike,
    access_token: str,
    switch_entity: str,
    remaining_entity: str,
    duration_entity: str,
    duration_seconds: float,
    expiry_grace_seconds: float,
) -> list[ServiceSmokeResult]:
    results = [_info("TIMER smoke: resetting duration and waiting for natural expiry")]
    api.call_service(
        access_token,
        "number",
        "set_value",
        {"entity_id": duration_entity, "value": duration_seconds},
    )
    time.sleep(2)
    reset_for_expiry = api.get_state(access_token, remaining_entity)
    reset_for_expiry_seconds = _timer_state_seconds(reset_for_expiry.get("state"))
    results.append(
        ServiceSmokeResult(
            reset_for_expiry_seconds is not None
            and abs(reset_for_expiry_seconds - duration_seconds) <= 2,
            f"TIMER reset for expiry remaining={reset_for_expiry.get('state')!r}",
        )
    )
    api.call_service(
        access_token,
        "switch",
        "turn_on",
        {"entity_id": switch_entity},
    )

    expiry_deadline = time.monotonic() + max(1.0, duration_seconds) + expiry_grace_seconds
    expired_state: dict[str, Any] | None = None
    while time.monotonic() <= expiry_deadline:
        remaining = api.get_state(access_token, remaining_entity)
        switch = api.get_state(access_token, switch_entity)
        remaining_seconds = _timer_state_seconds(remaining.get("state"))
        if (
            switch.get("state") == "off"
            and remaining_seconds is not None
            and abs(remaining_seconds - duration_seconds) <= 2
        ):
            expired_state = {
                "switch": switch.get("state"),
                "remaining": remaining.get("state"),
            }
            break
        time.sleep(2)
    results.append(
        ServiceSmokeResult(
            expired_state is not None,
            (
                "TIMER expiry reset "
                f"state={expired_state if expired_state is not None else 'not reached'}"
            ),
        )
    )
    return results


def _restore_timer(
    api: HomeAssistantApiLike,
    access_token: str,
    switch_entity: str,
    duration_entity: str,
    original_duration: float | None,
) -> None:
    with contextlib.suppress(Exception):  # noqa: BLE001
        api.call_service(
            access_token,
            "switch",
            "turn_off",
            {"entity_id": switch_entity},
        )
    if original_duration is not None:
        with contextlib.suppress(Exception):  # noqa: BLE001
            api.call_service(
                access_token,
                "number",
                "set_value",
                {
                    "entity_id": duration_entity,
                    "value": original_duration,
                },
            )


def _info(message: str) -> ServiceSmokeResult:
    return ServiceSmokeResult(True, message, level="INFO")


def result_prefix(result: ServiceSmokeResult) -> str:
    """Return the console prefix for one smoke result."""
    if result.level == "INFO":
        return "INFO"
    return "PASS" if result.ok else "FAIL"


def _dhe_device_status(api: HomeAssistantApiLike, access_token: str) -> str | None:
    with contextlib.suppress(Exception):  # noqa: BLE001
        state = api.get_state(access_token, "sensor.dhe_connect_device_status")
        value = state.get("state")
        if isinstance(value, str):
            return value
    return None


def _state_float(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _timer_state_seconds(value: object) -> int | None:
    text = str(value or "").strip()
    if ":" not in text:
        return None
    minutes_text, seconds_text = text.split(":", 1)
    try:
        minutes = int(minutes_text)
        seconds = int(seconds_text)
    except ValueError:
        return None
    if minutes < 0 or seconds < 0 or seconds >= 60:
        return None
    return minutes * 60 + seconds
