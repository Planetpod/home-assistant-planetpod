"""HTTP views implementing the pod-facing GET/POST /planetpod contract.

These serve the same `/planetpod` path and payload shapes the pod already
speaks to the cloud (api-spec/endpoints/planetpod/openapi.yaml), so the main
firmware-side change needed is repointing the base URL locally. Firmware also
needs to skip sending its Authorization header for local targets, and attach
the pod's serial number to the GET request (today only POST carries it, via
systemInfo.podSerialNumber) -- this view expects that as a `?serial=` query
param, an interim convention still pending confirmation with firmware.
"""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN, HTTP_VIEW_URL, PENDING_PODS_KEY, QUERY_PARAM_SERIAL
from .coordinator import PlanetpodLocalCoordinator

_LOGGER = logging.getLogger(__name__)


def _get_any_coordinator(hass: HomeAssistant) -> PlanetpodLocalCoordinator | None:
    """Return a coordinator to handle this request.

    NOTE: only single-install setups are supported for now -- with multiple
    config entries this just picks the first one. Fine for the current
    testing phase; revisit if/when multi-install-per-HA-instance is needed.
    """
    for key, value in hass.data.get(DOMAIN, {}).items():
        if key == PENDING_PODS_KEY:
            continue
        return value
    return None


class PlanetpodLocalView(HomeAssistantView):
    """Handles both GET (commands) and POST (telemetry) for /planetpod."""

    url = HTTP_VIEW_URL
    name = "api:planetpod_local"
    requires_auth = False  # Firmware sends no auth header for local targets.

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]

        try:
            payload = await request.json()
        except ValueError:
            return web.Response(status=400, text="Invalid JSON")

        if not isinstance(payload, dict):
            return web.Response(status=400, text="Invalid payload")

        serial = (payload.get("systemInfo") or {}).get("podSerialNumber")
        if not serial:
            _LOGGER.warning("POST /planetpod missing systemInfo.podSerialNumber")
            return web.Response(status=400, text="Missing systemInfo.podSerialNumber")

        # No 503-if-no-coordinator here on purpose: a pod's very first POST,
        # before any config entry exists, is exactly what the config flow's
        # "connect" step is waiting to see (buffered below).
        coordinator = _get_any_coordinator(hass)
        if coordinator is not None:
            coordinator.ingest_post(serial, payload)
        else:
            hass.data.setdefault(DOMAIN, {}).setdefault(PENDING_PODS_KEY, {})[serial] = payload
        return web.Response(status=200, text="success")

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        coordinator = _get_any_coordinator(hass)
        if coordinator is None:
            return web.Response(status=503, text="Planetpod Local not configured")

        serial = request.query.get(QUERY_PARAM_SERIAL)
        if not serial:
            return web.Response(status=400, text="Missing ?serial=<serial>")

        response = coordinator.get_response_for(serial)
        if response is None:
            return web.Response(status=404, text=f"Unknown pod serial: {serial}")

        return web.json_response(response)
