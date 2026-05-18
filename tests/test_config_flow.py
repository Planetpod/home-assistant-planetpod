"""Tests for Planetpod config flow."""
from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.planetpod.const import CONF_API_KEY, CONF_API_URL, DEFAULT_API_URL, DOMAIN
from tests.conftest import MOCK_API_KEY, MOCK_API_URL, MOCK_GRID_ID

USER_INPUT = {CONF_API_URL: DEFAULT_API_URL, CONF_API_KEY: MOCK_API_KEY}


async def _init_user_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_shows_form(hass: HomeAssistant):
    result = await _init_user_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_success(hass: HomeAssistant, aioclient_mock, mock_grid_payload):
    aioclient_mock.get(MOCK_API_URL, json=mock_grid_payload)
    result = await _init_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_KEY] == MOCK_API_KEY
    assert result["data"][CONF_API_URL] == DEFAULT_API_URL


async def test_user_invalid_auth(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, status=401)
    result = await _init_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_user_grid_not_found(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, status=404, json={"message": "Unknown grid"})
    result = await _init_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "grid_not_found"


async def test_user_no_data_yet(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, status=404, json={"message": "No pods found"})
    result = await _init_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "no_data_yet"


async def test_user_cannot_connect(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, status=500)
    result = await _init_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


async def test_user_already_configured(hass: HomeAssistant, aioclient_mock, config_entry, mock_grid_payload):
    config_entry.add_to_hass(hass)
    aioclient_mock.get(MOCK_API_URL, json=mock_grid_payload)
    result = await _init_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_shows_form(hass: HomeAssistant, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"


async def test_reconfigure_success(hass: HomeAssistant, config_entry, aioclient_mock, mock_grid_payload):
    config_entry.add_to_hass(hass)
    aioclient_mock.get(MOCK_API_URL, json=mock_grid_payload)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_URL: DEFAULT_API_URL, CONF_API_KEY: "pp_newkey"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_API_KEY] == "pp_newkey"


async def test_reconfigure_invalid_auth(hass: HomeAssistant, config_entry, aioclient_mock):
    config_entry.add_to_hass(hass)
    aioclient_mock.get(MOCK_API_URL, status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_reauth_shows_form(hass: HomeAssistant, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": config_entry.entry_id},
        data=config_entry.data,
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_confirm_success(hass: HomeAssistant, config_entry, aioclient_mock, mock_grid_payload):
    config_entry.add_to_hass(hass)
    aioclient_mock.get(MOCK_API_URL, json=mock_grid_payload)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": config_entry.entry_id},
        data=config_entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_URL: DEFAULT_API_URL, CONF_API_KEY: "pp_newkey"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_KEY] == "pp_newkey"
