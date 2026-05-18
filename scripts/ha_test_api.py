"""Home Assistant API helper for the local DHE test installation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import http.client
import json
import os
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

try:
    from scripts.ha_test_redaction import (
        format_redacted_exception,
        redact_sensitive_text,
    )
    from scripts.ha_test_api_smokes import (
        DEFAULT_CLIMATE_ENTITY,
        DEFAULT_RADIO_AUTO_OFF_SECONDS,
        DEFAULT_RADIO_ENTITY,
        DEFAULT_TIMER_DURATION_ENTITY,
        DEFAULT_TIMER_REMAINING_ENTITY,
        DEFAULT_TIMER_SMOKE_DURATION_SECONDS,
        DEFAULT_TIMER_SMOKE_EXPIRY_GRACE_SECONDS,
        DEFAULT_TIMER_SMOKE_OBSERVE_SECONDS,
        DEFAULT_TIMER_SWITCH_ENTITY,
        _timer_state_seconds,
        result_prefix,
        run_entity_smoke,
        run_service_smoke,
        run_timer_smoke,
    )
except ModuleNotFoundError:
    from ha_test_redaction import (
        format_redacted_exception,
        redact_sensitive_text,
    )
    from ha_test_api_smokes import (
        DEFAULT_CLIMATE_ENTITY,
        DEFAULT_RADIO_AUTO_OFF_SECONDS,
        DEFAULT_RADIO_ENTITY,
        DEFAULT_TIMER_DURATION_ENTITY,
        DEFAULT_TIMER_REMAINING_ENTITY,
        DEFAULT_TIMER_SMOKE_DURATION_SECONDS,
        DEFAULT_TIMER_SMOKE_EXPIRY_GRACE_SECONDS,
        DEFAULT_TIMER_SMOKE_OBSERVE_SECONDS,
        DEFAULT_TIMER_SWITCH_ENTITY,
        _timer_state_seconds,
        result_prefix,
        run_entity_smoke,
        run_service_smoke,
        run_timer_smoke,
    )


__all__ = [
    "DEFAULT_CLIMATE_ENTITY",
    "DEFAULT_RADIO_AUTO_OFF_SECONDS",
    "DEFAULT_RADIO_ENTITY",
    "DEFAULT_TIMER_DURATION_ENTITY",
    "DEFAULT_TIMER_REMAINING_ENTITY",
    "DEFAULT_TIMER_SMOKE_DURATION_SECONDS",
    "DEFAULT_TIMER_SMOKE_EXPIRY_GRACE_SECONDS",
    "DEFAULT_TIMER_SMOKE_OBSERVE_SECONDS",
    "DEFAULT_TIMER_SWITCH_ENTITY",
    "HomeAssistantApi",
    "AuthToken",
    "TokenCleanupResult",
    "_timer_state_seconds",
    "cleanup_localhost_refresh_tokens",
    "cleanup_localhost_refresh_tokens_with_retry",
    "run_entity_smoke",
    "run_service_smoke",
    "run_timer_smoke",
]


DEFAULT_URL = "http://127.0.0.1:8123"
DEFAULT_USERNAME = ""
DEFAULT_CONFIG = Path("/mnt/ha-test-config")
DEFAULT_CLIENT_ID = "http://localhost/"
DEFAULT_BACKUP_DIR = Path("/tmp")


@dataclass(frozen=True)
class AuthToken:
    """Home Assistant access and refresh token pair."""

    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class TokenCleanupResult:
    """Result of localhost refresh-token cleanup."""

    removed: int
    backup_path: Path | None
    stable: bool = True


class HomeAssistantApi:
    """Minimal Home Assistant API client for test automation."""

    def __init__(
        self,
        base_url: str,
        *,
        client_id: str = DEFAULT_CLIENT_ID,
        redirect_uri: str = DEFAULT_CLIENT_ID,
    ) -> None:
        """Initialize the API helper."""
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.redirect_uri = redirect_uri

    def login(self, username: str, password: str) -> AuthToken:
        """Log in with the HA local auth provider and return API tokens."""
        _, flow = self._request_json(
            "/auth/login_flow",
            {
                "client_id": self.client_id,
                "handler": ["homeassistant", None],
                "redirect_uri": self.redirect_uri,
            },
        )
        _, login = self._request_json(
            f"/auth/login_flow/{flow['flow_id']}",
            {
                "client_id": self.client_id,
                "username": username,
                "password": password,
            },
        )
        if login.get("type") != "create_entry":
            raise RuntimeError(
                f"HA auth failed: type={login.get('type')} errors={login.get('errors')}"
            )
        _, token = self._request_form(
            "/auth/token",
            {
                "grant_type": "authorization_code",
                "code": login["result"],
                "client_id": self.client_id,
            },
        )
        return AuthToken(
            access_token=str(token["access_token"]),
            refresh_token=str(token["refresh_token"]),
        )

    def revoke_refresh_token(self, refresh_token: str) -> bool:
        """Revoke a refresh token through the HA auth endpoint."""
        self._request_form(
            "/auth/token",
            {
                "grant_type": "delete",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
            },
            timeout=10,
        )
        return True

    def restart(self, access_token: str, *, timeout: float = 3.0) -> str:
        """Request a Home Assistant restart.

        HA often drops or times out the HTTP request while restarting. Treat
        transport timeouts and gateway/service errors as an accepted restart
        request, then rely on wait_online() for the real result.
        """
        try:
            self.call_service(
                access_token,
                "homeassistant",
                "restart",
                {},
                timeout=timeout,
        )
        except TimeoutError as err:
            return f"restart assumed after timeout: {err}"
        except urllib.error.HTTPError as err:
            detail = redact_sensitive_text(err.read().decode(errors="replace")[:120])
            if err.code in {500, 502, 503, 504}:
                return f"restart assumed after HTTP {err.code}: {detail!r}"
            raise
        except urllib.error.URLError as err:
            return f"restart assumed after transport close: {err}"
        return "restart requested"

    def wait_online(
        self,
        *,
        timeout: float = 180.0,
        interval: float = 2.0,
        require_seen_down: bool = False,
        settle_seconds: float = 0.0,
        stable_online_seconds: float = 20.0,
    ) -> bool:
        """Wait until HA exposes auth providers after an optional outage."""
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        deadline = time.monotonic() + timeout
        seen_down = not require_seen_down
        stable_online_since: float | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"{self.base_url}/auth/providers",
                    timeout=5,
                ) as response:
                    if response.status == 200:
                        if not require_seen_down:
                            return True
                        if not seen_down:
                            stable_online_since = None
                            time.sleep(interval)
                            continue
                        now = time.monotonic()
                        stable_online_since = stable_online_since or now
                        if now - stable_online_since >= stable_online_seconds:
                            return True
                    else:
                        seen_down = True
                        stable_online_since = None
            except (OSError, TimeoutError, urllib.error.URLError):
                seen_down = True
                stable_online_since = None
            time.sleep(interval)
        return False

    def wait_api_ready(
        self,
        access_token: str,
        *,
        timeout: float = 60.0,
        interval: float = 2.0,
        stable_seconds: float = 5.0,
    ) -> bool:
        """Wait until authenticated HA API requests stay available."""
        deadline = time.monotonic() + timeout
        stable_since: float | None = None
        while time.monotonic() < deadline:
            try:
                status, _result = self._request_json(
                    "/api/",
                    None,
                    access_token=access_token,
                    timeout=5,
                )
            except (
                OSError,
                TimeoutError,
                http.client.HTTPException,
                json.JSONDecodeError,
                urllib.error.URLError,
            ):
                stable_since = None
            else:
                if status == 200:
                    now = time.monotonic()
                    stable_since = stable_since or now
                    if now - stable_since >= stable_seconds:
                        return True
                else:
                    stable_since = None
            time.sleep(interval)
        return False

    def get_state(self, access_token: str, entity_id: str) -> dict[str, Any]:
        """Return one HA state object."""
        _, state = self._request_json(
            f"/api/states/{entity_id}",
            None,
            access_token=access_token,
        )
        return state

    def get_states(self, access_token: str) -> list[dict[str, Any]]:
        """Return all Home Assistant state objects."""
        _, states = self._request_json(
            "/api/states",
            None,
            access_token=access_token,
        )
        if isinstance(states, list):
            return [state for state in states if isinstance(state, dict)]
        return []

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
        _, result = self._request_json(
            f"/api/services/{domain}/{service}",
            payload,
            access_token=access_token,
            timeout=timeout,
        )
        if isinstance(result, list):
            return result
        return []

    def _request_json(
        self,
        path: str,
        payload: dict[str, Any] | None,
        *,
        access_token: str | None = None,
        timeout: float = 20.0,
    ) -> tuple[int, Any]:
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else {}

    def _request_form(
        self,
        path: str,
        payload: dict[str, str],
        *,
        timeout: float = 20.0,
    ) -> tuple[int, Any]:
        data = urllib.parse.urlencode(payload).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else {}


def cleanup_localhost_refresh_tokens(
    config: Path,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
) -> TokenCleanupResult:
    """Remove temporary localhost refresh tokens from mounted HA auth storage."""
    path = config / ".storage" / "auth"
    data = json.loads(path.read_text(encoding="utf-8"))
    original_data = json.loads(json.dumps(data))
    tokens = data.get("data", {}).get("refresh_tokens", [])
    removed = 0

    if isinstance(tokens, list):
        kept = []
        for token in tokens:
            if isinstance(token, dict) and token.get("client_id") == client_id:
                removed += 1
                continue
            kept.append(token)
        data["data"]["refresh_tokens"] = kept
    elif isinstance(tokens, dict):
        kept = {}
        for key, token in tokens.items():
            if isinstance(token, dict) and token.get("client_id") == client_id:
                removed += 1
                continue
            kept[key] = token
        data["data"]["refresh_tokens"] = kept

    if removed == 0:
        return TokenCleanupResult(removed=0, backup_path=None)

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / (
        "ha-test-auth-before-localhost-cleanup-"
        f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}.json"
    )
    backup_path.write_text(
        json.dumps(original_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return TokenCleanupResult(removed=removed, backup_path=backup_path)


def cleanup_localhost_refresh_tokens_with_retry(
    config: Path,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    attempts: int = 5,
    interval: float = 1.0,
) -> TokenCleanupResult:
    """Remove localhost refresh tokens until the mounted auth file stays clean."""
    remaining_attempts = max(1, attempts)
    total_removed = 0
    first_backup_path: Path | None = None
    stable = False
    for attempt in range(remaining_attempts):
        result = cleanup_localhost_refresh_tokens(
            config,
            client_id=client_id,
            backup_dir=backup_dir,
        )
        total_removed += result.removed
        first_backup_path = first_backup_path or result.backup_path
        if result.removed == 0:
            stable = True
            break
        if attempt + 1 < remaining_attempts:
            time.sleep(interval)
    return TokenCleanupResult(
        removed=total_removed,
        backup_path=first_backup_path,
        stable=stable,
    )


def _env_default(name: str, fallback: str) -> str:
    return os.environ.get(name, fallback)


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run HA API actions against the mounted DHE test installation.",
    )
    parser.add_argument("--url", default=_env_default("HA_TEST_URL", DEFAULT_URL))
    parser.add_argument(
        "--username",
        default=_env_default("HA_TEST_USERNAME", DEFAULT_USERNAME),
        help="HA username, or set HA_TEST_USERNAME.",
    )
    parser.add_argument(
        "--password-env",
        default="HA_TEST_PASSWORD",
        help="Environment variable that contains the HA password.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--login-wait-timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for HA auth providers before login.",
    )
    parser.add_argument(
        "--login-wait-interval",
        type=float,
        default=2.0,
        help="Polling interval while waiting for HA auth providers before login.",
    )
    parser.add_argument("--restart", action="store_true")
    parser.add_argument(
        "--restart-request-timeout",
        type=float,
        default=3.0,
        help="Seconds to wait for the HA restart service call itself.",
    )
    parser.add_argument("--wait-timeout", type=float, default=180.0)
    parser.add_argument(
        "--api-ready-timeout",
        type=float,
        default=90.0,
        help="Seconds to wait for authenticated HA API readiness.",
    )
    parser.add_argument(
        "--restart-settle-seconds",
        type=float,
        default=0.0,
        help="Seconds to wait after restart request before polling HA online.",
    )
    parser.add_argument("--service-smoke", action="store_true")
    parser.add_argument("--climate-entity", default=DEFAULT_CLIMATE_ENTITY)
    parser.add_argument("--radio-entity", default=DEFAULT_RADIO_ENTITY)
    parser.add_argument("--entity-smoke", action="store_true")
    parser.add_argument("--timer-smoke", action="store_true")
    parser.add_argument("--timer-switch-entity", default=DEFAULT_TIMER_SWITCH_ENTITY)
    parser.add_argument(
        "--timer-remaining-entity",
        default=DEFAULT_TIMER_REMAINING_ENTITY,
    )
    parser.add_argument(
        "--timer-duration-entity",
        default=DEFAULT_TIMER_DURATION_ENTITY,
    )
    parser.add_argument(
        "--timer-smoke-duration-seconds",
        type=_non_negative_float,
        default=DEFAULT_TIMER_SMOKE_DURATION_SECONDS,
        help="Temporary timer duration used by --timer-smoke.",
    )
    parser.add_argument(
        "--timer-smoke-observe-seconds",
        type=_non_negative_float,
        default=DEFAULT_TIMER_SMOKE_OBSERVE_SECONDS,
        help="Initial countdown observation window for --timer-smoke.",
    )
    parser.add_argument(
        "--timer-smoke-expiry-grace-seconds",
        type=_non_negative_float,
        default=DEFAULT_TIMER_SMOKE_EXPIRY_GRACE_SECONDS,
        help="Extra seconds to wait for DHE timer expiry and reset.",
    )
    parser.add_argument(
        "--radio-auto-off-seconds",
        type=float,
        default=DEFAULT_RADIO_AUTO_OFF_SECONDS,
        help="Turn the radio off this many seconds after service-smoke selects a source.",
    )
    parser.add_argument(
        "--cleanup-localhost-tokens",
        action="store_true",
        help="Remove temporary localhost auth tokens from --config if revoke fails.",
    )
    parser.add_argument(
        "--cleanup-localhost-token-attempts",
        type=int,
        default=5,
        help="Number of mounted-auth cleanup attempts after token revoke failure.",
    )
    parser.add_argument(
        "--cleanup-localhost-token-interval",
        type=_non_negative_float,
        default=1.0,
        help="Seconds to wait between mounted-auth cleanup attempts.",
    )
    parser.add_argument(
        "--restart-before-localhost-cleanup",
        action="store_true",
        help=(
            "Restart HA before mounted-auth cleanup after revoke failure so "
            "running auth state cannot immediately re-persist stale test tokens."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    password = os.environ.get(args.password_env)
    if not args.username:
        print("FAIL: HA username is required via --username or HA_TEST_USERNAME")
        return 1
    if not password:
        print(f"FAIL: password env var {args.password_env!r} is not set")
        return 1

    api = HomeAssistantApi(args.url)
    if not api.wait_online(
        timeout=args.login_wait_timeout,
        interval=args.login_wait_interval,
    ):
        print("FAIL: HA auth providers did not become reachable")
        return 1

    refresh_token = ""
    exit_code = 0
    try:
        try:
            token = api.login(args.username, password)
        except Exception as err:  # noqa: BLE001
            print(f"FAIL: HA auth login failed: {format_redacted_exception(err)}")
            return 1
        refresh_token = token.refresh_token
        print("PASS: HA auth login")
        if args.restart:
            print(
                "INFO: "
                f"{api.restart(token.access_token, timeout=args.restart_request_timeout)}"
            )
            if not api.wait_online(
                timeout=args.wait_timeout,
                require_seen_down=True,
                settle_seconds=args.restart_settle_seconds,
            ):
                print("FAIL: HA did not come back online")
                return 2
            print("PASS: HA online")
        if args.service_smoke:
            if not api.wait_api_ready(
                token.access_token,
                timeout=args.api_ready_timeout,
            ):
                print("FAIL: HA authenticated API did not become ready")
                exit_code = 3
            else:
                print("PASS: HA authenticated API ready")
                try:
                    results = run_service_smoke(
                        api,
                        token.access_token,
                        climate_entity=args.climate_entity,
                        radio_entity=args.radio_entity,
                        radio_auto_off_seconds=args.radio_auto_off_seconds,
                    )
                except Exception as err:  # noqa: BLE001
                    print(
                        "FAIL: HA service smoke aborted: "
                        f"{format_redacted_exception(err)}"
                    )
                    exit_code = 3
                else:
                    for result in results:
                        print(f"{result_prefix(result)}: {result.message}")
                        if not result.ok:
                            exit_code = 3
        if args.entity_smoke:
            if not api.wait_api_ready(
                token.access_token,
                timeout=args.api_ready_timeout,
            ):
                print("FAIL: HA authenticated API did not become ready")
                exit_code = 3
            else:
                print("PASS: HA authenticated API ready")
                try:
                    results = run_entity_smoke(api, token.access_token)
                except Exception as err:  # noqa: BLE001
                    print(
                        "FAIL: HA entity smoke aborted: "
                        f"{format_redacted_exception(err)}"
                    )
                    exit_code = 3
                else:
                    for result in results:
                        print(f"{result_prefix(result)}: {result.message}")
                        if not result.ok:
                            exit_code = 3
        if args.timer_smoke:
            if not api.wait_api_ready(
                token.access_token,
                timeout=args.api_ready_timeout,
            ):
                print("FAIL: HA authenticated API did not become ready")
                exit_code = 3
            else:
                print("PASS: HA authenticated API ready")
                try:
                    results = run_timer_smoke(
                        api,
                        token.access_token,
                        switch_entity=args.timer_switch_entity,
                        remaining_entity=args.timer_remaining_entity,
                        duration_entity=args.timer_duration_entity,
                        duration_seconds=args.timer_smoke_duration_seconds,
                        observe_seconds=args.timer_smoke_observe_seconds,
                        expiry_grace_seconds=args.timer_smoke_expiry_grace_seconds,
                    )
                except Exception as err:  # noqa: BLE001
                    print(
                        "FAIL: HA timer smoke aborted: "
                        f"{format_redacted_exception(err)}"
                    )
                    exit_code = 3
                else:
                    for result in results:
                        print(f"{result_prefix(result)}: {result.message}")
                        if not result.ok:
                            exit_code = 3
    finally:
        if refresh_token:
            try:
                api.revoke_refresh_token(refresh_token)
                print("PASS: HA refresh token revoked")
            except Exception as err:  # noqa: BLE001
                print(
                    "WARN: HA refresh token revoke failed: "
                    f"{format_redacted_exception(err)}"
                )
                if args.cleanup_localhost_tokens:
                    try:
                        if args.restart_before_localhost_cleanup:
                            try:
                                restart_result = api.restart(
                                    token.access_token,
                                    timeout=args.restart_request_timeout,
                                )
                            except Exception as restart_err:  # noqa: BLE001
                                print(
                                    "WARN: restart before localhost token cleanup failed: "
                                    f"{format_redacted_exception(restart_err)}"
                                )
                            else:
                                print(
                                    "INFO: restart before localhost token cleanup: "
                                    f"{restart_result}"
                                )
                                if not api.wait_online(
                                    timeout=args.wait_timeout,
                                    require_seen_down=True,
                                    settle_seconds=args.restart_settle_seconds,
                                ):
                                    print(
                                        "WARN: HA did not come back online before cleanup"
                                    )
                        cleanup = cleanup_localhost_refresh_tokens_with_retry(
                            args.config,
                            attempts=args.cleanup_localhost_token_attempts,
                            interval=args.cleanup_localhost_token_interval,
                        )
                    except Exception as cleanup_err:  # noqa: BLE001
                        print(
                            "WARN: localhost token cleanup failed: "
                            f"{format_redacted_exception(cleanup_err)}"
                        )
                    else:
                        prefix = "PASS" if cleanup.stable else "WARN"
                        print(
                            f"{prefix}: localhost token cleanup "
                            f"removed={cleanup.removed} "
                            f"stable={cleanup.stable} "
                            f"backup={cleanup.backup_path}"
                        )
                        if not cleanup.stable:
                            exit_code = 3
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
