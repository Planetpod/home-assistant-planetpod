"""End-to-end regression tests for local-mode entity state writes.

These go through a real config entry + sensor platform setup (unlike
test_coordinator.py's unit-level tests) specifically because the bug this
guards against -- an invalid ENUM sensor state -- only surfaces when an
entity actually writes its state to hass, not from inspecting the
coordinator's data dict alone.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
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

    # Reboot is always present in the real contract (default false), not
    # omitted -- it must revert to False on the next GET, not disappear.
    second = coordinator.get_response_for("PP-001")
    assert second["Reboot"] is False


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

    state = hass.states.get("sensor.planetpod_pp_001_p1_balance_source")
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

    state = hass.states.get("sensor.planetpod_pp_001_p1_balance_source")
    assert state.state == "My P1 Meter"

    delivered = hass.states.get("sensor.planetpod_pp_001_p1_power_delivered")
    assert float(delivered.state) == 1.5

    # SoC/Mode controls must be on the pod's own device, not a separate one.
    number_state = hass.states.get("number.planetpod_pp_001_soc_upper_limit")
    select_state = hass.states.get("select.planetpod_pp_001_mode")
    assert number_state is not None
    assert select_state is not None


async def test_command_buttons_are_config_category(hass: HomeAssistant):
    """Regression test: command buttons must be entity_category=CONFIG so
    they land in the device page's "Configuration" section, separate from
    Mode/SoC limits in "Controls" -- otherwise HA alphabetizes everything
    together, mixing "Calibration" in between "Mode" and the SoC sliders.
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
    await hass.async_block_till_done()

    registry = er.async_get(hass)

    for entity_id in (
        "button.planetpod_pp_001_reboot",
        "button.planetpod_pp_001_calibration",
        "button.planetpod_pp_001_turn_off_bms",
    ):
        entry_reg = registry.async_get(entity_id)
        assert entry_reg is not None, f"{entity_id} not found"
        assert entry_reg.entity_category == EntityCategory.CONFIG

    # Unlock SCU/BMS Update/Debug are deliberately not exposed as HA buttons.
    for entity_id in (
        "button.planetpod_pp_001_unlock_scu",
        "button.planetpod_pp_001_bms_update",
        "button.planetpod_pp_001_debug",
    ):
        assert registry.async_get(entity_id) is None, f"{entity_id} should not exist"

    # Mode/SoC must stay in the primary Controls section (no category).
    for entity_id in (
        "select.planetpod_pp_001_mode",
        "number.planetpod_pp_001_soc_upper_limit",
        "number.planetpod_pp_001_soc_lower_limit",
    ):
        entry_reg = registry.async_get(entity_id)
        assert entry_reg is not None, f"{entity_id} not found"
        assert entry_reg.entity_category is None


