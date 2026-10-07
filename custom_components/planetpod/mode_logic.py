"""Balance/Speed decision logic for GET /planetpod responses.

This mirrors the real wire contract firmware parses (`Planetpod-embedded/src/API.cpp`,
~lines 1240-1600), not a simplified shape -- confirmed by reading firmware and
the cloud backend (`orm-planetpod-v2/src/api/controllers/devices/planetpod/
planetpod_get.ts`) directly:

- Firmware only recognizes internal modes "balance"/"speed" via a nested
  `solarSmart: {subMode, setpoint_kW}` object, sent under `Modus: "solarSmart"`.
  Those strings never appear as a top-level field, and there is no top-level
  `setPoint` field anywhere in the real contract -- firmware looks up
  `solarSmart.setpoint_kW` specifically, so a flat key is silently ignored.
- `Actual_power_delivered_p1`/`Actual_power_returned_p1` are sent as STRINGS
  (`.toString()` in the cloud, `cJSON_IsString` in firmware <=1.1.5), not
  numbers, and are capitalized.
- In Balance mode `solarSmart.setpoint_kW` is the target GRID power, not a
  battery power: firmware's PI loop (`SolarMode.cpp`) drives its own P1
  reading toward it. HA sends 0 (net zero) and leaves the regulating to it.
- "standby" is an HA-side-only concept (confirmed to match how the real
  cloud's own standby feature works): firmware has no wire-level "standby"
  subMode at all -- anything other than exactly "balance" falls through to
  its "speed" branch (`API.cpp:1352`). So standby is sent as
  `subMode: "speed", setpoint_kW: 0.0` -- a persistent zero-output request,
  not the pod's own separate internal hardware Mode::STANDBY (which fires
  autonomously from lost-cloud-connection/error conditions and isn't
  remotely controllable via this endpoint at all).
"""
from __future__ import annotations

from typing import Any, Literal

Mode = Literal["balance", "speed", "standby", "planning"]


def compute_get_response(
    *,
    mode: Mode,
    g1_power_delivered_kw: float | None,
    g1_power_returned_kw: float | None,
    speed_setpoint_kw: float | None = None,
    planning_power_kw: float | None = None,
) -> dict[str, Any]:
    """Compute the GET /planetpod response body for one pod.

    Mode/SoC limits/Speed Setpoint/Planning are all independent per pod (see
    coordinator_local.py's _get_per_pod_option) -- callers invoke this once
    per pod, with that pod's own values, not a single shared result mirrored
    to every pod on the install.
    """
    if mode == "balance":
        # Grid target of net zero, not the live P1 reading: sending the
        # reading made the target flip sign every GET.
        setpoint_kw = 0.0
        wire_sub_mode = "balance"
    elif mode == "standby":
        setpoint_kw = 0.0
        wire_sub_mode = "speed"
    elif mode == "planning":
        # Same wire shape as speed -- a held kW setpoint -- just sourced from
        # the current hour's entry in the 24-hour schedule instead of one
        # manually staged value.
        setpoint_kw = planning_power_kw or 0.0
        wire_sub_mode = "speed"
    else:  # speed
        setpoint_kw = speed_setpoint_kw or 0.0
        wire_sub_mode = "speed"

    return {
        "Modus": "solarSmart",
        "solarSmart": {"subMode": wire_sub_mode, "setpoint_kW": setpoint_kw},
        "Actual_power_delivered_p1": (
            str(g1_power_delivered_kw) if g1_power_delivered_kw is not None else None
        ),
        "Actual_power_returned_p1": (
            str(g1_power_returned_kw) if g1_power_returned_kw is not None else None
        ),
    }
