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

from homeassistant import config_entries

from custom_components.planetpod.const import (
    CONF_CONNECTION_TYPE,
    CONF_G1_SOURCE,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
    G1_SOURCE_POD,
    PENDING_PODS_KEY,
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

    # Must always show the local G1-source form (never the cloud API-key
    # form), even with no auto-detected candidate sensor in this test hass --
    # the user can still pick any sensor manually via the entity selector.
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure_local"


async def test_local_setup_completes_via_g1_form_with_no_candidate_detected(
    hass: HomeAssistant,
):
    """Regression test: the G1-source step must always show a real form and
    let setup complete (default to pod-reported), even when no P1/DSMR-like
    sensor is auto-detected -- it must not silently skip/auto-decide.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "local_connect"

    hass.data.setdefault(DOMAIN, {}).setdefault(PENDING_PODS_KEY, {})["PP-001"] = MOCK_LOCAL_PAYLOAD
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "local_g1"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_G1_SOURCE: G1_SOURCE_POD}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_G1_SOURCE] == G1_SOURCE_POD


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


async def test_balance_source_sensor_reflects_g1_config(hass: HomeAssistant):
    """The Balance Source sensor (and the shared SoC/Mode controls) must be
    attached to the pod's own device, and reflect pod-reported vs. an HA
    sensor correctly.
    """
    hass.states.async_set("sensor.my_p1_meter", "1.5", {"friendly_name": "My P1 Meter"})

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
    await hass.async_block_till_done()

    state = hass.states.get("sensor.planetpod_pp_001_balance_source")
    assert state is not None
    assert state.state == "Pod-reported"

    hass.config_entries.async_update_entry(
        entry,
        options={
            "g1_source": "ha_sensor",
            "g1_ha_entity_id": "sensor.my_p1_meter",
        },
    )
    coordinator.async_options_updated()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.planetpod_pp_001_balance_source")
    assert state.state == "My P1 Meter"

    delivered = hass.states.get("sensor.planetpod_pp_001_balance_g1_power_delivered")
    assert float(delivered.state) == 1.5

    # SoC/Mode controls must be on the pod's own device, not a separate one.
    number_state = hass.states.get("number.planetpod_pp_001_soc_upper_limit")
    select_state = hass.states.get("select.planetpod_pp_001_mode")
    assert number_state is not None
    assert select_state is not None