async def _setup_local_entry(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Planetpod",
        data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
        options=options or {},
        unique_id="planetpod_local",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_speed_setpoint_drives_get_response(hass: HomeAssistant):
    """Setting the Speed Setpoint number entity must actually flow into the
    next GET response once Mode is set to Speed -- this is the core bug fix:
    speed_setpoint_kw was never wired into compute_get_response() before.
    """
    entry = await _setup_local_entry(hass, options={"mode": "speed"})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    coordinator.set_speed_setpoint(2.5)

    response = coordinator.get_response_for("PP-001")
    assert response["Modus"] == "solarSmart"
    assert response["solarSmart"] == {"subMode": "speed", "setpoint_kW": 2.5}

    state = hass.states.get("sensor.planetpod_pp_001_speed_setpoint_status")
    assert state.state == "Active"


async def test_speed_setpoint_expires_to_idle(hass: HomeAssistant):
    """A Speed Setpoint that hasn't been refreshed within the timeout window
    must revert to 0/idle rather than keep applying a stale value.
    """
    entry = await _setup_local_entry(hass, options={"mode": "speed"})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    coordinator.set_speed_setpoint(1.0)
    coordinator._speed_setpoint_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    coordinator._rebuild()
    await hass.async_block_till_done()

    response = coordinator.get_response_for("PP-001")
    assert response["solarSmart"] == {"subMode": "speed", "setpoint_kW": 0.0}

    state = hass.states.get("sensor.planetpod_pp_001_speed_setpoint_status")
    assert state.state == "Expired (reverted to idle)"


async def test_speed_setpoint_duration_changes_expiry_window(hass: HomeAssistant):
    """Setting a shorter Speed Setpoint Duration must apply the new window
    the next time a setpoint is set, not force an immediate expiry.
    """
    entry = await _setup_local_entry(hass, options={"mode": "speed"})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    coordinator.set_speed_setpoint_duration(5)
    assert coordinator.speed_setpoint_duration_min == 5

    coordinator.set_speed_setpoint(1.5)
    assert coordinator.effective_speed_setpoint_kw == 1.5

    coordinator._speed_setpoint_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert coordinator.effective_speed_setpoint_kw == 0.0


async def test_balance_source_sensor_shows_no_p1_error(hass: HomeAssistant):
    """With Balance mode selected and no usable G1 reading (HA sensor
    unavailable, no pod-reported G1 in the payload either), the P1 Balance
    Source sensor must show a clear error instead of silently doing nothing.
    """
    entry = await _setup_local_entry(
        hass,
        options={
            "mode": "balance",
            "g1_source": "ha_sensor",
            "g1_ha_entity_id": "sensor.does_not_exist",
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id]
    payload = {**MOCK_LOCAL_PAYLOAD, "g1Data": {"powerDelivered": None, "powerReturned": None}}
    coordinator.ingest_post("PP-001", payload)
    await hass.async_block_till_done()

    response = coordinator.get_response_for("PP-001")
    assert response["solarSmart"]["setpoint_kW"] == 0.0

    state = hass.states.get("sensor.planetpod_pp_001_p1_balance_source")
    assert state.state == "Can't balance: no P1 sensor"


async def test_speed_setpoint_unavailable_unless_mode_is_speed(hass: HomeAssistant):
    """The Speed Setpoint number entity must be unavailable (grayed out)
    whenever Mode isn't Speed -- it has no effect in Balance mode, so it
    shouldn't look editable/active on the device page.
    """
    entry = await _setup_local_entry(hass, options={"mode": "balance"})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    state = hass.states.get("number.planetpod_pp_001_speed_setpoint")
    assert state.state == "unavailable"

    hass.config_entries.async_update_entry(entry, options={**entry.options, "mode": "speed"})
    coordinator.async_options_updated()
    await hass.async_block_till_done()

    state = hass.states.get("number.planetpod_pp_001_speed_setpoint")
    assert state.state != "unavailable"


async def test_editing_speed_setpoint_number_does_not_send_until_button_pressed(
    hass: HomeAssistant,
):
    """Editing the Speed Setpoint/Duration number entities must only stage
    values -- nothing is actually sent to the pod until "Send Speed Command"
    is pressed. This is what avoids the old order-dependency footgun where
    changing Duration after Setpoint silently used the previous duration.
    """
    entry = await _setup_local_entry(hass, options={"mode": "speed"})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    coordinator.stage_speed_setpoint(2.0)
    coordinator.set_speed_setpoint_duration(10)

    # Staged only -- not yet active/sent.
    assert coordinator.effective_speed_setpoint_kw == 0.0
    assert coordinator.speed_setpoint_active is False

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.planetpod_pp_001_send_speed_command"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert coordinator.speed_setpoint_active is True
    response = coordinator.get_response_for("PP-001")
    assert response["solarSmart"] == {"subMode": "speed", "setpoint_kW": 2.0}


async def test_staging_new_setpoint_while_active_does_not_leak_until_send(
    hass: HomeAssistant,
):
    """Staging a new Speed Setpoint while a previous command is still
    active must NOT change what's applied until "Send Speed Command" is
    pressed again -- effective_speed_setpoint_kw must reflect the value that
    was active at the last send, not whatever is currently staged.
    """
    entry = await _setup_local_entry(hass, options={"mode": "speed"})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    coordinator.set_speed_setpoint(2.0)
    assert coordinator.speed_setpoint_active is True
    assert coordinator.effective_speed_setpoint_kw == 2.0

    # Stage a new value only -- do NOT press "Send Speed Command" again.
    coordinator.stage_speed_setpoint(-1.0)

    # Still active from the first send, and must still apply 2.0, not -1.0.
    assert coordinator.speed_setpoint_active is True
    assert coordinator.effective_speed_setpoint_kw == 2.0
    response = coordinator.get_response_for("PP-001")
    assert response["solarSmart"] == {"subMode": "speed", "setpoint_kW": 2.0}

    # Now actually send -- the staged -1.0 takes over, and immediately.
    coordinator.send_speed_command()
    assert coordinator.effective_speed_setpoint_kw == -1.0


async def test_sending_new_setpoint_while_active_overwrites_not_queues(
    hass: HomeAssistant,
):
    """A second "send" while a previous command is still active must fully
    replace it -- no queueing of the old command's remaining duration.
    """
    entry = await _setup_local_entry(hass, options={"mode": "speed"})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    coordinator.set_speed_setpoint_duration(5)
    coordinator.set_speed_setpoint(2.0)
    first_expiry = coordinator._speed_setpoint_expires_at

    coordinator.set_speed_setpoint_duration(10)
    coordinator.set_speed_setpoint(-1.0)

    assert coordinator.effective_speed_setpoint_kw == -1.0
    assert coordinator._speed_setpoint_expires_at != first_expiry
    assert coordinator._speed_setpoint_expires_at > first_expiry


async def test_send_speed_command_button_unavailable_unless_mode_is_speed(
    hass: HomeAssistant,
):
    """The Send Speed Command button must be unavailable outside Speed mode,
    same as the Setpoint/Duration number entities it applies.
    """
    entry = await _setup_local_entry(hass, options={"mode": "balance"})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    state = hass.states.get("button.planetpod_pp_001_send_speed_command")
    assert state.state == "unavailable"

    registry = er.async_get(hass)
    entry_reg = registry.async_get("button.planetpod_pp_001_send_speed_command")
    assert entry_reg is not None
    assert entry_reg.entity_category is None


async def test_last_post_received_sensor_exposes_raw_payload(hass: HomeAssistant):
    """The Last POST Received sensor must expose a real timestamp state plus
    the raw POST payload as an attribute, so the last message from a pod is
    inspectable from Developer Tools > States without digging through logs.
    """
    entry = await _setup_local_entry(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.planetpod_pp_001_last_post_received")
    assert state is not None
    assert state.state != "unknown"
    assert state.attributes["raw_payload"] == MOCK_LOCAL_PAYLOAD

    registry = er.async_get(hass)
    entry_reg = registry.async_get("sensor.planetpod_pp_001_last_post_received")
    assert entry_reg is not None
    assert entry_reg.entity_category == EntityCategory.DIAGNOSTIC


async def test_last_error_sensor_reflects_errorlogs_from_post(hass: HomeAssistant):
    """The Last Error sensor must surface the raw POST's errorLogs (SCU/BMS
    fault data), which the cloud REST API never exposes -- this is
    local-mode-only visibility into battery faults.
    """
    entry = await _setup_local_entry(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.planetpod_pp_001_last_error")
    assert state.state == "None"

    payload_with_error = {
        **MOCK_LOCAL_PAYLOAD,
        "errorLogs": [
            {
                "timestamp": "2026-07-16T13:49:26.000Z",
                "errorCode": "E042",
                "errorType": "bms",
                "description": "Cell overvoltage detected",
                "severity": 2,
                "errorGroup": "battery",
                "startEnd": 1,
            }
        ],
    }
    coordinator.ingest_post("PP-001", payload_with_error)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.planetpod_pp_001_last_error")
    assert state.state == "Cell overvoltage detected"
    assert state.attributes["error_logs"][0]["errorCode"] == "E042"

    registry = er.async_get(hass)
    entry_reg = registry.async_get("sensor.planetpod_pp_001_last_error")
    assert entry_reg is not None
    assert entry_reg.entity_category == EntityCategory.DIAGNOSTIC


async def test_always_present_command_fields_default_false(hass: HomeAssistant):
    """Reboot/Toggle_calibration/TurnOffBMS/UnlockBMS must always be present
    (default False) in every GET response, matching the real cloud contract --
    not omitted like Unlock/Debug_on/bmsUpdate.
    """
    entry = await _setup_local_entry(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    response = coordinator.get_response_for("PP-001")
    assert response["Reboot"] is False
    assert response["Toggle_calibration"] is False
    assert response["TurnOffBMS"] is False
    assert response["UnlockBMS"] is False
    assert "Unlock" not in response
    assert "Debug_on" not in response
    assert "bmsUpdate" not in response


async def test_conditional_command_fields_omitted_unless_true(hass: HomeAssistant):
    """Unlock/Debug_on/bmsUpdate must be OMITTED when not triggered, and
    present as True (not False) exactly once, matching the real cloud
    contract's conditional-spread behavior.
    """
    entry = await _setup_local_entry(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    coordinator.trigger_command("PP-001", "debug_on")
    coordinator.trigger_command("PP-001", "unlock_bms")
    coordinator.trigger_command("PP-001", "bms_update")

    first = coordinator.get_response_for("PP-001")
    assert first["Debug_on"] is True
    assert first["bmsUpdate"] is True
    # unlock_bms is an always-present field, so it reverts to False, not omitted.
    assert first["UnlockBMS"] is True

    second = coordinator.get_response_for("PP-001")
    assert "Debug_on" not in second
    assert "bmsUpdate" not in second
    assert second["UnlockBMS"] is False


async def test_get_response_includes_soc_limits_and_same_group(hass: HomeAssistant):
    """Min_SOC/Max_SOC/sameGroup are confirmed control-affecting on firmware
    (persisted into its own SOC-limit storage and NVS group setting), not
    informational -- omitting them means the SoC Upper/Lower Limit entities
    would silently have no effect on a real pod.
    """
    entry = await _setup_local_entry(hass, options={"soc_upper_limit_pct": 90, "soc_lower_limit_pct": 15})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    response = coordinator.get_response_for("PP-001")
    assert response["Max_SOC"] == 90
    assert response["Min_SOC"] == 15
    assert response["sameGroup"] is True


async def test_soh_and_cycle_count_survive_posts_that_omit_them(hass: HomeAssistant):
    """Firmware only includes bmsData.soh/cycleCount/cycleBufferMah in a POST
    when the value changed since the last send (delta-throttled) -- a naive
    full-overwrite of the raw payload would flicker State of Health/Total
    Cycles to unknown on every POST that doesn't repeat them.
    """
    entry = await _setup_local_entry(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)  # has soh=98, cycleCount=143
    await hass.async_block_till_done()

    payload_without_deltas = {
        **MOCK_LOCAL_PAYLOAD,
        "bmsData": {"socPct": 61, "avgTempC": 27.1},  # no soh/cycleCount this time
    }
    coordinator.ingest_post("PP-001", payload_without_deltas)
    await hass.async_block_till_done()

    soh_state = hass.states.get("sensor.planetpod_pp_001_state_of_health")
    cycles_state = hass.states.get("sensor.planetpod_pp_001_total_cycles")
    assert soh_state.state == "98"
    assert cycles_state.state == "143"

    # The raw diagnostic sensor must stay genuinely raw (no backfilled values).
    last_post_state = hass.states.get("sensor.planetpod_pp_001_last_post_received")
    assert "soh" not in last_post_state.attributes["raw_payload"]["bmsData"]


async def test_standby_mode_forces_zero_setpoint(hass: HomeAssistant):
    """Standby mode must force a persistent 0kW/idle request every GET --
    sent as subMode="speed"/setpoint_kW=0.0 since firmware has no wire-level
    "standby" subMode (anything other than exactly "balance" falls through
    to its speed branch) -- confirmed this matches how the real cloud's own
    standby feature works too (just holding the setpoint at 0).
    """
    entry = await _setup_local_entry(hass, options={"mode": "speed"})
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.ingest_post("PP-001", MOCK_LOCAL_PAYLOAD)
    await hass.async_block_till_done()

    coordinator.set_speed_setpoint(2.5)
    response = coordinator.get_response_for("PP-001")
    assert response["solarSmart"]["setpoint_kW"] == 2.5

    hass.config_entries.async_update_entry(entry, options={**entry.options, "mode": "standby"})
    coordinator.async_options_updated()
    await hass.async_block_till_done()

    # Standby must override even a still-active, non-expired Speed Setpoint.
    response = coordinator.get_response_for("PP-001")
    assert response["Modus"] == "solarSmart"
    assert response["solarSmart"] == {"subMode": "speed", "setpoint_kW": 0.0}
