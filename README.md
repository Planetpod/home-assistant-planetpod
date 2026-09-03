# Home Assistant Planetpod Integration

Monitor and control your Planetpod solar battery from Home Assistant. Two connection types are available, chosen when you add the integration — pick whichever section below matches your setup.

| | Cloud | Local |
|---|---|---|
| Data path | Through Planetpod's servers (Open API) | Direct, pod ↔ Home Assistant on your LAN |
| Poll interval | Every 60 seconds | Every ~10 seconds (pod-driven push) |
| Control entities | No | Yes (Mode, SoC limits, Speed/Planning setpoints, one-shot actions) |
| Setup | Paste an Open API token | Point the pod at Home Assistant, follow the config flow |

Both connection types expose the same [sensors](#sensors); Local mode additionally exposes control entities and a bundled dashboard.

---

<details>
<summary><strong>☁️ Cloud mode</strong></summary>

Sensor data is routed through Planetpod's servers via the Open API. This is the simplest setup — no network changes needed — but read-only: mode/limits/commands are managed from the Planetpod app, not from Home Assistant.

### Generating an API token

1. Open the Planetpod app
2. Go to **Instellingen → Planetpod beheer**
3. Scroll down to the **Open API** section
4. Tap **Token aanmaken**
5. Tap the copy button next to the token — it is only shown once
6. The token starts with `pp_` and is valid for 1 year

> Generating a new token revokes the previous one. If you rotate the token, Home Assistant will show a re-authentication banner — enter the new token there.

### Token expiry & re-authentication

Tokens expire after 1 year by default. When a token expires or is revoked, Home Assistant displays a **Re-authenticate** banner on the integration. Tap it, enter a new token generated from the app, and the integration resumes automatically.

</details>

<details>
<summary><strong>🏠 Local mode</strong> (WIP — <code>feat/localMode</code> branch)</summary>

The pod is pointed at Home Assistant's own network instead of Planetpod's cloud, and talks to a local HTTP endpoint HA exposes at `/planetpod` — no cloud round-trip.

### How the read/write cycle works

- The pod **POSTs** its telemetry (SoC, power, temperature, status, etc.) to `/planetpod` roughly **every 10 seconds**. Home Assistant applies it the instant it arrives — no polling delay.
- The pod also **GETs** `/planetpod` on the same ~10 second cadence to fetch whatever Home Assistant currently wants it to do (mode, setpoint, SoC limits, one-shot actions). There's no push channel from HA to the pod — every command is picked up on the pod's *next* GET, so a command can take up to ~10 seconds to actually apply.
- Both directions are stateless HTTP, no auth required on the local endpoint (`requires_auth = False`) — it's meant to be reachable only from your own LAN.

### Follow the setup wizard

[![Open your Home Assistant instance and start setting up the Planetpod integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=planetpod)

1. Choose **Local** as the connection type
2. Home Assistant registers the `/planetpod` HTTP view and shows the address to point your pod at — the wizard waits here
3. Point the pod's local endpoint configuration at that address (same LAN as Home Assistant)
4. Once the pod POSTs at least once, the wizard proceeds automatically — pick which grid-power reading (**G1 source**) Balance mode should use: the pod's own reported P1 data, or an existing Home Assistant P1/DSMR sensor
5. Its device and sensors appear right away; a **"Planetpod"** dashboard is auto-provisioned into the sidebar (see below) — first appears after one HA restart

<details>
<summary>Manual setup steps (if the button doesn't work)</summary>

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Planetpod**
3. Choose **Local**

</details>

### Sidebar dashboard

A **"Planetpod"** dashboard is created automatically (one view per pod, named after its serial). Its layout, top to bottom:

| Row | Contents |
|---|---|
| **KPI band** | State of Charge, Deployed Power, Temperature, P1 Meter, Online, Relay Status — at a glance |
| **Charts** | SoC over the day, hourly Energy (grid import/export + battery charge/discharge), and the draggable **Planning** schedule |
| **Details** | Mode + SoC limits, one-shot action buttons (Reboot / Calibration / Turn Off BMS), and an Activity log |

Layout changes ship as ordinary integration updates — the dashboard regenerates automatically the next time Home Assistant (re)starts.

### Modes

The **Mode** select entity controls how the pod's power setpoint is derived. It's mirrored identically to every pod on the install — there's no per-pod split.

| Mode | Behavior |
|---|---|
| **Balance** | Zero-export target: aims to keep grid import/export near zero using your chosen G1 source. |
| **Standby** | Holds a persistent 0 kW setpoint — the pod neither charges nor discharges. |
| **Speed** | Holds a manually staged kW setpoint (**Speed Setpoint** + duration), applied via the **Send Speed Command** button. |
| **Planning** | Holds whichever value is set for the *current hour* in the 24-entry hourly schedule (`Planning Hour 00`–`23`, ±kW, staged via the dashboard's drag-to-edit Planning chart and applied via **Send Planning**) — the same source an external optimizer (e.g. EMHASS) could drive. |

All four modes are sent to the pod using the same underlying wire representation firmware expects (`Modus: "solarSmart"`, a `subMode`/`setpoint_kW` pair) — this is an implementation detail, not something you need to configure.

### Actions

| Action | Effect |
|---|---|
| **SoC Upper/Lower Limit** (number entities) | Caps how full/empty the pod will charge/discharge to. Sent to the pod on its next GET. |
| **Reboot** (button) | One-shot pod reboot. |
| **Toggle Calibration** (button) | Triggers a calibration cycle (full charge + balance). |
| **Turn Off BMS** (button) | One-shot BMS shutdown. |
| *(conditionally shown)* **Unlock SCU / Debug On / BMS Update** | Additional one-shot actions, surfaced only when applicable. |

</details>

---

## Requirements

- Home Assistant 2024.4.0 or later
- A Planetpod account with an active battery
- **Cloud mode:** a Planetpod Open API token (generated in the app)
- **Local mode:** the pod reachable on the same network as Home Assistant, and Home Assistant's HTTP integration enabled (on by default)

## Step 1: Install via HACS

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

See the **☁️ Cloud mode** or **🏠 Local mode** section above for the connection-specific wizard steps.

## Sensors

One device is created per battery (identified by serial number). The following sensors are available regardless of connection type:

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

<details>
<summary>Sensors showing "Unknown"</summary>

Some sensors may show **Unknown** until the hardware has operated for a period of time:

| Sensor | Reason |
|---|---|
| **State of Health** | Populated after a pod (re)boot |
| **Total Cycles** | Populated after a pod (re)boot |
| **AC Voltage** | Reported by the pod's inverters when Relay Status is `230_ON` — `0` if inverters have not sent data yet, null if inverters are OFF |
| **Requested Power Received by Pod** | Only non-null when the pod is actively executing a power command — null at idle is expected |

</details>

## Support

https://github.com/Planetpod/home-assistant-planetpod
