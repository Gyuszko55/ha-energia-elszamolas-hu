// Rezsikövető – indítókártya (custom:rezsikoveto-kartya). Egyvonalas ház, benne az otthon kifizetetlen számláinak
// összege és fiókonként (ikonnal) a fizetendő; koppintásra a Rezsikövető panel nyílik. Az otthon: a beállított,
// különben a panelen utoljára kiválasztott (localStorage „hu_rezsi_otthon”, böngészőnként), különben az első.
// Az integráció minden oldalon betölti (add_extra_js_url) – erőforrásként nem kell felvenni.
// Fűtés: otthononként, az otthon beállításaiból (Rezsikövető → otthon → Konfigurálás; hu_rezsi/kartya „futes”): futes =
// climate (vagy kapcsoló/bináris érzékelő) – bent a hőmérséklete, fűtés közben füst száll a kéményből; belso_homerseklet
// felülírja a bentit; kulso_homerseklet (érzékelő vagy időjárás) a házon kívül. Beállítás nélkül nincs hőmérséklet és füst.
// AI-tájékoztató (KÍSÉRLETI, ai_tajekoztato: true): a lábléc gombja felugró ablakban mutatja az AI szövegét a számlák
// állásáról és a kilátásokról (hu_rezsi/ai_tajekoztato; az utolsó tárolva, újat csak kérésre – az AI-hívás 10–60 s).

// Új változat: a már definiált kártyát a böngésző nem cseréli le (a mobilalkalmazás HA-újraindításkor sem tölt újra),
// ezért a betöltött fájl módosítási idejét figyeljük, és ha közben új került fel, az alkalmazás háttérből való
// visszatérésekor (vagy a következő lekéréskor, ha az oldal épp nem látszik) újratöltjük az oldalt – mint a panel.
const FAJL = new URL(import.meta.url).pathname;
const verzio = async () => {
  try {
    const v = await fetch(FAJL, { method: "HEAD", cache: "no-store" });
    return v.ok ? v.headers.get("last-modified") || v.headers.get("etag") : null;
  } catch (e) { return null; }
};
const BETOLTOTT = verzio();
let ujVerzio = false;
async function verzioEllenor() {
  const [regi, most] = await Promise.all([BETOLTOTT, verzio()]);
  if (regi && most && regi !== most) ujVerzio = most;
  return ujVerzio;
}
async function ujratoltHaKell() {
  if (!ujVerzio) return;
  try {
    if (sessionStorage.getItem("hu_rezsi_kartya_ujratoltve") === ujVerzio) return; // egy változatra csak egyszer
    sessionStorage.setItem("hu_rezsi_kartya_ujratoltve", ujVerzio);
  } catch (e) { /* tárolás nélkül is */ }
  // A modul URL-je (…?v=) HA-újraindításig nem változik, és a fájl gyorsítótár-fejléc nélkül jön: a böngésző (Android
  // WebView) újratöltéskor a régi, tárolt példányt adná. Előbb a tárolt példányt frissítjük, csak utána töltünk újra.
  try { await fetch(import.meta.url, { cache: "reload" }); } catch (e) { /* újratöltés így is */ }
  location.reload();
}
if (!window.__huRezsiKartyaFigyelo) {
  window.__huRezsiKartyaFigyelo = true;
  document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState === "visible" && await verzioEllenor()) ujratoltHaKell();
  });
}

const IKON = { villany: "mdi:flash", gaz: "mdi:fire", viz: "mdi:water", tavho: "mdi:radiator", hulladek: "mdi:trash-can-outline", kozos: "mdi:office-building-outline", tavkozles: "mdi:router-wireless" };
const FRISSITES_MS = 5 * 60 * 1000;
const MAX_TETEL = 6;  // 2 oszlop × 3 sor
// A ház egyetlen vonallal: a talajvonal balról befut a bal falba, kémény, tető, jobb fal, a padlón balra, a végén
// csepp alakú hurok (mint a mintarajzon), majd a padlót keresztezve tovább a talajon. A ház balra tolva: jobbra fent a
// mérőállások oszlopa ne lógjon a tetőbe.
const HAZ = "M6,234 C20,229 30,237 40,232 C47,229 46,222 46,212 L46,125 L28,125 L72,89.6 L72,52 L90,52 L90,75.1 L136,38 "
  + "L244,125 L226,125 L226,220 C226,228 220,230 208,230 L100,230 C92,230 91,223 99,223 C112,223 130,232 160,236 "
  + "C200,240 230,238 252,237 C276,236 290,232 314,233";
