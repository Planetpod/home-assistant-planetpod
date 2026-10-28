// Planetpod dashboard cards: SoC line, hourly Energy bars, draggable Planning.
// Plain SVG, no external chart library -- served by the integration itself
// (see __init__.py's _async_register_frontend_resources).

// Planetpod brand palette (PlanetpodAppV2/tamagui.config.ts) — hardcoded rather than
// via an HA theme, since HA has no API to create theme YAML and this session has no
// filesystem access to /config to write one by hand.
const PP_GREEN = "#44F4B3";
const PP_YELLOW = "#ffc53a";
const PP_BLUE = "#5551fe";
const PP_RED = "#f8333c";
const PP_BORDER = "#88888840";
const PP_FONT = "'Manrope', var(--paper-font-common-base_-_font-family, sans-serif)";

const COLOR_SOC = PP_BLUE;
const COLOR_LIMIT = "#94a3b8";
const COLOR_GRID = PP_RED;
const COLOR_BATTERY = PP_GREEN;
const COLOR_PLANNING = PP_YELLOW;

const CHARGE_STATUS_LABELS = { charge: "Charging", discharge: "Discharging", idle: "Idle" };
const CHARGE_STATUS_COLORS = { charge: PP_GREEN, discharge: PP_YELLOW, idle: "#94a3b8" };

