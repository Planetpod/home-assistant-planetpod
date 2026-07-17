"""Button platform for Planetpod integration (local mode only).

One-shot device actions -- Reboot, Toggle Calibration, Turn Off BMS,
Unlock SCU, Unlock BMS, BMS Update, Debug -- matching the toggle fields
planetpod_get.ts already sends today. These are per-pod, not install-level,
since each command targets one specific battery.

Standby is intentionally NOT implemented here yet: verified against the real
cloud (planetpod_get.ts) and firmware (ModeManager.cpp/API.cpp) that standby
is a PERSISTENT toggle (the device-event is never stamped/cleared like the
other one-shot commands are), achieved by forcing solarSmart.setpoint_kW=0 on
every GET while active -- not a one-shot command, and not a "Modus: standby"
wire value (firmware never checks for that; the real Modus collapses to
"solarSmart" regardless). A one-shot button here would neither send the
right data nor behave the right way, so it's left out until it can be a
proper switch entity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ATTRIBUTION,
    CONF_CONNECTION_TYPE,
    CONNECTION_TYPE_LOCAL,
    DOMAIN,
    MANUFACTURER,
    MODE_SPEED,
)
from .coordinator_local import PlanetpodLocalCoordinator

SEND_SPEED_COMMAND = "send_speed_command"


@dataclass
class PlanetpodButtonEntityDescription(ButtonEntityDescription):
    """Describes a one-shot Planetpod command button."""

    command: str = ""


# entity_category=CONFIG puts these in the device page's "Configuration"
# section, separate from Mode/SoC limits in the primary "Controls" section --
# otherwise HA's device page just alphabetizes everything together, mixing
# "Calibration" in between "Mode" and the SoC sliders.
BUTTON_DESCRIPTIONS: tuple[PlanetpodButtonEntityDescription, ...] = (
    PlanetpodButtonEntityDescription(
        key="reboot", name="Reboot", command="reboot", entity_category=EntityCategory.CONFIG
    ),
    PlanetpodButtonEntityDescription(
        key="toggle_calibration",
        name="Calibration",
        command="toggle_calibration",
        entity_category=EntityCategory.CONFIG,
    ),
    PlanetpodButtonEntityDescription(
        key="turn_off_bms",
        name="Turn Off BMS",
        command="turn_off_bms",
        entity_category=EntityCategory.CONFIG,
    ),
    PlanetpodButtonEntityDescription(
        key="unlock_scu",
        name="Unlock SCU",
        command="unlock_scu",
        entity_category=EntityCategory.CONFIG,
    ),
    PlanetpodButtonEntityDescription(
        key="unlock_bms",
        name="Unlock BMS",
        command="unlock_bms",
        entity_category=EntityCategory.CONFIG,
    ),
    PlanetpodButtonEntityDescription(
        key="bms_update",
        name="BMS Update",
        command="bms_update",
        entity_category=EntityCategory.CONFIG,
    ),
    PlanetpodButtonEntityDescription(
        key="debug_on", name="Debug", command="debug_on", entity_category=EntityCategory.CONFIG
    ),
)

# No entity_category -- this stays in the primary "Controls" section next to
# the Speed Setpoint/Duration number entities it applies, not "Configuration"
# with the one-shot pod commands above.
SEND_SPEED_COMMAND_DESCRIPTION = PlanetpodButtonEntityDescription(
    key=SEND_SPEED_COMMAND, name="Send Speed Command", command=SEND_SPEED_COMMAND
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up command buttons for Planetpod (local mode only)."""
    if entry.data.get(CONF_CONNECTION_TYPE) != CONNECTION_TYPE_LOCAL:
        return

    coordinator: PlanetpodLocalCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_serials: set[str] = set()

    def _add_new_pods() -> None:
        pods: list[dict] = coordinator.data.get("pods", []) if coordinator.data else []
        new_entities: list[PlanetpodCommandButton] = []
        for pod in pods:
            serial = pod.get("battery", {}).get("serial_number")
            if not serial or serial in known_serials:
                continue
            known_serials.add(serial)
            for description in BUTTON_DESCRIPTIONS:
                new_entities.append(PlanetpodCommandButton(coordinator, entry, description, serial))
            new_entities.append(
                PlanetpodCommandButton(coordinator, entry, SEND_SPEED_COMMAND_DESCRIPTION, serial)
            )
        if new_entities:
            async_add_entities(new_entities, False)

    _add_new_pods()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_pods))


class PlanetpodCommandButton(CoordinatorEntity[PlanetpodLocalCoordinator], ButtonEntity):
    """A one-shot command button for a specific pod."""

    entity_description: PlanetpodButtonEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTR_ATTRIBUTION

    def __init__(
        self,
        coordinator: PlanetpodLocalCoordinator,
        entry: ConfigEntry,
        description: PlanetpodButtonEntityDescription,
        serial_number: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
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
    def available(self) -> bool:
        if self.entity_description.command == SEND_SPEED_COMMAND:
            return super().available and self.coordinator.mode == MODE_SPEED
        return super().available

    async def async_press(self) -> None:
        if self.entity_description.command == SEND_SPEED_COMMAND:
            self.coordinator.send_speed_command()
            return
        self.coordinator.trigger_command(self._serial, self.entity_description.command)
