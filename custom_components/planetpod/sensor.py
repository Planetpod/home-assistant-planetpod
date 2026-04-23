"""Sensor platform for Planetpod integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTR_ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import PlanetpodDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform for Planetpod."""
    coordinator: PlanetpodDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = [
        PlanetpodStatusSensor(coordinator, entry),
    ]

    async_add_entities(sensors, False)


class PlanetpodStatusSensor(SensorEntity):
    """Representation of a Planetpod status sensor."""

    def __init__(self, coordinator: PlanetpodDataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_name = f"Planetpod Status"
        self._attr_manufacturer = MANUFACTURER
        self._attr_attribution = ATTR_ATTRIBUTION

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": f"Planetpod {self.entry.data.get('host')}",
            "manufacturer": MANUFACTURER,
        }

    @property
    def native_value(self) -> str | None:
        """Return the state."""
        return self.coordinator.data.get("status") if self.coordinator.data else None

    @property
    def available(self) -> bool:
        """Return availability."""
        return self.coordinator.last_update_success

    @property
    def should_poll(self) -> bool:
        """Return False, polling handled by coordinator."""
        return False

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
