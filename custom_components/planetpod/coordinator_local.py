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


class PlanetpodLocalCoordinator(DataUpdateCoordinator):
    """Holds latest per-pod state for one install, pushed from HTTP POSTs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._raw_payloads: dict[str, dict[str, Any]] = {}
        self._last_message_at: dict[str, datetime] = {}
        self._last_requested_power_kw: dict[str, float] = {}
        self.async_set_updated_data({"pods": []})

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
            status["status"]["app_mode"] = self.mode
            pods.append(status)
        self.async_set_updated_data({"pods": pods})

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
