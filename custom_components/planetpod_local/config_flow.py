"""Config flow for Planetpod Local integration.

Two plain steps:
  1. G1 setup   -- which grid meter reading should Balance mode use.
  2. Battery(s) setup -- wait for at least one pod to actually connect
     before finishing, with a retry action if none has shown up yet.

SoC limits and sound mode are NOT asked here at all (silently defaulted,
editable later as entities/options).
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_G1_HA_ENTITY_ID,
    CONF_G1_SOURCE,
    DOMAIN,
    G1_SOURCE_HA_SENSOR,
    G1_SOURCE_POD,
    PENDING_PODS_KEY,
)

# Heuristic match for common Dutch smart-meter (P1/DSMR) integrations, until
# a more principled detection (e.g. by device_class + unit) is worth adding.
_G1_CANDIDATE_HINTS = ("dsmr", "p1_meter", "power_consumption")


@callback
def _find_g1_candidate(hass: HomeAssistant) -> str | None:
    """Return an existing entity_id that looks like a P1/grid-power sensor, if any."""
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if entry.domain != "sensor":
            continue
        entity_id = entry.entity_id.lower()
        if any(hint in entity_id for hint in _G1_CANDIDATE_HINTS):
            return entry.entity_id
    return None


def _ha_address(hass: HomeAssistant) -> str:
    """Best-effort local HA address to show the user for troubleshooting.

    Deliberately avoids `homeassistant.helpers.network.get_url` -- its exact
    keyword signature varies across HA versions and couldn't be verified
    against an installed `homeassistant` package in this environment.
    `hass.config.internal_url` is a plain, stable attribute instead.
    """
    if hass.config.internal_url:
        return hass.config.internal_url
    port = hass.http.server_port if hass.http else 8123
    return f"http://homeassistant.local:{port}"


class PlanetpodLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Planetpod Local."""

    VERSION = 1

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    # --- Step 1: G1 setup ---------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask which G1 reading Balance mode should use, if a candidate exists."""
        self._abort_if_unique_id_configured()

        candidate = _find_g1_candidate(self.hass)

        if candidate is None:
            # Nothing to choose from -- skip straight to pod-reported.
            self._options = {CONF_G1_SOURCE: G1_SOURCE_POD}
            return await self.async_step_connect()

        if user_input is not None:
            self._options = {CONF_G1_SOURCE: G1_SOURCE_POD}
            if user_input["g1_choice"] == candidate:
                self._options[CONF_G1_SOURCE] = G1_SOURCE_HA_SENSOR
                self._options[CONF_G1_HA_ENTITY_ID] = candidate
            return await self.async_step_connect()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("g1_choice", default=G1_SOURCE_POD): vol.In(
                        {
                            G1_SOURCE_POD: "Pod-reported",
                            candidate: candidate,
                            "not_now": "Not now",
                        }
                    ),
                }
            ),
        )

    # --- Step 2: battery(s) setup --------------------------------------

    async def async_step_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Wait for at least one real pod connection before finishing setup."""
        pending: dict[str, Any] = self.hass.data.get(DOMAIN, {}).get(PENDING_PODS_KEY, {})

        if pending:
            # At least one pod has already POSTed -- finish setup. The
            # buffered payload(s) get adopted by async_setup_entry.
            return self.async_create_entry(
                title="Planetpod", data={}, options=self._options
            )

        # Still nothing -- (re)show the waiting screen. A plain form
        # re-invokes this same step on submit, which is the "Retry" action.
        return self.async_show_form(
            step_id="connect",
            data_schema=vol.Schema({}),
            description_placeholders={"ha_address": _ha_address(self.hass)},
        )
