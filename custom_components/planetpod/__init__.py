"""The Planetpod integration."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import entity_registry as er

from .api_local import ensure_local_view_registered
from .const import CONF_CONNECTION_TYPE, CONNECTION_TYPE_LOCAL, DOMAIN, PENDING_PODS_KEY
from .coordinator import PlanetpodDataUpdateCoordinator
from .coordinator_local import PlanetpodLocalCoordinator

_LOGGER: logging.Logger = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT, Platform.BUTTON]

# Bundled Lovelace cards (SoC / Energy / Planning), served straight from the
# integration's www/ folder and self-registered as a frontend resource on
# every boot -- avoids asking the user to add a dashboard resource by hand,
# the way most HACS cards require.
_CARD_URL = f"/{DOMAIN}_static/planetpod-cards.js"


async def _async_register_frontend_resources(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_static_registered"):
        return
    domain_data["_static_registered"] = True

    www_path = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"/{DOMAIN}_static", str(www_path), cache_headers=False)]
    )
    # frontend is a core component always loaded before custom integrations
    # in a real HA install, but isn't guaranteed present in a minimal test
    # environment -- skip registering the resource rather than failing setup.
    try:
        add_extra_js_url(hass, _CARD_URL)
    except KeyError:
        _LOGGER.debug("PLANETPOD: frontend component not loaded, skipping dashboard resource registration")

# Buttons removed from button.py's BUTTON_DESCRIPTIONS -- HA does not delete
# an entity from the registry just because the integration stops creating
# it (it's left behind, usually shown as unavailable), so this must be done
# explicitly on every setup or the removed buttons keep reappearing.
_REMOVED_BUTTON_KEYS = ("unlock_scu", "bms_update", "debug_on")


def _remove_stale_button_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity_entry.domain != "button":
            continue
        if entity_entry.unique_id.endswith(tuple(f"_{key}" for key in _REMOVED_BUTTON_KEYS)):
            _LOGGER.warning(
                "PLANETPOD: removing stale button entity %s (unique_id=%s)",
                entity_entry.entity_id,
                entity_entry.unique_id,
            )
            registry.async_remove(entity_entry.entity_id)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the pod-facing local HTTP view.

    NOTE: this only runs at boot if a config entry already exists (or the
    domain is in configuration.yaml) -- it does NOT run just because someone
    opens the config flow. ensure_local_view_registered() is also called
    from config_flow.py to cover a brand-new install with no entry yet.
    """
    _LOGGER.warning("PLANETPOD: async_setup() starting")
    ensure_local_view_registered(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Planetpod from a config entry."""
    _LOGGER.warning(
        "PLANETPOD: async_setup_entry() starting for entry %s (connection_type=%s)",
        entry.entry_id,
        entry.data.get(CONF_CONNECTION_TYPE),
    )
    hass.data.setdefault(DOMAIN, {})
    await _async_register_frontend_resources(hass)

    if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_LOCAL:
        _remove_stale_button_entities(hass, entry)

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
