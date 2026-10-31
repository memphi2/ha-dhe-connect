"""Repository test transport policy for the local Fake-DHE servers."""

import pytest
import pytest_socket


@pytest.fixture(autouse=True)
def _allow_loopback_servers() -> None:
    """Permit local protocol tests without allowing external network access."""
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(["127.0.0.1", "::1"], allow_unix_socket=True)
