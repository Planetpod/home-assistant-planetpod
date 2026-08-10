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

## Step 1: Via HACS (Recommended)

Click the button below to add the repository to HACS on your Home Assistant instance:

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Planetpod&repository=home-assistant-planetpod&category=integration)

Then in HACS, click **Download**, confirm, and restart Home Assistant.

<details>
<summary>Manual steps (if the button doesn't work)</summary>

1. Open HACS in Home Assistant
2. Click the three-dot menu (⋮) in the top right and select **Custom repositories**
3. Paste `https://github.com/Planetpod/home-assistant-planetpod` and set category to **Integration**
4. Click **Add**
5. Search for **Planetpod**, click **Download**, confirm, and restart Home Assistant

</details>

## Step 2: Setup

[![Open your Home Assistant instance and start setting up the Planetpod integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=planetpod)

Paste your `pp_` token and confirm.

<details>
<summary>Manual steps (if the button doesn't work)</summary>

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Planetpod**
3. Paste your `pp_` token and confirm

</details>

## Sensors

One device is created per battery (identified by serial number). The following sensors are available:

| Sensor | Unit | Description | Possible values |
|---|---|---|---|
| State of Charge | % | Latest batterypack state of charge level as a percentage of total capacity. | 0 – 100 |
| State of Health | % | Battery Health indicator — 100% is new, lower values indicate reduced capacity over time (degradation). Over time, degradation is expected. | 0 – 100 |
| Online | — | Whether the pod sent a message to the server in the last 60 seconds. | `online`, `offline` |
| Charge Status | — | Latest direction of Planetpod energy flow reported by the pod going on AC connection. | `charge`, `discharge`, `idle` |
| App Mode | — | Active control strategy set in the Planetpod app. | `cash`, `solar`, `solarSmart`, `solarPure` |
| Pod Mode | — | Internal operating state reported by the pod firmware. When pod is in standby it experiences an error; this can be resolved automatically if the error is cleared. When pod is in locked it has encountered a severe error pending review from Planetpod before being resolved. Calibration is a mode where Planetpod calibrates itself by charging to 100% and balancing after that; after calibration is finished, pod will go to the latest set strategy. Calibration will happen at minimum once per 2 weeks, or if the battery is detected to be in need of calibration. | `cash`, `solar`, `solarSmart`, `solarPure`, `standby`, `shortStandby`, `locked`, `calibration`, `solarSmartSpeed`, `solarSmartBalance`, `developer`, `factorycheck`, `unknown` |
| Deployed Power | kW | AC power the pod is currently delivering to or absorbing from the grid. The pod will match this value with Requested Power Received by Pod as closely as possible at that moment. | negative = discharging to grid, positive = charging from grid, 0 = idle |
| Requested Power | kW | Power setpoint scheduled for the latest minute by the Planetpod server. | negative = discharge request, positive = charge request, 0 = idle |
| Requested Power Received by Pod | kW | Power setpoint to execute as received by the pod's control module — null when no active command received. | negative = discharge, positive = charge, null at idle |
| Max Charge Power | kW | Maximum charge power ceiling for this Pod currently — reduced to 1.484 kW when sound mode is active. | `3.0` normally, `1.484` in sound mode |
| Max Discharge Power | kW | Maximum discharge power ceiling for this Pod currently — reduced to -1.484 kW when sound mode is active. | `-3.0` normally, `-1.484` in sound mode |
| Battery Temperature | °C | Average internal cell temperature of the batterypack measured by the BMS. | numeric |
| AC Voltage | V | Average AC voltage reading, measured by both inverters — null if inverters have not reported yet or are turned off by the AC relay. | typically ~230 V. Operating range 180 – 264 V |
| WiFi Signal Strength | dBm | WiFi RSSI reading. Wireless signal quality of the pod's connection to the local network. Wi-Fi signal strength is excellent at -30 to -50 dBm, good at -50 to -67 dBm, weak at -70 to -80 dBm, and poor below -80 dBm; a reading of 0 indicates a fault. | negative number, closer to 0 is stronger |
| Relay Status | — | Whether the pod's internal 230 V relay is connected or disconnected. The pod reduces power consumption by turning off inverters with this relay. With no signal power, this is by default ON (NC). Switching time from on→off→on has a minimum of 10 seconds. | `230_ON`, `230_OFF`, null means no data |
| Total Cycles | — | Number of full charge/discharge cycles the battery has completed, counted by the BMS. | integer ≥ 0 |
| SoC Upper Limit | % | Maximum charge level the pod will charge to, as configured in the app. Defaults to 85% if not set. | 0 – 100 |
| SoC Lower Limit | % | Minimum charge level the pod will discharge to, as configured in the app. Defaults to 20% if not set. | 0 – 100 |
| G1 Solar Power | kW | Solar production power, from the pod's G1 module or a standalone P1 meter — null if no G1/P1 device is present. | numeric, ≥ 0 |
| G1 Raw Solar Current | A | Raw, unfiltered solar production current reading. | numeric |
| G1 Solar Phase | — | Number of phases the solar installation is wired across, as configured for this grid. | `single`, `three` |
| G1 Grid Import Power | kW | Power currently being drawn from the grid. | numeric, ≥ 0 |
| G1 Grid Export Power | kW | Power currently being exported to the grid (e.g. solar surplus). | numeric, ≥ 0 |
| G1 House Usage Power | kW | Total household power consumption, derived from solar + net grid flow − battery power. | numeric |

## Sensors showing "Unknown"

Some sensors may show **Unknown** until the hardware has operated for a period of time:

| Sensor | Reason |
|---|---|
| **State of Health** | Populated after a pod (re)boot |
| **Total Cycles** | Populated after a pod (re)boot |
| **AC Voltage** | Reported by the pod's inverters when Relay Status is `230_ON` — `0` if inverters have not sent data yet, null if inverters are OFF |
| **Requested Power Received by Pod** | Only non-null when the pod is actively executing a power command — null at idle is expected |
| **G1 Solar Power / G1 Raw Solar Current / G1 Solar Phase / G1 Grid Import Power / G1 Grid Export Power / G1 House Usage Power** | Only populated for pods with a G1 module or a standalone P1 meter reporting solar/grid data — stays Unknown for pods without one |

## Token expiry & re-authentication

Tokens expire after 1 year by default. When a token expires or is revoked, Home Assistant will display a **Re-authenticate** banner on the integration. Tap it, enter a new token generated from the app, and the integration resumes automatically.

## Support

https://github.com/Planetpod/home-assistant-planetpod
