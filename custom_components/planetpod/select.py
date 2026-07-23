"""Select platform for Planetpod integration (local mode only).

Lets an installer switch a local-mode install between Balance, Speed, and
Standby mode from the HA UI, instead of it being fixed at whatever was set
up initially. Mode is shared across the install but shown on each pod's own
device, same reasoning as number.py's SoC limits.

Standby here means "hold output at idle" -- confirmed this is exactly how
the real cloud implements its own standby feature too (forcing
setpoint_kW=0 persistently), not the pod's own separate internal hardware
Mode::STANDBY state (which fires autonomously from lost-cloud-connection/
error conditions and isn't remotely controllable -- see Pod Mode sensor).
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
    MODE_STANDBY,
)
from .coordinator_local import PlanetpodLocalCoordinator

MODE_SELECT_DESCRIPTION = SelectEntityDescription(
    key="mode",
    name="Mode",
    translation_key="planetpod_mode",
    options=[MODE_BALANCE, MODE_SPEED, MODE_STANDBY],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the mode select entity for Planetpod (local mode only), one per pod."""
    if entry.data.get(CONF_CONNECTION_TYPE) != CONNECTION_TYPE_LOCAL:
        return

    coordinator: PlanetpodLocalCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_serials: set[str] = set()

    def _add_new_pods() -> None:
        pods: list[dict] = coordinator.data.get("pods", []) if coordinator.data else []
        new_entities: list[PlanetpodModeSelect] = []
        for pod in pods:
            serial = pod.get("battery", {}).get("serial_number")
            if not serial or serial in known_serials:
                continue
            known_serials.add(serial)
            new_entities.append(PlanetpodModeSelect(coordinator, entry, serial))
        if new_entities:
            async_add_entities(new_entities, False)

    _add_new_pods()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_pods))


class PlanetpodModeSelect(CoordinatorEntity[PlanetpodLocalCoordinator], SelectEntity):
    """Balance/Speed mode selector, shared across the install but shown per-pod."""

    entity_description = MODE_SELECT_DESCRIPTION
    _attr_has_entity_name = True
    _attr_attribution = ATTR_ATTRIBUTION

    def __init__(
        self, coordinator: PlanetpodLocalCoordinator, entry: ConfigEntry, serial_number: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._serial = serial_number
        self._attr_unique_id = f"{entry.entry_id}_{serial_number}_mode"

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._serial)},
            "name": f"Planetpod {self._serial}",
            "manufacturer": MANUFACTURER,
        }

    @property
    def current_option(self) -> str:
        return self.coordinator.mode

    async def async_select_option(self, option: str) -> None:
        new_options = {**self._entry.options, CONF_MODE: option}
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.coordinator.async_options_updated()
