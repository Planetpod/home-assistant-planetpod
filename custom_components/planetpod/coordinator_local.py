"""Push-based coordinator holding local Planetpod state.

Unlike the cloud integration's polling DataUpdateCoordinator, this one never
polls (`update_interval=None`) -- state is pushed in whenever a pod POSTs to
the local HTTP endpoint, and `async_set_updated_data` notifies entities.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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
    CONF_SPEED_SETPOINT_DURATION_MIN,
    CONF_SPEED_SETPOINT_KW,
    DEFAULT_MODE,
    DEFAULT_SOC_LOWER_LIMIT,
    DEFAULT_SOC_UPPER_LIMIT,
    DEFAULT_SOUND_MODE,
    DEFAULT_SPEED_SETPOINT_DURATION_MIN,
    DEFAULT_SPEED_SETPOINT_KW,
    DOMAIN,
    G1_SOURCE_HA_SENSOR,
    MODE_BALANCE,
)
from .mode_logic import compute_get_response
from .pod_status import build_pod_status

_LOGGER = logging.getLogger(__name__)

# One-shot command flags, matching planetpod_get.ts's real response shape
# (verified against orm-planetpod-v2 and Planetpod-embedded/src/API.cpp):
# - Reboot/Toggle_calibration/TurnOffBMS/UnlockBMS are ALWAYS present,
#   default false (device_events of these types are read every GET).
# - Unlock/Debug_on/bmsUpdate are OMITTED entirely unless true -- the cloud
#   never sends them as false.
# "standby" has no such field at all -- real cloud forces Modus="standby"
# instead (see STANDBY_MODUS_OVERRIDE below), it isn't a boolean toggle.
_ALWAYS_PRESENT_COMMANDS = {
    "reboot": "Reboot",
    "toggle_calibration": "Toggle_calibration",
    "turn_off_bms": "TurnOffBMS",
    "unlock_bms": "UnlockBMS",
}
_CONDITIONAL_COMMANDS = {
    "unlock_scu": "Unlock",
    "debug_on": "Debug_on",
    "bms_update": "bmsUpdate",
}
STANDBY_COMMAND = "standby"

ONE_SHOT_COMMANDS = (
    *_ALWAYS_PRESENT_COMMANDS,
    *_CONDITIONAL_COMMANDS,
    STANDBY_COMMAND,
)


def _build_command_flags(pending: set[str]) -> dict[str, bool]:
    flags = {field: command in pending for command, field in _ALWAYS_PRESENT_COMMANDS.items()}
    flags.update(
        {field: True for command, field in _CONDITIONAL_COMMANDS.items() if command in pending}
    )
    return flags


class PlanetpodLocalCoordinator(DataUpdateCoordinator):
    """Holds latest per-pod state for one install, pushed from HTTP POSTs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._raw_payloads: dict[str, dict[str, Any]] = {}
        self._last_message_at: dict[str, datetime] = {}
        self._last_requested_power_kw: dict[str, float] = {}
        self._pending_commands: dict[str, set[str]] = {}
        self._speed_setpoint_expires_at: datetime | None = None
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

    @property
    def speed_setpoint_duration_min(self) -> float:
        return self.entry.options.get(
            CONF_SPEED_SETPOINT_DURATION_MIN, DEFAULT_SPEED_SETPOINT_DURATION_MIN
        )

    def stage_speed_setpoint(self, value: float) -> None:
        """Stage a Speed Setpoint value without sending it -- takes effect
        only once send_speed_command() is called (the "Send Speed Command"
        button), so Setpoint and Duration can both be set before applying."""
        new_options = {**self.entry.options, CONF_SPEED_SETPOINT_KW: value}
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        self._rebuild()

    def set_speed_setpoint_duration(self, value: float) -> None:
        """Update how long a Speed Setpoint stays active once sent -- takes
        effect the next time send_speed_command() is called, not retroactively."""
        new_options = {**self.entry.options, CONF_SPEED_SETPOINT_DURATION_MIN: value}
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        self._rebuild()

    def set_speed_setpoint(self, value: float) -> None:
        """Stage a Speed Setpoint value and immediately send it -- convenience
        for programmatic callers (e.g. tests, or an EMHASS bridge automation
        that wants one atomic call) that don't need the stage/send split."""
        self.stage_speed_setpoint(value)
        self.send_speed_command()

    def send_speed_command(self) -> None:
        """Apply the currently staged Speed Setpoint, active for
        speed_setpoint_duration_min from now."""
        self._speed_setpoint_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.speed_setpoint_duration_min
        )
        self._rebuild()

    @property
    def effective_speed_setpoint_kw(self) -> float:
        """The Speed Setpoint to actually apply, or 0.0 if its duration has elapsed."""
        if not self.speed_setpoint_active:
            return DEFAULT_SPEED_SETPOINT_KW
        return self.entry.options.get(CONF_SPEED_SETPOINT_KW, DEFAULT_SPEED_SETPOINT_KW)

    @property
    def speed_setpoint_active(self) -> bool:
        """Whether the current Speed Setpoint is still within its configured duration."""
        if self._speed_setpoint_expires_at is None:
            return False
        return datetime.now(timezone.utc) < self._speed_setpoint_expires_at

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
            status["raw_post"] = {
                "payload": payload,
                "received_at": self._last_message_at.get(serial),
            }
            g1_delivered, g1_returned = self._resolve_g1(serial)
            no_p1 = g1_delivered is None and g1_returned is None
            status["balance"] = {
                "source_label": self._g1_source_label(),
                "power_delivered_kw": g1_delivered,
                "power_returned_kw": g1_returned,
                "error": "Can't balance: no P1 sensor" if (no_p1 and self.mode == MODE_BALANCE) else None,
            }
            status["speed_setpoint_status"] = (
                "Active" if self.speed_setpoint_active else "Expired (reverted to idle)"
            )
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

        pending = self._pending_commands.pop(serial, None) or set()

        if STANDBY_COMMAND in pending:
            # Real cloud behavior: standby overrides Modus entirely for this
            # GET rather than being a boolean toggle field (there is no
            # "Standby" field firmware parses) -- see planetpod_get.ts.
            return {"Modus": "standby", **_build_command_flags(pending - {STANDBY_COMMAND})}

        g1_delivered, g1_returned = self._resolve_g1(serial)

        response = compute_get_response(
            mode=self.mode,
            g1_power_delivered_kw=g1_delivered,
            g1_power_returned_kw=g1_returned,
            speed_setpoint_kw=self.effective_speed_setpoint_kw,
        )

        set_point = response["solarSmart"]["setpoint_kW"]
        self._last_requested_power_kw[serial] = set_point
        self._rebuild()

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
