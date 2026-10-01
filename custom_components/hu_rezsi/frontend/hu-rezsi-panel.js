// Rezsikövető – „Rezsi” oldalsáv-panel (Home Assistant). Build nélküli webkomponens.
// Adat: websocket `hu_rezsi/adatok`; leolvasás: `hu_rezsi.leolvasas_rogzites` szolgáltatás.
// Szemlélet: Mennyibe került? → Mennyi lesz? → Hol tartok a keretben? → Kell-e valamin változtatnom?

const FT = new Intl.NumberFormat("hu-HU", { maximumFractionDigits: 0 });
const SZAM = new Intl.NumberFormat("hu-HU", { maximumFractionDigits: 1 });
const ft = (x) => (x === null || x === undefined ? "–" : `${FT.format(x)} Ft`);
const szam = (x, e = "") => (x === null || x === undefined ? "–" : `${SZAM.format(x)}${e ? " " + e : ""}`);
const HONAP = ["jan.", "febr.", "márc.", "ápr.", "máj.", "jún.", "júl.", "aug.", "szept.", "okt.", "nov.", "dec."];
const nap = (iso) => {
  if (!iso) return "–";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${y}. ${HONAP[m - 1]} ${d}.`;
};
const elozoNap = (iso) => {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const IKON = { villany: "mdi:flash", gaz: "mdi:fire", viz: "mdi:water", hulladek: "mdi:trash-can-outline" };
const KOZMU = { villany: "Villany", gaz: "Gáz", viz: "Víz", hulladek: "Hulladékszállítás" };

class HuRezsiPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._adat = null;
    this._nyitva = new Set();
    this._hiba = null;
  }

  set hass(hass) {
    const elso = !this._hass;
    this._hass = hass;
    const mb = this.shadowRoot.querySelector("ha-menu-button");
    if (mb) mb.hass = hass;
    if (elso) {
      this._betolt();
      this._idozito = setInterval(() => this._betolt(), 60000);
    }
  }

  set narrow(v) {
    this._narrow = v;
    const mb = this.shadowRoot.querySelector("ha-menu-button");
    if (mb) mb.narrow = v;
  }

  disconnectedCallback() {
    clearInterval(this._idozito);
  }

  async _betolt() {
    try {
      this._adat = await this._hass.callWS({ type: "hu_rezsi/adatok" });
      this._hiba = null;
    } catch (e) {
      this._hiba = e.message || String(e);
    }
    this._rajzol();
  }

  // ---------------------------------------------------------------- megjelenítés

  _rajzol() {
    const a = this._adat;
    const fiokok = a ? a.haztartasok.flatMap((h) => h.fiokok) : [];
    this.shadowRoot.innerHTML = `
      <style>${STILUS}</style>
      <div class="fej">
        <ha-menu-button></ha-menu-button>
        <div class="cim">Rezsi</div>
        <button class="ikongomb" id="frissit" title="Frissítés"><ha-icon icon="mdi:refresh"></ha-icon></button>
      </div>
      <div class="tartalom">
        ${this._hiba ? `<div class="hiba">Nem sikerült betölteni: ${esc(this._hiba)}</div>` : ""}
        ${!a ? `<div class="toltes">Betöltés…</div>` : a.haztartasok.length === 0 ? `<div class="ures">Nincs beállított Rezsikövető-háztartás.</div>` : ""}
        ${a ? a.haztartasok.map((h) => this._haztartas(h)).join("") : ""}
        <div class="labjegyzet">Tájékoztató jellegű számítás, a hivatalos számlát nem helyettesíti.</div>
      </div>
      ${this._dialogus()}`;
    const mb = this.shadowRoot.querySelector("ha-menu-button");
    if (mb) {
      mb.hass = this._hass;
      mb.narrow = this._narrow;
    }
    this.shadowRoot.getElementById("frissit").addEventListener("click", () => this._betolt());
    this.shadowRoot.querySelectorAll("[data-reszlet]").forEach((el) =>
      el.addEventListener("click", () => {
        const sid = el.dataset.reszlet;
        this._nyitva.has(sid) ? this._nyitva.delete(sid) : this._nyitva.add(sid);
        this._rajzol();
      }),
    );
    this.shadowRoot.querySelectorAll("[data-leolvas]").forEach((el) =>
      el.addEventListener("click", () => this._dialogusNyit(fiokok.find((f) => f.sid === el.dataset.leolvas))),
    );
    this._dialogusKezelo();
  }

  _figyelmeztetesek(h) {
    const lista = [];
    for (const f of h.fiokok) {
      if (f.hiba) lista.push({ szint: "hiba", szoveg: `${f.nev}: nem számolható (${f.hiba})` });
      if (f.keret?.atlepes) lista.push({ szint: "figy", szoveg: `${f.nev}: várhatóan ${nap(f.keret.atlepes)} körül elfogy a kedvezményes keret` });
      if (f.elszamolas && f.elszamolas.egyenleg < -10000)
        lista.push({ szint: "figy", szoveg: `${f.nev}: várható ráfizetés az elszámoláskor kb. ${ft(-f.elszamolas.egyenleg)}` });
      if (f.egyenleg && f.egyenleg.egyenleg < -10000)
        lista.push({ szint: "figy", szoveg: `${f.nev}: az éves elszámolásnál várható ráfizetés kb. ${ft(-f.egyenleg.egyenleg)}` });
      if (f.szamla_stat?.figyelmeztetes) lista.push({ szint: "info", szoveg: `${f.nev}: ${f.szamla_stat.figyelmeztetes}` });
    }
    return lista;
  }

  _haztartas(h) {
    const figy = this._figyelmeztetesek(h);
    return `
      <section class="osszesito">
        <div class="hnev">${esc(h.nev)}</div>
        <div class="nagyszamok">
          <div><div class="cimke">Ebben a hónapban eddig</div><div class="nagy">${ft(h.osszesen.eddig)}</div></div>
          <div><div class="cimke">Várható hó végére</div><div class="nagy">${ft(h.osszesen.varhato)}</div></div>
        </div>
        <div class="megj">A több hónapra számlázott díjakból (pl. negyedéves hulladékdíj) a havi rész szerepel.</div>
        ${figy.length ? `<ul class="figylista">${figy.map((x) => `<li class="${x.szint}">${esc(x.szoveg)}</li>`).join("")}</ul>` : `<div class="rendben">Nincs teendő.</div>`}
      </section>
      <div class="racs">${h.fiokok.map((f) => this._fiok(f)).join("")}</div>`;
  }

  _fiok(f) {
    const ikon = IKON[f.kozmu] || "mdi:cash";
    if (!f.eddig) {
      return `<div class="kartya"><div class="kfej"><ha-icon icon="${ikon}"></ha-icon><div><div class="knev">${esc(f.nev)}</div></div></div>
        <div class="hiba">${esc(f.hiba || "nincs adat")}</div></div>`;
    }
    const idoszak = `${nap(f.idoszak.tol)} – ${nap(elozoNap(f.idoszak.ig))}`;
    const negyedev = f.idoszak.honapok > 1;
    const egyseg = f.egyseg === "db" ? "" : f.egyseg;
    const blokkok = [];
    // Mennyibe került? / Mennyi lesz?
    blokkok.push(`
      <div class="ket">
        <div><div class="cimke">${negyedev ? "Ebben a negyedévben" : "Eddig"}</div>
          <div class="ertek">${ft(f.eddig.osszeg)}</div>
          ${f.eddig.havi_resz ? `<div class="dolt">havonta ${ft(f.eddig.havi_resz)}</div>` : ""}
          ${!f.fix_dij ? `<div class="kicsi">${szam(f.eddig.mennyiseg, egyseg)}</div>` : ""}</div>
        <div><div class="cimke">Várható</div>
          <div class="ertek">${ft(f.varhato.osszeg)}</div>
          ${f.varhato.havi_resz ? `<div class="dolt">havonta ${ft(f.varhato.havi_resz)}</div>` : ""}
          ${!f.fix_dij && f.varhato.napi_atlag !== null ? `<div class="kicsi">napi ${szam(f.varhato.napi_atlag, egyseg)}</div>` : ""}</div>
      </div>`);
    // Hol tartok a keretben?
    if (f.keret && f.keret.osszes > 0) {
      const arany = Math.min(100, (100 * f.keret.felhasznalt) / f.keret.osszes);
      blokkok.push(`
        <div class="keret">
          <div class="cimke">Kedvezményes keret</div>
          <div class="sav"><div class="toltes ${arany >= 100 ? "tele" : arany > 80 ? "kozel" : ""}" style="width:${arany}%"></div></div>
          <div class="kicsi">${szam(f.keret.felhasznalt, f.keret.egyseg)} / ${szam(f.keret.osszes, f.keret.egyseg)} · hátra ${szam(f.keret.hatralevo, f.keret.egyseg)}
          ${f.keret.atlepes ? ` · <span class="figyszoveg">elfogy ${nap(f.keret.atlepes)} körül</span>` : ""}</div>
        </div>`);
    }
    // Kell-e változtatni? – elszámolás, egyenleg
    if (f.elszamolas) {
      const e = f.elszamolas;
      blokkok.push(`
        <div class="sor"><div><div class="cimke">Ha ma lenne az elszámolás</div>
          <div class="kicsi">${nap(e.tol)} óta: ${ft(e.tenyleges)} fogyasztás, ${ft(e.befizetve)} befizetve (${e.szamlak_db} számla)</div></div>
          <div class="ertek ${e.egyenleg < 0 ? "minusz" : "plusz"}">${e.egyenleg < 0 ? "−" : "+"}${ft(Math.abs(e.egyenleg))}</div></div>`);
    }
    if (f.egyenleg) {
      const e = f.egyenleg;
      blokkok.push(`
        <div class="sor"><div><div class="cimke">Éves egyenleg (${nap(e.ev_tol)} – ${nap(e.ev_ig)})</div>
          <div class="kicsi">várható éves költség ${ft(e.varhato_eves)} · befizetve ${ft(e.befizetve)} + hátralévő ${e.hatralevo_db} részszámla ${ft(e.hatralevo_reszszamla)}${e.megbizhato ? "" : " · <i>alacsony megbízhatóság</i>"}</div></div>
          <div class="ertek ${e.egyenleg < 0 ? "minusz" : "plusz"}">${e.egyenleg < 0 ? "−" : "+"}${ft(Math.abs(e.egyenleg))}</div></div>`);
    }
    if (f.napelem) {
      const n = f.napelem;
      blokkok.push(`
        <div class="sor"><div><div class="cimke">Napelem <span class="cimkeszalag">kísérleti</span></div>
          <div class="kicsi">vételezés ${szam(n.vetelezes, "kWh")} · betáplálás ${szam(n.betaplalas, "kWh")} · jóváírás ${ft(n.jovairas)}</div></div>
          <div class="ertek">${ft(n.egyenleg)}</div></div>`);
    }
    if (f.szamla_stat) {
      const s = f.szamla_stat;
      blokkok.push(`
        <div class="sor"><div><div class="cimke">Számlák</div>
          <div class="kicsi">utolsó 12 hónap ${ft(s.eves_osszeg)} (${s.eves_db} db) · következő ${s.kovetkezo_datum ? nap(s.kovetkezo_datum) + " körül, kb. " + ft(s.kovetkezo_osszeg) : "–"}</div>
          ${s.figyelmeztetes ? `<div class="kicsi figyszoveg">${esc(s.figyelmeztetes)}</div>` : ""}</div></div>`);
    }
    const nyitva = this._nyitva.has(f.sid);
    return `
      <div class="kartya">
        <div class="kfej"><ha-icon icon="${ikon}"></ha-icon>
          <div><div class="knev">${esc(f.nev)}</div><div class="kicsi">${KOZMU[f.kozmu] || ""} · ${idoszak}${f.aktualis_ar && !f.fix_dij ? ` · ${szam(f.aktualis_ar)} Ft/${esc(egyseg)}` : ""}</div></div></div>
        ${blokkok.join("")}
        <div class="gombok">
          <button data-reszlet="${f.sid}">${nyitva ? "Kevesebb" : "Részletek"}</button>
          ${!f.fix_dij && f.device_id ? `<button class="fo" data-leolvas="${f.sid}">Mérőállás rögzítése</button>` : ""}
        </div>
        ${nyitva ? this._reszletek(f) : ""}
      </div>`;
  }

  _reszletek(f) {
    const tabla = (fej, sorok) =>
      sorok.length
        ? `<div class="tablagorgeto"><table><thead><tr>${fej.map((x) => `<th>${x}</th>`).join("")}</tr></thead><tbody>${sorok
            .map((s) => `<tr>${s.map((c) => `<td>${c}</td>`).join("")}</tr>`)
            .join("")}</tbody></table></div>`
        : `<div class="kicsi">nincs adat</div>`;
    const egyseg = f.egyseg === "db" ? "" : f.egyseg;
    return `
      <div class="reszletek">
        <h4>Lezárt időszakok</h4>
        ${tabla(["Időszak", "Mennyiség", "Összeg"], (f.lezart || []).map((x) => [
          `${nap(x.tol)} – ${nap(elozoNap(x.ig))}`, f.fix_dij ? "–" : szam(Number(x.mennyiseg), egyseg), ft(x.osszesen_ft),
        ]))}
        ${f.fix_dij ? "" : `<h4>Mérőállások</h4>
        ${tabla(["Nap", "Állás", "Mérő", "Forrás"], (f.leolvasasok || []).map((x) => [
          nap(x.datum) + (x.elszamolasi ? " ★" : ""),
          szam(x.allas),
          x.csatorna === "almero" ? "almérő" : x.csatorna === "betaplalas" ? "betáplálás" : esc(x.mero || "fő"),
          esc(x.tipus === "szolgaltatoi" ? "szolgáltató" : x.megjegyzes?.startsWith("számla") ? "számla" : x.megjegyzes?.startsWith("v1") ? "v1" : "saját"),
        ]))}
        <div class="kicsi">★ éves elszámoló leolvasás</div>`}
        <h4>Számlák</h4>
        ${tabla(["Kelte", "Sorszám", "Típus", "Összeg"], (f.szamlak || []).map((x) => [
          nap(x.kelte), esc(x.sorszam), x.tipus === "elszamolo" ? "elszámoló" : x.tipus === "resz" ? "részszámla" : "", x.osszeg === null ? "–" : ft(Number(x.osszeg)),
        ]))}
      </div>`;
  }

  // ---------------------------------------------------------------- mérőállás rögzítése

  _dialogus() {
    return `
      <dialog id="leolv">
        <form method="dialog" id="leolvform">
          <h3 id="leolvcim">Mérőállás rögzítése</h3>
          <label>Nap<input type="date" name="datum" required></label>
          <label>Mérőállás<input type="number" name="allas" step="0.001" min="0" required inputmode="decimal"></label>
          <label id="csatsor">Mérő<select name="csatorna"></select></label>
          <label class="pipa"><input type="checkbox" name="szolgaltatoi"> Szolgáltatói leolvasás (nem saját)</label>
          <div class="dhiba" id="dhiba"></div>
          <div class="gombok">
            <button value="megse" type="button" id="megse">Mégse</button>
            <button class="fo" type="submit">Mentés</button>
          </div>
        </form>
      </dialog>`;
  }

  _dialogusNyit(f) {
    if (!f) return;
    this._dfiok = f;
    const d = this.shadowRoot.getElementById("leolv");
    this.shadowRoot.getElementById("leolvcim").textContent = `Mérőállás – ${f.nev}`;
    const form = this.shadowRoot.getElementById("leolvform");
    form.datum.value = new Date().toISOString().slice(0, 10);
    form.allas.value = "";
    const opciok = [["vetelezes", f.kozmu === "viz" ? "Főmérő" : "Mérő"]];
    if (f.almero) opciok.push(["almero", "Locsolási almérő"]);
    if (f.napelem_mod && f.napelem_mod !== "nincs") opciok.push(["betaplalas", "Betáplálás (2.8.0)"]);
    form.csatorna.innerHTML = opciok.map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
    this.shadowRoot.getElementById("csatsor").style.display = opciok.length > 1 ? "" : "none";
    this.shadowRoot.getElementById("dhiba").textContent = "";
    d.showModal();
  }

  _dialogusKezelo() {
    const d = this.shadowRoot.getElementById("leolv");
    const form = this.shadowRoot.getElementById("leolvform");
    this.shadowRoot.getElementById("megse").addEventListener("click", () => d.close());
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = this._dfiok;
      try {
        await this._hass.callService("hu_rezsi", "leolvasas_rogzites", {
          device_id: f.device_id,
          datum: form.datum.value,
          allas: Number(form.allas.value),
          csatorna: form.csatorna.value || "vetelezes",
          tipus: form.szolgaltatoi.checked ? "szolgaltatoi" : "kezi",
          megjegyzes: "Rezsi panel",
        });
        d.close();
        setTimeout(() => this._betolt(), 1500);
      } catch (e) {
        this.shadowRoot.getElementById("dhiba").textContent = e.message || String(e);
      }
    });
  }
}

const STILUS = `
  :host { display: block; min-height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color);
          font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif); }
  .fej { display: flex; align-items: center; gap: 4px; height: 56px; padding: 0 8px; background: var(--app-header-background-color, var(--primary-color));
         color: var(--app-header-text-color, var(--text-primary-color, #fff)); position: sticky; top: 0; z-index: 2; }
  .cim { font-size: 20px; flex: 1; margin-left: 8px; }
  .ikongomb { background: none; border: 0; color: inherit; cursor: pointer; padding: 8px; border-radius: 50%; }
  .tartalom { max-width: 1200px; margin: 0 auto; padding: 16px; box-sizing: border-box; }
  .osszesito { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); padding: 16px 20px; margin-bottom: 16px;
               box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); }
  .hnev { font-size: 14px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .05em; }
  .nagyszamok { display: flex; gap: 32px; flex-wrap: wrap; margin: 8px 0 4px; }
  .nagy { font-size: 32px; font-weight: 500; }
  .cimke { font-size: 12px; color: var(--secondary-text-color); }
  .megj, .kicsi { font-size: 12px; color: var(--secondary-text-color); }
  .dolt { font-size: 12px; font-style: italic; color: var(--secondary-text-color); }
  .figylista { margin: 12px 0 0; padding: 0; list-style: none; }
  .figylista li { padding: 6px 10px; margin-top: 6px; border-radius: 6px; font-size: 14px; border-left: 4px solid; }
  .figylista .figy { border-color: var(--warning-color, #ff9800); background: color-mix(in srgb, var(--warning-color, #ff9800) 12%, transparent); }
  .figylista .hiba { border-color: var(--error-color, #db4437); background: color-mix(in srgb, var(--error-color, #db4437) 12%, transparent); }
  .figylista .info { border-color: var(--info-color, #039be5); background: color-mix(in srgb, var(--info-color, #039be5) 10%, transparent); }
  .rendben { margin-top: 10px; color: var(--success-color, #43a047); font-size: 14px; }
  .racs { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
  .kartya { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); padding: 16px; border: 1px solid var(--divider-color);
            box-shadow: var(--ha-card-box-shadow, none); display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .kfej { display: flex; gap: 12px; align-items: center; }
  .kfej ha-icon { color: var(--state-icon-color, var(--primary-color)); background: color-mix(in srgb, var(--primary-color) 12%, transparent);
                  border-radius: 50%; padding: 8px; }
  .knev { font-size: 18px; font-weight: 500; }
  .ket { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .ertek { font-size: 22px; font-weight: 500; white-space: nowrap; }
  .ertek.minusz { color: var(--error-color, #db4437); }
  .ertek.plusz { color: var(--success-color, #43a047); }
  .sor { display: flex; justify-content: space-between; align-items: center; gap: 12px; border-top: 1px solid var(--divider-color); padding-top: 10px; }
  .sav { height: 8px; background: var(--divider-color); border-radius: 4px; overflow: hidden; margin: 4px 0; }
  .sav .toltes { height: 100%; background: var(--success-color, #43a047); }
  .sav .toltes.kozel { background: var(--warning-color, #ff9800); }
  .sav .toltes.tele { background: var(--error-color, #db4437); }
  .figyszoveg { color: var(--warning-color, #ff9800); }
  .cimkeszalag { font-size: 10px; padding: 1px 6px; border-radius: 8px; background: var(--warning-color, #ff9800); color: #fff; margin-left: 4px; }
  .gombok { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; margin-top: auto; }
  button { font: inherit; font-size: 14px; padding: 8px 14px; border-radius: 18px; cursor: pointer; border: 1px solid var(--divider-color);
           background: transparent; color: var(--primary-color); }
  button.fo { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .reszletek h4 { margin: 12px 0 6px; font-size: 14px; font-weight: 500; }
  .tablagorgeto { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--divider-color); white-space: nowrap; }
  th { color: var(--secondary-text-color); font-weight: 500; }
  td:last-child, th:last-child { text-align: right; }
  .hiba { color: var(--error-color, #db4437); }
  .toltes, .ures { padding: 24px; text-align: center; color: var(--secondary-text-color); }
  .labjegyzet { margin: 24px 0 8px; font-size: 12px; color: var(--secondary-text-color); text-align: center; }
  dialog { border: 0; border-radius: 16px; padding: 20px; background: var(--card-background-color); color: var(--primary-text-color); width: min(360px, 90vw); }
  dialog::backdrop { background: rgba(0, 0, 0, .45); }
  dialog h3 { margin: 0 0 12px; font-weight: 500; }
  dialog label { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; font-size: 13px; color: var(--secondary-text-color); }
  dialog label.pipa { flex-direction: row; align-items: center; gap: 8px; }
  dialog input, dialog select { font: inherit; font-size: 16px; padding: 8px; border-radius: 8px; border: 1px solid var(--divider-color);
                                background: var(--primary-background-color); color: var(--primary-text-color); }
  .dhiba { color: var(--error-color, #db4437); font-size: 13px; min-height: 1em; margin-bottom: 8px; }
  @media (max-width: 600px) { .tartalom { padding: 8px; } .racs { grid-template-columns: 1fr; } .nagy { font-size: 26px; } }
`;

customElements.define("hu-rezsi-panel", HuRezsiPanel);
