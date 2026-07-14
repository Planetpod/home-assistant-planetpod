"""Balance/Speed decision logic for GET /planetpod responses.

Intended as a port of orm-planetpod-v2/src/api/controllers/devices/planetpod/
planetpod_get.ts. IMPORTANT CAVEAT: the actual zero-export setpoint formula
for Balance mode is not implemented in planetpod_get.ts itself -- it reads a
precomputed value out of `planetpod_load_planning`, which is populated by a
separate service. The formula below is a placeholder (mirror grid
import/export 1:1) until the real formula is confirmed and ported. Do not
treat this as verified control logic.
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
    response: dict[str, Any] = {"mode": mode}

    net_export_kw = None
    if g1_power_delivered_kw is not None or g1_power_returned_kw is not None:
        net_export_kw = (g1_power_returned_kw or 0) - (g1_power_delivered_kw or 0)
        response["actual_power_delivered_p1"] = g1_power_delivered_kw
        response["actual_power_returned_p1"] = g1_power_returned_kw

    if mode == "balance":
        # PLACEHOLDER FORMULA -- see module docstring.
        set_point = round(net_export_kw, 3) if net_export_kw is not None else 0.0
        response["status"] = (
            "idle" if set_point == 0 else "charge" if set_point > 0 else "discharge"
        )
        response["setPoint"] = set_point
    else:  # speed
        set_point = speed_setpoint_kw or 0.0
        response["status"] = (
            "idle" if set_point == 0 else "charge" if set_point > 0 else "discharge"
        )
        response["speed"] = set_point

    return response
