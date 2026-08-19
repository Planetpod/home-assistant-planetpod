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
MODE_STANDBY = "standby"
DEFAULT_MODE = MODE_BALANCE

CONF_SPEED_SETPOINT_KW = "speed_setpoint_kw"
DEFAULT_SPEED_SETPOINT_KW = 0.0
SPEED_SETPOINT_TIMEOUT_MINUTES = 30

CONF_SPEED_SETPOINT_DURATION_MIN = "speed_setpoint_duration_min"
DEFAULT_SPEED_SETPOINT_DURATION_MIN = 30
MIN_SPEED_SETPOINT_DURATION_MIN = 1
MAX_SPEED_SETPOINT_DURATION_MIN = 720

# Persisted so an active Speed Setpoint command survives a coordinator
# reload (HA restart, integration reinstall/update) instead of silently
# reverting to idle with time still remaining.
CONF_SPEED_SETPOINT_EXPIRES_AT = "speed_setpoint_expires_at"
CONF_SENT_SPEED_SETPOINT_KW = "sent_speed_setpoint_kw"

# Persisted so a one-shot command (Reboot/Calibration/...) queued via a
# button press isn't silently dropped if a reload happens before the pod's
# next GET picks it up.
CONF_PENDING_COMMANDS = "pending_commands"

ONLINE_TIMEOUT_SECONDS = 60

QUERY_PARAM_SERIAL = "serial"
HTTP_VIEW_URL = "/planetpod"

PENDING_PODS_KEY = "_pending_pods"

ATTR_ATTRIBUTION_LOCAL = "Data provided by your Planetpod (local)"
