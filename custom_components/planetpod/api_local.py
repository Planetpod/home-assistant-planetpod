"""HTTP views implementing the pod-facing GET/POST /planetpod contract."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN, HTTP_VIEW_URL, PENDING_PODS_KEY, QUERY_PARAM_SERIAL
from .coordinator_local import PlanetpodLocalCoordinator

_LOGGER = logging.getLogger(__name__)

_VIEW_REGISTERED_KEY = "_local_view_registered"


def ensure_local_view_registered(hass: HomeAssistant) -> None:
    """Register the /planetpod HTTP view exactly once, whenever first called.

    IMPORTANT: async_setup() only runs at boot if a config entry already
    exists (or the domain is in configuration.yaml) -- starting a config
    flow does NOT trigger it (verified against homeassistant.config_entries
    ._load_integration, which only loads config_flow.py and dependencies).
    So this must also be called from the config flow itself, not only from
    async_setup(), or the view never exists for a brand-new install.
    """
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(PENDING_PODS_KEY, {})

    if hass.data[DOMAIN].get(_VIEW_REGISTERED_KEY):
        return

    if hass.http is None:
        _LOGGER.warning("PLANETPOD: hass.http is None -- local mode connections will NOT work")
        return

    hass.http.register_view(PlanetpodLocalView())
    hass.data[DOMAIN][_VIEW_REGISTERED_KEY] = True
    _LOGGER.warning("PLANETPOD: HTTP view registered at /planetpod")


def _get_any_coordinator(hass: HomeAssistant) -> PlanetpodLocalCoordinator | None:
    for key, value in hass.data.get(DOMAIN, {}).items():
        if key == PENDING_PODS_KEY:
            continue
        if isinstance(value, PlanetpodLocalCoordinator):
            return value
    return None


class PlanetpodLocalView(HomeAssistantView):
    """Handles both GET (commands) and POST (telemetry) for /planetpod."""

    url = HTTP_VIEW_URL
    name = "api:planetpod_local"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        _LOGGER.warning("PLANETPOD: POST /planetpod received from %s", request.remote)

        try:
            payload = await request.json()
        except ValueError:
            _LOGGER.warning("PLANETPOD: POST /planetpod invalid JSON")
            return web.Response(status=400, text="Invalid JSON")

        if not isinstance(payload, dict):
            _LOGGER.warning("PLANETPOD: POST /planetpod payload is not a JSON object")
            return web.Response(status=400, text="Invalid payload")

        serial = (payload.get("systemInfo") or {}).get("podSerialNumber")
        if not serial:
            _LOGGER.warning("PLANETPOD: POST /planetpod missing systemInfo.podSerialNumber")
            return web.Response(status=400, text="Missing systemInfo.podSerialNumber")

        coordinator = _get_any_coordinator(hass)
        if coordinator is not None:
            _LOGGER.warning("PLANETPOD: POST /planetpod ingested by coordinator, serial=%s", serial)
            coordinator.ingest_post(serial, payload)
        else:
            _LOGGER.warning("PLANETPOD: POST /planetpod buffered as pending, serial=%s (no coordinator yet)", serial)
            hass.data.setdefault(DOMAIN, {}).setdefault(PENDING_PODS_KEY, {})[serial] = payload
        return web.Response(status=200, text="success")

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        _LOGGER.warning("PLANETPOD: GET /planetpod received from %s, query=%s", request.remote, dict(request.query))
        coordinator = _get_any_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("PLANETPOD: GET /planetpod -- no coordinator set up yet (503)")
            return web.Response(status=503, text="Planetpod Local not configured")

        serial = request.query.get(QUERY_PARAM_SERIAL)
        if not serial:
            known = coordinator.known_serials()
            if len(known) == 1:
                serial = next(iter(known))
                _LOGGER.debug(
                    "GET /planetpod with no ?serial= -- assuming the only known pod: %s",
                    serial,
                )
            elif len(known) > 1:
                return web.Response(
                    status=400,
                    text="Missing ?serial=<serial> and multiple pods are known -- cannot guess which one",
                )
            else:
                return web.Response(status=400, text="Missing ?serial=<serial>")

        response = coordinator.get_response_for(serial)
        if response is None:
            return web.Response(status=404, text=f"Unknown pod serial: {serial}")

        _LOGGER.warning("PLANETPOD: GET /planetpod response for serial=%s: %s", serial, response)
        return web.json_response(response)
