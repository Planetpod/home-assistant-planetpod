"""Tests for Planetpod coordinator."""
from __future__ import annotations

import asyncio

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.planetpod.coordinator import PlanetpodDataUpdateCoordinator
from tests.conftest import MOCK_API_URL, MOCK_GRID_ID, MOCK_SERIAL


async def test_success(hass, config_entry, aioclient_mock, mock_grid_payload):
    aioclient_mock.get(MOCK_API_URL, json=mock_grid_payload)
    coordinator = PlanetpodDataUpdateCoordinator(hass, config_entry)
    data = await coordinator._async_update_data()
    assert data["grid_id"] == MOCK_GRID_ID
    assert len(data["pods"]) == 1
    assert data["pods"][0]["battery"]["serial_number"] == MOCK_SERIAL
    assert data["pods"][0]["status"]["soc_pct"] == 85


async def test_auth_failed(hass, config_entry, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, status=401)
    coordinator = PlanetpodDataUpdateCoordinator(hass, config_entry)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_grid_not_found(hass, config_entry, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, status=404, json={"message": "Unknown grid"})
    coordinator = PlanetpodDataUpdateCoordinator(hass, config_entry)
    with pytest.raises(UpdateFailed, match="Grid not found"):
        await coordinator._async_update_data()


async def test_no_pods_yet(hass, config_entry, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, status=404, json={"message": "No pods found"})
    coordinator = PlanetpodDataUpdateCoordinator(hass, config_entry)
    data = await coordinator._async_update_data()
    assert data == {"grid_id": 0, "pods": []}


async def test_timeout(hass, config_entry, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, exc=asyncio.TimeoutError())
    coordinator = PlanetpodDataUpdateCoordinator(hass, config_entry)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_invalid_response(hass, config_entry, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, json={"unexpected": "shape"})
    coordinator = PlanetpodDataUpdateCoordinator(hass, config_entry)
    with pytest.raises(UpdateFailed, match="invalid response"):
        await coordinator._async_update_data()


async def test_unexpected_status(hass, config_entry, aioclient_mock):
    aioclient_mock.get(MOCK_API_URL, status=503)
    coordinator = PlanetpodDataUpdateCoordinator(hass, config_entry)
    with pytest.raises(UpdateFailed, match="503"):
        await coordinator._async_update_data()
