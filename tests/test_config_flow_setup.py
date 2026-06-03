"""Tests for setup-form helpers used by config and reconfigure flows."""

from __future__ import annotations

import pytest

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

from custom_components.stiebel_dhe_connect.config_flow_setup import (
    connection_data_from_user_input,
)
from custom_components.stiebel_dhe_connect.const import DEFAULT_NAME, DEFAULT_PORT
from custom_components.stiebel_dhe_connect.entity_state_helpers import (
    CONF_INTERNAL_SCALD_PROTECTION,
)
from custom_components.stiebel_dhe_connect.error_codes import (
    INVALID_INTERNAL_SCALD_PROTECTION,
)


def test_connection_data_from_user_input_normalizes_values() -> None:
    data = connection_data_from_user_input(
        {
            CONF_HOST: "  dhe-ja06.local.  ",
            CONF_PORT: "8443",
            CONF_NAME: "  Bad EG  ",
            CONF_INTERNAL_SCALD_PROTECTION: "55",
        }
    )

    assert data[CONF_HOST] == "dhe-ja06.local"
    assert data[CONF_PORT] == 8443
    assert data[CONF_NAME] == "Bad EG"
    assert data[CONF_INTERNAL_SCALD_PROTECTION] == "55"


def test_connection_data_from_user_input_applies_defaults() -> None:
    data = connection_data_from_user_input(
        {
            CONF_HOST: "dhe.local",
            CONF_NAME: "   ",
            CONF_INTERNAL_SCALD_PROTECTION: "no_jumper",
        }
    )

    assert data[CONF_PORT] == DEFAULT_PORT
    assert data[CONF_NAME] == DEFAULT_NAME


def test_connection_data_from_user_input_rejects_unknown_scald_value() -> None:
    with pytest.raises(ValueError, match=INVALID_INTERNAL_SCALD_PROTECTION):
        connection_data_from_user_input(
            {
                CONF_HOST: "dhe.local",
                CONF_PORT: DEFAULT_PORT,
                CONF_INTERNAL_SCALD_PROTECTION: "44",
            }
        )