// Mérőállás-ikonok közművenként színesen.
const MERO_SZIN = { villany: "#f2a900", gaz: "#ef6c00", viz: "#1e88e5", tavho: "#d84315" };

// Füstpamacsok a kémény fölött (a kémény közepe x=81, teteje y=52); késleltetve indulnak, így folyamatos a füst.
const FUST = [0, 1, 2].map((i) => `<circle class="pamacs" cx="81" cy="46" r="6" style="animation-delay:${i}s"/>`).join("");

const fok = (v) => `${Number(v).toLocaleString("hu-HU", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} °C`;
const ft = (n) => `${Math.round(n).toLocaleString("hu-HU")} Ft`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// Mérőállások: villanynál a tarifa jele (+ regiszter), másnál csak az ikon; az állás élőben a szenzorral lép.
const REGISZTER = { h_teli: "téli", h_nyari: "nyári", zona_csucs: "csúcs", zona_volgy: "völgy", betaplalas: "2.8.0", almero: "almérő" };
const allasJel = (f, a) => [f.kozmu === "villany" ? f.tarifa : "", REGISZTER[a.szerep] || ""].filter(Boolean).join(" ");
// Egész számra (lefelé), ahogy a mérőóra egész számlálója mutatja és ahogy a számlák is számolnak.
const allasSzam = (v, egyseg) => `${Math.floor(Number(v) + 1e-9).toLocaleString("hu-HU", { useGrouping: true })} ${egyseg}`;
const nap = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("hu-HU", { month: "short", day: "numeric" });

