"""Tests for Planetpod sensor platform."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import PERCENTAGE, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.planetpod.const import DEFAULT_API_URL, DOMAIN, MANUFACTURER
from custom_components.planetpod.energy import ENERGY_DESCRIPTIONS
from custom_components.planetpod.sensor import SENSOR_DESCRIPTIONS
from tests.conftest import MOCK_API_URL, MOCK_SERIAL


def _entity_id(sensor_key: str) -> str:
    """Build expected entity ID for a pod sensor."""
    serial_slug = MOCK_SERIAL.lower().replace("-", "_")
    return f"sensor.planetpod_{serial_slug}_{sensor_key}"


async def test_sensor_count(hass: HomeAssistant, loaded_config_entry):
    """One sensor entity per SENSOR_DESCRIPTIONS entry per pod, plus the
    energy-integration sensors (grid delivered/returned, battery net) added
    for the Energy dashboard card."""
    states = hass.states.async_all("sensor")
    assert len(states) == len(SENSOR_DESCRIPTIONS) + len(ENERGY_DESCRIPTIONS)


async def test_soc_value(hass: HomeAssistant, loaded_config_entry):
    state = hass.states.get(_entity_id("state_of_charge"))
    assert state is not None
    assert state.state == "85"
    assert state.attributes.get("unit_of_measurement") == PERCENTAGE


async def test_online_state(hass: HomeAssistant, loaded_config_entry):
    state = hass.states.get(_entity_id("online"))
    assert state is not None
    assert state.state == "online"


async def test_charge_status(hass: HomeAssistant, loaded_config_entry):
    state = hass.states.get(_entity_id("charge_status"))
    assert state is not None
    assert state.state == "idle"


async def test_app_mode(hass: HomeAssistant, loaded_config_entry):
    state = hass.states.get(_entity_id("app_mode"))
    assert state is not None
    assert state.state == "solar"


async def test_device_info(hass: HomeAssistant, loaded_config_entry):
    from homeassistant.helpers import device_registry as dr
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, MOCK_SERIAL)})
    assert device is not None
    assert device.manufacturer == MANUFACTURER
    assert MOCK_SERIAL in device.name


async def test_sensor_unavailable_after_coordinator_failure(
    hass: HomeAssistant, loaded_config_entry
):
    """Sensors go unavailable when the coordinator fails on the next poll."""
    coordinator = hass.data[DOMAIN][loaded_config_entry.entry_id]
    with patch.object(coordinator, "_async_update_data", side_effect=UpdateFailed("api down")):
        await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id("state_of_charge"))
    assert state is not None
    assert state.state == STATE_UNAVAILABLE
