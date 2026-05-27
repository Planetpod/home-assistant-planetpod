# Home Assistant Planetpod Integration

Monitor your Planetpod solar battery from Home Assistant. The integration connects via the Planetpod Open API (read-only).

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

1. Open HACS in Home Assistant
2. Click **Custom repositories**
3. Add `https://github.com/Planetpod/home-assistant-planetpod`
4. Install **Planetpod** and restart Home Assistant


## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Planetpod**
3. Paste your `pp_` token and confirm

## Sensors

One device is created per battery (identified by serial number). The following sensors are available:

| Sensor | Unit |
|---|---|
| State of Charge | % |
| State of Health | % |
| Online status | — |
| Charge status | — |
| App mode | — |
| Pod mode | — |
| Deployed power | kW |
| Requested power | kW |
| Received by pod power | kW |
| Max charge power | kW |
| Max discharge power | kW |
| Battery temperature | °C |
| AC voltage | V |
| WiFi signal strength | dBm |
| Relay status | — |
| Total cycles | — |
| SoC upper limit | % |
| SoC lower limit | % |

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
