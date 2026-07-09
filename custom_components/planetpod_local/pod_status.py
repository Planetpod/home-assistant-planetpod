"""Build a grid-status-shaped record for one pod from its raw POST telemetry.

This is a field-by-field port of `buildPodStatusResponse` in
orm-planetpod-v2/src/api/controllers/open/pod_status_controller.ts, sourced
from the latest local POST payload (PodDataV2 shape) instead of per-pod DB
queries, so it stays wire-compatible with the shape the existing
`custom_components.planetpod` sensors already expect.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .const import (
    DEFAULT_SOC_LOWER_LIMIT,
    DEFAULT_SOC_UPPER_LIMIT,
    MAX_CHARGE_POWER_KW,
    MAX_CHARGE_POWER_KW_SOUND_MODE,
    ONLINE_TIMEOUT_SECONDS,
)

VALID_RELAY_STATES = {"230_ON", "230_OFF"}


def _round3(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def _avg_ac_voltage(bic_data: dict[str, Any]) -> float | None:
    v0 = bic_data.get("acVoltageReadBic0")
    v1 = bic_data.get("acVoltageReadBic1")
    if v0 is None or v1 is None:
        return None
    return round((v0 + v1) / 2, 1)


def build_pod_status(
    serial: str,
    payload: dict[str, Any],
    *,
    soc_upper_limit_pct: float = DEFAULT_SOC_UPPER_LIMIT,
    soc_lower_limit_pct: float = DEFAULT_SOC_LOWER_LIMIT,
    sound_mode: bool = False,
    capacity_total_kwh: float | None = None,
    capacity_useable_kwh: float | None = None,
    last_message_at: datetime | None = None,
    last_requested_power_kw: float | None = None,
) -> dict[str, Any]:
    """Build one PodStatusResponse-shaped dict from a raw POST payload."""
    system_info = payload.get("systemInfo") or {}
    g1_data = payload.get("g1Data") or {}
    bms_data = payload.get("bmsData") or {}
    bic_data = payload.get("bicData") or {}
    pod_status = payload.get("podStatus") or {}
    power_calc = payload.get("powerCalculationInfo") or {}

    relay_state = payload.get("relaisState")
    relay_status = relay_state if relay_state in VALID_RELAY_STATES else None

    now = datetime.now(timezone.utc)
    online = (
        last_message_at is not None
        and (now - last_message_at).total_seconds() <= ONLINE_TIMEOUT_SECONDS
    )

    max_charge = MAX_CHARGE_POWER_KW_SOUND_MODE if sound_mode else MAX_CHARGE_POWER_KW

    received_by_pod_power_kw = None
    if (v := power_calc.get("requestedAcPower")) is not None:
        received_by_pod_power_kw = _round3(v / 1000)

    deployed_power_kw = None
    if (v := power_calc.get("podCalcDeployAcPowerWatt")) is not None:
        deployed_power_kw = _round3(v / 1000)

    return {
        "battery": {
            "serial_number": serial,
            "scu_firmware_version": system_info.get("firmwareVersion"),
            "hmi_firmware_version": system_info.get("hmiFirmwareVersion"),
            "capacity_useable_kwh": capacity_useable_kwh,
            "capacity_total_kwh": capacity_total_kwh,
            "soc_upper_limit_pct": soc_upper_limit_pct,
            "soc_lower_limit_pct": soc_lower_limit_pct,
            "total_cycles": (
                int(v) if (v := bms_data.get("cycleCount")) is not None else None
            ),
            "last_message_at": last_message_at.isoformat() if last_message_at else None,
            # No local equivalent of planetpod_device_events yet; left as None
            # until calibration-event tracking is implemented here.
            "last_calibration_at": None,
        },
        "power_limits": {
            "max_charge_power_kw": max_charge,
            "max_discharge_power_kw": -max_charge,
        },
        "power_control": {
            "requested_power_kw": last_requested_power_kw,
            "received_by_pod_power_kw": received_by_pod_power_kw,
            "deployed_power_kw": deployed_power_kw,
        },
        "status": {
            # App-level mode selection lives in HA config for local mode;
            # populated by the coordinator, not derivable from POST alone.
            "app_mode": None,
            "online": online,
            "pod_mode": pod_status.get("podMode"),
            "charge_status": pod_status.get("podChargingStatus"),
            "soc_pct": bms_data.get("socPct"),
        },
        "advanced": {
            "soh_pct": bms_data.get("soh"),
            "wifi_rssi_dbm": payload.get("rssiValue"),
            "avg_battery_temp_c": bms_data.get("avgTempC"),
            "relay_status": relay_status,
            "avg_ac_voltage_v": _avg_ac_voltage(bic_data),
        },
        # Not part of PodStatusResponse; kept for the Balance-mode input and
        # for actual_power_delivered_p1/returned_p1 on GET (see mode_logic.py).
        "_g1": {
            "power_delivered_kw": g1_data.get("powerDelivered"),
            "power_returned_kw": g1_data.get("powerReturned"),
        },
    }
