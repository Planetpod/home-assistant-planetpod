"""Sensor platform for Planetpod integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfElectricPotential,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import PlanetpodDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class PlanetpodSensorEntityDescription(SensorEntityDescription):
    """Describes a Planetpod sensor."""

    value_fn: Callable[[dict], Any] = lambda _: None


SENSOR_DESCRIPTIONS: tuple[PlanetpodSensorEntityDescription, ...] = (
    PlanetpodSensorEntityDescription(
        key="soc_pct",
        name="State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["status"]["soc_pct"],
    ),
    PlanetpodSensorEntityDescription(
        key="online",
        name="Online",
        translation_key="online",
        device_class=SensorDeviceClass.ENUM,
        options=["online", "offline"],
        value_fn=lambda pod: "online" if pod["status"]["online"] else "offline",
    ),
    PlanetpodSensorEntityDescription(
        key="charge_status",
        name="Charge Status",
        translation_key="charge_status",
        device_class=SensorDeviceClass.ENUM,
        options=["charge", "discharge", "idle"],
        value_fn=lambda pod: pod["status"]["charge_status"],
    ),
    PlanetpodSensorEntityDescription(
        key="app_mode",
        name="App Mode",
        translation_key="app_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["cash", "solar", "solarSmart", "solarPure"],
        value_fn=lambda pod: pod["status"]["app_mode"],
    ),
    PlanetpodSensorEntityDescription(
        key="pod_mode",
        name="Pod Mode",
        value_fn=lambda pod: pod["status"]["pod_mode"],
    ),
    PlanetpodSensorEntityDescription(
        key="deployed_power_kw",
        name="Deployed Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["power_control"]["deployed_power_kw"],
    ),
    PlanetpodSensorEntityDescription(
        key="requested_power_kw",
        name="Requested Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["power_control"]["requested_power_kw"],
    ),
    PlanetpodSensorEntityDescription(
        key="received_by_pod_power_kw",
        name="Received by Pod Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["power_control"]["received_by_pod_power_kw"],
    ),
    PlanetpodSensorEntityDescription(
        key="max_charge_power_kw",
        name="Max Charge Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["power_limits"]["max_charge_power_kw"],
    ),
    PlanetpodSensorEntityDescription(
        key="max_discharge_power_kw",
        name="Max Discharge Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["power_limits"]["max_discharge_power_kw"],
    ),
    PlanetpodSensorEntityDescription(
        key="soh_pct",
        name="State of Health",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["advanced"]["soh_pct"],
    ),
    PlanetpodSensorEntityDescription(
        key="avg_battery_temp_c",
        name="Battery Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["advanced"]["avg_battery_temp_c"],
    ),
    PlanetpodSensorEntityDescription(
        key="wifi_rssi_dbm",
        name="WiFi Signal Strength",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["advanced"]["wifi_rssi_dbm"],
    ),
    PlanetpodSensorEntityDescription(
        key="avg_ac_voltage_v",
        name="AC Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["advanced"]["avg_ac_voltage_v"],
    ),
    PlanetpodSensorEntityDescription(
        key="relay_status",
        name="Relay Status",
        translation_key="relay_status",
        device_class=SensorDeviceClass.ENUM,
        options=["on", "off"],
        value_fn=lambda pod: pod["advanced"]["relay_status"].lower(),
    ),
    PlanetpodSensorEntityDescription(
        key="total_cycles",
        name="Total Cycles",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["battery"]["total_cycles"],
    ),
    PlanetpodSensorEntityDescription(
        key="soc_upper_limit_pct",
        name="SoC Upper Limit",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["battery"]["soc_upper_limit_pct"],
    ),
    PlanetpodSensorEntityDescription(
        key="soc_lower_limit_pct",
        name="SoC Lower Limit",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod["battery"]["soc_lower_limit_pct"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform for Planetpod."""
    coordinator: PlanetpodDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_serials: set[str] = set()

    def _add_new_pods() -> None:
        """Add sensors for any pods not yet registered."""
        pods: list[dict] = coordinator.data.get("pods", []) if coordinator.data else []
        new_entities: list[PlanetpodSensor] = []
        for pod in pods:
            serial = pod.get("battery", {}).get("serial_number")
            if not serial or serial in known_serials:
                continue
            known_serials.add(serial)
            for description in SENSOR_DESCRIPTIONS:
                new_entities.append(PlanetpodSensor(coordinator, entry, description, serial))
        if new_entities:
            async_add_entities(new_entities, False)

    # Register initial pods
    _add_new_pods()

    # Keep listening for pods added to the grid after initial setup
    entry.async_on_unload(coordinator.async_add_listener(_add_new_pods))


class PlanetpodSensor(CoordinatorEntity[PlanetpodDataUpdateCoordinator], SensorEntity):
    """Representation of a Planetpod sensor."""

    entity_description: PlanetpodSensorEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTR_ATTRIBUTION

    def __init__(
        self,
        coordinator: PlanetpodDataUpdateCoordinator,
        entry: ConfigEntry,
        description: PlanetpodSensorEntityDescription,
        serial_number: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._serial = serial_number
        self._attr_unique_id = f"{entry.entry_id}_{serial_number}_{description.key}"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        pod = self._get_pod()
        battery = pod.get("battery", {}) if pod else {}
        return {
            "identifiers": {(DOMAIN, self._serial)},
            "name": f"Planetpod {self._serial}",
            "manufacturer": MANUFACTURER,
            "model": f"Capacity: {cap} kWh" if (cap := battery.get("capacity_total_kwh")) is not None else None,
            "sw_version": battery.get("scu_firmware_version"),
        }

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        pod = self._get_pod()
        if pod is None:
            return None
        try:
            return self.entity_description.value_fn(pod)
        except (KeyError, TypeError):
            return None

    @property
    def available(self) -> bool:
        """Return availability."""
        return super().available and self._get_pod() is not None

    def _get_pod(self) -> dict | None:
        """Find this sensor's pod in coordinator data."""
        if not self.coordinator.data:
            return None
        for pod in self.coordinator.data.get("pods", []):
            if pod.get("battery", {}).get("serial_number") == self._serial:
                return pod
        return None


