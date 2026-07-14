"""The Planetpod integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api_local import PlanetpodLocalView
from .const import CONF_CONNECTION_TYPE, CONNECTION_TYPE_LOCAL, DOMAIN, PENDING_PODS_KEY
from .coordinator import PlanetpodDataUpdateCoordinator
from .coordinator_local import PlanetpodLocalCoordinator

_LOGGER: logging.Logger = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the pod-facing local HTTP view once, independent of any config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(PENDING_PODS_KEY, {})

    if hass.http is not None:
        hass.http.register_view(PlanetpodLocalView())
    else:
        _LOGGER.warning("HTTP component not available; local mode connections will not work")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Planetpod from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_LOCAL:
        coordinator: Any = PlanetpodLocalCoordinator(hass, entry)

        pending: dict[str, Any] = hass.data[DOMAIN].get(PENDING_PODS_KEY, {})
        for serial, payload in list(pending.items()):
            coordinator.ingest_post(serial, payload)
            del pending[serial]
    else:
        coordinator = PlanetpodDataUpdateCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
