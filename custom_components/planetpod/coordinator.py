"""DataUpdateCoordinator for Planetpod integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_API_KEY, CONF_API_URL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


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
        self._api_url: str = entry.data[CONF_API_URL]
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
                    raise UpdateFailed("Invalid API key (401 Unauthorized)")
                if resp.status == 404:
                    raise UpdateFailed("Grid not found (404)")
                if resp.status != 200:
                    raise UpdateFailed(f"Unexpected status {resp.status}")
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Error communicating with Planetpod API: {err}") from err

