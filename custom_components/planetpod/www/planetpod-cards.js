// Planetpod dashboard cards: draggable hourly Planning. SoC/Energy charts and the
// KPI band now use apexcharts-card and mushroom cards respectively -- this plain
// SVG card only remains for Planning's drag-to-edit interaction, which no
// off-the-shelf charting card supports.
// Served by the integration itself (see __init__.py's _async_register_frontend_resources).

// Planetpod brand palette (PlanetpodAppV2/tamagui.config.ts) — hardcoded rather than
// via an HA theme, since HA has no API to create theme YAML and this session has no
// filesystem access to /config to write one by hand.
const PP_GREEN = "#44F4B3";
const PP_YELLOW = "#ffc53a";
const PP_BORDER = "#88888840";
const PP_FONT = "'Manrope', var(--paper-font-common-base_-_font-family, sans-serif)";

const COLOR_PLANNING = PP_YELLOW;

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

        .send-btn {
          margin-top: 6px; padding: 6px 18px; border: none; border-radius: 8px;
          background: ${PP_GREEN}; color: #080B11;
          font-family: ${PP_FONT}; font-size: 14px; font-weight: 600; cursor: pointer;
        }
        .send-btn:disabled { opacity: 0.4; cursor: default; }
      </style>`;
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

customElements.define("planetpod-planning-card", PlanetpodPlanningCard);

window.customCards = window.customCards || [];
window.customCards.push(
  { type: "planetpod-soc-card", name: "Planetpod SoC", description: "State of charge over one day with limit lines." },
  { type: "planetpod-energy-card", name: "Planetpod Energy", description: "Hourly grid/battery energy bars." },
  { type: "planetpod-kpi-card", name: "Planetpod KPIs", description: "Key stat tiles: SoC, power, temperature, P1." },
  { type: "planetpod-planning-card", name: "Planetpod Planning", description: "Draggable hourly power planning." }
);