const idopont = (iso) => new Date(iso).toLocaleString("hu-HU", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

// A felugró ablak a dokumentum törzsébe kerül (a kártya rácscellája ne vágja le); a HA témaváltozói a html elemen
// vannak, így itt is érvényesek.
class RezsiAiAblak extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._billentyu = (e) => { if (e.key === "Escape") this.bezar(); };
  }

  nyit(hass, entryId, entitas, otthonNev) {
    this._hass = hass; this._entry = entryId; this._entitas = entitas || null; this._nev = otthonNev;
    this._t = null; this._hiba = null; this._keszul = false;
    document.body.appendChild(this);
    document.addEventListener("keydown", this._billentyu);
    this._rajzol();
    this._leker(false);
  }

  bezar() {
    document.removeEventListener("keydown", this._billentyu);
    this.remove();
  }

  async _leker(uj) {
    this._hiba = null;
    if (uj) { this._keszul = true; this._rajzol(); }
    try {
      const v = await this._hass.callWS({ type: "hu_rezsi/ai_tajekoztato", entry_id: this._entry, uj, ...(this._entitas ? { entitas: this._entitas } : {}) });
      this._vanAi = !!v.entitas;
      this._t = v.tajekoztato || this._t;
      // Még nincs (vagy épp készül egy másik eszközről): elkészíttetjük / megvárjuk. Újat (fizetős AI-hívás) csak
      // rendszergazda kérhet; másnak a tárolt tájékoztató, ill. egy üzenet.
      if (!uj && (v.keszul || (!v.tajekoztato && v.entitas))) {
        if (this._hass?.user?.is_admin) return this._leker(true);
        if (!v.tajekoztato) this._hiba = v.keszul ? "A tájékoztató most készül – nyisd meg újra egy perc múlva." : "Még nincs tájékoztató; rendszergazda készíthet újat.";
      }
    } catch (e) {
      this._hiba = e?.message || "Az AI-tájékoztató nem készült el.";
    }
    this._keszul = false;
    this._rajzol();
  }

  _rajzol() {
    const t = this._t;
    const lista = (cim, ikon, tetelek) => tetelek?.length ? `<section><h3><ha-icon icon="${ikon}"></ha-icon>${cim}</h3><ul>${tetelek.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></section>` : "";
    const tartalom = this._keszul
      ? `<div class="var"><ha-circular-progress indeterminate size="small"></ha-circular-progress><span>Az AI megírja a tájékoztatót… (10–60 másodperc)</span></div>`
      : t ? `<p class="ossz">${esc(t.osszefoglalo)}</p>${lista("Most", "mdi:receipt-text-check-outline", t.most)}${lista("Kilátások", "mdi:chart-timeline-variant", t.kilatasok)}${lista("Teendők", "mdi:checkbox-marked-circle-outline", t.teendok)}`
        : this._vanAi === false ? `<p class="hiba">Nincs AI Task entitás. Vegyél fel egy AI-szolgáltatást (pl. Google Gemini, OpenAI) a Beállítások → Eszközök és szolgáltatások alatt.</p>` : "";
    this.shadowRoot.innerHTML = `
      <style>
        :host { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 16px;
          background: rgba(0, 0, 0, .45); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
        .ablak { background: var(--ha-card-background, var(--card-background-color, #fff)); color: var(--primary-text-color);
          border-radius: var(--ha-dialog-border-radius, 24px); width: min(560px, 100%); max-height: calc(100% - 32px); display: flex;
          flex-direction: column; box-shadow: 0 8px 32px rgba(0, 0, 0, .35); overflow: hidden; }
        header { display: flex; align-items: flex-start; gap: 8px; padding: 18px 12px 6px 20px; }
        header ha-icon { --mdc-icon-size: 24px; color: var(--primary-color); margin-top: 2px; }
        h2 { flex: 1; margin: 0; font-size: 1.25em; font-weight: 500; line-height: 1.3; }
        .x { background: none; border: 0; color: var(--secondary-text-color); cursor: pointer; padding: 4px; border-radius: 50%; }
        .x ha-icon { --mdc-icon-size: 22px; color: inherit; margin: 0; }
        .meta { padding: 0 20px 8px; font-size: .85em; color: var(--secondary-text-color); }
        .torzs { overflow-y: auto; padding: 4px 20px 8px; line-height: 1.45; }
        .ossz { margin: 4px 0 12px; font-size: 1.02em; }
        section { margin-bottom: 10px; }
        h3 { display: flex; align-items: center; gap: 6px; margin: 0 0 4px; font-size: .95em; font-weight: 500; color: var(--secondary-text-color);
          text-transform: uppercase; letter-spacing: .04em; }
        h3 ha-icon { --mdc-icon-size: 18px; color: var(--primary-color); }
        ul { margin: 0; padding-left: 22px; }
        li { margin: 3px 0; }
        .var { display: flex; align-items: center; gap: 12px; padding: 24px 0; color: var(--secondary-text-color); }
        .hiba { color: var(--error-color, #db4437); }
        .megj { margin: 8px 0 0; font-size: .8em; color: var(--secondary-text-color); font-style: italic; }
        footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; padding: 10px 16px 16px; border-top: 1px solid var(--divider-color); }
        footer button { font: inherit; font-weight: 500; border-radius: 18px; padding: 8px 16px; cursor: pointer; border: 1px solid var(--divider-color);
          background: none; color: var(--primary-color); }
        footer button.fo { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
        footer button:disabled { opacity: .5; cursor: default; }
      </style>
      <div class="ablak" role="dialog" aria-modal="true" aria-label="AI-tájékoztató">
        <header><ha-icon icon="mdi:creation-outline"></ha-icon><h2>${esc(t?.cim || "Rezsi-tájékoztató")}</h2>
          <button class="x" title="Bezárás" aria-label="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></header>
        <div class="meta">${esc(this._nev || t?.otthon || "")}${t ? ` · készült ${idopont(t.keszult)}` : ""}</div>
        <div class="torzs">${tartalom}${this._hiba ? `<p class="hiba">${esc(this._hiba)}</p>` : ""}
          <p class="megj">Kísérleti funkció: a szöveget mesterséges intelligencia írta a Rezsikövető számaiból, tévedhet – a pontos adatok a Rezsikövető panelen.</p></div>
        <footer><button class="panel">Panel megnyitása</button>${this._hass?.user?.is_admin ? `<button class="fo uj"${this._keszul || this._vanAi === false ? " disabled" : ""}>Új tájékoztató</button>` : ""}</footer>
      </div>`;
    this.shadowRoot.querySelector(".x").addEventListener("click", () => this.bezar());
    this.shadowRoot.querySelector(".uj")?.addEventListener("click", () => this._leker(true));
    this.shadowRoot.querySelector(".panel").addEventListener("click", () => {
      this.bezar();
      history.pushState(null, "", "/rezsi");
      window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
    });
    this.addEventListener("click", (e) => { if (e.composedPath()[0] === this) this.bezar(); }, { once: true });
  }
}

