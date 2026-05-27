# Home Assistant Planetpod Integration

Monitor your Planetpod solar battery from Home Assistant. The integration polls the Planetpod cloud API every 60 seconds — sensor data is routed through Planetpod's servers, not read directly from the hardware on your local network.

## Requirements

- Home Assistant 2024.4.0 or later
- A Planetpod account with an active battery
- A Planetpod Open API token (generated in the app)

## Generating an API token

1. Open the Planetpod app
2. Go to **Instellingen → Planetpod beheer**
3. Scroll down to the **Open API** section
4. Tap **Token aanmaken**
5. Tap the copy button next to the token — it is only shown once
6. The token starts with `pp_` and is valid for 1 year

> Generating a new token revokes the previous one. If you rotate the token, Home Assistant will show a re-authentication banner — enter the new token there.

## Installation

### Via HACS (Recommended)

**Step 1 — Add the custom repository**

1. Open HACS in Home Assistant
2. Click the three-dot menu (⋮) in the top right and select **Custom repositories**
3. Paste `https://github.com/Planetpod/home-assistant-planetpod` and set category to **Integration**
4. Click **Add**

**Step 2 — Download the integration**

1. In HACS, search for **Planetpod**
2. Click **Download** and confirm
3. Restart Home Assistant


## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Planetpod**
3. Paste your `pp_` token and confirm

## Sensors

One device is created per battery (identified by serial number). The following sensors are available:

| Sensor | Unit | Description | Possible values |
|---|---|---|---|
| State of Charge | % | Current battery charge level as a percentage of total capacity. | 0 – 100 |
| State of Health | % | Battery degradation indicator — 100% is new, lower values indicate reduced capacity over time. | 0 – 100 |
| Online | — | Whether the pod sent a message to the server in the last 60 seconds. | `online`, `offline` |
| Charge Status | — | Current direction of energy flow reported by the pod. | `charge`, `discharge`, `idle` |
| App Mode | — | Active control strategy set in the Planetpod app. | `cash`, `solar`, `solarSmart`, `solarPure` |
| Pod Mode | — | Internal operating state reported by the pod firmware. | `cash`, `solar`, `solarSmart`, `solarPure`, `standby`, `shortStandby`, `locked`, `calibration`, `cell_health_protect`, `solarSmartSpeed`, `solarSmartBalance`, `developer`, `factorycheck`, `unknown` |
| Deployed Power | kW | Actual AC power the pod is delivering to or absorbing from the grid right now. | positive = discharging to grid, negative = charging from grid |
| Requested Power | kW | Power setpoint scheduled for the current minute by the Planetpod server. | positive = discharge request, negative = charge request |
| Received by Pod Power | kW | Power setpoint the pod's BIC module received and is executing — `null` when no active command. | positive = discharge, negative = charge, `null` at idle |
| Max Charge Power | kW | Maximum charge power ceiling sent to the BIC — reduced to 1.484 kW when sound mode is active. | `3.0` normally, `1.484` in sound mode |
| Max Discharge Power | kW | Maximum discharge power ceiling — mirrors max charge power with opposite sign. | `-3.0` normally, `-1.484` in sound mode |
| Battery Temperature | °C | Average internal cell temperature measured by the BMS. | numeric |
| AC Voltage | V | Average of both BIC module AC voltage readings — `null` if BIC has not reported yet. | typically ~230 V |
| WiFi Signal Strength | dBm | Wireless signal quality of the pod's connection to the local network. | negative number, closer to 0 is stronger |
| Relay Status | — | Whether the pod's internal 230 V relay is connected or disconnected. | `on`, `off` |
| Total Cycles | — | Number of full charge/discharge cycles the battery has completed, counted by the BMS. | integer ≥ 0 |
| SoC Upper Limit | % | Maximum charge level the pod will charge to, as configured in the app. Defaults to 85% if not set. | 0 – 100 |
| SoC Lower Limit | % | Minimum charge level the pod will discharge to, as configured in the app. Defaults to 20% if not set. | 0 – 100 |

## Sensors showing "Unknown"

Some sensors may show **Unknown** until the hardware has operated for a period of time:

| Sensor | Reason |
|---|---|
| **State of Health** | Populated after a battery calibration cycle |
| **Total Cycles** | Populated after a battery calibration cycle |
| **AC Voltage** | Reported by the BIC hardware module — null if BIC has not sent data yet |
| **Received by Pod Power** | Only non-null when the pod is actively executing a power command — null at idle is expected |

## Token expiry & re-authentication

Tokens expire after 1 year by default. When a token expires or is revoked, Home Assistant will display a **Re-authenticate** banner on the integration. Tap it, enter a new token generated from the app, and the integration resumes automatically.

## Support

https://github.com/Planetpod/home-assistant-planetpod
