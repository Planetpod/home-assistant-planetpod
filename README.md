# Home Assistant Planetpod Integration

Monitor and control your Planetpod solar battery from Home Assistant. Two connection types are available, chosen when you add the integration — pick whichever section below matches your setup.

| | Cloud | Local |
|---|---|---|
| Data path | Through Planetpod's servers (Open API) | Direct, pod ↔ Home Assistant on your LAN |
| Poll interval | Every 60 seconds | Every ~10 seconds (pod-driven push) |
| Control entities | No | Yes (Mode, SoC limits, Speed/Planning setpoints, one-shot actions) |
| Setup | Paste an Open API token | Install the beta, have the pod switched to Home Assistant mode, follow the config flow |

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

> Requires **pod firmware 1.1.11 or later**. One Planetpod integration handles **every pod on your network**: each pod gets its own device, entities and dashboard view, and is controlled independently.

### How the read/write cycle works

- The pod **POSTs** its telemetry (SoC, power, temperature, status, etc.) to `/planetpod` roughly **every 10 seconds**. Home Assistant applies it the instant it arrives — no polling delay.
- The pod also **GETs** `/planetpod` on the same ~10 second cadence to fetch whatever Home Assistant currently wants it to do (mode, setpoint, SoC limits, one-shot actions). There's no push channel from HA to the pod — every command is picked up on the pod's *next* GET, so a command can take up to ~10 seconds to actually apply.
- Both directions are stateless HTTP, no auth required on the local endpoint (`requires_auth = False`) — it's meant to be reachable only from your own LAN.

### Before you start

