"""Constants for the Planetpod Local integration.

This integration is the local (no-cloud) counterpart to `custom_components.planetpod`.
It is deliberately a separate integration/domain so the existing cloud-based
integration is never touched or put at risk by this one.
"""
from __future__ import annotations

DOMAIN = "planetpod_local"
MANUFACTURER = "Planetpod"

# Matches the pod's own default SOC boundaries used today via the cloud
# (`SOC_BOUNDARY_DEFAULT` in orm-planetpod-v2). Applied silently -- not asked
# during setup, to keep the config flow short; editable afterward as entities.
DEFAULT_SOC_UPPER_LIMIT = 85
DEFAULT_SOC_LOWER_LIMIT = 20
DEFAULT_SOUND_MODE = False

# Mirrors pod_status_controller.ts: 3.0 kW normally, 1.484 kW under sound mode.
MAX_CHARGE_POWER_KW = 3.0
MAX_CHARGE_POWER_KW_SOUND_MODE = 1.484

CONF_G1_SOURCE = "g1_source"
G1_SOURCE_POD = "pod_reported"
G1_SOURCE_HA_SENSOR = "ha_sensor"
CONF_G1_HA_ENTITY_ID = "g1_ha_entity_id"

# A pod is "online" if it POSTed within this window — matches
# pod_status_controller.ts's `received_at > now() - interval '60 seconds'`.
ONLINE_TIMEOUT_SECONDS = 60

# Firmware has no pod identifier on GET today (unlike POST, which carries
# systemInfo.podSerialNumber in its body). Interim convention, pending
# confirmation with firmware: GET /planetpod?serial=<serial>.
QUERY_PARAM_SERIAL = "serial"

HTTP_VIEW_URL = "/planetpod"

# hass.data[DOMAIN][PENDING_PODS_KEY]: dict[serial, payload] for pods that
# have POSTed but aren't yet claimed by any config entry's coordinator --
# read by the config flow's connect step, adopted by async_setup_entry.
PENDING_PODS_KEY = "_pending_pods"

ATTR_ATTRIBUTION = "Data provided by your Planetpod (local)"