class RezsikovetoKartya extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._adat = null;
    this._hiba = null;
    this._lekerve = 0;
    this._rajzolt = false;
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    const elso = !this._hass;
    this._hass = hass;
    if (elso || Date.now() - this._lekerve > FRISSITES_MS) this._lekeres();
    else if (this._otthonKulcs() !== this._kulcs) this._render(); // a panelen közben másik otthont választottak
    else this._allapot();
  }

  _homerseklet(id, attr) {
    const a = id && this._hass?.states[id];
    if (!a) return null;
    const v = attr ? a.attributes[attr] : a.entity_id.startsWith("weather.") ? a.attributes.temperature : a.state;
    return v === null || v === undefined || v === "" || isNaN(Number(v)) ? null : Number(v);
  }

  _futes() {
    return this._otthon()?.futes || {};
  }

  _fut() {
    const c = this._futes();
    const a = c.futes && this._hass?.states[c.futes];
    if (!a) return false;
    if (a.entity_id.startsWith("climate.")) return a.attributes.hvac_action === "heating";
    return ["on", "heat", "heating"].includes(a.state);
  }

  // A mérőállás élőben: a koordinátor (10 percenként) számolt állása + szorzó × a szenzor azóta mért változása.
  _elo(a) {
    const st = this._hass?.states?.[a.entity_id];
    const v = st ? Number(st.state) : NaN;
    if (a.alap === null || a.alap === undefined || isNaN(v) || v < a.alap) return a.allas;
    return a.allas + a.szorzo * (v - a.alap);
  }

  // A hőmérsékletek, a mérőállások és a füst helyben frissül (újrarajzolás nélkül: a füst animációja nem ugrik).
  _allapot() {
    const r = this.shadowRoot;
    if (!r.querySelector(".haz")) return;
    r.querySelectorAll(".allas[data-i]").forEach((el) => {
      const [fi, ai] = el.dataset.i.split(".").map(Number);
      const f = this._allasFiokok?.[fi], a = f?.allasok?.[ai];
      if (a) el.querySelector(".aert").textContent = allasSzam(this._elo(a), f.egyseg);
    });
    const c = this._futes(), futesClimate = c.futes?.startsWith("climate.");
    const bent = c.belso_homerseklet ? this._homerseklet(c.belso_homerseklet) : futesClimate ? this._homerseklet(c.futes, "current_temperature") : null;
    const kint = this._homerseklet(c.kulso_homerseklet);
    const fut = this._fut();
    const allit = (sel, v) => { const el = r.querySelector(sel); el.hidden = v === null; if (v !== null) el.querySelector("span").textContent = fok(v); };
    allit(".bent", bent);
    allit(".kint", kint);
    r.querySelector(".fust").classList.toggle("fut", fut);
    r.querySelector(".bent").classList.toggle("fut", fut);
    const b = r.querySelector(".bent");
    b.title = `Bent ${bent !== null ? fok(bent) : ""}${c.futes ? fut ? " · fűtés: fűt" : " · fűtés: nem fűt" : ""}`;
  }

  _reszletek(e, id) {
    // A hőmérsékletre koppintva az entitás részletei (a kártya többi része a panelt nyitja).
    if (!id) return;
    e.stopPropagation();
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId: id } }));
  }

  connectedCallback() {
    // A panelről visszatérve friss adat (pl. közben rögzített fizetés).
    if (this._hass && Date.now() - this._lekerve > 15000) this._lekeres();
  }

  async _lekeres() {
    this._lekerve = Date.now();
    verzioEllenor().then((uj) => { if (uj && document.visibilityState !== "visible") ujratoltHaKell(); });
    try {
      const adat = await this._hass.callWS({ type: "hu_rezsi/kartya" });
      this._hiba = null;
      clearTimeout(this._ujra);
      if (adat.kesz === false) {
        // Újraindítás után az integráció még számol (a fizetések még nincsenek beolvasva): rövidesen újra.
        this._ujra = setTimeout(() => this._lekeres(), 15000);
        if (!this._adat) { this._render(); return; }
        return;
      }
      this._adat = adat;
    } catch (e) {
      this._hiba = e?.message || "A Rezsikövető adatai nem érhetők el.";
    }
    this._render();
  }

  _otthonKulcs() {
    if (this._config?.otthon) return this._config.otthon;
    try { return localStorage.getItem("hu_rezsi_otthon"); } catch (e) { return null; }
  }

  _otthon() {
    const hazak = this._adat?.haztartasok || [];
    const k = this._otthonKulcs();
    return hazak.find((h) => h.entry_id === k || h.nev === k) || hazak[0];
  }

  _render() {
    if (!this._config) return;
    this._kulcs = this._otthonKulcs();
    const h = this._otthon();
    const fiokok = (h?.fiokok || []).filter((f) => f.nyitott_ft > 0 || f.varhato_ft > 0 || !f.megszunt);
    // Tételek: kifizetetlen számla, vagy esedékes, de még nem számlázott összeg (sárga dőlt, mint a panelen).
    const nyitott = fiokok.filter((f) => f.nyitott_ft > 0 || f.varhato_ft > 0)
      // előbb a kiállított (kifizetetlen) számlák, utána a csak becsült (még nem számlázott) tételek
      .sort((a, b) => (b.nyitott_ft > 0) - (a.nyitott_ft > 0) || (b.nyitott_ft + (b.varhato_ft || 0)) - (a.nyitott_ft + (a.varhato_ft || 0)));
    const osszeg = nyitott.reduce((s, f) => s + f.nyitott_ft, 0);
    const varhato = nyitott.reduce((s, f) => s + (f.varhato_ft || 0), 0);
    const lejart = nyitott.reduce((s, f) => s + f.lejart_ft, 0);
    const hatarido = nyitott.map((f) => f.hatarido).filter(Boolean).sort()[0];
    const tobb = nyitott.length > MAX_TETEL ? nyitott.length - (MAX_TETEL - 1) : 0;
    const tetelek = tobb ? nyitott.slice(0, MAX_TETEL - 1) : nyitott;
    const tetelHtml = (f) => {
      const cim = [f.nyitott_ft ? `${f.nyitott_db} kifizetetlen számla${f.lejart_ft ? `, ebből lejárt ${ft(f.lejart_ft)}` : ""}` : "",
        f.varhato_ft ? `~${ft(f.varhato_ft)} esedékes, még nem számlázva` : ""].filter(Boolean).join("; ");
      return `<div class="tetel${f.lejart_ft ? " lejart" : ""}${f.nyitott_ft ? "" : " csakvarh"}" title="${esc(f.nev)}: ${cim}">
        <ha-icon icon="${IKON[f.kozmu] || "mdi:cash"}"></ha-icon><span class="tert">${f.nyitott_ft ? `<span>${ft(f.nyitott_ft)}</span>` : ""}${f.varhato_ft ? `<span class="tvarh">~${ft(f.varhato_ft)}</span>` : ""}</span></div>`;
    };

    let belso;
    if (this._hiba) belso = `<div class="cimke">Rezsikövető</div><div class="uzenet">${esc(this._hiba)}</div>`;
    else if (!this._adat) belso = `<div class="cimke">Rezsikövető</div><div class="uzenet">Betöltés…</div>`;
    else if (!h) belso = `<div class="cimke">Rezsikövető</div><div class="uzenet">Még nincs otthon felvéve.</div>`;
    else if (!osszeg && !varhato) {
      belso = `<div class="cimke">Fizetendő</div><div class="osszeg nulla">0 Ft</div>
        <div class="rendben"><ha-icon icon="mdi:check-circle-outline"></ha-icon>Minden számla rendezve</div>
        <div class="ikonsor">${fiokok.map((f) => `<ha-icon class="halvany" icon="${IKON[f.kozmu] || "mdi:cash"}" title="${esc(f.nev)}"></ha-icon>`).join("")}</div>`;
    } else {
      belso = `<div class="cimke">Fizetendő</div><div class="osszeg${lejart ? " lejart" : osszeg ? "" : " nulla"}">${ft(osszeg)}</div>
        <div class="tetelek${tetelek.length + (tobb ? 1 : 0) === 1 ? " egy" : ""}">${tetelek.map(tetelHtml).join("")}
          ${tobb ? `<div class="tetel" title="${esc(nyitott.slice(MAX_TETEL - 1).map((f) => f.nev).join(", "))}"><ha-icon icon="mdi:dots-horizontal"></ha-icon><span>+${tobb} fiók</span></div>` : ""}</div>`;
    }
    // Mérőállások – csak a szenzoros csatornák; ha egy sincs: „Nincsenek szenzorok”.
    this._allasFiokok = (h?.fiokok || []).filter((f) => !f.megszunt && f.allasok?.length);
    const allasSorok = this._allasFiokok.flatMap((f, fi) => f.allasok.map((a, ai) => `<div class="allas${a.becsult ? " becsult" : ""}" data-i="${fi}.${ai}" data-id="${esc(a.entity_id)}"
      title="${esc(f.nev)}${REGISZTER[a.szerep] ? ` – ${REGISZTER[a.szerep]}` : ""}${a.becsult ? " (becsült – régi adat)" : ""}"><ha-icon icon="${IKON[f.kozmu] || "mdi:counter"}" style="color:${MERO_SZIN[f.kozmu] || "var(--state-icon-color)"}"></ha-icon><span class="ajel">${esc(allasJel(f, a))}</span><span class="aert">${allasSzam(a.allas, f.egyseg)}</span></div>`));
    const allasBlokk = !h || this._hiba || !this._adat ? "" : `<div class="allasok${allasSorok.length > 4 ? " sok" : ""}"><div class="acim">Mérőállások</div>${allasSorok.length ? allasSorok.join("") : '<div class="anincs">Nincsenek szenzorok</div>'}</div>`;
    const lab = !h || this._hiba ? "" : osszeg
      ? lejart ? `<span class="lejart">Lejárt: ${ft(lejart)}</span>${hatarido ? ` · következő határidő ${nap(hatarido)}` : ""}`
        : hatarido ? `Határidő: ${nap(hatarido)}` : ""
      : "";

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { cursor: pointer; overflow: hidden; padding: 12px 12px 10px; height: 100%; box-sizing: border-box; }
        ha-card:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
        .haz { position: relative; container-type: inline-size; aspect-ratio: 320 / 237; max-width: 340px; margin: 0 auto; }
        svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
        path { fill: none; stroke: var(--primary-text-color); stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; opacity: .85; }
        path.rajzol { stroke-dasharray: 1; stroke-dashoffset: 1; animation: rajz 1.6s ease-out forwards; }
        @keyframes rajz { to { stroke-dashoffset: 0; } }
        @media (prefers-reduced-motion: reduce) { path.rajzol { animation: none; stroke-dashoffset: 0; } }
        /* A ház belseje: a tető alatti sávtól a padlóig (viewBox 8–245: falak 46–226, eresz 125, padló 230; a ház balra tolva); a benti hőmérséklet fent, a tetőtérben. */
        .belso { position: absolute; left: 15.5%; right: 30.5%; top: 31.4%; bottom: 9%; display: flex; flex-direction: column;
          align-items: center; justify-content: flex-start; text-align: center; color: var(--primary-text-color); }
        .cimke { font-size: 4.2cqw; color: var(--secondary-text-color); letter-spacing: .02em; }
        .osszeg { font-size: 8cqw; font-weight: 600; line-height: 1.12; white-space: nowrap; margin-bottom: 1.8cqw; }
        .osszeg.nulla { color: var(--success-color, #43a047); }
        .lejart { color: var(--error-color, #db4437); }
        .tetelek { display: grid; grid-template-columns: 1fr 1fr; gap: 1cqw 2.4cqw; width: 100%; }
        .tetelek.egy { grid-template-columns: 1fr; justify-items: center; }
        .tetel { display: flex; align-items: center; gap: 1cqw; font-size: 3.7cqw; white-space: nowrap; min-width: 0; }
        .tetel span { overflow: hidden; text-overflow: ellipsis; }
        .tert { display: flex; flex-direction: column; line-height: 1.15; min-width: 0; }
        .tvarh { color: var(--rezsi-varhato, #c76a00); font-style: italic; }
        .tvarh { font-size: .88em; }

        .tetel ha-icon, .ikonsor ha-icon, .rendben ha-icon { --mdc-icon-size: 5.4cqw; flex: none; }
        .tetel ha-icon { color: var(--state-icon-color, var(--primary-color)); }
        .tetel.lejart ha-icon { color: var(--error-color, #db4437); }
        .rendben { display: flex; align-items: center; gap: 1cqw; font-size: 3.7cqw; color: var(--secondary-text-color); margin-bottom: 2cqw; }
        .rendben ha-icon { color: var(--success-color, #43a047); }
        .ikonsor { display: flex; flex-wrap: wrap; justify-content: center; gap: 1.6cqw; }
        .halvany { opacity: .45; }
        .bent, .kint { position: absolute; display: flex; align-items: center; gap: .8cqw; font-size: 4cqw; white-space: nowrap;
          color: var(--primary-text-color); cursor: pointer; }
        .bent[hidden], .kint[hidden] { display: none; }
        .bent { left: 22.5%; right: 37.5%; top: 21%; justify-content: center; }
        .kint { right: 1%; top: 3%; color: var(--secondary-text-color); }
        .allasokkal .kint { top: 60%; }
        .bent ha-icon, .kint ha-icon { --mdc-icon-size: 5cqw; }
        .bent ha-icon { color: var(--secondary-text-color); }
        .bent.fut ha-icon { color: var(--state-climate-heat-color, #ff8100); }
        .pamacs { fill: none; stroke: var(--primary-text-color); stroke-width: 1.6; opacity: 0; transform-box: fill-box; transform-origin: center; }
        .fust.fut .pamacs { animation: fust 3s ease-out infinite; }
        @keyframes fust { 0% { transform: translate(0, 0) scale(.35); opacity: 0; } 15% { opacity: .75; }
          100% { transform: translate(18px, -40px) scale(1.7); opacity: 0; } }
        @media (prefers-reduced-motion: reduce) { .fust.fut .pamacs { animation: none; opacity: .35; }
          .fust.fut .pamacs:nth-child(2) { transform: translate(7px, -16px) scale(1.1); } .fust.fut .pamacs:nth-child(3) { transform: translate(14px, -32px) scale(1.5); } }
        /* Mérőállások: a jobb felső sarokban, a tető jobb lejtője fölött (a bal oldalon a kémény és a füst van; a tető
           vonala a szélesség 70%-ánál a magasság ~34%-án) – a kinti hőmérséklet ilyenkor a jobb fal mellé kerül. */
        .allasok { position: absolute; right: 0; top: 1%; max-width: 36%; display: grid; gap: .4cqw; font-size: 3cqw; line-height: 1.15; color: var(--primary-text-color); }
        .allasok.sok { font-size: 2.6cqw; gap: .1cqw; }
        .acim { text-align: right; }
        .acim { font-size: .82em; letter-spacing: .06em; text-transform: uppercase; color: var(--secondary-text-color); margin-bottom: .3cqw; }
        .allas { display: grid; grid-template-columns: auto auto 1fr; align-items: center; gap: 1cqw; white-space: nowrap; cursor: pointer; }
        .allas ha-icon { --mdc-icon-size: 1.25em; color: var(--state-icon-color, var(--primary-color)); }
        .ajel { color: var(--secondary-text-color); font-size: .9em; }
        .aert { font-variant-numeric: tabular-nums; text-align: right; }
        .allas.becsult .aert { font-style: italic; color: var(--secondary-text-color); }
        .anincs { color: var(--secondary-text-color); font-style: italic; }
        .uzenet { font-size: 3.8cqw; color: var(--secondary-text-color); margin-top: 3cqw; }
        .lab { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 2px 8px; align-items: baseline; margin-top: 4px; }
        .nev { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
        .info { flex: 1 1 auto; font-size: .85em; color: var(--secondary-text-color); text-align: right; }
        .lab { align-items: center; }
        .aigomb { display: inline-flex; align-items: center; gap: 3px; font: inherit; font-size: .82em; font-weight: 500; cursor: pointer;
          border: 1px solid var(--divider-color); border-radius: 14px; padding: 2px 9px 2px 6px; background: none; color: var(--primary-color); }
        .aigomb ha-icon { --mdc-icon-size: 16px; }
      </style>
      <ha-card tabindex="0" role="link" aria-label="Rezsikövető megnyitása${h ? ` – ${esc(h.nev)}` : ""}">
        <div class="haz${allasBlokk ? " allasokkal" : ""}">
          <svg viewBox="0 8 320 237" aria-hidden="true"><g class="fust">${FUST}</g><path class="${this._rajzolt ? "" : "rajzol"}" pathLength="1" d="${HAZ}"/></svg>
          <div class="belso">${belso}</div>
          ${allasBlokk}
          <div class="bent" hidden><ha-icon icon="mdi:home-thermometer-outline"></ha-icon><span></span></div>
          <div class="kint" hidden title="Kint"><ha-icon icon="mdi:thermometer"></ha-icon><span></span></div>
        </div>
        <div class="lab"><span class="nev">${esc(this._config.cim || h?.nev || "Rezsikövető")}</span><span class="info">${lab}</span>${this._config.ai_tajekoztato && h && !this._hiba ? `<button class="aigomb" title="AI-tájékoztató a számlákról és a kilátásokról (kísérleti)" aria-label="AI-tájékoztató"><ha-icon icon="mdi:creation-outline"></ha-icon>AI</button>` : ""}</div>
      </ha-card>`;
    if (this._adat) this._rajzolt = true;
    const kartya = this.shadowRoot.querySelector("ha-card");
    kartya.addEventListener("click", () => this._megnyit());
    this.shadowRoot.querySelector(".aigomb")?.addEventListener("click", (e) => {
      e.stopPropagation();
      const ablak = document.createElement("rezsi-ai-ablak");
      ablak.nyit(this._hass, h.entry_id, this._config.ai_entitas, h.nev);
    });
    this.shadowRoot.querySelectorAll(".allas[data-id]").forEach((el) => el.addEventListener("click", (e) => this._reszletek(e, el.dataset.id)));
    this.shadowRoot.querySelector(".bent").addEventListener("click", (e) => this._reszletek(e, this._futes().belso_homerseklet || this._futes().futes));
    this.shadowRoot.querySelector(".kint").addEventListener("click", (e) => this._reszletek(e, this._futes().kulso_homerseklet));
    this._allapot();
    kartya.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this._megnyit(); } });
  }

  _megnyit() {
    history.pushState(null, "", "/rezsi");
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  getCardSize() { return 5; }

  getGridOptions() { return { columns: 6, min_columns: 4, rows: 5, min_rows: 4 }; }

  static getConfigForm() {
    return {
      schema: [
        { name: "cim", selector: { text: {} } },
        { name: "otthon", selector: { text: {} } },
        { name: "ai_tajekoztato", selector: { boolean: {} } },
        { name: "ai_entitas", selector: { entity: { domain: "ai_task" } } },
      ],
      computeLabel: (s) => ({ cim: "Felirat (üresen: az otthon neve)", otthon: "Otthon neve (üresen: a panelen utoljára választott)",
        ai_tajekoztato: "AI-tájékoztató gomb (kísérleti)", ai_entitas: "AI Task entitás (üresen: az első elérhető)" })[s.name],
      computeHelper: (s) => (s.name === "otthon" ? "A fűtés és a hőmérséklet otthononként: Beállítások → Eszközök és szolgáltatások → Rezsikövető → az otthon Konfigurálás gombja." : undefined),
    };
  }

  static getStubConfig() { return {}; }
}

// Regisztráció csak a HA felületének indulása után: a HA a saját (scoped) elem-nyilvántartására cseréli a böngészőét
// (window.customElements). Ha a kártya ez előtt definiálódik (az extra modul korán fut), a régi nyilvántartásba kerül,
// amit a HA már nem lát – „Konfigurációs hiba”. Ezért megvárjuk, hogy a home-assistant elem a mostani nyilvántartásban
// legyen, és mindig az akkori window.customElements-be definiálunk.
function regisztral() {
  // __huRezsiKartyaAzonnal: HA-felület nélküli oldal (demó) – nincs mire várni.
  if (!window.customElements.get("home-assistant") && !window.__huRezsiKartyaAzonnal) return false;
  if (!window.customElements.get("rezsikoveto-kartya")) window.customElements.define("rezsikoveto-kartya", RezsikovetoKartya);
  if (!window.customElements.get("rezsi-ai-ablak")) window.customElements.define("rezsi-ai-ablak", RezsiAiAblak);
  window.customCards = window.customCards || [];
  if (!window.customCards.some((x) => x.type === "rezsikoveto-kartya")) {
    window.customCards.push({
      type: "rezsikoveto-kartya",
      name: "Rezsikövető",
      description: "Az otthon kifizetetlen számláinak összege egy vonalas házban; koppintásra a Rezsikövető panel nyílik.",
      preview: true,
      documentationURL: "https://github.com/Gyuszko55/ha-energia-elszamolas-hu",
    });
  }
  return true;
}
if (!regisztral()) {
  const t0 = Date.now();
  const varo = setInterval(() => {
    // Ha 60 s alatt sincs home-assistant elem (pl. nem a HA felületén – demó), definiálunk így is.
    if (regisztral() || Date.now() - t0 > 60000) {
      clearInterval(varo);
      if (!window.customElements.get("rezsikoveto-kartya")) window.customElements.define("rezsikoveto-kartya", RezsikovetoKartya);
      if (!window.customElements.get("rezsi-ai-ablak")) window.customElements.define("rezsi-ai-ablak", RezsiAiAblak);
    }
  }, 50);
}
