"""Config flow for Planetpod integration."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_CONNECTION_TYPE,
    CONF_G1_HA_ENTITY_ID,
    CONF_G1_SOURCE,
    CONNECTION_TYPE_CLOUD,
    CONNECTION_TYPE_LOCAL,
    DEFAULT_API_URL,
    DOMAIN,
    G1_SOURCE_HA_SENSOR,
    G1_SOURCE_POD,
    PENDING_PODS_KEY,
)
from .helpers import is_valid_grid_payload, read_json_payload

_LOGGER = logging.getLogger(__name__)

_G1_CANDIDATE_HINTS = ("dsmr", "p1_meter", "power_consumption")


def _classify_404_error(payload: dict[str, Any] | None) -> str:
    """Map backend 404 payloads to more specific config flow errors."""
    if not payload:
        return "grid_not_found"

    message = payload.get("message")
    if isinstance(message, str):
        normalized = message.lower()
        if "no pods found" in normalized or "no pod status available" in normalized:
            return "no_data_yet"

    return "grid_not_found"


async def _validate_connection(
    hass: HomeAssistant, api_key: str
) -> tuple[int | None, str | None]:
    """Return the grid id on success, or an error key string on failure."""
    session = async_get_clientsession(hass)
    url = f"{DEFAULT_API_URL}/open/v1/grid/status"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 401:
                return None, "invalid_auth"
            if resp.status == 404:
                return None, _classify_404_error(await read_json_payload(resp))
            if resp.status != 200:
                return None, "cannot_connect"
            payload = await read_json_payload(resp)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None, "cannot_connect"

    if payload is None or not is_valid_grid_payload(payload):
        return None, "invalid_response"

    if len(payload["pods"]) == 0:
        return None, "no_data_yet"

    return payload["grid_id"], None


@callback
def _find_g1_candidate(hass: HomeAssistant) -> str | None:
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if entry.domain != "sensor":
            continue
        entity_id = entry.entity_id.lower()
        if any(hint in entity_id for hint in _G1_CANDIDATE_HINTS):
            return entry.entity_id
    return None


def _ha_address(hass: HomeAssistant) -> str:
    if hass.config.internal_url:
        return hass.config.internal_url
    port = hass.http.server_port if hass.http else 8123
    return f"http://homeassistant.local:{port}"


class PlanetpodConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Planetpod."""

    VERSION = 1

    def __init__(self) -> None:
        self._local_options: dict[str, Any] = {}

    # Compatibility shims for HA < 2024.x
    def _get_reconfigure_entry(self) -> config_entries.ConfigEntry:
        return self.hass.config_entries.async_get_entry(self.context["entry_id"])

    def _get_reauth_entry(self) -> config_entries.ConfigEntry:
        return self.hass.config_entries.async_get_entry(self.context["entry_id"])

    def _abort_if_unique_id_mismatch(self) -> None:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry and entry.unique_id != self.unique_id:
            raise config_entries.data_entry_flow.AbortFlow("unique_id_mismatch")

    async def async_update_reload_and_abort(
        self,
        entry: config_entries.ConfigEntry,
        *,
        data_updates: dict[str, Any] | None = None,
        reason: str = "reconfigure_successful",
    ) -> config_entries.data_entry_flow.FlowResult:
        if data_updates:
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, **data_updates}
            )
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_abort(reason=reason)

    # --- Entry point: choose Cloud vs Local -----------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: how does your Planetpod connect."""
        if user_input is not None:
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_TYPE_LOCAL:
                return await self.async_step_local_g1()
            return await self.async_step_cloud()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_CLOUD
                    ): vol.In([CONNECTION_TYPE_CLOUD, CONNECTION_TYPE_LOCAL])
                }
            ),
        )

    # --- Cloud path (existing behavior, unmodified) ----------------------

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the cloud API-key step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            grid_id, error = await _validate_connection(self.hass, user_input[CONF_API_KEY])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(f"planetpod_grid_{grid_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Planetpod",
                    data={
                        CONF_API_KEY: user_input[CONF_API_KEY],
                        CONF_CONNECTION_TYPE: CONNECTION_TYPE_CLOUD,
                    },
                )

        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            grid_id, error = await _validate_connection(self.hass, user_input[CONF_API_KEY])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(f"planetpod_grid_{grid_id}")
                self._abort_if_unique_id_mismatch()
                return await self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY]}
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle re-authentication triggered by a 401."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the re-authentication form."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            grid_id, error = await _validate_connection(self.hass, user_input[CONF_API_KEY])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(f"planetpod_grid_{grid_id}")
                self._abort_if_unique_id_mismatch()
                return await self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    # --- Local path -------------------------------------------------------

    async def async_step_local_g1(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask which G1 reading Balance mode should use, if a candidate exists."""
        await self.async_set_unique_id("planetpod_local")
        self._abort_if_unique_id_configured()

        candidate = _find_g1_candidate(self.hass)

        if candidate is None:
            self._local_options = {CONF_G1_SOURCE: G1_SOURCE_POD}
            return await self.async_step_local_connect()

        if user_input is not None:
            self._local_options = {CONF_G1_SOURCE: G1_SOURCE_POD}
            if user_input["g1_choice"] == candidate:
                self._local_options[CONF_G1_SOURCE] = G1_SOURCE_HA_SENSOR
                self._local_options[CONF_G1_HA_ENTITY_ID] = candidate
            return await self.async_step_local_connect()

        return self.async_show_form(
            step_id="local_g1",
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

    async def async_step_local_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Wait for at least one real pod connection before finishing setup."""
        pending: dict[str, Any] = self.hass.data.get(DOMAIN, {}).get(PENDING_PODS_KEY, {})

        if pending:
            return self.async_create_entry(
                title="Planetpod",
                data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
                options=self._local_options,
            )

        return self.async_show_form(
            step_id="local_connect",
            data_schema=vol.Schema({}),
            description_placeholders={"ha_address": _ha_address(self.hass)},
        )
