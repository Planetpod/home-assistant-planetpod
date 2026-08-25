"""Sensor platform for Planetpod integration."""
from __future__ import annotations

import json
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
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfElectricPotential,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import PlanetpodDataUpdateCoordinator
from .coordinator_local import PlanetpodLocalCoordinator
from .energy import async_setup_energy_entities


_ERROR_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",       # real firmware format, e.g. "2026-08-19 08:06:27"
    "%Y-%m-%dT%H:%M:%S.%fZ",   # ISO, in case a future firmware version sends this
    "%Y-%m-%dT%H:%M:%SZ",
)


def _parse_error_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    for fmt in _ERROR_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _sort_errors_newest_first(logs: list[dict]) -> list[dict]:
    """Sort error log entries by timestamp, newest first.

    Firmware's getErrors() (ErrorLogger.cpp) returns a
    std::unordered_map<std::string, ErrorLog> -- C++ gives NO ordering
    guarantee for unordered_map iteration, so the JSON array's order is
    effectively arbitrary (hash-bucket order), not chronological or
    insertion order -- confirmed with a real payload where an older E405
    entry was last and a newer E402 was first. Entries with an unparsable
    timestamp sort last rather than raising.
    """
    return sorted(
        logs,
        key=lambda entry: _parse_error_timestamp(entry.get("timestamp")) or datetime.min,
        reverse=True,
    )


def _format_error_entry(entry: dict) -> str:
    """Format one error log entry as "[group] code (type): description".

    Firmware's ErrorInfoList isn't consistent -- most entries have a real
    human-readable `description`, but some (e.g. E405/lost cloud connection)
    ship with an empty one, carrying their only human text in `errorType`
    instead, and `errorGroup` is often empty too. `[group]` is always shown
    (as "[ ]" when empty) so every entry's shape stays visually consistent;
    code/type/description are each included only when firmware populated
    them.
    """
    group = entry.get("errorGroup") or ""
    code = entry.get("errorCode") or ""
    error_type = entry.get("errorType") or ""
    description = entry.get("description") or ""

    text = f"[{group or ' '}]"
    if code and error_type:
        text += f" {code} ({error_type})"
    else:
        label = code or error_type
        if label:
            text += f" {label}"
    if description:
        text += f": {description}"
    return text


def _pretty_json(value: Any) -> str | None:
    """Render a payload as indented JSON so it's actually readable as an
    entity attribute -- HA's Developer Tools/more-info dialog show a raw
    dict's repr() as one hard-to-read line, especially once it's nested a
    few levels deep (systemInfo/bmsData/etc.). default=str covers datetime
    objects (e.g. received_at/sent_at), which json.dumps can't serialize
    directly.
    """
    if not value:
        return None
    return json.dumps(value, indent=2, default=str)


def _format_last_error(pod: dict) -> str:
    """Format every error in the latest POST, newest first.

    One POST can legitimately carry more than one error at a time (e.g. a
    just-resolved reboot notice alongside a currently-active connectivity
    error) -- show all of them rather than collapsing to a single "most
    important" one.
    """
    logs = pod.get("error_logs")
    if not logs:
        return "None"
    formatted = [f for entry in _sort_errors_newest_first(logs) if (f := _format_error_entry(entry))]
    return "; ".join(formatted) if formatted else "None"

