"""The Planetpod Local integration.

Separate from `custom_components.planetpod` (cloud) by design, with no
shared code path, so the existing production integration is never touched
or put at risk by this one.

The HTTP view is registered at component-setup time (`async_setup`), not
per-entry, so it can receive a pod's first POST *before* any config entry
exists -- this is what lets the config flow's "Connect your Planetpod"
step actually detect a real connection instead of just starting a server
and hoping (see config_flow.py / PENDING_PODS_KEY below).
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import PlanetpodLocalView
from .const import DOMAIN, PENDING_PODS_KEY
from .coordinator import PlanetpodLocalCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the pod-facing HTTP view once, independent of any config entry."""
    hass.data.setdefault(DOMAIN, {})
    # Payloads from pods not yet claimed by a config entry's coordinator,
    # keyed by serial -- read by the config flow's "connect" step.
    hass.data[DOMAIN].setdefault(PENDING_PODS_KEY, {})

    hass.http.register_view(PlanetpodLocalView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Planetpod Local from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = PlanetpodLocalCoordinator(hass, entry)

    # Adopt any payload that arrived while this pod was still "pending"
    # (i.e. POSTed during the config flow's connect step, before this entry
    # -- and therefore this coordinator -- existed).
    pending: dict[str, Any] = hass.data[DOMAIN].get(PENDING_PODS_KEY, {})
    for serial, payload in list(pending.items()):
        coordinator.ingest_post(serial, payload)
        del pending[serial]

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
