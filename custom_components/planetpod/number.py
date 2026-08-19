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
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.const import UnitOfTime

from .const import (
    ATTR_ATTRIBUTION,
    CONF_CONNECTION_TYPE,
    CONF_SOC_LOWER_LIMIT,
    CONF_SOC_UPPER_LIMIT,
    CONF_SPEED_SETPOINT_DURATION_MIN,
    CONF_SPEED_SETPOINT_KW,
    CONNECTION_TYPE_LOCAL,
    DEFAULT_SPEED_SETPOINT_DURATION_MIN,
    DEFAULT_SPEED_SETPOINT_KW,
    DOMAIN,
    MANUFACTURER,
    MAX_CHARGE_POWER_KW,
    MAX_SOC_UPPER_LIMIT_PCT,
    MAX_SPEED_SETPOINT_DURATION_MIN,
    MIN_SOC_LOWER_LIMIT_PCT,
    MIN_SPEED_SETPOINT_DURATION_MIN,
    MODE_SPEED,
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
        native_min_value=MIN_SOC_LOWER_LIMIT_PCT,
        native_max_value=MAX_SOC_UPPER_LIMIT_PCT,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda coordinator: coordinator.soc_upper_limit_pct,
    ),
    PlanetpodNumberEntityDescription(
        key="soc_lower_limit_pct",
        name="SoC Lower Limit",
        option_key=CONF_SOC_LOWER_LIMIT,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=MIN_SOC_LOWER_LIMIT_PCT,
        native_max_value=MAX_SOC_UPPER_LIMIT_PCT,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda coordinator: coordinator.soc_lower_limit_pct,
    ),
    PlanetpodNumberEntityDescription(
        key="speed_setpoint_kw",
        name="Speed Setpoint",
        option_key=CONF_SPEED_SETPOINT_KW,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=-MAX_CHARGE_POWER_KW,
        native_max_value=MAX_CHARGE_POWER_KW,
        native_step=0.1,
        mode=NumberMode.BOX,
        value_fn=lambda coordinator: coordinator.entry.options.get(
            CONF_SPEED_SETPOINT_KW, DEFAULT_SPEED_SETPOINT_KW
        ),
    ),
    PlanetpodNumberEntityDescription(
        key="speed_setpoint_duration_min",
        name="Speed Setpoint Duration",
        option_key=CONF_SPEED_SETPOINT_DURATION_MIN,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=MIN_SPEED_SETPOINT_DURATION_MIN,
        native_max_value=MAX_SPEED_SETPOINT_DURATION_MIN,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda coordinator: coordinator.speed_setpoint_duration_min,
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

    @property
    def available(self) -> bool:
        if self.entity_description.option_key in (
            CONF_SPEED_SETPOINT_KW,
            CONF_SPEED_SETPOINT_DURATION_MIN,
        ):
            return super().available and self.coordinator.mode == MODE_SPEED
        return super().available

    async def async_set_native_value(self, value: float) -> None:
        # Speed Setpoint/Duration are staged only -- editing them here does not
        # send anything to the pod. Press "Send Speed Command" to apply.
        if self.entity_description.option_key == CONF_SPEED_SETPOINT_KW:
            self.coordinator.stage_speed_setpoint(value)
            return
        if self.entity_description.option_key == CONF_SPEED_SETPOINT_DURATION_MIN:
            self.coordinator.set_speed_setpoint_duration(value)
            return
        new_options = {**self._entry.options, self.entity_description.option_key: value}
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.coordinator.async_options_updated()