AnyPlanetpodCoordinator = PlanetpodDataUpdateCoordinator | PlanetpodLocalCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class PlanetpodSensorEntityDescription(SensorEntityDescription):
    """Describes a Planetpod sensor."""

    value_fn: Callable[[dict], Any] = lambda _: None
    attr_fn: Callable[[dict], dict[str, Any]] = lambda _: {}


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
        name="Requested Power Received by Pod",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: round(v, 3) if (v := pod["power_control"]["received_by_pod_power_kw"]) is not None else None,
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
        options=["230_ON", "230_OFF"],
        value_fn=lambda pod: pod["advanced"]["relay_status"],
    ),
    PlanetpodSensorEntityDescription(
        key="total_cycles",
        name="Total Cycles",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: int(v) if (v := pod["battery"]["total_cycles"]) is not None else None,
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
    # Local-mode only: pod.get("balance") doesn't exist for cloud entries,
    # so these stay "unknown" there rather than raising. Named with a "P1"
    # prefix so they sort together, separate from the battery sensors above,
    # on the device page.
    PlanetpodSensorEntityDescription(
        key="balance_source",
        name="P1 Balance Source",
        value_fn=lambda pod: pod.get("balance", {}).get("error")
        or pod.get("balance", {}).get("source_label"),
    ),
    PlanetpodSensorEntityDescription(
        key="balance_g1_power_delivered_kw",
        name="P1 Power Delivered",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod.get("balance", {}).get("power_delivered_kw"),
    ),
    PlanetpodSensorEntityDescription(
        key="balance_g1_power_returned_kw",
        name="P1 Power Returned",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda pod: pod.get("balance", {}).get("power_returned_kw"),
    ),
    PlanetpodSensorEntityDescription(
        key="speed_setpoint_status",
        name="Speed Setpoint Status",
        value_fn=lambda pod: pod.get("speed_setpoint_status"),
    ),
    # Diagnostic aid: lets you confirm what the pod is actually sending and
    # when, from Developer Tools > States, without digging through HA logs.
    # raw_payload is pretty-printed JSON (not the raw dict) so it's actually
    # readable in the more-info dialog/Developer Tools attribute view rather
    # than a single hard-to-read repr() line.
    PlanetpodSensorEntityDescription(
        key="last_post_received",
        name="Last POST Received",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda pod: pod.get("raw_post", {}).get("received_at"),
        attr_fn=lambda pod: {"raw_payload": _pretty_json(pod.get("raw_post", {}).get("payload"))},
    ),
    # Mirrors "Last POST Received" for the other direction -- what HA most
    # recently sent back to the pod in a GET response, and when.
    PlanetpodSensorEntityDescription(
        key="last_get_sent",
        name="Last GET Sent",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda pod: pod.get("raw_get", {}).get("sent_at"),
        attr_fn=lambda pod: {"raw_response": _pretty_json(pod.get("raw_get", {}).get("response"))},
    ),
    # Local-mode only: surfaces the SCU/BMS errorLogs field from the raw
    # POST, which the cloud REST API never exposes. The state itself lists
    # every error in the latest POST, newest first (see _format_last_error),
    # with the full raw list as an attribute.
    PlanetpodSensorEntityDescription(
        key="last_error",
        name="Last Error",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_format_last_error,
        attr_fn=lambda pod: {"error_logs": pod.get("error_logs", [])},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform for Planetpod."""
    coordinator: AnyPlanetpodCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_serials: set[str] = set()
    known_energy_ids: set[str] = set()

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

        # Backs the Energy dashboard card -- integrates P1/deployed power
        # into kWh. Registered after the pod's power sensors above so their
        # unique_ids already exist in the entity registry for lookup.
        hass.async_create_task(
            async_setup_energy_entities(
                hass, entry, lambda ents: async_add_entities(ents, False), known_energy_ids, pods
            )
        )

    # Register initial pods
    _add_new_pods()

    # Keep listening for pods added to the grid after initial setup
    entry.async_on_unload(coordinator.async_add_listener(_add_new_pods))


class PlanetpodSensor(CoordinatorEntity[AnyPlanetpodCoordinator], SensorEntity):
    """Representation of a Planetpod sensor."""

    entity_description: PlanetpodSensorEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTR_ATTRIBUTION

    def __init__(
        self,
        coordinator: AnyPlanetpodCoordinator,
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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-sensor extra attributes, if this description defines any."""
        pod = self._get_pod()
        if pod is None:
            return {}
        try:
            return self.entity_description.attr_fn(pod)
        except (KeyError, TypeError):
            return {}

    def _get_pod(self) -> dict | None:
        """Find this sensor's pod in coordinator data."""
        if not self.coordinator.data:
            return None
        for pod in self.coordinator.data.get("pods", []):
            if pod.get("battery", {}).get("serial_number") == self._serial:
                return pod
        return None


