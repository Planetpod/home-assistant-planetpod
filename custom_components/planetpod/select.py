"""Select platform for Planetpod integration (local mode only).

Lets an installer switch a local-mode install between Balance and Speed
mode from the HA UI, instead of it being fixed at whatever was set up
initially.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ATTRIBUTION,
    CONF_CONNECTION_TYPE,
    CONF_MODE,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
    MANUFACTURER,
    MODE_BALANCE,
    MODE_SPEED,
)
from .coordinator_local import PlanetpodLocalCoordinator

MODE_SELECT_DESCRIPTION = SelectEntityDescription(
    key="mode",
    name="Mode",
    translation_key="planetpod_mode",
    options=[MODE_BALANCE, MODE_SPEED],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the mode select entity for Planetpod (local mode only)."""
    if entry.data.get(CONF_CONNECTION_TYPE) != CONNECTION_TYPE_LOCAL:
        return

    coordinator: PlanetpodLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PlanetpodModeSelect(coordinator, entry)])


class PlanetpodModeSelect(CoordinatorEntity[PlanetpodLocalCoordinator], SelectEntity):
    """Balance/Speed mode selector for a local-mode Planetpod install."""

    entity_description = MODE_SELECT_DESCRIPTION
    _attr_has_entity_name = True
    _attr_attribution = ATTR_ATTRIBUTION

    def __init__(self, coordinator: PlanetpodLocalCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_mode"

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Planetpod",
            "manufacturer": MANUFACTURER,
        }

    @property
    def current_option(self) -> str:
        return self.coordinator.mode

    async def async_select_option(self, option: str) -> None:
        new_options = {**self._entry.options, CONF_MODE: option}
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.coordinator.async_options_updated()
