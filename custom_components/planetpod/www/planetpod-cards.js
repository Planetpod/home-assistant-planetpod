// Planetpod dashboard cards: SoC line, hourly Energy bars, draggable Planning.
// Plain SVG, no external chart library -- served by the integration itself
// (see __init__.py's _async_register_frontend_resources).

const COLOR_SOC = "#3b82f6";
const COLOR_LIMIT = "#94a3b8";
const COLOR_GRID = "#ef4444";
const COLOR_BATTERY = "#22c55e";
const COLOR_PLANNING = "#f97316";

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
        .card-content { padding: 8px 16px 16px; }
        svg { width: 100%; height: 420px; display: block; overflow: visible; }
        .axis-label { font-size: 15px; fill: var(--secondary-text-color); }
        .legend { font-size: 16px; fill: var(--primary-text-color); }
      </style>`;
  }
}

// ---------------------------------------------------------------- SoC card
class PlanetpodSocCard extends PlanetpodBaseCard {
  _build() {
    this._root(`<svg id="chart" viewBox="0 0 600 220" preserveAspectRatio="none"></svg>`);
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
           <text class="axis-label" x="2" y="${yFor(pct) + 3}">${pct}%</text>`
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
    this._root(`<svg id="chart" viewBox="0 0 600 220" preserveAspectRatio="none"></svg>`);
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

    this._svg.innerHTML = `
      <text class="legend" x="${pad}" y="14">Energy per hour</text>
      <rect x="${width - 150}" y="4" width="10" height="10" fill="${COLOR_GRID}"/>
      <text class="legend" x="${width - 136}" y="13">Grid</text>
      <rect x="${width - 90}" y="4" width="10" height="10" fill="${COLOR_BATTERY}"/>
      <text class="legend" x="${width - 76}" y="13">Battery</text>
      <line x1="${pad}" x2="${width - pad}" y1="${zeroY}" y2="${zeroY}" stroke="var(--divider-color)" stroke-width="1.5"/>
      ${bars}
      ${hourTicks}
    `;
  }
}

// ------------------------------------------------------------ Planning card
class PlanetpodPlanningCard extends PlanetpodBaseCard {
  _build() {
    this._root(`
      <svg id="chart" viewBox="0 0 600 240" preserveAspectRatio="none" style="touch-action:none;"></svg>
    `);
    this._svg = this.shadowRoot.getElementById("chart");
    this._dragging = null;
    this._values = new Array(24).fill(0);
    this.width = 600;
    this.height = 240;
    this.pad = 40;
    this._svg.addEventListener("pointerdown", (e) => this._onPointerDown(e));
    this._svg.addEventListener("pointermove", (e) => this._onPointerMove(e));
    this._svg.addEventListener("pointerup", (e) => this._onPointerUp(e));
    this._svg.addEventListener("pointercancel", (e) => this._onPointerUp(e));
  }

  _onHass() {
    if (this._dragging !== null) return; // don't fight the user's drag
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
    const hour = this._dragging;
    const entityId = this._config.entities[hour];
    this._hass.callService("number", "set_value", {
      entity_id: entityId,
      value: this._values[hour],
    });
    this._dragging = null;
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
customElements.define("planetpod-planning-card", PlanetpodPlanningCard);

window.customCards = window.customCards || [];
window.customCards.push(
  { type: "planetpod-soc-card", name: "Planetpod SoC", description: "State of charge over one day with limit lines." },
  { type: "planetpod-energy-card", name: "Planetpod Energy", description: "Hourly grid/battery energy bars." },
  { type: "planetpod-planning-card", name: "Planetpod Planning", description: "Draggable hourly power planning." }
);
