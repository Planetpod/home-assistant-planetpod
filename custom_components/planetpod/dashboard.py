"""Auto-provisions the "Planetpod" Lovelace dashboard from code.

There is no public/supported Home Assistant API for an integration to
create a storage-mode dashboard -- the dashboards collection lives as a
local variable inside lovelace's own async_setup() and is never exposed via
hass.data. This module reconstructs a second DashboardsCollection pointed
at the same on-disk storage key (confirmed safe by reading
homeassistant/components/lovelace/dashboard.py: the storage key is fixed,
not per-instance) to create-or-update our dashboard idempotently on every
integration setup, so dashboard layout changes ship as ordinary code
changes/releases instead of manual per-install edits.

This deliberately touches HA internals with no stability guarantee --
every call in async_ensure_dashboard is wrapped so a failure here (e.g. an
HA core update renaming these classes) can never take down the rest of the
integration; it just logs and the dashboard doesn't update that run.

Caveat: creating the dashboard for the first time registers it in the
dashboards collection but the *sidebar panel* only appears after an HA
restart (the live lovelace panel registry only reacts to changes on its
own collection instance, which this module can't reach). Content updates
to an already-created dashboard take effect immediately, no restart
needed.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, MAX_CHARGE_POWER_KW, PLANNING_HOURS

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "planetpod-home"
DASHBOARD_TITLE = "Planetpod"
DASHBOARD_ICON = "mdi:battery-charging-high"


def _eid(
    registry: er.EntityRegistry, entry_id: str, serial: str, domain: str, key: str
) -> str | None:
    """Resolve a Planetpod entity_id from its unique_id, or None if not yet registered."""
    return registry.async_get_entity_id(domain, DOMAIN, f"{entry_id}_{serial}_{key}")


def _build_view(registry: er.EntityRegistry, entry_id: str, serial: str) -> dict[str, Any] | None:
    """Build one pod's dashboard view, or None if its core entities aren't registered yet."""
    soc = _eid(registry, entry_id, serial, "sensor", "soc_pct")
    upper = _eid(registry, entry_id, serial, "number", "soc_upper_limit_pct")
    lower = _eid(registry, entry_id, serial, "number", "soc_lower_limit_pct")
    grid_delivered = _eid(registry, entry_id, serial, "sensor", "energy_grid_delivered_kwh")
    grid_returned = _eid(registry, entry_id, serial, "sensor", "energy_grid_returned_kwh")
    battery_net = _eid(registry, entry_id, serial, "sensor", "energy_battery_net_kwh")
    if not all((soc, upper, lower, grid_delivered, grid_returned, battery_net)):
        return None

    planning_entities = [
        _eid(registry, entry_id, serial, "number", f"planning_hour_{hour:02d}")
        for hour in PLANNING_HOURS
    ]
    if not all(planning_entities):
        return None

    status_entities = [
        e
        for key, domain in (
            ("mode", "select"),
            ("online", "sensor"),
            ("charge_status", "sensor"),
            ("soc_pct", "sensor"),
            ("deployed_power_kw", "sensor"),
            ("requested_power_kw", "sensor"),
            ("received_by_pod_power_kw", "sensor"),
            ("max_charge_power_kw", "sensor"),
            ("max_discharge_power_kw", "sensor"),
            ("avg_battery_temp_c", "sensor"),
            ("avg_ac_voltage_v", "sensor"),
            ("balance_g1_power_delivered_kw", "sensor"),
            ("balance_g1_power_returned_kw", "sensor"),
            ("relay_status", "sensor"),
            ("soc_upper_limit_pct", "number"),
            ("soc_lower_limit_pct", "number"),
        )
        if (e := _eid(registry, entry_id, serial, domain, key))
    ]
    buttons = [
        e
        for key in ("reboot", "calibration", "turn_off_bms")
        if (e := _eid(registry, entry_id, serial, "button", key))
    ]

    return {
        "title": f"Planetpod {serial}",
        "path": f"pod-{serial}",
        "type": "sections",
        "max_columns": 2,
        "sections": [
            {
                "type": "grid",
                "cards": [
                    {"type": "heading", "heading": "Status", "icon": "mdi:battery-charging-high"},
                    {"type": "entities", "entities": status_entities},
                    {
                        "type": "grid",
                        "columns": 3,
                        "cards": [{"type": "button", "entity": e} for e in buttons],
                    },
                ],
            },
            {
                "type": "grid",
                "cards": [
                    {"type": "heading", "heading": "Charts", "icon": "mdi:chart-line"},
                    {
                        "type": "custom:planetpod-soc-card",
                        "title": "State of Charge",
                        "entity": soc,
                        "upper_limit_entity": upper,
                        "lower_limit_entity": lower,
                        "grid_options": {"columns": "full", "rows": 8},
                    },
                    {
                        "type": "custom:planetpod-energy-card",
                        "title": "Energy per hour",
                        "grid_delivered_entity": grid_delivered,
                        "grid_returned_entity": grid_returned,
                        "battery_entity": battery_net,
                        "grid_options": {"columns": "full", "rows": 8},
                    },
                ],
            },
            {
                "type": "grid",
                "cards": [
                    {"type": "heading", "heading": "Planning", "icon": "mdi:gesture-tap-hold"},
                    {
                        "type": "custom:planetpod-planning-card",
                        "title": "Planning",
                        "entities": planning_entities,
                        "max_power_kw": MAX_CHARGE_POWER_KW,
                        "grid_options": {"columns": "full", "rows": 8},
                    },
                ],
            },
        ],
    }


def build_dashboard_config(
    registry: er.EntityRegistry, entry_id: str, serials: list[str]
) -> dict[str, Any] | None:
    """Build the full dashboard config, or None if no pod has its entities registered yet."""
    views = [v for serial in serials if (v := _build_view(registry, entry_id, serial))]
    if not views:
        return None
    return {"views": views}


async def async_ensure_dashboard(hass: HomeAssistant, entry_id: str, serials: list[str]) -> None:
    """Create-or-update the Planetpod dashboard so its layout stays in sync with the code."""
    try:
        from homeassistant.components.lovelace import dashboard as ll_dashboard
        from homeassistant.components.lovelace.const import (
            CONF_ALLOW_SINGLE_WORD,
            CONF_ICON,
            CONF_REQUIRE_ADMIN,
            CONF_SHOW_IN_SIDEBAR,
            CONF_TITLE,
            CONF_URL_PATH,
        )

        registry = er.async_get(hass)
        config = build_dashboard_config(registry, entry_id, serials)
        if config is None:
            return

        collection = ll_dashboard.DashboardsCollection(hass)
        await collection.async_load()
        item = next(
            (i for i in collection.async_items() if i.get(CONF_URL_PATH) == DASHBOARD_URL_PATH),
            None,
        )
        if item is None:
            item = await collection.async_create_item(
                {
                    CONF_URL_PATH: DASHBOARD_URL_PATH,
                    CONF_TITLE: DASHBOARD_TITLE,
                    CONF_ICON: DASHBOARD_ICON,
                    CONF_SHOW_IN_SIDEBAR: True,
                    CONF_REQUIRE_ADMIN: False,
                    CONF_ALLOW_SINGLE_WORD: False,
                }
            )
            _LOGGER.warning(
                "PLANETPOD: created the %s dashboard -- restart Home Assistant once to "
                "see it in the sidebar (later layout updates apply without a restart)",
                DASHBOARD_URL_PATH,
            )

        await ll_dashboard.LovelaceStorage(hass, item).async_save(config)
    except Exception:  # noqa: BLE001 -- internal HA API, must never break integration setup
        _LOGGER.exception("PLANETPOD: failed to auto-provision the dashboard (non-fatal)")
