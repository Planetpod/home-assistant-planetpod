"""Constants for the Planetpod integration."""
from __future__ import annotations

DOMAIN = "planetpod"
MANUFACTURER = "Planetpod"

CONF_API_KEY = "api_key"

DEFAULT_API_URL = "https://storm.planetpod.energy"
DEFAULT_SCAN_INTERVAL = 60

ATTR_ATTRIBUTION = "Data provided by Planetpod"

CONF_CONNECTION_TYPE = "connection_type"
CONNECTION_TYPE_CLOUD = "cloud"
CONNECTION_TYPE_LOCAL = "local"

CONF_SOC_UPPER_LIMIT = "soc_upper_limit_pct"
CONF_SOC_LOWER_LIMIT = "soc_lower_limit_pct"
CONF_SOUND_MODE = "sound_mode"

DEFAULT_SOC_UPPER_LIMIT = 85
DEFAULT_SOC_LOWER_LIMIT = 20
DEFAULT_SOUND_MODE = False

MAX_CHARGE_POWER_KW = 3.0
MAX_CHARGE_POWER_KW_SOUND_MODE = 1.484

CONF_G1_SOURCE = "g1_source"
G1_SOURCE_POD = "pod_reported"
G1_SOURCE_HA_SENSOR = "ha_sensor"
CONF_G1_HA_ENTITY_ID = "g1_ha_entity_id"

CONF_MODE = "mode"
MODE_BALANCE = "balance"
MODE_SPEED = "speed"
DEFAULT_MODE = MODE_BALANCE

ONLINE_TIMEOUT_SECONDS = 60

QUERY_PARAM_SERIAL = "serial"
HTTP_VIEW_URL = "/planetpod"

PENDING_PODS_KEY = "_pending_pods"

ATTR_ATTRIBUTION_LOCAL = "Data provided by your Planetpod (local)"
