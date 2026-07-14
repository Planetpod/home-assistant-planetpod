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

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the pod-facing local HTTP view once, independent of any config entry."""
    _LOGGER.warning("PLANETPOD: async_setup() starting")
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(PENDING_PODS_KEY, {})

    if hass.http is not None:
        hass.http.register_view(PlanetpodLocalView())
        _LOGGER.warning("PLANETPOD: HTTP view registered at /planetpod")
    else:
        _LOGGER.warning("PLANETPOD: hass.http is None -- local mode connections will NOT work")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Planetpod from a config entry."""
    _LOGGER.warning(
        "PLANETPOD: async_setup_entry() starting for entry %s (connection_type=%s)",
        entry.entry_id,
        entry.data.get(CONF_CONNECTION_TYPE),
    )
    hass.data.setdefault(DOMAIN, {})

    if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_LOCAL:
        coordinator: Any = PlanetpodLocalCoordinator(hass, entry)

        pending: dict[str, Any] = hass.data[DOMAIN].get(PENDING_PODS_KEY, {})
        _LOGGER.warning("PLANETPOD: adopting %d pending pod payload(s)", len(pending))
        for serial, payload in list(pending.items()):
            coordinator.ingest_post(serial, payload)
            del pending[serial]
    else:
        coordinator = PlanetpodDataUpdateCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.warning("PLANETPOD: async_setup_entry() finished for entry %s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
