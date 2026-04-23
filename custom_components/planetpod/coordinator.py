"""DataUpdateCoordinator for Planetpod integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class PlanetpodDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Planetpod data from API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self.host = entry.data.get("host")
        self.port = entry.data.get("port", 8000)
        self.username = entry.data.get("username")
        self.password = entry.data.get("password")

    async def _async_update_data(self) -> dict:
        """Fetch data from Planetpod API."""
        try:
            # Placeholder for actual API call
            # TODO: Implement actual Planetpod API communication
            data = {
                "status": "online",
                "data": {}
            }
            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Planetpod: {err}") from err
