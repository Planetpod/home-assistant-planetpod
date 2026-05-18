"""Config flow for Planetpod integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_API_KEY, CONF_API_URL, DEFAULT_API_URL, DOMAIN
from .helpers import is_valid_grid_payload, read_json_payload

_LOGGER = logging.getLogger(__name__)


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
    hass: HomeAssistant, api_url: str, api_key: str
) -> tuple[int | None, str | None]:
    """Return the grid id on success, or an error key string on failure."""
    session = async_get_clientsession(hass)
    url = f"{api_url.rstrip('/')}/open/v1/grid/status"
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


class PlanetpodConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Planetpod."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            grid_id, error = await _validate_connection(
                self.hass,
                user_input[CONF_API_URL],
                user_input[CONF_API_KEY],
            )
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(f"planetpod_grid_{grid_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Planetpod",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_API_URL, default=DEFAULT_API_URL): str,
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )
