"""Push-based coordinator holding local Planetpod state.

Unlike the cloud integration's polling DataUpdateCoordinator, this one never
polls (`update_interval=None`) -- state is pushed in whenever a pod POSTs to
the local HTTP endpoint, and `async_set_updated_data` notifies entities.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_G1_HA_ENTITY_ID,
    CONF_G1_SOURCE,
    CONF_MODE,
    CONF_SOC_LOWER_LIMIT,
    CONF_SOC_UPPER_LIMIT,
    CONF_SOUND_MODE,
    DEFAULT_MODE,
    DEFAULT_SOC_LOWER_LIMIT,
    DEFAULT_SOC_UPPER_LIMIT,
    DEFAULT_SOUND_MODE,
    DOMAIN,
    G1_SOURCE_HA_SENSOR,
)
from .mode_logic import compute_get_response
from .pod_status import build_pod_status

_LOGGER = logging.getLogger(__name__)

# One-shot command flags matching the fields planetpod_get.ts sends today:
# Toggle_calibration, Reboot, TurnOffBMS, UnlockBMS/Unlock (SCU), Debug_on.
# Standby isn't a real cloud toggle field (it's a Modus value) but is
# offered here as an equivalent one-shot action pending a real design.
ONE_SHOT_COMMANDS = (
    "reboot",
    "toggle_calibration",
    "turn_off_bms",
    "unlock_scu",
    "debug_on",
    "standby",
)

# Maps our internal command name to the JSON field the cloud/firmware
# contract already uses, per planetpod_get.ts's response shape.
_COMMAND_TO_RESPONSE_FIELD = {
    "reboot": "Reboot",
    "toggle_calibration": "Toggle_calibration",
    "turn_off_bms": "TurnOffBMS",
    "unlock_scu": "Unlock",
    "debug_on": "Debug_on",
    "standby": "Standby",
}


def _build_command_flags(pending: set[str]) -> dict[str, bool]:
    return {_COMMAND_TO_RESPONSE_FIELD[command]: True for command in pending}


class PlanetpodLocalCoordinator(DataUpdateCoordinator):
    """Holds latest per-pod state for one install, pushed from HTTP POSTs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._raw_payloads: dict[str, dict[str, Any]] = {}
        self._last_message_at: dict[str, datetime] = {}
        self._last_requested_power_kw: dict[str, float] = {}
        self._pending_commands: dict[str, set[str]] = {}
        self.async_set_updated_data({"pods": []})

    def trigger_command(self, serial: str, command: str) -> None:
        """Queue a one-shot command (reboot, calibration, ...) for a pod.

        Sent on the pod's next GET, then cleared -- not a persistent state.
        """
        if command not in ONE_SHOT_COMMANDS:
            raise ValueError(f"Unknown command: {command}")
        self._pending_commands.setdefault(serial, set()).add(command)

    @property
    def mode(self) -> str:
        return self.entry.options.get(CONF_MODE, DEFAULT_MODE)

    @property
    def soc_upper_limit_pct(self) -> float:
        return self.entry.options.get(CONF_SOC_UPPER_LIMIT, DEFAULT_SOC_UPPER_LIMIT)

    @property
    def soc_lower_limit_pct(self) -> float:
        return self.entry.options.get(CONF_SOC_LOWER_LIMIT, DEFAULT_SOC_LOWER_LIMIT)

    @property
    def sound_mode(self) -> bool:
        return self.entry.options.get(CONF_SOUND_MODE, DEFAULT_SOUND_MODE)

    def async_options_updated(self) -> None:
        """Recompute pod status after an option (SoC limits, sound mode, ...) changes."""
        self._rebuild()

    def ingest_post(self, serial: str, payload: dict[str, Any]) -> None:
        """Handle a POST /planetpod payload from one pod."""
        self._raw_payloads[serial] = payload
        self._last_message_at[serial] = datetime.now(timezone.utc)
        self._rebuild()

    def _rebuild(self) -> None:
        pods = []
        for serial, payload in self._raw_payloads.items():
            status = build_pod_status(
                serial,
                payload,
                soc_upper_limit_pct=self.soc_upper_limit_pct,
                soc_lower_limit_pct=self.soc_lower_limit_pct,
                sound_mode=self.sound_mode,
                last_message_at=self._last_message_at.get(serial),
                last_requested_power_kw=self._last_requested_power_kw.get(serial),
            )
            # app_mode is a cloud-only concept (cash/solar/solarSmart/
            # solarPure) with a fixed ENUM sensor schema -- Balance/Speed is
            # a different concept, exposed separately via the Mode select
            # entity (select.py), not this field.
            g1_delivered, g1_returned = self._resolve_g1(serial)
            status["balance"] = {
                "source_label": self._g1_source_label(),
                "power_delivered_kw": g1_delivered,
                "power_returned_kw": g1_returned,
            }
            pods.append(status)
        self.async_set_updated_data({"pods": pods})

    def _g1_source_label(self) -> str:
        """Human-readable label for whichever G1 source Balance mode is using."""
        if self.entry.options.get(CONF_G1_SOURCE) == G1_SOURCE_HA_SENSOR:
            entity_id = self.entry.options.get(CONF_G1_HA_ENTITY_ID)
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is not None:
                return state.attributes.get("friendly_name", entity_id)
            return entity_id or "Home Assistant sensor (unavailable)"
        return "Pod-reported"

    def known_serials(self) -> set[str]:
        return set(self._raw_payloads.keys())

    def get_response_for(self, serial: str) -> dict[str, Any] | None:
        """Compute the GET /planetpod response for one pod, or None if unknown."""
        if serial not in self._raw_payloads:
            return None

        g1_delivered, g1_returned = self._resolve_g1(serial)

        # speed_setpoint_kw is intentionally not passed -- Speed-mode
        # scheduling (e.g. a configured schedule, or an EMHASS-derived plan)
        # isn't implemented yet, so Speed mode currently always resolves to
        # a 0 setpoint / idle status.
        response = compute_get_response(
            mode=self.mode,
            g1_power_delivered_kw=g1_delivered,
            g1_power_returned_kw=g1_returned,
        )

        set_point = response.get("setPoint", response.get("speed"))
        if set_point is not None:
            self._last_requested_power_kw[serial] = set_point
            self._rebuild()

        pending = self._pending_commands.pop(serial, None)
        if pending:
            response.update(_build_command_flags(pending))

        return response

    def _resolve_g1(self, serial: str) -> tuple[float | None, float | None]:
        """Return (delivered_kw, returned_kw), from the configured G1 source."""
        source = self.entry.options.get(CONF_G1_SOURCE)
        if source == G1_SOURCE_HA_SENSOR:
            entity_id = self.entry.options.get(CONF_G1_HA_ENTITY_ID)
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is not None:
                try:
                    value = float(state.state)
                except (TypeError, ValueError):
                    value = None
                if value is not None:
                    # HA P1 sensors are typically signed power in kW: positive
                    # = import (delivered), negative = export (returned).
                    return (max(value, 0.0), max(-value, 0.0))
            _LOGGER.debug(
                "Configured HA G1 sensor %s unavailable, falling back to pod-reported G1",
                entity_id,
            )

        raw = self._raw_payloads.get(serial, {})
        g1_data = raw.get("g1Data") or {}
        return g1_data.get("powerDelivered"), g1_data.get("powerReturned")
