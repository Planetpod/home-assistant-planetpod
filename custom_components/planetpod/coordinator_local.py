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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_G1_HA_ENTITY_ID,
    CONF_G1_SOURCE,
    CONF_MODE,
    CONF_PENDING_COMMANDS,
    CONF_SENT_SPEED_SETPOINT_KW,
    CONF_SOC_LOWER_LIMIT,
    CONF_SOC_UPPER_LIMIT,
    CONF_SOUND_MODE,
    CONF_SPEED_SETPOINT_DURATION_MIN,
    CONF_SPEED_SETPOINT_EXPIRES_AT,
    CONF_SPEED_SETPOINT_KW,
    DEFAULT_MODE,
    DEFAULT_PLANNING_POWER_KW,
    DEFAULT_SOC_LOWER_LIMIT,
    DEFAULT_SOC_UPPER_LIMIT,
    DEFAULT_SOUND_MODE,
    DEFAULT_SPEED_SETPOINT_DURATION_MIN,
    DEFAULT_SPEED_SETPOINT_KW,
    DOMAIN,
    G1_SOURCE_HA_SENSOR,
    MODE_BALANCE,
    ONLINE_RECHECK_INTERVAL_SECONDS,
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
# Standby is NOT here -- verified it's a persistent toggle (never
# stamped/cleared like these are) achieved via solarSmart.setpoint_kW=0, not
# a one-shot command or a "Modus: standby" wire value. Left out until it can
# be a proper switch entity (see button.py's module docstring).
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

ONE_SHOT_COMMANDS = (
    *_ALWAYS_PRESENT_COMMANDS,
    *_CONDITIONAL_COMMANDS,
)


def _build_command_flags(pending: set[str]) -> dict[str, bool]:
    flags = {field: command in pending for command, field in _ALWAYS_PRESENT_COMMANDS.items()}
    flags.update(
        {field: True for command, field in _CONDITIONAL_COMMANDS.items() if command in pending}
    )
    return flags


# Confirmed in firmware (API.cpp): these three bmsData fields are only
# included in a POST when their value has changed since the pod's last send
# (delta-throttled), unlike every other field. A naive full-overwrite of the
# raw payload per POST would make State of Health/Total Cycles sensors
# flicker to unknown on any POST where they legitimately didn't change.
_DELTA_THROTTLED_BMS_FIELDS = ("soh", "cycleCount", "cycleBufferMah")


