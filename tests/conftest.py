"""Shared fixtures for Planetpod tests."""
from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations for all tests."""
    return

from custom_components.planetpod.const import CONF_API_KEY, DEFAULT_API_URL, DOMAIN

MOCK_GRID_ID = 123
MOCK_SERIAL = "POD-001"
MOCK_API_KEY = "pp_testkey"
MOCK_API_URL = f"{DEFAULT_API_URL}/open/v1/grid/status"


@pytest.fixture
def mock_grid_payload() -> dict[str, Any]:
    """Full valid API response with one pod."""
    return {
        "grid_id": MOCK_GRID_ID,
        "pods": [
            {
                "battery": {
                    "serial_number": MOCK_SERIAL,
                    "capacity_total_kwh": 5.0,
                    "scu_firmware_version": "1.2.3",
                    "total_cycles": 50,
                    "soc_upper_limit_pct": 100,
                    "soc_lower_limit_pct": 10,
                },
                "status": {
                    "soc_pct": 85,
                    "online": True,
                    "charge_status": "idle",
                    "app_mode": "solar",
                    "pod_mode": "normal",
                },
                "power_control": {
                    "deployed_power_kw": 1.5,
                    "requested_power_kw": 0.0,
                    "received_by_pod_power_kw": 0.0,
                },
                "power_limits": {
                    "max_charge_power_kw": 3.0,
                    "max_discharge_power_kw": 3.0,
                },
                "advanced": {
                    "soh_pct": 98,
                    "avg_battery_temp_c": 22.5,
                    "wifi_rssi_dbm": -55,
                    "avg_ac_voltage_v": 230,
                    "relay_status": "ON",
                },
            }
        ],
    }


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Mock config entry with test credentials."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Planetpod",
        data={CONF_API_KEY: MOCK_API_KEY},
        unique_id=f"planetpod_grid_{MOCK_GRID_ID}",
    )


@pytest.fixture
async def loaded_config_entry(hass, config_entry, aioclient_mock, mock_grid_payload):
    """Config entry set up in hass with coordinator data and sensors initialized."""
    aioclient_mock.get(MOCK_API_URL, json=mock_grid_payload)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
