"""DataUpdateCoordinator for Planetpod integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_API_KEY, DEFAULT_API_URL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .helpers import is_valid_grid_payload, read_json_payload

_LOGGER = logging.getLogger(__name__)


def _is_no_data_404(payload: dict[str, Any] | None) -> bool:
    """Detect backend 404 responses that indicate temporary no-data states."""
    if not payload:
        return False

    message = payload.get("message")
    if not isinstance(message, str):
        return False

    normalized = message.lower()
    return "no pods found" in normalized or "no pod status available" in normalized


class PlanetpodDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Planetpod data from the open API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self._api_url: str = DEFAULT_API_URL
        self._api_key: str = entry.data[CONF_API_KEY]

    async def _async_update_data(self) -> dict:
        """Fetch grid status from the Planetpod open API."""
        session = async_get_clientsession(self.hass)
        url = f"{self._api_url.rstrip('/')}/open/v1/grid/status"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed("API key expired or revoked")
                if resp.status == 404:
                    payload = await read_json_payload(resp)
                    if _is_no_data_404(payload):
                        existing_grid_id = (
                            self.data.get("grid_id")
                            if isinstance(self.data, dict)
                            and isinstance(self.data.get("grid_id"), int)
                            else 0
                        )
                        return {"grid_id": existing_grid_id, "pods": []}
                    raise UpdateFailed("Grid not found (404)")
                if resp.status != 200:
                    raise UpdateFailed(f"Unexpected status {resp.status}")
                payload = await read_json_payload(resp)
                if payload is None or not is_valid_grid_payload(payload):
                    raise UpdateFailed("Planetpod API returned an invalid response contract")
                return payload
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Error communicating with Planetpod API: {err}") from err

