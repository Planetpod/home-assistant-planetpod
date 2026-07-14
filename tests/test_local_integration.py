"""End-to-end regression tests for local-mode entity state writes.

These go through a real config entry + sensor platform setup (unlike
test_coordinator.py's unit-level tests) specifically because the bug this
guards against -- an invalid ENUM sensor state -- only surfaces when an
entity actually writes its state to hass, not from inspecting the
coordinator's data dict alone.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.planetpod.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
)

MOCK_LOCAL_PAYLOAD = {
    "timestamp": "2026-07-14T12:00:00.000Z",
    "systemInfo": {"podSerialNumber": "PP-001", "firmwareVersion": "1.1.8"},
    "g1Data": {"powerDelivered": 0, "powerReturned": 1.2},
    "bmsData": {"socPct": 62, "soh": 98, "cycleCount": 143, "avgTempC": 27.4},
    "podStatus": {"podChargingStatus": "idle", "podMode": "balance"},
}


async def test_local_pod_post_does_not_raise_on_entity_state_write(hass: HomeAssistant):
    """Regression test: a local pod's POST must not crash entity state
    writes. Previously, coordinator_local set status.app_mode to the
    Balance/Speed mode value, which collides with the app_mode sensor's
    fixed ENUM options (cash/solar/solarSmart/solarPure) and raised
    ValueError deep inside async_set_updated_data's listener callbacks --
    escaping mid-request and causing GET/POST handlers to hang instead of
    responding.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Planetpod",
        data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
        options={},
        unique_id="planetpod_local",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]

    # This must not raise -- it did, before the fix.
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.planetpod_pp_001_app_mode")
    assert state is not None
    assert state.state == "unknown"


async def test_reconfigure_local_entry_shows_g1_step_not_api_key_form(
    hass: HomeAssistant,
):
    """Regression test: "Reconfigure" on a local-mode entry must not show
    the cloud API-key form -- it has no API key to reconfigure.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Planetpod",
        data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
        options={},
        unique_id="planetpod_local",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )

    # No G1 candidate exists in this test hass, so this aborts rather than
    # showing a form -- either way, it must not be the cloud "reconfigure"
    # (api_key) step.
    assert result.get("step_id") != "reconfigure"


async def test_command_button_sets_one_shot_flag_on_next_get(hass: HomeAssistant):
    """A command button press must appear exactly once in the next GET
    response, then clear -- it's a one-shot action, not persistent state.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Planetpod",
        data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
        options={},
        unique_id="planetpod_local",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)

    coordinator.trigger_command("PP-001", "reboot")

    first = coordinator.get_response_for("PP-001")
    assert first["Reboot"] is True

    second = coordinator.get_response_for("PP-001")
    assert "Reboot" not in second