class PlanetpodLocalCoordinator(DataUpdateCoordinator):
    """Holds latest per-pod state for one install, pushed from HTTP POSTs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._raw_payloads: dict[str, dict[str, Any]] = {}
        self._last_known_bms_fields: dict[str, dict[str, Any]] = {}
        self._last_message_at: dict[str, datetime] = {}
        self._last_requested_power_kw: dict[str, float] = {}
        self._last_get_response: dict[str, dict[str, Any]] = {}

        # Restored from entry.options (see _persist_pending_commands) so a
        # button press queued right before a reload -- HA restart,
        # integration update/reinstall -- isn't silently dropped before the
        # pod's next GET picks it up.
        self._pending_commands: dict[str, set[str]] = {
            serial: set(commands)
            for serial, commands in entry.options.get(CONF_PENDING_COMMANDS, {}).items()
        }

        # Restored from entry.options (see send_speed_command), per pod, so
        # an active Speed Setpoint command survives a reload instead of
        # silently reverting to idle with time still remaining.
        raw_expires_at = entry.options.get(CONF_SPEED_SETPOINT_EXPIRES_AT)
        self._speed_setpoint_expires_at: dict[str, datetime] = (
            {serial: datetime.fromisoformat(v) for serial, v in raw_expires_at.items()}
            if isinstance(raw_expires_at, dict)
            else {}
        )
        # Snapshot of each pod's staged CONF_SPEED_SETPOINT_KW taken at the
        # moment send_speed_command() last ran for it --
        # effective_speed_setpoint_kw must read this, NOT the live staged
        # option, otherwise staging a new value while a previous command is
        # still active leaks through immediately without
        # send_speed_command() ever being called again. Also restored from
        # entry.options for the same reload-survival reason.
        raw_sent = entry.options.get(CONF_SENT_SPEED_SETPOINT_KW)
        self._sent_speed_setpoint_kw: dict[str, float] = dict(raw_sent) if isinstance(raw_sent, dict) else {}
        self.async_set_updated_data({"pods": []})

        # _rebuild() (which recomputes status.online against
        # ONLINE_TIMEOUT_SECONDS) otherwise only runs reactively, from
        # ingest_post/get_response_for/an option change -- exactly the kind
        # of traffic that stops once a pod actually goes offline. Without
        # this, online/available would freeze at whatever they were at the
        # last real message instead of ever flipping once the pod goes
        # quiet.
        entry.async_on_unload(
            async_track_time_interval(
                hass,
                self._handle_online_recheck,
                timedelta(seconds=ONLINE_RECHECK_INTERVAL_SECONDS),
            )
        )

    @callback
    def _handle_online_recheck(self, _now: datetime) -> None:
        # Without @callback, HA schedules this onto an executor thread
        # instead of the event loop -- and _rebuild()'s
        # async_set_updated_data() must run on the event loop.
        if self._raw_payloads:
            self._rebuild()

    def _persist_pending_commands(self) -> None:
        new_options = {
            **self.entry.options,
            CONF_PENDING_COMMANDS: {
                serial: sorted(commands) for serial, commands in self._pending_commands.items()
            },
        }
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)

    def trigger_command(self, serial: str, command: str) -> None:
        """Queue a one-shot command (reboot, calibration, ...) for a pod.

        Sent on the pod's next GET, then cleared -- persisted in the
        meantime so a reload before that GET doesn't drop it.
        """
        if command not in ONE_SHOT_COMMANDS:
            raise ValueError(f"Unknown command: {command}")
        self._pending_commands.setdefault(serial, set()).add(command)
        self._persist_pending_commands()

    def _get_per_pod_option(self, key: str, serial: str, default: Any) -> Any:
        """Read one pod's value out of a per-pod option dict.

        Mode/SoC limits/Planning/Speed Setpoint are all stored this way:
        {key: {serial: value}} in entry.options, so each pod's HA entities
        are genuinely independent instead of every pod's card silently
        reading/writing the exact same install-wide value (the bug this
        replaced -- confirmed live where sending a Speed command from one
        pod's card overwrote another pod's still-active command).

        A pre-upgrade install stored this as one flat value shared by every
        pod (no dict at all) -- fall back to THAT, not the hardcoded
        default, so upgrading doesn't silently reset an already-configured
        Mode/SoC limit/setpoint back to factory defaults on a live pod.
        """
        per_pod = self.entry.options.get(key)
        if isinstance(per_pod, dict):
            return per_pod.get(serial, default)
        if per_pod is not None:
            return per_pod
        return default

    def _set_per_pod_option(self, key: str, serial: str, value: Any) -> None:
        existing = self.entry.options.get(key)
        if isinstance(existing, dict):
            per_pod = dict(existing)
        elif existing is not None:
            # Legacy flat value (see _get_per_pod_option) -- seed every
            # OTHER currently-known pod with it before this pod's value
            # diverges, so they don't silently jump to the hardcoded
            # default the instant this option becomes a per-pod dict.
            per_pod = {other: existing for other in self.known_serials()}
        else:
            per_pod = {}
        per_pod[serial] = value
        new_options = {**self.entry.options, key: per_pod}
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)

    def async_options_updated(self) -> None:
        """Recompute pod status after entry.options was mutated directly
        (bypassing one of the setter methods above)."""
        self._rebuild()

    def mode(self, serial: str) -> str:
        return self._get_per_pod_option(CONF_MODE, serial, DEFAULT_MODE)

    def set_mode(self, serial: str, mode: str) -> None:
        self._set_per_pod_option(CONF_MODE, serial, mode)
        self._rebuild()

    def soc_upper_limit_pct(self, serial: str) -> float:
        return self._get_per_pod_option(CONF_SOC_UPPER_LIMIT, serial, DEFAULT_SOC_UPPER_LIMIT)

    def set_soc_upper_limit(self, serial: str, value: float) -> None:
        self._set_per_pod_option(CONF_SOC_UPPER_LIMIT, serial, value)
        self._rebuild()

    def soc_lower_limit_pct(self, serial: str) -> float:
        return self._get_per_pod_option(CONF_SOC_LOWER_LIMIT, serial, DEFAULT_SOC_LOWER_LIMIT)

    def set_soc_lower_limit(self, serial: str, value: float) -> None:
        self._set_per_pod_option(CONF_SOC_LOWER_LIMIT, serial, value)
        self._rebuild()

    @property
    def sound_mode(self) -> bool:
        # Not yet exposed as an HA entity (no switch/select writes to it) --
        # stays install-wide until it is.
        return self.entry.options.get(CONF_SOUND_MODE, DEFAULT_SOUND_MODE)

    def planning_hour_kw(self, serial: str, hour: int) -> float:
        return self._get_per_pod_option(f"planning_hour_{hour:02d}", serial, DEFAULT_PLANNING_POWER_KW)

    def set_planning_hour_kw(self, serial: str, hour: int, value: float) -> None:
        self._set_per_pod_option(f"planning_hour_{hour:02d}", serial, value)
        self._rebuild()

    def effective_planning_power_kw(self, serial: str) -> float:
        """The Planning schedule's setpoint for the current wall-clock hour.

        Uses HA's configured local timezone, not UTC -- the Planning
        dashboard card labels hours (00:00..23:00) as local wall-clock time,
        so the schedule must be read back against the same clock.
        """
        hour = dt_util.now().hour
        return self.planning_hour_kw(serial, hour)

    def speed_setpoint_duration_min(self, serial: str) -> float:
        return self._get_per_pod_option(
            CONF_SPEED_SETPOINT_DURATION_MIN, serial, DEFAULT_SPEED_SETPOINT_DURATION_MIN
        )

    def set_speed_setpoint_duration(self, serial: str, value: float) -> None:
        """Update how long a Speed Setpoint stays active once sent -- takes
        effect the next time send_speed_command() is called, not retroactively."""
        self._set_per_pod_option(CONF_SPEED_SETPOINT_DURATION_MIN, serial, value)
        self._rebuild()

    def staged_speed_setpoint_kw(self, serial: str) -> float:
        return self._get_per_pod_option(CONF_SPEED_SETPOINT_KW, serial, DEFAULT_SPEED_SETPOINT_KW)

    def stage_speed_setpoint(self, serial: str, value: float) -> None:
        """Stage a Speed Setpoint value without sending it -- takes effect
        only once send_speed_command() is called (the "Send Speed Command"
        button), so Setpoint and Duration can both be set before applying."""
        self._set_per_pod_option(CONF_SPEED_SETPOINT_KW, serial, value)
        self._rebuild()

    def set_speed_setpoint(self, serial: str, value: float) -> None:
        """Stage a Speed Setpoint value and immediately send it -- convenience
        for programmatic callers (e.g. tests, or an EMHASS bridge automation
        that wants one atomic call) that don't need the stage/send split."""
        self.stage_speed_setpoint(serial, value)
        self.send_speed_command(serial)

    def send_speed_command(self, serial: str) -> None:
        """Apply the currently staged Speed Setpoint for this pod, active
        for its speed_setpoint_duration_min from now.

        Snapshots the staged value into _sent_speed_setpoint_kw[serial] so a
        later stage_speed_setpoint() call (without a matching send) can
        never change what's actually being applied -- and fully overwrites
        any still-active previous command for THIS pod only, no queueing
        and no effect on any other pod's own command. Both the snapshot and
        the expiry are persisted into entry.options so an active command
        survives a coordinator reload (HA restart, integration
        update/reinstall) instead of silently reverting to idle."""
        value = self.staged_speed_setpoint_kw(serial)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.speed_setpoint_duration_min(serial)
        )
        self._sent_speed_setpoint_kw[serial] = value
        self._speed_setpoint_expires_at[serial] = expires_at

        self._set_per_pod_option(CONF_SENT_SPEED_SETPOINT_KW, serial, value)
        self._set_per_pod_option(CONF_SPEED_SETPOINT_EXPIRES_AT, serial, expires_at.isoformat())
        self._rebuild()

    def effective_speed_setpoint_kw(self, serial: str) -> float:
        """The Speed Setpoint to actually apply for this pod, or 0.0 if its
        duration has elapsed."""
        if not self.speed_setpoint_active(serial):
            return DEFAULT_SPEED_SETPOINT_KW
        return self._sent_speed_setpoint_kw.get(serial, DEFAULT_SPEED_SETPOINT_KW)

    def speed_setpoint_active(self, serial: str) -> bool:
        """Whether this pod's current Speed Setpoint is still within its
        configured duration."""
        expires_at = self._speed_setpoint_expires_at.get(serial)
        if expires_at is None:
            return False
        return datetime.now(timezone.utc) < expires_at

    def ingest_post(self, serial: str, payload: dict[str, Any]) -> None:
        """Handle a POST /planetpod payload from one pod."""
        bms_data = payload.get("bmsData") or {}
        known = self._last_known_bms_fields.setdefault(serial, {})
        for field in _DELTA_THROTTLED_BMS_FIELDS:
            value = bms_data.get(field)
            if value is not None:
                known[field] = value

        self._raw_payloads[serial] = payload
        self._last_message_at[serial] = datetime.now(timezone.utc)
        self._rebuild()

    def _with_last_known_bms_fields(self, serial: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Backfill delta-throttled bmsData fields with their last known value.

        Only for feeding build_pod_status -- the raw_post/"Last POST
        Received" attribute must stay genuinely raw for debugging accuracy.
        """
        known = self._last_known_bms_fields.get(serial)
        if not known:
            return payload
        bms_data = payload.get("bmsData") or {}
        merged_bms = dict(bms_data)
        changed = False
        for field, value in known.items():
            if merged_bms.get(field) is None:
                merged_bms[field] = value
                changed = True
        if not changed:
            return payload
        return {**payload, "bmsData": merged_bms}

    def _rebuild(self) -> None:
        pods = []
        for serial, payload in self._raw_payloads.items():
            status = build_pod_status(
                serial,
                self._with_last_known_bms_fields(serial, payload),
                soc_upper_limit_pct=self.soc_upper_limit_pct(serial),
                soc_lower_limit_pct=self.soc_lower_limit_pct(serial),
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
            status["raw_get"] = self._last_get_response.get(serial, {})
            g1_delivered, g1_returned = self._resolve_g1(serial)
            no_p1 = g1_delivered is None and g1_returned is None
            status["balance"] = {
                "source_label": self._g1_source_label(),
                "power_delivered_kw": g1_delivered,
                "power_returned_kw": g1_returned,
                "error": (
                    "Can't balance: no P1 sensor"
                    if (no_p1 and self.mode(serial) == MODE_BALANCE)
                    else None
                ),
            }
            status["speed_setpoint_status"] = (
                "Active" if self.speed_setpoint_active(serial) else "Expired (reverted to idle)"
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

        popped = self._pending_commands.pop(serial, None)
        pending = popped or set()
        if popped:
            self._persist_pending_commands()

        g1_delivered, g1_returned = self._resolve_g1(serial)

        response = compute_get_response(
            mode=self.mode(serial),
            g1_power_delivered_kw=g1_delivered,
            g1_power_returned_kw=g1_returned,
            speed_setpoint_kw=self.effective_speed_setpoint_kw(serial),
            planning_power_kw=self.effective_planning_power_kw(serial),
        )

        set_point = response["solarSmart"]["setpoint_kW"]
        self._last_requested_power_kw[serial] = set_point
        self._rebuild()

        # Confirmed control-affecting on firmware (API.cpp), not informational:
        # Min_SOC/Max_SOC are persisted into firmware's own SOC-limit storage
        # (cloudSOCLimits.setValue, "persistent, no expiry"), and sameGroup is
        # persisted to NVS and used by the local UDP mesh grouping logic.
        # Omitting these means the SoC Upper/Lower Limit entities silently
        # have no effect on the real pod at all.
        response["Min_SOC"] = self.soc_lower_limit_pct(serial)
        response["Max_SOC"] = self.soc_upper_limit_pct(serial)
        # Mode/SoC/Speed/Planning are now genuinely independent per pod (see
        # _get_per_pod_option), so pods must NOT be grouped for firmware's
        # own local UDP mesh load-sharing anymore -- sameGroup=True would
        # let firmware silently coordinate/rebalance power between pods
        # behind HA's back, undermining the independence just implemented.
        response["sameGroup"] = False

        response.update(_build_command_flags(pending))

        self._last_get_response[serial] = {
            "response": response,
            "sent_at": datetime.now(timezone.utc),
        }
        self._rebuild()

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
