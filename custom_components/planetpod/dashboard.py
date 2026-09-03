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

    charge_status = _eid(registry, entry_id, serial, "sensor", "charge_status")
    deployed_power = _eid(registry, entry_id, serial, "sensor", "deployed_power_kw")
    requested_power = _eid(registry, entry_id, serial, "sensor", "requested_power_kw")
    battery_temp = _eid(registry, entry_id, serial, "sensor", "avg_battery_temp_c")
    p1_delivered = _eid(registry, entry_id, serial, "sensor", "balance_g1_power_delivered_kw")
    p1_returned = _eid(registry, entry_id, serial, "sensor", "balance_g1_power_returned_kw")
    if not all(
        (charge_status, deployed_power, requested_power, battery_temp, p1_delivered, p1_returned)
    ):
        return None


    kpi_tiles = [
        {
            "kind": "value_subtitle",
            "label": "State of Charge",
            "entity": soc,
            "unit": "%",
            "subtitle_entity": charge_status,
        },
        {
            "kind": "dual_signed",
            "label": "Deployed Power",
            "primary_entity": deployed_power,
            "secondary_entity": requested_power,
            "secondary_label": "Requested",
            "unit": "kW",
        },
        {
            "kind": "value",
            "label": "Temperature",
            "entity": battery_temp,
            "unit": "°C",
        },
        {
            "kind": "net_signed",
            "label": "P1 Meter",
            "positive_entity": p1_delivered,
            "negative_entity": p1_returned,
            "unit": "kW",
        },
    ]

    ENTITY_LABELS = {
        "mode": "Mode",
        "online": "Online",
        "max_charge_power_kw": "Max Charge Power",
        "max_discharge_power_kw": "Max Discharge Power",
        "relay_status": "Relay Status",
        "soc_upper_limit_pct": "SoC Upper Limit",
        "soc_lower_limit_pct": "SoC Lower Limit",
        "reboot": "Reboot",
        "toggle_calibration": "Calibration",
        "turn_off_bms": "Turn Off BMS",
    }

    def _eids(*keys_domains: tuple[str, str]) -> list[tuple[str, str]]:
        return [
            (e, ENTITY_LABELS[key])
            for key, domain in keys_domains
            if (e := _eid(registry, entry_id, serial, domain, key))
        ]

    entity_col_1 = _eids(("mode", "select"), ("online", "sensor"))
    entity_col_2 = _eids(
        ("max_charge_power_kw", "sensor"), ("max_discharge_power_kw", "sensor"), ("relay_status", "sensor")
    )
    entity_col_3 = _eids(("soc_upper_limit_pct", "number"), ("soc_lower_limit_pct", "number"))
    buttons = _eids(
        ("reboot", "button"), ("toggle_calibration", "button"), ("turn_off_bms", "button")
    )

    activity_entities = [
        e
        for e in (
            *(e for e, _label in entity_col_1),
            *(e for e, _label in entity_col_2),
            *(e for e, _label in entity_col_3),
            *(e for e, _label in buttons),
            *planning_entities,
            soc,
            deployed_power,
            requested_power,
        )
        if e
    ]

    return {
        "title": f"Planetpod {serial}",
        "path": f"pod-{serial}",
        "type": "sections",
        "max_columns": 4,
        "sections": [
            {
                "type": "grid",
                "column_span": 4,
                "cards": [
                    {
                        "type": "custom:planetpod-kpi-card",
                        "tiles": kpi_tiles,
                        "grid_options": {"columns": "full", "rows": "auto"},
                    },
                ],
            },
            {
                "type": "grid",
                "column_span": 4,
                "cards": [
                    {
                        "type": "custom:planetpod-soc-card",
                        "title": "SoC (%)",
                        "entity": soc,
                        "upper_limit_entity": upper,
                        "lower_limit_entity": lower,
                        "grid_options": {"columns": 16, "rows": "auto"},
                    },
                    {
                        "type": "custom:planetpod-energy-card",
                        "title": "Energy Usage",
                        "grid_delivered_entity": grid_delivered,
                        "grid_returned_entity": grid_returned,
                        "battery_entity": battery_net,
                        "grid_options": {"columns": 16, "rows": "auto"},
                    },
                    {
                        "type": "custom:planetpod-planning-card",
                        "title": "Planning",
                        "entities": planning_entities,
                        "max_power_kw": MAX_CHARGE_POWER_KW,
                        "grid_options": {"columns": 16, "rows": "auto"},
                    },
                ],
            },
            {
                "type": "grid",
                "column_span": 4,
                "cards": [
                    {
                        "type": "vertical-stack",
                        "cards": [
                            {"type": "custom:mushroom-entity-card", "entity": e, "name": label}
                            for e, label in entity_col_1
                        ],
                        "grid_options": {"columns": 8, "rows": "auto"},
                    },
                    {
                        "type": "vertical-stack",
                        "cards": [
                            {"type": "custom:mushroom-entity-card", "entity": e, "name": label}
                            for e, label in entity_col_2
                        ],
                        "grid_options": {"columns": 8, "rows": "auto"},
                    },
                    {
                        "type": "vertical-stack",
                        "cards": [
                            {"type": "custom:mushroom-entity-card", "entity": e, "name": label}
                            for e, label in entity_col_3
                        ],
                        "grid_options": {"columns": 8, "rows": "auto"},
                    },
                    {
                        "type": "vertical-stack",
                        "cards": [
                            {
                                "type": "custom:mushroom-entity-card",
                                "entity": e,
                                "name": label,
                                "icon_color": "#f8333c",
                            }
                            for e, label in buttons
                        ],
                        "grid_options": {"columns": 8, "rows": "auto"},
                    },
                    {
                        "type": "logbook",
                        "entities": activity_entities,
                        "grid_options": {"columns": 16, "rows": "auto"},
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
