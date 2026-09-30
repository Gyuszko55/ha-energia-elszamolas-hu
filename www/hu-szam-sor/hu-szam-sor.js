// hu-szam-sor: input_number beviteli sor tizedesvesszővel (energia-elszámolás csomag).
// A böngésző number-mezője a HA számformátumától függetlenül pontot mutat; ez szöveges mezőt használ,
// vesszővel jelenít meg, vesszőt és pontot is elfogad, és input_number.set_value-val ment.
class HuSzamSor extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) throw new Error("entity kötelező");
    this._config = config;
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._root) this._build();
    this._update();
  }
  getCardSize() { return 1; }

  _decimals(so, v) {
    if (this._config.decimals !== undefined) return this._config.decimals;
    const tiz = (x) => { const t = String(x); return t.includes(".") ? t.split(".")[1].replace(/0+$/, "").length : 0; };
    // a lépésköz tizedesei, de legalább annyi, amennyi a tárolt értékben van (ne kerekítsen el semmit)
    return Math.max(tiz((so && so.attributes.step) || 1), tiz(v !== undefined ? v : (so ? so.state : 0)));
  }
  _fmt(v, dec) {
    return Number(v).toLocaleString("hu-HU", { minimumFractionDigits: dec, maximumFractionDigits: dec, useGrouping: false });
  }
  _build() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        :host { display: block; }
        .row { display: flex; align-items: center; min-height: 40px; gap: 16px; }
        .icon { width: 40px; display: flex; justify-content: center; color: var(--state-icon-color, var(--paper-item-icon-color)); cursor: pointer; flex: none; }
        .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; color: var(--primary-text-color); }
        .box { display: flex; align-items: center; gap: 6px; background: var(--input-fill-color, var(--secondary-background-color));
               border-bottom: 1px solid var(--input-idle-line-color, var(--secondary-text-color)); border-radius: 4px 4px 0 0; padding: 0 10px; height: 48px; flex: none; }
        .box.err { border-bottom: 2px solid var(--error-color); }
        .box:focus-within { border-bottom: 2px solid var(--primary-color); }
        input { width: 90px; border: none; background: transparent; font: inherit; font-size: 16px; text-align: right; color: var(--primary-text-color); outline: none; }
        .unit { color: var(--secondary-text-color); font-size: 14px; min-width: 32px; }
      </style>
      <div class="row">
        <div class="icon"><ha-state-icon></ha-state-icon></div>
        <div class="name"></div>
        <div class="box"><input type="text" inputmode="decimal" autocomplete="off"><span class="unit"></span></div>
      </div>`;
    this._in = this._root.querySelector("input");
    this._box = this._root.querySelector(".box");
    const more = () => this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: this._config.entity }, bubbles: true, composed: true }));
    this._root.querySelector(".icon").addEventListener("click", more);
    this._root.querySelector(".name").addEventListener("click", more);
    this._in.addEventListener("keydown", (e) => { if (e.key === "Enter") this._in.blur(); if (e.key === "Escape") { this._editing = false; this._update(true); this._in.blur(); } });
    this._in.addEventListener("focus", () => { this._editing = true; this._shown = this._in.value; this._in.select(); });
    this._in.addEventListener("blur", () => this._save());
  }
  _update(force) {
    const so = this._hass.states[this._config.entity];
    const icon = this._root.querySelector("ha-state-icon");
    icon.hass = this._hass; icon.stateObj = so;
    if (this._config.icon) icon.icon = this._config.icon;
    this._root.querySelector(".name").textContent = this._config.name || (so ? so.attributes.friendly_name : this._config.entity);
    this._root.querySelector(".unit").textContent = (so && so.attributes.unit_of_measurement) || "";
    if (!so) { this._in.value = "–"; this._in.disabled = true; return; }
    this._in.disabled = so.state === "unavailable";
    if (!this._editing || force) {
      const n = parseFloat(so.state);
      this._in.value = isNaN(n) ? so.state : this._fmt(n, this._decimals(so, n));
    }
  }
  _save() {
    if (!this._editing) return;
    this._editing = false;
    if (this._in.value === this._shown) return; // nem módosították: nem ment (nincs kerekítési átírás)
    const so = this._hass.states[this._config.entity];
    const raw = this._in.value.replace(/\s/g, "").replace(",", ".");
    const v = parseFloat(raw);
    const a = so.attributes;
    if (raw === "" || isNaN(v) || !/^[-+]?\d*\.?\d+$/.test(raw) || v < a.min || v > a.max) {
      this._box.classList.add("err");
      setTimeout(() => this._box.classList.remove("err"), 1500);
      this._update(true);
      return;
    }
    if (v !== parseFloat(so.state)) {
      this._hass.callService("input_number", "set_value", { entity_id: this._config.entity, value: v });
    }
    this._in.value = this._fmt(v, this._decimals(so, v));
  }
}
customElements.define("hu-szam-sor", HuSzamSor);
