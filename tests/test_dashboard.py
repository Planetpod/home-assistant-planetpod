"""Tests for the auto-provisioned dashboard's config-building logic.

Only the pure build_dashboard_config()/_build_view() path is tested here --
async_ensure_dashboard() touches homeassistant.components.lovelace internals
directly and is out of scope for unit tests (see dashboard.py's module
docstring for why). Planning number entities only exist in local mode (see
number.py), so these tests use a local config entry with an ingested pod
POST, not the cloud loaded_config_entry fixture.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.planetpod.const import CONF_CONNECTION_TYPE, CONNECTION_TYPE_LOCAL, DOMAIN
from custom_components.planetpod.dashboard import build_dashboard_config

SERIAL = "PP-001"
MOCK_LOCAL_PAYLOAD = {
    "timestamp": "2026-07-14T12:00:00.000Z",
    "systemInfo": {"podSerialNumber": SERIAL, "firmwareVersion": "1.1.8"},
    "g1Data": {"powerDelivered": 0, "powerReturned": 1.2},
    "bmsData": {"socPct": 62, "soh": 98, "cycleCount": 143, "avgTempC": 27.4},
    "podStatus": {"podChargingStatus": "idle", "podMode": "balance"},
}


async def _setup_local_entry_with_pod(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Planetpod",
        data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
        options={},
        unique_id="planetpod_local_dashboard_test",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post(SERIAL, MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()
    return entry


async def test_build_dashboard_config_none_when_entities_missing(hass: HomeAssistant):
    """No registered entities -> no view for that pod -> no dashboard config at all."""
    registry = er.async_get(hass)
    config = build_dashboard_config(registry, "some_entry_id", [SERIAL])
    assert config is None


async def test_build_dashboard_config_builds_view_once_entities_registered(hass: HomeAssistant):
    """Once a pod's entities exist in the registry, its view resolves with real entity_ids."""
    entry = await _setup_local_entry_with_pod(hass)
    registry = er.async_get(hass)

    config = build_dashboard_config(registry, entry.entry_id, [SERIAL])

    assert config is not None
    assert len(config["views"]) == 1
    view = config["views"][0]
    assert view["path"] == f"pod-{SERIAL}"
    assert view["type"] == "sections"
    assert len(view["sections"]) == 3

    charts_section, planning_section = view["sections"][1], view["sections"][2]
    soc_card = next(c for c in charts_section["cards"] if c["type"] == "custom:planetpod-soc-card")
    assert soc_card["entity"].startswith("sensor.")

    planning_card = next(
        c for c in planning_section["cards"] if c["type"] == "custom:planetpod-planning-card"
    )
    assert len(planning_card["entities"]) == 24
    assert all(e.startswith("number.") for e in planning_card["entities"])


async def test_build_dashboard_config_skips_unknown_pod(hass: HomeAssistant):
    """A serial with no registered entities is dropped, not left half-built."""
    entry = await _setup_local_entry_with_pod(hass)
    registry = er.async_get(hass)

    config = build_dashboard_config(registry, entry.entry_id, [SERIAL, "UNKNOWN-SERIAL"])

    assert len(config["views"]) == 1
    assert config["views"][0]["path"] == f"pod-{SERIAL}"
