"""Number platform for Planetpod integration (local mode only).

Cloud entries get SoC limits as read-only sensors, sourced from the app;
local entries have no cloud/app to configure them, so they're writable
entities here instead. These values are mirrored across every pod on the
install (see modus_controller.ts's grid-wide behavior), but are attached to
each pod's own device so everything for that pod appears in one place --
writing from any pod's slider updates the same shared config entry option.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ATTRIBUTION,
    CONF_CONNECTION_TYPE,
    CONF_SOC_LOWER_LIMIT,
    CONF_SOC_UPPER_LIMIT,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator_local import PlanetpodLocalCoordinator


@dataclass
class PlanetpodNumberEntityDescription(NumberEntityDescription):
    """Describes a Planetpod local-mode number entity."""

    option_key: str = ""
    value_fn: Callable[[PlanetpodLocalCoordinator], float] = lambda _: 0.0


NUMBER_DESCRIPTIONS: tuple[PlanetpodNumberEntityDescription, ...] = (
    PlanetpodNumberEntityDescription(
        key="soc_upper_limit_pct",
        name="SoC Upper Limit",
        option_key=CONF_SOC_UPPER_LIMIT,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda coordinator: coordinator.soc_upper_limit_pct,
    ),
    PlanetpodNumberEntityDescription(
        key="soc_lower_limit_pct",
        name="SoC Lower Limit",
        option_key=CONF_SOC_LOWER_LIMIT,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda coordinator: coordinator.soc_lower_limit_pct,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities for Planetpod (local mode only), one set per pod."""
    if entry.data.get(CONF_CONNECTION_TYPE) != CONNECTION_TYPE_LOCAL:
        return

    coordinator: PlanetpodLocalCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_serials: set[str] = set()

    def _add_new_pods() -> None:
        pods: list[dict] = coordinator.data.get("pods", []) if coordinator.data else []
        new_entities: list[PlanetpodSocLimitNumber] = []
        for pod in pods:
            serial = pod.get("battery", {}).get("serial_number")
            if not serial or serial in known_serials:
                continue
            known_serials.add(serial)
            for description in NUMBER_DESCRIPTIONS:
                new_entities.append(PlanetpodSocLimitNumber(coordinator, entry, description, serial))
        if new_entities:
            async_add_entities(new_entities, False)

    _add_new_pods()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_pods))


class PlanetpodSocLimitNumber(CoordinatorEntity[PlanetpodLocalCoordinator], NumberEntity):
    """A writable SoC upper/lower limit, shared across the install but shown per-pod."""

    entity_description: PlanetpodNumberEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTR_ATTRIBUTION

    def __init__(
        self,
        coordinator: PlanetpodLocalCoordinator,
        entry: ConfigEntry,
        description: PlanetpodNumberEntityDescription,
        serial_number: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._serial = serial_number
        self._attr_unique_id = f"{entry.entry_id}_{serial_number}_{description.key}"

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._serial)},
            "name": f"Planetpod {self._serial}",
            "manufacturer": MANUFACTURER,
        }

    @property
    def native_value(self) -> float:
        return self.entity_description.value_fn(self.coordinator)

    async def async_set_native_value(self, value: float) -> None:
        new_options = {**self._entry.options, self.entity_description.option_key: value}
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.coordinator.async_options_updated()
