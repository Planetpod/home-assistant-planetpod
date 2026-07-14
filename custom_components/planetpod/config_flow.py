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
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_local import ensure_local_view_registered
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


def _g1_schema(*, default_source: str, default_entity_id: str | None) -> vol.Schema:
    """Build the G1-source form schema, always letting the user pick manually."""
    fields: dict[Any, Any] = {
        vol.Required(CONF_G1_SOURCE, default=default_source): vol.In(
            {
                G1_SOURCE_POD: "Pod-reported",
                G1_SOURCE_HA_SENSOR: "Use a Home Assistant sensor",
            }
        ),
    }
    entity_selector = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    if default_entity_id:
        fields[vol.Optional(CONF_G1_HA_ENTITY_ID, default=default_entity_id)] = entity_selector
    else:
        fields[vol.Optional(CONF_G1_HA_ENTITY_ID)] = entity_selector
    return vol.Schema(fields)


def _g1_options_from_input(user_input: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return (options, error) from a submitted G1-source form."""
    source = user_input[CONF_G1_SOURCE]
    if source == G1_SOURCE_HA_SENSOR:
        entity_id = user_input.get(CONF_G1_HA_ENTITY_ID)
        if not entity_id:
            return {}, "g1_entity_required"
        return {CONF_G1_SOURCE: G1_SOURCE_HA_SENSOR, CONF_G1_HA_ENTITY_ID: entity_id}, None
    return {CONF_G1_SOURCE: G1_SOURCE_POD}, None


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
                return await self.async_step_local_connect()
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
        entry = self._get_reconfigure_entry()

        if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_LOCAL:
            return await self.async_step_reconfigure_local()

        errors: dict[str, str] = {}

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

    async def async_step_reconfigure_local(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of a local-mode entry: change the G1 source."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            options, error = _g1_options_from_input(user_input)
            if error:
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(entry, options=options)
                return await self.async_update_reload_and_abort(entry)

        current_source = entry.options.get(CONF_G1_SOURCE, G1_SOURCE_POD)
        current_entity_id = entry.options.get(CONF_G1_HA_ENTITY_ID)

        return self.async_show_form(
            step_id="reconfigure_local",
            data_schema=_g1_schema(
                default_source=current_source,
                default_entity_id=current_entity_id or _find_g1_candidate(self.hass),
            ),
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

    async def async_step_local_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Wait for at least one real pod connection before asking anything else."""
        await self.async_set_unique_id("planetpod_local")
        self._abort_if_unique_id_configured()

        # async_setup() only runs at boot if a config entry already exists --
        # for a brand-new install there isn't one yet, so the HTTP view must
        # be registered here too, the first time this step actually runs.
        ensure_local_view_registered(self.hass)

        pending: dict[str, Any] = self.hass.data.get(DOMAIN, {}).get(PENDING_PODS_KEY, {})

        if pending:
            return await self.async_step_local_g1()

        return self.async_show_form(
            step_id="local_connect",
            data_schema=vol.Schema({}),
            description_placeholders={"ha_address": _ha_address(self.hass)},
        )

    async def async_step_local_g1(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask which G1 reading Balance mode should use -- always shown, the
        user can pick any sensor manually even if none was auto-detected."""
        candidate = _find_g1_candidate(self.hass)
        errors: dict[str, str] = {}

        if user_input is not None:
            options, error = _g1_options_from_input(user_input)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="Planetpod",
                    data={CONF_CONNECTION_TYPE: CONNECTION_TYPE_LOCAL},
                    options=options,
                )

        return self.async_show_form(
            step_id="local_g1",
            data_schema=_g1_schema(
                default_source=G1_SOURCE_HA_SENSOR if candidate else G1_SOURCE_POD,
                default_entity_id=candidate,
            ),
            errors=errors,
        )
