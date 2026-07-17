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
- IMPORTANT CAVEAT (confirmed, not just suspected): the real zero-export
  formula for Balance mode does not live in the cloud at all. The cloud only
  ever forwards a target grid-power setpoint (`solarSmart.setpoint_kW`,
  0 = net-zero by default); the actual closed-loop convergence toward that
  target runs in firmware itself (`SolarMode.cpp`, a PI controller with
  Kp=0/Ki=0.05, using the pod's own live/averaged P1 readings). Directly
  mirroring instantaneous net export 1:1 as done below is a placeholder that
  conflates "the target to send" with "the live control-loop input firmware
  computes on its own" -- it will behave far noisier than real firmware
  control and should not be treated as verified. It's also currently
  unreachable in cloud production: `sub_mode` is read but never written
  anywhere in orm-planetpod-v2, so this code path never actually fires there.
"""
from __future__ import annotations

from typing import Any, Literal

Mode = Literal["balance", "speed"]


def compute_get_response(
    *,
    mode: Mode,
    g1_power_delivered_kw: float | None,
    g1_power_returned_kw: float | None,
    speed_setpoint_kw: float | None = None,
) -> dict[str, Any]:
    """Compute the GET /planetpod response body for one pod.

    `mode` and any config (SOC boundaries, etc.) are mirrored identically to
    every pod on an install per the confirmed modus_controller.ts pattern --
    callers are expected to invoke this once per install and send the same
    result to every pod's GET, not compute a per-pod split.
    """
    net_export_kw = None
    if g1_power_delivered_kw is not None or g1_power_returned_kw is not None:
        net_export_kw = (g1_power_returned_kw or 0) - (g1_power_delivered_kw or 0)

    if mode == "balance":
        # PLACEHOLDER FORMULA -- see module docstring.
        setpoint_kw = round(net_export_kw, 3) if net_export_kw is not None else 0.0
    else:  # speed
        setpoint_kw = speed_setpoint_kw or 0.0

    return {
        "Modus": "solarSmart",
        "solarSmart": {"subMode": mode, "setpoint_kW": setpoint_kw},
        "Actual_power_delivered_p1": (
            str(g1_power_delivered_kw) if g1_power_delivered_kw is not None else None
        ),
        "Actual_power_returned_p1": (
            str(g1_power_returned_kw) if g1_power_returned_kw is not None else None
        ),
    }