1. **Install the beta release.** Local mode is only in the beta releases for now. In HACS open **Planetpod → ⋮ (top right) → Redownload**, pick **v1.1.0-beta.51** in the version list (if it isn't listed, enable **Show beta versions** first), download, and restart Home Assistant. Do **not** accept the "update" HACS then offers to the stable release: that installs v1.0.0, which has no Local mode.
2. **Let Planetpod switch your pod to Home Assistant control.** The pod only accepts commands from Home Assistant while it's in Home Assistant mode (`open_homeAssistant`). A switch for this in the app is coming; until then, ask Planetpod support to set it. Without it you still see live data, but every command is ignored.
3. **Make sure the pod can reach Home Assistant at `http://homeassistant.local:8123`.** The pod always connects to that address (it's fixed in the firmware). This works with a default Home Assistant OS install on the same network as the pod. It does **not** work if you renamed Home Assistant's hostname, changed its port, serve it over HTTPS only, or keep the pod on a separate network/VLAN that HA can't be reached from.

### Follow the setup wizard

[![Open your Home Assistant instance and start setting up the Planetpod integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=planetpod)

1. Choose **Local** as the connection type
2. The wizard shows **Waiting for connection** until the pod's first message arrives (normally within ~10 seconds)
3. Pick which grid-power reading (**G1 source**) Balance mode should use: the pod's own reported P1 data, or an existing Home Assistant P1/DSMR sensor
4. Its device and sensors appear right away; if [Mushroom](https://github.com/piitaya/lovelace-mushroom) is installed, a **"Planetpod"** dashboard is auto-provisioned into the sidebar (see below) — first appears after one HA restart. More pods on the same network are added automatically as soon as they connect.

<details>
<summary>Manual setup steps (if the button doesn't work)</summary>

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Planetpod**
3. Choose **Local**

</details>

<details>
<summary>Stuck on "Waiting for connection"?</summary>

1. Check that `http://homeassistant.local:8123` opens Home Assistant from another device on the **same network as the pod**. If it doesn't, see step 3 of [Before you start](#before-you-start).
2. Check that the pod is online in the Planetpod app.
3. In Home Assistant, open **Settings → System → Logs** and search for `PLANETPOD`. Every message from a pod is logged as `POST /planetpod received from <ip>`. No such lines means the pod isn't reaching Home Assistant at all (network/address problem); lines present but the wizard still waiting means something else is wrong, so contact Planetpod support with those log lines.

</details>

### Sidebar dashboard

A **"Planetpod"** dashboard is created automatically (one view per pod, named after its serial).

> **Requires [Mushroom](https://github.com/piitaya/lovelace-mushroom)** (install via HACS → Frontend). The dashboard is optional: without Mushroom it is not created, and a notice under **Settings → Repairs** explains how to get it. Devices, entities and automations work either way. After installing Mushroom the dashboard is created automatically; restart Home Assistant once for it to appear in the sidebar, then reload the browser page (F5).

Its layout, top to bottom:

| Row | Contents |
|---|---|
| **KPI band** | State of Charge, Deployed Power, Temperature, P1 Meter, Pod Mode, Online, Relay Status — at a glance. Pod Mode turns yellow when the firmware takes over (calibration, standby) and red when locked |
| **Charts** | SoC over the day, hourly Energy (grid import/export + battery charge/discharge), and the draggable **Planning** schedule |
| **Details** | Mode + SoC limits, one-shot action buttons (Reboot / Calibration / Turn Off BMS), and an Activity log (includes every Pod Mode change, e.g. when calibration starts and ends) |

```
┌──────────────────────────────────────────────────────────────────────┐
│ ┌──────┐ ┌────────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌──────┐ │
│ │ SoC  │ │Deployed│ │ Temp  │ │  P1   │ │  Pod  │ │Online │ │Relay │ │  KPI band
│ │  %   │ │ Power  │ │  °C   │ │ Meter │ │ Mode  │ │       │ │Status│ │
│ └──────┘ └────────┘ └───────┘ └───────┘ └───────┘ └───────┘ └──────┘ │
├──────────────────────────────────────────────────────────────────────┤
│ ┌────────────────┐  ┌────────────────┐  ┌────────────────┐          │
│ │   SoC (%)      │  │  Energy Usage  │  │    Planning    │          │  Charts
│ │  (line chart)  │  │  (hourly bars) │  │ (drag-to-edit) │          │
│ └────────────────┘  └────────────────┘  └────────────────┘          │
├──────────────────────────────────────────────────────────────────────┤
│ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌────────────────────────┐ │
│ │  SoC      │ │  Reboot   │ │  Mode     │ │       Activity         │ │  Details
│ │  Upper/   │ │Calibration│ │(+ Speed   │ │      (log feed)        │ │
│ │  Lower    │ │Turn Off   │ │ controls  │ │                        │ │
│ │  Limit    │ │  BMS      │ │if "Speed")│ │                        │ │
│ └───────────┘ └───────────┘ └───────────┘ └────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

Layout changes ship as ordinary integration updates — the dashboard regenerates automatically the next time Home Assistant (re)starts.

### Modes

The **Mode** select entity controls how the pod's power setpoint is derived. Mode, SoC limits, the Speed Setpoint/Duration/Send, and the Planning schedule are all independent per pod — setting them on one pod's card never affects another pod on the same grid.

| Mode | Behavior | How to activate it |
|---|---|---|
| **Balance** | Zero-export target: aims to keep grid import/export near zero using your chosen G1 source. | Select **Balance** in the Mode dropdown — takes effect on its own, no further input needed. |
| **Standby** | Holds a persistent 0 kW setpoint — the pod neither charges nor discharges. | Select **Standby** — takes effect on its own, no further input needed. |
| **Speed** | Holds a manually staged kW setpoint for a fixed duration. | Select **Speed** first — this reveals the **Speed Setpoint** (kW) and **Duration** (min) sliders plus a **Send Speed Command** button in the dashboard's Mode card. Set both values, then press the button — nothing applies until you do. |
| **Planning** | Holds whichever value is set for the *current hour* in the 24-entry hourly schedule (`Planning Hour 00`–`23`, ±kW) — the same source an external optimizer (e.g. EMHASS) could drive. | Select **Planning**, drag each hour's point on the dashboard's Planning chart to the desired kW, then press **Send Planning** — nothing applies until you do. **Mode must actually be set to Planning for the schedule to have any effect** — unlike Send Speed Command, Send Planning has no built-in check for this: it'll happily write your dragged values even while Mode is set to something else, with no warning, and they'll just sit there unused until you switch Mode to Planning. |

All four modes are sent to the pod using the same underlying wire representation firmware expects (`Modus: "solarSmart"`, a `subMode`/`setpoint_kW` pair) — this is an implementation detail, not something you need to configure.

### Actions

**SoC Upper/Lower Limit** (number entities) cap how full/empty the pod will charge/discharge to. Sent to the pod on its next GET.

#### Action buttons

Use the Action buttons to send commands to Planetpod through Home Assistant — these remote commands are mainly for troubleshooting and maintenance.

| Action | What it does | When to use | How to check |
|---|---|---|---|
| **Reboot** | Restarts Planetpod's onboard computer. | When Planetpod behaves unexpectedly, or Support requests a restart. | "Had a reboot" appears in the last error log after approximately one minute. |
| **Calibration** | Calibrates the state of charge (SoC) reading and balances the battery cells. Will charge to ~100%. | To start calibration manually, or when requested by Support. | Calibration mode indicates it is running. A completion message in the error log confirms it has finished. |
| **Turn-off battery supply** (`Turn Off BMS`) | Switches off the battery system. | When requested by Support, or to shut down completely for transport or service — see "Turn-off battery supply — usage notes" below. | After the complete shutdown procedure below, only one steady red light remains visible through the bottom window. |

> Other Planetpod service actions are part of the real wire protocol but deliberately **not** exposed as HA buttons — they're considered too sensitive/rare for a one-tap local action and are meant to be triggered through Planetpod support or the app instead.

<details>
<summary>Reboot — usage notes</summary>

A reboot clears the computer's cache and restarts its processes. Charging and discharging pause for approximately one minute while Planetpod starts up and reconnects to Wi-Fi and Home Assistant.

Wait at least one minute between reboots. If Planetpod has lost its connection to Home Assistant and/or Wi-Fi, the command may not reach it — in that case, perform a manual reset as described in the user manual.

</details>

<details>
<summary>Calibration — what to expect</summary>

Planetpod automatically schedules calibration:

- Every two weeks, starting the next time it receives a charge command. The action button lets you start this cycle manually.
- Or immediately, if an off-nominal low charge level is detected (undervoltage).

During calibration, Planetpod charges to approximately 100%, starting at 1.6 kW and gradually reducing the charging speed as the battery fills. The cycle ends with a trickle charge to balance the cells.

Planetpod ignores other charge and discharge commands during calibration. Once finished, it leaves Calibration mode, records an informational completion message in the error log, and resumes accepting commands from Home Assistant. To cancel calibration, reboot Planetpod.

</details>

<details>
<summary>Turn-off battery supply — usage notes</summary>

Turning off the battery system does not fully shut down Planetpod while AC power remains on — the battery system switches off, but the onboard computer continues running on AC power. Rebooting Planetpod turns the Battery supply (BMS) back on.

For a complete shutdown, follow the sequence below.

**Complete shutdown**

1. Switch off the AC input using Planetpod's isolation switch (werkschakelaar) or its dedicated circuit breaker in the distribution board (meterkastgroep).
2. Wait 30 seconds.
3. Send the **Turn-off battery supply** command through Home Assistant. Planetpod powers down once it receives the command.
4. Check the viewing window at the bottom. Shutdown is complete when only one steady red light remains visible — this is the BMS indicator for the battery system.
5. If other lights remain visible, the system is still active. Confirm that the AC input is off, then send the **Turn-off battery supply** command again. Once Planetpod has shut down, communication is no longer available.

**Starting Planetpod again**

1. Make sure the AC input has been off for at least one minute.
2. Switch the AC input back on using the isolation switch or dedicated circuit breaker.
3. Allow approximately one minute for Planetpod to start up and reconnect. Once connected, it resumes accepting charge and discharge commands from Home Assistant.

</details>

### Integrating with EMHASS (or any external optimizer)

**Planning** mode exists specifically as a generic hand-off point for an external optimizer — its 24 `Planning Hour 00`–`23` number entities are just a plain hourly kW schedule that anything can write to, [EMHASS](https://github.com/davidusb-geek/emhass) included.

EMHASS computes a day-ahead (or rolling) optimal charge/discharge schedule from PV/load forecasts and grid tariffs, and publishes it as a sensor (commonly with a `forecasts` attribute — a list of `{timestamp, value}` pairs, typically at 30-minute resolution). To feed that into Planetpod, add an automation that:

1. Triggers whenever EMHASS finishes an optimization (it fires an event) or on EMHASS's own re-run schedule.
2. Sets `select.planetpod_..._mode` to `planning`.
3. Takes the forecast for the **next 24 hours only**, averages the values that fall in each clock hour (two values per hour at 30-minute resolution), converts them to Planetpod's units, and writes each hour once with `number.set_value` on the matching `number.planetpod_..._planning_hour_HH` entity.

The 24 Planning entities are a rolling schedule by hour of day: the slot for 15:00 means "the next 15:00". Writing only the next 24 hours keeps tomorrow's values from overwriting today's, and averaging keeps one half-hour from overwriting the other.

```yaml
automation:
  - alias: "EMHASS -> Planetpod planning schedule"
    trigger:
      - platform: state
        entity_id: sensor.emhass_p_batt_forecast
    action:
      - variables:
          # Adjust these to your EMHASS sensor (check Developer Tools -> States).
          forecast: "{{ state_attr('sensor.emhass_p_batt_forecast', 'forecasts') or [] }}"
          time_key: "timestamp"
          value_key: "value"
          # EMHASS battery power is normally in W with positive = discharge;
          # Planetpod Planning is in kW with positive = charge.
          to_planetpod_kw: -0.001
          max_kw: 3.0
      - variables:
          schedule: >
            {% set start = now().replace(minute=0, second=0, microsecond=0) %}
            {% set ns = namespace(out=[]) %}
            {% for h in range(24) %}
              {% set slot_start = start + timedelta(hours=h) %}
              {% set slot_end = slot_start + timedelta(hours=1) %}
              {% set acc = namespace(total=0, count=0) %}
              {% for item in forecast %}
                {% set t = as_datetime(item[time_key]) %}
                {% if t is not none and slot_start <= t < slot_end %}
                  {% set acc.total = acc.total + (item[value_key] | float(0)) %}
                  {% set acc.count = acc.count + 1 %}
                {% endif %}
              {% endfor %}
              {% if acc.count > 0 %}
                {% set kw = acc.total / acc.count * to_planetpod_kw %}
                {% set kw = [[kw, max_kw] | min, -max_kw] | max %}
                {% set ns.out = ns.out + [{'hour': slot_start.hour, 'kw': kw | round(2)}] %}
              {% endif %}
            {% endfor %}
            {{ ns.out }}
      - service: select.select_option
        target: { entity_id: select.planetpod_XXXX_mode }
        data: { option: "planning" }
      - repeat:
          for_each: "{{ schedule }}"
          sequence:
            - service: number.set_value
              target:
                entity_id: "number.planetpod_XXXX_planning_hour_{{ '%02d' | format(repeat.item.hour) }}"
              data:
                value: "{{ repeat.item.kw }}"
```

A few things worth knowing before wiring this up:

- **Resolution mismatch:** Planning mode is hourly; EMHASS is commonly half-hourly. The automation above uses the **average** of the 30-minute values in each hour, so you lose EMHASS's sub-hourly detail against Planetpod's hourly grid.
- **Check units, sign and attribute names:** the variables at the top assume a `forecasts` attribute with `timestamp`/`value` keys, values in W, and positive = discharge. EMHASS versions and configs differ, so compare with your own sensor in **Developer Tools → States** and adjust `forecast`, `time_key`, `value_key` and `to_planetpod_kw`. Timestamps must include a timezone offset (EMHASS's do by default).
- **Keep battery specs in sync:** EMHASS's own config needs Planetpod's real capacity, round-trip efficiency, and max charge/discharge power to produce a physically realistic schedule. The Planning entities only accept values within ±the pod's max charge power (writing anything outside that range fails), which is why the automation clamps to `max_kw` (use 1.484 with sound mode on). Nothing catches an SoC-infeasible schedule (e.g. discharging past `SoC Lower Limit`), so keep EMHASS's SoC bounds matching `SoC Upper/Lower Limit` too.
- **Not EMHASS-specific:** any planner that can output (or be translated into) a 24-value hourly kW array works the same way — a plain price-reactive automation, a custom AppDaemon/pyscript app, etc. Planners that instead express charge/discharge as time *windows* rather than an hourly array (e.g. Predbat) need an extra translation step to fit Planning mode's hourly grid.

</details>

---

## Requirements

- Home Assistant 2024.4.0 or later
- A Planetpod account with an active battery
- **Pod firmware 1.1.11 or later** (required for Local mode)
- **Cloud mode:** a Planetpod Open API token (generated in the app)
- **Local mode:** the pod on the same network as Home Assistant, with Home Assistant reachable at `http://homeassistant.local:8123` (see [Before you start](#before-you-start)). One integration handles any number of pods, each controlled independently.
- **Optional, for the sidebar dashboard:** [Mushroom](https://github.com/piitaya/lovelace-mushroom) via HACS (see [Sidebar dashboard](#sidebar-dashboard))

> **Privacy:** Local mode does not send any sensitive information anywhere — only battery telemetry/control data (the same fields listed in [Sensors](#sensors)) and the connection to Planetpod's cloud that already exists independently of this integration.

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

One device is created per battery (identified by serial number). Energy Pulse (G1) data is included on the same device; multiple Energy Pulses are not supported. The following sensors are available:

| Sensor | Source | Unit | Description | Possible values |
|---|---|---|---|---|
| State of Charge | Battery | % | Latest batterypack state of charge level as a percentage of total capacity. | 0 – 100 |
| State of Health | Battery | % | Battery Health indicator — 100% is new, lower values indicate reduced capacity over time (degradation). Over time, degradation is expected. | 0 – 100 |
| Online | Battery | — | Whether the pod sent a message to the server in the last 60 seconds. | `online`, `offline` |
| Charge Status | Battery | — | Latest direction of Planetpod energy flow reported by the pod going on AC connection. | `charge`, `discharge`, `idle` |
| App Mode | Battery | — | Active control strategy set in the Planetpod app. | `cash`, `solar`, `solarSmart`, `solarPure` |
| Pod Mode | Battery | — | Internal operating state reported by the pod firmware. When pod is in standby it experiences an error; this can be resolved automatically if the error is cleared. When pod is in locked it has encountered a severe error pending review from Planetpod before being resolved, contact Planetpod. Calibration is a mode where Planetpod calibrates itself by charging to 100% and balancing after that; after calibration is finished, pod will go to the latest set strategy. Calibration will happen at minimum once per 2 weeks, or if the battery is detected to be in need of calibration. Speed is a mode where pod follows a set charging power. Balance is a mode where pod is balancing P1 to 0. | `speed` (shown as Normal), `balance`, `standby`, `shortStandby`, `calibration`, `cell_health_protect`, `locked`, `developer`, `factorycheck`, `unknown` (any value newer firmware adds); Cloud mode can also report the app modes (`cash`, `solar`, `solarSmart`, …) |
| Deployed Power | Battery | kW | AC power the pod is currently delivering to or absorbing from the grid. The pod will match this value with Requested Power Received by Pod as closely as possible at that moment. | negative = discharging to grid, positive = charging from grid, 0 = idle |
| Requested Power | Battery | kW | Power setpoint scheduled for the latest minute by the Planetpod server. | negative = discharge request, positive = charge request, 0 = idle |
| Requested Power Received by Pod | Battery | kW | Power setpoint to execute as received by the pod's control module — null when no active command received. | negative = discharge, positive = charge, null at idle |
| Max Charge Power | Battery | kW | Maximum charge power ceiling for this Pod currently — reduced to 1.484 kW when sound mode is active. | `3.0` normally, `1.484` in sound mode |
| Max Discharge Power | Battery | kW | Maximum discharge power ceiling for this Pod currently — reduced to -1.484 kW when sound mode is active. | `-3.0` normally, `-1.484` in sound mode |
| Battery Temperature | Battery | °C | Average internal cell temperature of the batterypack measured by the BMS. | numeric |
| AC Voltage | Battery | V | Average AC voltage reading, measured by both inverters — null if inverters have not reported yet or are turned off by the AC relay. | typically ~230 V. Operating range 180 – 264 V |
| WiFi Signal Strength | Battery | dBm | WiFi RSSI reading. Wireless signal quality of the pod's connection to the local network. Wi-Fi signal strength is excellent at -30 to -50 dBm, good at -50 to -67 dBm, weak at -70 to -80 dBm, and poor below -80 dBm; a reading of 0 indicates a fault. | negative number, closer to 0 is stronger |
| Relay Status | Battery | — | Whether the pod's internal 230 V relay is connected or disconnected. The pod reduces power consumption by turning off inverters with this relay. With no signal power, this is by default ON (NC). Switching time from on→off→on has a minimum of 10 seconds. | `230_ON`, `230_OFF`, null means no data |
| Total Cycles | Battery | — | Number of full charge/discharge cycles the battery has completed, counted by the BMS. | integer ≥ 0 |
| SoC Upper Limit | Battery | % | Maximum charge level the pod will charge to, as configured in the app. Defaults to 85% if not set. | 0 – 100 |
| SoC Lower Limit | Battery | % | Minimum charge level the pod will discharge to, as configured in the app. Defaults to 20% if not set. | 0 – 100 |
| G1 Solar Power | Energy Pulse | kW | Solar production power, from the pod's G1 module or a standalone P1 meter — null if no G1/P1 device is present. | numeric, ≥ 0 |
| G1 Raw Solar Current | Energy Pulse | A | Raw, unfiltered solar production current reading. | numeric |
| G1 Solar Phase | Energy Pulse | — | Number of phases the solar installation is wired across, as configured for this grid. | `single`, `three` |
| G1 Grid Import Power | Energy Pulse | kW | Power currently being drawn from the grid. | numeric, ≥ 0 |
| G1 Grid Export Power | Energy Pulse | kW | Power currently being exported to the grid (e.g. solar surplus). | numeric, ≥ 0 |
| Last Error | Battery | — | Local mode only. The pod's latest error messages, newest first, each with its severity and `(resolved)` once cleared. See [Errors](#errors). | text, or `None` |
| Last POST Received | Battery | — | Local mode only. When the pod last sent its data to Home Assistant; the raw message is in the `raw_payload` attribute. | timestamp |
| Last GET Sent | Battery | — | Local mode only. When Home Assistant last answered the pod with its commands; the raw answer is in the `raw_response` attribute. | timestamp |

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

### Errors

Local mode shows the pod's error messages in the **Last Error** sensor, and every change appears in the dashboard's **Activity** log. Each message starts with its severity, for example `[Minor error] E405 (Lost cloud connection)`, and ends with `(resolved)` once the pod reports the error has cleared. The full details of every message are in the sensor's `error_logs` attribute, and `highest_severity` holds the most severe level currently reported (handy for automations).

| Severity | Meaning | What to do |
|---|---|---|
| **Info** | Normal operation: firmware updates, restarts, calibration start/finish | Nothing |
| **Minor warning** | The pod noticed something and handles it itself | Nothing, unless it keeps repeating |
| **Minor error** | Something failed temporarily, e.g. a lost cloud connection or a communication retry | Usually recovers by itself; contact Planetpod if it persists |
| **Major error** | The pod limits or stops operation to protect the battery | Contact Planetpod if it doesn't clear |
| **Fatal** | The pod has stopped for safety | Contact Planetpod |

Messages you're most likely to see:

| Code | Severity | Meaning | Action |
|---|---|---|---|
| E401A / E401B | Info / Minor error | A firmware update was tried / installed; the pod restarts | None |
| E407A–C | Info | A firmware update attempt failed; it's retried later | None |
| E402 | Info | The pod restarted (reason included) | None, unless it repeats often |
| E300 / E901 | Info | Calibration scheduled / finished | None |
| E060 | Info | Discharge current limited near the low voltage limit | None |
| E405 | Minor error | Lost connection to the Planetpod cloud; "(resolved)" when it's back | Only if it stays unresolved: check the pod's WiFi/internet |
| E406 | Minor warning | The pod stays in short standby because another error persists; resolves automatically | Look at the other active errors |
| E902 | Minor warning | Calibration aborted due to overvoltage | None, unless it keeps happening |
| E501 | Minor error | A discharge was requested while SoC is below 3% | Check your SoC Lower Limit / EMS logic |
| E036C | Major error | SoC below minimum; the pod starts a calibration run | None; wait for calibration to finish |
| E013 / E035 | Major error | Pod or cell temperature above its limit | Check ventilation around the pod; contact Planetpod if it persists |
| E043, E044, E046, E048–E053 | Fatal | Critical BMS alarm (over-voltage, over-current, temperature) | Contact Planetpod |
| E042, E045, E047 | Major error | BMS alarm: pack/cell under-voltage or critically low SoC | Contact Planetpod if it doesn't clear |
| E033C | Fatal | Battery system locked | Contact Planetpod |

<details>
<summary>All error codes</summary>

Taken from the pod firmware's error list. Codes that never reach customers in normal operation (factory tests, debug logs) are included for completeness.

| Code | Severity | Type | Description |
|---|---|---|---|
| E001 | Major error | Temperature Error | BIC0 temperature above threshold |
| E002 | Major error | Voltage Error | BIC0 overvoltage |
| E003 | Major error | Current Error | BIC0 current exceeds threshold |
| E005 | Major error | Temperature Error | BIC1 temperature above threshold |
| E006 | Major error | Voltage Error | BIC1 overvoltage |
| E007 | Major error | Current Error | BIC1 current exceeds threshold |
| E009 | Minor error | Current Error | Total DC current exceeds pod threshold |
| E010 | Major error | Battery Error | Battery current exceeds threshold |
| E011 | Major error | Battery Error | Battery overvoltage |
| E012 | Major error | Battery Error | Battery undervoltage |
| E013 | Major error | Temperature Error | Pod temperature above high threshold |
| E014 | Minor error | Temperature Error | Pod temperature below low threshold |
| E025B | Minor warning | BIC Fault (hardware) | BIC 1 fault |
| E025C | Minor warning | BIC Fault (hardware) | BIC 0 overtemperature |
| E025D | Minor warning | BIC Fault (hardware) | BIC 1 overtemperature |
| E026A | Major error | BIC Fault | Over-temperature protection triggered BIC 0 |
| E026B | Major error | BIC Fault | Over-temperature protection triggered BIC 1 |
| E027A | Major error | BIC Fault | Over-voltage protection triggered BIC 0 |
| E027B | Major error | BIC Fault | Over-voltage protection triggered BIC 1 |
| E028A | Major error | BIC Fault | Over-current protection triggered BIC 0 |
| E028B | Major error | BIC Fault | Over-current protection triggered BIC 1 |
| E029A | Minor error | BIC Fault | AC failure detected BIC 0 |
| E029B | Minor error | BIC Fault | AC failure detected BIC 1 |
| E030A | Major error | BIC Fault | Fan failure detected BIC 0 |
| E030B | Major error | BIC Fault | Fan failure detected BIC 1 |
| E031A | Major error | BIC Fault | High temperature detected BIC 0 |
| E031B | Major error | BIC Fault | High temperature detected BIC 1 |
| E032A | Fatal | BIC Fault | Short-circuit protection BIC 0 |
| E032B | Fatal | BIC Fault | Short-circuit protection BIC 1 |
| E033A | Major error | Battery Error | Critical battery failure level 03 (alarm) detected during operation, see BMS alarm level 2 |
| E033C | Fatal | Battery Error | Battery system locked |
| E035 | Major error | Temperature Error | Cell temperature above threshold |
| E036 | Fatal | Temperature Error | Cell, BIC, BMS or SCU above threshold |
| E036A | Minor warning | Cell voltage low | Cell voltage nearing threshold |
| E036B | Major error | BMS_ERROR | Cell undervoltage |
| E036C | Major error | SOC low | SOC below minimum threshold, starting calibration run |
| E037 | Major error | Cell overvoltage | Cell voltage over threshold |
| E037A | Fatal | Fatal Cell overvoltage | Cell voltage over fatal threshold |
| E038 | Minor warning | Backuppower detect | Backup power detected |
| E039 | Minor error | BICChecker | SystemConfig not as expected |
| E040 | Minor error | BICChecker | Direction not as expected |
| E041 | Minor error | BICChecker | bidirectionConfig not as expected |
| E042 | Major error | BMS Alarm | Pack under-voltage critical |
| E0429 | Minor warning | BMS Unlock | BMS is not in locked state, unlock skipped |
| E042A | Minor warning | BMS Alarm Data 1 | BMS alarm details |
| E042B | Minor warning | BMS Unlocked | BMS is in unlocked state! |
| E042C | Minor warning | BMS Unlock PGN | Received BMS PGN but not the expected data |
| E043 | Fatal | BMS Alarm | Pack over-voltage critical |
| E044 | Fatal | BMS Alarm | Discharging over-current critical |
| E045 | Major error | BMS Alarm | Low SOC critical |
| E046 | Fatal | BMS Alarm | Cell over-voltage critical |
| E047 | Major error | BMS Alarm | Cell under-voltage critical |
| E048 | Fatal | BMS Alarm | High cell voltage difference critical |
| E049 | Fatal | BMS Alarm | Charging over-temperature critical |
| E050 | Fatal | BMS Alarm | Charging under-temperature critical |
| E051 | Fatal | BMS Alarm | Discharging over-temperature critical |
| E052 | Fatal | BMS Alarm | Discharging under-temperature critical |
| E053 | Fatal | BMS Alarm | High cell temperature difference critical |
| E054 | Major error | BMS Alarm | Voltage Aquisition Fault |
| E055 | Major error | BMS Alarm | Temperature Aquisition Fault |
| E060 | Info | Low voltage limit | Discharge current limit |
| E109 | Minor error | Data expired | Data expired in BIC_Data |
| E111 | Minor error | Data expired | No BIC and SCU temp |
| E112 | Minor warning | Data expired | sameGroup=true but no G1 devices connected |
| E113 | Minor warning | Data expired | G1Device solar_data expired for balancing device |
| E114 | Minor warning | Data expired | G1Device solar_data expired for non-balancing device |
| E120A | Minor warning | CAN Queue full | failed to send message to queue |
| E120B | Minor error | BMS Update | Starting BMS firmware update |
| E121 | Info | BMSUpdater | BMS firmware version changed |
| E122A | Minor warning | BMS Update | Incorrect password for BMS firmware update |
| E122B | Minor warning | BMS Update | Update disabled |
| E123 | Minor error | BMS Update | CAN timeout |
| E200 | Minor error | CAN Fault | Error Sending BIC Read Operation Command |
| E200A | Minor error | CAN Fault | Error Sending BIC Read Direction Command |
| E200B | Minor error | CAN Fault | Error Sending BIC Read VOUT Command |
| E201 | Minor error | CAN Fault | Error Sending BIC Read VIN Command |
| E202 | Minor error | CAN Fault | Error Sending BIC Read Temperature Command |
| E203 | Minor error | CAN Fault | Error Sending BIC Read IOUT Command |
| E204 | Minor error | CAN Fault | Error Sending BIC Read Fault Status Command |
| E205 | Minor error | CAN Fault | Error Sending BIC Read ScalingFactor Command |
| E205A | Minor error | CAN Fault | Error Sending BIC Read SystemStatus Command |
| E206 | Minor error | CAN Fault | Error Sending BIC Read IOUT_SET Command |
| E207 | Minor error | CAN Fault | Error Sending VOUT_SET Command |
| E207A | Minor error | CAN Fault | Error Sending BIC Read reverse_IOUT_SET Command |
| E208 | Minor error | CAN Fault | Error Sending BIC Read VOUT_SET Command |
| E208A | Minor error | CAN Fault | Error Sending Reverse_VOUT_SET Command |
| E209 | Minor error | CAN Fault | Error Sending BIC Read reverseVOUT_SET Command |
| E209A | Minor error | CAN Fault | Error Sending IOUT_SET Command |
| E210 | Minor error | CAN Fault | Error Sending Reverse_IOUT_SET Command |
| E211 | Minor error | Communication Error | Error Sending Direction Control Command |
| E212 | Minor warning | Communication Error | Error Sending System Configuration Command |
| E213 | Minor warning | Communication Error | Error Sending read System Configuration Command |
| E214 | Minor warning | Communication Error | Error Sending Bidirectional Configuration Command |
| E215 | Minor warning | Communication Error | Error Sending read Bidirectional Configuration Command |
| E300 | Info | planned calibration | Starting a scheduled calibration at next charge cycle |
| E305 | Major error | PCF8574 Init fail | PCF8574 Communication Initialized |
| E306 | Major error | Communication Error | Failed to initialize PCF8574 (write failure) |
| E307 | Major error | NVS | NVS Initialization failed |
| E308 | Major error | NVS | failed to enqueue NVS write request |
| E401A | Info | OTA Update | Trying OTA update |
| E401B | Minor error | OTA Update | OTA update successful, restarting after 15sec |
| E402 | Info | Reboot | Pod restarted (description includes the reason) |
| E405 | Minor error | Lost cloud connection | Pod lost (or restored) its connection to the Planetpod cloud |
| E406 | Minor warning | Extended Short Standby | Pod stays in short standby because errors persist; resolves automatically |
| E407A | Info | OTA Update fail | Failed to set boot partition: |
| E407B | Info | OTA Update fail | Could not get next update partition after succesfull download |
| E407C | Info | OTA Update fail | OTA fail: |
| E409A | Info | NVS Erasing | NVS partition erased |
| E409B | Info | NVS Erasing perserve url | NVS partition erased |
| E410 | Minor warning | Low internal memory | Internal free:  bytes |
| E411 | Info | P1 Balance Ducking | Balance mode reduced power to respect the grid connection |
| E501 | Minor error | Output | Discharge command while SOC < 3 |
| E503 | Minor warning | Output | BIC_Data power calc not valid |
| E504 | Minor warning | Output | BMSBatteryData1 power calc not valid |
| E505 | Minor warning | Output | BMSSystemData2 power calc not valid |
| E506 | Minor warning | Output | BMSCellData1 power calc not valid |
| E508 | Minor warning | Output | BIC_Data power calc not valid |
| E509 | Minor warning | Output | BMSBatteryData1 power calc not valid |
| E510 | Minor warning | Output | BMSSystemData2 power calc not valid |
| E511 | Minor warning | Output | BMSCellData1 power calc not valid |
| E512 | Minor warning | Output | Solar power calc not valid |
| E513 | Minor warning | Output | BMSCellData2 power calc not valid |
| E514 | Minor warning | Output | BMSCellData2 power calc not valid |
| E600 | Minor warning | FactoryCheck | Not started calib, no BMS data |
| E601 | Minor warning | FactoryCheck | Not started calib, no BMS data during discharge |
| E602 | Info | FactoryCheck | Factory complete, turning bms off |
| E603 | Info | FactoryCheck | Starting calibration task |
| E604 | Minor warning | FactoryCheck | Discharge too fast during factory test |
| E901 | Info | Calibration | Calibration run finished |
| E902 | Minor warning | Calibration | Calibration aborted due to overvoltage |
| E988 | Minor warning | Test log | Misread can bit, starting 3 S timer |

</details>


## Support

https://github.com/Planetpod/home-assistant-planetpod