function fmtSigned(value, unit) {
  if (value == null || isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)} ${unit || ""}`;
}

function fmtPlain(value, unit) {
  if (value == null || isNaN(value)) return "—";
  return `${value.toFixed(1)} ${unit || ""}`;
}

function dayBounds() {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { start, end };
}

function xForHour(hourFrac, width, pad) {
  return pad + (hourFrac / 24) * (width - 2 * pad);
}

class PlanetpodBaseCard extends HTMLElement {
  setConfig(config) {
    this._config = config;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._build();
      this._built = true;
    }
    this._onHass();
  }

  getCardSize() {
    return 4;
  }

  _root(bodyHtml) {
    this.shadowRoot.innerHTML = `
      <ha-card header="${this._config.title || ""}">
        <div class="card-content">${bodyHtml}</div>
      </ha-card>
      <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap');

        ha-card {
          font-family: ${PP_FONT};
          border-radius: 18px;
          border: 1px solid ${PP_BORDER};
        }
        .card-content { padding: 8px 16px 16px; font-family: ${PP_FONT}; }
        svg { width: 100%; height: auto; display: block; overflow: visible; }
        svg text { font-family: ${PP_FONT}; }
        .axis-label { font-size: 15px; fill: var(--secondary-text-color); }
        .legend { font-size: 16px; fill: var(--primary-text-color); }

        .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
        .kpi-tile { background: var(--secondary-background-color); border-radius: 14px; border: 1px solid ${PP_BORDER}; padding: 14px; text-align: center; }
        .kpi-label { font-size: 13px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: 0.04em; }
        .kpi-value { font-size: 30px; font-weight: 700; margin: 6px 0 2px; color: var(--primary-text-color); }
        .kpi-unit { font-size: 15px; font-weight: 400; margin-left: 3px; color: var(--secondary-text-color); }
        .kpi-subtitle { display: block; font-size: 13px; margin-top: 2px; }
        .kpi-subtitle.secondary { color: var(--secondary-text-color); }

        .send-btn {
          margin-top: 6px; padding: 6px 18px; border: none; border-radius: 8px;
          background: ${PP_GREEN}; color: #080B11;
          font-family: ${PP_FONT}; font-size: 14px; font-weight: 600; cursor: pointer;
        }
        .send-btn:disabled { opacity: 0.4; cursor: default; }
      </style>`;
  }
}

// ---------------------------------------------------------------- SoC card
class PlanetpodSocCard extends PlanetpodBaseCard {
  _build() {
    this._root(`<svg id="chart" viewBox="0 0 600 220"></svg>`);
    this._svg = this.shadowRoot.getElementById("chart");
    this._lastFetch = 0;
  }

  async _onHass() {
    const now = Date.now();
    if (now - this._lastFetch < 30000) return; // refetch history at most every 30s
    this._lastFetch = now;
    await this._render();
  }

  async _render() {
    const hass = this._hass;
    const cfg = this._config;
    const { start, end } = dayBounds();
    const historyResp = await hass.callApi(
      "GET",
      `history/period/${start.toISOString()}?filter_entity_id=${cfg.entity}&end_time=${end.toISOString()}&minimal_response`
    );
    const points = (historyResp && historyResp[0]) || [];

    const upper = parseFloat(hass.states[cfg.upper_limit_entity]?.state ?? "85");
    const lower = parseFloat(hass.states[cfg.lower_limit_entity]?.state ?? "20");

    const width = 600, height = 220, pad = 36;
    const yFor = (pct) => height - pad - (pct / 100) * (height - 2 * pad);

    const path = points
      .map((p) => {
        const t = new Date(p.last_changed || p.lu * 1000);
        const hourFrac = (t - start) / 3600000;
        const val = parseFloat(p.state ?? p.s);
        if (isNaN(val)) return null;
        return `${xForHour(hourFrac, width, pad)},${yFor(val)}`;
      })
      .filter(Boolean)
      .join(" ");

    const gridLines = [0, 20, 40, 60, 80, 100]
      .map(
        (pct) =>
          `<line x1="${pad}" x2="${width - pad}" y1="${yFor(pct)}" y2="${yFor(pct)}" stroke="var(--divider-color)" stroke-width="1"/>
           <text class="axis-label" x="2" y="${yFor(pct) + 3}">${pct}</text>`
      )
      .join("");

    const hourTicks = [0, 4, 8, 12, 16, 20, 24]
      .map(
        (h) =>
          `<text class="axis-label" x="${xForHour(h === 24 ? 23.99 : h, width, pad)}" y="${height - 8}" text-anchor="middle">${String(h).padStart(2, "0")}:00</text>`
      )
      .join("");

    this._svg.innerHTML = `
      ${gridLines}
      <line x1="${pad}" x2="${width - pad}" y1="${yFor(upper)}" y2="${yFor(upper)}" stroke="${COLOR_LIMIT}" stroke-dasharray="4,3" stroke-width="1.5"/>
      <text class="axis-label" x="${width - pad}" y="${yFor(upper) - 4}" text-anchor="end">Upper ${upper}%</text>
      <line x1="${pad}" x2="${width - pad}" y1="${yFor(lower)}" y2="${yFor(lower)}" stroke="${COLOR_LIMIT}" stroke-dasharray="4,3" stroke-width="1.5"/>
      <text class="axis-label" x="${width - pad}" y="${yFor(lower) + 12}" text-anchor="end">Lower ${lower}%</text>
      <polyline points="${path}" fill="none" stroke="${COLOR_SOC}" stroke-width="2.5"/>
      ${hourTicks}
    `;
  }
}

// ------------------------------------------------------------- Energy card
class PlanetpodEnergyCard extends PlanetpodBaseCard {
  _build() {
    this._root(`<svg id="chart" viewBox="0 0 600 220"></svg>`);
    this._svg = this.shadowRoot.getElementById("chart");
    this._lastFetch = 0;
  }

  async _onHass() {
    const now = Date.now();
    if (now - this._lastFetch < 60000) return;
    this._lastFetch = now;
    await this._render();
  }

  async _hourlyDeltas(statisticId, start, end) {
    const stats = await this._hass.callWS({
      type: "recorder/statistics_during_period",
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      statistic_ids: [statisticId],
      period: "hour",
    });
    const rows = stats[statisticId] || [];
    return rows.map((r) => (r.sum != null ? r.sum : r.state) ?? 0);
  }

  async _render() {
    const cfg = this._config;
    const { start, end } = dayBounds();

    const [delivered, returned, battery] = await Promise.all([
      this._hourlyDeltas(cfg.grid_delivered_entity, start, end),
      this._hourlyDeltas(cfg.grid_returned_entity, start, end),
      this._hourlyDeltas(cfg.battery_entity, start, end),
    ]);

    const hours = 24;
    const gridKwh = [];
    const batteryKwh = [];
    for (let h = 0; h < hours; h++) {
      const dNow = delivered[h], dPrev = h > 0 ? delivered[h - 1] : delivered[h];
      const rNow = returned[h], rPrev = h > 0 ? returned[h - 1] : returned[h];
      const bNow = battery[h], bPrev = h > 0 ? battery[h - 1] : battery[h];
      const gridDelta = (dNow ?? dPrev ?? 0) - (dPrev ?? 0) - ((rNow ?? rPrev ?? 0) - (rPrev ?? 0));
      const batteryDelta = -((bNow ?? bPrev ?? 0) - (bPrev ?? 0));
      gridKwh.push(delivered.length ? gridDelta : 0);
      batteryKwh.push(battery.length ? batteryDelta : 0);
    }

    const maxAbs = Math.max(1, ...gridKwh.map(Math.abs), ...batteryKwh.map((v, i) => Math.abs(v) + Math.abs(gridKwh[i])));
    const width = 600, height = 220, pad = 36;
    const zeroY = height / 2;
    const scale = (height / 2 - pad / 2) / maxAbs;
    const barWidth = ((width - 2 * pad) / hours) * 0.7;

    let bars = "";
    for (let h = 0; h < hours; h++) {
      const cx = xForHour(h + 0.5, width, pad);
      const g = gridKwh[h] || 0;
      const b = batteryKwh[h] || 0;
      // Stack battery on top of grid, each keeping its own sign.
      const gY0 = zeroY, gY1 = zeroY - g * scale;
      const bY0 = gY1, bY1 = gY1 - b * scale;
      bars += `<rect x="${cx - barWidth / 2}" y="${Math.min(gY0, gY1)}" width="${barWidth}" height="${Math.abs(gY1 - gY0)}" fill="${COLOR_GRID}"/>`;
      bars += `<rect x="${cx - barWidth / 2}" y="${Math.min(bY0, bY1)}" width="${barWidth}" height="${Math.abs(bY1 - bY0)}" fill="${COLOR_BATTERY}"/>`;
    }

    const hourTicks = [0, 4, 8, 12, 16, 20, 24]
      .map(
        (h) =>
          `<text class="axis-label" x="${xForHour(h === 24 ? 23.99 : h, width, pad)}" y="${height - 4}" text-anchor="middle">${String(h).padStart(2, "0")}</text>`
      )
      .join("");

    const yTicks = [-maxAbs, -maxAbs / 2, 0, maxAbs / 2, maxAbs]
      .map((v) => {
        const y = zeroY - v * scale;
        return `<line x1="${pad}" x2="${width - pad}" y1="${y}" y2="${y}" stroke="var(--divider-color)" stroke-width="1"/>
                <text class="axis-label" x="2" y="${y + 3}">${v.toFixed(1)}</text>`;
      })
      .join("");

    this._svg.innerHTML = `
      <rect x="${width - 150}" y="4" width="10" height="10" fill="${COLOR_GRID}"/>
      <text class="legend" x="${width - 136}" y="13">Grid</text>
      <rect x="${width - 90}" y="4" width="10" height="10" fill="${COLOR_BATTERY}"/>
      <text class="legend" x="${width - 76}" y="13">Battery</text>
      ${yTicks}
      <line x1="${pad}" x2="${width - pad}" y1="${zeroY}" y2="${zeroY}" stroke="var(--primary-text-color)" stroke-width="1"/>
      ${bars}
      ${hourTicks}
    `;
  }
}

// ----------------------------------------------------------------- KPI card
class PlanetpodKpiCard extends PlanetpodBaseCard {
  _build() {
    this._root(`<div id="kpis" class="kpi-grid"></div>`);
    this._el = this.shadowRoot.getElementById("kpis");
  }

  _onHass() {
    this._render();
  }

  _state(entityId) {
    return this._hass.states[entityId];
  }

  _val(entityId) {
    const s = this._state(entityId);
    return s ? parseFloat(s.state) : NaN;
  }

  _renderTile(tile) {
    let valueHtml, subtitleHtml = "";

    if (tile.kind === "value_subtitle") {
      const v = this._val(tile.entity);
      const raw = this._state(tile.subtitle_entity)?.state;
      const label = CHARGE_STATUS_LABELS[raw] || raw || "—";
      const color = CHARGE_STATUS_COLORS[raw] || "var(--secondary-text-color)";
      valueHtml = `${isNaN(v) ? "—" : v.toFixed(1)}<span class="kpi-unit">${tile.unit || ""}</span>`;
      subtitleHtml = `<span class="kpi-subtitle" style="color:${color}">${label}</span>`;
    } else if (tile.kind === "dual_signed") {
      const primary = this._val(tile.primary_entity);
      const secondary = this._val(tile.secondary_entity);
      valueHtml = fmtSigned(primary, tile.unit);
      subtitleHtml = `<span class="kpi-subtitle secondary">${tile.secondary_label}: ${fmtSigned(secondary, tile.unit)}</span>`;
    } else if (tile.kind === "net_signed") {
      const pos = this._val(tile.positive_entity);
      const neg = this._val(tile.negative_entity);
      const net = (isNaN(pos) ? 0 : pos) - (isNaN(neg) ? 0 : neg);
      valueHtml = fmtSigned(net, tile.unit);
      const direction = net > 0.01 ? "Importing" : net < -0.01 ? "Exporting" : "Balanced";
      subtitleHtml = `<span class="kpi-subtitle secondary">${direction}</span>`;
    } else if (tile.kind === "text") {
      const raw = this._state(tile.entity)?.state;
      const label = (tile.labels && tile.labels[raw]) || raw || "—";
      const color = (tile.colors && tile.colors[raw]) || "var(--primary-text-color)";
      valueHtml = `<span style="color:${color}">${label}</span>`;
    } else {
      valueHtml = fmtPlain(this._val(tile.entity), tile.unit);
    }

    return `
      <div class="kpi-tile">
        <div class="kpi-label">${tile.label}</div>
        <div class="kpi-value">${valueHtml}</div>
        ${subtitleHtml}
      </div>`;
  }

  _render() {
    const tiles = this._config.tiles || [];
    this._el.innerHTML = tiles.map((t) => this._renderTile(t)).join("");
  }
}

// ------------------------------------------------------------ Planning card
class PlanetpodPlanningCard extends PlanetpodBaseCard {
  _build() {
    this._root(`
      <svg id="chart" viewBox="0 0 600 190" style="touch-action:none;"></svg>
      <div style="text-align:center;">
        <button id="send-btn" class="send-btn" disabled>Send Planning</button>
      </div>
    `);
    this._svg = this.shadowRoot.getElementById("chart");
    this._sendBtn = this.shadowRoot.getElementById("send-btn");
    this._sendBtn.addEventListener("click", () => this._onSendClick());
    this._dragging = null;
    this._dirty = false;
    this._values = new Array(24).fill(0);
    this.width = 600;
    this.height = 220;
    this.pad = 40;
    this._svg.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    this._svg.addEventListener("pointermove", (e) => this._onPointerMove(e));
    this._svg.addEventListener("pointerup", (e) => this._onPointerUp(e));
    this._svg.addEventListener("pointercancel", (e) => this._onPointerUp(e));
  }

  _onHass() {
    // Don't clobber a drag in progress, or edits staged but not yet sent.
    if (this._dragging !== null || this._dirty) return;
    const cfg = this._config;
    const changed = cfg.entities.some((id, h) => {
      const state = this._hass.states[id];
      const val = state ? parseFloat(state.state) : 0;
      const same = this._values[h] === val;
      this._values[h] = val;
      return !same;
    });
    if (changed || !this._rendered) {
      this._rendered = true;
      this._render();
    }
  }

  _yFor(kw) {
    const max = this._config.max_power_kw || 3.0;
    const { height, pad } = this;
    return height / 2 - (kw / max) * (height / 2 - pad / 2);
  }

  _kwFor(y) {
    const max = this._config.max_power_kw || 3.0;
    const { height, pad } = this;
    const kw = -((y - height / 2) / (height / 2 - pad / 2)) * max;
    return Math.max(-max, Math.min(max, Math.round(kw * 10) / 10));
  }

  _hourForClientX(clientX) {
    const rect = this._svg.getBoundingClientRect();
    const scaleX = this.width / rect.width;
    const svgX = (clientX - rect.left) * scaleX;
    const frac = ((svgX - this.pad) / (this.width - 2 * this.pad)) * 24;
    return Math.max(0, Math.min(23, Math.round(frac - 0.5)));
  }

  _onPointerDown(e) {
    if (e.target.dataset && e.target.dataset.hour !== undefined) {
      this._dragging = parseInt(e.target.dataset.hour, 10);
      this._svg.setPointerCapture(e.pointerId);
      this._onPointerMove(e);
    }
  }

  _onPointerMove(e) {
    if (this._dragging === null) return;
    const rect = this._svg.getBoundingClientRect();
    const scaleY = this.height / rect.height;
    const svgY = (e.clientY - rect.top) * scaleY;
    this._values[this._dragging] = this._kwFor(svgY);
    this._render();
  }

  _onPointerUp() {
    if (this._dragging === null) return;
    this._dragging = null;
    this._dirty = true;
    this._sendBtn.disabled = false;
    this._render();
  }

  async _onSendClick() {
    this._sendBtn.disabled = true;
    this._sendBtn.textContent = "Sending…";
    const cfg = this._config;
    try {
      await Promise.all(
        cfg.entities.map((id, hour) =>
          this._hass.callService("number", "set_value", { entity_id: id, value: this._values[hour] })
        )
      );
      this._dirty = false;
      this._sendBtn.textContent = "Send Planning";
      this._sendBtn.disabled = true;
    } catch (err) {
      console.error("PLANETPOD: Send Planning failed", err);
      this._sendBtn.textContent = "Send failed — retry";
      this._sendBtn.disabled = false;
    }
  }

  _render() {
    const { width, height, pad } = this;
    const max = this._config.max_power_kw || 3.0;
    const zeroY = this._yFor(0);

    const gridLines = [max, max / 2, 0, -max / 2, -max]
      .map(
        (kw) =>
          `<line x1="${pad}" x2="${width - pad}" y1="${this._yFor(kw)}" y2="${this._yFor(kw)}" stroke="var(--divider-color)" stroke-width="1"/>
           <text class="axis-label" x="2" y="${this._yFor(kw) + 3}">${kw.toFixed(1)}kW</text>`
      )
      .join("");

    const linePoints = this._values
      .map((v, h) => `${xForHour(h + 0.5, width, pad)},${this._yFor(v)}`)
      .join(" ");

    const dots = this._values
      .map((v, h) => {
        const cx = xForHour(h + 0.5, width, pad);
        const cy = this._yFor(v);
        return `<circle data-hour="${h}" cx="${cx}" cy="${cy}" r="9" fill="${COLOR_PLANNING}" stroke="white" stroke-width="1.5" style="cursor:ns-resize;"/>`;
      })
      .join("");

    const hourTicks = [0, 4, 8, 12, 16, 20, 24]
      .map(
        (h) =>
          `<text class="axis-label" x="${xForHour(h === 24 ? 23.99 : h, width, pad)}" y="${height - 6}" text-anchor="middle">${String(h).padStart(2, "0")}:00</text>`
      )
      .join("");

    this._svg.innerHTML = `
      ${gridLines}
      <line x1="${pad}" x2="${width - pad}" y1="${zeroY}" y2="${zeroY}" stroke="var(--primary-text-color)" stroke-width="1"/>
      <polyline points="${linePoints}" fill="none" stroke="${COLOR_PLANNING}" stroke-width="2"/>
      ${dots}
      ${hourTicks}
    `;
  }
}

customElements.define("planetpod-soc-card", PlanetpodSocCard);
customElements.define("planetpod-energy-card", PlanetpodEnergyCard);
customElements.define("planetpod-kpi-card", PlanetpodKpiCard);
customElements.define("planetpod-planning-card", PlanetpodPlanningCard);

window.customCards = window.customCards || [];
window.customCards.push(
  { type: "planetpod-soc-card", name: "Planetpod SoC", description: "State of charge over one day with limit lines." },
  { type: "planetpod-energy-card", name: "Planetpod Energy", description: "Hourly grid/battery energy bars." },
  { type: "planetpod-kpi-card", name: "Planetpod KPIs", description: "Key stat tiles: SoC, power, temperature, P1." },
  { type: "planetpod-planning-card", name: "Planetpod Planning", description: "Draggable hourly power planning." }
);
