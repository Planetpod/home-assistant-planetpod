"""Energy-integration sensors backing the "Energy per hour" dashboard card.

The pod only reports instantaneous power (kW): P1 Power Delivered/Returned
and Deployed Power. The hourly bar chart needs energy (kWh) per hour, so
each of these three sensors does its own trapezoidal (Riemann) integration
of a source power sensor over time -- the same technique as HA's built-in
"Integration" helper, reimplemented here so it ships with the integration
instead of requiring the user to add helpers by hand.

Sign convention consumed by the Planning/Energy card:
- energy_grid_delivered_kwh / energy_grid_returned_kwh: always >= 0,
  state_class TOTAL_INCREASING. The card computes
  grid segment = delta(delivered) - delta(returned) per hour (positive =
  net import, negative = net export/feed-in).
- energy_battery_net_kwh: signed, state_class TOTAL (may go up or down --
  it mirrors deployed_power_kw's sign, positive while charging). The card
  computes battery segment = -delta(battery_net) per hour (positive =
  battery discharged/contributed that hour, negative = battery charged).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import ATTR_ATTRIBUTION, DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


@dataclass
class PlanetpodEnergyEntityDescription(SensorEntityDescription):
    """Describes one Riemann-integration energy sensor and its power source."""

    source_key: str = ""
    # Multiplies the source power reading before integrating -- lets one
    # source (e.g. deployed_power_kw, negative while discharging) feed a
    # sensor with the opposite sign convention without a second source.
    sign: float = 1.0
    state_class_value: SensorStateClass = SensorStateClass.TOTAL_INCREASING


ENERGY_DESCRIPTIONS: tuple[PlanetpodEnergyEntityDescription, ...] = (
    PlanetpodEnergyEntityDescription(
        key="energy_grid_delivered_kwh",
        name="Grid Energy Delivered",
        source_key="balance_g1_power_delivered_kw",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class_value=SensorStateClass.TOTAL_INCREASING,
    ),
    PlanetpodEnergyEntityDescription(
        key="energy_grid_returned_kwh",
        name="Grid Energy Returned",
        source_key="balance_g1_power_returned_kw",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class_value=SensorStateClass.TOTAL_INCREASING,
    ),
    PlanetpodEnergyEntityDescription(
        key="energy_battery_net_kwh",
        name="Battery Net Energy",
        source_key="deployed_power_kw",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class_value=SensorStateClass.TOTAL,
    ),
)


async def async_setup_energy_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[SensorEntity]], None],
    known_serials: set[str],
    pods: list[dict],
) -> None:
    """Add energy-integration sensors for any pod not yet registered."""
    new_entities: list[PlanetpodEnergyIntegrationSensor] = []
    for pod in pods:
        serial = pod.get("battery", {}).get("serial_number")
        if not serial:
            continue
        for description in ENERGY_DESCRIPTIONS:
            unique_id = f"{entry.entry_id}_{serial}_{description.key}"
            if unique_id in known_serials:
                continue
            known_serials.add(unique_id)
            new_entities.append(
                PlanetpodEnergyIntegrationSensor(hass, entry, description, serial)
            )
    if new_entities:
        async_add_entities(new_entities)


class PlanetpodEnergyIntegrationSensor(RestoreEntity, SensorEntity):
    """Trapezoidal integral of one Planetpod power sensor, in kWh."""

    entity_description: PlanetpodEnergyEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTR_ATTRIBUTION
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        description: PlanetpodEnergyEntityDescription,
        serial_number: str,
    ) -> None:
        self.hass = hass
        self.entity_description = description
        self._entry = entry
        self._serial = serial_number
        self._attr_unique_id = f"{entry.entry_id}_{serial_number}_{description.key}"
        self._attr_native_value: float = 0.0
        self._source_unique_id = f"{entry.entry_id}_{serial_number}_{description.source_key}"
        self._last_source_state: tuple[float, datetime] | None = None

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._serial)},
            "name": f"Planetpod {self._serial}",
            "manufacturer": MANUFACTURER,
        }

    @property
    def state_class(self) -> SensorStateClass:
        return self.entity_description.state_class_value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._attr_native_value = float(last_state.state)
            except (TypeError, ValueError):
                self._attr_native_value = 0.0

        registry = er.async_get(self.hass)
        source_entity_id = registry.async_get_entity_id("sensor", DOMAIN, self._source_unique_id)
        if source_entity_id is None:
            _LOGGER.debug(
                "PLANETPOD: energy sensor %s waiting for source entity to register",
                self.entity_id,
            )
            return
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [source_entity_id], self._handle_source_change
            )
        )

    @callback
    def _handle_source_change(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        old_state = event.data["old_state"]
        if new_state is None:
            return
        try:
            new_value = float(new_state.state)
        except (TypeError, ValueError):
            return

        now = new_state.last_updated
        if self._last_source_state is not None:
            prev_value, prev_time = self._last_source_state
            hours = (now - prev_time).total_seconds() / 3600
            if hours > 0:
                avg_power_kw = (prev_value + new_value) / 2 * self.entity_description.sign
                self._attr_native_value = round(
                    (self._attr_native_value or 0.0) + avg_power_kw * hours, 4
                )
        elif old_state is not None:
            try:
                prev_value = float(old_state.state)
                self._last_source_state = (prev_value, old_state.last_updated)
            except (TypeError, ValueError):
                pass

        self._last_source_state = (new_value, now)
        self.async_write_ha_state()
