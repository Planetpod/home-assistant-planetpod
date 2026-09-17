"""Tests for the auto-provisioned dashboard's config-building logic.

Only the pure build_dashboard_config()/_build_view() path is tested here --
async_ensure_dashboard() touches homeassistant.components.lovelace internals
directly and is out of scope for unit tests (see dashboard.py's module
docstring for why). Planning number entities only exist in local mode (see
number.py), so these tests use a local config entry with an ingested pod
POST, not the cloud loaded_config_entry fixture.
"""
from __future__ import annotations

from unittest.mock import patch

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
SERIAL_2 = "PP-002"
MOCK_LOCAL_PAYLOAD_2 = {
    "timestamp": "2026-07-14T12:00:05.000Z",
    "systemInfo": {"podSerialNumber": SERIAL_2, "firmwareVersion": "1.1.8"},
    "g1Data": {"powerDelivered": 0, "powerReturned": 1.2},
    "bmsData": {"socPct": 40, "soh": 95, "cycleCount": 88, "avgTempC": 25.1},
    "podStatus": {"podChargingStatus": "charge", "podMode": "balance"},
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

    status_section = view["sections"][0]
    kpi_card = next(c for c in status_section["cards"] if c["type"] == "custom:planetpod-kpi-card")
    assert [t["kind"] for t in kpi_card["tiles"]] == [
        "value_subtitle",
        "dual_signed",
        "value",
        "net_signed",
        "text",
        "text",
    ]
    soc_tile = kpi_card["tiles"][0]
    assert soc_tile["entity"].startswith("sensor.")
    assert soc_tile["subtitle_entity"].startswith("sensor.")
    online_tile, relay_tile = kpi_card["tiles"][4], kpi_card["tiles"][5]
    assert online_tile["label"] == "Online"
    assert online_tile["entity"].startswith("sensor.")
    assert relay_tile["label"] == "Relay Status"
    assert relay_tile["entity"].startswith("sensor.")

    charts_section, details_section = view["sections"][1], view["sections"][2]
    soc_card = next(c for c in charts_section["cards"] if c["type"] == "custom:planetpod-soc-card")
    assert soc_card["entity"].startswith("sensor.")

    planning_card = next(
        c for c in charts_section["cards"] if c["type"] == "custom:planetpod-planning-card"
    )
    assert len(planning_card["entities"]) == 24
    assert all(e.startswith("number.") for e in planning_card["entities"])

    entity_stacks = [c for c in details_section["cards"] if c["type"] == "vertical-stack"]
    assert len(entity_stacks) == 3
    soc_limit_stack, button_stack, mode_stack = entity_stacks

    mode_card = mode_stack["cards"][0]
    assert mode_card["type"] == "custom:mushroom-entity-card"
    assert mode_card["name"] == "Mode"
    assert mode_card["entity"].startswith("select.")

    speed_conditional = mode_stack["cards"][1]
    assert speed_conditional["type"] == "conditional"
    assert speed_conditional["conditions"] == [
        {"entity": mode_card["entity"], "state": "speed"}
    ]
    speed_card_types = [c["type"] for c in speed_conditional["card"]["cards"]]
    assert speed_card_types == [
        "custom:mushroom-number-card",
        "custom:mushroom-number-card",
        "custom:mushroom-entity-card",
    ]

    assert all(c["type"] == "custom:mushroom-entity-card" for c in soc_limit_stack["cards"])
    assert all(c.get("name") for c in soc_limit_stack["cards"])

    assert len(button_stack["cards"]) == 3
    assert all(c["type"] == "custom:mushroom-entity-card" for c in button_stack["cards"])
    assert {c["name"] for c in button_stack["cards"]} == {"Reboot", "Calibration", "Turn Off BMS"}

    logbook_card = next(c for c in details_section["cards"] if c["type"] == "logbook")
    assert sum(e.startswith("number.") and "planning" in e for e in logbook_card["entities"]) == 24


async def test_build_dashboard_config_skips_unknown_pod(hass: HomeAssistant):
    """A serial with no registered entities is dropped, not left half-built."""
    entry = await _setup_local_entry_with_pod(hass)
    registry = er.async_get(hass)

    config = build_dashboard_config(registry, entry.entry_id, [SERIAL, "UNKNOWN-SERIAL"])

    assert len(config["views"]) == 1
    assert config["views"][0]["path"] == f"pod-{SERIAL}"


async def test_dashboard_retries_a_pod_not_yet_saved_instead_of_dropping_it_forever(
    hass: HomeAssistant,
):
    """Regression test for a real production bug: two pods on one grid, but
    the sidebar dashboard only ever showed one pod's tab -- confirmed live,
    where both pods' entities (61 each) were fully registered yet the second
    pod's view never appeared.

    Root cause: __init__.py's _maybe_update_dashboard marked a newly-seen
    serial as "known" as soon as the coordinator reported it, regardless of
    whether async_ensure_dashboard actually managed to save a view for it.
    Since entity registration (sensor.py/number.py/etc.'s own listeners) and
    the dashboard rebuild race against each other, a pod whose entities
    hadn't finished registering yet got silently dropped from the built
    config (see build_dashboard_config) -- and because "known" already
    included it, the guard that would normally trigger a rebuild on the
    next coordinator update (`serials != known_dashboard_serials`) never
    fired again. That pod's tab was gone permanently, not just delayed.

    This simulates exactly that: async_ensure_dashboard returns a *partial*
    result (as it now can, see its own docstring) the first time PP-002
    shows up, standing in for its entities not being registered yet.
    """
    calls: list[list[str]] = []

    async def fake_ensure_dashboard(hass, entry_id, serials):
        sorted_serials = sorted(serials)
        calls.append(sorted_serials)
        if SERIAL_2 in serials and len(calls) == 2:
            # Simulate PP-002's entities not being in the registry yet on
            # its first appearance -- only PP-001's view got saved.
            return {SERIAL}
        return set(serials)

    with patch(
        "custom_components.planetpod.async_ensure_dashboard",
        side_effect=fake_ensure_dashboard,
    ):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Planetpod",
            data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
            options={},
            unique_id="planetpod_local_dashboard_retry_test",
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator.ingest_post(SERIAL, MOCK_LOCAL_PAYLOAD)
        await hass.async_block_till_done()
        coordinator.ingest_post(SERIAL_2, MOCK_LOCAL_PAYLOAD_2)
        await hass.async_block_till_done()

        assert calls == [[SERIAL], [SERIAL, SERIAL_2]]

        # PP-002 wasn't confirmed saved -- a later coordinator update (any
        # pod's next periodic POST) must retry it, not silently accept the
        # partial result as "done".
        coordinator.ingest_post(SERIAL, MOCK_LOCAL_PAYLOAD)
        await hass.async_block_till_done()

        assert calls == [[SERIAL], [SERIAL, SERIAL_2], [SERIAL, SERIAL_2]]
