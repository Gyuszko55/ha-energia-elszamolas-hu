// Rezsikövető – oldalsáv-panel (Home Assistant). Build nélküli webkomponens.
// Adat: websocket `hu_rezsi/adatok`; leolvasás: `hu_rezsi.leolvasas_rogzites` szolgáltatás.
// Szemlélet: Mennyibe került? → Mennyi lesz? → Hol tartok a keretben? → Kell-e valamin változtatnom?

const FT = new Intl.NumberFormat("hu-HU", { maximumFractionDigits: 0 });
// Várható (még nem érkezett) számla forrása – a számlakimutatásban.
const FORRAS_NEV = { meres: "saját mérés", diktalas: "diktált állás", atalany: "átalány", fix: "fix díj", elszamolas: "várható elszámolás" };
const SZAM = new Intl.NumberFormat("hu-HU", { maximumFractionDigits: 1 });
const SZAM3 = new Intl.NumberFormat("hu-HU", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const ft = (x) => (x === null || x === undefined ? "–" : `${FT.format(x)} Ft`);
const TUZHELY = { "2_langu": "2 lángú tűzhely", "3_4_langu": "3–4 lángú tűzhely", "4_langu_elektromos_sutovel": "4 lángú tűzhely elektromos sütővel", "5_langu": "5+ lángú tűzhely", garzon: "garzon gáztűzhely" };
const honapNev = (x) => (x ? new Date(x).toLocaleDateString("hu-HU", { year: "numeric", month: "long" }) : "–");
const meret = (b) => (b == null ? "–" : b >= 1048576 ? `${(b / 1048576).toLocaleString("hu-HU", { maximumFractionDigits: 1 })} MB` : `${Math.max(1, Math.round(b / 1024))} kB`);
const szam = (x, e = "") => (x === null || x === undefined ? "–" : `${SZAM.format(x)}${e ? " " + e : ""}`);
// Mérőállás: mindig egész szám (a szenzor szerinti is) – ahogy az óra számlálója mutatja (a tört rész elhagyva),
// egyezik az indítókártyával.
// Több regiszteres mérő (H-tarifa téli/nyári, A2 csúcs/völgy): a fogyasztás regiszterenként (a folyó időszak szeletei).
const REG_NEV = { h_teli: "téli", h_nyari: "nyári", zona_csucs: "csúcs", zona_volgy: "völgy" };
const regiszterBontas = (f) => {
  const ossz = {};
  for (const s of f.eddig?.szeletek || []) if (REG_NEV[s.csatorna]) ossz[s.csatorna] = (ossz[s.csatorna] || 0) + (s.mennyiseg || 0);
  const k = Object.keys(ossz);
  return k.length > 1 ? k.map((c) => `${REG_NEV[c]} ${SZAM.format(Math.round(ossz[c] * 10) / 10)}`).join(" · ") + (f.egyseg && f.egyseg !== "db" ? ` ${f.egyseg}` : "") : "";
};
const allas = (x, e = "") => (x === null || x === undefined || x === "" || isNaN(Number(x)) ? "–" : szam(Math.floor(Number(x) + 1e-9), e));
const HONAP = ["jan.", "febr.", "márc.", "ápr.", "máj.", "jún.", "júl.", "aug.", "szept.", "okt.", "nov.", "dec."];
const nap = (iso) => {
  if (!iso) return "–";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${y}. ${HONAP[m - 1]} ${d}.`;
};
const kovNap = (iso) => {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
};
// Diktálásos/átalányos villanynál a határ a diktálás napja: a számla szerint „előző diktálás másnapja – diktálás napja”.
const idoszakSzoveg = (tol, ig, diktalasos) =>
  diktalasos ? `${nap(kovNap(tol))} – ${nap(ig)}` : `${nap(tol)} – ${nap(elozoNap(ig))}`;
// A következő diktálási ablak szövege (pl. „okt. 8–14.”): ebben a hónapban, ha még nem múlt el, különben a következőben.
const kovDiktalas = (a, ig = null, ma = new Date()) => {
  // Diktálásos fióknál az az ablak, amelyik a folyó időszakot zárja (az időszak vége); különben a legközelebbi.
  let m = ma.getMonth();
  if (ig) m = Number(ig.slice(5, 7)) - 1;
  else if (ma.getDate() > a[1]) m = (m + 1) % 12;
  return `${HONAP[m]} ${a[0]}–${a[1]}.`;
};
// A fejléc időszakai: az idei évszám nélkül (pl. „szept. 30. – nov. 11.”).
const fejNap = (iso) => (!iso ? "–" : iso.slice(0, 4) === String(new Date().getFullYear()) ? nap(iso).slice(6) : nap(iso));
const fejIdoszak = (tol, ig, diktalasos) =>
  diktalasos ? `${fejNap(kovNap(tol))} – ${fejNap(ig)}` : `${fejNap(tol)} – ${fejNap(elozoNap(ig))}`;
const rovidNap = (iso) => (iso ? `${iso.slice(0, 10).replaceAll("-", ".")}.` : "–");
const elozoNap = (iso) => {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
};
// ⓘ gomb: a magyarázat buborékban (helytakarékos). A szöveg HTML (csak saját, számított adat kerül bele).
const info = (html) =>
  `<button type="button" class="info" aria-label="Magyarázat" data-info="${esc(html)}"><ha-icon icon="mdi:information-outline"></ha-icon></button>`;
const elojelFt = (x) => (x === null || x === undefined ? "–" : `<span class="${x < 0 ? "minusz" : x > 0 ? "plusz" : ""}">${x < 0 ? "−" : x > 0 ? "+" : ""}${ft(Math.abs(x))}</span>`);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const IKON = { villany: "mdi:flash", gaz: "mdi:fire", viz: "mdi:water", tavho: "mdi:radiator", hulladek: "mdi:trash-can-outline", kozos: "mdi:office-building-outline", tavkozles: "mdi:router-wireless" };
const KOZMU = { villany: "Villany", gaz: "Gáz", viz: "Víz", tavho: "Távhő", hulladek: "Hulladékszállítás", kozos: "Közös költség", tavkozles: "Internet, TV, telefon" };
const TOBBHAVI = { 2: "Kéthavi", 3: "Negyedéves", 4: "Négyhavi", 6: "Félévi", 12: "Éves" };
const CSAT = { vetelezes: "", h_teli: "H téli", h_nyari: "H nyári", zona_csucs: "A2 csúcs", zona_volgy: "A2 völgy", almero: "almérő", betaplalas: "betáplálás" };
const ELSZ_MOD = { diktalas: "diktálás", atalany: "átalány", tavleolvasas: "távleolvasás" };
const UTEM = { 1: "havonta", 2: "kéthavonta", 3: "negyedévente", 4: "négyhavonta", 6: "félévente", 12: "évente" };

// Automatikus bezárás: a csak megjelenítő ablakok (és a fiókkártya lenyitott Részletek része) ennyi másodperc
// tétlenség után bezárulnak (panel-beállítás: hu_rezsi/panel_beallitas, alapból 10, 0 = soha). Az űrlapos ablakok
// (mérőállás, számla, törlés, javítás, lezárás, mentés és beállítások, szenzor-hozzárendelés, e-mail varázsló) soha;
// ha ezek közül bármelyik nyitva van (pl. egy megjelenítő ablakból nyílt), az időzítés szünetel.
const OLVASO_ABLAKOK = new Set(["grafdlg", "reklamdlg", "evesdlg", "teteldlg", "kimutdlg", "fszdlg", "ddlg", "beallit"]);
const AKTIVITAS = ["pointerdown", "pointermove", "wheel", "scroll", "keydown", "touchstart", "touchmove"];
const SZERK_MEZO = "input:not([type=checkbox]):not([type=radio]):not([type=button]), textarea";

class HuRezsiPanel extends HTMLElement {
  // Rendszergazda? A nem rendszergazda mindent lát, de csak mérőállást és fizetést rögzíthet (a szerver is ezt engedi).
  get _admin() { return !!this._hass?.user?.is_admin; }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._adat = null;
    this._nyitva = new Set();
    this._jelolt = new Set(); // törlésre kijelölt számlák: "sid|sorszám"
    // Több otthonnál fülek: a kiválasztott otthon (böngészőnként megjegyezve; tárolás nélkül is működik).
    try { this._aktivHaz = localStorage.getItem("hu_rezsi_otthon"); } catch (e) { this._aktivHaz = null; }
    // Tablet/notebook nézet (2.3.0b3): eszközönként megjegyezve – „auto” (900 px felett tablet), „mobil”, „tablet”;
    // a tabletnézeten belül „fiok” (fiókonkénti lapok) vagy „tema” (témánkénti táblázatok); a kiválasztott lap otthononként.
    try {
      this._nezetBeall = localStorage.getItem("hu_rezsi_nezet") || "auto";
      this._tabletMod = localStorage.getItem("hu_rezsi_tablet_mod") || "fiok";
      this._lap = JSON.parse(localStorage.getItem("hu_rezsi_lap") || "{}") || {};
    } catch (e) { this._nezetBeall = "auto"; this._tabletMod = "fiok"; this._lap = {}; }
    this._hiba = null;
    // Automatikus bezárás: tétlenség mérése (a görgetés az ablakok belsejében is – a shadow-gyökéren elkapva).
    this._aktiv = Date.now();
    this._jel = () => { this._aktiv = Date.now(); };
    for (const t of AKTIVITAS) this.shadowRoot.addEventListener(t, this._jel, { capture: true, passive: true });
    // Megjelenítő ablakban beírt / módosított mező (pl. a folyószámla kézi tétele): az ablak már nem zárul magától.
    this.shadowRoot.addEventListener("input", (ev) => {
      const d = ev.target.closest?.("dialog");
      if (d && ev.target.matches?.(SZERK_MEZO)) d.dataset.szerkesztett = "1";
    }, true);
    this.shadowRoot.addEventListener("close", (ev) => {
      if (ev.target.localName === "dialog") { delete ev.target.dataset.szerkesztett; this._aktiv = Date.now(); }
      // Nyitott ablak alatt elhalasztott újrarajzolás (méretváltás, korrekció visszajelzése) – a bezárás után.
      if (this._rajzolVar) setTimeout(() => {
        if (this._rajzolVar && !this.shadowRoot.querySelector("dialog[open]")) { this._rajzolVar = false; this._rajzol(); }
      }, 0);
    }, true);
    // ⓘ buborék: egy közös elem, kattintásra a gomb alatt; máshova kattintva / görgetéskor bezárul.
    this._nyitottSzamla = new Set();
    // Számla-sor: koppintásra lenyílnak a részletei (a kijelölő négyzet nem nyit).
    this.shadowRoot.addEventListener("click", (ev) => {
      const ut = ev.composedPath();
      if (ut.some((el) => el.classList?.contains("jelol") || el.classList?.contains("fizmezo") || el.dataset?.javit)) return;
      // A lenyílt részletekre koppintva is bezárul.
      const reszletSor = ut.find((el) => el.classList?.contains("szreszlet"));
      const sor = reszletSor ? reszletSor.previousElementSibling : ut.find((el) => el.classList?.contains("szsor"));
      if (!sor) return;
      const k = sor.dataset.szamlasor, reszlet = sor.nextElementSibling;
      const nyit = reszlet.hidden;
      reszlet.hidden = !nyit;
      sor.querySelector(".nyil").setAttribute("icon", nyit ? "mdi:chevron-down" : "mdi:chevron-right");
      if (nyit) this._nyitottSzamla.add(k); else this._nyitottSzamla.delete(k);
    });
    this.shadowRoot.addEventListener("click", (ev) => {
      // csak a ⓘ gomb (data-info) – a figyelmeztetés-sor <li class="info"> nem buborék
      const gomb = ev.composedPath().find((el) => el.classList?.contains("info") && el.dataset?.info !== undefined);
      if (gomb) {
        ev.stopPropagation();
        this._buborek(gomb);
      } else this._buborek(null);
    });
    window.addEventListener("scroll", () => this._buborek(null), { passive: true, capture: true });
    // Szélességváltáskor (forgatás, ablakméret) a két sornál hosszabb magyarázatok újramérése.
    let szelesseg = window.innerWidth, idozito;
    window.addEventListener("resize", () => {
      if (window.innerWidth === szelesseg) return;
      szelesseg = window.innerWidth;
      clearTimeout(idozito);
      idozito = setTimeout(() => this._hosszuMagyarazat(), 250);
    }, { passive: true });
    // A betöltő miatt a HA az elemet a definíció előtt is létrehozhatja, és a hass/narrow/panel értéket már
    // beállíthatta rá sima tulajdonságként – ezek eltakarnák a beállítókat. Átvesszük őket a beállítókon át.
    queueMicrotask(() => {
      for (const kulcs of ["narrow", "panel", "route", "hass"]) {
        if (Object.prototype.hasOwnProperty.call(this, kulcs)) {
          const ertek = this[kulcs];
          delete this[kulcs];
          this[kulcs] = ertek;
        }
      }
    });
  }

  _buborek(gomb) {
    const b = this.shadowRoot.getElementById("buborek");
    if (!b) return;
    const regi = this.shadowRoot.querySelector("button.info.aktiv");
    if (regi) regi.classList.remove("aktiv");
    if (!gomb || gomb === regi) {
      b.hidden = true;
      return;
    }
    gomb.classList.add("aktiv");
    b.innerHTML = gomb.dataset.info;
    b.hidden = false;
    const r = gomb.getBoundingClientRect();
    const sz = b.offsetWidth, m = b.offsetHeight;
    b.style.left = `${Math.max(12, Math.min(r.left + r.width / 2 - sz / 2, window.innerWidth - sz - 12))}px`;
    b.style.top = `${r.bottom + 6 + m > window.innerHeight ? Math.max(12, r.top - m - 6) : r.bottom + 6}px`;
  }

  set hass(hass) {
    const elso = !this._hass;
    this._hass = hass;
    const mb = this.shadowRoot.querySelector("ha-menu-button");
    if (mb) mb.hass = hass;
    // A Mérők lap „Saját szenzor szerint most” cellái élőben (a panel többi része nem rajzolódik újra).
    for (const el of this.shadowRoot.querySelectorAll(".szelo")) {
      const v = Number(hass.states?.[el.dataset.eid]?.state), alap = el.dataset.alap === "" ? null : Number(el.dataset.alap);
      const ertek = alap == null || isNaN(v) || v < alap ? Number(el.dataset.allas) : Number(el.dataset.allas) + Number(el.dataset.szorzo) * (v - alap);
      const uj = allas(ertek, el.dataset.egys);
      if (el.textContent !== uj) el.textContent = uj;
    }
    if (elso) {
      this._betolt();
      // Nyitott párbeszédablak alatt nincs újrarajzolás (eltüntetné az ablakot).
      this._idozito = setInterval(() => !this._szerkesztesAlatt() && this._betolt(), 60000);
      // Ha az alkalmazás a háttérből visszatér, és közben új panelváltozat került fel, újratölt (nyitott ablak alatt nem).
      this._lathato = () => document.visibilityState === "visible" && !this.shadowRoot.querySelector("dialog[open]") && this._frissit();
      document.addEventListener("visibilitychange", this._lathato);
    }
  }

  set narrow(v) {
    this._narrow = v;
    const mb = this.shadowRoot.querySelector("ha-menu-button");
    if (mb) mb.narrow = v;
  }

  connectedCallback() {
    for (const t of AKTIVITAS) window.addEventListener(t, this._jel, { capture: true, passive: true });
    // Szélességváltáskor (pl. a tablet elforgatása) a nézet magától vált mobil és tablet között.
    this._meretFigyelo ??= new ResizeObserver(() => {
      if (!this._adat || this._nezetMod() === this._utolsoMod) return;
      if (this._szerkesztesAlatt()) this._rajzolVar = true;  // nyitott ablak / szerkesztés alatt: bezáráskor
      else this._rajzol();
    });
    this._meretFigyelo.observe(this);
    clearInterval(this._autoIdo);
    this._aktiv = Date.now();
    this._autoIdo = setInterval(() => this._autoBezaras(), 1000);
  }

  // A beállított mp (a panel adataiból; amíg nincs adat, az alapérték).
  get _autoMp() {
    const v = this._adat?.panel_beallitas?.auto_bezaras_mp;
    return v == null ? 10 : Number(v) || 0;
  }

  _autoBezaras() {
    const mp = this._autoMp;
    if (!mp) return;
    if (document.visibilityState !== "visible") { this._aktiv = Date.now(); return; } // rejtett lapnál szünetel
    if (Date.now() - this._aktiv < mp * 1000) return;
    const r = this.shadowRoot;
    const nyitott = [...r.querySelectorAll("dialog[open]")];
    const fokusz = r.activeElement;
    if (nyitott.length) {
      if (nyitott.some((d) => !OLVASO_ABLAKOK.has(d.id))) return; // űrlap nyitva (akár egy megjelenítőből nyílt)
      const d = nyitott[nyitott.length - 1];
      if (d.dataset.szerkesztett || (fokusz && d.contains(fokusz) && fokusz.matches(SZERK_MEZO)) || d.querySelector("#fszkeziszerk")) return;
      d.close();
      this._aktiv = Date.now();
      return;
    }
    // A fiókkártya lenyitott Részletek része – kivéve, ha számla van kijelölve, menü nyitva vagy mezőben gépelnek.
    if (this._nyitva.size && !this._jelolt.size && !this._menuSid && !(fokusz && fokusz.matches(SZERK_MEZO))) {
      this._nyitva.clear();
      this._aktiv = Date.now();
      this._rajzol();
    }
  }

  disconnectedCallback() {
    this._meretFigyelo?.disconnect();
    clearInterval(this._autoIdo);
    clearTimeout(this._emailFigyIdo);
    this._emailFigyIdo = null;
    for (const t of AKTIVITAS) window.removeEventListener(t, this._jel, { capture: true });
    clearInterval(this._idozito);
    if (this._lathato) document.removeEventListener("visibilitychange", this._lathato);
  }

  // Frissítés gomb: ha közben új panelváltozat került fel (fejlesztés), az oldal újratölt – különben az adatok.
  async _frissit() {
    const p = window.huRezsiPanel;
    if (p && (await p.ujVerzio()) !== p.verzio) {
      location.reload();
      return;
    }
    this._betolt();
  }

  // Szerkesztés közben (fókuszban lévő mező, nyitott ablak) nem rajzolunk újra – különben elveszne, amit épp írsz.
  _szerkesztesAlatt() {
    const a = this.shadowRoot.activeElement;
    return !!(this.shadowRoot.querySelector("dialog[open]") || (a && a.matches("input:not([type=checkbox]), textarea, select")));
  }

  // Módosítás után: újratöltés pár másodperc múlva (a háttérszámolás végére), több gyors módosításból egy.
  _kesoBetolt(ms = 2500) {
    clearTimeout(this._kesoIdozito);
    this._kesoIdozito = setTimeout(() => (this._szerkesztesAlatt() ? this._kesoBetolt(2000) : this._betolt()), ms);
  }

  // Egy számla fizetés-állapota helyben (a panel adataiban és a sorában), újrarajzolás nélkül.
  _helyiFizetes(sid, sorszam, valt) {
    const hs = Array.isArray(this._adat) ? this._adat : (this._adat?.otthonok || this._adat?.haztartasok || []);
    const f = hs.flatMap((h) => h.fiokok).find((x) => x.sid === sid);
    const x = f?.szamlak?.find((y) => y.sorszam === sorszam);
    if (!x) return;
    x.fizetes = { ...(x.fizetes || {}), ...valt };
    const sor = this.shadowRoot.querySelector(`tr[data-szamlasor="${CSS.escape(`${sid}|${sorszam}`)}"]`);
    const cella = sor?.lastElementChild;
    if (cella) cella.innerHTML = this._fizetesCella(f, x);
  }

  async _betolt() {
    try {
      this._adat = await this._hass.callWS({ type: "hu_rezsi/adatok" });
      this._hiba = null;
    } catch (e) {
      this._hiba = e.message || String(e);
    }
    this._rajzol();
    if (this._emailFut()) this._emailFigyel();
  }

  // ---------------------------------------------------------------- megjelenítés

  _rajzol() {
    const a = this._adat;
    const fiokok = a ? a.haztartasok.flatMap((h) => h.fiokok) : [];
    this.shadowRoot.innerHTML = `
      <style>${STILUS}</style>
      <div class="fej">
        <ha-menu-button></ha-menu-button>
        <div class="cim">Rezsikövető</div>
        ${this._ertesitesIkon()}
        ${this._hass?.user?.is_admin ? `<button class="ikongomb" id="mentesgomb" title="Beállítások, mentés és visszaállítás"><ha-icon icon="mdi:backup-restore"></ha-icon></button>` : ""}
        <button class="ikongomb" id="frissit" title="Frissítés (új panelváltozatnál újratölt)${window.huRezsiPanel?.verzio ? ` · betöltött változat: ${new Date(window.huRezsiPanel.verzio).toLocaleString("hu-HU")}` : ""}"><ha-icon icon="mdi:refresh"></ha-icon></button>
      </div>
      <div class="tartalom">
        ${this._hiba ? `<div class="hiba">Nem sikerült betölteni: ${esc(this._hiba)}</div>` : ""}
        ${this._sav ? `<div class="banner korrsav" role="status"><div>${this._sav.html}</div><button type="button" class="ikongomb" data-savzar title="Bezárás" aria-label="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></div>` : ""}
        ${!a ? `<div class="toltes">Betöltés…</div>` : a.haztartasok.length === 0 ? `<div class="ures">Nincs beállított Rezsikövető-háztartás.</div>` : ""}
        ${a && a.haztartasok.length > 1 ? this._fulek(a.haztartasok) : ""}
        ${a ? a.haztartasok.filter((h) => h === this._aktivHaztartas(a.haztartasok)).map((h) => ((this._utolsoMod = this._nezetMod()) === "regi" ? this._haztartas(h) : this._haztartasTablet(h))).join("") : ""}
        <div class="labjegyzet">Tájékoztató jellegű számítás, a hivatalos számlát nem helyettesíti.</div>
      </div>
      ${this._dialogus()}
      <div id="buborek" class="buborek" hidden></div>`;
    const mb = this.shadowRoot.querySelector("ha-menu-button");
    if (mb) {
      mb.hass = this._hass;
      mb.narrow = this._narrow;
    }
    this.shadowRoot.getElementById("frissit").addEventListener("click", () => this._frissit());
    this.shadowRoot.getElementById("mentesgomb")?.addEventListener("click", () => this._mentesNyit());
    this.shadowRoot.getElementById("ertesitesgomb")?.addEventListener("click", () => this._mentesNyit("ertesites"));
    this.shadowRoot.querySelectorAll("[data-otthon]").forEach((el) =>
      el.addEventListener("click", () => this._otthonValt(el.dataset.otthon)),
    );
    const fulsor = this.shadowRoot.querySelector(".fulek");
    if (fulsor) fulsor.addEventListener("keydown", (ev) => {
      if (!["ArrowLeft", "ArrowRight"].includes(ev.key)) return;
      const fulek = [...fulsor.querySelectorAll("[data-otthon]")];
      const i = fulek.findIndex((f) => f.getAttribute("aria-selected") === "true");
      const uj = fulek[(i + (ev.key === "ArrowRight" ? 1 : fulek.length - 1)) % fulek.length];
      this._otthonValt(uj.dataset.otthon);
      this.shadowRoot.querySelector(`[data-otthon="${uj.dataset.otthon}"]`)?.focus();
    });
    this.shadowRoot.querySelectorAll("[data-fuggo]").forEach((el) =>
      el.addEventListener("click", async () => {
        if (el.dataset.fuggo === "elvet" && !window.confirm("Elveted ezt a számlát? Nem kerül be a Rezsikövetőbe (később újraolvasható).")) return;
        el.closest(".fuggo")?.querySelectorAll("button").forEach((b) => (b.disabled = true));
        try {
          await this._hass.callWS({ type: "hu_rezsi/fuggo_dontes", entry_id: el.dataset.entry, sid: el.dataset.sid, dontes: el.dataset.fuggo });
        } catch (e) {
          window.alert(`Nem sikerült: ${e.message || e}`);
        }
        this._betolt();
      }),
    );
    this.shadowRoot.querySelectorAll("[data-reszlet]").forEach((el) =>
      el.addEventListener("click", () => {
        const sid = el.dataset.reszlet;
        this._nyitva.has(sid) ? this._nyitva.delete(sid) : this._nyitva.add(sid);
        this._rajzol();
      }),
    );
    this.shadowRoot.querySelectorAll("[data-szamla]").forEach((el) =>
      el.addEventListener("click", () => this._szamlaNyit(fiokok.find((f) => f.sid === el.dataset.szamla))),
    );
    this.shadowRoot.querySelectorAll("input.jelol").forEach((el) =>
      el.addEventListener("change", () => {
        const k = `${el.dataset.fiok}|${el.dataset.sorszam}`;
        el.checked ? this._jelolt.add(k) : this._jelolt.delete(k);
        const f = fiokok.find((x) => x.sid === el.dataset.fiok);
        const sor = this.shadowRoot.querySelector(`[data-torolsor="${f.sid}"]`);
        if (sor) sor.outerHTML = this._torlesGomb(f);
        this._torlesGombKotes(fiokok);
      }),
    );
    this._torlesGombKotes(fiokok);
    this.shadowRoot.querySelectorAll("[data-leolvas]").forEach((el) =>
      el.addEventListener("click", () => this._dialogusNyit(fiokok.find((f) => f.sid === el.dataset.leolvas))),
    );
    this.shadowRoot.querySelectorAll("[data-fszfej]").forEach((el) =>
      el.addEventListener("click", () => this._folyoszamlaNyit(fiokok.find((f) => f.sid === el.dataset.fszfej))),
    );
    this.shadowRoot.querySelectorAll("[data-graf]").forEach((el) =>
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._osszevetesNyit(fiokok.find((f) => f.sid === el.dataset.graf));
      }),
    );
    this.shadowRoot.querySelectorAll("[data-emailatnez]").forEach((el) =>
      el.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        el.disabled = true;
        el.textContent = "Átnézés folyamatban…";
        try {
          const v = await this._hass.callWS({ type: "hu_rezsi/email_atnezes", entry_id: el.dataset.emailatnez });
          const pfk = Object.values(v.otthonok || {}).flatMap((o) => Object.values(o.postafiokok || {}));
          const hibak = pfk.filter((p) => p.hiba);
          if (hibak.length) window.alert(`Nem sikerült átnézni: ${hibak.map((p) => `${p.nev}: ${p.hiba}`).join("\n")}`);
        } catch (e) {
          window.alert(`Nem sikerült: ${e.message || e}`);
        }
        this._betolt();
      }),
    );
    this.shadowRoot.querySelectorAll("[data-emailnyit]").forEach((el) => el.addEventListener("click", () => this._emailNyit(el.dataset.emailnyit)));
    this.shadowRoot.querySelectorAll("[data-emailkeres]").forEach((el) =>
      el.addEventListener("click", async () => {
        const [entry_id, sid] = el.dataset.emailkeres.split("|");
        el.disabled = true;
        el.textContent = "Keresem…";
        try {
          await this._hass.callWS({ type: "hu_rezsi/email_felderites", entry_id, sid });
        } catch (e) {
          window.alert(`Nem sikerült: ${e.message || e}`);
        }
        this._betolt();
        this._emailFigyel();
      }),
    );
    this.shadowRoot.querySelectorAll("[data-emailvalasz]").forEach((el) =>
      el.addEventListener("click", async () => {
        // „azon”, nem „id”: az id a WebSocket-üzenet saját sorszáma, azt a HA felülírná.
        const [entry_id, tipus, azon, ertek] = el.dataset.emailvalasz.split("|");
        el.closest(".emailkartya, .emailuzenet, .emailgombok")?.querySelectorAll("button").forEach((b) => (b.disabled = true));
        try {
          const v = await this._hass.callWS({ type: "hu_rezsi/email_valasz", entry_id, tipus, azon, ertek });
          if (v?.navigal) {
            window.alert("A fiók-varázsló előtöltve vár: a megnyíló oldalon az otthonod ⋮ menüjében válaszd a „Fiók hozzáadása” pontot (a közmű és a szolgáltató már be lesz állítva; a mérő adatait add meg). A számlái ezután maguktól ide jönnek.");
            history.pushState(null, "", v.navigal);
            window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
            return;
          }
        } catch (e) {
          window.alert(`Nem sikerült: ${e.message || e}`);
        }
        this._kesoBetolt(1500);
      }),
    );
    this.shadowRoot.querySelectorAll("[data-kimutatas]").forEach((el) =>
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._kimutatasNyit(el.dataset.kimutatas);
      }),
    );
    this.shadowRoot.querySelectorAll("[data-delemzes]").forEach((el) =>
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._dElemzesNyit(fiokok.find((f) => f.sid === el.dataset.delemzes));
      }),
    );
    this.shadowRoot.querySelectorAll("[data-menu]").forEach((el) =>
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._menuSid = this._menuSid === el.dataset.menu ? null : el.dataset.menu;
        this._rajzol();
      }),
    );
    this.shadowRoot.querySelectorAll("[data-menu-muvelet]").forEach((el) =>
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._menuMuvelet(el.dataset.menuMuvelet, fiokok.find((f) => f.sid === el.dataset.sid));
      }),
    );
    if (this._menuSid) {
      this.shadowRoot.querySelector(".tartalom").addEventListener("click", () => {
        this._menuSid = null;
        this._rajzol();
      }, { once: true });
    }
    this.shadowRoot.querySelectorAll("[data-sajatdij]").forEach((el) =>
      el.addEventListener("click", () => this._sajatDijNyit(fiokok.find((f) => f.sid === el.dataset.sajatdij))),
    );
    const bd = this.shadowRoot.getElementById("beallit");
    this.shadowRoot.getElementById("beallitbezar").addEventListener("click", () => bd.close());
    bd.addEventListener("click", (ev) => ev.target === bd && bd.close());
    this._dialogusKezelo();
    this._grafKezelo();
    this._dKezelo();
    this._kimutatasKezelo();
    this._folyoszamlaKezelo();
    this._tetelKezelo();
    this._szamlaKezelo();
    this._torlesKezelo();
    this._lezarKezelo();
    this._javitasKezelo();
    this._mentesKezelo();
    this._emailKezelo();
    this._tabletKezelo();
    requestAnimationFrame(() => this._hosszuMagyarazat());
  }

  // A fiókkártyán a két sornál hosszabb magyarázó sor helyett a megnevezése után ⓘ gomb, a teljes szöveg buborékban.
  // Megnevezés: az előtte álló .cimke (ha már van ⓘ-je, abba kerül), ennek híján a sor „Név: …” eleje.
  _hosszuMagyarazat() {
    const r = this.shadowRoot;
    // Előző állapot visszaállítása (újramérés más szélességen).
    r.querySelectorAll("button.hosszuinfo").forEach((b) => b.remove());
    r.querySelectorAll("[data-hosszu-eredeti]").forEach((b) => { b.dataset.info = b.dataset.hosszuEredeti; delete b.dataset.hosszuEredeti; });
    r.querySelectorAll("[data-hosszu-html]").forEach((e) => { e.innerHTML = e.dataset.hosszuHtml; delete e.dataset.hosszuHtml; });
    r.querySelectorAll("[data-hosszu-rejtett]").forEach((e) => { e.hidden = false; delete e.dataset.hosszuRejtett; });
    const tartalom = (e) => {
      // A beágyazott ⓘ szövege dőlten a buborékba kerül (buborékban buborék nem nyitható).
      const k = e.cloneNode(true);
      k.querySelectorAll("button.info").forEach((b) => b.replaceWith(Object.assign(document.createElement("i"), { innerHTML: ` – ${b.dataset.info}` })));
      return k.innerHTML.trim();
    };
    const gomb = (html) => {
      const t = document.createElement("template");
      t.innerHTML = info(html);
      const b = t.content.firstElementChild;
      b.classList.add("hosszuinfo");
      return b;
    };
    const cimkeje = (e) => {
      for (let s = e.previousElementSibling; s; s = s.previousElementSibling) {
        if (s.matches(".cimke")) return s;
        if (s.querySelector(".cimke") || !s.matches(".kicsi, .sav, .ertek, .nagyobb")) return null;
      }
      return null;
    };
    const elemek = [...r.querySelectorAll(".kartya .kicsi, .kartya .kinfo > div")]
      .filter((e) => !e.closest(".kfej, .fejlec, .reszletek, .gombok, dialog") && e.offsetParent);
    // Előbb mérünk, utána módosítunk (a módosítás nem befolyásolja a többi mérést).
    const hosszuak = elemek.filter((e) => {
      const st = getComputedStyle(e);
      const sor = parseFloat(st.lineHeight) || parseFloat(st.fontSize) * 1.35;
      return e.getBoundingClientRect().height > sor * 2 + 2;
    });
    for (const e of hosszuak) {
      const szoveg = tartalom(e);
      const c = cimkeje(e);
      if (c) {
        const meglevo = c.querySelector("button.info");
        if (meglevo) {
          meglevo.dataset.hosszuEredeti = meglevo.dataset.info;
          meglevo.dataset.info = `${szoveg}<hr>${meglevo.dataset.info}`;
        } else c.append(" ", gomb(szoveg));
        e.dataset.hosszuRejtett = "1";
        e.hidden = true;
        continue;
      }
      // „Megnevezés: érték …” – a megnevezés marad, a többi a buborékba.
      const html = e.innerHTML, i = html.indexOf(": ");
      e.dataset.hosszuHtml = html;
      if (i > 0 && i < 80 && !html.slice(0, i).includes("<")) {
        e.innerHTML = html.slice(0, i);
        e.append(" ", gomb(`<b>${html.slice(0, i)}:</b> ${tartalom(Object.assign(document.createElement("div"), { innerHTML: html.slice(i + 2) }))}`));
      } else {
        // Megnevezés nélkül: két sorra rövidítve, a ⓘ az elején.
        e.innerHTML = `<span class="ketsor">${html}</span>`;
        e.firstElementChild.prepend(gomb(szoveg), " ");
      }
    }
  }

  _aktivHaztartas(hazak) {
    return hazak.find((h) => h.entry_id === this._aktivHaz) || hazak[0];
  }

  _otthonValt(id) {
    if (id === this._aktivHaz) return;
    this._aktivHaz = id;
    this._jelolt.clear();
    try { localStorage.setItem("hu_rezsi_otthon", id); } catch (e) { /* tárolás nélkül is működik */ }
    this._rajzol();
    window.scrollTo({ top: 0 });
  }

  // Fülsor (mint a böngészőben): otthononként a név és az e havi esedékes összeg; figyelmeztetésnél jelzőpont.
  _fulek(hazak) {
    const aktiv = this._aktivHaztartas(hazak);
    return `<nav class="fulek" role="tablist" aria-label="Otthonok">${hazak.map((h) => {
      const sel = h === aktiv;
      const figy = this._figyelmeztetesek(h).some((x) => x.szint !== "info");
      return `<button type="button" role="tab" class="ful${sel ? " aktiv" : ""}" data-otthon="${esc(h.entry_id)}" aria-selected="${sel}" tabindex="${sel ? 0 : -1}">
        <span class="fulnev">${esc(h.nev)}${figy ? '<span class="fulpont" title="Van teendő"></span>' : ""}</span>
        <span class="fulosszeg">${ft(h.osszesen.esedekes)}</span></button>`;
    }).join("")}</nav>`;
  }

  _figyelmeztetesek(h) {
    const lista = [];
    for (const f of h.fiokok) {
      if (f.hiba) lista.push({ sid: f.sid, szint: "hiba", szoveg: `${f.nev}: nem számolható (${f.hiba})` });
      if (f.fizetes?.lejart_db)
        lista.push({ sid: f.sid, szint: "hiba", szoveg: `${f.nev}: ${f.fizetes.lejart_db} számla lejárt, nincs kifizetve (${ft(f.fizetes.lejart_ft)}) – ha már fizetted, jelöld a Részletek → Számlák listában` });
      if (f.keret?.atlepes) lista.push({ sid: f.sid, szint: "figy", szoveg: `${f.nev}: várhatóan ${nap(f.keret.atlepes)} körül elfogy a kedvezményes keret` });
      // Ha van éves előrejelzés, az a mérvadó (pl. nyaralónál a nyári ráfizetést a téli átalányok kiegyenlítik).
      if (f.elszamolas && f.elszamolas.egyenleg < -10000 && !f.egyenleg)
        lista.push({ sid: f.sid, szint: "figy", szoveg: `${f.nev}: várható ráfizetés az elszámoláskor kb. ${ft(-f.elszamolas.egyenleg)}` });
      if (f.egyenleg && f.egyenleg.egyenleg < -10000)
        lista.push({ sid: f.sid, szint: "figy", szoveg: `${f.nev}: ${f.utem && f.utem.elszamolas_honap === 6 ? "a félévi" : "az éves"} elszámolásnál (${nap(f.egyenleg.ev_ig)} körül) várható ráfizetés kb. ${ft(-f.egyenleg.egyenleg)}` });
      const dk = f.utem?.kovetkezo_diktalas;
      if (dk) {
        const ma = new Date().toISOString().slice(0, 10), het = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
        if (dk[0] <= het && ma <= dk[1]) lista.push({ sid: f.sid, szint: "figy", szoveg: `${f.nev}: mérőállás-diktálás ${nap(dk[0])} – ${nap(dk[1])} között (a szolgáltatónak)` });
      }
      const de = f.szamla_stat?.dij_elteres;
      if (f.szamla_stat?.figyelmeztetes) lista.push({ sid: f.sid, szint: "info", szoveg: `${f.nev}: ${f.szamla_stat.figyelmeztetes}`, html: de && this._admin
        ? `<div class="ellgombok"><button type="button" class="linkgomb" data-dijelt="${esc(`${f.sid}|${de.sorszam}`)}" data-dontes="uj_dij" title="A havidíj ${nap(de.tol)}-tól ${ft(Math.round(de.osszeg / de.honap))} (felülírás a fiókban)">Ez az új havidíj (${ft(Math.round(de.osszeg / de.honap))}/hó, ${fejNap(de.tol)}-tól)</button>
            <button type="button" class="linkgomb" data-dijelt="${esc(`${f.sid}|${de.sorszam}`)}" data-dontes="egyszeri" title="Egyszeri tétel vagy kedvezmény – ennél a számlánál nem jelez tovább">Egyszeri eltérés – rendben</button></div>` : "" });
      // Számla-ellenőrzés: a szolgáltató számláinak talált hibái (reklamálható / pótszámla várható).
      for (const t of f.ellenorzes || []) {
        if (t.rendezve && !this._ellMind) continue;
        const ertek = t.hatas_ft < 0 ? `kb. ${ft(-t.hatas_ft)} túlszámlázás – reklamálható` : `kb. ${ft(t.hatas_ft)} nincs kiszámlázva – pótszámla várható`;
        const NEV = { nem_szamlazott: "nem kiszámlázott fogyasztás", regisztercsere: "felcserélt regiszterek", csatorna_tobblet: "több szennyvíz, mint ivóvíz", elteres: "eltérés a saját számítástól" };
        const k = `${f.sid}|${t.kulcs}`;
        lista.push({
          sid: f.sid,
          szint: t.rendezve ? "info" : t.sulyos ? "figy" : "info",
          szoveg: `${f.nev} · ${t.sorszam} (${nap(t.kelte)}): ${NEV[t.tipus] || t.tipus} – ${t.tipus === "elteres" ? `${ft(Math.abs(t.hatas_ft))} eltérés, ellenőrizendő` : ertek}${t.rendezve ? " (rendezve)" : ""}`,
          html: `<div class="kicsi">${esc(t.leiras)} A számla díja ${ft(t.szamla_ft)}, a saját számítás szerint ${ft(t.szamolt_ft)}.</div>
            <div class="ellgombok"><button type="button" class="linkgomb" data-reklam="${esc(k)}">Reklamáció-tervezet ›</button>
            ${this._admin ? `<button type="button" class="linkgomb" data-ellrend="${esc(k)}" data-dontes="${t.rendezve ? "nyitott" : "rendezve"}">${t.rendezve ? "Újranyitás" : "Rendezve"}</button>` : ""}</div>`,
        });
      }
      // Késő várt számla (átalány / fix díj / diktálás): ha soha nem jön meg, a becslés jóváhagyással lemondható.
      const kk = f.fejlec?.kovetkezo;
      if (kk?.kesik && kk.varva)
        lista.push({ sid: f.sid, szint: "figy", szoveg: `${f.nev}: a${kk.tol ? ` ${fejNap(kk.tol)} – ${fejNap(kk.ig)} közötti` : ""} várt számla (${ft(kk.dij)}) ${nap(kk.varva)} óta késik`,
          html: this._admin ? `<div class="kicsi">Ha a szolgáltató erről nem állít ki számlát (pl. másképp számolta el), a becslés törölhető – a számlák, befizetések és egyenlegek nem változnak.</div>
            <div class="ellgombok"><button type="button" class="linkgomb" data-lemond="${esc(f.sid)}" data-varva="${esc(kk.varva)}" data-tol="${esc(kk.tol || "")}" data-ig="${esc(kk.ig || "")}" data-osszeg="${esc(String(kk.dij ?? ""))}"
              data-szoveg="${esc(`${f.nev}: ${kk.tol ? `${fejNap(kk.tol)} – ${fejNap(kk.ig)}, ` : ""}${ft(kk.dij)}`)}">Nem jön számla – törlés…</button></div>` : "" });
      // Automatikusan rendezett ki nem számlázott tételek (egy későbbi számla elszámolta) – 30 napig tájékoztatásul.
      for (const r of f.auto_rendezett || []) {
        if (!r.rogzitve || Date.now() - new Date(r.rogzitve).getTime() > 30 * 864e5) continue;
        const mit = r.fajta === "uton" ? `a ${fejNap(r.tol)} – ${fejNap(r.ig)} közötti, saját számítású számla` : `a ${nap(r.kovetkezo_datum)} körül várt számla`;
        lista.push({ sid: f.sid, szint: "info", szoveg: `${f.nev}: ${mit} (${ft(r.osszeg)}) nem jött meg – egy későbbi számla (${r.sorszam || ""}) elszámolta, automatikusan rendezve` });
      }
      if (f.ismeretlen_fajlok?.length)
        lista.push({ sid: f.sid, szint: "info", szoveg: `${f.nev}: ${f.ismeretlen_fajlok.length} fájlt nem ismertem fel a számlamappában (${f.ismeretlen_fajlok.slice(0, 3).join(", ")}${f.ismeretlen_fajlok.length > 3 ? ", …" : ""}) – rögzítsd az Új számla gombbal${this._aiLehet() ? ", olvastasd ki AI-val" : ""}, vagy küldj mintát.`,
          html: this._aiLehet() ? `<div class="ellgombok">${f.ismeretlen_fajlok.filter((n) => /\.pdf$/i.test(n)).slice(0, 5).map((n) =>
            `<button type="button" class="linkgomb" data-aifajl="${esc(`${f.sid}|${n}`)}" title="A számla szövegét (a személyes adatok kitakarásával) a választott AI kiolvassa; rögzíteni te hagyod jóvá">Kiolvasás AI-val: ${esc(n)} ›</button>`).join("")}</div>` : "" });
    }
    return lista;
  }

  _haztartas(h) {
    if (!h.fiokok.length && !(h.szigetek || []).length)
      return `<section class="osszesito"><div class="hnev">${esc(h.nev)}</div><div class="megj">Ennek a háztartásnak még nincs fiókja. Beállítások → Eszközök és szolgáltatások → Rezsikövető → ${esc(h.nev)} → Fiók hozzáadása.</div></section>`;
    return `${this._osszesito(h)}
      <div class="racs">${h.fiokok.map((f) => this._fiok(f)).join("")}${(h.szigetek || []).map((x) => this._sziget(x)).join("")}</div>`;
  }

  // Az otthon összesítője (nagy számok, e-mail, folyószámla, esedékes számlák, függő számlák, teendők).
  _osszesito(h) {
    const figy = this._figyelmeztetesek(h);
    return `
      <section class="osszesito">
        <button class="ikongomb kimutgomb" data-kimutatas="${h.entry_id}" title="Számlák kimutatása" aria-label="Számlák kimutatása – ${esc(h.nev)}"><ha-icon icon="mdi:table-large"></ha-icon></button>
        ${this._hass?.user?.is_admin ? `<button class="ikongomb szenzorgomb" data-szenzorok="${h.entry_id}" title="Szenzorok hozzárendelése" aria-label="Szenzorok – ${esc(h.nev)}"><ha-icon icon="mdi:link-variant"></ha-icon></button>` : ""}
        <div class="hnev">${esc(h.nev)}</div>
        <div class="nagyszamok">
          <div><div class="cimke">Ebben a hónapban esedékes számlák ${info("A számlázási ütem szerint ebben a hónapban kiállított és még várható számlák összege.")}</div><div class="nagy">${ft(h.osszesen.esedekes)}</div>${(() => {
            const b = h.fiokok.reduce((t, f) => t + (f.esedekes?.e_havi_varhato || 0) + (f.uton_szamlak || []).reduce((u, x) => u + x.osszeg, 0), 0);
            return b ? `<div class="kicsi esedekesmajd">ebből ~${ft(b)} még nem érkezett (becslés)</div>` : "";
          })()}</div>
          <div><div class="cimke">Havi átlag ${info("Az átalány napra leosztott része, illetve a több hónapra számlázott díjak (víz) havi része. A hónapnál rövidebb vagy hosszabb időszak (pl. az éves leolvasás után a diktálásig) díja egy átlagos hónapra arányosítva. A fix díjas szemétszállítás csak az esedékesség hónapjában szerepel, a teljes számlaösszeggel.")}</div><div class="nagy masodlagos">${ft(h.osszesen.varhato)}</div></div>
        </div>
        ${h.hianyzo_szenzorok ? `<div class="banner szenzorhiany">${h.hianyzo_szenzorok} használt szenzor nem található ebben a rendszerben (pl. visszaállítás után) – ezek a fiókok nem kapnak mérést. ${this._hass?.user?.is_admin ? `<button type="button" class="linkgomb" data-szenzorok="${h.entry_id}">Szenzorok hozzárendelése ›</button>` : ""}</div>` : ""}
        ${(() => {
          // Mobilon az e-mailes blokk összecsukva (hibánál, futó keresésnél nyitva).
          const pfk = h.email?.postafiokok || [];
          if (this._nezetMod() !== "mobil" || !pfk.length) return this._emailBlokk(h);
          const nyitva = pfk.some((x) => x.felderites_fut || x.hiba);
          return `<details class="mobilemail"${nyitva ? " open" : ""}><summary><ha-icon icon="mdi:email-search-outline"></ha-icon> Számlák e-mailből <span class="kicsi">(${pfk.length} postafiók)</span></summary>${this._emailBlokk(h)}</details>`;
        })()}
        ${this._folyoszamlaSor(h)}
        ${this._esedekesLista(h)}
        ${this._szigetOsszesito(h)}
        ${this._fuggoBlokk(h)}
        ${figy.length ? `<ul class="figylista">${figy.map((x) => `<li class="${x.szint}"${x.sid ? ` data-ugrik="${x.sid}" title="Ugrás a fiók kártyájára"` : ""}>${esc(x.szoveg)}${x.html || ""}</li>`).join("")}</ul>` : `<div class="rendben">Nincs teendő.</div>`}
        ${h.fiokok.some((f) => (f.ellenorzes || []).some((t) => t.rendezve)) ? `<button type="button" class="linkgomb kicsi" data-ellmind="1">${this._ellMind ? "Rendezett számlahibák elrejtése" : "Rendezett számlahibák mutatása"}</button>` : ""}
      </section>`;
  }

  // ---- Tablet/notebook nézet (2.3.0b3) ----
  // A megjelenítés: „tablet” (széles, hasábos lapok, táblázatok), „mobil” (keskeny lapok, kártyák) vagy „regi”
  // (minden egymás alatt). Automatikusan: 900 px felett tablet, alatta mobil.
  _nezetMod() {
    if (["tablet", "mobil", "regi"].includes(this._nezetBeall)) return this._nezetBeall;
    return (this.clientWidth || window.innerWidth) >= 900 ? "tablet" : "mobil";
  }

  _tablet() { return this._nezetMod() !== "regi"; }  // lapozós (tablet vagy mobil) nézet

  _mentLap() {
    try {
      localStorage.setItem("hu_rezsi_lap", JSON.stringify(this._lap));
      localStorage.setItem("hu_rezsi_tablet_mod", this._tabletMod);
      localStorage.setItem("hu_rezsi_nezet", this._nezetBeall);
    } catch (e) { /* tárolás nélkül is működik */ }
  }

  _lapok(h) {
    if (this._tabletMod === "tema")
      return [["attekintes", "mdi:view-dashboard-outline", "Áttekintés"], ["szamlak", "mdi:file-document-outline", "Számlák"],
        ["fogyasztas", "mdi:chart-bar", "Fogyasztás"], ["egyenleg", "mdi:scale-balance", "Egyenleg"], ["merok", "mdi:gauge", "Mérők"], ["matrix", "mdi:grid", "Mátrix"]]
        .map(([id, ikon, nev]) => ({ id, ikon, nev }));
    const figy = new Set(this._figyelmeztetesek(h).filter((x) => x.szint !== "info").map((x) => x.sid));
    return [{ id: "attekintes", ikon: "mdi:view-dashboard-outline", nev: "Áttekintés", al: ft(h.osszesen.esedekes) },
      ...h.fiokok.map((f) => ({ id: f.sid, ikon: IKON[f.kozmu] || "mdi:cash", nev: f.nev, figy: figy.has(f.sid),
        al: f.fejlec?.kovetkezo ? ft(f.fejlec.kovetkezo.dij) : f.esedekes?.kovetkezo_osszeg != null ? ft(f.esedekes.kovetkezo_osszeg) : "" })),
      ...(h.fiokok.length ? [{ id: "matrix", ikon: "mdi:grid", nev: "Mátrix" }] : [])];
  }

  _aktivLap(h) {
    const lapok = this._lapok(h), id = this._lap[`${h.entry_id}|${this._tabletMod}`];
    return lapok.find((l) => l.id === id) || lapok[0];
  }

  _lapValt(entryId, id, mod = null) {
    if (mod) this._tabletMod = mod;
    if (id) this._lap[`${entryId}|${this._tabletMod}`] = id;
    this._menuSid = null;
    this._mentLap();
    this._rajzol();
    this.shadowRoot.querySelector(".lapful.aktiv")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  _lapLeptet(h, irany) {
    const lapok = this._lapok(h), i = lapok.findIndex((l) => l.id === this._aktivLap(h).id);
    this._lapValt(h.entry_id, lapok[(i + irany + lapok.length) % lapok.length].id);
  }

  _haztartasTablet(h) {
    if (!h.fiokok.length && !(h.szigetek || []).length) return this._haztartas(h);
    const lapok = this._lapok(h), aktivId = this._aktivLap(h).id, aktiv = lapok.find((l) => l.id === aktivId), fiokMod = this._tabletMod === "fiok";
    const mobil = this._nezetMod() === "mobil";
    const ful = (l) => `<button type="button" role="tab" class="lapful${l === aktiv ? " aktiv" : ""}" data-lap="${esc(l.id)}" data-entry="${esc(h.entry_id)}"
        aria-selected="${l === aktiv}" tabindex="${l === aktiv ? 0 : -1}" title="${esc(l.nev)}"><ha-icon icon="${l.ikon}"></ha-icon>
        <span class="lapnev">${esc(l.nev)}${l.figy ? '<span class="fulpont" title="Van teendő"></span>' : ""}</span>${l.al ? `<span class="lapal">${esc(l.al)}</span>` : ""}</button>`;
    const valto = `<div class="nezetvalto" role="group" aria-label="Nézet">
        <button type="button" class="${fiokMod ? "aktiv" : ""}" data-tabletmod="fiok" data-entry="${esc(h.entry_id)}" aria-pressed="${fiokMod}" title="Fiókonként: egy fiók egy lapon"><ha-icon icon="mdi:view-carousel-outline"></ha-icon><span class="nvszoveg">Fiókok</span></button>
        <button type="button" class="${fiokMod ? "" : "aktiv"}" data-tabletmod="tema" data-entry="${esc(h.entry_id)}" aria-pressed="${!fiokMod}" title="Témánként: minden fiók egy táblázatban"><ha-icon icon="mdi:table-large"></ha-icon><span class="nvszoveg">Témák</span></button></div>`;
    let lap;
    if (aktiv.id === "attekintes") lap = this._attekintes(h);
    else if (aktiv.id === "matrix") lap = this._matrix(h);
    else if (fiokMod) {
      const f = h.fiokok.find((x) => x.sid === aktiv.id);
      lap = mobil ? this._fiok(f) : `<div class="egylap">${this._fiok(f)}</div>`;
    } else lap = this._temaLap(h, aktiv.id);
    const i = lapok.indexOf(aktiv);
    const lapozo = lapok.length > 1 ? `<div class="lapozo">
        <button type="button" class="ikongomb" data-lapnyil="-1" data-entry="${esc(h.entry_id)}" title="Előző (←)" aria-label="Előző lap"><ha-icon icon="mdi:chevron-left"></ha-icon></button>
        ${lapok.map((l, j) => `<button type="button" class="lappotty${j === i ? " aktiv" : ""}" data-lap="${esc(l.id)}" data-entry="${esc(h.entry_id)}" aria-label="${esc(l.nev)}" title="${esc(l.nev)}"></button>`).join("")}
        <button type="button" class="ikongomb" data-lapnyil="1" data-entry="${esc(h.entry_id)}" title="Következő (→)" aria-label="Következő lap"><ha-icon icon="mdi:chevron-right"></ha-icon></button></div>` : "";
    return `<div class="lapos${mobil ? " keskeny" : ""}"><div class="tabletsav"><nav class="lapfulek" role="tablist" aria-label="${fiokMod ? "Fiókok" : "Témák"}">${lapok.map(ful).join("")}</nav>${valto}</div>
      <div class="lapter" data-lapter="${esc(h.entry_id)}">${lap}</div>${lapozo}</div>`;
  }

  // Áttekintés: az összesítő és fiókonként egy csempe (koppintásra a fiók lapja).
  _attekintes(h) {
    const figy = new Set(this._figyelmeztetesek(h).filter((x) => x.szint !== "info").map((x) => x.sid));
    const csempe = (f) => {
      const k = f.fejlec?.kovetkezo, e = f.fejlec?.egyenleg, ev = f.egyenleg;
      const kov = k ? `${ft(k.dij)}${k.kesik ? ' <span class="figyszoveg">késik</span>' : ""}` : f.esedekes?.kovetkezo_osszeg != null ? ft(f.esedekes.kovetkezo_osszeg) : "–";
      const mikor = k?.kelte ? `${nap(k.kelte)} körül` : f.esedekes?.kovetkezo_datum ? `${nap(f.esedekes.kovetkezo_datum)} körül` : "";
      return `<button type="button" class="csempe${figy.has(f.sid) ? " figy" : ""}" data-lapra="${esc(f.sid)}" data-entry="${esc(h.entry_id)}" title="${esc(f.nev)} – a fiók lapja">
        <div class="csfej"><ha-icon icon="${IKON[f.kozmu] || "mdi:cash"}"></ha-icon><b>${esc(f.nev)}</b>${figy.has(f.sid) ? '<span class="fulpont"></span>' : ""}</div>
        ${f.hiba ? `<div class="kicsi figyszoveg">${esc(f.hiba)}</div>` : `<div class="cscimke">Következő számla</div><div class="csertek">${kov}</div><div class="kicsi">${mikor}</div>
        <div class="cssor">${ev ? `<span>éves ${elojelFt(ev.egyenleg)}</span>` : ""}${e ? `<span>folyószámla ${elojelFt(-e.osszeg)}</span>` : ""}</div>`}</button>`;
    };
    return `${this._osszesito(h)}
      <div class="csempek">${h.fiokok.map(csempe).join("")}</div>
      ${(h.szigetek || []).length ? `<div class="racs">${h.szigetek.map((x) => this._sziget(x)).join("")}</div>` : ""}`;
  }

  // Témák: minden fiók egy táblázatban (tablet), illetve fiókonként egy kis kártyán (mobil); egy sorra/kártyára
  // koppintva a fiók lapja a Fiókok nézetben. Az adat egyszer épül fel (fej, sorok, összesen), a megjelenítés kétféle.
  // ---- Mátrix (2.3.0b10): fiók × elszámolási szakasz, ill. fiók × hónap (számlanaptár) ----
  // A cella színe az állapot (pontos/mért, becsült, átalány, teendő, nem vonatkozik); koppintásra a magyarázat felül.
  // Csak a meglévő panel-adatból – új számolás nincs mögötte.
  // A következő diktálási ablak [tól, ig] (ISO): az ütemből (víz: a számlán közölt következő ablak), ennek híján a
  // számlán közölt havi ablakból (MVM áram: minden hónap pl. 8–14.) – a mostani hónapé, ha még nem múlt el, különben
  // a következőé. havi: true, ha a havi ablakból jön. Közös MVM-számlázásnál (pl. A1 + H) a fiók saját számláin
  // nincs ablak: ilyenkor a csoport (fejlec.egyenleg.kozos) másik fiókjáé – ugyanazon a napon diktálható mindkét óra.
  _mxDiktalas(f, ma, tarsak = []) {
    if (f.utem?.kovetkezo_diktalas) return { dk: f.utem.kovetkezo_diktalas, havi: false };
    const ablak = (x) => [...(x.szamlak || [])].filter((y) => Array.isArray(y.diktalasi_ablak) && y.tipus !== "storno")
      .sort((a, b) => (b.kelte || "").localeCompare(a.kelte || ""))[0]?.diktalasi_ablak;
    const kozos = f.fejlec?.egyenleg?.kozos;
    const da = ablak(f) || (kozos ? tarsak.filter((t) => t !== f && t.fejlec?.egyenleg?.kozos === kozos).map(ablak).find(Boolean) : null);
    if (!da || f.megszunt) return null;
    const ho = new Date(ma.getFullYear(), ma.getMonth() + (ma.getDate() > da[1] ? 1 : 0), 1);
    const utolso = new Date(ho.getFullYear(), ho.getMonth() + 1, 0).getDate(), p2 = (n) => String(n).padStart(2, "0");
    const hh = `${ho.getFullYear()}-${p2(ho.getMonth() + 1)}`;
    return { dk: [`${hh}-${p2(Math.min(da[0], utolso))}`, `${hh}-${p2(Math.min(da[1], utolso))}`], havi: true };
  }

  _mxCellak(f, ma, tarsak = []) {
    const fe = f.fejlec || {}, fo = fe.folyo || {}, kv = fe.kovetkezo || {}, u = f.utem || {}, es = f.esedekes || {}, eg = fe.egyenleg;
    const fix = f.fix_dij, resz = f.reszszamlas, mod = f.elszamolas_mod, p = u.szamlazas_honap || 1;
    const diktSz = mod === "diktalas" || f.diktalas_szerint;
    const c = {};
    c.meres = fix ? { s: "na", t: "nincs mérő", r: "Fix díj: a számla összege nem a fogyasztástól függ." }
      : f.szenzor ? { s: "ok", t: "szenzor", r: "Saját szenzor méri folyamatosan; a számla és a leolvasások igazítják (korrekciós szorzó)." }
      : { s: "becs", t: "leolvasás", r: "Nincs szenzor: a fogyasztás a rögzített leolvasások közti napi átlagból becsülve. Diktálás vagy a következő számla pontosítja." };
    c.mod = fix ? { s: "ok", t: f.kozmu === "kozos" ? "előírás" : "fix díj", r: "Az összeg időszakonként azonos (a díjszabás vagy az előírás szerint)." }
      : mod === "diktalas" ? { s: "ok", t: "diktálás szerint", r: "Minden számla a diktált (leolvasott) állás szerint számol el: a két diktálás közti fogyasztás díja." }
      : resz && f.diktalas_szerint ? { s: "ok", t: "diktálás szerint", sub: "átalány helyett", r: "Átalányos szerződés, de a következő számla a diktált (ill. a közös számlázási időszak szerinti) mért fogyasztás díja." }
      : resz ? { s: "ata", t: "átalány", r: "A szolgáltató az átalányt számlázza; a tényleges fogyasztás különbsége az éves elszámoláskor rendeződik." }
      : { s: "ok", t: "mért", r: "A számla a mért fogyasztás szerint jön." };
    const utemNev = p === 1 ? "havi" : (TOBBHAVI[p] || `${p} havi`).toLowerCase();
    c.utem = { s: "ok", t: utemNev, r: `A szolgáltató ${UTEM[p] || `${p} havonta`} számláz${u.szolgaltato ? ` (${u.szolgaltato})` : ""}.` };
    const i = f.idoszak;
    if (i) {
      const havi = fo.honapok != null;
      const ar = havi ? fo.eltelt_honap / fo.honapok : (fo.eltelt_nap || 0) / (fo.napok || 1);
      c.folyo = { s: "ok", t: fejIdoszak(i.tol, i.ig, ["diktalas", "atalany"].includes(mod)), sub: havi ? `${fo.eltelt_honap}/${fo.honapok} hónap` : `${fo.eltelt_nap ?? "–"}/${fo.napok ?? "–"} nap`,
        bar: Math.max(0, Math.min(1, ar || 0)),
        r: p > 1 && !fix ? "A számlázási időszak: a legutóbbi számla vége utántól az ütem szerint." : diktSz ? "A diktálás szerinti időszak: az előző leolvasás másnapjától a következő diktálásig."
          : fix ? "A díj időszaka." : "Az elszámolási időszak." };
    }
    if (fo.varhato !== undefined) {
      c.varhato = fo.varhato_mert != null
        ? { s: "ata", t: ft(fo.varhato), sub: `mérés szerint ${ft(fo.varhato_mert)}`, r: fo.magyarazat || "" }
        : { s: ["mert", "pontos"].includes(fo.cimke) ? "ok" : "becs", t: ft(fo.varhato), sub: `eddig ${ft(fo.eddig)}`, r: fo.magyarazat || "" };
    }
    const uton = f.uton_szamlak || [];
    if (uton.length) {
      const x = uton[0], o = x.osszeg_brutto ?? x.osszeg;
      c.kov = { s: "tenni", t: "még nem jött", sub: `${fejNap(x.tol)} – ${fejNap(x.ig)} · ${ft(o)}`,
        r: "A lezárt időszakra (saját számítás) még nem érkezett számla. Ha egy későbbi számla elszámolja, a Rezsikövető magától rendezettnek veszi." + (x.levonva ? " A díjat a túlfizetésből vonják le." : "") };
    } else if (kv.dij !== undefined) {
      const kel = kv.kelte || es.kovetkezo_datum;
      c.kov = { s: kv.kesik ? "tenni" : kv.forras === "atalany" ? "ata" : kv.cimke === "pontos" ? "ok" : "becs", t: kel ? `${fejNap(kel)} körül` : "–",
        sub: `${ft(kv.fizetendo ?? kv.dij)}${kv.kesik ? " · késik" : ""}`, r: `${kv.tol ? `${nap(kv.tol)} – ${nap(kv.ig)} időszakra. ` : ""}${kv.magyarazat || ""}` };
    }
    const dkx = this._mxDiktalas(f, ma, tarsak), dk = dkx?.dk;
    if (dk) {
      const kozel = (new Date(dk[0]) - ma) / 864e5 <= 30;
      c.dikt = { s: kozel ? "tenni" : "ok", t: `${fejNap(dk[0])} – ${fejNap(dk[1])}`, sub: kozel ? (dkx.havi ? "havonta · hamarosan" : "hamarosan") : (dkx.havi ? "havonta" : null),
        r: dkx.havi ? "A számlán közölt havi diktálási ablak (minden hónapban ezekben a napokban diktálható a mérőállás); itt a legközelebbi."
          : "A diktálási ablak a díjszabás, ill. a számla szerint. A diktált állás a következő számláig felülírja az átalányt." };
    } else c.dikt = diktSz ? { s: "ok", t: "havonta", r: "Diktálás havonta, a szolgáltató ablakában (vagy a szenzor adja)." } : { s: "na", t: "–", r: "Ennél a fióknál nincs diktálás." };
    const ke = u.kovetkezo_elszamolas, el = f.elszamolas || {};
    if (ke && !fix) {
      const e = el.egyenleg;
      c.eves = { s: e != null && e < -10000 ? "tenni" : "becs", t: fejNap(ke),
        sub: e == null ? null : Math.abs(e) < 100 ? "kb. nullszaldó" : e > 0 ? `visszajár kb. ${ft(e)}` : `ráfizetés kb. ${ft(-e)}`,
        r: "„Ha ma lenne az elszámolás”: a mért fogyasztás díja és a befizetett átalány, ill. részszámlák különbsége az elszámolási év elejétől." };
    } else c.eves = { s: "na", t: "–", r: "Nincs éves elszámolás." };
    if (eg) {
      const o = eg.osszeg || 0;
      c.foly = { s: o > 0 ? "tenni" : "ok", t: o === 0 ? "rendezett" : o > 0 ? `tartozás ${ft(o)}` : `túlfizetés ${ft(-o)}`, sub: eg.kozos ? `közös: ${eg.kozos}` : null,
        r: "A folyószámla-kivonat záró egyenlege." + (eg.kozos ? " Közös folyószámla: a befizetés minden számlát kiegyenlít, ezért a fiókok egyenlege együtt látszik." : "") };
    } else c.foly = { s: "na", t: "–", r: "Nincs folyószámla-kivonat." };
    return c;
  }

  _matrix(h) {
    const MX_OSZL = [["meres", "Mérés", "honnan jön a fogyasztás"], ["mod", "Elszámolás", "mi alapján számláz"], ["utem", "Ütem", "milyen gyakran"],
      ["folyo", "Folyó időszak", "eltelt rész"], ["varhato", "Várható díj", "az időszak végére"], ["kov", "Következő számla", "kelte, fizetendő"],
      ["dikt", "Diktálás", "következő ablak"], ["eves", "Éves elszámolás", "ha ma lenne"], ["foly", "Folyószámla", "záró egyenleg"]];
    const ALL = { ok: "pontos / mért", becs: "becsült", ata: "átalány", tenni: "figyelj rá", na: "nem vonatkozik" };
    const TB = { resz: "R", elszamolo: "E", storno: "S", egyeb: "Sz", eloiras: "Ő" };
    const TN = { resz: "részszámla", elszamolo: "elszámoló számla", storno: "sztornó", egyeb: "számla", eloiras: "előírás" };
    const ma = new Date(), maHo = `${ma.getFullYear()}-${String(ma.getMonth() + 1).padStart(2, "0")}`;
    this._mxAll = this._mxAll || {};
    const all = (this._mxAll[h.entry_id] = this._mxAll[h.entry_id] || { nezet: "elszamolas", val: null });
    const fiokok = h.fiokok.filter((f) => !f.hiba && !f.megszunt);
    const cellak = Object.fromEntries(fiokok.map((f) => [f.sid, this._mxCellak(f, ma, fiokok)]));
    const e = esc(h.entry_id);
    // Teendők: a narancs cellák (közös folyószámla csak egyszer).
    const tenni = [];
    fiokok.forEach((f) => MX_OSZL.forEach(([k, n]) => {
      const c = cellak[f.sid][k];
      if (c?.s !== "tenni" || (k === "foly" && c.sub && tenni.some((x) => x.k === "foly" && x.c.sub === c.sub))) return;
      tenni.push({ f, k, n, c, nev: k === "foly" && c.sub ? c.sub.replace("közös: ", "") : f.nev });
    }));
    const valto = `<div class="mxvalto" role="group" aria-label="Mátrix nézet">${[["elszamolas", "Elszámolás"], ["naptar", "Számlanaptár"]].map(([k, n]) =>
      `<button type="button" data-mxnezet="${k}" data-entry="${e}" aria-pressed="${all.nezet === k}" class="${all.nezet === k ? "aktiv" : ""}">${n}</button>`).join("")}</div>`;
    const teendo = `<div class="mxteendok"><b>${tenni.length ? `${tenni.length} dolog, amire figyelj` : "Nincs teendő"}</b>${tenni.map((x) =>
      `<button type="button" class="mxchip" data-mxcella="${esc(`${x.f.sid}|${x.k}`)}" data-entry="${e}">${esc(x.n)}: <b>${esc(x.nev)}</b> – ${esc(x.c.t)}${x.c.sub && x.k !== "foly" ? ` (${esc(x.c.sub)})` : ""}</button>`).join("")}</div>`;
    // Részletek a kiválasztott celláról (alapból az első teendő, ennek híján az első fiók folyó időszaka).
    let reszlet;
    if (all.val?.startsWith("sz:")) {
      const x = JSON.parse(all.val.slice(3));
      reszlet = `<div class="mxbal"><div class="mxr1">Számlanaptár</div><div class="mxcim">${esc(x.fiok)}</div>
        <div class="mxertek">${ft(x.o)}<span class="mxpill mx-${x.uton ? "tenni" : x.var ? "becs" : "ok"}">${esc(x.cim)}</span></div></div><div class="mxjobb">
        ${x.n ? `<div class="kicsi">${x.var ? "Várható kelte" : "Kelte"}: ${nap(x.n)}${x.var ? " körül" : ""}</div>` : ""}
        ${x.i?.[0] ? `<div class="kicsi">Elszámolt időszak: ${nap(x.i[0])} – ${nap(x.i[1])}</div>` : ""}
        ${x.uton || x.var ? "" : (() => {
          // Beérkezett számla: sorszám, honnan jött (beolvasott fájl / AI / kézzel), megjegyzés, határidő, fizetés.
          const kezzel = x.kezi || x.forr === "kezi";
          const honnan = kezzel ? "kézzel rögzítve" : x.forr === "ai" ? `AI-val kiolvasva${x.fajl ? ` (${esc(x.fajl)})` : ""}`
            : x.fajl ? `számlafájlból beolvasva (${esc(x.fajl)}${x.fajl === "XML" ? ", Díjnet" : ""})` : "beolvasva";
          const MOD = { dijnet: "Díjnet", beszedes: "beszedési megbízás", utemezett: "állandó átutalás", feltetelezett: "feltételezett", egyenleg: "egyenleg szerint" };
          const fiz = !x.fiz ? "" : x.fiz.nf ? "nincs fizetendő" : x.fiz.f ? `fizetve${x.fiz.d ? ` ${nap(x.fiz.d)}` : ""}${MOD[x.fiz.m] ? ` (${MOD[x.fiz.m]})` : ""}`
            : `nincs kifizetve${x.fiz.l ? " – lejárt" : ""}`;
          return `<div><b>Sorszám:</b> ${x.sz ? esc(x.sz) : `nincs${kezzel ? " – kézzel rögzítve" : ""}`}</div>
            <div class="kicsi">${honnan}${x.megj ? ` · megjegyzés: ${esc(x.megj)}` : ""}</div>
            ${x.hat || fiz ? `<div class="kicsi">${x.hat ? `Fizetési határidő: ${nap(x.hat)}` : ""}${x.hat && fiz ? " · " : ""}${fiz}</div>` : ""}`;
        })()}
        <div>${x.uton ? "A lezárt időszakra saját számítás van, számla még nem jött. Ha egy későbbi számla elszámolja, magától rendezettnek veszi."
          : x.var ? "Az ütem és a legutóbbi számlák alapján: átalánynál az átalány, mért fióknál a folyó időszak várható díja, fix díjnál a díj." : ""}</div></div>`;
    } else {
      let [sid, k] = (all.val || "").split("|");
      if (!cellak[sid]?.[k]) [sid, k] = tenni.length ? [tenni[0].f.sid, tenni[0].k] : [fiokok[0]?.sid, "folyo"];
      const f = fiokok.find((x) => x.sid === sid), c = cellak[sid]?.[k];
      all.val = `${sid}|${k}`;
      reszlet = !c ? `<div class="kicsi">Válassz egy cellát.</div>` : `<div class="mxbal"><div class="mxr1">${esc(MX_OSZL.find((x) => x[0] === k)[1])}</div><div class="mxcim">${esc(f.nev)}</div>
        <div class="mxertek mx-${c.s}">${esc(c.t)}<span class="mxpill">${ALL[c.s]}</span></div></div><div class="mxjobb">
        ${c.sub ? `<div class="kicsi">${esc(c.sub)}</div>` : ""}<div>${esc(c.r || "")}</div>
        <div class="kicsi">A sor többi cellája: ${MX_OSZL.filter((x) => x[0] !== k).map((x) => `${x[1].toLowerCase()} ${esc(cellak[sid][x[0]]?.t || "–")}`).join(" · ")}</div>
        <button type="button" class="mxnyit" data-lapra="${esc(sid)}" data-entry="${e}">A fiók lapja <ha-icon icon="mdi:chevron-right"></ha-icon></button></div>`;
    }
    const fiokCella = (f, al) => `<td class="mxfiok km-${f.kozmu}"><div class="mxfb"><ha-icon icon="${IKON[f.kozmu] || "mdi:cash"}"></ha-icon><div><div class="mxn">${esc(f.nev)}</div><div class="kicsi">${esc(al)}</div></div></div></td>`;
    let tabla;
    if (all.nezet === "naptar") {
      const honapok = [];
      for (let j = -8; j <= 3; j++) { const d = new Date(ma.getFullYear(), ma.getMonth() + j, 1); honapok.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`); }
      const tetel = (st, betu, o, info, extra = "") => `<div class="mxszla mx-${st}${extra}" role="button" tabindex="0" data-mxszla="${esc(JSON.stringify(info))}" data-entry="${e}"><span class="mxbetu">${betu}</span>${FT.format(o ?? 0)}</div>`;
      tabla = `<table class="mxtabla mxnaptar"><thead><tr><th>Fiók</th>${honapok.map((m) => `<th class="${m === maHo ? "mxmost" : ""}"><span class="mxo">${HONAP[+m.slice(5) - 1]}</span>${m.slice(0, 4)}${m === maHo ? " · most" : ""}</th>`).join("")}</tr></thead><tbody>
        ${fiokok.map((f) => {
          const p = f.utem?.szamlazas_honap || 1, kv = f.fejlec?.kovetkezo || {}, uton = f.uton_szamlak || [];
          const kel = uton.length ? null : kv.kelte || f.esedekes?.kovetkezo_datum;
          const varh = [];
          if (kel) { const d = new Date(kel + "T12:00:00"); for (let j = 0; j < 4; j++) { const x = new Date(d.getFullYear(), d.getMonth() + j * p, Math.min(d.getDate(), 28)); varh.push({ h: `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}`, n: j ? null : kel, elso: !j }); } }
          const dk = this._mxDiktalas(f, ma, fiokok)?.dk, lv = f.fix_dij ? null : f.utem?.kovetkezo_leolvasas;
          const ke = f.fix_dij || lv ? null : f.utem?.kovetkezo_elszamolas;
          const tartam = (a, b) => (a.slice(0, 7) === b.slice(0, 7) ? `${+a.slice(8)}–${+b.slice(8)}.` : `${+a.slice(8)}.–${HONAP[+b.slice(5, 7) - 1]} ${+b.slice(8)}.`);
          return `<tr>${fiokCella(f, cellak[f.sid].utem.t)}${honapok.map((m) => {
            const t = (f.szamlak || []).filter((x) => (x.kelte || "").slice(0, 7) === m).sort((a, b) => a.kelte.localeCompare(b.kelte)).map((x) =>
              tetel(x.tipus === "storno" ? "na" : x.tipus === "resz" ? "ata" : "ok", TB[x.tipus] || "?", Number(x.osszeg),
                { fiok: f.nev, cim: TN[x.tipus] || x.tipus, o: Number(x.osszeg), n: x.kelte, i: x.idoszak, sz: x.sorszam || null,
                  forr: x.forras || null, kezi: !!x.kezi, fajl: x.fajl ? (x.fajl.split(".").pop() || "").toUpperCase() : null, megj: x.megjegyzes || null,
                  hat: x.hatarido || x.fizetes?.hatarido || null, fiz: x.fizetes ? { f: !!x.fizetes.fizetve, d: x.fizetes.datum || null, m: x.fizetes.forras || null,
                  nf: !!x.fizetes.nincs_fizetendo, l: !!x.fizetes.lejart } : null }, x.tipus === "storno" ? " mxstorno" : ""));
            if (uton.length && m === maHo) t.push(tetel("tenni", "?", uton[0].osszeg_brutto ?? uton[0].osszeg, { fiok: f.nev, cim: "még nem érkezett számla", o: uton[0].osszeg_brutto ?? uton[0].osszeg, i: [uton[0].tol, uton[0].ig], uton: true }, " mxvarhato"));
            varh.filter((v) => v.h === m).forEach((v) => t.push(tetel(v.elso ? "becs" : "na", "~", kv.fizetendo ?? kv.dij, { fiok: f.nev, cim: v.elso ? "következő várható számla" : "ütem szerint várható", o: kv.fizetendo ?? kv.dij, n: v.n, var: true }, " mxvarhato")));
            if (dk && dk[0].slice(0, 7) === m) t.push(`<span class="mxjel" title="Diktálási ablak: ${esc(nap(dk[0]))} – ${esc(nap(dk[1]))}">D ${tartam(dk[0], dk[1])}</span>`);
            if (lv && lv[0].slice(0, 7) === m) t.push(`<span class="mxjel" title="Éves leolvasás (elszámolás) ablaka: ${esc(nap(lv[0]))} – ${esc(nap(lv[1]))}">É ${tartam(lv[0], lv[1])}</span>`);
            if (ke && ke.slice(0, 7) === m) t.push(`<span class="mxjel" title="Éves elszámolás, leolvasás">É ${+ke.slice(8)}.</span>`);
            return `<td class="${t.length ? "mxnc" : "mxures"}${m === maHo ? " mxmostosz" : ""}">${t.join("")}</td>`;
          }).join("")}</tr>`;
        }).join("")}</tbody></table>`;
    } else {
      tabla = `<table class="mxtabla"><thead><tr><th>Fiók</th>${MX_OSZL.map(([, n, a]) => `<th><span class="mxo">${n}</span>${a}</th>`).join("")}</tr></thead><tbody>
        ${fiokok.map((f) => `<tr>${fiokCella(f, KOZMU[f.kozmu] || f.kozmu)}${MX_OSZL.map(([k]) => {
          const c = cellak[f.sid][k] || { s: "na", t: "–" }, id = `${f.sid}|${k}`;
          return `<td class="mxcella mx-${c.s}${all.val === id ? " valasztott" : ""}" role="button" tabindex="0" data-mxcella="${esc(id)}" data-entry="${e}">
            <div class="mxt">${esc(c.t)}</div>${c.sub ? `<div class="kicsi">${esc(c.sub)}</div>` : ""}${c.bar != null ? `<div class="mxsav"><i style="width:${(c.bar * 100).toFixed(1)}%"></i></div>` : ""}</td>`;
        }).join("")}</tr>`).join("")}</tbody></table>`;
    }
    const jelm = all.nezet === "naptar"
      ? `<span class="mx-ok"><span class="mxbetu">E</span>elszámoló</span><span class="mx-ata"><span class="mxbetu">R</span>részszámla</span><span class="mx-ok"><span class="mxbetu">Sz</span>számla, <span class="mxbetu">Ő</span>előírás</span><span class="mx-na"><span class="mxbetu">S</span>sztornó</span><span class="mx-becs mxvarhato"><span class="mxbetu">~</span>következő várható</span><span class="mx-tenni mxvarhato"><span class="mxbetu">?</span>még nem érkezett</span><span><span class="mxjel">D</span>diktálási ablak</span><span><span class="mxjel">É</span>éves leolvasás, elszámolás</span>`
      : Object.entries(ALL).map(([k, n]) => `<span class="mx-${k}"><i class="mxnegyzet"></i>${n}</span>`).join("");
    return `<div class="mxlap"><div class="mxfej">${teendo}${valto}</div><div class="mxreszlet" aria-live="polite">${reszlet}</div>
      <div class="tablagorgeto mxgorgo">${tabla}</div><div class="mxjelm">${jelm}</div>
      <div class="kicsi temamegj">Kattints egy cellára: felül látszik, miből jön az érték. A mátrix a fiókok meglévő adataiból épül (a kártya szakaszai sorban); a számlanaptár az elmúlt 8 és a következő 3 hónap számláit mutatja – a várhatókat az ütem szerint.</div></div>`;
  }

  _temaLap(h, tema) {
    if (tema === "matrix") return this._matrix(h);
    const egys = (f) => (f.egyseg === "db" ? "" : f.egyseg);
    const ikon = (f) => `<ha-icon icon="${IKON[f.kozmu] || "mdi:cash"}"></ha-icon>`;
    const sor = (f, cellak) => ({ f, cellak });
    const td = (x) => x;
    const ossz = (arr) => { const v = arr.filter((x) => typeof x === "number"); return v.length ? v.reduce((a, b) => a + b, 0) : null; };
    const ures = (c) => c === "" || c === "–" || c == null;
    const tabla = (fej, sorok, lab = null, megj = "") => {
      const megjegyzes = megj ? `<div class="kicsi temamegj">${megj}</div>` : "";
      const nyit = (f) => `data-lapra="${esc(f.sid)}" data-entry="${esc(h.entry_id)}" title="${esc(f.nev)} – megnyitás a Fiókok nézetben"`;
      if (this._nezetMod() === "mobil")
        return `<div class="temakartyak">${sorok.map(({ f, cellak }) => `<div class="temakartya" role="button" tabindex="0" ${nyit(f)}>
            <div class="tkfej">${ikon(f)}<b>${esc(f.nev)}</b><ha-icon class="tknyil" icon="mdi:chevron-right"></ha-icon></div>
            <div class="tkracs">${fej.map((n, i) => (ures(cellak[i]) ? "" : `<div class="tkc">${n || ""}</div><div class="tkv">${cellak[i]}</div>`)).join("")}</div></div>`).join("")}
          ${lab ? `<div class="temakartya osszes"><div class="tkfej"><b>Összesen</b></div><div class="tkracs">${fej.map((n, i) => (ures(lab[i]) ? "" : `<div class="tkc">${n}</div><div class="tkv">${lab[i]}</div>`)).join("")}</div></div>` : ""}</div>${megjegyzes}`;
      return `<div class="tablagorgeto"><table class="tematabla"><thead><tr><th>Fiók</th>${fej.map((x) => `<th>${x}</th>`).join("")}</tr></thead>
        <tbody>${sorok.map(({ f, cellak }) => `<tr ${nyit(f)}><td class="tfiok">${ikon(f)}${esc(f.nev)}</td>${cellak.map((c) => `<td class="szam">${c}</td>`).join("")}</tr>`).join("")}</tbody>
        ${lab ? `<tfoot><tr><td>Összesen</td>${lab.map((c) => `<td class="szam">${c ?? ""}</td>`).join("")}</tr></tfoot>` : ""}</table></div>${megjegyzes}`;
    };
    const fiokok = h.fiokok.filter((f) => !f.hiba || tema === "merok");
    // Várható díj: átalánynál az átalány (a fejléc folyó időszaka szerint); a mért díj összehasonlításként.
    const varhatoDij = (f) => (f.fejlec?.folyo?.varhato_atalany != null ? f.fejlec.folyo.varhato : f.varhato?.osszeg ?? null);
    if (tema === "szamlak") {
      const kov = (f) => f.fejlec?.kovetkezo?.dij ?? f.esedekes?.kovetkezo_osszeg ?? null;
      const utolso = (f) => (f.szamlak || []).filter((x) => x.tipus !== "storno").sort((a, b) => (b.kelte || "").localeCompare(a.kelte || ""))[0];
      const sorok = fiokok.map((f) => {
        const k = f.fejlec?.kovetkezo, u = utolso(f), s = f.szamla_stat, e = f.fejlec?.egyenleg;
        const mikor = k?.kelte ? nap(k.kelte) : f.esedekes?.kovetkezo_datum ? nap(f.esedekes.kovetkezo_datum) : "–";
        return sor(f, [td(`${ft(kov(f))}${k?.kesik ? ' <span class="figyszoveg">késik</span>' : ""}`), td(`${mikor}${f.esedekes?.elmaradt ? ' <span class="figyszoveg">elmaradt</span>' : ""}`),
          td(ft(f.esedekes?.e_havi_osszesen ?? null)), td(u ? `${ft(Number(u.osszeg))} <span class="kicsi">${nap(u.kelte)}</span>` : "–"),
          td(s ? `${ft(s.eves_osszeg)} <span class="kicsi">(${s.eves_db} db)</span>` : "–"), td(e ? elojelFt(-e.osszeg) : "–")]);
      });
      const lab = [ft(ossz(fiokok.map(kov))), "", ft(ossz(fiokok.map((f) => f.esedekes?.e_havi_osszesen))), "", ft(ossz(fiokok.map((f) => f.szamla_stat?.eves_osszeg))),
        elojelFt(ossz(fiokok.map((f) => (f.fejlec?.egyenleg ? -f.fejlec.egyenleg.osszeg : null))))];
      return tabla(["Következő számla", "Várható kelte", "Ebben a hónapban", "Utolsó számla", "Utolsó 12 hónap", "Folyószámla"], sorok, lab,
        "Folyószámla: plusz = túlfizetés (a következő számlákon beszámítják), mínusz = fizetendő.");
    }
    if (tema === "fogyasztas") {
      const sorok = fiokok.map((f) => {
        const fo = f.fejlec?.folyo, ar = fo?.napok ? Math.max(0, Math.min(100, (100 * fo.eltelt_nap) / fo.napok)) : null, kr = f.keret;
        const kar = kr?.osszes ? Math.min(100, (100 * kr.felhasznalt) / kr.osszes) : null;
        return sor(f, [td(fo ? `${fejNap(fo.tol)} – ${fejNap(fo.ig)}` : f.idoszak ? `${fejNap(f.idoszak.tol)} – ${fejNap(f.idoszak.ig)}` : "–"),
          td(ar != null && !f.fix_dij ? `<div class="minisav"><div style="width:${ar}%"></div></div><div class="kicsi">${fo.eltelt_nap}/${fo.napok} nap</div>` : "–"),
          td(f.fix_dij ? "–" : `${szam(f.eddig?.mennyiseg, egys(f))}${regiszterBontas(f) ? `<div class="kicsi">${regiszterBontas(f)}</div>` : ""}`), td(f.fix_dij ? "–" : ft(f.eddig?.osszeg ?? null)),
          td(f.fix_dij ? "–" : szam(f.varhato?.mennyiseg, egys(f))), td(`${ft(varhatoDij(f))}${f.fejlec?.folyo?.varhato_mert != null ? `<div class="kicsi">mérés szerint ${ft(f.fejlec.folyo.varhato_mert)}</div>` : ""}`),
          td(f.fix_dij || f.varhato?.napi_atlag == null ? "–" : szam(f.varhato.napi_atlag, egys(f))),
          td(kar != null ? `<div class="minisav${kr.felhasznalt > kr.osszes ? " tullepve" : ""}"><div style="width:${kar}%"></div></div><div class="kicsi">${szam(Math.round(kr.felhasznalt))} / ${szam(kr.osszes, kr.egyseg)}</div>` : "–")]);
      });
      const lab = ["", "", "", ft(ossz(fiokok.map((f) => (f.fix_dij ? null : f.eddig?.osszeg)))), "", ft(ossz(fiokok.map(varhatoDij))), "", ""];
      return tabla(["Folyó időszak", "Eltelt", "Fogyasztás eddig", "Díj eddig", "Várható fogyasztás", "Várható díj", "Napi átlag", "Kedvezményes keret"], sorok, lab,
        "Mérő nélküli (fix díjas) fióknál nincs időarányos fogyasztás és díj – havi, negyedéves díj; a várható díj az időszak díja.");
    }
    if (tema === "egyenleg") {
      const hama = (f) => (f.elszamolas && (f.reszszamlas || f.megszunt) ? f.elszamolas.egyenleg : null);
      // Közös folyószámla (MVM: egy ügyfél áramfiókjai): egy sor – az összegek összeadva, a folyószámla egyszer.
      const csoportok = [];
      for (const f of fiokok) {
        const k = f.fejlec?.egyenleg?.kozos;
        const g = k ? csoportok.find((c) => c.kozos === k) : null;
        if (g) g.tagok.push(f); else csoportok.push({ kozos: k || null, tagok: [f] });
      }
      const ertekek = csoportok.map(({ kozos, tagok }) => {
        const f0 = tagok[0], e = f0.fejlec?.egyenleg, evek = tagok.map((f) => f.egyenleg).filter(Boolean);
        return {
          f: tagok.length > 1 ? { ...f0, nev: kozos } : f0, tobb: tagok.length > 1,
          hama: ossz(tagok.map(hama)), egyenleg: ossz(evek.map((v) => v.egyenleg)),
          ev: [...new Set(evek.map((v) => `${nap(v.ev_tol)} – ${nap(v.ev_ig)}`))].join("<br>") || "–",
          varhato: ossz(evek.map((v) => v.varhato_eves)), befizetve: ossz(evek.map((v) => v.befizetve)),
          hatra: evek.reduce((a, v) => a + (v.hatralevo_db || 0), 0), foly: e ? -e.osszeg : null,
        };
      });
      const sorok = ertekek.map((x) => sor(x.f, [td(x.hama != null ? elojelFt(x.hama) : "–"), td(x.egyenleg != null ? elojelFt(x.egyenleg) : "–"), td(x.ev),
        td(x.varhato != null ? ft(x.varhato) : "–"), td(x.befizetve != null ? `${ft(x.befizetve)}${x.hatra ? ` <span class="kicsi">+ ${x.hatra} részszámla</span>` : ""}` : "–"),
        td(x.foly != null ? `${elojelFt(x.foly)}${x.tobb ? ' <span class="kicsi">közös</span>' : ""}` : "–")]));
      const lab = [elojelFt(ossz(ertekek.map((x) => x.hama))), elojelFt(ossz(ertekek.map((x) => x.egyenleg))), "", ft(ossz(ertekek.map((x) => x.varhato))), "",
        elojelFt(ossz(ertekek.map((x) => x.foly)))];
      return tabla(["Ha ma lenne az elszámolás", "Éves egyenleg", "Elszámolási év", "Várható éves költség", "Befizetve", "Folyószámla"], sorok, lab,
        "Plusz: visszatérítés / túlfizetés várható, mínusz: ráfizetés / fizetendő. A „Ha ma lenne az elszámolás” csak átalányos (részszámlás) fióknál. "
        + "Közös folyószámlás fiókok (MVM: egy ügyfél áramfiókjai) egy sorban, az összegek összeadva, a folyószámla egyszer.");
    }
    // Mérők – a saját szenzor szerinti mostani állás élőben: állás + szorzó × (a szenzor mostani értéke − alap).
    const SZEREP = { vetelezes: "", h_teli: "1.81 téli", h_nyari: "1.82 nyári", zona_csucs: "csúcs", zona_volgy: "völgy", almero: "almérő", betaplalas: "betáplálás" };
    const elo = (a) => {
      const v = Number(this._hass?.states?.[a.entity_id]?.state);
      return a.alap == null || isNaN(v) || v < a.alap ? a.allas : a.allas + a.szorzo * (v - a.alap);
    };
    const szenzorCella = (f) => (f.szenzor_allasok || []).length
      ? f.szenzor_allasok.map((a) => `<div title="${esc(a.entity_id)}${a.becsult ? " – becsült (a szenzor most nem ad értéket)" : ""}">${SZEREP[a.szerep] ? `<span class="kicsi">${SZEREP[a.szerep]}</span> ` : ""}<span class="szelo" data-eid="${esc(a.entity_id)}" data-allas="${a.allas}" data-alap="${a.alap ?? ""}" data-szorzo="${a.szorzo}" data-egys="${esc(egys(f))}">${allas(elo(a), egys(f))}</span>${a.becsult ? ' <span class="kicsi">becsült</span>' : ""}</div>`).join("")
      : "";
    const sorok = h.fiokok.map((f) => {
      const u = f.utolso_allasok || {}, fo = u.vetelezes || Object.values(u)[0];
      const lo = f.leolvasasok || [], mero = lo.find((x) => x.mero && x.csatorna !== "almero")?.mero;
      const am = u.almero, amMero = lo.find((x) => x.mero && x.csatorna === "almero")?.mero;
      const kl = f.utem?.kovetkezo_leolvasas, kd = f.utem?.kovetkezo_diktalas;
      const tart = (x) => (Array.isArray(x) ? `${fejNap(x[0])} – ${fejNap(x[1])}` : x ? fejNap(x) : "–");
      const kov = [kl ? `<div class="tor"><span class="kicsi">leolvasás</span> ${tart(kl)}</div>` : "", kd ? `<div class="tor"><span class="kicsi">diktálás</span> ${tart(kd)}</div>` : ""].join("") || "–";
      const almeroSor = am && f.almero ? `<div class="tor"><span class="kicsi">almérő</span> ${allas(am.allas, egys(f))} <span class="kicsi">${nap(am.datum)}</span>${amMero ? `<div class="kicsi">mérő: ${esc(amMero)}</div>` : ""}</div>` : "";
      const cellak = [td(f.fix_dij ? '<span class="kicsi">nincs mérő</span>' : fo ? `${allas(fo.allas, egys(f))} <span class="kicsi">${nap(fo.datum)}</span>${mero ? `<div class="kicsi">mérő: ${esc(mero)}</div>` : ""}${almeroSor}` : "–"),
        td(f.fix_dij ? "" : szenzorCella(f))];
      cellak.push(td(kov), td(!f.fix_dij && f.device_id && !f.megszunt ? `<button type="button" class="kisgomb" data-leolvas="${esc(f.sid)}" >Mérőállás</button>` : ""));
      return sor(f, cellak);
    });
    return tabla(["Utolsó rögzített állás", "Saját szenzor szerint most", "Következő", ""], sorok, null,
      "A saját szenzor szerinti állás a kalibrált becslés (a rögzített állás + a szenzor azóta mért fogyasztása) – élőben frissül. "
      + "Ha eltér az órától: Mérőállás → „Csak korrekciós leolvasás” – igazítja a szenzor szerinti állást és a korrekciós szorzót, de nem diktálás és nem időszakhatár."
      + " A mérőállások egész számmal, ahogy az óra számlálója mutatja.");
  }

  // Korrekciós leolvasás után (2.3.0b6): a háttér újraszámol (a frissítéskérés késleltetett – H-tarifánál három
  // rögzítés), addig töltünk újra, amíg a beírt állás meg nem jelenik (≤ ~15 s); visszajelzés: a szenzor szerinti
  // becslés és az eltérés, a korrekciós szorzó előtte → utána.
  async _korrekcioEredmeny(f, ertekek, datum) {
    const elotte = Object.fromEntries((f.kalibracio || []).map((k) => [k.csatorna, k.szorzo]));
    const becsles = Object.fromEntries((f.szenzor_allasok || []).map((a) => [a.szerep, a.allas]));
    const keres = () => (this._adat?.haztartasok || []).flatMap((x) => x.fiokok).find((x) => x.sid === f.sid);
    const megvan = (x) => ertekek.every(([c, e]) => x?.utolso_allasok?.[c]?.datum === datum && Math.abs(Number(x.utolso_allasok[c].allas) - e) < 0.001);
    for (let i = 0; i < 6; i++) {
      await new Promise((ok) => setTimeout(ok, i ? 2500 : 1500));
      try { this._adat = await this._hass.callWS({ type: "hu_rezsi/adatok" }); } catch (e) { /* a következő körben újra */ }
      if (megvan(keres())) break;
    }
    const uj = keres() || f, egys = uj.egyseg === "db" ? "" : uj.egyseg, sorok = [];
    for (const [csat, beirt] of ertekek) {
      const nev = { h_teli: "1.81: ", h_nyari: "1.82: " }[csat] || "";
      if (becsles[csat] != null) {
        const e = beirt - becsles[csat];
        sorok.push(`${nev}a szenzor szerint ${szam(Math.round(becsles[csat] * 10) / 10, egys)} volt – eltérés ${e >= 0 ? "+" : "−"}${szam(Math.round(Math.abs(e) * 10) / 10, egys)}`);
      }
      const k = (uj.kalibracio || []).find((x) => x.csatorna === csat);
      if (k) sorok.push(`${nev}korrekciós szorzó: ${elotte[csat] ? `×${SZAM3.format(elotte[csat])}` : "nem volt"} → ${k.szorzo ? `<b>×${SZAM3.format(k.szorzo)}</b>` : `még nincs (${k.pontok}/3 leolvasás, ${k.napok}/45 nap)`}`);
    }
    return `<span class="ok">✓ Korrekciós leolvasás rögzítve:</span> ${ertekek.map(([c, e]) => `${{ h_teli: "1.81 ", h_nyari: "1.82 " }[c] || ""}${szam(e, egys)}`).join(" · ")}${sorok.length ? "<br>" + sorok.join("<br>") : ""}`;
  }

  _tabletKezelo() {
    this._egyszer("tablet", () => {
      const r = this.shadowRoot;
      const haz = (id) => (this._adat?.haztartasok || []).find((x) => x.entry_id === id);
      r.addEventListener("click", (ev) => {
        if (ev.target.closest?.("[data-savzar]")) { this._sav = null; this._rajzol(); return; }
        const mx = ev.target.closest?.("[data-mxcella],[data-mxnezet],[data-mxszla]");
        if (mx) {
          // Mátrix: cella / számla kiválasztása, nézetváltás – a vízszintes görgetés megmarad.
          this._mxAll = this._mxAll || {};
          const a = (this._mxAll[mx.dataset.entry] = this._mxAll[mx.dataset.entry] || { nezet: "elszamolas", val: null });
          if (mx.dataset.mxnezet) { a.nezet = mx.dataset.mxnezet; a.val = null; }
          else if (mx.dataset.mxszla) a.val = "sz:" + mx.dataset.mxszla;
          else { a.val = mx.dataset.mxcella; if (mx.classList.contains("mxchip")) a.nezet = "elszamolas"; }
          const g = r.querySelector(".mxgorgo"), sl = g && !mx.dataset.mxnezet ? g.scrollLeft : 0;
          this._rajzol();
          const g2 = r.querySelector(".mxgorgo");
          if (g2 && sl) g2.scrollLeft = sl;
          const most = mx.dataset.mxnezet === "naptar" && g2?.querySelector("th.mxmost");
          if (most) g2.scrollLeft = Math.max(0, most.offsetLeft - g2.clientWidth * 0.55);
          return;
        }
        const t = ev.target.closest?.("[data-lap],[data-lapra],[data-tabletmod],[data-lapnyil]");
        if (!t || ev.target.closest("[data-leolvas]")) return;
        if (t.dataset.tabletmod) this._lapValt(t.dataset.entry, null, t.dataset.tabletmod);
        else if (t.dataset.lapra) this._lapValt(t.dataset.entry, t.dataset.lapra, "fiok");
        else if (t.dataset.lapnyil) { const h = haz(t.dataset.entry); if (h) this._lapLeptet(h, Number(t.dataset.lapnyil)); }
        else this._lapValt(t.dataset.entry, t.dataset.lap);
      });
      r.addEventListener("keydown", (ev) => {
        const mxk = ev.target.closest?.("[data-mxcella],[data-mxszla]");
        if (mxk && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); mxk.click(); return; }
        const tk = ev.target.closest?.(".temakartya[data-lapra]");
        if (tk && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); this._lapValt(tk.dataset.entry, tk.dataset.lapra, "fiok"); return; }
        if (!["ArrowLeft", "ArrowRight"].includes(ev.key) || !ev.target.closest?.(".lapfulek")) return;
        const h = haz(ev.target.dataset.entry);
        if (!h) return;
        ev.preventDefault();
        this._lapLeptet(h, ev.key === "ArrowRight" ? 1 : -1);
        r.querySelector(".lapful.aktiv")?.focus();
      });
      // Lapozás húzással (a vízszintesen görgethető táblázatokon és az űrlapmezőkön nem).
      let kezd = null;
      r.addEventListener("touchstart", (ev) => {
        const ter = ev.target.closest?.(".lapter");
        kezd = ter && !ev.target.closest(".tablagorgeto, input, select, textarea, dialog") ? { x: ev.touches[0].clientX, y: ev.touches[0].clientY, id: ter.dataset.lapter } : null;
      }, { passive: true });
      r.addEventListener("touchend", (ev) => {
        if (!kezd) return;
        const dx = ev.changedTouches[0].clientX - kezd.x, dy = ev.changedTouches[0].clientY - kezd.y, h = haz(kezd.id);
        kezd = null;
        if (h && Math.abs(dx) > 70 && Math.abs(dy) < 50) this._lapLeptet(h, dx < 0 ? 1 : -1);
      }, { passive: true });
    });
  }

  // Az otthon összesítőjében: a szigetüzemi rendszerek folyó havi kWh-ja és önellátottsága – Ft nélkül, a rezsiösszegbe nem számít.
  _szigetOsszesito(h) {
    const sorok = (h.szigetek || []).map((x) => {
      const r = x.idoszakok?.honap;
      if (x.hiba || !r) return `<li>${esc(x.nev)}: ${esc(x.hiba || "nincs adat")}</li>`;
      const ho = new Date(r.tol).toLocaleDateString("hu-HU", { month: "long" });
      const pv = r.ertekek?.pv;
      return `<li><b>${esc(x.nev)}</b> · ${esc(ho)}: ${szam(r.fogyasztas, "kWh")} fogyasztás${pv != null ? `, PV ${szam(pv, "kWh")}` : ""}${r.onellatottsag != null ? ` · önellátottság <b>${r.onellatottsag.toLocaleString("hu-HU", { maximumFractionDigits: 1 })}%</b>` : ""}${r.minoseg !== "COMPLETE" ? ` <span class="kicsi">(${{ ESTIMATED: "részben becsült", PARTIAL: "hiányos", INCONSISTENT: "ellentmondásos mérés", INSUFFICIENT_DATA: "nincs elég adat" }[r.minoseg] || r.minoseg})</span>` : ""}</li>`;
    });
    return sorok.length ? `<ul class="szigetossz">${sorok.join("")}</ul><div class="kicsi">Szigetüzem: csak kWh, a fenti rezsiösszegbe nem számít.</div>` : "";
  }

  // Szigetüzem (kísérleti): csak kWh – fogyasztás, energiaforrások, akkumulátor, ellátás, adatminőség (docs/terv/06).
  _sziget(x) {
    const NEV = { fogyasztas: "Fogyasztás", pv: "PV-termelés", akku_toltes: "Töltés", akku_kisutes: "Kisütés", halozat: "Hálózati vételezés",
      halozat_akku: "ebből hálózatról akkuba", export: "Visszatáplálás (export)", generator: "Generátor", egyeb_termeles: "Egyéb termelés" };
    const IDO = [["ma", "Ma"], ["tegnap", "Tegnap"], ["honap", "Hónap"], ["elozo_honap", "Előző hónap"], ["ev", "Év"], ["elozo_ev", "Előző év"], ["osszesen", "Összesen"]];
    const MIN = { COMPLETE: ["ok", "teljes energiamérleg"], ESTIMATED: ["figy", "részben becsült (hézag a mérésben)"],
      PARTIAL: ["figy", "hiányos – nem minden csatorna mért a teljes időszakban"], INCONSISTENT: ["hiba", "ellentmondásos mérés – lásd lent"],
      INSUFFICIENT_DATA: ["hiba", "nincs elég adat"] };
    const fej = `<div class="kfej"><ha-icon icon="mdi:solar-power-variant"></ha-icon><div><div class="knev">${esc(x.nev)} <span class="cimkeszalag">kísérleti</span></div>
      <div class="kicsi">Szigetüzem · csak kWh, a rezsiösszegbe nem számít</div></div></div>`;
    if (x.hiba) return `<div class="kartya sziget">${fej}<div class="hiba">${esc(x.hiba)}</div></div>`;
    this._szigetIdo = this._szigetIdo || {};
    const kulcs = this._szigetIdo[x.sid] && x.idoszakok[this._szigetIdo[x.sid]] ? this._szigetIdo[x.sid] : "honap";
    const r = x.idoszakok[kulcs];
    const kwh = (v) => (v == null ? "–" : szam(v, "kWh"));
    const pct = (v) => (v == null ? "–" : `${v.toLocaleString("hu-HU", { maximumFractionDigits: 1 })}%`);
    const e = r.ertekek || {};
    const sor = (cimke, v, extra = "") => `<div class="szsorsz"><span>${cimke}</span><b>${v}</b>${extra}</div>`;
    const becs = (k) => ((r.becsult || []).includes(k) ? ' <span class="kicsi">(becsült)</span>' : "");
    const forrasok = ["pv", "halozat", "generator", "egyeb_termeles"].filter((k) => k in e);
    const akku = ["akku_toltes", "akku_kisutes"].some((k) => k in e);
    const [mo, mszoveg] = MIN[r.minoseg] || ["", r.minoseg];
    // Lezárt időszak vége éjfél (az előző nap az utolsó); folyó időszaknál (most) a mai nap is benne van. Ha a közös
    // mérési ablak az időszakon belül indul (r.kezdet), minden érték attól számol.
    const idoSzoveg = `${nap((r.kezdet || r.tol).slice(0, 10))} – ${nap(r.ig.endsWith("T00:00:00") ? elozoNap(r.ig.slice(0, 10)) : r.ig.slice(0, 10))}`;
    const havi = (x.honapok || []).slice(-12).reverse();
    return `<div class="kartya sziget">${fej}
      <div class="szigetido" role="group" aria-label="Időszak">${IDO.filter(([k]) => x.idoszakok[k]).map(([k, n]) =>
        `<button type="button" data-szigetido="${x.sid}|${k}" aria-pressed="${k === kulcs}">${n}</button>`).join("")}</div>
      <div class="ket"><div><div class="cimke">Fogyasztás · ${idoSzoveg}</div><div class="ertek">${kwh(r.fogyasztas)}</div>${becs("fogyasztas")}</div>
        <div><div class="cimke">Önellátottság ${info("1 − (hálózat + generátor) / fogyasztás. Időszakhatár-érzékeny: az akku az egyik időszakban felvett energiát egy másikban adhatja vissza (pl. éjjel a hálózatról tölt, másnap kisüt), ezért napi bontásban jelentősen eltérhet; havi és éves szinten ez egyre kevésbé számít.")}</div>
          <div class="ertek">${pct(r.onellatottsag)}</div>${["ma", "tegnap"].includes(kulcs) && r.onellatottsag != null ? `<div class="kicsi">napi érték – időszakhatár-érzékeny</div>` : ""}${r.onellatottsag != null ? `<div class="sav"><div class="toltes" style="width:${Math.max(0, Math.min(100, r.onellatottsag))}%"></div></div>` : ""}</div></div>
      ${forrasok.length ? `<div class="szblokk"><div class="cimke">Energiaforrások</div>${forrasok.map((k) => sor(NEV[k], kwh(e[k]), becs(k))).join("")}${r.sajat != null ? sor("Saját rendszerből", kwh(r.sajat)) : ""}</div>` : ""}
      ${akku ? `<div class="szblokk"><div class="cimke">Akkumulátor ${info("Akkuba töltve / akkuból kivéve. Hatásfokot nem számolunk: egy időszakra a kivét/töltés arány nem round-trip hatásfok, mert az időszak eleji és végi tárolt energia eltérhet.")}</div>
        ${"akku_toltes" in e ? sor(NEV.akku_toltes, kwh(e.akku_toltes), becs("akku_toltes")) : ""}${"akku_kisutes" in e ? sor(NEV.akku_kisutes, kwh(e.akku_kisutes), becs("akku_kisutes")) : ""}
        ${r.akku_netto != null ? sor("Nettó (töltés − kisütés)", kwh(r.akku_netto)) : ""}</div>` : ""}
      ${"export" in e || "halozat_akku" in e ? `<div class="szblokk">${"halozat_akku" in e ? sor(NEV.halozat_akku, kwh(e.halozat_akku)) : ""}${"export" in e ? sor(NEV.export, kwh(e.export)) : ""}</div>` : ""}
      ${r.halozati_reszarany != null || r.generator_reszarany != null ? `<div class="szblokk"><div class="cimke">Ellátás</div>${r.halozati_reszarany != null ? sor("Hálózati részarány", pct(r.halozati_reszarany)) : ""}${r.generator_reszarany != null ? sor("Generátor részarány", pct(r.generator_reszarany)) : ""}</div>` : ""}
      ${Object.keys(r.utvonalak || {}).length ? `<div class="szblokk"><div class="cimke">Mért útvonalak</div>${Object.entries(r.utvonalak).map(([k, v]) => sor({ halozat_akku: "Hálózat → akku", halozat_fogyasztas: "Hálózat → fogyasztás", pv_helyben: "PV helyben felhasználva" }[k] || k, kwh(v))).join("")}</div>` : ""}
      ${r.merleg_elteres != null ? `<div class="szblokk"><div class="cimke">Energiamérleg ${info("BE = PV + hálózat + generátor + egyéb + akku kisütés; KI = fogyasztás + akku töltés + export. A különbség veszteség (inverter, DC/DC, kábel, sajátfogyasztás), a mérési pontok (DC vagy AC oldal) különbsége, és az akkuban tárolt energia időszak eleji/végi változása – nem automatikusan akkuveszteség.")}</div>
        ${sor("Be / ki", `${kwh(r.merleg_be)} / ${kwh(r.merleg_ki)}`)}${sor("Mérleg-eltérés", kwh(r.merleg_elteres))}</div>` : ""}
      <div class="szminoseg ${mo}"><ha-icon icon="${mo === "ok" ? "mdi:check-circle-outline" : "mdi:alert-circle-outline"}"></ha-icon> Adatminőség: ${mszoveg}</div>
      ${(r.megjegyzesek || []).map((m) => `<div class="kicsi">${esc(m)}</div>`).join("")}
      ${havi.length ? `<details class="szhavi"><summary>Havi bontás</summary><div class="tablagorgeto"><table><thead><tr><th>Hónap</th><th>Fogyasztás</th>${forrasok.map((k) => `<th>${NEV[k].replace("Hálózati vételezés", "Hálózat")}</th>`).join("")}${akku ? "<th>Töltés</th><th>Kisütés</th>" : ""}<th>Önellátás</th></tr></thead><tbody>${havi.map((h) =>
        `<tr><td>${esc(honapNev(h.honap))}${h.reszleges ? " *" : ""}</td><td>${kwh(h.fogyasztas)}</td>${forrasok.map((k) => `<td>${kwh(h.ertekek[k])}</td>`).join("")}${akku ? `<td>${kwh(h.ertekek.akku_toltes)}</td><td>${kwh(h.ertekek.akku_kisutes)}</td>` : ""}<td>${pct(h.onellatottsag)}</td></tr>`).join("")}</tbody></table></div><div class="kicsi">* folyamatban lévő hónap</div></details>` : ""}
    </div>`;
  }

  // A szolgáltató közös folyószámlája (MVM): a legutóbbi számla szerinti egyenleg, és mi lesz, ha a talált hibákat javítják.
  // Számlák e-mailből – közérthetően: mi van bekötve, mikor nézte utoljára, mit talált, és a teendők (kérdés: melyik
  // fiókhoz tartozik; ajánlat: nincs ilyen fiók; üzenet: mi kapcsolódott be). Rendszergazdának a „📧 Számlák
  // e-mailből” gomb (vezetett beállítás), „Átnézés most”, „Keresés újra”, és a kézi szűrős fiókoknál az átállás.
  _emailBlokk(h) {
    const e = h.email;
    const pfk = e?.postafiokok || [];
    const gomb = !this._admin ? "" : pfk.length
      ? `<button type="button" class="emailnyit masodik" data-emailnyit="${esc(h.entry_id)}" title="Még egy e-mail cím (pl. a párodé)">+ E-mail cím</button>`
      : `<button type="button" class="emailnyit" data-emailnyit="${esc(h.entry_id)}"><span aria-hidden="true">📧</span> Számlák e-mailből</button>`;
    if (!pfk.length) return this._admin ? `<div class="emailsor emailures">${gomb}<span class="kicsi">Add meg az e-mail címed, és a szolgáltatók e-mailben küldött számlái maguktól bekerülnek.</span></div>` : "";
    const ido = (x) => (x ? new Date(x).toLocaleString("hu-HU", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : null);
    const HIBA = { hitelesites: "nem tudok belépni (jelszó?)", jelszo_hianyzik: "add meg újra a jelszót", kapcsolat: "a levelezőszerver nem érhető el" };
    const sorok = pfk.map((p) => {
      const kotes = (p.bekotott || []).map((b) => `${esc(b.nev)}${b.mod === "kezi" ? ' <span class="kicsi">(kézi szűrő)</span>' : ""}`).join(", ");
      let allapot;
      if (p.felderites_fut) {
        const perc = p.felderites_kezdet ? Math.floor((Date.now() - new Date(p.felderites_kezdet)) / 60000) : null;
        allapot = `<span class="emailfut"><span class="porgo" aria-hidden="true"></span> Keresem a számláidat…</span>
          <div class="kicsi">A fél év leveleit nézem át, ez több percig is tarthat${perc === null ? "" : perc < 1 ? " – most indult" : ` – ${perc} perce fut`}.</div>`;
      }
      else if (p.hiba) allapot = `<span class="figyszoveg" title="${esc(p.hiba)}">${HIBA[p.hiba_tipus] || "hiba"}</span>${p.utolso_sikeres ? ` <span class="kicsi">(utoljára sikeres: ${ido(p.utolso_sikeres)})</span>` : ""}`;
      else if (!p.fiokok) allapot = `<span class="kicsi">még egy fiókhoz sincs bekötve</span>`;
      else if (!p.utolso_atnezes) allapot = `<span class="kicsi">hamarosan átnézem</span>`;
      else allapot = `utoljára ${ido(p.utolso_atnezes)} · ${p.utolso_talalt ? `<b>${p.utolso_talalt} új számla</b>` : "nincs új számla"}${p.nem_besorolhato
        ? ` · <span class="figyszoveg" title="${esc((p.talalatok || []).filter((t) => t.tipus === "nem_besorolhato").map((t) => `${t.datum}: ${t.ok} (${t.fiok})`).join("\n"))}">${p.nem_besorolhato} levelet nem tudtam fiókhoz rendelni</span>` : ""}`;
      const f = p.felderites;
      const fsz = f && !p.felderites_fut ? (f.hiba ? "" : `<div class="kicsi">Legutóbbi keresés (${ido(f.ido)}): az utolsó fél évben ${f.talalt || 0} számlát találtam.</div>`) : "";
      const lista = (p.talalatok || []).filter((t) => t.tipus !== "nem_besorolhato").map((t) => `${t.datum} · ${t.fiok}: ${t.fajl || `${t.sorszam} (${t.osszeg} Ft, értesítő)`}`).join("\n");
      const kezi = (p.bekotott || []).some((b) => b.mod === "kezi");
      return `<div class="emailpf"${lista ? ` title="Legutóbb talált:\n${esc(lista)}"` : ""}><div><b>${esc(p.nev)}</b>${p.cim ? ` <span class="kicsi">${esc(p.cim)}</span>` : ""}: ${allapot}</div>
        ${kotes ? `<div class="kicsi">Innen jönnek: ${kotes}</div>` : ""}${fsz}
        ${this._admin ? `<div class="emailgombok"><button type="button" class="linkgomb" data-emailatnez="${esc(h.entry_id)}"${e.fut ? " disabled" : ""}>${e.fut ? "Folyamatban…" : "Átnézés most"}</button>
          <button type="button" class="linkgomb" data-emailkeres="${esc(h.entry_id)}|${esc(p.sid)}"${p.felderites_fut ? " disabled" : ""}>Keresés újra</button>
          ${kezi ? `<button type="button" class="linkgomb" data-emailvalasz="${esc(h.entry_id)}|auto|${esc(p.sid)}|" title="A számlák a tartalmuk (mérő, szolgáltató) szerint kerülnek a fiókokhoz; a feladó-szűrő tartaléknak marad">Automatikus besorolás bekapcsolása</button>` : ""}</div>` : ""}</div>`;
    });
    const uz = (e.uzenetek || []);
    const uzenetek = uz.length ? `<div class="emailuzenet" role="status"><ha-icon icon="mdi:email-check-outline"></ha-icon><div>${uz.map((u) => `<div>${esc(u.szoveg)}</div>`).join("")}</div>${this._admin
      ? `<button type="button" data-emailvalasz="${esc(h.entry_id)}|uzenet||">Rendben</button>` : ""}</div>` : "";
    const KOZMU_T = { villany: "villanyszámla", gaz: "gázszámla", viz: "vízszámla", tavho: "távhőszámla", hulladek: "hulladékszámla", tavkozles: "számla" };
    const pelda = (k) => [k.mero ? `mérő: ${esc(k.mero)}` : null, k.kelte ? nap(k.kelte) : null, k.osszeg != null ? ft(k.osszeg) : null,
      k.db > 1 ? `${k.db} számla` : null].filter(Boolean).join(" · ");
    const kerdesek = this._admin ? (e.kerdesek || []).map((k) => `<div class="emailkartya" role="group" aria-label="Kérdés">
        <div class="ekcim"><ha-icon icon="mdi:help-circle-outline"></ha-icon><b>Ez a számla melyik fiókhoz tartozik?</b></div>
        <div>${esc(k.nev)}${pelda(k) ? ` <span class="kicsi">(${pelda(k)})</span>` : ""}${k.ok === "mas_mero" ? `<div class="kicsi">A mérő gyári száma egyik fiókénál sem szerepel – mérőcsere, vagy egy másik ingatlan számlája?</div>` : ""}</div>
        <div class="gombok ekgombok">${k.jeloltek.map((j) => `<button type="button" class="fo" data-emailvalasz="${esc(h.entry_id)}|kerdes|${esc(k.id)}|${esc(j.sid)}">${esc(j.nev)}</button>`).join("")}
          <button type="button" data-emailvalasz="${esc(h.entry_id)}|kerdes|${esc(k.id)}|egyik_sem">Egyik sem</button></div></div>`).join("") : "";
    const ajanlatok = this._admin ? (e.ajanlatok || []).map((a) => `<div class="emailkartya" role="group" aria-label="Ajánlat">
        <div class="ekcim"><ha-icon icon="mdi:file-plus-outline"></ha-icon><b>${esc(a.targy || a.nev)} találtam, de nincs ilyen fiók.</b></div>
        <div class="kicsi">${pelda(a) || esc(KOZMU_T[a.kozmu] || "")}${a.kozmu !== "tavkozles" ? " – a fiók-varázsló előtöltve nyílik (a mérő adatait ott kell megadni)." : " – a fiók egy gombnyomással elkészül, a számlák ide jönnek."}</div>
        <div class="gombok ekgombok"><button type="button" class="fo" data-emailvalasz="${esc(h.entry_id)}|ajanlat|${esc(a.id)}|letrehoz">Fiók létrehozása</button>
          <button type="button" data-emailvalasz="${esc(h.entry_id)}|ajanlat|${esc(a.id)}|nem_kell">Nem kell</button></div></div>`).join("") : "";
    return `<div class="emailblokk"><div class="emailfej"><ha-icon icon="mdi:email-search-outline"></ha-icon><span>Számlák e-mailből</span>${gomb}</div>
      ${sorok.join("")}${uzenetek}${kerdesek}${ajanlatok}</div>`;
  }


  _folyoszamlaSor(h) {
    const fo = h.folyoszamla;
    if (!fo || (!fo.erdekes && !fo.hibak_db)) return "";
    const jel = (v) => (v < 0 ? `${ft(-v)} túlfizetés (neked jár)` : v > 0 ? `${ft(v)} fizetendő` : "0 Ft");
    return `<div class="folyosor"><span class="cimke">MVM folyószámla ${info(
      `Az MVM-nél egy ügyfél minden villany-fiókja (pl. A1 és H) egy közös folyószámlán van: az egyik fiók jóváírását a másik számláján vonják le („Egyéb fizetendőt csökkentő tétel”, „Túlfizetés”). Ezért a számlák „fizetendő” összege nem az adott fiók díja – a Rezsikövető a költségben a számla saját értékével számol. Az egyenleg a legutóbbi számla (${esc(fo.sorszam)}, ${nap(fo.kelte)}) szerinti, az azóta történt befizetések nélkül.`
      + (fo.hibak_db ? ` A talált számlahibák (lent) kijavítása után várható egyenleg: a számla szerinti egyenleg + a hibák forint-hatása (pótszámla: +, reklamáció: −).` : ""))}</span>
      <span>${jel(fo.osszeg)} <span class="kicsi">(a ${nap(fo.kelte).replace(/\.$/, "")}-i számla szerint)</span></span>
      ${fo.hibak_db ? `<div class="kicsi figyszoveg">Ha az MVM kijavítja a ${fo.hibak_db} talált számlahibát: kb. ${fo.korrigalt > 0 ? `${ft(fo.korrigalt)} fizetendő` : `${ft(-fo.korrigalt)} jár vissza`}.</div>` : ""}</div>`;
  }

  // Reklamáció-tervezet egy talált számlahibához: levélszöveg a bizonyítékokkal; nyomtatható / PDF-be menthető.
  _reklamacio(sid, kulcs) {
    const a = this._adat, hs = Array.isArray(a) ? a : (a?.otthonok || a?.haztartasok || []);
    const f = hs.flatMap((h) => h.fiokok).find((x) => x.sid === sid);
    const t = (f?.ellenorzes || []).find((x) => x.kulcs === kulcs);
    if (!t) return;
    const u = f.ugyfel || {}, ma = new Date().toLocaleDateString("hu-HU");
    const szam_ = (v) => String(v).replace(".", ",");
    const torzs = t.tipus === "regisztercsere"
      ? `<p>A ${nap(t.kelte)} kelt, <b>${esc(t.sorszam)}</b> sorszámú elszámoló számla (elszámolási időszak: ${nap(t.tol)} – ${nap(t.ig)}) a „H” tarifás mérő két regiszterét felcserélve számolja el: a téli (1.81) időszakra ${szam_(t.mvm_teli)} kWh-t, a nyári (1.82) időszakra ${szam_(t.mvm_nyari)} kWh-t számlázott.</p>
         <p>A mérő regiszterállásai és a folyamatos (óránkénti) mérésem szerint az időszakban a téli fogyasztás <b>${szam_(t.mert_teli)} kWh</b>, a nyári <b>${szam_(t.mert_nyari)} kWh</b> volt. A nyári mennyiség a drágább díjtételekkel került elszámolásra, így a számla a díjszabás szerint kb. <b>${ft(-t.hatas_ft)}</b>-tal több a helyesnél (helyes díj kb. ${ft(t.szamolt_ft)} a számlázott ${ft(t.szamla_ft)} helyett).</p>
         <p>Kérem a számla felülvizsgálatát és helyesbítését, a különbözet jóváírását.</p>`
      : t.tipus === "csatorna_tobblet"
      ? `<p>A ${nap(t.kelte)} kelt, <b>${esc(t.sorszam)}</b> sorszámú számla (elszámolt időszak: ${nap(t.tol)} – ${nap(t.ig)}) a mért <b>${szam_(t.ivoviz)} m³</b> ivóvízre <b>${szam_(t.csatorna)} m³</b> szennyvizet (csatornadíjat) számláz – például a szennyvízdíj tétele kétszer szerepel rajta. Az elvezetett szennyvíz mennyisége nem lehet több a mért ivóvíz-fogyasztásnál.</p>
         <p>A ${szam_(t.csatorna - t.ivoviz)} m³ többlet csatornadíja (a hozzá tartozó vízterhelési díjjal) kb. <b>${ft(-t.hatas_ft)}</b>; a helyes díj így kb. ${ft(t.szamolt_ft)} a számlázott ${ft(t.szamla_ft)} helyett.</p>
         <p>Kérem a számla helyesbítését (helyesbítő számla kiállítását), és ha a számlát már befizettem, a különbözet jóváírását a folyószámlámon.</p>`
      : t.tipus === "nem_szamlazott"
      ? `<p>A ${nap(t.kelte)} kelt, <b>${esc(t.sorszam)}</b> sorszámú elszámoló számla (elszámolási időszak: ${nap(t.tol)} – ${nap(t.ig)}) mérősorai szerint az időszakban <b>${szam_(t.mennyiseg_mert)} kWh</b> fogyott, a számla azonban csak <b>${szam_(t.mennyiseg_szamlazott)} kWh</b>-t számláz ki („Fogyasztás összesen”), miközben a korábbi részszámlákat jóváírja.</p>
         <p>Kérem a számla felülvizsgálatát és helyesbítését, hogy az elszámolás a tényleges fogyasztás szerint történjen (becslésem szerint a helyes díj kb. ${ft(t.szamolt_ft)}, a számla szerinti ${ft(t.szamla_ft)} helyett), és tájékoztatást arról, hogyan rendezik a különbözetet.</p>`
      : `<p>A ${nap(t.kelte)} kelt, <b>${esc(t.sorszam)}</b> sorszámú számla (elszámolási időszak: ${nap(t.tol)} – ${nap(t.ig)}) díja ${ft(t.szamla_ft)}, a mérőállások és a díjszabás szerint számolt díj kb. ${ft(t.szamolt_ft)}.</p>
         <p>Kérem a számla felülvizsgálatát, és tájékoztatást az eltérés okáról.</p>`;
    const szolg = f.utem?.szolgaltato || "";
    const cimzett = /MVM/i.test(szolg) ? "MVM Next Energiakereskedelmi Zrt.<br>Ügyfélszolgálat (ugyfelszolgalat@mvm.hu)" : `${esc(szolg || "Szolgáltató")}<br>Ügyfélszolgálat`;
    const level = `<p>${cimzett}</p>
      <p><b>Tárgy: számlakifogás – ${esc(t.sorszam)} sorszámú számla</b></p>
      <p>Felhasználó: ${esc(u.nev || "…")}<br>Felhasználó azonosító: ${esc(u.azonosito || "…")}<br>Felhasználási hely: ${esc(u.hely || "…")}${f.kozmu === "viz" ? (u.mero ? `<br>Vízmérő: ${esc(u.mero)}` : "") : `<br>Mérési pont: ${esc(u.meresi_pont || "…")}`}</p>
      <p>Tisztelt Ügyfélszolgálat!</p>${torzs}
      <p>Mellékelem a számla másolatát. Válaszukat a fenti elérhetőségeken várom.</p>
      <p>Kelt: ${ma}</p><p>Tisztelettel:<br><br>……………………………<br>${esc(u.nev || "")}</p>`;
    const d = this.shadowRoot.getElementById("reklamdlg");
    this.shadowRoot.getElementById("reklambody").innerHTML = `<div class="level">${level}</div>
      <p class="kicsi">A forint-összegek a Rezsikövető tájékoztató számításai (a díjszabás és a mérés szerint); a szolgáltató helyesbítése ettől eltérhet. Küldés előtt nézd át, és csatold a számlát.</p>`;
    this._reklamLevel = level;
    if (!d.open) d.showModal();
  }

  _reklamNyomtat() {
    const html = `<!doctype html><html lang="hu"><head><meta charset="utf-8"><title>Számlakifogás</title><style>
      @page { size: A4; margin: 22mm 20mm; } body { font: 11pt/1.5 "Segoe UI", Roboto, Arial, sans-serif; color: #000; } p { margin: 0 0 10pt; }
    </style></head><body>${this._reklamLevel || ""}</body></html>`;
    this._nyomtatoKeret?.remove();
    const f = (this._nyomtatoKeret = document.createElement("iframe"));
    f.setAttribute("aria-hidden", "true");
    Object.assign(f.style, { position: "fixed", right: "0", bottom: "0", width: "0", height: "0", border: "0" });
    document.body.appendChild(f);
    f.contentDocument.open();
    f.contentDocument.write(html);
    f.contentDocument.close();
    setTimeout(() => { f.contentWindow.focus(); f.contentWindow.print(); }, 300);
  }

  // Jóváhagyásra váró (a számlamappába érkezett) számlák: mi változna velük, összevetve a saját méréssel.
  _fuggoBlokk(h) {
    const fiokok = h.fiokok.filter((f) => (f.fuggo || []).length);
    if (!fiokok.length) return "";
    const TIP = { resz: "részszámla", elszamolo: "elszámoló", vegszamla: "végszámla", storno: "stornó", egyeb: "számla", eloiras: "előírás" };
    const CS = { vetelezes: "1.8.0 / fő", h_teli: "1.81 téli", h_nyari: "1.82 nyári", almero: "almérő", betaplalas: "betáplálás" };
    return fiokok.map((f) => {
      const e = f.fuggo_elonezet;
      const szamlak = (e?.szamlak || f.fuggo).map((x) => `<div class="fuggoszamla">
        <b>${esc(x.sorszam)}</b> · ${TIP[x.tipus] || esc(x.tipus || "")} · kelte ${nap(x.kelte)}${x.idoszak ? ` · ${nap(x.idoszak[0])} – ${nap(x.idoszak[1])}` : ""} · fizetendő <b>${x.osszeg != null ? ft(Number(x.osszeg)) : "–"}</b>${x.ai ? ` · <span class="cimkeszalag" title="${esc(`AI-val kiolvasva (${x.fajl}), az adatait te ellenőrizted${x.ai_megerositve ? " – ellentmondással, megerősítve" : ""}`)}">AI-val kiolvasva</span>` : String(x.forras || "").startsWith("sablon:") ? ` · <span class="cimkeszalag" title="${esc(`A korábban jóváhagyott számlából készült saját beolvasóval (${String(x.forras).slice(7)}) – AI nélkül`)}">saját beolvasóval</span>` : ""}
        ${x.szamla_ft != null && x.szamolt_ft != null ? `<div class="kicsi">A számla díja ${ft(x.szamla_ft)} · a saját mérésünk szerint ${ft(x.szamolt_ft)}${x.szamla_mennyiseg != null && x.szamolt_mennyiseg != null ? ` · ${szam(x.szamla_mennyiseg)} / ${szam(x.szamolt_mennyiseg)} ${esc(f.egyseg || "")}` : ""}${x.mert === false ? " (az időszak egyik végén nincs valódi mérőállás – a saját érték részben becsült)" : ""}</div>` : ""}
        ${(x.figyelmeztetes || []).map((m) => `<div class="kicsi figyszoveg">Figyelem: ${esc(m)}</div>`).join("")}</div>`).join("");
      const SOR = [["eddig", "Eddig (folyó időszak)"], ["varhato", "Várható (folyó időszak)"], ["kovetkezo", "Következő számla"],
        ["esedekes", "Ebben a hónapban esedékes"], ["ha_ma", "Ha ma lenne az elszámolás"], ["eves_egyenleg", "Éves egyenleg"], ["keret_hatra", "Hátralévő keret"]];
      const ertek = (k, v) => (v == null ? "–" : k === "keret_hatra" ? szam(v, f.egyseg) : ft(v));
      const sorok = e ? SOR.filter(([k]) => e.elotte?.[k] != null || e.utana?.[k] != null).map(([k, n]) => {
        const a = e.elotte?.[k], b = e.utana?.[k], valt = a !== b;
        return `<tr class="${valt ? "valt" : ""}"><th scope="row">${n}</th><td>${ertek(k, a)}</td><td>${ertek(k, b)}</td></tr>`;
      }).join("") : "";
      const allasok = (e?.uj_allasok || []).map((x) => `${nap(x.datum)}: ${allas(x.allas)} (${CS[x.csatorna] || esc(x.csatorna)})`).join(" · ");
      return `<div class="fuggo" role="region" aria-label="Jóváhagyásra váró számla – ${esc(f.nev)}">
        <div class="fuggocim"><ha-icon icon="mdi:file-document-alert-outline"></ha-icon><b>${esc(f.nev)}: új számla jóváhagyásra vár</b></div>
        ${szamlak}
        ${e ? `${e.hiba ? `<div class="kicsi figyszoveg">Az újraszámolás hibát adott: ${esc(e.hiba)}</div>` : ""}
          <div class="tablagorgeto"><table class="fuggotabla"><thead><tr><th></th><th>Most</th><th>Jóváhagyás után</th></tr></thead><tbody>${sorok}</tbody></table></div>
          ${allasok ? `<div class="kicsi">Átvett mérőállások: ${allasok}</div>` : `<div class="kicsi">A számlán nincs új valódi mérőállás (pl. becsült részszámla).</div>`}`
        : `<div class="kicsi">Az előnézet számolása folyamatban…</div>`}
        ${this._admin ? `<div class="gombok fuggogombok">
          <button type="button" data-fuggo="elvet" data-sid="${f.sid}" data-entry="${h.entry_id}">Elvetés</button>
          <button type="button" class="fo" data-fuggo="jovahagy" data-sid="${f.sid}" data-entry="${h.entry_id}">Jóváhagyás</button>
        </div>` : ""}
        <div class="kicsi">Jóváhagyás: a számla és a mérőállásai bekerülnek, minden újraszámolódik. Elvetés: nem kerül be (a fájl a mappában marad, később újraolvasható).</div>
      </div>`;
    }).join("");
  }

  _esedekesLista(h) {
    const sorok = h.fiokok.filter((f) => (f.esedekes && f.esedekes.e_havi_osszesen > 0) || f.uton_szamlak?.length).map((f) => {
      const e = f.esedekes || { e_havi_szamlak: [], e_havi_varhato: 0 };
      const kiallitott = e.e_havi_szamlak.map((x) => `${nap(x.kelte)}: ${ft(x.osszeg)} (${f.kozmu === "kozos" ? "előírás" : "kiállítva"})`);
      const varhato = e.e_havi_varhato > 0 ? [`<span class="esedekesmajd">${nap(e.kovetkezo_datum)} körül kb. ${ft(e.e_havi_varhato)}${e.elmaradt ? " – késik" : ""}</span>`] : [];
      const uton = (f.uton_szamlak || []).map((x) => `<span class="esedekesmajd">${nap(x.tol)} – ${nap(x.ig)}: ${x.levonva && !x.osszeg ? "nincs fizetendő (túlfizetésből)" : `kb. ${ft(x.osszeg)}`} (még nem érkezett)</span>`);
      return `<li><b>${esc(f.nev)}</b>: ${[...kiallitott, ...varhato, ...uton].join(", ")}</li>`;
    });
    return sorok.length ? `<ul class="esedekes">${sorok.join("")}</ul>` : "";
  }

  _fiok(f) {
    // A túlfizetés beszámítása a következő számlába (ha van): a kártya több helyén is kell.
    const kovB = f.beszamitas?.szamlak?.[0];
    // A várható díj csempe csak akkor szürke, ha a túlfizetés épp az aktuális időszak számláját fedezi (nem egy korábbi,
    // még nem érkezett számlát).
    const sajatIdoszak = !!(kovB && !kovB.idoszak && f.varhato && Math.abs(kovB.dij - f.varhato.osszeg) < 1);
    const fedezett = sajatIdoszak && !kovB.fizetendo;
    // A következő (ütem szerinti) számla – ha épp ezt fedezi a túlfizetés, a fizetendő-csempék ezt jelzik.
    const kovFedez = !!(kovB && kovB.datum && f.esedekes?.kovetkezo_datum && kovB.datum === f.esedekes.kovetkezo_datum);
    const fedezCls = (kiallitott) => (kovFedez && !kiallitott && !kovB.fizetendo ? " fedezett" : null);
    const fedezSzoveg = (kiallitott) => (!kovFedez || kiallitott ? ""
      : `<div class="kicsi">${kovB.fizetendo ? `fizetendő kb. ${ft(kovB.fizetendo)} – a többit a túlfizetés fedezi` : "fizetendő 0 Ft – a túlfizetés fedezi"}</div>`);
    const ikon = IKON[f.kozmu] || "mdi:cash";
    // Átalányos, de diktálás szerint (havonta elszámolóval) számlázott fiók: a mért diktálásos fiók kártyája – az
    // átalányt nem számlázzák, csak a fenti tájékoztató sorban marad.
    if (f.diktalas_szerint) f = { ...f, atalany_info: f.atalany, atalany: null, reszszamlas: false, szamlazasi: null };
    if (!f.eddig) {
      return `<div class="kartya"><div class="kfej"><ha-icon icon="${ikon}"></ha-icon><div><div class="knev">${esc(f.nev)}</div></div>${this._menu3(f)}</div>
        <div class="hiba">${esc(f.hiba || "nincs adat")}</div></div>`;
    }
    const diktalasos = ["diktalas", "atalany"].includes(f.elszamolas_mod);
    const idoszak = idoszakSzoveg(f.idoszak.tol, f.idoszak.ig, diktalasos);
    const negyedev = f.idoszak.honapok > 1;
    const egyseg = f.egyseg === "db" ? "" : f.egyseg;
    const blokkok = [];
    if (f.megszunt) {
      const es = f.esedekes || {};
      const vegszamla = f.fix_dij
        ? (es.nincs_tobb ? "A végszámla megérkezett, több számla nem várható."
          : es.vegszamla ? `${es.kovetkezo_datum !== es.vegszamla.datum ? `Még esedékes: ${nap(es.kovetkezo_datum)} körül ${ft(es.kovetkezo_osszeg)}; ` : ""}végszámla ${nap(es.vegszamla.datum)} körül, kb. ${ft(es.vegszamla.osszeg)} (a lezárásig tartó töredék időszak díja), utána nincs több számla.` : "")
        : "A számolás itt megállt; a végszámla érkezéséig „még nem érkezett számla”.";
      blokkok.push(`<div class="lezartfiok"><ha-icon icon="mdi:archive-lock-outline"></ha-icon><span><b>Lezárva ${nap(f.megszunt.datum)}</b> – végelszámolás${f.megszunt.allas != null ? ` · záró állás ${allas(f.megszunt.allas)} ${egyseg}` : ""}. ${vegszamla}</span></div>`);
    }
    if (f.szunetel) {
      const sz_ = f.szunetel;
      blokkok.push(sz_.most
        ? `<div class="lezartfiok"><ha-icon icon="mdi:pause-circle-outline"></ha-icon><span><b>A számlázás szünetel ${nap(sz_.tol)}${sz_.ig ? ` – ${nap(sz_.ig)}` : ""}</b> – erre az időre a Rezsikövető semmit nem számol (se fogyasztást, se alapdíjat, se minimumot), és számlát sem vár.</span></div>`
        : `<div class="nemesedekes">${sz_.ig && sz_.ig < new Date().toISOString().slice(0, 10) ? "A számlázás szünetelt" : "A számlázás szünetel majd"}: ${nap(sz_.tol)}${sz_.ig ? ` – ${nap(sz_.ig)}` : " – "} (erre az időre nincs díj).</div>`);
    }
    // Átalány: a havi fizetendő az átalány napra leosztva; a tényleges fogyasztás alatta, másodlagosan.
    const sz = f.szamlazasi;
    const inaktiv = sz && !sz.esedekes_most ? " inaktiv" : "";
    const szIdo = sz ? `${nap(sz.tol)} – ${nap(elozoNap(sz.ig))}` : "";
    // Utólagos számlázás: a számla hónapjában a megelőző (lezárt) időszak számlája esedékes.
    const szamlaSzoveg = sz ? (sz.kiallitott ? `${f.kozmu === "kozos" ? "előírva" : "kiállítva"} ${nap(sz.szamla_datum)}` : `várható ${nap(sz.szamla_datum)} körül`) : "";
    if (["aktualis", "reszleges"].includes(f.kezdes?.mod))
      blokkok.push(`<div class="nemesedekes">A költségkövetés kezdete: ${nap(f.kezdes.datum)} (a szenzor akkori értéke). Korábbi mérőállással – a fiók beállításaiban a kezdőnap és az óraállás – az időszak visszamenőleg is kiszámítható.</div>`);
    const viz = f.kozmu === "viz";
    if (sz && !sz.esedekes_most && !f.fix_dij)
      blokkok.push(`<div class="nemesedekes">Ebben a hónapban nincs számla – a következő ${nap(sz.kovetkezo_datum)} körül, kb. ${ft(sz.kovetkezo_osszeg)} (${szIdo}).</div>`);
    // Átalánynál a legutóbbi számla utáni diktált állás felülírja az átalányt: a következő számla a diktált fogyasztás díja.
    const dk = f.diktalt_szamla;
    // A fejléc „Következő számla” blokkja már mutatja – a kártyán nem ismételjük.
    const fejKov = !!f.fejlec?.kovetkezo;
    const diktaltCsempe = !dk || fejKov ? "" : dk.becsult
      ? `<div><div class="cimke">Következő számla (becslés a diktálásig) ${info(
        `A szolgáltató diktálás szerint számláz: a következő számla várhatóan a következő diktálással jön (a diktálási ablak közepe: ${nap(dk.datum)}). Becslés: a ${nap(dk.tol)} óta mért fogyasztás (saját mérő), napi átlaggal a diktálás napjáig kivetítve, a díjszabás szerint. Ha diktálsz, a diktált állás veszi át; a számla megérkezésekor a valódi összeg.`)}</div>
        <div class="ertek esedekesmajd">${ft(dk.osszeg)}</div><div class="kicsi">kb. ${szam(dk.mennyiseg, egyseg)} · ${nap(dk.tol)} – ${nap(dk.datum)} · az átalány helyett</div></div>`
      : `<div><div class="cimke">Következő számla (diktálás alapján) ${info(
      `Az utolsó számla elszámolt időszaka után (${nap(dk.tol)}-tól) diktált mérőállás (${nap(dk.datum)}: ${allas(dk.allas)}) felülírja az átalány mennyiségét – a szolgáltató a következő számlát a diktált fogyasztás szerint állítja ki. Egyszeri: az azutáni számla újra az átalány szerint jön, amíg nem diktálsz újra.`)}</div>
        <div class="ertek esedekesmajd">${ft(dk.osszeg)}</div><div class="kicsi">${szam(dk.mennyiseg, egyseg)} · ${nap(dk.tol)} – ${nap(dk.datum)} · az átalány helyett</div></div>`;
    // Az átalány fizetendője a számlázási ütemre (havi, kéthavi …), „eddig” nélkül – az átalányt kell fizetni.
    const utemHo = (sz && sz.honap) || f.utem?.szamlazas_honap || 1;
    const utemNev = utemHo > 1 ? `${TOBBHAVI[utemHo] || utemHo + " havi"} fizetendő (átalány)` : "Havi fizetendő (átalány)";
    if (f.atalany && sz && sz.fizetendo != null && sz.lezart) {
      const at = f.atalany;
      blokkok.push(`
      <div class="ket">
        <div><div class="cimke">Ebben a hónapban fizetendő</div><div class="ertek${fedezCls(sz.kiallitott) ?? (sz.kiallitott ? "" : " esedekesmajd")}">${ft(sz.fizetendo)}</div>
          <div class="kicsi">${(TOBBHAVI[sz.honap] || "").toLowerCase()} számla · ${szIdo} · ${szamlaSzoveg}</div>${fedezSzoveg(sz.kiallitott)}</div>
        ${viz && sz.mennyiseg_eddig != null ? `<div><div class="cimke">Fogyasztás a számlázott időszakban</div><div class="ertek">${szam(sz.mennyiseg_eddig, egyseg)}</div>
          <div class="kicsi">mért${sz.mennyiseg_becsult ? " · részben becsült" : ""}</div></div>`
        : viz ? "" : `<div><div class="cimke">Átalány ${info(`Az átalány forrása: ${esc(at.forras)}.`)}</div><div class="ertek">${szam(at.napi)} Ft/nap</div>
          <div class="kicsi">${sz.napok} nap · havonta ${ft(at.havi)}</div></div>`}
      </div>`);
    } else if (f.atalany && sz && sz.fizetendo != null && !(fejKov && !sz.kiallitott)) {
      const at = f.atalany;
      blokkok.push(`
      <div class="ket${inaktiv}">
        <div><div class="cimke">${utemNev} ${info(`Az átalány forrása: ${esc(at.forras)} · havonta ${ft(at.havi)}.`)}</div><div class="ertek${fedezCls(sz.kiallitott) ?? (sz.kiallitott ? "" : " esedekesmajd")}">${ft(sz.diktalt ? Math.round(at.napi * sz.napok) : sz.fizetendo)}</div>
          <div class="kicsi">${szIdo} · ${szamlaSzoveg}${viz ? "" : ` · ${sz.napok} nap × ${szam(at.napi)} Ft`}</div>${fedezSzoveg(sz.kiallitott)}</div>
        ${diktaltCsempe}
      </div>`);
    } else if (f.atalany && !fejKov) {
      const at = f.atalany;
      blokkok.push(`
      <div class="ket">
        <div><div class="cimke">${utemNev} ${info(`Az átalány forrása: ${esc(at.forras)}.`)}</div><div class="ertek${fedezCls(false) ?? " esedekesmajd"}">${ft(at.havi * utemHo)}</div>
          <div class="kicsi">${utemHo > 1 ? `${utemHo} × havi ${ft(at.havi)}` : `napi ${szam(at.napi)} Ft`}${f.esedekes?.kovetkezo_datum && !dk ? ` · következő számla ${nap(f.esedekes.kovetkezo_datum)} körül` : ""}</div>${fedezSzoveg(false)}</div>
        ${diktaltCsempe}
      </div>`);
    }
    // Átalánynál nincs tételes számítás: csak a fogyasztás, összevetve az átalány mennyiségével.
    if (f.atalany && !f.fix_dij && sz && sz.mennyiseg_varhato != null && sz.lezart && !viz) {
      const elteres = sz.atalany_mennyiseg != null ? sz.mennyiseg_eddig - sz.atalany_mennyiseg : null;
      blokkok.push(`
      <div class="ket">
        <div><div class="cimke">Fogyasztás a számlázott időszakban</div><div class="ertek">${szam(sz.mennyiseg_eddig, egyseg)}</div>
          <div class="kicsi">${szIdo}${sz.mennyiseg_becsult ? " · részben becsült" : ""}</div></div>
        ${viz ? "" : `<div><div class="cimke">Átalány az időszakra</div><div class="ertek">${sz.atalany_mennyiseg != null ? szam(sz.atalany_mennyiseg, egyseg) : "–"}</div>
          ${elteres != null ? `<div class="kicsi"><span class="${elteres > 0 ? "figyszoveg" : ""}">${elteres > 0 ? "+" : ""}${szam(elteres, egyseg)}</span> az átalányhoz képest</div>` : ""}</div>`}
      </div>`);
    } else if (f.atalany && !f.fix_dij && sz && sz.mennyiseg_varhato != null && !(viz && sz.lezart)) {
      const elteres = sz.atalany_mennyiseg != null ? sz.mennyiseg_varhato - sz.atalany_mennyiseg : null;
      blokkok.push(`
      <div class="ket${inaktiv}">
        <div><div class="cimke">Fogyasztás eddig (${szIdo})</div><div class="ertek">${szam(sz.mennyiseg_eddig, egyseg)}</div></div>
        <div><div class="cimke">Várható ${(TOBBHAVI[sz.honap] || "").toLowerCase()} fogyasztás</div><div class="ertek">${szam(sz.mennyiseg_varhato, egyseg)}</div>
          ${f.varhato.napi_atlag !== null ? `<div class="kicsi">napi ${szam(f.varhato.napi_atlag, egyseg)}</div>` : ""}</div>
      </div>
      ${sz.atalany_mennyiseg != null && !viz ? `<div class="kicsi${inaktiv}">Átalány az időszakra: ${szam(sz.atalany_mennyiseg, egyseg)}${
        elteres != null ? ` · várhatóan <span class="${elteres > 0 ? "figyszoveg" : ""}">${elteres > 0 ? "+" : ""}${szam(elteres, egyseg)}</span> az átalányhoz képest` : ""}</div>` : ""}`);
    } else if (f.atalany && !f.fix_dij && !(viz && sz && sz.lezart)) {
      const at = f.atalany;
      // Szaldós napelem: az átalány a nettó (vételezés − betáplálás) fogyasztáshoz mérendő.
      const be = at.betaplalas;
      const netto = be && f.varhato.mennyiseg != null ? Math.max(f.varhato.mennyiseg - be.varhato, 0) : null;
      const vart = netto ?? f.varhato.mennyiseg;
      const elteres = at.mennyiseg_idoszak != null && vart != null ? vart - at.mennyiseg_idoszak : null;
      blokkok.push(`
      <div class="ket">
        <div><div class="cimke">${be ? "Vételezés eddig" : "Fogyasztás eddig"}</div><div class="ertek">${szam(f.eddig.mennyiseg, egyseg)}</div></div>
        <div><div class="cimke">${be ? "Várható vételezés" : "Várható fogyasztás"}</div><div class="ertek">${szam(f.varhato.mennyiseg, egyseg)}</div>
          ${f.varhato.napi_atlag !== null ? `<div class="kicsi">napi ${szam(f.varhato.napi_atlag, egyseg)}</div>` : ""}</div>
      </div>
      ${be ? `<div class="kicsi">Betáplálás eddig ${szam(be.eddig, egyseg)}, várhatóan ${szam(be.varhato, egyseg)} · nettó várhatóan <b>${szam(netto, egyseg)}</b> (vételezés − betáplálás)</div>` : ""}
      ${at.mennyiseg_idoszak != null ? `<div class="kicsi">Átalány az időszakra (${at.napok} nap): ${szam(at.mennyiseg_idoszak, egyseg)}${
        elteres != null ? ` · várhatóan <span class="${elteres > 0 ? "figyszoveg" : ""}">${elteres > 0 ? "+" : ""}${szam(elteres, egyseg)}</span> ${be ? "nettó " : ""}az átalányhoz képest` : ""}</div>` : ""}`);
    } else if (viz && f.atalany && sz && sz.lezart) {
      // Víz, lezárt számlázási időszak: a fizetendő és a fogyasztás már fent, egy sorban áll.
    } else if (f.gaz_atalany) {
      // Gázmérő nélküli fix átalány: a havi díj és a számlázás alapja – mérés, keret, előrejelzés nincs.
      const g = f.gaz_atalany, havi = f.varhato.osszeg;
      // Többhavi számlázásnál (pl. negyedéves, a negyedév közepén az adott negyedévről) a számla díja és napja.
      const gn = f.utem?.szamlazas_honap || 1;
      const gsz = f.szamlazasi;
      const elsoCsempe = gn > 1
        ? `<div><div class="cimke">${TOBBHAVI[gn] || gn + " havi"} díj</div><div class="ertek">${ft(gsz?.fizetendo ?? havi * gn)}</div>
            <div class="kicsi">${gsz ? `${nap(gsz.tol)} – ${nap(elozoNap(gsz.ig))} · ${gsz.kiallitott ? `kiállítva ${nap(gsz.szamla_datum)}` : `számla ${nap(gsz.szamla_datum)} körül`}` : `${gn} × havi ${ft(havi)}`}</div></div>`
        : `<div><div class="cimke">Havi díj</div><div class="ertek">${ft(havi)}</div>
            <div class="kicsi">minden hónapban ugyanannyi</div></div>`;
      blokkok.push(`
      <div class="ket">
        ${elsoCsempe}
        <div><div class="cimke">Éves díj</div><div class="ertek">${ft(havi * 12)}</div>
          <div class="kicsi">12 × ${ft(havi)}${gn > 1 ? " (havi díj)" : ""}</div></div>
      </div>
      <div><div class="cimke">A számlázás alapja ${info("Ahol nincs gázóra (pl. csak gáztűzhely van), az MVM havi fix mennyiséget számláz a szobaszám és a tűzhely fajtája szerint, országosan egységes egységáron (MVM: „Földgázdíjak mérő nélküli (átalánydíjas) ügyfeleknek”). Mérés, leolvasás, kedvezményes keret és éves elszámolás nincs. Ha a lakás vagy a tűzhely változik, a fiók beállításában módosítsd.")}</div>
        <div class="tablagorgeto"><table class="bontas"><tbody>
          <tr><td>Elszámolás<div class="kicsi">gázmérő nélküli átalánydíj</div></td><td>MVM-táblázat</td></tr>
          <tr><td>Lakás<div class="kicsi">szobaszám</div></td><td>${String(g.szobaszam).replace(".", ",")} szoba</td></tr>
          <tr><td>Gáztűzhely</td><td>${TUZHELY[g.tuzhely] || g.tuzhely}</td></tr>
          <tr><td>Havi mennyiség</td><td>${szam(g.mj, "MJ")}</td></tr>
          ${g.egysegar != null ? `<tr><td>Egységár<div class="kicsi">nettó · bruttó (${szam(g.afa)}% ÁFA)</div></td><td>${String(g.egysegar).replace(".", ",")} · ${String(g.egysegar_brutto).replace(".", ",")} Ft/MJ</td></tr>` : ""}
          ${g.havi_netto != null ? `<tr><td>Havi díj<div class="kicsi">${szam(g.mj, "MJ")} × egységár</div></td><td>${ft(g.havi_netto)} + ÁFA = <strong>${ft(havi)}</strong></td></tr>` : ""}
        </tbody></table></div></div>`);
    } else if (f.fix_dij && sz) {
    // Fix díj, utólagos számlázás (pl. MOHU: a negyedév után számláz).
    // Csak az esedékesség hónapjában „fizetendő”; máskor a következő esedékesség hónapja, az összeg szürkén, dőlten.
    const dij = `${(TOBBHAVI[sz.honap] || "").toLowerCase()} díj`;
    const st = f.szamla_stat;
    // Idényes díj (pl. üdülő hulladékdíja): az idényen kívüli negyedévre nincs díj, nem jön számla.
    const idenyen_kivul = !sz.esedekes_most && !(sz.kovetkezo_osszeg ?? sz.fizetendo) && st?.kovetkezo_datum;
    blokkok.push(idenyen_kivul
      ? `<div><div class="cimke">Idényen kívül</div><div class="ertek esedekesmajd">0 Ft</div>
          <div class="kicsi">${szIdo}: nincs díj, nem jön számla · a következő ${nap(st.kovetkezo_datum)} körül, kb. ${ft(st.kovetkezo_osszeg)}</div></div>`
      : sz.esedekes_most
      ? `<div><div class="cimke">Ebben a hónapban fizetendő</div><div class="ertek${sz.kiallitott ? "" : " esedekesmajd"}">${ft(sz.fizetendo)}</div>
          <div class="kicsi">${dij} · ${szIdo} · ${szamlaSzoveg}</div></div>`
      : `<div><div class="cimke">Esedékes: ${honapNev(sz.kovetkezo_datum)}</div><div class="ertek esedekesmajd">${ft(sz.kovetkezo_osszeg ?? sz.fizetendo)}</div>
          <div class="kicsi">${dij} · ${szIdo}</div></div>`);
    } else if (!f.fejlec?.folyo) {
    // Mennyibe került? / Mennyi lesz? – ha a következő számlát a túlfizetés teljesen fedezi, a várható díj szürke.
    // (Ha van fejléc, a folyó időszak ott áll; ez csak a lezárt fiók utolsó időszakához kell.)
    blokkok.push(`
      <div class="ket${inaktiv}">
        <div><div class="cimke">${f.megszunt ? `Utolsó időszak (${nap(f.idoszak.tol)} – ${nap(elozoNap(f.megszunt.datum))})` : negyedev ? "Ebben a negyedévben" : "Eddig"}</div>
          <div class="ertek">${ft(f.eddig.osszeg)}</div>
          ${f.eddig.havi_resz ? `<div class="dolt">havonta ${ft(f.eddig.havi_resz)}</div>` : ""}
          ${!f.fix_dij ? `<div class="kicsi">${szam(f.eddig.mennyiseg, egyseg)}${f.eddig.becsult ? ` · becsült ${info(
            `Az utolsó mérőállás (${nap(f.idoszak.tol)}) óta nincs mért adat (nincs mérő-szenzor, vagy kiesett): a fogyasztás a legutóbbi időszak napi átlaga × az eltelt napok. A következő leolvasás vagy diktálás után valódi érték lesz. Az „Eddig” csak a már elmúlt hónapfordulók alapdíját tartalmazza.`)}` : ""}</div>` : ""}</div>
        ${f.megszunt ? "" : `<div><div class="cimke">${fedezett ? `Várható díj ${info("Az időszak várható költsége – ennyi lesz a számla díja. A folyószámlán lévő túlfizetés fedezi, ezért nem kell kifizetni; lásd lent: Következő számla.")}` : "Várható"}</div>
          <div class="ertek${fedezett ? " fedezett" : f.reszszamlas || f.fix_dij ? "" : " esedekesmajd"}">${ft(f.varhato.osszeg)}</div>
          ${fedezett ? `<div class="kicsi">nem kell fizetni – a túlfizetés fedezi</div>` : sajatIdoszak ? `<div class="kicsi">ebből fizetendő kb. ${ft(kovB.fizetendo)} – a többit a túlfizetés fedezi</div>` : ""}
          ${f.varhato.havi_resz ? `<div class="dolt">${f.idoszak.honapok > 1 ? "havonta" : "havi átlagban kb."} ${ft(f.varhato.havi_resz)}</div>` : ""}
          ${!f.fix_dij && f.varhato.napi_atlag !== null && !f.idenyszakok ? `<div class="kicsi">napi ${szam(f.varhato.napi_atlag, egyseg)}${
            f.diktalas_szerint && f.diktalt_szamla?.becsult ? ` · a következő számla ${info(
              `A szolgáltató diktálás szerint számláz (az utolsó két számla elszámoló, vagy nemrég diktáltál): a következő számla a legutóbbi számla utáni naptól a következő diktálásig (a diktálási ablak közepe: ${nap(f.diktalt_szamla.datum)}) mért fogyasztásé. Becslés: a saját mérés napi átlaggal a diktálás napjáig kivetítve; ha diktálsz, a diktált állás veszi át.`)}` : ""}</div>` : ""}</div>`}
      </div>`);
    }
    // Víz: tételes bontás – vízdíj a főmérő, csatornadíj a főmérő − almérő mennyisége után.
    if (sz && sz.bontas && f.kozmu === "viz") {
      const bo = sz.bontas;
      const csatMenny = bo.almero_m3 != null
        ? `${szam(bo.fo_m3, "m³")} − ${szam(bo.almero_m3, "m³")} = ${szam(bo.csatorna_m3, "m³")}`
        : szam(bo.csatorna_m3, "m³");
      const cim = sz.lezart ? `Díj a mért fogyasztás szerint (${szIdo})` : `Díj eddig (${nap(sz.tol)} – ma)`;
      blokkok.push(`
        <div class="${sz.lezart ? "" : "inaktiv"}"><div class="cimke">${cim} ${info(
          "Vízdíj a főmérő teljes mennyisége után; csatornadíj a főmérő mínusz a locsolási almérő mennyisége után (az almérő levonása csak a locsolási idényben, május 1. – szeptember 30. jár); alapdíj havonta (ivóvíz + szennyvíz); mind +27% ÁFA. "
          + "A szolgáltató egész m³-re kerekített óraállásokkal számláz, ezért a díj a számlázott (egész) mennyiségből számol; zárójelben a szenzor szerint mért mennyiség."
          + (bo.meleg_szennyviz_ft != null ? " Meleg szennyvíz: a távhőről kapott melegvíz szennyvizét a vízmű a csatornadíjjal számlázza – hónaponként a távhőszámla melegvíz-mennyisége (számla híján az átalány), legalább 1 m³." : "")
          + (f.atalany ? ` A számla az átalányt tartalmazza (${ft(sz.fizetendo)}); a különbség az elszámoló számlán rendeződik.` : "")
          + (bo.becsult ? " Részben becsült: a mérőállások közötti napok arányosítva." : ""))}</div>
          <div class="tablagorgeto"><table class="bontas"><tbody>
            <tr><td>Vízdíj<div class="kicsi">főmérő: ${szam(bo.fo_m3, "m³")}${bo.fo_m3_mert != null && bo.fo_m3_mert !== bo.fo_m3 ? ` (mért: ${szam(bo.fo_m3_mert, "m³")})` : ""}</div></td><td>${ft(bo.viz_ft)}</td></tr>
            <tr><td>Csatornadíj<div class="kicsi">${bo.almero_m3 != null ? "főmérő − locsolási almérő: " : ""}${csatMenny}</div></td><td>${ft(bo.csatorna_ft)}</td></tr>
            ${bo.meleg_szennyviz_ft != null ? `<tr><td>Meleg szennyvíz<div class="kicsi">távhős melegvíz: ${szam(bo.meleg_szennyviz_m3, "m³")} (havonta a távhőszámla szerint, legalább 1 m³)</div></td><td>${ft(bo.meleg_szennyviz_ft)}</td></tr>` : ""}
            <tr><td>Alapdíj<div class="kicsi">ivóvíz + szennyvíz</div></td><td>${ft(bo.alapdij_ft)}</td></tr>
            <tr><td><strong>Összesen</strong></td><td><strong>${ft(bo.osszesen_ft)}</strong></td></tr>
          </tbody></table></div>
</div>`);
    }
    // H-tarifa: téli (1.81) és nyári (1.82) külön – októberben és áprilisban mindkettő. A2: csúcs és völgy.
    const a2 = !!(f.idenyszakok && (f.idenyszakok.eddig?.csucs || f.idenyszakok.eddig?.volgy || f.idenyszakok.varhato?.csucs || f.idenyszakok.varhato?.volgy));
    if (f.idenyszakok) {
      const nevek = { teli: "Téli (1.81, H-ár, keret nélkül)", nyari: "Nyári (1.82, A1 ár)", csucs: "Csúcsidőszak (1.8.1)", volgy: "Völgyidőszak (1.8.2)" };
      const sorok = (a2 ? ["csucs", "volgy"] : ["teli", "nyari"]).filter((k) => f.idenyszakok.eddig?.[k] || f.idenyszakok.varhato?.[k]).map((k) => {
        const e = f.idenyszakok.eddig?.[k] || {}, v = f.idenyszakok.varhato?.[k] || {};
        return f.atalany
          ? `<tr><td>${nevek[k]}</td><td>${szam(e.mennyiseg, "kWh")}</td><td>${szam(v.mennyiseg, "kWh")}</td></tr>`
          : `<tr><td>${nevek[k]}</td><td>${szam(e.mennyiseg, "kWh")}<div class="kicsi">${ft(e.energia_ft)}</div></td><td>${szam(v.mennyiseg, "kWh")}<div class="kicsi">${ft(v.energia_ft)}</div></td></tr>`;
      });
      const fej = "<th></th><th>Eddig</th><th>Várható</th>";
      if (sorok.length) blokkok.push(`
        <div><div class="cimke">${a2 ? "Csúcs- és völgyidőszak (A2)" : "Téli és nyári tarifa (téli: okt. 15. – ápr. 15.)"}</div>
          <div class="tablagorgeto"><table><thead><tr>${fej}</tr></thead><tbody>${sorok.join("")}</tbody></table></div></div>`);
    }
    // Hol tartok a keretben?
    if (f.keret && f.keret.osszes > 0) {
      const arany = Math.min(100, (100 * f.keret.felhasznalt) / f.keret.osszes);
      blokkok.push(`
        <div class="keret">
          <div class="cimke">${a2 ? `Kedvezményes keret – csúcs + völgy együtt ${info("Az A2 mérési pont egy 2 523 kWh/év kerete a két zónára közösen jár; a Rezsikövető a zónák között a fogyasztásuk arányában osztja meg.")}`
            : f.idenyszakok ? "Nyári (1.82) rezsicsökkentett keret – a téli H-árra nincs keret"
            : f.keret.mod === "eves" ? `Éves kedvezményes keret${f.keret.ev_tol ? ` (${nap(f.keret.ev_tol)}-tól)` : ""} ${info(f.kozmu === "gaz"
              ? "Az éves kedvezményes keret (63 645 MJ) és az év elejétől ténylegesen felhasznált mennyiség – a mérőállás-szenzorból, ennek híján a rögzített mérőállásokból. Átalánynál az év az éves elszámoló leolvasással, diktálásnál a kedvezményes évvel (augusztus 1.) indul."
              : "Átalánynál (egyenletes részszámla) a keret éves: a csík az elszámolási év elejétől felhasznált mennyiséget mutatja a teljes éves kerethez képest.")}`
            : f.keret.mod === "havi_sulyozott" ? `Kedvezményes keret – e számla (havonta súlyozott) ${info("Diktálásnál az MVM a gáz éves 63 645 MJ-os keretét hónapokra súlyozva adja (télen több, nyáron kevesebb; pl. január 12 365, július 512 MJ). Az e havi számla napjaira jutó rész; a ki nem használt keret a kedvezményes évben (aug. 1. – júl. 31.) később jár.")}`
            : "Kedvezményes keret"}</div>
          <div class="sav"><div class="toltes ${arany >= 100 ? "tele" : arany > 80 ? "kozel" : ""}" style="width:${arany}%"></div></div>
          <div class="kicsi">${szam(f.keret.felhasznalt, f.keret.egyseg)} / ${szam(f.keret.osszes, f.keret.egyseg)} · hátra ${szam(f.keret.hatralevo, f.keret.egyseg)}
          ${f.keret.atlepes ? ` · <span class="figyszoveg">elfogy ${nap(f.keret.atlepes)} körül</span>` : ""}</div>
          ${f.keret.idoszak ? `<div class="kicsi">ebben a számlában (havonta súlyozott keret): ${szam(f.keret.idoszak.felhasznalt, f.keret.egyseg)} / ${szam(f.keret.idoszak.osszes, f.keret.egyseg)}</div>` : ""}
          ${f.keret.savkorrekcio ? `<div class="kicsi">sávkorrekció ${f.keret.savkorrekcio > 0 ? "+" : ""}${szam(f.keret.savkorrekcio, f.keret.egyseg)} ${info(
            "A kedvezményes keret az elszámolási évben – az éves elszámoló leolvasástól a következőig – halmozódik, a következő évre nem vihető át. "
            + (f.keret.savkorrekcio > 0
              ? "Az év korábbi részében ki nem használt keret most piaci helyett kedvezményes áron jár – a számlán „sávkorrekció” sorként jelenik meg."
              : "Az év korábbi részében a keretnél többet számoltak kedvezményesen, ezt most visszarendezi."))}</div>` : ""}
        </div>`);
    }
    // A túlfizetés beszámítása a következő számlába: díj − túlfizetés = a számlán várható végösszeg; fizetendő (mínusz helyett 0).
    if (kovB) {
      const marad = kovB.szamlan < 0 ? -kovB.szamlan : 0;
      blokkok.push(`
        <div><div class="cimke">Túlfizetés beszámítása a következő számlába${kovB.datum ? ` – ${nap(kovB.datum)} körül` : ""} ${info("A folyószámlán túlfizetés van: a szolgáltató a következő számlán beszámítja. Ha a túlfizetés nagyobb a számla díjánál, a számla végösszege mínuszos lesz – ilyenkor nincs fizetendő, a maradék túlfizetés a következő számlákon számítódik be.")}</div>
          <div class="tablagorgeto"><table class="bontas"><tbody>
            <tr><td>A számla díja<div class="kicsi">becslés${kovB.idoszak ? ` · ${nap(kovB.idoszak[0])} – ${nap(kovB.idoszak[1])}` : ""}</div></td><td>${ft(kovB.dij)}</td></tr>
            <tr><td>Túlfizetés beszámítása<div class="kicsi">a folyószámláról${f.beszamitas.kozos ? " (közös)" : ""}</div></td><td class="minuszft">−${ft(kovB.beszamitas)}</td></tr>
            <tr><td>A számlán várható végösszeg</td><td class="${kovB.szamlan < 0 ? "minuszft" : ""}">${ft(kovB.szamlan)}</td></tr>
            <tr><td><strong>Fizetendő</strong></td><td><strong>${kovB.fizetendo ? ft(kovB.fizetendo) : "0 Ft – nincs fizetendő"}</strong></td></tr>
          </tbody></table></div>
          ${marad ? `<div class="kicsi">A számla után megmaradó túlfizetés: ${ft(marad)} – a következő számlákon számítják be.</div>` : ""}</div>`);
    }
    // Lezárt időszak, amelyre még nem jött számla (pl. új fiók): becsült összeggel.
    if (f.uton_szamlak?.length) {
      const ossz = f.uton_szamlak.reduce((x, y) => x + y.osszeg, 0);
      const dij = f.uton_szamlak.reduce((x, y) => x + (y.osszeg_brutto ?? y.osszeg), 0);
      const reszben = f.uton_szamlak.some((y) => y.levonva);
      blokkok.push(`
        <div><div class="cimke">Még nem érkezett számla ${info("Lezárt időszak, amelyre még nem jött számla – várhatóan hamarosan megérkezik. Az összeg a Rezsikövető számítása a mért fogyasztásból (becsült); a számla beérkezésekor eltűnik innen. Az otthon „ebben a hónapban esedékes” összegében is szerepel.")}</div>
          <div class="ertek${reszben && !ossz ? " fedezett" : " esedekesmajd"}">${ft(reszben ? dij : ossz)}</div>
          ${reszben ? `<div class="kicsi">${ossz ? `fizetendő kb. ${ft(ossz)} – a többit a túlfizetés fedezi` : "fizetendő 0 Ft – a túlfizetés fedezi"}</div>` : ""}
          ${f.uton_szamlak.map((x) => `<div class="kicsi">${nap(x.tol)} – ${nap(x.ig)}: ${szam(Number(x.mennyiseg), egyseg)} · díj kb. ${ft(x.osszeg_brutto ?? x.osszeg)}</div>`).join("")}
          ${this._elsoSzamla(f, diktalasos)}</div>`);
    }
    // D (dinamikus) árszabás elemzés – csak A1 fióknál, és csak ha az elmúlt 12 hónapban volt kereten felüli
    // fogyasztás (a D tarifa csak azt árazza másképp; enélkül minden sor 0 lenne). Részletek külön ablakban.
    // Éves elszámolási kimutatás (MVM villany A1/H, számlákkal): a két éves leolvasás közti év vs. a számlák.
    if (this._evesLehet(f)) {
      blokkok.push(`
        <button type="button" class="dlink" data-eves="${f.sid}" data-entry="${this._entryId(f.sid)}">
          <ha-icon icon="mdi:file-table-outline"></ha-icon><span>Éves elszámolási kimutatás</span>
          <ha-icon class="chev" icon="mdi:chevron-right"></ha-icon></button>`);
    }
    if (f.d_osszevetes && f.d_osszevetes.idoszakok?.some((x) => x.keret_felett > 0)) {
      blokkok.push(`
        <button type="button" class="dlink" data-delemzes="${f.sid}">
          <ha-icon icon="mdi:chart-bell-curve-cumulative"></ha-icon><span>D tarifa elemzés</span>
          <ha-icon class="chev" icon="mdi:chevron-right"></ha-icon></button>`);
    }
    // Kell-e változtatni? – elszámolás, egyenleg. A „Ha ma lenne az elszámolás” csak átalányos fióknál (ott az éves
    // elszámolásig gyűlik a különbség) és lezárásnál; havonta elszámolt (diktálásos, leolvasásos) fióknál csak a
    // „még nem érkezett számla” ismétlése lenne.
    if (f.elszamolas && (f.reszszamlas || f.megszunt)) {
      const e = f.elszamolas;
      blokkok.push(`
        <div class="sor"><div><div class="cimke">${f.megszunt ? `Végelszámolás (${nap(f.megszunt.datum)})` : "Ha ma lenne az elszámolás"} ${info(
          `A legutóbbi elszámolás (${nap(e.tol)}) óta mért fogyasztás díja, mínusz az azóta kapott számlák. `
          + (e.egyenleg < 0
            ? (e.szamlak_db === 0 && f.esedekes
              ? `Azóta még nem jött számla – ez nem tartozás: a következő (${nap(f.esedekes.kovetkezo_datum)} körül, kb. ${ft(f.esedekes.kovetkezo_osszeg)}) ezt rendezi.`
              : "Az azóta kapott számlák ennyivel kevesebbek a mért fogyasztás díjánál.")
            : "Az azóta kapott számlák ennyivel többek a mért fogyasztás díjánál."))}</div>
          <div class="kicsi">${nap(e.tol)} óta: ${ft(e.tenyleges)} fogyasztás, ${ft(e.befizetve)} befizetve (${e.szamlak_db} számla)</div></div>
          <div class="ertek ${e.egyenleg < 0 ? "minusz" : "plusz"}">${e.egyenleg < 0 ? "−" : "+"}${ft(Math.abs(e.egyenleg))}</div></div>`);
    }
    if (f.egyenleg) {
      const e = f.egyenleg;
      const ciklusHo = (f.utem && f.utem.elszamolas_honap) || 12;
      const ciklusNev = ciklusHo === 6 ? "félévi" : "éves";
      const atalanyTeljes = f.atalany && f.atalany.havi != null ? f.atalany.havi * ciklusHo : null;
      blokkok.push(`
        <div class="sor"><div><div class="cimke">${ciklusHo === 6 ? "Félévi" : "Éves"} egyenleg (${nap(e.ev_tol)} – ${nap(e.ev_ig)}) ${info(
          `Várható ${ciklusNev} költség, szemben a befizetett és a még hátralévő részszámlákkal. `
          + (e.egyenleg < 0
            ? `Mínusz: az elszámoló számla (${nap(e.ev_ig)} után) várható összege – a részszámlák nem fedik le a teljes időszakot, a maradékot ez számlázza.`
            : `Plusz: az elszámoláskor (${nap(e.ev_ig)} után) várhatóan ennyi jár vissza.`)
          + (atalanyTeljes != null
            ? ` Átalány a teljes időszakra ${ft(atalanyTeljes)}: a várható költség ${ft(Math.abs(atalanyTeljes - e.varhato_eves))}-tal ${atalanyTeljes >= e.varhato_eves ? "kevesebb" : "több (valódi ráfizetés)"}.`
            : ""))}</div>
          <div class="kicsi">várható ${ciklusNev} költség ${ft(e.varhato_eves)} · befizetve ${ft(e.befizetve)} + hátralévő ${e.hatralevo_db} részszámla ${ft(e.hatralevo_reszszamla)}${e.megbizhato ? "" : " · <i>alacsony megbízhatóság</i>"}${atalanyTeljes != null
            ? ` · átalányhoz képest <span class="${atalanyTeljes < e.varhato_eves ? "figyszoveg" : ""}">${atalanyTeljes < e.varhato_eves ? "+" : "−"}${ft(Math.abs(atalanyTeljes - e.varhato_eves))}</span>`
            : ""}</div></div>
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
        <div class="sor"><div><div class="cimke">${f.kozmu === "kozos" ? "Előírások" : "Számlák"}</div>
          <div class="kicsi">utolsó 12 hónap ${ft(s.eves_osszeg)} (${s.eves_db} db) · ${f.esedekes?.szunetel
            ? `<span class="esedekesmajd">következő számla nem várható (a számlázás szünetel)</span>`
            : f.esedekes?.elmaradt
            ? `<span class="figyszoveg">esedékes volt ${nap(f.esedekes.kovetkezo_datum)} körül (kb. ${ft(f.esedekes.kovetkezo_osszeg)}) – még nem érkezett meg</span>`
            : `következő ${f.esedekes && (f.esedekes.kovetkezo_osszeg || f.esedekes.kovetkezo_osszeg_brutto != null || !s.kovetkezo_datum) ? `${nap(f.esedekes.kovetkezo_datum)} körül, <span class="esedekesmajd">${f.esedekes.kovetkezo_osszeg_brutto != null && !f.esedekes.kovetkezo_osszeg ? "nincs fizetendő (túlfizetésből)" : `kb. ${ft(f.esedekes.kovetkezo_osszeg)}`}</span>` : s.kovetkezo_datum ? `${nap(s.kovetkezo_datum)} körül, <span class="esedekesmajd">kb. ${ft(s.kovetkezo_osszeg)}</span>` : "–"}`}${
            !f.fix_dij && (f.uton_szamlak?.length || f.diktalt_szamla || !f.reszszamlas) ? ` <button type="button" class="linkgomb" data-tetel="${f.sid}" data-entry="${this._entryId(f.sid)}">tételesen ›</button>` : ""}</div>
          ${f.beszamitas && !kovB ? `<div class="kicsi turfizetes">Túlfizetés: ${ft(f.beszamitas.turfizetes)}${f.beszamitas.levonva ? ` · a várható számlából levonva ${ft(f.beszamitas.levonva)} · marad ${ft(f.beszamitas.marad)}` : ""}${f.beszamitas.kozos ? " (közös folyószámla)" : ""}</div>` : ""}
          ${s.figyelmeztetes ? `<div class="kicsi figyszoveg">${esc(s.figyelmeztetes)}</div>` : ""}
          ${s.dij_elteres && this._admin ? `<div class="ellgombok"><button type="button" class="linkgomb" data-dijelt="${esc(`${f.sid}|${s.dij_elteres.sorszam}`)}" data-dontes="uj_dij">Ez az új havidíj (${ft(Math.round(s.dij_elteres.osszeg / s.dij_elteres.honap))}/hó)</button>
            <button type="button" class="linkgomb" data-dijelt="${esc(`${f.sid}|${s.dij_elteres.sorszam}`)}" data-dontes="egyszeri">Egyszeri eltérés – rendben</button></div>` : ""}</div></div>`);
    }
    const nyitva = this._nyitva.has(f.sid);
    return `
      <div class="kartya" data-kartya="${f.sid}">
        <div class="kfej"><ha-icon icon="${ikon}"></ha-icon>
          <div><div class="knev">${esc(f.nev)}${f.atalany || f.reszszamlas ? ' <span class="cimkeszalag atalany">átalány</span>' : ""}</div><div class="kicsi">${KOZMU[f.kozmu] || ""}${f.fejlec ? "" : ` · ${idoszak}`}${f.aktualis_ar && !f.fix_dij ? ` · ${szam(f.aktualis_ar)} Ft/${esc(egyseg)}` : ""}</div>
</div>${this._menu3(f)}</div>
        ${this._fejlec(f)}
        ${this._utemInfo(f)}
        ${blokkok.join("")}
        <div class="gombok">
          <button data-reszlet="${f.sid}">${nyitva ? "Kevesebb" : "Részletek"}</button>
          ${f.device_id && this._admin ? `<button data-szamla="${f.sid}">${f.kozmu === "kozos" ? "Új előírás" : "Új számla"}</button>` : ""}
          ${this._admin && !f.megszunt && ((f.fix_dij && !f.gaz_atalany) || f.kozmu === "viz") ? `<button data-sajatdij="${f.sid}" title="A saját (település, edényméret szerinti) díjaid">Saját díjak</button>` : ""}
          ${!f.fix_dij && f.device_id && !f.megszunt ? `<button class="fo" data-leolvas="${f.sid}">Mérőállás</button>` : ""}
        </div>
        ${nyitva ? this._reszletek(f) : ""}
      </div>`;
  }

  // Új fiók, még nincs számla: mi kerül az első számlá(k)ra – birtokba vétel → éves leolvasás → diktálás.
  _elsoSzamla(f, diktalasos) {
    const u = f.utem || {};
    if (u.van_szamla || !u.kezdo || !f.uton_szamlak?.length) return "";
    const elso = f.uton_szamlak[0];
    const eves = u.utolso_eves_leolvasas && u.utolso_eves_leolvasas !== u.kezdo.datum ? u.utolso_eves_leolvasas : null;
    const sorok = [];
    if (elozoNap(elso.tol) === u.kezdo.datum && eves && elso.ig === eves)
      sorok.push(`<b>${nap(elso.tol)} – ${nap(elso.ig)}</b>: a birtokba vételtől az éves leolvasásig. Ezt a szolgáltató az éves leolvasáskor (${nap(eves)}) leolvasott állással számolja el.`);
    if (diktalasos && u.diktalasi_ablak && f.varhato)
      sorok.push(`<b>${eves ? "Új elszámolási év" : "Folyó időszak"} (${nap(kovNap(f.idoszak.tol))} –)</b>: a következő számla a <b>${kovDiktalas(u.diktalasi_ablak, f.idoszak.ig)}</b> diktálás után készül, a diktált állás szerint – a mostani fogyasztással kb. <b>${ft(f.varhato.osszeg)}</b>.${eves ? ` ${info("Az éves leolvasás utáni első diktálási ablak kimarad, ha 20 napon belül van: az MVM a következő hónapig vár (pl. 2025: leolvasás okt. 1., a következő számla okt. 2. – nov. 10.).")}` : ""}`);
    if (!sorok.length) return "";
    return `<div class="elsoszamla"><div class="escim"><b>Az első számla</b> ${info(
      "Új fióknál még nincs számla, ezért a Rezsikövető a mért fogyasztásból becsül. Az MVM az éves leolvasás napjáig külön számlát küld (pl. 2025: szept. 10. – okt. 1., 12 nappal a leolvasás után); az új elszámolási év a leolvasás másnapján indul. Az első számla megérkezése után a kártya a számla adataival számol tovább.")}</div>
      ${sorok.map((x) => `<div class="essor">${x}</div>`).join("")}</div>`;
  }

  // A kártya fejléce: következő számla · folyó időszak · folyószámla-egyenleg (fejlec.py). A megbízhatósági címke
  // mutatja, miből jön az összeg: pontos (átalány, fix díj, ismert záró állás), mért (szenzor), becsült (napi átlag).
  _fejlec(f) {
    const fj = f.fejlec;
    if (!fj || (!fj.kovetkezo && !fj.folyo && !fj.egyenleg)) return "";
    const CIMKE = { pontos: "pontos", mert: "mért", becsult: "becsült" };
    const jel = (c, m) => `<span class="mjel mjel-${c}" title="${esc(m)}">${CIMKE[c] || c}</span>`;
    const diktalasos = ["diktalas", "atalany"].includes(f.elszamolas_mod);
    const k = fj.kovetkezo, fo = fj.folyo, e = fj.egyenleg;
    const kov = !k ? `<div class="fjblokk"><div class="cimke">Következő számla</div><div class="ertek fjures">–</div>
        <div class="kicsi">${f.esedekes?.szunetel ? "a számlázás szünetel" : f.megszunt ? "nem várható több számla" : "nincs adat"}</div></div>`
      : `<div class="fjblokk"><div class="cimke">Következő számla ${info(esc(k.magyarazat) + (k.kelte ? ` Várható kelte: ${nap(k.kelte)} körül.` : ""))}</div>
        <div class="ertek${k.dij > k.fizetendo && !k.fizetendo ? " fedezett" : " esedekesmajd"}">${ft(k.dij)} ${jel(k.cimke, k.magyarazat)}</div>
        <div class="kicsi">${k.folyo ? fejIdoszak(f.idoszak.tol, f.idoszak.ig, diktalasos) : k.tol && k.ig ? `${fejNap(k.tol)} – ${fejNap(k.ig)}` : ""}${k.kesik ? `${k.tol ? " · " : ""}<span class="figyszoveg">késik</span>` : k.kelte && !k.folyo ? `${k.tol ? " · " : ""}számla ${fejNap(k.kelte)} körül` : ""}</div>
        ${k.dij > k.fizetendo ? `<div class="kicsi turfizetes">${k.fizetendo ? `fizetendő kb. ${ft(k.fizetendo)} – a többit a túlfizetés fedezi` : "fizetendő 0 Ft – a túlfizetés fedezi"}</div>` : ""}</div>`;
    // Fix (havi) díjnál a hónap az egység: a csík és a szöveg hónapokban.
    const havi = fo && fo.honapok != null;
    const arany = !fo ? 0 : havi ? (100 * fo.eltelt_honap) / fo.honapok : fo.napok ? Math.max(0, Math.min(100, (100 * fo.eltelt_nap) / fo.napok)) : 0;
    const haladas = !fo ? "" : havi ? `${fo.eltelt_honap}/${fo.honapok} hónap` : `${fo.eltelt_nap}/${fo.napok} nap`;
    const egyseg = f.egyseg === "db" ? "" : f.egyseg;
    const folyo = !fo ? ""
      : `<div class="fjblokk fjfolyo"><div class="fjsor"><div class="cimke">Folyó időszak${fo.tajekoztato ? " · mérés szerint" : ""} ${info(esc(fo.magyarazat))}</div>
          <div class="kicsi">${fejIdoszak(fo.tol, fo.ig, diktalasos)} · ${haladas}</div></div>
        <div class="fjsor"><div><span class="fjkozep">${fo.eddig_netto != null ? szam(fo.eddig_netto, egyseg) : ft(fo.eddig)}</span> <span class="kicsi">${fo.eddig_netto != null ? "nettó eddig" : "eddig"}</span></div>
          <div class="kicsi">várható <b>${fo.varhato_netto != null ? szam(fo.varhato_netto, egyseg) : ft(fo.varhato)}</b> ${jel(fo.cimke, fo.magyarazat)}${!f.fix_dij && fo.napi_atlag != null ? ` · napi ${szam(fo.napi_atlag, egyseg)}` : ""}</div></div>
        ${fo.varhato_mert != null ? `<div class="kicsi">átalány · mérés szerint ${ft(fo.varhato_mert)} lenne${f.kozmu === "gaz" ? " (évszak szerint súlyozva)" : ""}</div>` : ""}
        ${!f.fix_dij && f.eddig?.mennyiseg != null && regiszterBontas(f) ? `<div class="kicsi">eddig ${szam(f.eddig.mennyiseg, egyseg)}: ${regiszterBontas(f)}</div>` : ""}
        <div class="sav fjsav" title="${haladas}"><div class="toltes" style="width:${arany}%"></div></div></div>`;
    const egy = !e ? `<div class="fjblokk fjjobb"><div class="cimke">Folyószámla</div><div class="ertek fjures">–</div><div class="kicsi">még nincs számla</div></div>`
      : `<div class="fjblokk fjjobb"><div class="cimke">Folyószámla ${info(`A rögzített számlák és befizetések szerinti egyenleg (a Folyószámla záró egyenlege). Mínusz: túlfizetés – a következő számlákon beszámítják; plusz: kifizetetlen (még nem esedékes vagy lejárt) számla.${e.kozos ? ` Közös folyószámla: ${esc(e.kozos)}.` : ""}`)}</div>
        <div class="ertek ${e.osszeg < 0 ? "plusz" : e.osszeg > 0 ? "minusz" : ""}">${e.osszeg < 0 ? "−" : ""}${ft(Math.abs(e.osszeg))}</div>
        <div class="kicsi">${e.osszeg < 0 ? "túlfizetés" : e.osszeg > 0 ? "fizetendő" : "rendezve"}${e.kozos ? ` · közös: ${esc(e.kozos)}` : ""}</div>
        <button type="button" class="linkgomb kicsi" data-fszfej="${f.sid}">Folyószámla ›</button></div>`;
    return `<div class="fejlec">${kov}${egy}${folyo}</div>`;
  }

  // A szolgáltató, az ütem, a következő leolvasás/diktálás és a számla szerinti mennyiség – teljes szélességben.
  _utemInfo(f) {
    const u = f.utem;
    if (!u) return "";
    const sorok = [];
    const elso = [esc(u.szolgaltato || "")];
    if (f.kozmu === "kozos") elso.push("havi előírás a közös képviselő kimutatása szerint (számla nincs)");
    else if (u.szamlazas_honap) elso.push(`${UTEM[u.szamlazas_honap] || u.szamlazas_honap + " havonta"} számláz`);
    if (f.elszamolas_mod) elso.push(ELSZ_MOD[f.elszamolas_mod]);
    if (!f.fix_dij) elso.push(`elszámolás ${UTEM[u.elszamolas_honap] || ""}`);
    sorok.push(elso.filter(Boolean).join(" · "));
    // Időpontok – mindegyik külön sorban.
    const egys = f.egyseg === "db" ? "" : f.egyseg === "m3" ? "m³" : f.egyseg;
    // Új fiók az első számla előtt: honnan számolunk (birtokba vétel / új mérő kezdőállása).
    if (u.kezdo && !u.van_szamla) sorok.push(`Kezdőállás: ${nap(u.kezdo.datum)} · ${allas(u.kezdo.allas, egys)} ${info(
      "A birtokba vétel (vagy az új mérő) napja és óraállása – innen számol a Rezsikövető, és az első számla is innen indul.")}`);
    if (!f.fix_dij && u.utolso_eves_leolvasas) {
      if (u.kezdo && !u.van_szamla && u.utolso_eves_leolvasas === u.kezdo.datum) {
        sorok.push(`Éves leolvasás: még nincs rögzítve ${info(
          "Ha a szolgáltató leolvasója már járt itt, rögzítsd az állást a Mérőállás ablakban az „Éves (elszámoló) leolvasás” jelöléssel: innen indul az új elszámolási év és a kedvezményes keret, és ehhez igazodik a következő éves leolvasás is.")}`);
      } else {
        const be = u.eves_allas_betaplalas != null;  // napelem: mindkét regiszter
        sorok.push(`Éves leolvasás: ${nap(u.utolso_eves_leolvasas)}${u.eves_allas != null ? ` · ${be ? "1.8.0 " : ""}${allas(u.eves_allas, egys)}` : ""}${be ? ` · 2.8.0 ${allas(u.eves_allas_betaplalas, egys)}` : ""}${u.kezdo && !u.van_szamla ? ` ${info(
          "A szolgáltató éves (elszámoló) leolvasása: eddig tartott az előző elszámolási év (a birtokba vételtől), innen indul az új – a kedvezményes keret is innen számol. Az ez előtti fogyasztást a szolgáltató ezzel az állással számolja el.")}` : ""}`);
      }
    }
    // Napelem: a legutóbbi állás mindkét regiszteren (vételezés 1.8.0, betáplálás 2.8.0).
    const ua = f.utolso_allasok || {};
    if (f.napelem_mod && f.napelem_mod !== "nincs" && ua.betaplalas)
      sorok.push(`Utolsó állás: ${ua.vetelezes ? `${nap(ua.vetelezes.datum)} · 1.8.0 ${allas(ua.vetelezes.allas, egys)} · ` : ""}2.8.0 ${allas(ua.betaplalas.allas, egys)}${ua.vetelezes && ua.vetelezes.datum !== ua.betaplalas.datum ? ` (${nap(ua.betaplalas.datum)})` : ""}`);
    if (u.kovetkezo_leolvasas) sorok.push(`Következő leolvasás: ${nap(u.kovetkezo_leolvasas[0])} – ${nap(u.kovetkezo_leolvasas[1])}`);
    else if (!f.fix_dij && u.kovetkezo_elszamolas && !f.megszunt)
      sorok.push(`${u.elszamolas_honap === 12 ? "Következő éves leolvasás" : "Következő elszámolás"}: ${nap(u.kovetkezo_elszamolas)} körül`);
    if (f.megszunt) sorok.push(`Lezárva: ${nap(f.megszunt.datum)} (végelszámolás)`);
    else if (u.kovetkezo_diktalas) sorok.push(`Diktálás: ${nap(u.kovetkezo_diktalas[0])} – ${nap(u.kovetkezo_diktalas[1])}`);
    else if (u.diktalasi_ablak) sorok.push(`Diktálás: <strong>${kovDiktalas(u.diktalasi_ablak, ["diktalas", "atalany"].includes(f.elszamolas_mod) ? f.idoszak?.ig : null)}</strong> (minden hónap ${u.diktalasi_ablak[0]}–${u.diktalasi_ablak[1]}.)`);
    // Átalány (nem víz): amiből a havi fizetendőt számolja.
    const at = f.atalany || f.atalany_info;
    if (at && f.kozmu !== "viz") {
      const havi_m = at.mennyiseg_havi ?? u.elszamolt_gaz?.resz_m3;  // gáznál a számlán közölt részszámla-mennyiség
      const menny = havi_m != null ? `${szam(havi_m, f.egyseg === "m3" || f.kozmu === "gaz" ? "m³" : f.egyseg)}/hó · ` : "";
      const honnan = /^beállított/.test(at.forras || "") ? "beállított" : "számla szerint";
      sorok.push(`Átalány: <strong>${menny}${ft(at.havi)}/hó</strong> (${honnan})${f.diktalas_szerint ? ` – most nem ezt számlázzák ${info(
        "Az utolsó két számla elszámoló volt (vagy nemrég diktáltál): a szolgáltató havonta a diktált állás szerint számláz, így minden hónap ki van egyenlítve – éves ráfizetés vagy visszatérítés nem gyűlik. Ha egyszer nem diktálsz, a következő számla az átalány; a kártya ilyenkor magától visszavált az átalányos nézetre.")}` : ""}`);
    }
    const e = u.elszamolt_viz;
    if (e) sorok.push(`Számla szerint elszámolt${e.idoszak ? ` (${nap(e.idoszak[0])} – ${nap(e.idoszak[1])}${e.atalany ? ", átalány" : ""})` : ""}: `
      + `<strong>ivóvíz ${szam(e.ivoviz, "m³")}</strong> · <strong>csatorna ${szam(e.csatorna, "m³")}</strong>`);
    const eg = u.elszamolt_gaz;
    if (eg) sorok.push(`Számla szerint elszámolt${eg.idoszak ? ` (${nap(eg.idoszak[0])} – ${nap(eg.idoszak[1])}, ${eg.tipus === "resz" ? "részszámla" : "elszámoló"})` : ""}: <strong>${szam(eg.m3, "m³")}</strong> (${szam(eg.mj, "MJ")})`);
    const ek = u.elszamolt_kwh;
    if (ek) sorok.push(`Számla szerint elszámolt${ek.idoszak ? ` (${nap(ek.idoszak[0])} – ${nap(ek.idoszak[1])}, ${ek.tipus === "resz" ? "részszámla" : "elszámoló"})` : ""}: <strong>${szam(ek.kwh, "kWh")}</strong>`);
    return `<div class="kinfo">${sorok.map((x) => `<div>${x}</div>`).join("")}</div>`;
  }

  // ---------------------------------------------------------------- hárompontos menü

  _entitasok(f) {
    if (!f.device_id || !this._hass?.entities) return [];
    return Object.values(this._hass.entities)
      .filter((e) => e.device_id === f.device_id)
      .sort((a, b) => (a.entity_category ? 1 : 0) - (b.entity_category ? 1 : 0) || a.entity_id.localeCompare(b.entity_id));
  }

  _foEntitas(f) {
    const lista = this._entitasok(f);
    const elso = (tk) => lista.find((e) => e.translation_key === tk);
    return (elso("koltseg_eddig") || elso("atalany_havi") || elso("kovetkezo_szamla") || lista[0])?.entity_id;
  }

  _menu3(f) {
    if (!f.device_id) return "";
    const nyitva = this._menuSid === f.sid;
    const tetel = (muvelet, ikon, szoveg) =>
      `<button class="mtetel" data-menu-muvelet="${muvelet}" data-sid="${f.sid}"><ha-icon icon="${ikon}"></ha-icon>${szoveg}</button>`;
    return `<div class="menu3">
        ${f.fix_dij ? "" : `<button class="ikongomb pontok grafgomb" data-graf="${f.sid}" title="Éves összevetés" aria-label="Éves összevetés grafikon"><ha-icon icon="mdi:chart-bar"></ha-icon></button>`}
        <button class="ikongomb pontok" data-menu="${f.sid}" title="Továbbiak" aria-haspopup="menu" aria-expanded="${nyitva}"><ha-icon icon="mdi:dots-vertical"></ha-icon></button>
        ${nyitva ? `<div class="menulista" role="menu">
          ${f.fix_dij ? "" : tetel("osszevetes", "mdi:chart-bar", "Éves összevetés")}
          ${tetel("folyoszamla", "mdi:book-open-variant-outline", "Folyószámla")}
          ${tetel("elozmenyek", "mdi:chart-box-outline", "Előzmények")}
          ${tetel("beallitasok", "mdi:cog-outline", "Beállítások")}
          ${tetel("kapcsolodo", "mdi:information-outline", "Kapcsolódó")}
          ${!this._admin ? "" : tetel("lezaras", f.megszunt ? "mdi:archive-arrow-up-outline" : "mdi:archive-lock-outline", f.megszunt ? "Lezárás visszavonása" : "Fiók lezárása (végelszámolás)")}
        </div>` : ""}
      </div>`;
  }

  _tobbInfo(entityId, view) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId, view }, bubbles: true, composed: true }));
  }

  _navigal(utvonal) {
    history.pushState(null, "", utvonal);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  _menuMuvelet(muvelet, f) {
    this._menuSid = null;
    this._rajzol();
    if (muvelet === "elozmenyek") this._tobbInfo(this._foEntitas(f), "history");
    else if (muvelet === "kapcsolodo") this._tobbInfo(this._foEntitas(f), "related");
    else if (muvelet === "beallitasok") this._beallitasNyit(f);
    else if (muvelet === "osszevetes") this._osszevetesNyit(f);
    else if (muvelet === "lezaras") this._lezarNyit(f);
    else if (muvelet === "folyoszamla") this._folyoszamlaNyit(f);
  }

  async _osszevetesNyit(f) {
    const r = this.shadowRoot;
    const d = r.getElementById("grafdlg");
    this._graf = { f, adat: null, mertek: this._graf?.mertek || "mennyiseg", ev: null, hiba: null };
    if (!d.open) d.showModal();
    this._grafRajzol();
    try {
      const v = await this._hass.callWS({ type: "hu_rezsi/osszevetes", sid: f.sid });
      if (this._graf.f !== f) return;
      this._graf.adat = v;
      const evek = [...new Set(v.honapok.filter((h) => h.mennyiseg != null).map((h) => +h.honap.slice(0, 4)))].sort((a, b) => b - a);
      this._graf.evek = evek;
      this._graf.ev = evek[0] ?? new Date().getFullYear();
    } catch (e) {
      this._graf.hiba = e.message || String(e);
    }
    this._grafRajzol();
  }

  _entryId(sid) {
    const a = this._adat;
    const hs = Array.isArray(a) ? a : (a?.otthonok || a?.haztartasok || []);
    return hs.find((h) => h.fiokok.some((f) => f.sid === sid))?.entry_id || "";
  }

  // A shadow-gyökér szintű (delegált) figyelők egyszer kötődnek be – a kezelők minden rajzoláskor lefutnak, és a
  // gyökér a rajzolások között megmarad (korábban halmozódtak: egy kattintás többször futott le).
  _egyszer(kulcs, fn) {
    this._kotott ??= new Set();
    if (this._kotott.has(kulcs)) return;
    this._kotott.add(kulcs);
    fn();
  }

  _tetelKezelo() {
    const d = this.shadowRoot.getElementById("teteldlg");
    this.shadowRoot.getElementById("tetelbezar").addEventListener("click", () => d.close());
    d.addEventListener("click", (ev) => ev.target === d && d.close());
    // Delegált: a kártyák és a kimutatás „Tételesen” gombjai (újrarajzolás után is).
    this._egyszer("deleg0", () => this.shadowRoot.addEventListener("click", (ev) => {
      const b = ev.target.closest?.("[data-tetel]");
      if (b) this._tetelNyit(b.dataset.entry, b.dataset.tetel, b.dataset.tol, b.dataset.ig);
      // Számla-ellenőrzés: reklamáció-tervezet, rendezve / újranyitás, rendezettek mutatása.
      const r = ev.target.closest?.("[data-reklam]");
      if (r) { const [sid, kulcs] = r.dataset.reklam.split("|"); this._reklamacio(sid, kulcs); }
      const e = ev.target.closest?.("[data-ellrend]");
      if (e) {
        const [sid, kulcs] = e.dataset.ellrend.split("|");
        e.disabled = true;
        this._hass.callWS({ type: "hu_rezsi/ellenorzes_dontes", entry_id: this._entryId(sid), sid, kulcs, dontes: e.dataset.dontes })
          .then(() => this._betolt?.()).catch((err) => { e.disabled = false; alert(err.message || err); });
      }
      if (ev.target.closest?.("[data-ellmind]")) { this._ellMind = !this._ellMind; this._rajzol(); }
      // AI-számlabeolvasó (2.3.0b1): a fel nem ismert fájl kiolvasása, jóváhagyással.
      const ai = ev.target.closest?.("[data-aifajl]");
      if (ai) {
        const i = ai.dataset.aifajl.indexOf("|");
        this._aiNyit(ai.dataset.aifajl.slice(0, i), ai.dataset.aifajl.slice(i + 1));
        return;
      }
      // Késő várt számla lemondása (megerősítéssel).
      const lm = ev.target.closest?.("[data-lemond]");
      if (lm) {
        const d = lm.dataset;
        if (!confirm(`Törlöd ezt a várt számlát?\n\n${d.szoveg}\n\nCsak a becslés tűnik el (a kártyáról, a folyószámla várható soraiból, az e havi esedékességből); a számlák, befizetések és egyenlegek nem változnak. Ha mégis megjön, ugyanúgy beolvassa.`)) return;
        lm.disabled = true;
        this._hass.callWS({ type: "hu_rezsi/szamla_lemondas", entry_id: this._entryId(d.lemond), sid: d.lemond, kovetkezo_datum: d.varva,
          tol: d.tol || null, ig: d.ig || null, osszeg: d.osszeg ? Number(d.osszeg) : null })
          .then(() => this._betolt?.()).catch((err) => { lm.disabled = false; alert(err.message || err); });
        return;
      }
      // Díjeltérés (fix díjas fiók): a számla összege az új havidíj, vagy egyszeri eltérés.
      const de = ev.target.closest?.("[data-dijelt]");
      if (de) {
        const [sid, sorszam] = de.dataset.dijelt.split("|");
        de.disabled = true;
        this._hass.callWS({ type: "hu_rezsi/dij_elteres", entry_id: this._entryId(sid), sid, sorszam, dontes: de.dataset.dontes })
          .then(() => this._betolt?.()).catch((err) => { de.disabled = false; alert(err.message || err); });
        return;
      }
      // Teendőre kattintva (nem a gombjaira): ugrás a fiók kártyájára, egy pillanatra kiemelve.
      const li = ev.target.closest?.("li[data-ugrik]");
      if (li && !ev.target.closest("button, a") && this._tablet()) {
        this._lapValt(this._entryId(li.dataset.ugrik), li.dataset.ugrik, "fiok");
        return;
      }
      if (li && !ev.target.closest("button, a")) {
        const k = this.shadowRoot.querySelector(`.kartya[data-kartya="${li.dataset.ugrik}"]`);
        if (k) {
          k.scrollIntoView({ behavior: "smooth", block: "start" });
          k.classList.remove("kiemelt"); void k.offsetWidth; k.classList.add("kiemelt");
        }
      }
    }));
    const ed = this.shadowRoot.getElementById("evesdlg");
    this.shadowRoot.getElementById("evesbezar").addEventListener("click", () => ed.close());
    ed.addEventListener("click", (ev) => ev.target === ed && ed.close());
    this.shadowRoot.getElementById("evesnyomtat").addEventListener("click", () => this._evesNyomtat());
    this.shadowRoot.getElementById("evesreklam").addEventListener("click", () => this._evesReklam());
    this.shadowRoot.getElementById("evesev").addEventListener("change", (ev) => {
      if (this._eves) this._evesNyit(this._eves.entryId, this._eves.sid, ev.target.value);
    });
    this._egyszer("deleg1", () => this.shadowRoot.addEventListener("change", (ev) => {
      const t = ev.target;
      if (t.dataset?.hatarido) {
        // Kézi számla fizetési határideje (üresre törölve: nincs határidő).
        const [hsid, hsorszam] = t.dataset.hatarido.split("|");
        t.disabled = true;
        this._hass.callWS({ type: "hu_rezsi/hatarido", entry_id: this._entryId(hsid), sid: hsid, sorszam: hsorszam, hatarido: t.value || null })
          .then(() => { t.disabled = false; this._kesoBetolt(); }).catch((err) => { t.disabled = false; alert(err.message || err); });
        return;
      }
      const kulcs = t.dataset?.fizet || t.dataset?.fizdatum;
      if (!kulcs) return;
      const [sid, sorszam] = kulcs.split("|");
      const ma = new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
      const fizetve = t.dataset.fizet ? t.checked : true;
      const datum = t.dataset.fizdatum ? (t.value || ma) : ma;
      // Azonnal a sorban (a szerver a háttérben számol újra); a fejléc egyenlege a késleltetett újratöltéssel frissül.
      this._helyiFizetes(sid, sorszam, { fizetve, datum: fizetve ? datum : null, forras: "kezi", lejart: false });
      this._hass.callWS({ type: "hu_rezsi/fizetes", entry_id: this._entryId(sid), sid, sorszam, fizetve, ...(fizetve ? { datum } : {}) })
        .then(() => this._kesoBetolt()).catch((err) => { alert(err.message || err); this._betolt(); });
    }));
    this._egyszer("deleg2", () => this.shadowRoot.addEventListener("click", (ev) => {
      const sz = ev.target.closest?.("[data-szigetido]");
      if (sz) { const [sid, k] = sz.dataset.szigetido.split("|"); this._szigetIdo = { ...(this._szigetIdo || {}), [sid]: k }; this._rajzol(); return; }
      const b = ev.target.closest?.("[data-eves]");
      if (b) this._evesNyit(b.dataset.entry, b.dataset.eves);
    }));
    const rd = this.shadowRoot.getElementById("reklamdlg");
    this.shadowRoot.getElementById("reklambezar").addEventListener("click", () => rd.close());
    this.shadowRoot.getElementById("reklamnyomtat").addEventListener("click", () => this._reklamNyomtat());
    this.shadowRoot.getElementById("reklammasol").addEventListener("click", async () => {
      const txt = this.shadowRoot.querySelector("#reklambody .level")?.innerText || "";
      try { await navigator.clipboard.writeText(txt); } catch { /* nem támogatott */ }
    });
  }

  _evesLehet(f) {
    return f.kozmu === "villany" && ["villany/a1", "villany/h"].includes(f.dijszabas) && (f.szamlak || []).some((x) => x.tipus === "elszamolo");
  }

  // Éves elszámolási kimutatás (hu_rezsi/eves_kimutatas): a két éves leolvasás közötti év a mérőállások és a díjszabás
  // szerint, számlánként szembeállítva a szolgáltató elszámoló számláival; nyomtatható, reklamáció-tervezettel.
  async _evesNyit(entryId, sid, evTol) {
    const d = this.shadowRoot.getElementById("evesdlg"), body = this.shadowRoot.getElementById("evesbody");
    const r = this.shadowRoot;
    r.getElementById("evesnyomtat").disabled = r.getElementById("evesreklam").disabled = true;
    body.innerHTML = `<div class="kicsi grafvar">Számolás…</div>`;
    if (!d.open) d.showModal();
    let k;
    try {
      k = await this._hass.callWS({ type: "hu_rezsi/eves_kimutatas", entry_id: entryId, sid, ...(evTol ? { ev_tol: evTol } : {}) });
    } catch (e) {
      body.innerHTML = `<div class="figyszoveg">${esc(e.message || String(e))}</div>`;
      return;
    }
    this._eves = { entryId, sid, k };
    r.getElementById("evescim").textContent = `Éves elszámolási kimutatás – ${k.fiok}`;
    r.getElementById("evesev").innerHTML = k.jeloltek.map(([a, b]) =>
      `<option value="${a}" ${a === k.ev_tol ? "selected" : ""}>${nap(a)} – ${nap(b)}</option>`).join("");
    body.innerHTML = this._evesHtml(k);
    r.getElementById("evesnyomtat").disabled = false;
    r.getElementById("evesreklam").disabled = !k.megallapitasok.some((m) => m.hatas_ft != null);
  }

  _evesHtml(k) {
    const h = k.dijszabas === "villany/h", o = k.osszesen, u = k.ugyfel || {};
    const ftk = (v) => (v == null ? "–" : ft(v));
    const kw = (v) => (v == null ? "–" : szam(Math.round(v), "kWh"));
    const fizSzoveg = (z) => (!z ? "–" : z.nincs_fizetendo ? "nincs fizetendő" : z.fizetve ? `${z.datum ? rovidNap(z.datum) : "igen"}${z.forras === "dijnet" ? " (D)" : z.forras === "beszedes" ? " (B)" : z.forras === "utemezett" ? " (Á)" : ""}` : `<span class="lejart">nyitott${z.lejart ? ", lejárt" : ""}</span>`);
    const TIPN = { resz: "részszámla", elszamolo: "elszámoló", vegszamla: "végszámla", egyeb: "számla", eloiras: "előírás" };
    const bf = k.befizetesek;
    const befSor = (bf?.szamlak || []).map((b) => `<tr><td>${rovidNap(b.kelte)}</td><td class="bal">${esc(b.sorszam)}</td><td class="bal">${TIPN[b.tipus] || esc(b.tipus || "")}</td>
      <td class="bal">${b.idoszak ? `${nap(b.idoszak[0])} – ${nap(b.idoszak[1])}` : ""}</td><td>${b.fizetes?.osszeg != null ? ft(b.fizetes.osszeg) : "–"}</td>
      <td>${b.fizetes?.hatarido ? rovidNap(b.fizetes.hatarido) : "–"}</td><td>${fizSzoveg(b.fizetes)}</td></tr>`).join("");
    // Mérőállások: az év két vége és a számlák zárónapjai.
    const csat = h ? ["h_teli", "h_nyari"] : ["vetelezes"];
    const napok = Object.keys(k.allasok[csat[0]] || {}).sort();
    const allasSor = napok.map((x) => {
      const esemeny = x === k.ev_tol ? (k.sorok[0]?.tol === x ? "kezdőállás" : "éves leolvasás (kezdő)") : x === k.ev_ig ? "éves leolvasás (záró)"
        : `számla zárónapja (${esc(k.sorok.find((s) => s.ig === x)?.sorszam || "")})`;
      const ert = csat.map((c) => k.allasok[c][x]);
      return `<tr${x === k.ev_tol || x === k.ev_ig ? ' class="evossz"' : ""}><td>${nap(x)}</td><td class="bal">${esemeny}</td>${ert.map((v) => `<td>${v == null ? "–" : SZAM.format(Math.round(v))}</td>`).join("")}${h ? `<td>${SZAM.format(Math.round(ert[0] + ert[1]))}</td>` : ""}</tr>`;
    }).join("");
    const fogyEv = csat.reduce((t, c) => t + (k.allasok[c][k.ev_ig] - k.allasok[c][k.ev_tol]), 0);
    const sorok = k.sorok.map((s) => {
      const m = s.mvm, hiba = s.elteres != null && Math.abs(s.elteres) >= Math.max(100, s.helyes * 0.005);
      return `<tr class="${!m ? "evfugg" : hiba ? "evhiba" : ""}"><td class="bal">${nap(s.tol)} – ${nap(s.ig)}</td><td class="bal">${m ? esc(s.sorszam) : "még nincs számla"}</td>
        <td>${kw(s.mert)}</td><td>${kw(m?.kiszamlazott)}</td>
        ${h ? `<td>${kw(s.teli)}</td><td>${kw(m?.teli)}</td>` : ""}
        <td>${kw(s.kedvezmenyes)}</td><td>${kw(m?.kedvezmenyes)}</td><td>${kw(s.piaci)}</td><td>${kw(m?.piaci)}</td>
        <td>${s.alapdij_ho} / ${m ? m.alapdij_ho : "–"}</td><td>${ftk(s.helyes)}</td><td>${ftk(m?.dij)}</td><td><b>${ftk(s.elteres)}</b></td><td>${fizSzoveg(s.fizetes)}</td></tr>`;
    }).join("");
    const ossz = `<tr class="evossz"><td class="bal" colspan="2">Számlázott időszak összesen${o.ig ? ` (–${nap(o.ig)})` : ""}</td><td>${kw(o.mert)}</td><td>${kw(o.kiszamlazott)}</td>
      ${h ? `<td>${kw(o.teli)}</td><td>${kw(o.mvm_teli)}</td>` : ""}<td>${kw(o.kedvezmenyes)}</td><td>${kw(o.mvm_kedvezmenyes)}</td><td>${kw(o.piaci)}</td><td>${kw(o.mvm_piaci)}</td>
      <td>${o.alapdij_ho} / ${o.mvm_alapdij_ho}</td><td>${ftk(o.helyes)}</td><td>${ftk(o.mvm)}</td><td><b>${ftk(o.elteres)}</b></td><td></td></tr>`;
    const dj = o.dij || {}, a1 = k.dijak?.a1 || {}, hd = k.dijak?.h || {};
    const dijSor = (nev, v) => (v ? `<tr><td class="bal">${nev}</td><td>${ft(v)}</td></tr>` : "");
    const meg = k.megallapitasok.map((m) => `<li><b>${esc(m.sorszam)}</b> (${nap(m.tol)} – ${nap(m.ig)}): ${esc(m.szoveg)}${m.hatas_ft != null ? ` – <b>${m.hatas_ft > 0 ? "kiszámlázatlan / pótszámla" : "túlszámlázás"}: ${ft(Math.abs(m.hatas_ft))}</b>` : ""}</li>`).join("");
    const hibak = k.megallapitasok.filter((m) => m.hatas_ft != null && m.tipus !== "elteres");
    const hibaOssz = hibak.reduce((t, m) => t + m.hatas_ft, 0);
    return `
      <p class="kicsi">Elszámolási év: <b>${nap(k.ev_tol)} – ${nap(k.ev_ig)}</b>${h ? " · téli idény okt. 15. – ápr. 15. (1.81, H-ár), nyári ápr. 16. – okt. 14. (1.82, A1-ár saját kerettel)" : ""} · ${esc(k.szolgaltato || "")}
        ${u.nev ? `<br>${esc(u.nev)} · azonosító: ${esc(u.azonosito || "–")} · ${esc(u.hely || "")} · mérési pont: ${esc(u.meresi_pont || "–")}` : ""}${k.mero ? ` · mérő: ${esc(k.mero)}` : ""}</p>
      ${k.hianyos ? `<div class="figyszoveg">Néhány időszakhoz nincs mérőállás – ezek kimaradtak.</div>` : ""}
      <h4>Mérőállások</h4>
      <div class="tablagorgeto"><table class="teteltabla evtabla"><thead><tr><th>Nap</th><th class="bal">Esemény</th>${h ? "<th>1.81 téli</th><th>1.82 nyári</th><th>összesen</th>" : "<th>Mérőállás (kWh)</th>"}</tr></thead>
        <tbody>${allasSor}</tbody><tfoot><tr class="evossz"><td class="bal" colspan="${h ? 4 : 2}">Fogyasztás az elszámolási évben</td><td>${kw(fogyEv)}</td></tr></tfoot></table></div>
      <h4>Összesítő – a számlázott időszak</h4>
      <div class="tablagorgeto"><table class="teteltabla evtabla"><thead><tr><th class="bal"></th><th>Mérés és díjszabás szerint</th><th>Számlák szerint</th><th>Különbség</th></tr></thead><tbody>
        <tr><td class="bal">Fogyasztás / kiszámlázott</td><td>${kw(o.mert)}</td><td>${kw(o.kiszamlazott)}</td><td>${kw(o.mert - o.kiszamlazott)}</td></tr>
        ${h ? `<tr><td class="bal">ebből téli H-ár (1.81)</td><td>${kw(o.teli)}</td><td>${kw(o.mvm_teli)}</td><td>${kw(o.teli - o.mvm_teli)}</td></tr>` : ""}
        <tr><td class="bal">${h ? "nyári " : ""}kedvezményes (keret ${SZAM.format(k.keret_ev)} kWh/év)</td><td>${kw(o.kedvezmenyes)}</td><td>${kw(o.mvm_kedvezmenyes)}</td><td>${kw(o.kedvezmenyes - o.mvm_kedvezmenyes)}</td></tr>
        <tr><td class="bal">${h ? "nyári " : ""}lakossági piaci</td><td>${kw(o.piaci)}</td><td>${kw(o.mvm_piaci)}</td><td>${kw(o.piaci - o.mvm_piaci)}</td></tr>
        <tr><td class="bal">Elosztói alapdíj (hó)</td><td>${o.alapdij_ho}</td><td>${o.mvm_alapdij_ho}</td><td>${o.alapdij_ho - o.mvm_alapdij_ho}</td></tr>
        <tr class="evossz"><td class="bal">Díj összesen (bruttó)</td><td>${ft(o.helyes)}</td><td>${ft(o.mvm)}</td><td><b>${ft(o.elteres)}</b></td></tr></tbody></table></div>
      <div class="tablagorgeto"><table class="teteltabla evtabla evdij"><thead><tr><th class="bal">A helyes díj összetevői (bruttó)</th><th>Ft</th></tr></thead><tbody>
        ${dijSor(`Energiadíj – kedvezményes (${String(a1.energia_kedvezmenyes ?? "").replace(".", ",")} Ft/kWh + ÁFA)`, dj.kedvezmenyes)}
        ${dijSor(`Energiadíj – piaci (${String(a1.energia_piaci ?? "").replace(".", ",")} Ft/kWh + ÁFA)`, dj.piaci)}
        ${dijSor(`Rendszerhasználati díj (${String(a1.rendszerhasznalati ?? "").replace(".", ",")} Ft/kWh + ÁFA)`, dj.rhd)}
        ${dijSor(`Téli H-ár (${String(hd.energia_teli ?? "").replace(".", ",")} Ft/kWh + ÁFA)`, dj.teli)}
        ${dijSor(`Téli rendszerhasználati díj (${String(hd.rendszerhasznalati ?? "").replace(".", ",")} Ft/kWh + ÁFA)`, dj.teli_rhd)}
        ${dijSor("Elosztói alapdíj (a hónap 1-jei szerint)", dj.alapdij)}</tbody></table></div>
      <h4>Számlánként</h4>
      <div class="tablagorgeto"><table class="teteltabla evtabla"><thead><tr><th class="bal">Elszámolt időszak</th><th class="bal">Számla</th><th>Mért</th><th>Számlázta</th>
        ${h ? "<th>Téli helyes</th><th>Téli számla</th>" : ""}<th>Kedv. helyes</th><th>Kedv. számla</th><th>Piaci helyes</th><th>Piaci számla</th><th>Alapdíj hó</th><th>Helyes díj</th><th>Számla díja</th><th>Különbség</th><th>Fizetve</th></tr></thead>
        <tbody>${sorok}</tbody><tfoot>${ossz}</tfoot></table></div>
      <p class="kicsi">„Számla díja”: a számla saját díja (energiadíj + rendszerhasználati díjak, bruttó) a levont részszámlák és a folyószámla-tételek nélkül; az alapdíj hónaponként, az év összes számlájából egyszer. Sztornózott számla helyett az újra kiállított. A sávkorrekció a kedvezményes/piaci oszlopokban benne van.</p>
      ${bf ? `<h4>Befizetések – az év számlái</h4>
      <p class="kicsi">Fizetendő összesen <b>${ft(bf.fizetendo_ft)}</b>, ebből fizetve <b>${ft(bf.fizetve_ft)}</b>${bf.nyitott_db ? `, nyitott <b class="lejart">${ft(bf.nyitott_ft)}</b> (${bf.nyitott_db} számla)` : ""}${bf.jovairas_ft ? ` · jóváírás / visszajár: ${ft(-bf.jovairas_ft)}` : ""}. A fizetés a Díjnet szerint (D) vagy kézzel rögzítve (Részletek → Számlák).</p>
      <div class="tablagorgeto"><table class="teteltabla evtabla"><thead><tr><th>Kelte</th><th class="bal">Számla</th><th class="bal">Típus</th><th class="bal">Időszak</th><th>Fizetendő</th><th>Határidő</th><th>Fizetve</th></tr></thead>
        <tbody>${befSor}</tbody></table></div>` : ""}
      <h4>Megállapítások</h4>
      ${meg ? `<ol class="evmeg">${meg}</ol>` : `<p class="kicsi">A számlák a mérés és a díjszabás szerint helyesek.</p>`}
      ${k.fuggo ? `<p class="kicsi"><b>${nap(k.fuggo.tol)} – ${nap(k.fuggo.ig)}:</b> erre még nincs elszámoló számla – várhatóan ${kw(k.fuggo.mert)}, ${ft(k.fuggo.helyes)}. A teljes elszámolási év helyes díja ${ft(k.ev_helyes)}.</p>` : ""}
      ${hibak.length ? `<div class="evdoboz"><b>Összegzés:</b> a talált számlahibák együtt ${hibaOssz >= 0 ? "kiszámlázatlan díj (pótszámla várható)" : "túlszámlázás (visszajár)"}: <b>${ft(Math.abs(hibaOssz))}</b>.</div>` : ""}
      <p class="kicsi">Tájékoztató számítás a mérőállások és a díjszabás szerint (keret: ${SZAM.format(k.keret_ev)} kWh/év napra arányosan, számlánként egész kWh-ra kerekítve, az elszámolási éven belül halmozva; alapdíj a hónap 1-jei szerint; tételenként kerekítve). A szolgáltató helyesbítése ettől eltérhet.</p>`;
  }

  _nyomtatoKeretbe(html) {
    this._nyomtatoKeret?.remove();
    const f = (this._nyomtatoKeret = document.createElement("iframe"));
    f.setAttribute("aria-hidden", "true");
    Object.assign(f.style, { position: "fixed", right: "0", bottom: "0", width: "0", height: "0", border: "0" });
    document.body.appendChild(f);
    f.contentDocument.open();
    f.contentDocument.write(html);
    f.contentDocument.close();
    setTimeout(() => { f.contentWindow.focus(); f.contentWindow.print(); }, 300);
  }

  _evesNyomtat() {
    const k = this._eves?.k;
    if (!k) return;
    this._nyomtatoKeretbe(`<!doctype html><html lang="hu"><head><meta charset="utf-8"><title>Éves elszámolási kimutatás – ${esc(k.fiok)}</title><style>
      @page { size: A4 landscape; margin: 12mm; } body { font: 9pt/1.4 "Segoe UI", Roboto, Arial, sans-serif; color: #111; }
      h2 { font-size: 14pt; margin: 0 0 4pt; } h4 { font-size: 10.5pt; margin: 10pt 0 3pt; border-bottom: 1pt solid #1d5c63; color: #123c41; }
      table { border-collapse: collapse; width: 100%; margin: 2pt 0 6pt; } th, td { border: .5pt solid #aaa; padding: 2pt 4pt; text-align: right; }
      th { background: #e6f0f0; font-size: 8pt; } .bal { text-align: left; } .evhiba td { background: #fbe9e2; } .evossz td { font-weight: 700; background: #f2f4f4; }
      .evfugg td { color: #555; font-style: italic; } .evdij { width: 60%; } .kicsi { font-size: 8pt; color: #444; } .figyszoveg { color: #a3421f; }
      .evdoboz { border-left: 3pt solid #a3421f; background: #f8ebe4; padding: 4pt 8pt; margin: 6pt 0; } tr { break-inside: avoid; }
      .blokk { break-inside: avoid; } h4 { break-after: avoid; }
    </style></head><body><h2>Éves elszámolási kimutatás – ${esc(k.fiok)}</h2>${this._evesHtml(k).replace(/<h4>[^]*?<\/table><\/div>/g, (b) => `<div class="blokk">${b}</div>`)}</body></html>`);
  }

  _evesReklam() {
    const k = this._eves?.k;
    if (!k) return;
    const u = k.ugyfel || {}, o = k.osszesen, h = k.dijszabas === "villany/h", ma = new Date().toLocaleDateString("hu-HU");
    const hibak = k.megallapitasok.filter((m) => m.hatas_ft != null);
    const levontak = k.megallapitasok.filter((m) => m.tipus === "nem_levont");
    const ossz = hibak.reduce((t, m) => t + m.hatas_ft, 0);
    const kw = (v) => szam(Math.round(v), "kWh");
    const cs = h ? ["h_teli", "h_nyari"] : ["vetelezes"];
    const all = (x) => cs.map((c) => SZAM.format(Math.round(k.allasok[c][x]))).join(" / ");
    const level = `<p>${/MVM/i.test(k.szolgaltato || "") ? "MVM Next Energiakereskedelmi Zrt.<br>Ügyfélszolgálat (ugyfelszolgalat@mvm.hu)" : `${esc(k.szolgaltato || "Szolgáltató")}<br>Ügyfélszolgálat`}</p>
      <p><b>Tárgy: számlakifogás – a ${nap(k.ev_tol)} – ${nap(k.ev_ig)} elszámolási év${h ? " (H-tarifa)" : ""} elszámolása; ${hibak.map((m) => esc(m.sorszam)).join(", ")} sz. számla</b></p>
      <p>Felhasználó: ${esc(u.nev || "…")}<br>Felhasználó azonosító: ${esc(u.azonosito || "…")}<br>Felhasználási hely: ${esc(u.hely || "…")}<br>Mérési pont: ${esc(u.meresi_pont || "…")}${k.mero ? ` · Mérő: ${esc(k.mero)}` : ""}</p>
      <p>Tisztelt Ügyfélszolgálat!</p>
      <p>Az elszámolási évet a mérőállások és az Önök számlái alapján összesítettem (a kimutatást mellékelem). Kezdő állás (${nap(k.ev_tol)}): <b>${all(k.ev_tol)}</b>${h ? " (1.81 / 1.82)" : " kWh"}, záró állás (${nap(k.ev_ig)}, éves leolvasás): <b>${all(k.ev_ig)}</b>${h ? "" : " kWh"}. A ${o.ig ? nap(o.ig).replace(/\.$/, "") : ""}-ig kiállított elszámoló számlák a mért ${kw(o.mert)} fogyasztásra ${kw(o.kiszamlazott)}-t számláztak ki; a díj a mérés és a díjszabás szerint ${ft(o.helyes)}, a számlák szerint ${ft(o.mvm)}.</p>
      <p>Az eltérés oka:</p><ol>${hibak.map((m) => `<li>a <b>${esc(m.sorszam)}</b> sz. számla (${nap(m.tol)} – ${nap(m.ig)}): ${esc(m.szoveg)} (${m.hatas_ft > 0 ? "kiszámlázatlan" : "túlszámlázott"}: ${ft(Math.abs(m.hatas_ft))});</li>`).join("")}</ol>
      <p>Kérem a fenti számlák felülvizsgálatát és helyesbítését a tényleges fogyasztás szerint (becslésem szerint a különbözet összesen ${ft(Math.abs(ossz))} ${ossz >= 0 ? "a szolgáltató javára" : "a javamra"})${levontak.length ? `, a ${levontak.map((m) => esc(m.sorszam)).join(", ")} sz. részszámla levonását a következő elszámoló számlában` : ""}${k.fuggo ? `, valamint a ${nap(k.fuggo.tol)} – ${nap(k.fuggo.ig)} közötti időszak elszámolását a ${nap(k.ev_ig).replace(/\.$/, "")}-i éves leolvasás alapján` : ""}, és tájékoztatást arról, hogyan rendezik a különbözetet és hogyan alakul a folyószámla egyenlege.</p>
      <p>Válaszukat a fenti elérhetőségeken várom.</p>
      <p>Melléklet: éves elszámolási kimutatás (${nap(k.ev_tol)} – ${nap(k.ev_ig)})</p>
      <p>Kelt: ${ma}</p><p>Tisztelettel:<br><br>……………………………<br>${esc(u.nev || "")}</p>`;
    this.shadowRoot.getElementById("reklambody").innerHTML = `<div class="level">${level}</div>
      <p class="kicsi">A forint-összegek a Rezsikövető tájékoztató számításai (a díjszabás és a mérés szerint); a szolgáltató helyesbítése ettől eltérhet. Küldés előtt nézd át, és csatold a kimutatást (Nyomtatás / PDF az éves kimutatás ablakában).</p>`;
    this._reklamLevel = level;
    const d = this.shadowRoot.getElementById("reklamdlg");
    if (!d.open) d.showModal();
  }

  // Tájékoztató, számlaszerű tételes bontás egy még nem érkezett számlára (hu_rezsi/varhato_tetelek).
  async _tetelNyit(entryId, sid, tol, ig) {
    const d = this.shadowRoot.getElementById("teteldlg"), body = this.shadowRoot.getElementById("tetelbody");
    body.innerHTML = `<div class="kicsi grafvar">Számolás…</div>`;
    if (!d.open) d.showModal();
    let t;
    try {
      t = await this._hass.callWS({ type: "hu_rezsi/varhato_tetelek", entry_id: entryId, sid, ...(tol && ig ? { tol, ig } : {}) });
    } catch (e) {
      body.innerHTML = `<div class="figyszoveg">${esc(e.message || String(e))}</div>`;
      return;
    }
    this.shadowRoot.getElementById("tetelcim").textContent = `Várható számla – ${t.fiok}`;
    const ftd = (v) => FT.format(Math.round(v));
    const ar = (v) => new Intl.NumberFormat("hu-HU", { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(v);
    const sorok = t.sorok.map((x) => `<tr>
      <th scope="row">${esc(x.nev)}</th><td>${nap(x.tol)} – ${nap(x.ig)}</td>
      <td>${szam(x.mennyiseg)} ${esc(x.egyseg)}</td><td>${ar(x.ar)} Ft/${esc(x.egyseg || "db")}</td>
      <td>${ftd(x.netto)}</td><td>${x.afa != null ? `${FT.format(x.afa)}%` : "–"}</td>
      <td>${x.afa != null ? ftd(x.netto * (1 + x.afa / 100)) : ftd(x.netto)}</td></tr>`).join("");
    const afa = Object.entries(t.afa || {}).map(([k, v]) => `<tr><th scope="row" colspan="6">ÁFA ${FT.format(Number(k))}%</th><td>${ftd(v)}</td></tr>`).join("");
    const forras = t.kivetitve
      ? `a ${nap(t.tol)} óta mért fogyasztás (saját mérő), a mai naptól ${nap(t.ig)}-ig napi átlaggal kivetítve`
      : "a mért fogyasztás (valódi mérőállások és saját mérő) az időszakra";
    body.innerHTML = `
      <p class="kicsi">Elszámolási időszak: <b>${nap(t.tol)} – ${nap(t.ig)}</b> · fogyasztás összesen: <b>${szam(t.mennyiseg)} ${esc(t.egyseg)}</b>${t.becsult ? " (részben becsült)" : ""}<br>Alapja: ${forras}.</p>
      <div class="tablagorgeto"><table class="teteltabla">
        <thead><tr><th>Tétel</th><th>Fogyasztási időszak</th><th>Mennyiség</th><th>Nettó egységár</th><th>Nettó érték (Ft)</th><th>ÁFA</th><th>Bruttó érték (Ft)</th></tr></thead>
        <tbody>${sorok}</tbody>
        <tfoot><tr><th scope="row" colspan="6">Nettó számlaérték összesen</th><td>${ftd(t.netto)}</td></tr>${afa}
          ${t.kerekites ? `<tr><th scope="row" colspan="6">Kerekítés</th><td>${ftd(t.kerekites)}</td></tr>` : ""}
          <tr class="osszeg"><th scope="row" colspan="6">Bruttó számlaérték összesen (várható fizetendő)</th><td class="kmvarh">${ftd(t.brutto)}</td></tr></tfoot>
      </table></div>
      <p class="kicsi">Tájékoztató becslés, nem számla – a tételek a díjszabás szerint, a számla szerkezetében. A valódi számla eltérhet (a szolgáltató más állással, becsléssel vagy sávkorrekcióval számolhat; átalánynál a részszámla az átalány szerint jön).</p>`;
  }

  async _kimutatasNyit(entryId) {
    const d = this.shadowRoot.getElementById("kimutdlg");
    this._km = { entryId, adat: null, hiba: null, ev: this._km?.entryId === entryId ? this._km.ev : null, cella: null };
    if (!d.open) d.showModal();
    this._kimutatasRajzol();
    try {
      this._km.adat = await this._hass.callWS({ type: "hu_rezsi/szamla_kimutatas", entry_id: entryId });
    } catch (e) {
      this._km.hiba = e.message || String(e);
    }
    this._kimutatasRajzol();
  }

  _kimutatasKezelo() {
    const r = this.shadowRoot;
    const d = r.getElementById("kimutdlg");
    r.getElementById("kimutbezar").addEventListener("click", () => d.close());
    r.getElementById("kimutcsv").addEventListener("click", () => this._kimutatasCsv());
    r.getElementById("kimutnyomtat").addEventListener("click", () => this._kimutatasNyomtat());
    d.addEventListener("click", (ev) => ev.target === d && d.close());
    r.getElementById("kimutev").addEventListener("change", (ev) => { this._km.ev = ev.target.value; this._km.cella = null; this._kimutatasRajzol(); });
    r.getElementById("kimuttabla").addEventListener("click", (ev) => {
      const td = ev.target.closest("td[data-cella]");
      if (!td) return;
      this._km.cella = this._km.cella === td.dataset.cella ? null : td.dataset.cella;
      this._kimutatasRajzol();
    });
    if (this._km && d.open) this._kimutatasRajzol();
  }

  _kimutatasRajzol() {
    const r = this.shadowRoot, g = this._km;
    const el = (id) => r.getElementById(id);
    if (!g) return;
    el("kimutreszlet").innerHTML = "";
    g.csv = null;
    el("kimutcsv").disabled = true;
    el("kimutnyomtat").disabled = true;
    if (g.hiba) { el("kimuttabla").innerHTML = `<div class="figyszoveg">${esc(g.hiba)}</div>`; return; }
    if (!g.adat) { el("kimuttabla").innerHTML = `<div class="kicsi grafvar">Betöltés…</div>`; return; }
    const a = g.adat;
    el("kimutcim").textContent = `${a.nev} – számlák kimutatása`;
    const HONAPNEV = ["január", "február", "március", "április", "május", "június", "július", "augusztus", "szeptember", "október", "november", "december"];
    const evek = [...new Set(a.fiokok.flatMap((f) => f.szamlak.map((x) => x.kelte.slice(0, 4))))].sort().reverse();
    if (!g.ev) g.ev = "utolso12";
    el("kimutev").innerHTML = [`<option value="utolso12"${g.ev === "utolso12" ? " selected" : ""}>Utolsó 12 hónap</option>`,
      ...evek.map((y) => `<option value="${y}"${g.ev === y ? " selected" : ""}>${y}</option>`)].join("");
    // Sorok: hónapok (újabb felül)
    let honapok;
    const most = new Date().toISOString().slice(0, 7);
    // Várható (még nem érkezett) számlák hónapjai – a jövő hónapok csak ezekért jelennek meg.
    const vHonapok = [...new Set(a.fiokok.flatMap((f) => (f.varhato || []).map((v) => v.honap)))];
    if (g.ev === "utolso12") {
      const m = new Date(); honapok = vHonapok.filter((h) => h > most).sort().reverse();
      for (let i = 0; i < 12; i++) { const x = new Date(m.getFullYear(), m.getMonth() - i, 1); honapok.push(`${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}`); }
    } else {
      honapok = Array.from({ length: 12 }, (_, i) => `${g.ev}-${String(12 - i).padStart(2, "0")}`).filter((h) => h <= most || vHonapok.includes(h));
    }
    const fiokok = a.fiokok.filter((f) => f.szamlak.length || (f.varhato || []).length);
    if (!fiokok.length) { el("kimuttabla").innerHTML = `<div class="kicsi">Ennek az otthonnak még nincs rögzített számlája.</div>`; return; }
    const ertek = (x) => {
      // Mindig a fizetendő: az elszámoló számlaértéke a korábbi (havi) számlákat is magában foglalja, összeadva kétszer
      // számolna; a fizetendők összege a ténylegesen kifizetett összeg. A számlaérték csak a cella részleteiben áll.
      const v = x.osszeg;
      return v == null || x.tipus === "storno" ? 0 : Number(v);
    };
    const cella = {};
    for (const f of fiokok) for (const x of f.szamlak) {
      const k = `${f.sid}|${x.kelte.slice(0, 7)}`;
      (cella[k] = cella[k] || []).push(x);
    }
    const vcella = {};
    for (const f of fiokok) for (const v of f.varhato || []) {
      const k = `${f.sid}|${v.honap}`;
      (vcella[k] = vcella[k] || []).push(v);
    }
    const vOsszeg = (l) => l.reduce((t, v) => t + v.osszeg, 0);
    const fmt = (v) => (v === 0 ? "0 Ft" : ft(Math.round(v)));
    const vfmt = (v) => `~${fmt(v)}`;
    const jel = (lista) => (lista.some((x) => x.tipus === "elszamolo" || x.tipus === "vegszamla") ? `<span class="kmjel" title="elszámoló számla">E</span>` : "")
      + (lista.some((x) => x.fizetes && !x.fizetes.fizetve && !x.fizetes.nincs_fizetendo && x.fizetes.hatarido && x.fizetes.hatarido >= new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10))
        ? `<span class="kmnyit" title="nincs kifizetve">!</span>` : "");
    const oszlopOssz = {}, vOszlop = {}; let mindOssz = 0, vMind = 0;
    const varhSor = (h, cim = "várható – még nem érkezett") => {
      if (!fiokok.some((f) => vcella[`${f.sid}|${h}`])) return "";
      let ossz = 0;
      const tdk = fiokok.map((f) => {
        const l = vcella[`${f.sid}|${h}`];
        if (!l) return `<td class="ures"></td>`;
        const v = vOsszeg(l), k = `v|${f.sid}|${h}`;
        ossz += v; vOszlop[f.sid] = (vOszlop[f.sid] || 0) + v;
        return `<td data-cella="${k}" class="kmvarh${g.cella === k ? " aktiv" : ""}" title="${esc(l.map((x) => `várható ${x.kelte} · ${FORRAS_NEV[x.forras] || x.forras} · ${fmt(x.osszeg)}`).join("\n"))}">${vfmt(v)}${l.length > 1 ? `<span class="kmdb">${l.length}×</span>` : ""}</td>`;
      });
      vMind += ossz;
      return `<tr class="kmvarhsor"><th scope="row">${cim}</th>${tdk.join("")}<td class="osszcella kmvarh">${vfmt(ossz)}</td></tr>`;
    };
    const sorok = honapok.map((h) => {
      if (h > most) {
        const [y, m] = h.split("-");
        return varhSor(h, `${y}. ${HONAPNEV[+m - 1]} – várható`);
      }
      let sorOssz = 0, van = false;
      const tdk = fiokok.map((f) => {
        const lista = cella[`${f.sid}|${h}`];
        if (!lista) return `<td class="ures">–</td>`;
        van = true;
        const v = lista.reduce((t, x) => t + ertek(x), 0);
        sorOssz += v; oszlopOssz[f.sid] = (oszlopOssz[f.sid] || 0) + v;
        const k = `${f.sid}|${h}`;
        return `<td data-cella="${k}" class="${v < 0 ? "minuszft" : ""}${g.cella === k ? " aktiv" : ""}" title="${esc(lista.map((x) => `${x.sorszam} · ${x.kelte} · ${fmt(ertek(x))}`).join("\n"))}">${fmt(v)}${lista.length > 1 ? `<span class="kmdb">${lista.length}×</span>` : ""}${jel(lista)}</td>`;
      });
      mindOssz += sorOssz;
      const [y, m] = h.split("-");
      return `<tr class="${van ? "" : "uressor"}"><th scope="row">${y}. ${HONAPNEV[+m - 1]}</th>${tdk.join("")}<td class="osszcella">${van ? fmt(sorOssz) : "–"}</td></tr>` + varhSor(h);
    });
    const vanVarh = Object.keys(vOszlop).length > 0;
    el("kimuttabla").innerHTML = `<div class="tablagorgeto"><table>
      <thead><tr><th scope="col">Hónap</th>${fiokok.map((f) => `<th scope="col" class="km-${f.kozmu || "egyeb"}"><ha-icon icon="${IKON[f.kozmu] || "mdi:cash"}"></ha-icon><span>${esc(f.nev)}</span><small>${esc(f.szolgaltato || "")}</small></th>`).join("")}<th scope="col" class="osszcella">Összesen</th></tr></thead>
      <tbody>${sorok.join("")}</tbody>
      <tfoot><tr><th scope="row">Összesen${vanVarh ? " (beérkezett)" : ""}</th>${fiokok.map((f) => `<td class="${(oszlopOssz[f.sid] || 0) < 0 ? "minuszft" : ""}">${oszlopOssz[f.sid] != null ? fmt(oszlopOssz[f.sid]) : "–"}</td>`).join("")}<td class="osszcella">${fmt(mindOssz)}</td></tr>
      ${vanVarh ? `<tr class="kmvarhsor"><th scope="row">Várható (még nem érkezett)</th>${fiokok.map((f) => `<td class="kmvarh">${vOszlop[f.sid] != null ? vfmt(vOszlop[f.sid]) : ""}</td>`).join("")}<td class="osszcella kmvarh">${vfmt(vMind)}</td></tr>
      <tr><th scope="row">Összesen várhatóval</th>${fiokok.map((f) => `<td>${oszlopOssz[f.sid] != null || vOszlop[f.sid] != null ? fmt((oszlopOssz[f.sid] || 0) + (vOszlop[f.sid] || 0)) : "–"}</td>`).join("")}<td class="osszcella">${fmt(mindOssz + vMind)}</td></tr>` : ""}</tfoot>
    </table></div>`;
    // CSV és PDF: ugyanaz a táblázat, egész forintokkal (üres cella = nincs számla); a várható számlák külön sorban.
    const egesz = (v) => (v == null ? "" : String(Math.round(v)));
    const tabla = [];
    for (const h of honapok) {
      const [y, m] = h.split("-");
      const nev = `${y}. ${HONAPNEV[+m - 1]}`;
      if (h <= most) {
        const cellak = fiokok.map((f) => {
          const l = cella[`${f.sid}|${h}`];
          return l ? { v: l.reduce((t, x) => t + ertek(x), 0), e: l.some((x) => x.tipus === "elszamolo" || x.tipus === "vegszamla"), db: l.length } : null;
        });
        tabla.push({ honap: nev, cellak, ossz: cellak.some(Boolean) ? cellak.reduce((t, c) => t + (c ? c.v : 0), 0) : null });
      }
      const vc = fiokok.map((f) => { const l = vcella[`${f.sid}|${h}`]; return l ? { v: vOsszeg(l), e: false, db: l.length } : null; });
      if (vc.some(Boolean)) tabla.push({ honap: `${nev} – várható`, cellak: vc, ossz: vc.reduce((t, c) => t + (c ? c.v : 0), 0), varh: true });
    }
    const labOssz = fiokok.map((f) => (oszlopOssz[f.sid] != null || vOszlop[f.sid] != null ? (oszlopOssz[f.sid] || 0) + (vOszlop[f.sid] || 0) : null));
    g.csv = {
      nev: `${a.nev}_számlák`,
      sorok: [["Hónap", ...fiokok.map((f) => `${f.nev} (${f.szolgaltato || ""})`), "Összesen"],
        ...tabla.map((t) => [t.honap, ...t.cellak.map((c) => egesz(c?.v)), egesz(t.ossz)]),
        [vanVarh ? "Összesen (beérkezett)" : "Összesen", ...fiokok.map((f) => egesz(oszlopOssz[f.sid])), egesz(mindOssz)],
        ...(vanVarh ? [["Várható (még nem érkezett)", ...fiokok.map((f) => egesz(vOszlop[f.sid])), egesz(vMind)],
          ["Összesen várhatóval", ...labOssz.map(egesz), egesz(mindOssz + vMind)]] : [])],
      // A PDF-hez: cellánként érték, elszámoló-jel és darabszám; a várható sorok jelölve.
      fej: fiokok.map((f) => ({ nev: f.nev, szolg: f.szolgaltato || "" })),
      tabla,
      oszlopOssz: fiokok.map((f) => oszlopOssz[f.sid] ?? null),
      mindOssz,
      varh: vanVarh ? { oszlop: fiokok.map((f) => vOszlop[f.sid] ?? null), mind: vMind, egyutt: labOssz } : null,
      cim: `${a.nev} – számlák kimutatása`,
      al: `Időszak: ${g.ev === "utolso12" ? "utolsó 12 hónap" : `${g.ev}. év`} · Összeg: fizetendő · Készült: ${new Date().toLocaleDateString("hu-HU")}`,
    };
    el("kimutcsv").disabled = false;
    el("kimutnyomtat").disabled = false;
    if (g.cella?.startsWith("v|") && vcella[g.cella.slice(2)]) {
      const [, sid] = g.cella.split("|"), f = fiokok.find((x) => x.sid === sid);
      const MAGY = {
        meres: "a mért fogyasztás díja az időszakra (a folyó időszaknál a végéig előrevetítve)",
        diktalas: "a diktált mérőállás szerinti fogyasztás díja",
        atalany: "a következő részszámla az átalány szerint",
        fix: "a fix díj az ütem szerint",
        elszamolas: "a várható éves egyenleg alapján (mínusz: visszajár)",
      };
      el("kimutreszlet").innerHTML = `<div class="cimke">${esc(f.nev)} – várható, még nem érkezett számla</div>` + vcella[g.cella.slice(2)].map((v) => `<div class="kmsor">
        <b class="kmvarh">~${fmt(v.osszeg)}</b> · ${FORRAS_NEV[v.forras] || esc(v.forras)} · várható kelte ${nap(v.kelte)}${v.tol ? ` · ${nap(v.tol)} – ${nap(v.ig)}` : ""}${
          ["meres", "diktalas"].includes(v.forras) && v.tol && v.ig ? ` <button type="button" class="linkgomb" data-tetel="${sid}" data-entry="${g.entryId}" data-tol="${v.tol}" data-ig="${v.ig}">tételesen ›</button>` : ""}
        <span class="kicsi">Becslés: ${MAGY[v.forras] || ""}. A számla megérkezésekor helyette a valódi fizetendő áll.</span></div>`).join("");
    } else if (g.cella && cella[g.cella]) {
      const [sid] = g.cella.split("|"), f = fiokok.find((x) => x.sid === sid);
      const TIP = { resz: "részszámla", elszamolo: "elszámoló", vegszamla: "végszámla", storno: "stornó", egyeb: "számla", eloiras: "előírás" };
      // Elszámolónál a számlaérték az egész elszámolt időszak (akár egy fűtési szezon) díja, a fizetendő pedig a
      // levonások (korábbi részszámlák, túlfizetés) utáni összeg – ezt kiírjuk, különben egy havi költségnek tűnne.
      const menny = (x) => x.elszamolt_kwh != null ? szam(Number(x.elszamolt_kwh), "kWh")
        : x.elszamolt_gaz?.m3 != null ? szam(Number(x.elszamolt_gaz.m3), "m³")
        : x.elszamolt_viz?.ivoviz != null ? szam(Number(x.elszamolt_viz.ivoviz), "m³") : "";
      const magyaraz = (x) => {
        if (x.tipus === "storno" || x.szamlaertek == null) return "";
        const honap = x.idoszak ? Math.round(((new Date(x.idoszak[1]) - new Date(x.idoszak[0])) / 864e5 + 1) / 30.44) : 0;
        const m = menny(x), r = [];
        if (honap >= 2) r.push(`A számlaérték a teljes elszámolt időszak díja: ${honap} hónap${m ? `, ${m}` : ""}.`);
        else if (m) r.push(`Elszámolt mennyiség: ${m}.`);
        if (x.egyeb_tetelek?.length) {
          r.push(`A fizetendő a közös MVM-folyószámla tételeit is tartalmazza: ${x.egyeb_tetelek.map(([n, o]) => `${esc(n)} ${fmt(Number(o))}`).join(", ")} – ezek nem e fiók díjai (pl. egy másik fiók jóváírásának átvezetése), a költségben a számlaérték számít.${x.folyoszamla != null ? ` Folyószámla-egyenleg a kibocsátáskor: ${fmt(Number(x.folyoszamla))}.` : ""}`);
          return `<span class="kicsi">${r.join(" ")}</span>`;
        }
        const kul = Math.round(Number(x.szamlaertek) - Number(x.osszeg ?? x.szamlaertek));
        if (kul > 0) r.push(`Ebből ${ft(kul)} levonva (korábbi részszámlák, túlfizetés), így ${Number(x.osszeg) < 0 ? `${ft(-Number(x.osszeg))} visszajár` : `${ft(Number(x.osszeg))} a fizetendő`}.`);
        else if (kul < 0) r.push(`A fizetendő ${ft(-kul)} korábbi tartozást is tartalmaz.`);
        return r.length ? `<span class="kicsi">${r.join(" ")}</span>` : "";
      };
      el("kimutreszlet").innerHTML = `<div class="cimke">${esc(f.nev)} – a hónap számlái</div>` + cella[g.cella].map((x) => `<div class="kmsor">
        <b>${esc(x.sorszam)}</b> · ${TIP[x.tipus] || esc(x.tipus || "")}${x.kezi ? " · kézi" : ""} · kelte ${nap(x.kelte)}${x.idoszak ? ` · ${nap(x.idoszak[0])} – ${nap(x.idoszak[1])}` : ""}
        <span class="kicsi">fizetendő ${x.osszeg != null ? fmt(Number(x.osszeg)) : "–"}${x.szamlaertek != null ? ` · számlaérték ${fmt(Number(x.szamlaertek))}` : ""}${x.fizetes?.hatarido ? ` · határidő ${nap(x.fizetes.hatarido)}` : ""}
          · ${!x.fizetes ? "" : x.fizetes.nincs_fizetendo ? "nincs fizetendő" : x.fizetes.fizetve ? `fizetve ${x.fizetes.datum ? nap(x.fizetes.datum) : ""}${x.fizetes.forras === "dijnet" ? " (Díjnet)" : x.fizetes.forras === "beszedes" ? " (beszedési megbízás)" : x.fizetes.forras === "utemezett" ? " (állandó átutalás)" : ""}` : `<b class="lejart">nincs kifizetve${x.fizetes.lejart ? " – lejárt" : ""}</b>`}</span>${magyaraz(x)}</div>`).join("");
    }
    el("kimutmegj").innerHTML = `A hónap a számla kelte szerint. Az összeg a <b>fizetendő</b>: amit a számla szerint fizetni kellett (elszámolónál a korábbi számlák és a túlfizetés levonása után – mínusz: visszajár), így az összesen a ténylegesen kifizetett összeg. <span class="kmvarh">~narancs</span>: várható, még nem érkezett számla – a Rezsikövető becslése a saját mérésből, a diktált állásból, az átalányból, a fix díjból vagy a várható elszámolásból, a várható kelte hónapjában. <span class="kmjel">E</span> elszámoló számla, <span class="kmnyit">!</span> nincs kifizetve (az utolsó 90 napból). Egy cellára koppintva alatta a számla adatai. A fejléc gombjaival a táblázat kinyomtatható (vagy PDF-be menthető), illetve CSV-be letölthető (Excelben megnyitható).`;
  }

  _kimutatasCsv() {
    const c = this._km?.csv;
    if (!c) return;
    // Pontosvessző + UTF-8 BOM: a magyar Excel így oszlopokra bontva, ékezethelyesen nyitja meg.
    const mezo = (x) => (/[;"\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x);
    const szoveg = "\ufeff" + c.sorok.map((sor) => sor.map((x) => mezo(String(x))).join(";")).join("\r\n") + "\r\n";
    const url = URL.createObjectURL(new Blob([szoveg], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${c.nev.replace(/[\\/:*?"<>|\s]+/g, "_")}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  _mobil() {
    return /Android|iPhone|iPad|iPod|Mobile|Home Assistant\//i.test(navigator.userAgent) || matchMedia("(pointer: coarse)").matches;
  }

  _letolt(blob, nev) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nev;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  // Mobilon a nyomtatás helyett PDF-fájl: a táblázat vászonra rajzolva (az ékezetekhez nem kell beágyazott betűkészlet),
  // oldalanként JPEG-képként egy fekvő A4-es PDF-be.
  async _kimutatasPdf() {
    const c = this._km?.csv;
    if (!c) return;
    const W = 1754, H = 1240, M = 70;  // A4 fekvő, 150 dpi
    const betu = getComputedStyle(this).fontFamily || "Roboto, Arial, sans-serif";
    const meres = document.createElement("canvas").getContext("2d");
    const fmt = (v) => `${FT.format(Math.round(v))} Ft`;
    // Méretezés: ha az oszlopok nem férnek ki, a betűméret csökken.
    let sz = 22, elso, oszl;
    for (; sz >= 12; sz -= 1) {
      meres.font = `${sz}px ${betu}`;
      elso = Math.max(...[c.sorok[0][0], ...c.tabla.map((x) => x.honap), "Összesen"].map((t) => meres.measureText(t).width)) + sz;
      const cellaSz = (t) => meres.measureText(t).width + sz * 2.2;
      meres.font = `bold ${sz}px ${betu}`;
      const fejSz = c.fej.map((f) => meres.measureText(f.nev).width + sz);
      meres.font = `${sz}px ${betu}`;
      oszl = c.fej.map((f, j) => Math.max(fejSz[j], meres.measureText(f.szolg).width * 0.8 + sz,
        ...c.tabla.map((x) => (x.cellak[j] ? cellaSz(fmt(x.cellak[j].v)) : 0)), cellaSz(c.oszlopOssz[j] != null ? fmt(c.oszlopOssz[j]) : "")));
      oszl.push(Math.max(meres.measureText("Összesen").width + sz, cellaSz(fmt(c.mindOssz))));
      if (elso + oszl.reduce((t, x) => t + x, 0) <= W - 2 * M) break;
    }
    const tobblet = (W - 2 * M - elso - oszl.reduce((t, x) => t + x, 0)) / oszl.length;
    if (tobblet > 0) oszl = oszl.map((x) => x + Math.min(tobblet, sz * 4));
    const sorM = Math.round(sz * 1.55), fejM = Math.round(sz * 2.6);
    const lapon = Math.max(1, Math.floor((H - 2 * M - 110 - fejM - sorM * (c.varh ? 3 : 1) - 60) / sorM));
    const lapok = [];
    for (let i = 0; i < c.tabla.length || i === 0; i += lapon) lapok.push(c.tabla.slice(i, i + lapon));
    const kepek = [];
    for (const [li, sorok] of lapok.entries()) {
      const cv = Object.assign(document.createElement("canvas"), { width: W, height: H });
      const x = cv.getContext("2d");
      x.fillStyle = "#fff"; x.fillRect(0, 0, W, H);
      x.textBaseline = "middle";
      let y = M;
      x.fillStyle = "#111"; x.font = `bold ${Math.round(sz * 1.5)}px ${betu}`; x.textAlign = "left";
      x.fillText(c.cim, M, y + sz * 0.7);
      y += sz * 2.3;
      x.fillStyle = "#555"; x.font = `${sz}px ${betu}`;
      x.fillText(c.al + (lapok.length > 1 ? ` · ${li + 1}/${lapok.length}. oldal` : ""), M, y);
      y += sz * 1.8;
      const jobb = (szoveg, xj, yy) => { x.textAlign = "right"; x.fillText(szoveg, xj, yy); x.textAlign = "left"; };
      const oszlX = [M + elso];
      for (const w of oszl) oszlX.push(oszlX.at(-1) + w);
      const szel = oszlX.at(-1);
      // Fejléc
      x.fillStyle = "#111"; x.font = `bold ${sz}px ${betu}`;
      x.fillText("Hónap", M + sz * 0.3, y + fejM - sz * 0.8);
      c.fej.forEach((f, j) => {
        jobb(f.nev, oszlX[j + 1] - sz * 0.4, y + fejM * 0.38);
        x.fillStyle = "#666"; x.font = `${Math.round(sz * 0.8)}px ${betu}`;
        jobb(f.szolg, oszlX[j + 1] - sz * 0.4, y + fejM * 0.75);
        x.fillStyle = "#111"; x.font = `bold ${sz}px ${betu}`;
      });
      jobb("Összesen", szel - sz * 0.4, y + fejM - sz * 0.8);
      y += fejM;
      x.fillStyle = "#444"; x.fillRect(M, y - 2, szel - M, 3);
      const cellaIr = (v, e, db, xj, yy, vastag, varh = false) => {
        let jx = xj - sz * 0.4;
        if (e) {  // E jel
          x.font = `bold ${Math.round(sz * 0.62)}px ${betu}`;
          const w = x.measureText("E").width + sz * 0.35;
          x.strokeStyle = "#333"; x.lineWidth = 1.5;
          x.strokeRect(jx - w, yy - sz * 0.42, w, sz * 0.84);
          x.fillStyle = "#333"; x.textAlign = "center"; x.fillText("E", jx - w / 2, yy + 1); x.textAlign = "left";
          jx -= w + sz * 0.3;
        }
        if (db > 1) {
          x.font = `${Math.round(sz * 0.7)}px ${betu}`; x.fillStyle = "#666";
          jobb(`${db}×`, jx, yy + sz * 0.1);
          jx -= x.measureText(`${db}×`).width + sz * 0.2;
        }
        x.font = `${varh ? "italic " : ""}${vastag ? "bold " : ""}${sz}px ${betu}`;
        x.fillStyle = varh ? "#b35f00" : v < 0 ? "#1b7f3b" : "#111";
        jobb(varh ? `~${fmt(v)}` : fmt(v), jx, yy);
      };
      sorok.forEach((s, i) => {
        if (s.varh) { x.fillStyle = "#fff3e0"; x.fillRect(M, y, szel - M, sorM); } else if (i % 2) { x.fillStyle = "#f4f4f4"; x.fillRect(M, y, szel - M, sorM); }
        const yy = y + sorM / 2;
        const ures = s.ossz == null;
        x.fillStyle = s.varh ? "#b35f00" : ures ? "#999" : "#111"; x.font = `${s.varh ? "italic " : ""}${sz}px ${betu}`;
        x.fillText(s.honap, M + sz * (s.varh ? 0.9 : 0.3), yy);
        s.cellak.forEach((cl, j) => {
          if (cl) cellaIr(cl.v, cl.e, cl.db, oszlX[j + 1], yy, false, s.varh);
          else if (!s.varh) { x.fillStyle = "#aaa"; x.font = `${sz}px ${betu}`; jobb("–", oszlX[j + 1] - sz * 0.4, yy); }
        });
        if (ures) { x.fillStyle = "#aaa"; jobb("–", szel - sz * 0.4, yy); } else cellaIr(s.ossz, false, 1, szel, yy, true, s.varh);
        y += sorM;
        x.fillStyle = "#ddd"; x.fillRect(M, y - 1, szel - M, 1);
      });
      x.fillStyle = "#bbb"; x.fillRect(oszlX.at(-2), y - sorM * sorok.length - fejM, 1.5, fejM + sorM * sorok.length);
      if (li === lapok.length - 1) {
        x.fillStyle = "#444"; x.fillRect(M, y, szel - M, 3);
        const yy = y + sorM / 2 + 3;
        x.fillStyle = "#111"; x.font = `bold ${sz}px ${betu}`;
        x.fillText(c.varh ? "Összesen (beérkezett)" : "Összesen", M + sz * 0.3, yy);
        c.oszlopOssz.forEach((v, j) => v != null && cellaIr(v, false, 1, oszlX[j + 1], yy, true));
        cellaIr(c.mindOssz, false, 1, szel, yy, true);
        if (c.varh) {
          for (const [cim, ertekek, mind, varh] of [["Várható (még nem érkezett)", c.varh.oszlop, c.varh.mind, true],
            ["Összesen várhatóval", c.varh.egyutt, c.mindOssz + c.varh.mind, false]]) {
            y += sorM;
            const y2 = y + sorM / 2 + 3;
            x.fillStyle = varh ? "#b35f00" : "#111"; x.font = `${varh ? "italic " : ""}bold ${sz}px ${betu}`;
            x.fillText(cim, M + sz * 0.3, y2);
            ertekek.forEach((v, j) => v != null && cellaIr(v, false, 1, oszlX[j + 1], y2, true, varh));
            cellaIr(mind, false, 1, szel, y2, true, varh);
          }
        }
        y += sorM + sz * 1.5;
        x.fillStyle = "#555"; x.font = `${Math.round(sz * 0.75)}px ${betu}`;
        x.fillText("A hónap a számla kelte szerint; az összeg a fizetendő (elszámolónál a korábbi számlák és a túlfizetés levonása után – mínusz: visszajár),", M, y);
        x.fillText("így az összesen a ténylegesen kifizetett összeg. Narancs, „~”: várható, még nem érkezett számla (becslés). E = elszámoló számla, „2×” = több számla a hónapban.", M, y + sz * 1.05);
      }
      kepek.push(new Uint8Array(await (await new Promise((ok) => cv.toBlob(ok, "image/jpeg", 0.9))).arrayBuffer()));
    }
    // Minimális PDF: oldalanként egy JPEG (DCTDecode) a teljes A4 fekvő lapon.
    const enc = new TextEncoder(), reszek = [], eltolas = [];
    let hossz = 0;
    const ir = (d) => { const b = typeof d === "string" ? enc.encode(d) : d; reszek.push(b); hossz += b.length; };
    const obj = (n, tartalom) => { eltolas[n] = hossz; ir(`${n} 0 obj\n`); tartalom(); ir("\nendobj\n"); };
    ir("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n");
    const n = kepek.length, lapId = (i) => 3 + i * 3;
    obj(1, () => ir("<< /Type /Catalog /Pages 2 0 R >>"));
    obj(2, () => ir(`<< /Type /Pages /Count ${n} /Kids [${kepek.map((_, i) => `${lapId(i)} 0 R`).join(" ")}] >>`));
    kepek.forEach((jpg, i) => {
      const p = lapId(i), tart = `q 842 0 0 595 0 0 cm /Im0 Do Q`;
      obj(p, () => ir(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /XObject << /Im0 ${p + 2} 0 R >> >> /Contents ${p + 1} 0 R >>`));
      obj(p + 1, () => ir(`<< /Length ${tart.length} >>\nstream\n${tart}\nendstream`));
      obj(p + 2, () => { ir(`<< /Type /XObject /Subtype /Image /Width ${W} /Height ${H} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpg.length} >>\nstream\n`); ir(jpg); ir("\nendstream"); });
    });
    const osszes = 3 + n * 3, xref = hossz;
    ir(`xref\n0 ${osszes}\n0000000000 65535 f \n${Array.from({ length: osszes - 1 }, (_, i) => `${String(eltolas[i + 1]).padStart(10, "0")} 00000 n \n`).join("")}`);
    ir(`trailer\n<< /Size ${osszes} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
    this._letolt(new Blob(reszek, { type: "application/pdf" }), `${c.nev.replace(/[\\/:*?"<>|\s]+/g, "_")}.pdf`);
  }

  // ---------------------------------------------------------------- Folyószámla (könyvelési kivonat)
  // Nyitó egyenleg, majd időrendben: számla (kiállítás kelte) a Követel, befizetés / jóváírás a Tartozik oszlopban,
  // futó egyenleggel (pozitív: hátralék, negatív: túlfizetés). MVM közös folyószámlánál a villanyfiókok együtt.
  async _folyoszamlaNyit(f) {
    const d = this.shadowRoot.getElementById("fszdlg");
    // egyutt: MVM közös folyószámlánál minden tarifa egy kivonatban (mint a szolgáltató kimutatásán) – ez az alap.
    this._fsz = { f, adat: null, idoszak: this._fsz?.f === f ? this._fsz.idoszak : "utolso12", nezet: this._fsz?.nezet || "teljesites", hiba: null,
      egyutt: this._fsz?.egyutt ?? true };
    if (!d.open) d.showModal();
    this._folyoszamlaRajzol();
    try {
      this._fsz.adat = await this._hass.callWS({ type: "hu_rezsi/folyoszamla", sid: f.sid, egyutt: this._fsz.egyutt });
    } catch (e) {
      this._fsz.hiba = e.message || String(e);
    }
    this._folyoszamlaRajzol();
  }

  _folyoszamlaKezelo() {
    const r = this.shadowRoot, d = r.getElementById("fszdlg");
    r.getElementById("fszbezar").addEventListener("click", () => d.close());
    d.addEventListener("click", (ev) => ev.target === d && d.close());
    r.getElementById("fszidoszak").addEventListener("change", (ev) => { this._fsz.idoszak = ev.target.value; this._folyoszamlaRajzol(); });
    d.querySelectorAll("[data-fsznezet]").forEach((b) => b.addEventListener("click", () => { this._fsz.nezet = b.dataset.fsznezet; this._folyoszamlaRajzol(); }));
    r.getElementById("fszmod").addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-fszegyutt]");
      if (!b || !this._fsz?.f) return;
      const egyutt = b.dataset.fszegyutt === "1";
      if (egyutt === this._fsz.egyutt) return;
      this._fsz.egyutt = egyutt;
      this._folyoszamlaNyit(this._fsz.f);
    });
    r.getElementById("fszcsv").addEventListener("click", () => this._folyoszamlaCsv());
    r.getElementById("fsznyomtat").addEventListener("click", () => this._folyoszamlaNyomtat());
    r.getElementById("fsztabla").addEventListener("click", async (ev) => {
      const egy = ev.target.closest("[data-fszegyeztet]");
      if (egy) {
        const [datum, elteres, sorszam] = egy.dataset.fszegyeztet.split("|");
        const e = Number(elteres);
        this._fsz.kezi = { datum, nev: `Egyeztetés a szolgáltató folyószámlájával (${sorszam})`, osszeg: Math.abs(e), oldal: e > 0 ? "tartozik" : "kovetel" };
        this._folyoszamlaRajzol();
        r.getElementById("fszkeziszerk")?.scrollIntoView({ block: "nearest" });
        return;
      }
      const ktorol = ev.target.closest("[data-fszkezitorol]");
      const ment = ev.target.closest("[data-fszkezi]");
      if ((ktorol || ment) && this._fsz?.f) {
        const adat = ktorol ? { torles: ktorol.dataset.fszkezitorol, datum: "" } : (() => {
          const o = Number(String(r.getElementById("fszkeziosszeg").value).replace(/\s/g, "").replace(",", "."));
          const oldal = r.getElementById("fszkezioldal").value;
          return { datum: r.getElementById("fszkezidatum").value, megnevezes: r.getElementById("fszkezinev").value,
            kovetel: oldal === "kovetel" ? o : 0, tartozik: oldal === "tartozik" ? o : 0 };
        })();
        if (!ktorol && (!adat.datum || !(adat.kovetel || adat.tartozik))) return;
        (ktorol || ment).disabled = true;
        try {
          this._fsz.adat = await this._hass.callWS({ type: "hu_rezsi/folyoszamla_tetel", sid: this._fsz.f.sid, egyutt: this._fsz.egyutt, ...adat });
          this._fsz.kezi = null;
        } catch (e) {
          this._fsz.hiba = e.message || String(e);
        }
        this._folyoszamlaRajzol();
        return;
      }
      const gomb = ev.target.closest("[data-fsznyito]");
      if (!gomb || !this._fsz?.f) return;
      const torol = gomb.dataset.fsznyito === "torol";
      const datum = r.getElementById("fsznyitodatum")?.value || null;
      const osszeg = r.getElementById("fsznyitoosszeg")?.value;
      if (!torol && (osszeg === "" || osszeg == null)) return;
      gomb.disabled = true;
      try {
        this._fsz.adat = await this._hass.callWS({ type: "hu_rezsi/folyoszamla_nyito", sid: this._fsz.f.sid, egyutt: this._fsz.egyutt,
          datum, osszeg: torol ? null : Number(String(osszeg).replace(/\s/g, "").replace(",", ".")) });
      } catch (e) {
        this._fsz.hiba = e.message || String(e);
      }
      this._folyoszamlaRajzol();
    });
    if (this._fsz && d.open) this._folyoszamlaRajzol();
  }

  // A kiválasztott időszak tételei: nyitó egyenleg (az időszak előtti utolsó egyenleg), tételek, forgalom, záró.
  _fszHatar() {
    const g = this._fsz, ma = new Date().toISOString().slice(0, 10);
    if (g.idoszak === "utolso12") { const d = new Date(); d.setFullYear(d.getFullYear() - 1); d.setDate(d.getDate() + 1); return { tol: d.toISOString().slice(0, 10), ig: ma, cim: "utolsó 12 hónap" }; }
    if (/^\d{4}$/.test(g.idoszak)) return { tol: `${g.idoszak}-01-01`, ig: `${g.idoszak}-12-31`, cim: `${g.idoszak}. év` };
    return { tol: null, ig: null, cim: "teljes időszak" };
  }

  // Teljesítés-nézet: a kiválasztott időszak számlái (kelte szerint), a várható számlák és az összesítő.
  _fszTeljNezet() {
    const a = this._fsz?.adat, t = a?.teljesites;
    if (!t) return null;
    const { tol, ig, cim } = this._fszHatar(), ma = new Date().toISOString().slice(0, 10);
    const sorok = t.sorok.filter((x) => (!tol || x.kelte >= tol) && (!ig || x.kelte <= ig));
    const o = { szamlazva: 0, fizetve: 0, nyitott: 0, lejart: 0 };
    for (const x of sorok) {
      if (x.tipus === "storno" || !(x.fizetendo > 0)) continue;
      o.szamlazva += x.fizetendo;
      if (x.fizetve) o.fizetve += x.fizetve.osszeg; else { o.nyitott += x.fizetendo; if (x.allapot === "lejart") o.lejart += x.fizetendo; }
    }
    const varhato = !ig || ig >= ma ? t.varhato || [] : [];
    return { cim, sorok, varhato, o, tulfizetes: t.beszamitas ? t.beszamitas.marad + t.beszamitas.levonva : t.osszesen.tulfizetes, beszamitas: t.beszamitas };
  }

  _fszNezet() {
    const g = this._fsz, a = g?.adat;
    if (!a) return null;
    const ma = new Date().toISOString().slice(0, 10);
    let tol = null, ig = null, cim = "teljes időszak";
    if (g.idoszak === "utolso12") {
      const d = new Date(); d.setFullYear(d.getFullYear() - 1); d.setDate(d.getDate() + 1);
      tol = d.toISOString().slice(0, 10); ig = ma; cim = "utolsó 12 hónap";
    } else if (/^\d{4}$/.test(g.idoszak)) {
      tol = `${g.idoszak}-01-01`; ig = `${g.idoszak}-12-31`; cim = `${g.idoszak}. év`;
    }
    const elotte = tol ? a.tetelek.filter((t) => t.datum < tol) : [];
    const nyito = tol ? { datum: elotte.length ? elotte.at(-1).datum : a.nyito.datum, osszeg: elotte.length ? elotte.at(-1).egyenleg : a.nyito.osszeg,
      forras: elotte.length ? "az előző időszak záró egyenlege" : a.nyito.forras } : a.nyito;
    const tetelek = a.tetelek.filter((t) => (!tol || t.datum >= tol) && (!ig || t.datum <= ig));
    const kov = tetelek.reduce((s, t) => s + t.kovetel, 0), tart = tetelek.reduce((s, t) => s + t.tartozik, 0);
    return { cim, nyito, tetelek, kov, tart, zaro: nyito.osszeg + kov - tart };
  }

  _fszTeljRajzol() {
    const r = this.shadowRoot, a = this._fsz.adat, n = this._fszTeljNezet();
    const el = (id) => r.getElementById(id);
    if (!n) { el("fsztabla").innerHTML = `<p class="kicsi">Nincs adat.</p>`; return; }
    const FORRAS = { kezi: "", dijnet: "Díjnet", beszedes: "beszedés", utemezett: "állandó átutalás", feltetelezett: "feltételezett", egyenleg: "egyenleg szerint" };
    const reszlet = (x) => [a.kozos ? esc(x.fiok) : "", x.idoszak ? `${nap(x.idoszak[0])} – ${nap(x.idoszak[1])}` : "", esc(x.mennyiseg || ""), esc(x.allasok || "")].filter(Boolean).join(" · ");
    const sorok = n.sorok.map((x) => `<tr class="fszt-${x.allapot}">
        <td class="fszdatum">${rovidNap(x.kelte)}</td>
        <td class="fszmegn"><span>${esc(x.megnevezes)}</span>${reszlet(x) ? `<small>${reszlet(x)}</small>` : ""}${x.beszamitva ? `<small>beszámítva a(z) ${esc(x.beszamitva)} ${x.beszamitva.includes(", ") ? "számlákon (részletekben)" : "számlán"}</small>` : ""}${x.szamlaertek != null && x.fizetendo != null && Math.abs(x.szamlaertek - x.fizetendo) >= 1 && x.tipus !== "storno" ? `<small>a számla saját értéke ${ft(x.szamlaertek)} – a különbség beszámítás (korábbi egyenleg${a.kozos_fiokok?.length ? ", közös folyószámla" : ""})</small>` : ""}</td>
        <td class="fszdatum">${x.hatarido ? rovidNap(x.hatarido) : ""}</td>
        <td class="${x.fizetendo < 0 ? "minuszft" : ""}">${x.fizetendo != null ? ft(x.fizetendo) : ""}</td>
        <td>${x.fizetve ? `${rovidNap(x.fizetve.datum)}<small>${ft(x.fizetve.osszeg)}${FORRAS[x.fizetve.forras] ? ` · ${FORRAS[x.fizetve.forras]}` : ""}</small>${x.fizetendo - x.fizetve.osszeg >= 1 && x.allapot === "fizetve" ? `<small>a többi (${ft(x.fizetendo - x.fizetve.osszeg)}) jóváírásból</small>` : ""}` : x.allapot === "fizetve" ? `<small>jóváírásból</small>` : ""}</td>
        <td><span class="fszallapot all-${x.allapot}">${esc(x.allapot_nev)}</span></td></tr>`).join("");
    const varh = n.varhato.map((v) => `<tr class="fszt-varhato">
        <td class="fszdatum">${v.datum ? `~${rovidNap(v.datum)}` : ""}</td>
        <td class="fszmegn"><span>Várható számla${a.kozos ? ` – ${esc(v.fiok)}` : ""}</span><small>${v.idoszak ? `${nap(v.idoszak[0])} – ${nap(v.idoszak[1])} · ` : ""}még nem érkezett (becslés)</small></td>
        <td></td><td>~${ft(v.osszeg)}</td>
        <td>${v.levonva ? `túlfizetésből<small>${ft(v.levonva)}</small>` : ""}</td>
        <td><span class="fszallapot all-${v.fizetendo ? "nyitott" : "nincs"}">${v.fizetendo ? `fizetendő ~${ft(v.fizetendo)}` : "nincs fizetendő"}</span></td></tr>`).join("");
    el("fsztabla").innerHTML = `
${a.kozos_fiokok?.length ? `<p class="kicsi fszkozos">Az MVM ezt a fiókot közös folyószámlán vezeti: ${a.kozos_fiokok.map(esc).join(", ")}. A számlán a „fizetendő” a közös egyenleg – ezért egy-egy számla fizetendője a másik tarifa jóváírását vagy tartozását is tartalmazhatja (a számla saját értéke alatta).</p>` : ""}
      <div class="kimut fszkimut"><table>
        <thead><tr><th>Kelte</th><th class="fszmegn">Számla</th><th>Határidő</th><th>Számla összege</th><th>Fizetve</th><th>Állapot</th></tr></thead>
        <tbody>${sorok || `<tr><td></td><td class="fszmegn kicsi">Ebben az időszakban nincs számla.</td><td></td><td></td><td></td><td></td></tr>`}${varh}</tbody>
        <tfoot>
          <tr><td></td><th class="fszmegn">Számlázva / fizetve</th><td></td><td>${ft(n.o.szamlazva)}</td><td>${ft(n.o.fizetve)}</td><td></td></tr>
          <tr class="fszzaro"><td></td><th class="fszmegn">Nyitott (fizetendő)${n.o.lejart ? ` <small class="fszelteres">ebből lejárt ${ft(n.o.lejart)}</small>` : ""}</th><td></td><td>${ft(n.o.nyitott)}</td><td></td><td></td></tr>
          ${n.tulfizetes ? `<tr><td></td><th class="fszmegn">Túlfizetés a folyószámlán${n.beszamitas?.levonva ? ` <small>a várható számlából levonva ${ft(n.beszamitas.levonva)}, marad ${ft(n.beszamitas.marad)}</small>` : ""}</th><td></td><td class="minuszft">${ft(-n.tulfizetes)}</td><td></td><td></td></tr>` : ""}
        </tfoot>
      </table></div>`;
    el("fszmegj").innerHTML = `Számla összege: a számla szerinti fizetendő (a szolgáltató beszámításaival együtt – pl. korábbi túlfizetés, támogatás); mínusz: túlfizetés, a következő számlán beszámítják.
      Fizetve: a Részletek → Számlák „Fizetve” jelölése (Díjnet; csoportos beszedésnél a határidő napja); <i>egyenleg szerint</i>: a számlán közölt folyószámla-egyenlegből visszafejtve (DAKÖV) – a fizetés napja a következő számla előtti legkésőbbi lehetséges nap, ha addig a határidő nem volt elég; <i>feltételezett</i>: 90 napnál régebben lejárt számla, amelyről nincs fizetési adat.
      Narancs: várható, még nem érkezett számla – a túlfizetés beszámításával. A könyvelési nézet (követel–tartozik, futó egyenleg) a Kivonat fülön.`;
  }

  _fszAllapot(v) {
    return Math.abs(v) < 0.5 ? "rendezett" : v > 0 ? "fizetendő hátralék" : "túlfizetés (jár vissza / beszámítják)";
  }

  _fszReszlet(t) {
    const r = [];
    if (t.fiok) r.push(esc(t.fiok));
    if (t.idoszak) r.push(`${nap(t.idoszak[0])} – ${nap(t.idoszak[1])}`);
    if (t.mennyiseg) r.push(esc(t.mennyiseg));
    if (t.allasok) r.push(esc(t.allasok));
    if (t.szolgaltato_egyenleg != null)
      r.push(`szolgáltató szerinti egyenleg ${ft(t.szolgaltato_egyenleg)}${t.elteres ? ` <span class="fszelteres">(eltérés ${ft(t.elteres)})</span>
        ${this._admin ? `<button type="button" class="linkgomb" data-fszegyeztet="${esc(`${t.datum}|${t.elteres}|${t.sorszam}`)}">Egyeztetés ›</button>` : ""}` : ""}${t.konyveles
          ? ` <span class="kicsi">(${t.konyveles.irany === "meg_nem_konyvelt" ? `a ${ft(t.konyveles.osszeg)} befizetést a szolgáltató a számla kiállításakor még nem könyvelte le` : `a ${ft(t.konyveles.osszeg)} befizetés a nálunk rögzített napnál korábban érkezett meg`} – nem eltérés)</span>` : ""}`);
    if (t.megjegyzes) r.push(`<i>megjegyzés: ${esc(t.megjegyzes)}</i>`);
    if (t.fajta === "kezi") r.push(`kézi könyvelési tétel${this._admin ? ` <button type="button" class="linkgomb" data-fszkezitorol="${esc(t.id)}">törlés</button>` : ""}`);
    return r.join(" · ");
  }

  _folyoszamlaRajzol() {
    const r = this.shadowRoot, g = this._fsz;
    if (!g) return;
    const el = (id) => r.getElementById(id);
    const a = g.adat;
    el("fszcim").textContent = a ? `Folyószámla – ${a.nev}` : `Folyószámla – ${g.f.nev}`;
    const evek = a ? [...new Set(a.tetelek.map((t) => t.datum.slice(0, 4)))].sort().reverse() : [];
    el("fszidoszak").innerHTML = [["teljes", "Teljes időszak"], ["utolso12", "Utolsó 12 hónap"], ...evek.map((e) => [e, `${e}. év`])]
      .map(([v, n]) => `<option value="${v}"${v === g.idoszak ? " selected" : ""}>${n}</option>`).join("");
    el("fszcsv").disabled = el("fsznyomtat").disabled = !a;
    // MVM közös folyószámla (pl. A1 + H): együtt (a szolgáltató kimutatásával összevethető) vagy tarifánként.
    const kozosE = a && (a.kozos || a.kozos_fiokok?.length);
    el("fszmod").hidden = !kozosE;
    if (kozosE) el("fszmod").innerHTML = [["1", "Közös"], ["0", "Tarifánként"]].map(([v, n]) => {
      const ak = (v === "1") === !!g.egyutt;
      return `<button type="button" role="tab" data-fszegyutt="${v}" class="${ak ? "aktiv" : ""}" aria-selected="${ak}">${n}</button>`;
    }).join("");
    if (g.hiba) { el("fsztabla").innerHTML = `<p class="hiba">${esc(g.hiba)}</p>`; return; }
    if (!a) { el("fsztabla").innerHTML = `<p class="kicsi">Betöltés…</p>`; return; }
    if (!a.tetelek.length) { el("fsztabla").innerHTML = `<p class="kicsi">Ennek a fióknak még nincs számlája.</p>`; return; }
    {
      r.querySelectorAll("#fszdlg [data-fsznezet]").forEach((b) => { const ak = b.dataset.fsznezet === g.nezet; b.classList.toggle("aktiv", ak); b.setAttribute("aria-selected", String(ak)); });
    }
    if (g.nezet !== "kivonat") { this._fszTeljRajzol(); return; }
    const n = this._fszNezet();
    const osszegCella = (v) => (v ? ft(v) : "");
    const egyenlegCella = (v) => `<td class="fszegy${v < -0.5 ? " minuszft" : ""}">${ft(v)}</td>`;
    // Közös (több tarifás) folyószámla: a szolgáltató kimutatásának oszlopai – esedékesség, kiegyenlítés dátuma.
    const mvm = !!a.kozos;
    const tobbOszlop = (t) => (mvm ? `<td class="fszdatum">${t.hatarido ? rovidNap(t.hatarido) : ""}</td>` : "");
    const kiegy = (t) => (mvm ? `<td class="fszdatum">${t.kiegyenlitve ? rovidNap(t.kiegyenlitve) : t.kovetel > 0 ? `<small>nyitott</small>` : ""}</td>` : "");
    const sorok = n.tetelek.map((t) => `<tr class="fsz-${t.fajta}${t.forras === "feltetelezett" ? " fszfelt" : ""}">
        <td class="fszdatum">${rovidNap(t.datum)}</td>
        <td class="fszmegn"><span>${esc(t.megnevezes)}</span>${this._fszReszlet(t) ? `<small>${this._fszReszlet(t)}</small>` : ""}</td>
        ${tobbOszlop(t)}<td>${osszegCella(t.kovetel)}</td><td>${osszegCella(t.tartozik)}</td>${kiegy(t)}${egyenlegCella(t.egyenleg)}</tr>`).join("");
    const ures = mvm ? "<td></td>" : "";
    const kezi = a.nyito.forras === "kézzel megadva";
    el("fsztabla").innerHTML = `
${a.kozos_fiokok?.length ? `<p class="kicsi fszkozos">Az MVM ezt a fiókot közös folyószámlán vezeti: ${a.kozos_fiokok.map(esc).join(", ")}. A számlán a „fizetendő” a közös egyenleg – ezért egy-egy számla fizetendője a másik tarifa jóváírását vagy tartozását is tartalmazhatja (a számla saját értéke alatta). A szolgáltató folyószámla-kimutatásával a „Közös” nézet vethető össze.</p>` : ""}
${mvm ? `<p class="kicsi fszkozos">Közös folyószámla: ${a.fiokok.length} tarifa (${esc(a.nev)}) egy kivonatban, mint a szolgáltató folyószámla-kimutatásán – a tarifa a tétel alatt.</p>` : ""}
      <div class="kimut fszkimut"><table>
        <thead><tr><th>Dátum</th><th class="fszmegn">Megnevezés</th>${mvm ? "<th>Esedékesség</th>" : ""}<th>Követel${mvm ? "<small>terhelés</small>" : ""}</th><th>Tartozik${mvm ? "<small>jóváírás</small>" : ""}</th>${mvm ? "<th>Kiegyenlítve</th>" : ""}<th>Egyenleg</th></tr></thead>
        <tbody>
          <tr class="fsznyito"><td class="fszdatum">${rovidNap(n.nyito.datum)}</td><td class="fszmegn"><span>Nyitó egyenleg</span><small>${esc(n.nyito.forras)}</small></td>${ures}<td></td><td></td>${ures}${egyenlegCella(n.nyito.osszeg)}</tr>
          ${sorok || `<tr><td></td><td class="fszmegn kicsi">Ebben az időszakban nincs tétel.</td>${ures}<td></td><td></td>${ures}<td></td></tr>`}
        </tbody>
        <tfoot>
          <tr><td></td><th class="fszmegn">Forgalom</th>${ures}<td>${ft(n.kov)}</td><td>${ft(n.tart)}</td>${ures}<td></td></tr>
          <tr class="fszzaro"><td></td><th class="fszmegn">Záró egyenleg <small>${this._fszAllapot(n.zaro)}</small></th>${ures}<td></td><td></td>${ures}${egyenlegCella(n.zaro)}</tr>
        </tfoot>
      </table></div>
      ${this._admin ? `<details class="fsznyitoszerk"${kezi ? " open" : ""}><summary>Nyitó egyenleg megadása</summary>
        <p class="kicsi">Ha tudod, mennyi volt a folyószámla egyenlege az első számla előtt (pl. a szolgáltató ügyfélportálján), add meg: pozitív = hátralék, negatív = túlfizetés.${a.kozos ? " A közös folyószámla minden fiókjára vonatkozik." : ""}</p>
        <div class="fsznyitosor gombok"><label>Dátum <input type="date" id="fsznyitodatum" value="${esc(kezi ? a.nyito.datum || "" : a.nyito.datum || "")}"></label>
          <label>Egyenleg (Ft) <input type="text" inputmode="decimal" id="fsznyitoosszeg" value="${kezi ? esc(String(a.nyito.osszeg)) : ""}" placeholder="pl. -6778"></label>
          ${kezi ? `<button type="button" data-fsznyito="torol">Kézi érték törlése</button>` : ""}<button type="button" class="fo" data-fsznyito="ment">Mentés</button></div>
      </details>
      <details class="fsznyitoszerk" id="fszkeziszerk"${g.kezi ? " open" : ""}><summary>Kézi könyvelési tétel (pl. egyeztetés)</summary>
        <p class="kicsi">Ha a kivonat egyenlege eltér a szolgáltatóétól, és az okát nem tudod pótolni (befizetés, számla), egyeztető tétellel igazíthatod – az „Egyeztetés ›” gomb a különbözettel kitölti. A tétel bármikor törölhető.</p>
        <div class="fsznyitosor gombok"><label>Dátum <input type="date" id="fszkezidatum" value="${esc(g.kezi?.datum || "")}"></label>
          <label class="fszszeles">Megnevezés <input type="text" id="fszkezinev" value="${esc(g.kezi?.nev || "")}" placeholder="pl. Egyeztetés a szolgáltató folyószámlájával"></label>
          <label>Összeg (Ft) <input type="text" inputmode="decimal" id="fszkeziosszeg" value="${esc(g.kezi?.osszeg ?? "")}"></label>
          <label>Oszlop <select id="fszkezioldal"><option value="tartozik"${g.kezi?.oldal === "tartozik" ? " selected" : ""}>Tartozik (csökkenti az egyenleget)</option><option value="kovetel"${g.kezi?.oldal === "kovetel" ? " selected" : ""}>Követel (növeli az egyenleget)</option></select></label>
          <button type="button" class="fo" data-fszkezi="ment">Rögzítés</button></div>
      </details>` : ""}`;
    el("fszmegj").innerHTML = `Követel: a számla értéke (elszámolónál a részszámlák levonása után), késedelmi kamat. Tartozik: befizetés, jóváíró számla, kötbér.
      A számlák „túlfizetés”, „támogatás”, „csökkentő tétel” sorai az előző egyenleget hozzák át, ezért nem külön tételek.
      A befizetés napja a Részletek → Számlák „Fizetve” jelölése (Díjnet; csoportos beszedésnél a határidő napja); <i>dőlt</i>: 90 napnál régebbi lejáratú számla, amelyről nincs fizetési adat – kifizetettnek vettük.
      ${a.tetelek.some((t) => t.elteres) ? "Ahol a szolgáltató szerinti egyenleg eltér, ott hiányzó vagy a valóditól eltérő napra jelölt befizetés, kézi számla vagy a számlán nem részletezett tétel lehet az ok." : ""}`;
  }

  _fszSorok() {
    if (this._fsz.nezet !== "kivonat") {
      const n = this._fszTeljNezet(), a = this._fsz.adat;
      const r = (v) => (v == null ? "" : String(Math.round(v)));
      const reszlet = (x) => [a.kozos ? x.fiok : "", x.idoszak ? `${x.idoszak[0]} – ${x.idoszak[1]}` : "", x.mennyiseg, x.allasok].filter(Boolean).join(" · ");
      return { n: { ...n, zaro: n.o.nyitott - (n.tulfizetes || 0) }, a, telj: true,
        sorok: [["Kelte", "Számla", "Részletek", "Határidő", "Számla összege (Ft)", "Fizetve (nap)", "Fizetve (Ft)", "Állapot"],
          ...n.sorok.map((x) => [x.kelte, x.megnevezes, reszlet(x), x.hatarido || "", r(x.fizetendo), x.fizetve?.datum || "", r(x.fizetve?.osszeg), x.allapot_nev]),
          ...n.varhato.map((v) => [v.datum || "", "Várható számla (becslés)" + (a.kozos ? ` – ${v.fiok}` : ""), v.idoszak ? `${v.idoszak[0]} – ${v.idoszak[1]}` : "", "", r(v.osszeg), "", v.levonva ? `túlfizetésből ${Math.round(v.levonva)}` : "", v.fizetendo ? `fizetendő ${Math.round(v.fizetendo)}` : "nincs fizetendő"]),
          ["", "Számlázva / fizetve", "", "", r(n.o.szamlazva), "", r(n.o.fizetve), ""],
          ["", "Nyitott (fizetendő)", n.o.lejart ? `ebből lejárt ${Math.round(n.o.lejart)}` : "", "", r(n.o.nyitott), "", "", ""],
          ...(n.tulfizetes ? [["", "Túlfizetés", "", "", r(-n.tulfizetes), "", "", ""]] : [])] };
    }
    const n = this._fszNezet(), a = this._fsz.adat;
    const hu = (v) => (v ? String(Math.round(v)) : "");
    const reszlet = (t) => [t.fiok, t.idoszak ? `${t.idoszak[0]} – ${t.idoszak[1]}` : "", t.mennyiseg, t.allasok,
      a.kozos && t.hatarido ? `esedékes ${t.hatarido}` : "", a.kozos && t.kiegyenlitve ? `kiegyenlítve ${t.kiegyenlitve}` : "",
      t.szolgaltato_egyenleg != null ? `szolgáltató szerinti egyenleg ${Math.round(t.szolgaltato_egyenleg)}` : ""].filter(Boolean).join(" · ");
    return { n, a, sorok: [["Dátum", "Megnevezés", "Részletek", "Követel (Ft)", "Tartozik (Ft)", "Egyenleg (Ft)"],
      [n.nyito.datum, "Nyitó egyenleg", n.nyito.forras, "", "", String(Math.round(n.nyito.osszeg))],
      ...n.tetelek.map((t) => [t.datum, t.megnevezes, reszlet(t), hu(t.kovetel), hu(t.tartozik), String(Math.round(t.egyenleg))]),
      ["", "Forgalom", "", String(Math.round(n.kov)), String(Math.round(n.tart)), ""],
      ["", "Záró egyenleg", this._fszAllapot(n.zaro), "", "", String(Math.round(n.zaro))]] };
  }

  _fszFajlnev(kit) {
    return `${this._fsz.adat.nev}_folyoszamla`.replace(/[\\/:*?"<>|\s+]+/g, "_") + kit;
  }

  _folyoszamlaCsv() {
    if (!this._fsz?.adat) return;
    const mezo = (x) => (/[;"\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x);
    const szoveg = "﻿" + this._fszSorok().sorok.map((s) => s.map((x) => mezo(String(x ?? ""))).join(";")).join("\r\n") + "\r\n";
    this._letolt(new Blob([szoveg], { type: "text/csv;charset=utf-8" }), this._fszFajlnev(".csv"));
  }

  _folyoszamlaNyomtat() {
    if (!this._fsz?.adat) return;
    if (this._mobil()) return this._folyoszamlaPdf();
    const tabla = this.shadowRoot.querySelector("#fsztabla table");
    if (!tabla) return;
    const n = this._fsz.nezet === "kivonat" ? this._fszNezet() : this._fszTeljNezet();
    const html = `<!doctype html><html lang="hu"><head><meta charset="utf-8"><title>${esc(this._fszFajlnev(""))}</title><style>
      @page { size: A4 portrait; margin: 14mm 12mm; }
      :root { color-scheme: light; } html, body { background: #fff; }
      body { font: 9.5pt Roboto, "Segoe UI", Arial, sans-serif; color: #111; margin: 0; }
      h1 { font-size: 14pt; margin: 0 0 2pt; } .al { color: #555; margin: 0 0 8pt; }
      table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
      th, td { padding: 3pt 5pt; text-align: right; vertical-align: top; border-bottom: 0.5pt solid #ccc; white-space: nowrap; }
      .fszmegn { text-align: left; white-space: normal; width: 55%; } .fszdatum { text-align: left; }
      .fszmegn small { display: block; color: #666; font-size: 7.5pt; } .fszelteres { color: #b00; }
      thead th { border-bottom: 1.5pt solid #444; font-weight: 600; }
      tr.fsznyito td, tr.fszzaro > * { font-weight: 700; } tr.fszfelt td { font-style: italic; color: #555; }
      tfoot td, tfoot th { border-top: 1.5pt solid #444; font-weight: 700; } .minuszft { color: #1b7f3b; }
      .lab { margin-top: 8pt; font-size: 7.5pt; color: #555; }
      * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    </style></head><body>
      <h1>${this._fsz.nezet === "kivonat" ? "Folyószámla" : "Számlák pénzügyi teljesítése"} – ${esc(this._fsz.adat.nev)}</h1>
      <p class="al">Időszak: ${n.cim} · ${this._fsz.nezet === "kivonat" ? `Záró egyenleg: ${ft(n.zaro)} (${this._fszAllapot(n.zaro)})` : `Nyitott: ${ft(this._fszTeljNezet().o.nyitott)}`} · Készült: ${new Date().toLocaleDateString("hu-HU")}</p>
      ${tabla.outerHTML}
      <p class="lab">${this.shadowRoot.getElementById("fszmegj").innerHTML} Rezsikövető – tájékoztató jellegű kimutatás, a szolgáltató folyószámla-kivonatát nem helyettesíti.</p>
    </body></html>`;
    this._nyomtatoKeret?.remove();
    const fr = (this._nyomtatoKeret = document.createElement("iframe"));
    fr.setAttribute("aria-hidden", "true");
    Object.assign(fr.style, { position: "fixed", right: "0", bottom: "0", width: "0", height: "0", border: "0" });
    document.body.appendChild(fr);
    fr.contentDocument.open();
    fr.contentDocument.write(html);
    fr.contentDocument.close();
    setTimeout(() => { fr.contentWindow.focus(); fr.contentWindow.print(); }, 300);
  }

  // Mobilon PDF-fájl: álló A4, a táblázat vászonra rajzolva, oldalanként JPEG-ként.
  async _folyoszamlaPdf() {
    const sv = this._fszSorok(), { n, a } = sv;
    // Teljesítés-nézetnél: kelte, számla, részletek (+ határidő), összeg, fizetve, állapot.
    const sorok = sv.telj ? sv.sorok.map((x, i) => (i === 0 ? x : [x[0], x[1], [x[2], x[3] ? `határidő ${x[3]}` : "", x[5] ? `fizetve ${x[5]}` : ""].filter(Boolean).join(" · "), x[4], x[6], x[7]])) : sv.sorok;
    const fej3 = sv.telj ? ["Összeg", "Fizetve", "Állapot"] : ["Követel", "Tartozik", "Egyenleg"];
    const W = 1240, H = 1754, M = 70, sz = 19, betu = getComputedStyle(this).fontFamily || "Roboto, Arial, sans-serif";
    const oszl = [150, 0, 170, 170, 190];
    oszl[1] = W - 2 * M - oszl.reduce((s, x) => s + x, 0);
    const sorM = Math.round(sz * 2.7), fejM = Math.round(sz * 2);
    const tetel = sorok.slice(1);
    const lapon = Math.floor((H - 2 * M - 170 - fejM) / sorM);
    const lapok = [];
    for (let i = 0; i < tetel.length; i += lapon) lapok.push(tetel.slice(i, i + lapon));
    const kepek = [];
    const fmt = (v) => (v === "" ? "" : `${FT.format(Number(v))} Ft`);
    for (const [li, lap] of lapok.entries()) {
      const cv = Object.assign(document.createElement("canvas"), { width: W, height: H });
      const x = cv.getContext("2d");
      x.fillStyle = "#fff"; x.fillRect(0, 0, W, H); x.textBaseline = "middle";
      let y = M;
      x.fillStyle = "#111"; x.font = `bold ${Math.round(sz * 1.45)}px ${betu}`;
      x.fillText(`${sv.telj ? "Számlák pénzügyi teljesítése" : "Folyószámla"} – ${a.nev}`, M, y + sz * 0.7); y += sz * 2.3;
      x.fillStyle = "#555"; x.font = `${sz}px ${betu}`;
      x.fillText(`Időszak: ${n.cim}${sv.telj ? ` · Nyitott: ${ft(n.o.nyitott)}` : ` · Záró egyenleg: ${ft(n.zaro)} (${this._fszAllapot(n.zaro)})`}${lapok.length > 1 ? ` · ${li + 1}/${lapok.length}. oldal` : ""}`, M, y);
      y += sz * 2;
      const xs = [M]; oszl.forEach((w) => xs.push(xs.at(-1) + w));
      const jobb = (s, xj, yy) => { x.textAlign = "right"; x.fillText(s, xj, yy); x.textAlign = "left"; };
      const vag = (s, w) => { let t = s; while (t && x.measureText(t).width > w) t = t.slice(0, -2); return t === s ? s : `${t}…`; };
      x.fillStyle = "#111"; x.font = `bold ${sz}px ${betu}`;
      ["Dátum", "Megnevezés"].forEach((h, j) => x.fillText(h, xs[j] + 6, y + fejM / 2));
      fej3.forEach((h, j) => jobb(h, xs[j + 3] - 6, y + fejM / 2));
      y += fejM; x.fillStyle = "#444"; x.fillRect(M, y - 2, W - 2 * M, 3);
      lap.forEach((s, i) => {
        const vastag = ["Nyitó egyenleg", "Záró egyenleg", "Forgalom", "Számlázva / fizetve", "Nyitott (fizetendő)", "Túlfizetés"].includes(s[1]);
        if (i % 2) { x.fillStyle = "#f4f4f4"; x.fillRect(M, y, W - 2 * M, sorM); }
        x.fillStyle = "#111"; x.font = `${vastag ? "bold " : ""}${sz}px ${betu}`;
        x.fillText(s[0] ? rovidNap(s[0]) : "", xs[0] + 6, y + sorM * 0.32);
        x.fillText(vag(s[1], oszl[1] - 12), xs[1] + 6, y + sorM * 0.32);
        [3, 4, 5].forEach((k, j) => {
          const v = s[k];
          const penz = !(sv.telj && k === 5) && /^-?\d+$/.test(String(v));
          x.fillStyle = penz && Number(v) < 0 ? "#1b7f3b" : "#111";
          jobb(penz ? fmt(v) : vag(String(v ?? ""), oszl[j + 2] - 8), xs[j + 3] - 6, y + sorM * 0.32);
        });
        if (s[2]) { x.fillStyle = "#666"; x.font = `${Math.round(sz * 0.78)}px ${betu}`; x.fillText(vag(s[2], oszl[1] + oszl[0] - 12), xs[1] + 6, y + sorM * 0.74); }
        y += sorM; x.fillStyle = "#ddd"; x.fillRect(M, y - 1, W - 2 * M, 1);
      });
      x.fillStyle = "#666"; x.font = `${Math.round(sz * 0.72)}px ${betu}`;
      x.fillText("Rezsikövető – tájékoztató jellegű kimutatás, a szolgáltató folyószámla-kivonatát nem helyettesíti.", M, H - M + 10);
      kepek.push(new Uint8Array(await (await new Promise((ok) => cv.toBlob(ok, "image/jpeg", 0.9))).arrayBuffer()));
    }
    this._letolt(this._jpegPdf(kepek, W, H, 595, 842), this._fszFajlnev(".pdf"));
  }

  // Minimális PDF: oldalanként egy JPEG (DCTDecode) a teljes lapon (pw × ph pont).
  _jpegPdf(kepek, W, H, pw, ph) {
    const enc = new TextEncoder(), reszek = [], eltolas = [];
    let hossz = 0;
    const ir = (d) => { const b = typeof d === "string" ? enc.encode(d) : d; reszek.push(b); hossz += b.length; };
    const obj = (n, tartalom) => { eltolas[n] = hossz; ir(`${n} 0 obj\n`); tartalom(); ir("\nendobj\n"); };
    ir("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n");
    const n = kepek.length, lapId = (i) => 3 + i * 3;
    obj(1, () => ir("<< /Type /Catalog /Pages 2 0 R >>"));
    obj(2, () => ir(`<< /Type /Pages /Count ${n} /Kids [${kepek.map((_, i) => `${lapId(i)} 0 R`).join(" ")}] >>`));
    kepek.forEach((jpg, i) => {
      const p = lapId(i), tart = `q ${pw} 0 0 ${ph} 0 0 cm /Im0 Do Q`;
      obj(p, () => ir(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pw} ${ph}] /Resources << /XObject << /Im0 ${p + 2} 0 R >> >> /Contents ${p + 1} 0 R >>`));
      obj(p + 1, () => ir(`<< /Length ${tart.length} >>\nstream\n${tart}\nendstream`));
      obj(p + 2, () => { ir(`<< /Type /XObject /Subtype /Image /Width ${W} /Height ${H} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpg.length} >>\nstream\n`); ir(jpg); ir("\nendstream"); });
    });
    const osszes = 3 + n * 3, xref = hossz;
    ir(`xref\n0 ${osszes}\n0000000000 65535 f \n${Array.from({ length: osszes - 1 }, (_, i) => `${String(eltolas[i + 1]).padStart(10, "0")} 00000 n \n`).join("")}`);
    ir(`trailer\n<< /Size ${osszes} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
    return new Blob(reszek, { type: "application/pdf" });
  }

  _kimutatasNyomtat() {
    if (this._mobil()) return this._kimutatasPdf();
    const g = this._km, tabla = this.shadowRoot.querySelector("#kimuttabla table");
    if (!g?.adat || !tabla) return;
    // A panel árnyék-DOM-ja és sötét témája helyett önálló, világos lap egy rejtett iframe-ben.
    const t = tabla.cloneNode(true);
    t.querySelectorAll("ha-icon").forEach((x) => x.remove());
    t.querySelectorAll(".aktiv").forEach((x) => x.classList.remove("aktiv"));
    const idoszak = g.ev === "utolso12" ? "utolsó 12 hónap" : `${g.ev}. év`;
    const html = `<!doctype html><html lang="hu"><head><meta charset="utf-8"><title>${esc(g.csv.nev.replace(/\s+/g, "_"))}</title><style>
      @page { size: A4 landscape; margin: 12mm; }
      :root { color-scheme: light; } html, body { background: #fff; }
      body { font: 10pt Roboto, "Segoe UI", Arial, sans-serif; color: #111; margin: 0; }
      h1 { font-size: 15pt; margin: 0 0 2pt; } .al { color: #555; margin: 0 0 10pt; }
      table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
      th, td { padding: 3pt 6pt; text-align: right; white-space: nowrap; border-bottom: 0.5pt solid #ccc; }
      th:first-child, td:first-child { text-align: left; }
      thead th { border-bottom: 1.5pt solid #444; vertical-align: bottom; font-weight: 600; }
      thead th span, thead th small { display: block; } thead th small { font-weight: 400; color: #666; font-size: 8pt; }
      tbody th { font-weight: 400; } tbody tr:nth-child(even) > * { background: #f4f4f4; }
      tr.uressor, td.ures { color: #aaa; } .minuszft { color: #1b7f3b; }
      .osszcella { font-weight: 600; border-left: 0.5pt solid #999; }
      tfoot th, tfoot td { font-weight: 700; border-top: 1.5pt solid #444; border-bottom: 0; }
      .kmdb { font-size: 7pt; color: #666; margin-left: 2pt; }
      .kmjel { font-size: 6.5pt; font-weight: 700; border: 0.5pt solid #333; border-radius: 2pt; padding: 0 2pt; margin-left: 3pt; }
      .kmvarh { color: #b35f00; font-style: italic; } tr.kmvarhsor > * { background: #fff3e0 !important; }
      tr.kmvarhsor th { color: #b35f00; font-style: italic; padding-left: 12pt; } tr.kmjovo th { color: #888; }
      .lab { margin-top: 10pt; font-size: 8pt; color: #555; }
      * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    </style></head><body>
      <h1>${esc(g.adat.nev)} – számlák kimutatása</h1>
      <p class="al">Időszak: ${idoszak} · Összeg: fizetendő · Készült: ${new Date().toLocaleDateString("hu-HU")}</p>
      ${t.outerHTML}
      <p class="lab">A hónap a számla kelte szerint; az összeg a fizetendő (elszámolónál a korábbi számlák és a túlfizetés levonása után – mínusz: visszajár), így az összesen a ténylegesen kifizetett összeg. Narancs, „~”: várható, még nem érkezett számla (becslés). E = elszámoló számla, „2×” = több számla a hónapban. Rezsikövető – tájékoztató jellegű kimutatás.</p>
    </body></html>`;
    this._nyomtatoKeret?.remove();
    const f = (this._nyomtatoKeret = document.createElement("iframe"));
    f.setAttribute("aria-hidden", "true");
    Object.assign(f.style, { position: "fixed", right: "0", bottom: "0", width: "0", height: "0", border: "0" });
    document.body.appendChild(f);
    f.contentDocument.open();
    f.contentDocument.write(html);
    f.contentDocument.close();
    setTimeout(() => { f.contentWindow.focus(); f.contentWindow.print(); }, 300);
  }

  async _dElemzesNyit(f, honap) {
    const d = this.shadowRoot.getElementById("ddlg");
    const regi = this._d && this._d.f.sid === f.sid ? this._d : null;
    this._d = { f, adat: regi && !honap ? regi.adat : null, nezet: regi?.nezet || "koltseg", mod: this._dMod || "mvm", nap: honap ? "" : regi?.nap || "", hiba: null };
    if (!d.open) d.showModal();
    this._dRajzol();
    try {
      const v = await this._hass.callWS({ type: "hu_rezsi/d_elemzes", sid: f.sid, ...(honap ? { honap } : {}) });
      if (this._d.f !== f) return;
      this._d.adat = v;
    } catch (e) {
      this._d.hiba = e.message || String(e);
    }
    this._dRajzol();
  }

  _dKezelo() {
    const r = this.shadowRoot;
    const d = r.getElementById("ddlg");
    r.getElementById("dbezar").addEventListener("click", () => d.close());
    d.addEventListener("click", (ev) => ev.target === d && d.close());
    r.querySelectorAll("[data-dnezet]").forEach((b) =>
      b.addEventListener("click", () => {
        this._d.nezet = b.dataset.dnezet;
        this._dRajzol();
      }),
    );
    r.querySelectorAll("[data-dmod]").forEach((b) =>
      b.addEventListener("click", () => {
        this._d.mod = this._dMod = b.dataset.dmod;
        this._dRajzol();
      }),
    );
    r.getElementById("dhavi").addEventListener("click", (ev) => {
      const tr = ev.target.closest("tr[data-honap]");
      if (tr && this._d) this._dElemzesNyit(this._d.f, tr.dataset.honap);
    });
    r.getElementById("dhonap").addEventListener("change", (ev) => this._dElemzesNyit(this._d.f, ev.target.value));
    r.getElementById("dnap").addEventListener("change", (ev) => {
      this._d.nap = ev.target.value;
      this._dRajzol();
    });
    if (this._d && d.open) this._dRajzol();
  }

  _dRajzol() {
    const r = this.shadowRoot;
    const g = this._d;
    const el = (id) => r.getElementById(id);
    if (!g) return;
    el("dcim").textContent = `${g.f.nev} – D tarifa elemzés`;
    r.querySelectorAll("[data-dnezet]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.dnezet === g.nezet)));
    r.querySelectorAll("[data-dmod]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.dmod === g.mod)));
    for (const id of ["dosszeg", "djel", "dmegj", "dhavi"]) el(id).innerHTML = "";
    el("dtip").hidden = true;
    if (g.hiba) { el("dsvg").innerHTML = `<div class="figyszoveg">${esc(g.hiba)}</div>`; return; }
    if (!g.adat) { el("dsvg").innerHTML = `<div class="kicsi grafvar">Számolás…</div>`; return; }
    const a = g.adat;
    const HONAPNEV = ["január", "február", "március", "április", "május", "június", "július", "augusztus", "szeptember", "október", "november", "december"];
    const honapNev = (h) => `${h.slice(0, 4)}. ${HONAPNEV[+h.slice(5, 7) - 1]}`;
    el("dhonap").innerHTML = a.honapok.map((h, i) => `<option value="${h}"${h === a.honap ? " selected" : ""}>${honapNev(h)}${i === 0 ? " (folyó)" : ""}</option>`).join("");
    const napok = [...new Set(a.idok.map((t) => t.slice(0, 10)))];
    if (g.nap && !napok.includes(g.nap)) g.nap = "";
    const most = new Date();
    const ma = `${most.getFullYear()}-${String(most.getMonth() + 1).padStart(2, "0")}-${String(most.getDate()).padStart(2, "0")}`;
    el("dnap").innerHTML = `<option value="">egész hónap</option>` + napok.map((n) =>
      `<option value="${n}"${n === g.nap ? " selected" : ""}>${+n.slice(8)}.${n === ma ? " (ma)" : ""}</option>`).join("");

    // A kiválasztott tartomány
    const idx = a.idok.map((t, i) => i).filter((i) => !g.nap || a.idok[i].startsWith(g.nap));
    // A hónap kerete a hónap elejétől, időrendben fogy: negyedóránként a keret feletti rész (az átlépésben arányosan).
    const p = a.arak, keret = a.keret_ho || 0;
    const fel = [];
    let halm = 0, atlepI = -1;
    a.idok.forEach((t, i) => {
      const q = a.fogyasztas[i];
      if (q == null) { fel.push(0); return; }
      const f = Math.min(q, Math.max(0, halm + q - keret));
      if (f > 0 && atlepI < 0) atlepI = i;
      halm += q;
      fel.push(f);
    });
    // MVM szerint: a hónap keret feletti aránya minden negyedórára egyformán (a keret feletti mennyiség a hónap teljes
    // fogyasztásával súlyozott D-áron); átlépés szerint: az átlépés utáni negyedórák a saját árukon.
    const mvm = g.mod === "mvm";
    let qAll = 0, fAll = 0;
    a.idok.forEach((t, i) => { if (a.fogyasztas[i] != null && a.d_ar[i] != null) { qAll += a.fogyasztas[i]; fAll += fel[i]; } });
    const sMvm = qAll > 0 ? fAll / qAll : 0;
    const resz = (q, f) => (mvm ? q * sMvm : f);
    const a1Ft = (q, f) => ((q - resz(q, f)) * p.kedvezmenyes + resz(q, f) * p.piaci + q * p.rendszerhasznalati) * p.afa;
    const dFt = (q, f, dd) => ((q - resz(q, f)) * p.kedvezmenyes + resz(q, f) * dd + q * p.rendszerhasznalati) * p.afa;
    const sorA = [], sorD = [], sorQ = [];
    let ka = 0, kd = 0, kq = 0, kf = 0, qd = 0;
    const utolsoMert = Math.max(-1, ...idx.filter((i) => a.fogyasztas[i] != null && a.d_ar[i] != null));
    for (const i of idx) {
      const q = a.fogyasztas[i], dd = a.d_ar[i], f = fel[i];
      sorQ.push(q);
      if (q != null && dd != null) { ka += a1Ft(q, f); kd += dFt(q, f, dd); kq += q; kf += resz(q, f); qd += resz(q, f) * dd; }
      if (g.nezet === "ar") {
        sorA.push(p.piaci * p.afa);
        sorD.push(dd == null ? null : dd * p.afa);
        continue;
      }
      if (q == null || dd == null) {
        // Halmozottban a hiányzó negyedóra vízszintesen viszi tovább a vonalat.
        const viszi = g.nezet === "halmozott" && kq && i < utolsoMert;
        sorA.push(viszi ? ka : null);
        sorD.push(viszi ? kd : null);
        continue;
      }
      sorA.push(g.nezet === "halmozott" ? ka : a1Ft(q, f));
      sorD.push(g.nezet === "halmozott" ? kd : dFt(q, f, dd));
    }
    const kul = Math.round(kd - ka);
    const elojel = (x) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${ft(Math.abs(x))}`;
    const tartNev = g.nap ? `${g.nap.slice(0, 4)}. ${HONAPNEV[+g.nap.slice(5, 7) - 1]} ${+g.nap.slice(8)}.` : honapNev(a.honap);
    el("dosszeg").innerHTML = kq > 0
      ? `<div><div class="cimke">A1-gyel · ${esc(tartNev)}</div><div class="nagyobb">${ft(Math.round(ka))}</div></div>
         <div><div class="cimke">D-vel (${mvm ? "MVM szerint" : "átlépés szerint"})</div><div class="nagyobb">${ft(Math.round(kd))}</div></div>
         <div><div class="cimke">Eltérés</div><div class="nagyobb ${kul > 0 ? "figyszoveg" : kul < 0 ? "joszoveg" : ""}">${elojel(kul)}</div>
           <div class="kicsi">${kul > 0 ? "D-vel többe kerülne" : kul < 0 ? "D-vel olcsóbb lenne" : "azonos"}</div></div>
         <div><div class="cimke">Fogyasztás</div><div class="nagyobb masodlagos">${szam(Math.round(kq * 10) / 10, "kWh")}</div>
           <div class="kicsi">${kf > 0 ? `ebből keret felett ${szam(Math.round(kf * 10) / 10, "kWh")} · D-ár rajta${mvm ? " (havi súlyozott)" : ""} ${szam(Math.round((qd / kf) * 100) / 100)} Ft/kWh nettó (A1: ${szam(p.piaci)})` : "mind a kedvezményes kereten belül"}</div></div>
         <div><div class="cimke">Kedvezményes keret · ${esc(honapNev(a.honap))}</div><div class="nagyobb masodlagos">${szam(Math.round(keret), "kWh")}</div>
           <div class="kicsi">${!keret ? "nincs keret" : atlepI >= 0 ? `átlépve: ${+a.idok[atlepI].slice(5, 7)}. ${+a.idok[atlepI].slice(8, 10)}. ${a.idok[atlepI].slice(11)}` : `még hátra ${szam(Math.round((keret - halm) * 10) / 10, "kWh")}`}</div></div>`
      : `<div class="kicsi">${a.van_szenzor ? "Erre az időszakra még nincs fogyasztási adat." : "Nincs fogyasztás-szenzor a fióknál: csak az egységárak vethetők össze (Egységár nézet)."}</div>`;

    // Rajz
    const W = Math.max(300, Math.round(el("dsvg").clientWidth || 640)), H = W < 500 ? 230 : 280;
    const bal = W < 500 ? 46 : 54, jobb = 6, fent = 10, lent = 26;
    const pw = W - bal - jobb, ph = H - fent - lent, y0 = fent + ph, n = idx.length;
    const ertekek = [...sorA, ...sorD].filter((x) => x != null);
    const min = Math.min(0, ...ertekek), max = Math.max(1e-6, ...ertekek);
    const tav = max - min;
    const p10 = 10 ** Math.floor(Math.log10(tav / 4 || 1));
    const nn = tav / 4 / p10;
    const lepes = (nn <= 1 ? 1 : nn <= 2 ? 2 : nn <= 5 ? 5 : 10) * p10;
    const ymin = Math.floor(min / lepes) * lepes, ymax = Math.ceil(max / lepes) * lepes || lepes;
    const X = (k) => bal + (n <= 1 ? 0 : (k / (n - 1)) * pw);
    const Y = (v) => y0 - ((v - ymin) / (ymax - ymin)) * ph;
    const ut = (sor) => {
      let d = "", toll = false;
      sor.forEach((v, k) => {
        if (v == null) { toll = false; return; }
        d += `${toll ? "L" : "M"}${X(k).toFixed(1)},${Y(v).toFixed(1)}`;
        toll = true;
      });
      return d;
    };
    let svg = "";
    for (let t = ymin; t <= ymax + 1e-9; t += lepes) {
      const yy = Y(t);
      svg += `<line class="racs" x1="${bal}" x2="${W - jobb}" y1="${yy}" y2="${yy}"/><text class="tengely" x="${bal - 6}" y="${yy + 4}" text-anchor="end">${t.toLocaleString("hu-HU", { maximumFractionDigits: 2 })}</text>`;
    }
    // Egységár nézetben a fogyasztás halvány oszlopként (arányosan, saját skála nélkül)
    if (g.nezet === "ar") {
      const qmax = Math.max(1e-9, ...sorQ.filter((x) => x != null));
      const bw = Math.max(0.6, pw / Math.max(1, n));
      svg += sorQ.map((q, k) => (q == null || q <= 0 ? "" : `<rect class="dfogy" x="${(X(k) - bw / 2).toFixed(1)}" y="${(y0 - (q / qmax) * ph * 0.35).toFixed(1)}" width="${bw.toFixed(2)}" height="${((q / qmax) * ph * 0.35).toFixed(1)}"/>`)).join("");
    }
    // A hónap kedvezményes keretén belüli szakasz halványan, az átlépés függőleges vonallal.
    if (keret > 0 && n) {
      const kAt = atlepI < 0 ? n : idx.indexOf(atlepI) >= 0 ? idx.indexOf(atlepI) : atlepI < idx[0] ? 0 : n;
      if (kAt > 0) svg += `<rect class="dkeretben" x="${bal}" y="${fent}" width="${Math.max(0, (kAt >= n ? X(n - 1) : X(kAt)) - bal)}" height="${ph}"/>`
        + `<text class="tengely dkeretfelirat" x="${bal + 6}" y="${fent + 14}">kedvezményes keretben</text>`;
      if (kAt < n && atlepI >= idx[0]) svg += `<line class="datlep" x1="${X(kAt)}" x2="${X(kAt)}" y1="${fent}" y2="${y0}"/>`
        + `<text class="tengely datlepfelirat" x="${X(kAt) + 4}" y="${fent + 28}">keret átlépve</text>`;
    }
    if (ymin < 0) svg += `<line class="alap" x1="${bal}" x2="${W - jobb}" y1="${Y(0)}" y2="${Y(0)}"/>`;
    // X tengely: nap nézetben 3 óránként, hónapban néhány naponként
    idx.forEach((i, k) => {
      const t = a.idok[i];
      const ora = +t.slice(11, 13), perc = +t.slice(14, 16), nap_ = +t.slice(8, 10);
      const napkoz = napok.length <= 10 ? 1 : W < 500 ? 7 : 5;
      const jel = g.nap ? perc === 0 && ora % 3 === 0 : ora === 0 && perc === 0 && (nap_ === 1 || nap_ % napkoz === 0);
      if (jel) {
        svg += `<line class="racs fugg" x1="${X(k)}" x2="${X(k)}" y1="${fent}" y2="${y0}"/><text class="tengely" x="${X(k)}" y="${H - 8}" text-anchor="middle">${g.nap ? `${ora}:00` : `${nap_}.`}</text>`;
      }
    });
    svg += `<line class="alap" x1="${bal}" x2="${W - jobb}" y1="${y0}" y2="${y0}"/>`;
    svg += `<path class="dvonal a1" d="${ut(sorA)}"/><path class="dvonal d" d="${ut(sorD)}"/>`;
    svg += `<line id="dkurzor" class="dkurzor" x1="0" x2="0" y1="${fent}" y2="${y0}" visibility="hidden"/>`;
    const egys = g.nezet === "ar" ? "Ft/kWh" : "Ft";
    el("dsvg").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="A1 és D ${g.nezet === "ar" ? "egységár" : "költség"} negyedóránként, ${esc(tartNev)}">${svg}</svg>`;

    // Tooltip
    const tip = el("dtip"), doboz = r.querySelector("#ddlg .grafdoboz");
    const svgEl = el("dsvg").querySelector("svg"), kurzor = svgEl.querySelector("#dkurzor");
    const fmt = (v, e) => (v == null ? "–" : `${v.toLocaleString("hu-HU", { maximumFractionDigits: e === "Ft" && g.nezet === "halmozott" ? 0 : 2 })} ${e}`);
    const mutat = (ev) => {
      if (!n) return;
      const rb = svgEl.getBoundingClientRect();
      const x = ((ev.clientX - rb.left) / rb.width) * W;
      const k = Math.min(n - 1, Math.max(0, Math.round(((x - bal) / pw) * (n - 1))));
      const i = idx[k], t = a.idok[i];
      kurzor.setAttribute("x1", X(k)); kurzor.setAttribute("x2", X(k)); kurzor.setAttribute("visibility", "visible");
      const veg = new Date(`${t}:00`); veg.setMinutes(veg.getMinutes() + 15);
      const q = a.fogyasztas[i];
      tip.innerHTML = `<div class="tcim">${+t.slice(5, 7)}. ${+t.slice(8, 10)}. ${t.slice(11)}–${String(veg.getHours()).padStart(2, "0")}:${String(veg.getMinutes()).padStart(2, "0")}</div>
        <div><span class="tjel a1"></span>A1: <b>${fmt(sorA[k], egys)}</b></div>
        <div><span class="tjel d"></span>D: <b>${fmt(sorD[k], egys)}</b></div>
        <div class="kicsi">fogyasztás ${q == null ? "–" : `${(q * 1000).toLocaleString("hu-HU", { maximumFractionDigits: 0 })} Wh${fel[i] > 0 ? fel[i] < q - 1e-9 ? ` (ebből ${(fel[i] * 1000).toLocaleString("hu-HU", { maximumFractionDigits: 0 })} Wh keret felett)` : " · keret felett" : " · kereten belül"}`} · D-ár ${a.d_ar[i] == null ? "–" : `${szam(a.d_ar[i])} Ft/kWh nettó`}</div>`;
      tip.hidden = false;
      const db = doboz.getBoundingClientRect();
      const px = (X(k) / W) * rb.width + (rb.left - db.left);
      tip.style.left = `${Math.min(Math.max(px - tip.offsetWidth / 2, 0), db.width - tip.offsetWidth)}px`;
    };
    svgEl.addEventListener("pointermove", mutat);
    svgEl.addEventListener("pointerdown", mutat);
    svgEl.addEventListener("pointerleave", (e) => {
      if (e.pointerType !== "mouse") return;
      tip.hidden = true;
      kurzor.setAttribute("visibility", "hidden");
    });

    el("djel").innerHTML = `<span><span class="tjel a1"></span>A1</span><span><span class="tjel d"></span>D (dinamikus)</span>`
      + (g.nezet === "ar" ? `<span><span class="tjel dfogyjel"></span>fogyasztás (arányos)</span>` : "")
      + `<span class="kicsi">${g.nezet === "ar" ? "keret feletti energiadíj, bruttó Ft/kWh" : g.nezet === "halmozott" ? "halmozott költség a tartomány elejétől, bruttó Ft" : "negyedórás költség, bruttó Ft"}</span>`;

    // Megjegyzések
    const megj = [];
    if (g.nezet !== "ar") {
      megj.push(keret > 0
        ? `A hónap kedvezményes kerete ${szam(Math.round(keret), "kWh")} (napi 6,91 kWh × a hónap napjai), a hónap elejétől fogy. Amíg tart, mindkét árszabáson a kedvezményes ár (${szam(p.kedvezmenyes)} Ft/kWh nettó) jár; felette az A1 piaci ára (${szam(p.piaci)}), ill. a D ára. `
          + (mvm
            ? sMvm === 0 ? "<b>MVM szerint</b> és átlépés szerint ugyanaz, amíg a hónap a kereten belül marad." : `<b>MVM szerint:</b> a keret feletti mennyiséget a D-számla a hónap <i>összes</i> negyedórás fogyasztásával súlyozott áron (${szam(a.osszeg.d_atlag)} Ft/kWh nettó) számlázza – a grafikonon ezért a keret feletti arány (${szam(Math.round(sMvm * 1000) / 10)}%) minden negyedórára egyformán jut.`
            : "<b>Átlépés szerint:</b> az átlépés negyedórájától az adott negyedórák D-árával – a két vonal az átlépésig együtt fut. A valódi D-számla az MVM szerinti.")
        : "A fióknál nincs kedvezményes keret: minden negyedóra a piaci, ill. a D-áron.");
      const o_ = a.osszeg;
      if (!mvm && !g.nap && o_.d_szamla != null && o_.keret_felett > 0) megj.push(`MVM szerint (ahogy a D-számla számol) ebben a hónapban D-vel ${ft(o_.d_szamla)} lenne (A1-hez képest ${elojel(o_.d_szamla - o_.a1)}).`);
      megj.push(`A költségben a rendszerhasználati díj (${szam(p.rendszerhasznalati)} Ft/kWh) is benne van, az alapdíj (mindkettőn azonos) nincs.`);
    }
    const fo = a.ar_forras || {};
    megj.push(`D-árak: ${a.mvm_ig ? `${nap(a.mvm_ig)}-ig az MVM közzétett negyedórás árlistája` : "MVM árlista"}`
      + (a.szamitott_ig ? `, utána ${nap(a.szamitott_ig.slice(0, 10))} ${a.szamitott_ig.slice(11)}-ig a HUPX másnapi árából számolva (HUPX × MNB EUR-árfolyam + ${szam(a.kereskedoi_dij)} Ft/kWh kereskedői díj – az MVM képletével, fillérre egyezik)` : "")
      + (fo.ora ? `; ${fo.ora} negyedórára csak órás átlagár ismert` : "") + ".");
    if (a.igazitas && Math.abs(a.igazitas - 1) > 0.01) megj.push(`A negyedórás fogyasztás a szenzor alakját követi, de a havi mennyiség a mérőleolvasásokhoz igazított elszámolásé (a szenzor értéke ×${a.igazitas.toLocaleString("hu-HU", { maximumFractionDigits: 3 })}).`);
    if (a.adat_ig) megj.push(`<span class="figyszoveg">A hónap csak ${nap(a.adat_ig)}-ig ismert</span> (az utolsó mérőállás) – rögzíts új mérőállást a teljes hónaphoz.`);
    if (a.egyenletes) megj.push(`<span class="figyszoveg">Nincs mérőszenzor:</span> a havi fogyasztás a mérőállásokból (két leolvasás között napokra arányosítva), a hónapon belül egyenletesen elosztva – a napszaki alakod ismeretlen, ezért a D-ár itt a hónap egyszerű átlaga. A pontos összevetéshez fogyasztás-szenzor (pl. Shelly) kell a fiókhoz.`);
    if (a.orabol) megj.push(`${a.orabol} negyedóra fogyasztása az órás statisztikából, egyenletesen elosztva (a negyedórás adat gyűjtése a funkció bekapcsolásától halmozódik).`);
    if (a.szaldo_napelem) megj.push(`<span class="figyszoveg">Szaldós napelemmel a D nem választható (bruttó elszámolásra kellene váltani).</span>`);
    megj.push("A D legkorábban 2027. január 1-jétől, távlehívható (okos) mérővel kérhető.");
    // Havi kimutatás: a folyó és az előző 12 naptári hónap a választott számítással; sorra koppintva az a hónap.
    const havi = a.havi || [];
    if (havi.length) {
      const dk = (x) => (mvm ? x.d_mvm : x.d_sajat);
      const lezart = havi.filter((x) => !x.folyo && !x.adat_ig && x.kwh > 0 && dk(x) != null).slice(0, 12);
      const sA = lezart.reduce((t, x) => t + x.a1, 0), sD = lezart.reduce((t, x) => t + dk(x), 0);
      const atl = (x) => (x.atlepes ? `${+x.atlepes.slice(8, 10)}. ${x.atlepes.slice(11)}` : x.kwh > 0 ? "–" : "");
      const kul = (v) => `<span class="${v > 0 ? "figyszoveg" : v < 0 ? "joszoveg" : ""}">${elojel(v)}</span>`;
      el("dhavi").innerHTML = `<div class="cimke">Havi kimutatás · ${mvm ? "MVM szerint" : "átlépés szerint"}</div>
        <div class="tablagorgeto"><table><thead><tr><th>Hónap</th><th>Fogyasztás</th><th class="szeles">Keret felett</th><th class="szeles">Átlépés</th><th>A1</th><th>D</th><th>Eltérés</th></tr></thead><tbody>${havi
          .map((x) => `<tr data-honap="${x.honap}" class="${x.honap === a.honap ? "aktiv" : ""}"><td>${x.honap.slice(0, 4)}. ${HONAP[+x.honap.slice(5, 7) - 1]}${x.folyo ? " *" : ""}${x.egyenletes ? " ≈" : ""}${x.adat_ig ? " ‡" : ""}</td>
            <td>${x.kwh > 0 ? szam(Math.round(x.kwh), "kWh") : "–"}</td><td class="szeles">${x.kwh > 0 ? szam(Math.round(x.keret_felett), "kWh") : "–"}</td><td class="szeles">${atl(x)}</td>
            <td>${x.kwh > 0 ? ft(x.a1) : "–"}</td><td>${x.kwh > 0 && dk(x) != null ? ft(dk(x)) : "–"}</td><td>${x.kwh > 0 && dk(x) != null ? kul(dk(x) - x.a1) : ""}</td></tr>`)
          .join("")}</tbody>${lezart.length ? `<tfoot><tr><td>${lezart.length} hónap</td><td>${szam(Math.round(lezart.reduce((t, x) => t + x.kwh, 0)), "kWh")}</td><td class="szeles">${szam(Math.round(lezart.reduce((t, x) => t + x.keret_felett, 0)), "kWh")}</td><td class="szeles"></td><td>${ft(sA)}</td><td>${ft(sD)}</td><td>${kul(sD - sA)}</td></tr></tfoot>` : ""}</table></div>
        <div class="kicsi">* folyó hónap (eddig).${havi.some((x) => x.egyenletes) ? " ≈ mérőállásokból, egyenletes elosztással." : ""}${havi.find((x) => x.adat_ig) ? ` ‡ csak az utolsó mérőállásig (${nap(havi.find((x) => x.adat_ig).adat_ig)}) ismert, az összesenbe nem számít – rögzíts új mérőállást.` : ""} Az összesen a ${lezart.length} lezárt hónapé. Sorra koppintva az a hónap nyílik meg.${havi.some((x) => x.orabol) ? " A régebbi hónapok negyedórás fogyasztása az órás adatból, egyenletesen elosztva." : ""}</div>`;
    }
    el("dmegj").innerHTML = megj.map((x) => `<div>${x}</div>`).join("");
  }

  _grafKezelo() {
    const r = this.shadowRoot;
    const d = r.getElementById("grafdlg");
    r.getElementById("grafbezar").addEventListener("click", () => d.close());
    d.addEventListener("click", (ev) => ev.target === d && d.close());
    r.querySelectorAll("[data-mertek]").forEach((b) =>
      b.addEventListener("click", () => {
        this._graf.mertek = b.dataset.mertek;
        this._grafRajzol();
      }),
    );
    r.getElementById("grafev").addEventListener("change", (ev) => {
      this._graf.ev = +ev.target.value;
      this._grafRajzol();
    });
    if (this._graf && d.open) this._grafRajzol(); // újrarajzolt panel nyitott ablakkal
  }

  _grafRajzol() {
    const r = this.shadowRoot;
    const g = this._graf;
    const el = (id) => r.getElementById(id);
    if (!g) return;
    el("grafcim").textContent = `${g.f.nev} – éves összevetés`;
    r.querySelectorAll("[data-mertek]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mertek === g.mertek)));
    for (const id of ["grafosszeg", "grafjel", "graftabla", "grafmegj", "grafvs", "grafnapelem"]) el(id).innerHTML = "";
    // Napelemes fiók: vételezés (1.8.0), betáplálás (2.8.0), nettó – külön mértékként.
    const napelemes = !!g.adat?.napelem;
    r.querySelectorAll(".napelemgomb").forEach((b) => { b.hidden = !napelemes; });
    el("grafmfogy").textContent = napelemes ? "Vételezés" : "Fogyasztás";
    if (!napelemes && ["betaplalas", "netto"].includes(g.mertek)) g.mertek = "mennyiseg";
    r.querySelectorAll("[data-mertek]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mertek === g.mertek)));
    el("graftip").hidden = true;
    if (g.hiba) { el("grafsvg").innerHTML = `<div class="figyszoveg">${esc(g.hiba)}</div>`; return; }
    if (!g.adat) { el("grafsvg").innerHTML = `<div class="kicsi grafvar">Számolás…</div>`; return; }
    el("grafev").innerHTML = (g.evek || []).map((y) => `<option value="${y}"${y === g.ev ? " selected" : ""}>${y}</option>`).join("");
    const ev = g.ev, elozo = ev - 1, m = g.mertek;
    el("grafvs").textContent = `összevetve: ${elozo}`;
    const egysAlap = { m3: "m³" }[g.adat.egyseg] || g.adat.egyseg || "";
    const egys = m === "ft" ? "Ft" : egysAlap;
    const idx = Object.fromEntries(g.adat.honapok.map((h) => [h.honap, h]));
    const k = (y, i) => `${y}-${String(i + 1).padStart(2, "0")}`;
    const ert = (h) => (h && h[m] != null ? h[m] : null);
    const sorok = HONAP.map((nev, i) => ({ i, nev, a: idx[k(ev, i)], b: idx[k(elozo, i)] }));
    const fmt = (v) => (v == null ? "–" : m === "ft" ? ft(v) : szam(v, egys));
    // Nettónál (lehet mínusz) a százalék csak pozitív alapnál értelmes.
    const szazalek = (a, b) => (a == null || b == null || !b || (m === "netto" && (a < 0 || b <= 0)) ? null : (a / b - 1) * 100);
    const szazSzoveg = (p) => (p == null ? "" : `${p >= 0 ? "▲ +" : "▼ −"}${Math.abs(p).toLocaleString("hu-HU", { maximumFractionDigits: 1 })}%`);

    // Tengely
    const ertekek = sorok.flatMap((s) => [ert(s.a), ert(s.b)]).filter((x) => x != null);
    const max = Math.max(1, ...ertekek), min = Math.min(0, ...ertekek);  // nettó: mínusz is lehet (nyári többlet)
    const p10 = 10 ** Math.floor(Math.log10((max - min) / 4));
    const n = (max - min) / 4 / p10;
    const lepes = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p10;
    const ymax = Math.ceil(max / lepes) * lepes, ymin = Math.floor(min / lepes) * lepes;
    const W = Math.max(300, Math.round(el("grafsvg").clientWidth || 640)), H = W < 500 ? 220 : 260;
    const bal = W < 500 ? 44 : 52, jobb = 4, fent = 10, lent = 26;
    const pw = W - bal - jobb, ph = H - fent - lent, gw = pw / 12;
    const bw = Math.min(18, (gw - 10) / 2);
    const yk = (v) => fent + ((ymax - v) / (ymax - ymin)) * ph;
    const y0 = yk(0);
    const rud = (x, v, cls) => {
      if (v == null || v === 0) return "";
      if (v < 0) {  // lefelé: a kerekítés alul
        const y1 = yk(v), h = y1 - y0, rr = Math.min(4, h, bw / 2);
        return `<path class="${cls} negativ" d="M${x},${y0}V${y1 - rr}Q${x},${y1} ${x + rr},${y1}H${x + bw - rr}Q${x + bw},${y1} ${x + bw},${y1 - rr}V${y0}Z"/>`;
      }
      const y1 = yk(v), h = y0 - y1, rr = Math.min(4, h, bw / 2);
      return `<path class="${cls}" d="M${x},${y0}V${y1 + rr}Q${x},${y1} ${x + rr},${y1}H${x + bw - rr}Q${x + bw},${y1} ${x + bw},${y1 + rr}V${y0}Z"/>`;
    };
    let svg = "";
    for (let t = ymin; t <= ymax + 1e-9; t += lepes) {
      const yy = yk(t);
      svg += `<line class="racs" x1="${bal}" x2="${W - jobb}" y1="${yy}" y2="${yy}"/><text class="tengely" x="${bal - 6}" y="${yy + 4}" text-anchor="end">${t.toLocaleString("hu-HU", { maximumFractionDigits: 1 })}</text>`;
    }
    for (const s of sorok) {
      const gx = bal + s.i * gw, x0 = gx + (gw - 2 * bw - 2) / 2;
      const osztaly = (h, alap) => `${alap}${h?.profil ? " profil" : h?.becsult ? " becsult" : ""}${h?.reszleges ? " reszleges" : ""}`;
      svg += `<rect class="hover" data-i="${s.i}" x="${gx}" y="${fent}" width="${gw}" height="${ph}"/>`;
      svg += rud(x0, ert(s.b), osztaly(s.b, "rud elozo"));
      svg += rud(x0 + bw + 2, ert(s.a), osztaly(s.a, "rud idei"));
      svg += `<text class="tengely" x="${gx + gw / 2}" y="${H - 8}" text-anchor="middle">${gw < 40 ? ["j", "f", "m", "á", "m", "j", "j", "a", "sz", "o", "n", "d"][s.i] : s.nev.replace(".", "")}</text>`;
    }
    svg += `<line class="alap" x1="${bal}" x2="${W - jobb}" y1="${y0}" y2="${y0}"/>`;
    const minta = (id, osztaly) => `<pattern id="${id}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect class="${osztaly} mintaalap" width="6" height="6"/><rect class="${osztaly}" width="3" height="6"/></pattern>`;
    svg = `<defs>${minta("csik-idei", "rud idei")}${minta("csik-elozo", "rud elozo")}</defs>` + svg;
    el("grafsvg").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Havi ${m === "ft" ? "költség" : "fogyasztás"}: ${ev} és ${elozo}">${svg}</svg>`;

    // Tooltip (egér és érintés)
    const tip = el("graftip"), doboz = r.querySelector(".grafdoboz");
    const svgEl = el("grafsvg").querySelector("svg");
    const mutat = (ev2) => {
      const t = ev2.target.closest("rect.hover");
      if (!t) return;
      svgEl.querySelectorAll("rect.hover.aktiv").forEach((x) => x !== t && x.classList.remove("aktiv"));
      t.classList.add("aktiv");
      const s = sorok[+t.dataset.i];
      const sor = (y, h) => `<div><span class="tjel ${y === ev ? "idei" : "elozo"}"></span>${y}: <b>${fmt(ert(h))}</b>${h?.profil ? " · elosztva a kazánbecslés szerint" : h?.becsult ? " · becsült" : ""}${h?.reszleges ? " · folyamatban" : ""}</div>`;
      const p = szazalek(ert(s.a), ert(s.b));
      const kwh = (v) => (v == null ? "–" : szam(v, egysAlap));
      const nap1 = (y, h) => (napelemes && h ? `<div class="kicsi">${y}: vételezés ${kwh(h.mennyiseg)} · betáplálás ${kwh(h.betaplalas)} · nettó ${kwh(h.netto)}</div>` : "");
      tip.innerHTML = `<div class="tcim">${HONAP[s.i]}</div>${sor(ev, s.a)}${sor(elozo, s.b)}${p != null ? `<div class="kicsi">${szazSzoveg(p)}</div>` : ""}${nap1(ev, s.a)}${nap1(elozo, s.b)}`;
      tip.hidden = false;
      const db = doboz.getBoundingClientRect(), tb = t.getBoundingClientRect();
      const x = tb.left - db.left + tb.width / 2;
      tip.style.left = `${Math.min(Math.max(x - tip.offsetWidth / 2, 0), db.width - tip.offsetWidth)}px`;
    };
    svgEl.addEventListener("pointerover", mutat);
    svgEl.addEventListener("pointerdown", mutat);
    svgEl.addEventListener("pointerleave", (e) => {
      if (e.pointerType !== "mouse") return;
      tip.hidden = true;
      svgEl.querySelectorAll("rect.hover.aktiv").forEach((x) => x.classList.remove("aktiv"));
    });

    // Összesítés: csak a mindkét évben meglévő, lezárt hónapok
    const ossz = sorok.filter((s) => ert(s.a) != null && ert(s.b) != null && !s.a.reszleges);
    const sa = ossz.reduce((x, s) => x + ert(s.a), 0), sb = ossz.reduce((x, s) => x + ert(s.b), 0);
    const elozoTeljes = sorok.every((s) => ert(s.b) != null && !s.b.reszleges) ? sorok.reduce((x, s) => x + ert(s.b), 0) : null;
    const tart = ossz.length ? `${HONAP[ossz[0].i]}–${HONAP[ossz[ossz.length - 1].i]}` : "";
    el("grafosszeg").innerHTML = ossz.length
      ? `<div><div class="cimke">${ev} · ${tart}</div><div class="nagyobb">${fmt(sa)}</div></div>
         <div><div class="cimke">${elozo} · ugyanezek a hónapok</div><div class="nagyobb masodlagos">${fmt(sb)}</div></div>
         <div><div class="cimke">Eltérés</div><div class="nagyobb">${szazSzoveg(szazalek(sa, sb)) || "–"}</div><div class="kicsi">${ossz.length} hónap${ossz.length < sorok.filter((s) => ert(s.a) != null).length ? ", a folyamatban lévő nélkül" : ""}</div></div>
         ${ossz.some((s) => s.a.profil || s.b.profil) ? `<div class="kicsi grafbecs">${ossz.filter((s) => s.a.profil || s.b.profil).length} hónap a leolvasások közti fogyasztásból, a profil-szenzor (pl. kazánbecslés) alakja szerint elosztva – a havi érték közelítő, az éves összeg pontos.</div>` : ""}
         ${ossz.some((s) => (s.a.becsult && !s.a.profil) || (s.b.becsult && !s.b.profil)) ? `<div class="kicsi figyszoveg grafbecs">${ossz.filter((s) => (s.a.becsult && !s.a.profil) || (s.b.becsult && !s.b.profil)).length} hónap becsült (ritka leolvasás, egyenletes elosztás) – a havi eltérés pontatlan lehet${ossz.some((s) => s.a.becsult !== s.b.becsult) ? ", főleg ahol az egyik év mért, a másik becsült" : ""}.</div>` : ""}
         ${elozoTeljes != null ? `<div><div class="cimke">${elozo} egész év</div><div class="nagyobb masodlagos">${fmt(elozoTeljes)}</div></div>` : ""}`
      : `<div class="kicsi">Nincs mindkét évben adat ugyanarra a hónapra.</div>`;

    el("grafjel").innerHTML = `<span><span class="tjel elozo"></span>${elozo}</span><span><span class="tjel idei"></span>${ev}</span>
      <span class="kicsi">csíkozott: becsült (leolvasások közt egyenletesen elosztva) · halványabb: a profil-szenzor (kazánbecslés) szerint elosztva · szaggatott: folyamatban lévő hónap</span>`;
    el("graftabla").innerHTML = `<table><thead><tr><th>Hónap</th><th>${elozo}</th><th>${ev}</th><th>Eltérés</th></tr></thead><tbody>${sorok
      .map((s) => `<tr><td>${HONAP[s.i]}</td><td>${fmt(ert(s.b))}${s.b?.profil ? "†" : s.b?.becsult ? "*" : ""}</td><td>${fmt(ert(s.a))}${s.a?.profil ? "†" : s.a?.becsult ? "*" : ""}${s.a?.reszleges ? " (folyamatban)" : ""}</td><td>${szazSzoveg(szazalek(ert(s.a), ert(s.b)))}</td></tr>`)
      .join("")}</tbody></table><div class="kicsi">* becsült (egyenletes elosztás) · † a profil-szenzor szerint elosztva</div>`;
    // Napelem: havonta egymás mellett a tavalyi és az idei vételezés (1.8.0), betáplálás (2.8.0) és nettó.
    if (napelemes) {
      const kwh = (v) => (v == null ? "–" : szam(v, egysAlap));
      // Eltérés a tavalyihoz – a folyamatban lévő hónapnál nem (néhány nap a teljes tavalyi hónaphoz képest félrevezető).
      const d = (a, b, resz) => (a == null || b == null || resz ? "" : `<div class="kicsi">${a - b >= 0 ? "+" : "−"}${szam(Math.abs(a - b), egysAlap)}</div>`);
      el("grafnapelem").innerHTML = `<h4>Vételezés és betáplálás – ${elozo} és ${ev}</h4><div class="tablagorgeto"><table class="napelemtabla"><thead>
        <tr><th rowspan="2">Hónap</th><th colspan="2">Vételezés (1.8.0)</th><th colspan="2">Betáplálás (2.8.0)</th><th colspan="2">Nettó</th></tr>
        <tr><th>${elozo}</th><th>${ev}</th><th>${elozo}</th><th>${ev}</th><th>${elozo}</th><th>${ev}</th></tr></thead><tbody>${sorok
        .filter((s) => s.a || s.b)
        .map((s) => `<tr><td>${HONAP[s.i]}</td><td>${kwh(s.b?.mennyiseg)}</td><td>${kwh(s.a?.mennyiseg)}${d(s.a?.mennyiseg, s.b?.mennyiseg, s.a?.reszleges)}</td>
          <td>${kwh(s.b?.betaplalas)}</td><td>${kwh(s.a?.betaplalas)}${d(s.a?.betaplalas, s.b?.betaplalas, s.a?.reszleges)}</td>
          <td class="${(s.b?.netto ?? 0) < 0 ? "tobblet" : ""}">${kwh(s.b?.netto)}</td><td class="${(s.a?.netto ?? 0) < 0 ? "tobblet" : ""}">${kwh(s.a?.netto)}${d(s.a?.netto, s.b?.netto, s.a?.reszleges)}${s.a?.reszleges ? " (folyamatban)" : ""}</td></tr>`)
        .join("")}</tbody></table></div>
        <div class="kicsi">Nettó = vételezés − betáplálás; mínusz (zöld): abban a hónapban több ment a hálózatba, mint amennyit vételeztél. ${g.adat.napelem === "szaldo" ? "Szaldónál az elszámolás évente, a nettó éves összegén megy (a havi mínusz a téli vételezést csökkenti)." : "Bruttó elszámolásnál a vételezést és a betáplálást külön számolják el."}</div>`;
    }
    el("grafmegj").textContent = m === "ft"
      ? `Költség: a Rezsikövető díjszámítása naptári hónapokra bontva (alapdíj és kedvezményes keret havonta). Tájékoztató jellegű: a számlák időszakai nem naptári hónapok.${napelemes ? " Napelemnél ez a havi vételezés díja – az elszámolás a betáplálással együtt történik." : ""}`
      : m === "betaplalas" ? "Betáplálás: a 2.8.0 regiszter havi növekménye a leolvasásokból (és a betáplálás-szenzorból, ha van); két leolvasás között napokra arányosítva."
      : m === "netto" ? "Nettó: vételezés − betáplálás havonta; a nulla alatti oszlop a hálózatba adott többlet."
      : "Fogyasztás: a mérő szenzora a leolvasásokhoz igazítva; ahol nincs szenzoradat, két leolvasás között napokra arányosítva.";
  }

  _beallitasNyit(f) {
    const d = this.shadowRoot.getElementById("beallit");
    this.shadowRoot.getElementById("beallitcim").textContent = `${f.nev} – entitások`;
    const allapot = (id) => {
      const st = this._hass.states[id];
      if (!st) return "–";
      if (st.state === "unknown" && st.attributes.elso_lezaras) return `első: ${nap(st.attributes.elso_lezaras)}`;
      if (st.state === "unavailable" || st.state === "unknown") return "nincs adat";
      let szoveg;
      try {
        szoveg = this._hass.formatEntityState ? this._hass.formatEntityState(st) : null;
      } catch (e) {
        szoveg = null;
      }
      szoveg = szoveg || (st.attributes.unit_of_measurement ? `${st.state} ${st.attributes.unit_of_measurement}` : st.state);
      return esc(szoveg.replace(/\s?HUF\b/, " Ft"));
    };
    const nev = (e) => {
      const st = this._hass.states[e.entity_id];
      const teljes = e.name || st?.attributes.friendly_name || e.entity_id;
      return teljes.startsWith(f.nev + " ") ? teljes.slice(f.nev.length + 1) : teljes;
    };
    const lista = this._entitasok(f);
    this.shadowRoot.getElementById("entlista").innerHTML = lista.length
      ? lista.map((e) => `<button class="entsor" data-ent="${esc(e.entity_id)}">
          <ha-state-icon data-ikon="${esc(e.entity_id)}"></ha-state-icon>
          <span class="entnev">${esc(nev(e))}<span class="kicsi">${esc(e.entity_id)}${e.hidden ? " · rejtett" : ""}</span></span>
          <span class="entertek">${allapot(e.entity_id)}</span></button>`).join("")
      : `<div class="kicsi">Nincs entitás.</div>`;
    this.shadowRoot.querySelectorAll("#entlista [data-ikon]").forEach((el) => {
      el.hass = this._hass;
      el.stateObj = this._hass.states[el.dataset.ikon];
    });
    this.shadowRoot.querySelectorAll("#entlista [data-ent]").forEach((el) =>
      el.addEventListener("click", () => {
        d.close();
        this._tobbInfo(el.dataset.ent, "settings");
      }),
    );
    // Az eszközoldal (/config/devices) csak rendszergazdának érhető el.
    this.shadowRoot.getElementById("eszkozoldal").hidden = !this._admin;
    this.shadowRoot.getElementById("eszkozoldal").onclick = () => {
      d.close();
      this._navigal(`/config/devices/device/${f.device_id}`);
    };
    d.showModal();
  }

  // „Saját díjak” (2.2.0b6): a fiók díjai bruttóban, felülírásként mentve (víz: ivóvíz, csatorna, alapdíj; fix díjas: havidíj)
  async _sajatDijNyit(f) {
    if (!f) return;
    const r = this.shadowRoot, d = r.getElementById("dijablak"), form = r.getElementById("dijform"), hiba = r.getElementById("dijhiba");
    r.getElementById("dijcim").textContent = `Saját díjak – ${f.nev}`;
    hiba.textContent = "";
    r.getElementById("dijmezok").innerHTML = `<div class="kicsi">Betöltés…</div>`;
    form.tol.value = new Date().toISOString().slice(0, 7) + "-01";
    if (!d.open) d.showModal();
    let adat;
    try { adat = await this._hass.callWS({ type: "hu_rezsi/sajat_dijak", entry_id: this._entryId(f.sid), sid: f.sid }); }
    catch (err) { r.getElementById("dijmezok").innerHTML = ""; hiba.textContent = err.message || String(err); return; }
    r.getElementById("dijmezok").innerHTML = adat.mezok.map((m) => `<label class="mezo">${esc(m.nev)} (${esc(m.egyseg)}, bruttó)${m.kezi ? ' <span class="cimkeszalag">saját</span>' : ""}
      <input type="number" name="${esc(m.kulcs)}" min="0" step="0.01" inputmode="decimal" value="${m.ertek || ""}" placeholder="a számládról"></label>`).join("");
    const megse = r.getElementById("dijmegse");
    megse.onclick = () => d.close();
    form.onsubmit = async (ev) => {
      ev.preventDefault();
      hiba.textContent = "";
      const ertekek = {};
      for (const m of adat.mezok) {
        const v = form[m.kulcs].value;
        if (v === "") continue;
        if (Number(v) !== m.ertek || !m.kezi) ertekek[m.kulcs] = Number(v);
      }
      if (!Object.keys(ertekek).length) { d.close(); return; }
      try {
        await this._hass.callWS({ type: "hu_rezsi/sajat_dijak", entry_id: this._entryId(f.sid), sid: f.sid, ertekek, tol: form.tol.value });
        d.close();
        this._betolt?.();
      } catch (err) { hiba.textContent = err.message || String(err); }
    };
  }

  // ---- AI-számlabeolvasó (2.3.0b1) ----
  _aiEntitasok() {
    return Object.values(this._hass?.states || {}).filter((s) => s.entity_id.startsWith("ai_task.") && s.state !== "unavailable")
      .map((s) => ({ id: s.entity_id, nev: s.attributes?.friendly_name || s.entity_id }));
  }

  _aiLehet() { return this._admin && this._aiEntitasok().length > 0; }

  _aiBeleegyezesSzoveg() {
    return "Ismeretlen számla kiolvasása AI-val\n\n"
      + "• A számla szövegét elküldöm a választott AI-szolgáltatónak (az AI Task entitás integrációjának, pl. Google Gemini). Helyi AI (pl. Ollama) esetén a gépedet nem hagyja el.\n"
      + "• Elküldés előtt igyekszem kitakarni a felismerhető személyes adatokat: a feliratos név- és címsorokat, a címeket, az ismert neveket és azonosítókat, a mérőszámot, az e-mailt, a telefont, a bankszámlát, az adóazonosítót. A kitakarás nem tökéletes – szokatlan elrendezésű számlán maradhat benne személyes adat. A szolgáltató neve és adószáma marad.\n"
      + "• Az AI válaszát és a számla szövegét nem tárolom; csak az általad jóváhagyott adatok kerülnek be.\n"
      + "• Egy kiolvasás néhány forintba kerülhet (fizetős AI-nál).\n\nEngedélyezed?";
  }

  _aiFiok(sid) {
    for (const h of this._adat?.haztartasok || []) { const f = h.fiokok.find((x) => x.sid === sid); if (f) return f; }
    return null;
  }

  async _aiNyit(sid, fajl) {
    const r = this.shadowRoot, d = r.getElementById("aiablak"), torzs = r.getElementById("aitorzs"), gombok = r.getElementById("aigombok"), hiba = r.getElementById("aihiba");
    const f = this._aiFiok(sid);
    r.getElementById("aicim").textContent = `Számla kiolvasása AI-val – ${f?.nev || ""}`;
    hiba.textContent = "";
    if (!this._adat?.panel_beallitas?.ai_beolvasas) {
      if (!window.confirm(this._aiBeleegyezesSzoveg())) return;
      try {
        const v = await this._hass.callWS({ type: "hu_rezsi/panel_beallitas", beallitas: { ai_beolvasas: true } });
        if (this._adat) this._adat.panel_beallitas = v;
      } catch (err) { alert(err.message || err); return; }
    }
    torzs.innerHTML = `<div class="aitolt"><ha-circular-progress indeterminate size="small"></ha-circular-progress> Kiolvasás folyamatban: <b>${esc(fajl)}</b> – ez 10–60 másodperc.</div>`;
    gombok.innerHTML = `<button type="button" data-aimegse>Mégse</button>`;
    gombok.querySelector("[data-aimegse]").onclick = () => { this._aiKeres = null; d.close(); };
    if (!d.open) d.showModal();
    const keresJel = (this._aiKeres = Symbol(fajl));  // egy elkésett válasz ne kerüljön egy másik fájl ablakába
    let e;
    try { e = await this._hass.callWS({ type: "hu_rezsi/ai_kiolvasas", entry_id: this._entryId(sid), sid, fajl }); }
    catch (err) { if (this._aiKeres === keresJel) { torzs.innerHTML = ""; hiba.textContent = err.message || String(err); } return; }
    if (!d.open || this._aiKeres !== keresJel) return;
    this._aiEredmeny = { sid, fajl, ...e };
    this._aiRajzol();
  }

  _aiRajzol() {
    const r = this.shadowRoot, torzs = r.getElementById("aitorzs"), gombok = r.getElementById("aigombok"), hiba = r.getElementById("aihiba");
    const e = this._aiEredmeny, a = e.adat, jel = e.jelolesek || {};
    const JEL = { ok: ["✓", "rendben"], figy: ["!", "ellenőrizd"], ellentmondas: ["✗", "ellentmondás"] };
    const jelzo = (k) => { const j = jel[k]; return j ? `<span class="aijel aijel-${j.jel}" title="${esc(JEL[j.jel][1] + (j.uzenet ? ": " + j.uzenet : ""))}">${JEL[j.jel][0]}</span>` : `<span class="aijel"></span>`; };
    const uzen = (k) => { const j = jel[k]; return j && j.jel !== "ok" && j.uzenet ? `<div class="aiuzenet aijel-${j.jel}">${esc(j.uzenet)}</div>` : ""; };
    const mezo = (k, nev, tipus = "text", ertek = a[k]) => `<label class="aimezo">${jelzo(k)}<span>${nev}</span>
      ${tipus === "tipus" ? `<select data-mezo="${k}">${[["resz", "részszámla"], ["elszamolo", "elszámoló"], ["egyeb", "egyéb"], ["storno", "sztornó"]].map(([v, n]) => `<option value="${v}" ${v === ertek ? "selected" : ""}>${n}</option>`).join("")}</select>`
        : `<input data-mezo="${k}" type="${tipus}" ${tipus === "number" ? 'step="any" inputmode="decimal"' : ""} value="${esc(ertek ?? "")}">`}</label>${uzen(k)}`;
    const tabla = (lista, oszlopok) => (a[lista] || []).length ? `<div class="tablagorgeto"><table class="aitabla"><thead><tr>${oszlopok.map((o) => `<th>${o[1]}</th>`).join("")}</tr></thead><tbody>${a[lista].map((s, i) =>
      `<tr>${oszlopok.map(([k, , t]) => { const kk = `${lista}.${i}.${k}`; return `<td>${jelzo(kk)}${t === "mod"
        ? `<select data-mezo="${kk}">${[["leolvasott", "leolvasott"], ["diktalt", "diktált"], ["becsult", "becsült"]].map(([v, n]) => `<option value="${v}" ${v === s[k] ? "selected" : ""}>${n}</option>`).join("")}</select>`
        : `<input data-mezo="${kk}" type="${t || "text"}" ${t === "number" ? 'step="any"' : ""} value="${esc(s[k] ?? "")}">`}${uzen(kk)}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>` : `<div class="kicsi">nincs</div>`;
    const o = jel._osszes || {};
    const kt = Object.entries(e.kitakarva || {}).map(([k, n]) => `${n} ${k}`).join(", ");
    torzs.innerHTML = `<div class="aiosszeg kicsi">${o.ellentmondas ? `<span class="aijel aijel-ellentmondas">✗</span> ${o.ellentmondas} ellentmondás – javítsd, vagy erősítsd meg. ` : ""}${o.figy ? `<span class="aijel aijel-figy">!</span> ${o.figy} figyelmeztetés. ` : ""}${!o.ellentmondas && !o.figy ? `<span class="aijel aijel-ok">✓</span> Minden ellenőrzött érték szerepel a számlán. ` : ""}
        Kiolvasta: ${esc(e.entitas)}${kt ? ` · elküldés előtt kitakarva: ${esc(kt)}` : ""}.</div>
      <div class="aiketoszlop"><div class="aiadatok">
        ${mezo("szolgaltato_nev", "Szolgáltató")}${mezo("sorszam", "Sorszám")}${mezo("tipus", "Típus", "tipus")}
        ${mezo("kelte", "Kelte", "date")}${mezo("fizetesi_hatarido", "Fizetési határidő", "date")}
        ${mezo("idoszak_tol", "Időszak kezdete", "date")}${mezo("idoszak_ig", "Időszak vége", "date")}
        ${mezo("fizetendo", "Fizetendő (Ft)", "number")}${mezo("szamlaertek", "Számlaérték (Ft)", "number")}
        <h4>Mérőállások</h4>${tabla("merok", [["gyari_szam", "Mérő"], ["tol_datum", "Induló nap", "date"], ["tol_allas", "Induló", "number"], ["ig_datum", "Záró nap", "date"], ["ig_allas", "Záró", "number"], ["mod", "Mód", "mod"]])}
        <h4>Elszámolt mennyiség</h4>${tabla("mennyisegek", [["megnevezes", "Megnevezés"], ["mennyiseg", "Mennyiség", "number"], ["egyseg", "Egység"]])}
        <h4>Tételek</h4>${tabla("tetelek", [["megnevezes", "Megnevezés"], ["mennyiseg", "Menny.", "number"], ["egyseg", "Egys."], ["egysegar", "Egységár", "number"], ["brutto", "Bruttó", "number"]])}
      </div><pre class="aiszoveg" tabindex="0">${this._aiKiemel(e.szoveg || "", a)}</pre></div>
      ${o.ellentmondas ? `<label class="jelolo aimeger"><input type="checkbox" id="aimeger"> Tudom, hogy ellentmondás van – mégis így veszem át</label>` : ""}
      <div class="kicsi">Átvétel után a számla a jóváhagyásra várók közé kerül: ott látod, mi változna vele (fogyasztás, költség, egyenleg), és ott hagyod jóvá vagy veted el. A <b>beolvasó mentése</b> a jóváhagyott adatokból helyi beolvasót készít (személyes adat nélkül): a szolgáltató következő számláit már AI nélkül olvasom be – ellentmondásos számlából nem készül.</div>`;
    torzs.querySelectorAll("[data-mezo]").forEach((el) => el.addEventListener("focus", () => {
      const v = el.value; if (!v) return;
      const m = [...torzs.querySelectorAll("pre.aiszoveg mark")].find((x) => x.dataset.k === el.dataset.mezo) || null;
      torzs.querySelectorAll("pre.aiszoveg mark.aktiv").forEach((x) => x.classList.remove("aktiv"));
      if (m) { m.classList.add("aktiv"); m.scrollIntoView({ block: "center", behavior: "smooth" }); }
    }));
    gombok.innerHTML = `<button type="button" data-aimegse>Mégse</button>
      <button type="button" data-aiatvesz="0" title="A számla a jóváhagyásra várók közé kerül; beolvasó nem készül">Csak átvétel</button>
      <button type="button" class="fo" data-aiatvesz="1" title="Átvétel, és a jóváhagyott adatokból helyi beolvasó (sablon) a szolgáltató következő számláihoz – AI nélkül, ingyen">Átvétel és beolvasó mentése</button>`;
    gombok.querySelector("[data-aimegse]").onclick = () => r.getElementById("aiablak").close();
    gombok.querySelectorAll("[data-aiatvesz]").forEach((g) => g.onclick = async (ev) => {
      const gomb = ev.currentTarget, sablon = gomb.dataset.aiatvesz === "1";
      hiba.textContent = "";
      const megerosit = !!torzs.querySelector("#aimeger")?.checked;
      gomb.disabled = true;  // a szerver újraellenőriz (a javított mezőkkel); ellentmondásnál csak megerősítéssel veszi át
      try {
        const v = await this._hass.callWS({ type: "hu_rezsi/ai_atvetel", entry_id: this._entryId(e.sid), sid: e.sid, fajl: e.fajl, adat: this._aiGyujt(), megerosit, sablon });
        if (!v.ok) { this._aiEredmeny = { ...e, adat: this._aiGyujt(), jelolesek: v.jelolesek }; this._aiRajzol(); r.getElementById("aihiba").textContent = "Ellentmondás van – javítsd a jelölt mezőket, vagy pipáld be a megerősítést."; return; }
        r.getElementById("aiablak").close();
        if (v.sablon) alert(v.sablon.uzenet);
        this._betolt?.();
      } catch (err) { hiba.textContent = err.message || String(err); gomb.disabled = false; }
    });
  }

  _aiGyujt() {
    const torzs = this.shadowRoot.getElementById("aitorzs"), a = structuredClone(this._aiEredmeny.adat);
    torzs.querySelectorAll("[data-mezo]").forEach((el) => {
      const ut = el.dataset.mezo.split("."), v = el.type === "number" ? (el.value === "" ? null : Number(el.value)) : (el.value || null);
      if (ut.length === 1) a[ut[0]] = v; else a[ut[0]][Number(ut[1])][ut[2]] = v;
    });
    return a;
  }

  // A számla szövegében kiemeli a kiolvasott értékeket (szám: tagolva/tagolás nélkül, dátum: pontokkal/kötőjellel).
  _aiKiemel(szoveg, a) {
    const tuk = [];
    const szamForma = (n) => {
      if (n === null || n === undefined || n === "") return [];
      const x = Number(n), egesz = Math.trunc(Math.abs(x)).toString(), tort = String(Math.abs(x)).split(".")[1];
      const tag = (s, sep) => s.replace(/\B(?=(\d{3})+(?!\d))/g, sep);
      return [...new Set([" ", " ", ".", ""].map((sep) => (x < 0 ? "-" : "") + tag(egesz, sep) + (tort ? "," + tort : ""))
        .concat(tort ? [(x < 0 ? "-" : "") + egesz + "." + tort] : []))];
    };
    const datForma = (s) => s ? [s.replaceAll("-", "."), s, s.replaceAll("-", ". ") + "."] : [];
    const add = (k, v, tip) => { for (const s of tip === "d" ? datForma(v) : tip === "n" ? szamForma(v) : (v ? [String(v)] : [])) if (s.replace(/\D/g, "").length >= 3 || (tip === "s" && s.length >= 4)) tuk.push([s, k]); };
    add("sorszam", a.sorszam, "s"); add("szolgaltato_nev", a.szolgaltato_nev, "s");
    for (const k of ["kelte", "fizetesi_hatarido", "idoszak_tol", "idoszak_ig"]) add(k, a[k], "d");
    for (const k of ["fizetendo", "szamlaertek"]) add(k, a[k], "n");
    (a.merok || []).forEach((m, i) => { add(`merok.${i}.gyari_szam`, m.gyari_szam, "s"); add(`merok.${i}.tol_datum`, m.tol_datum, "d"); add(`merok.${i}.ig_datum`, m.ig_datum, "d"); add(`merok.${i}.tol_allas`, m.tol_allas, "n"); add(`merok.${i}.ig_allas`, m.ig_allas, "n"); });
    (a.tetelek || []).forEach((m, i) => add(`tetelek.${i}.brutto`, m.brutto, "n"));
    (a.mennyisegek || []).forEach((m, i) => add(`mennyisegek.${i}.mennyiseg`, m.mennyiseg, "n"));
    tuk.sort((x, y) => y[0].length - x[0].length);
    if (!tuk.length) return esc(szoveg);
    const minta = new RegExp(tuk.map(([s]) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g");
    let ki = "", poz = 0;
    for (const m of szoveg.matchAll(minta)) {
      const elotte = szoveg[m.index - 1], utana = szoveg[m.index + m[0].length];
      if (/[\d,]/.test(elotte || "") || /\d/.test(utana || "")) continue;  // ne egy hosszabb szám belsejében
      const k = tuk.find(([s]) => s === m[0])[1];
      ki += esc(szoveg.slice(poz, m.index)) + `<mark data-k="${esc(k)}">${esc(m[0])}</mark>`;
      poz = m.index + m[0].length;
    }
    return ki + esc(szoveg.slice(poz));
  }

  _reszletek(f) {
    const tabla = (fej, sorok, osztaly = "") =>
      sorok.length
        ? `<div class="tablagorgeto"><table class="${osztaly}"><thead><tr>${fej.map((x) => `<th>${x}</th>`).join("")}</tr></thead><tbody>${sorok
            .map((s) => `<tr>${s.map((c) => `<td>${c}</td>`).join("")}</tr>`)
            .join("")}</tbody></table></div>`
        : `<div class="kicsi">nincs adat</div>`;
    const egyseg = f.egyseg === "db" ? "" : f.egyseg;
    return `
      <div class="reszletek">
        <h4>Lezárt időszakok</h4>
        ${tabla(["Időszak", "Mennyiség", "Összeg"], (f.lezart || []).map((x) => [
          idoszakSzoveg(x.tol, x.ig, ["diktalas", "atalany"].includes(f.elszamolas_mod)), f.fix_dij ? "–" : szam(Number(x.mennyiseg), egyseg), ft(x.osszesen_ft),
        ]))}
        ${f.elszamolas_mod === "diktalas" ? `<div class="kicsi">Diktálásnál a lezárt időszak két egymást követő leolvasás között tart, a fogyasztás a két állás különbsége – a számla időszaka és összege ettől eltérhet.</div>` : ""}
        ${f.fix_dij ? "" : `<h4>Mérőállások</h4>
        ${tabla(["Nap", "Állás", "Mérő", "Forrás"], (f.leolvasasok || []).map((x) => [
          nap(x.datum) + (x.elszamolasi ? " ★" : ""),
          allas(x.allas),
          // A regiszter is: H-nál 1.8.0 (összes) / 1.81 téli / 1.82 nyári, A2-nél csúcs / völgy.
          x.csatorna === "almero" ? "almérő" : x.csatorna === "betaplalas" ? "betáplálás (2.8.0)"
            : `${esc(x.mero || "fő")}${{ h_teli: " · 1.81 téli", h_nyari: " · 1.82 nyári", zona_csucs: " · 1.8.1 csúcs", zona_volgy: " · 1.8.2 völgy" }[x.csatorna]
              || (f.dijszabas === "villany/h" || (f.regiszterek || []).length ? " · 1.8.0 összes" : "")}`,
          esc(x.korrekcio ? "korrekció" : x.tipus === "kezdo" ? "kezdő óraállás" : x.tipus === "szamla_atalany" ? "számla alapján" : x.tipus === "szolgaltatoi" ? "szolgáltató" : x.megjegyzes?.startsWith("számla") ? "számla" : x.megjegyzes?.startsWith("v1") ? "v1" : "saját"),
        ]))}
        <div class="kicsi">★ éves elszámoló leolvasás · „korrekció”: korrekciós leolvasás – csak a saját szenzor szerinti állást és a korrekciós szorzót igazítja, nem időszakhatár · „számla alapján”: az átalányszámla szerint feltételezett állás (előző állás + számlázott mennyiség), tájékoztató – a fogyasztást nem befolyásolja · a „kezdő óraállás” a fiókban megadott kezdőállás – az elszámolások origója (Beállítások → fiók módosítása)</div>`}
        ${this._evesLehet(f) ? `<p><button type="button" class="linkgomb" data-eves="${f.sid}" data-entry="${this._entryId(f.sid)}">Éves elszámolási kimutatás ›</button></p>` : ""}
        ${f.dijszabas_info ? (() => {
          // Helytakarékos: a fejlécben a díjszabás neve, a részletek (érvényesség, ellenőrzés, forrás) az ⓘ buborékban;
          // a nem ellenőrzött díjszabás figyelmeztetése látható marad.
          const di = f.dijszabas_info;
          const rendben = ["szamlaval_egyezik", "arlapbol", "szamlabol"].includes(di.allapot);
          const ell = `Ellenőrzés: ${esc(di.allapot_szoveg)}${di.ellenorizve ? ` (${nap(di.ellenorizve)})` : ""}${di.mivel ? ` – ${esc(di.mivel)}` : ""}`;
          // Validálás számlacsoportonként: hol, melyik szolgáltató, milyen elszámolás és számlatípus, hány egyezett forintra.
          const val = (di.validalas || []).map((v) => `• ${v.hely ? `${esc(v.hely)}, ` : ""}${esc(v.szolgaltato)} · ${esc(v.elszamolas)}${v.hmke ? ` (${esc(v.hmke)})` : ""} · ${esc(v.szamla_tipusok.join(", "))}${v.idoszak ? ` · ${esc(v.idoszak)}` : ""}: <b>${v.forintra}/${v.szamlak}</b> számla forintra${v.max_elteres_ft ? `, legnagyobb eltérés ${ft(v.max_elteres_ft)}` : ""}${v.megjegyzes ? ` (${esc(v.megjegyzes)})` : ""}`).join("<br>");
          const reszlet = `<b>${esc(di.nev)}</b><br>Érvényes ${nap(di.ervenyes_tol)}-tól${di.ervenyes_ig ? ` ${nap(di.ervenyes_ig)}-ig` : ""}<br>${ell}${val ? `<br><b>Validáló számlák:</b><br>${val}` : ""}<br>Forrás: ${esc(di.forras)}`;
          return `<h4>Díjszabás ${info(reszlet)} <span class="kicsi dijnev">${esc(di.nev)}</span></h4>${rendben ? "" : `<div class="kicsi figyszoveg">${ell}</div>`}`;
        })() : ""}
        <h4>Számlák</h4>
        ${this._szamlaTabla(f)}
        ${f.device_id && this._admin && (f.szamlak || []).length ? `<div class="torlessor">${this._torlesGomb(f)}</div>` : ""}

      </div>`;
  }

  // Számlák: soronként lenyíló részletek (a számla minden tárolt adata). A nyitott sorokat megjegyzi (újrarajzoláskor is).
  _szamlaTabla(f) {
    const lista = f.szamlak || [];
    if (!lista.length) return `<div class="kicsi">nincs adat</div>`;
    const jel = !!f.device_id && this._admin;  // kijelölés törlésre: csak rendszergazda
    const fej = [jel ? "" : null, "Kelte", "Sorszám", "Típus", "Összeg", "Fizetve"].filter((x) => x !== null);
    const TIPUS = { elszamolo: "elsz.", resz: "rész", storno: "sztornó", egyeb: "", eloiras: "előírás" };
    const sorok = lista.map((x) => {
      const kulcs = `${f.sid}|${x.sorszam}`, nyitva = this._nyitottSzamla?.has(kulcs);
      const cellak = [
        ...(jel ? [`<input type="checkbox" class="jelol" aria-label="Kijelölés törlésre" data-fiok="${f.sid}" data-sorszam="${esc(x.sorszam)}"${this._jelolt.has(kulcs) ? " checked" : ""}>`] : []),
        `<ha-icon class="nyil" icon="${nyitva ? "mdi:chevron-down" : "mdi:chevron-right"}"></ha-icon>${rovidNap(x.kelte)}`,
        esc(x.sorszam) + (x.kezi ? ' <span class="cimkeszalag">kézi</span>' : "")
          + (x.javitas ? ` <ha-icon class="javjel" icon="mdi:pencil-outline" title="${esc(x.javitas.megjegyzes || "Kézzel javítva")}"></ha-icon>` : ""),
        TIPUS[x.tipus] ?? esc(x.tipus || ""),
        x.osszeg === null ? "–" : ft(Number(x.osszeg)),
        this._fizetesCella(f, x),
      ];
      return `<tr class="szsor" data-szamlasor="${esc(kulcs)}">${cellak.map((c) => `<td>${c}</td>`).join("")}</tr>`
        + `<tr class="szreszlet"${nyitva ? "" : " hidden"}><td colspan="${fej.length}">${this._szamlaReszlet(x, f)}</td></tr>`;
    });
    return `<div class="tablagorgeto"><table class="szamlalista"><thead><tr>${fej.map((x) => `<th>${x}</th>`).join("")}</tr></thead><tbody>${sorok.join("")}</tbody></table></div>`;
  }

  // Pénzügyi teljesítés: pipa + dátum (kézzel), a Díjnet szerint magától; nulla/mínusz fizetendőnél nincs teendő.
  _fizetesCella(f, x) {
    const z = x.fizetes;
    if (!z) return "–";
    if (z.nincs_fizetendo) return `<span class="kicsi">nincs fizetendő</span>`;
    const k = `${f.sid}|${esc(x.sorszam)}`, ki = !f.device_id;
    const allapot = z.fizetve
      ? `<input type="date" class="fizmezo fizdatum" data-fizdatum="${k}" value="${esc(z.datum || "")}" aria-label="Fizetés napja"${ki ? " disabled" : ""}>${z.forras === "dijnet" ? ' <span class="cimkeszalag" title="A Díjnet szerint kifizetve">Díjnet</span>' : z.forras === "beszedes" ? ' <span class="cimkeszalag" title="Csoportos beszedési megbízás / beszámítás: a határidő napján fizetettnek vesszük">beszedés</span>' : z.forras === "utemezett" ? ' <span class="cimkeszalag" title="Állandó átutalás: a beállított napon (munkaszüneti napon az utána következő első munkanapon) fizetettnek vesszük">állandó átutalás</span>' : ""}`
      : x.kezi && !ki && this._admin
        // Kézi számla: a határidő itt adható meg / írható át (a számláról nincs honnan kiolvasni).
        ? `<label class="kicsi${z.lejart ? " lejart" : ""}" title="Fizetési határidő">${z.lejart ? "lejárt" : "határidő"} <input type="date" class="fizmezo fizdatum" data-hatarido="${k}" value="${esc(z.hatarido || "")}" aria-label="Fizetési határidő"></label>`
        : z.lejart ? `<span class="lejart">lejárt (${rovidNap(z.hatarido)})</span>` : z.hatarido ? `<span class="kicsi">határidő ${rovidNap(z.hatarido)}</span>` : "";
    return `<span class="fizcella"><input type="checkbox" class="fizmezo" data-fizet="${k}" aria-label="Fizetve"${z.fizetve ? " checked" : ""}${ki ? " disabled" : ""}>${allapot}</span>`;
  }

  _szamlaReszlet(x, f = null) {
    const FORRAS = { mvm_aram: "MVM Next – áram", mvm_gaz: "MVM Next – gáz", dakov: "DAKÖV", mohu: "MOHU", kezi: "kézi rögzítés" };
    const TIPUS = { elszamolo: "elszámoló számla", resz: "részszámla", storno: "sztornó", egyeb: "egyéb", eloiras: "közös költség előírás" };
    const ido = (p) => (p && p[0] ? `${nap(p[0])} – ${nap(p[1])}` : null);
    const sorok = [
      ["Típus", TIPUS[x.tipus] || x.tipus],
      ["Kelte", nap(x.kelte)],
      ["Összeg", x.osszeg === null ? null : ft(Number(x.osszeg))],
      ["Elszámolt időszak", ido(x.idoszak)],
      ["Árszabás", x.arszabas],
      ["Elszámolt mennyiség", x.elszamolt_kwh != null ? szam(Number(x.elszamolt_kwh), "kWh")
        : x.elszamolt_gaz ? `${szam(Number(x.elszamolt_gaz.m3), "m³")} (${szam(Number(x.elszamolt_gaz.mj), "MJ")})`
        : x.elszamolt_viz ? `ivóvíz ${szam(Number(x.elszamolt_viz.ivoviz), "m³")} · csatorna ${szam(Number(x.elszamolt_viz.csatorna), "m³")}${x.elszamolt_viz.atalany ? " (átalány)" : ""}` : null],
      ["Következő részszámla mennyisége", x.atalany_mennyiseg != null ? `${szam(Number(x.atalany_mennyiseg))} (havonta)` : x.kovetkezo_resz_m3 != null ? szam(Number(x.kovetkezo_resz_m3), "m³") : null],
      ["Utolsó valódi mérőállás", x.utolso_valodi_allas ? nap(x.utolso_valodi_allas) : null],
      ["Következő leolvasás", ido(x.kovetkezo_leolvasas)],
      ["Következő diktálás", ido(x.kovetkezo_diktalas) || (x.diktalasi_ablak ? `minden hónap ${x.diktalasi_ablak[0]}–${x.diktalasi_ablak[1]}.` : null)],
      ["Fizetési határidő", x.hatarido ? nap(x.hatarido) : (x.fizetes?.hatarido ? nap(x.fizetes.hatarido) : null)],
      ["Fizetve", x.fizetes ? (x.fizetes.nincs_fizetendo ? "nincs fizetendő (visszatérítés vagy a folyószámláról rendezve)"
        : x.fizetes.fizetve ? `${x.fizetes.datum ? nap(x.fizetes.datum) : "igen"}${x.fizetes.forras === "dijnet" ? " (Díjnet)" : " (kézzel rögzítve)"}`
        : x.fizetes.lejart ? "nincs – a határidő lejárt" : "még nincs") : null],
      ["Forrás", FORRAS[x.forras] || x.forras],
      ["Fájl", x.fajl ? esc(x.fajl) : null],
      ["Megjegyzés", x.megjegyzes ? esc(x.megjegyzes) : null],
      ["Saját megjegyzés", x.javitas?.megjegyzes ? esc(x.javitas.megjegyzes) : null],
      ["Kézzel javítva", x.javitas?.modositva ? nap(x.javitas.modositva.slice(0, 10)) : null],
    ].filter(([, v]) => v !== null && v !== undefined && v !== "");
    return `<dl class="szamlaadat">${sorok.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`
      + (f?.device_id && this._admin ? `<button type="button" class="linkgomb" data-javit="${esc(`${f.sid}|${x.sorszam}`)}"><ha-icon icon="mdi:pencil-outline"></ha-icon> Javítás (fizetés, határidő, megjegyzés)</button>` : "");
  }

  // ---------------------------------------------------------------- mérőállás rögzítése

  _dialogus() {
    return `
      <dialog id="mentesdlg" class="szeles" aria-labelledby="mentescim">
        <div class="dfej"><h3 id="mentescim">Beállítások, mentés és visszaállítás</h3>
          <button class="ikongomb" id="mentesbezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></div>
        <div class="kicsi">Egyetlen zip-fájl: az otthonok beállításai (fiókok, szigetüzem), mérőállások, számlaadatok, fizetések,
          lezárt időszakok, a használt szenzorok neve – kérésre a számla-PDF-ek is. Visszaállításkor mindig <b>új otthon</b> jön létre
          (meglévőt nem ír felül), akár egy másik Home Assistantban is; utána a hiányzó szenzorok újra hozzárendelhetők.</div>
        <details id="panelbeall" class="mentesblokk"><summary>Panel beállításai</summary>
          <div class="mentessor">
            <label>Részletező ablakok automatikus bezárása (másodperc, 0 = soha)<input type="number" id="autobezaras" min="0" max="600" step="1" inputmode="numeric"></label>
            <button type="button" id="autobezarasment">Mentés</button>
          </div>
          <div class="kicsi">A csak megjelenítő ablakok (Részletek, Számlák kimutatása, Folyószámla, Éves összevetés, tételes bontás, D tarifa elemzés, Entitások) ennyi másodperc tétlenség után maguktól bezárulnak; mozdulat, görgetés vagy billentyű újraindítja. Az űrlapok (mérőállás, számla, mentés, beállítások) soha nem zárulnak be maguktól. Minden felhasználóra és minden otthonra érvényes (az indítókártya ablakára is).</div>
          <div id="autobezarasered" class="kicsi"></div>
          <div class="mentessor">
            <label>Megjelenítés ezen az eszközön<select id="nezetbeall"><option value="auto">automatikus (900 px felett tablet, alatta mobil)</option><option value="tablet">tablet / notebook (széles lapok, táblázatok)</option><option value="mobil">mobil (keskeny lapok, kártyák)</option><option value="regi">minden egymás alatt (a korábbi nézet)</option></select></label>
          </div>
          <div class="kicsi">Fiókonként lapozhatsz (Fiókok), vagy minden fiókot témánként láthatsz (Témák: tableten táblázatban, mobilon kártyákon) – a kettő között a fülsor jobb oldalán váltasz. Csak erre a böngészőre/eszközre vonatkozik.</div>
          <div class="mentessor">
            <label class="jelolo"><input type="checkbox" id="aibeolvasas"> Ismeretlen számla kiolvasása AI-val</label>
            <label>AI Task entitás<select id="aientitas"></select></label>
            <button type="button" id="aiment">Mentés</button>
          </div>
          <div class="kicsi">Ha egy számlát a Rezsikövető nem ismer fel, a választott AI kiolvassa belőle az adatokat; a rögzítést te hagyod jóvá. Elküldés előtt a felismerhető személyes adatokat (név, cím, azonosítók, mérőszám, e-mail, telefon, bankszámla) igyekszik kitakarni – a kitakarás nem tökéletes. Helyi AI (pl. Ollama) is választható. Alapból ki van kapcsolva.</div>
          <div id="aiered" class="kicsi"></div>
          <div class="mentessor" id="ertblokk">
            <label class="jelolo"><input type="checkbox" id="ertbe"> Értesítés a mobilra a fizetési határidő előtt</label>
            <label>Hány nappal előtte<input type="number" id="ertnapok" min="1" max="14" step="1" inputmode="numeric"></label>
            <label>Időpont<input type="time" id="ertido"></label>
          </div>
          <div class="mentessor ertcelok" id="ertcelok"></div>
          <div class="mentessor ertcelok" id="ertotthonok"></div>
          <div class="mentessor">
            <button type="button" id="ertment">Mentés</button>
            <button type="button" id="ertproba">Próbaüzenet</button>
          </div>
          <div class="kicsi">Naponta a megadott időpontban végignézi minden otthon számláit: ha egy még be nem fizetett számla határideje ennyi napon belül van, a kiválasztott telefon(ok)ra üzenetet küld (több számlát egy üzenetben). Ha a határidő elmúlt és nincs befizetve, a lejárat után egyszer még szól. Minden számláról csak egyszer; a csoportos beszedéses és az állandó átutalásos számlákról nem (ott nincs teendő). A telefonok a Home Assistant mobilalkalmazásából jönnek (<code>notify.mobile_app_…</code>). Bekapcsolva a fejlécben egy telefon ikon jelzi.</div>
          <div id="ertered" class="kicsi"></div>
        </details>
        <h4>Mentés most</h4>
        <div class="mentessor">
          <label>Otthon<select id="mentesotthon"></select></label>
          <label class="pipa"><input type="checkbox" id="mentesszamlak" checked> számla-fájlokkal (PDF, XML)</label>
          <button class="fo" type="button" id="mentesmost">Mentés</button>
        </div>
        <div id="mentesered" class="kicsi"></div>
        <details id="menteshelyek" class="mentesblokk"><summary>Mentési helyek és ütemezés</summary>
          <div id="helytabla" class="tablagorgeto"></div>
          <div class="mentessor">
            <label>Új hely<select id="helyjelolt"></select></label>
            <label>Almappa<input type="text" id="helyalmappa" value="Rezsikoveto_mentes"></label>
            <button type="button" id="helyhozzaad">Hozzáadás</button>
          </div>
          <div class="kicsi">Hálózati tárhely (NAS): Beállítások → Rendszer → Tárhely → <i>Hálózati tárhely hozzáadása</i> (Média vagy Megosztás használattal), utána itt választható.
            Google Drive: a helyi mentés a <code>config</code> mappában van, így a Google Drive Backup kiegészítő HA-mentéseivel automatikusan felkerül – visszaállításhoz lásd lent.</div>
          <h4>Ütemezés</h4>
          <div class="mentessor">
            <label>Gyakoriság<select id="utemgyak"><option value="ki">kikapcsolva</option><option value="napi">naponta</option><option value="heti">hetente</option></select></label>
            <label id="utemnapcimke">Nap<select id="utemnap">${["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"].map((n, i) => `<option value="${i}">${n}</option>`).join("")}</select></label>
            <label>Időpont<input type="time" id="utemido" value="03:30"></label>
            <label class="pipa"><input type="checkbox" id="utemszamlak"> számla-fájlokkal</label>
          </div>
          <div id="utolsomentes" class="kicsi"></div>
          <div class="gombok"><button class="fo" type="button" id="beallitasment">Beállítások mentése</button></div>
        </details>
        <h4>Mentések</h4>
        <div id="menteslista" class="tablagorgeto"></div>
        <details id="hamentesek" class="mentesblokk"><summary>Visszaállítás Home Assistant-mentésből (pl. Google Drive)</summary>
          <div class="kicsi">A HA mentései (helyi, felhő) tartalmazzák a Rezsikövető adatait is – akkor is, ha Rezsikövető-mentés még nem készült.
            Új rendszeren: a Google Drive-on lévő mentést előbb töltsd vissza a HA-ba (Google Drive Backup kiegészítő → a mentésnél <i>Upload</i>, vagy Beállítások → Rendszer → Mentések → <i>Feltöltés</i>), utána itt megjelenik.
            A <b>Kiolvasás</b> a HA-mentésből Rezsikövető-mentést készít (titkosítottnál a HA mentéskulcsával; nagy mentésnél egy-két perc), ami a fenti listából visszaállítható.</div>
          <div id="halista" class="tablagorgeto"></div>
        </details>
        <h4>Visszaállítás feltöltött mentésből</h4>
        <label>Rezsikövető-mentés (.zip), pl. másik Home Assistantból<input type="file" id="mentesfeltolt" accept=".zip,application/zip"></label>
      </dialog>
      <dialog id="szenzordlg" class="szeles" aria-labelledby="szenzorcim">
        <div class="dfej"><h3 id="szenzorcim">Szenzorok hozzárendelése</h3>
          <button class="ikongomb" id="szenzorbezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></div>
        <div class="kicsi">Melyik szenzorból számol a Rezsikövető. A pirossal jelölt szenzor ebben a rendszerben nem található (pl. visszaállítás után
          új Home Assistantban) – válaszd ki helyette az új szenzort (gépeléssel kereshető). Az <b>összes energia / mérőállás</b> típusú, növekvő szenzor kell (kWh, m³).</div>
        <div id="szenzortabla" class="tablagorgeto"></div>
        <datalist id="szenzorjeloltek"></datalist>
        <div id="szenzorered" class="kicsi"></div>
        <div class="gombok"><button type="button" id="szenzormegse">Mégse</button><button class="fo" type="button" id="szenzorment">Mentés</button></div>
      </dialog>
      <dialog id="grafdlg" class="szeles" aria-labelledby="grafcim">
        <div class="dfej"><h3 id="grafcim" tabindex="-1" autofocus>Éves összevetés</h3>
          <button class="ikongomb" id="grafbezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></div>
        <div class="grafvezerlo">
          <div class="szegmens" role="group" aria-label="Mérték">
            <button type="button" data-mertek="mennyiseg" aria-pressed="true" id="grafmfogy">Fogyasztás</button>
            <button type="button" data-mertek="betaplalas" aria-pressed="false" class="napelemgomb" hidden>Betáplálás</button>
            <button type="button" data-mertek="netto" aria-pressed="false" class="napelemgomb" hidden>Nettó</button>
            <button type="button" data-mertek="ft" aria-pressed="false">Költség</button>
          </div>
          <label class="sor-label">Év <select id="grafev"></select></label>
          <span class="kicsi" id="grafvs"></span>
        </div>
        <div id="grafosszeg" class="grafosszeg"></div>
        <div class="grafdoboz"><div id="grafsvg"></div><div id="graftip" class="graftip" hidden></div></div>
        <div id="grafjel" class="grafjel"></div>
        <div id="grafnapelem" class="graftabla"></div>
        <details class="graftabla"><summary>Táblázat</summary><div id="graftabla"></div></details>
        <div class="kicsi" id="grafmegj"></div>
      </dialog>
      <dialog id="reklamdlg" class="szeles" aria-labelledby="reklamcim">
        <div class="dfej"><h3 id="reklamcim" tabindex="-1" autofocus>Reklamáció-tervezet</h3>
          <span class="dfejgombok"><button class="ikongomb" id="reklammasol" title="Szöveg másolása"><ha-icon icon="mdi:content-copy"></ha-icon></button>
          <button class="ikongomb" id="reklamnyomtat" title="Nyomtatás / PDF"><ha-icon icon="mdi:printer"></ha-icon></button>
          <button class="ikongomb" id="reklambezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></span></div>
        <div id="reklambody"></div>
      </dialog>
      <dialog id="evesdlg" class="szeles evesdlg" aria-labelledby="evescim">
        <div class="dfej"><h3 id="evescim" tabindex="-1" autofocus>Éves elszámolási kimutatás</h3>
          <span class="dfejgombok"><select id="evesev" aria-label="Elszámolási év"></select>
          <button class="ikongomb" id="evesreklam" title="Reklamáció-tervezet" disabled><ha-icon icon="mdi:email-edit-outline"></ha-icon></button>
          <button class="ikongomb" id="evesnyomtat" title="Nyomtatás / PDF" disabled><ha-icon icon="mdi:printer"></ha-icon></button>
          <button class="ikongomb" id="evesbezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></span></div>
        <div id="evesbody"></div>
      </dialog>
      <dialog id="teteldlg" class="szeles" aria-labelledby="tetelcim">
        <div class="dfej"><h3 id="tetelcim" tabindex="-1" autofocus>Várható számla – tételesen</h3>
          <span class="dfejgombok"><button class="ikongomb" id="tetelbezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></span></div>
        <div id="tetelbody"></div>
      </dialog>
      <dialog id="kimutdlg" class="szeles" aria-labelledby="kimutcim">
        <div class="dfej"><h3 id="kimutcim" tabindex="-1" autofocus>Számlák kimutatása</h3>
          <span class="dfejgombok"><button class="ikongomb" id="kimutnyomtat" title="Nyomtatás (mobilon PDF-fájl letöltése)" aria-label="Nyomtatás vagy PDF" disabled><ha-icon icon="mdi:printer-outline"></ha-icon></button>
          <button class="ikongomb" id="kimutcsv" title="Letöltés CSV-be (Excelben megnyitható)" aria-label="Letöltés CSV-be" disabled><ha-icon icon="mdi:file-download-outline"></ha-icon></button>
          <button class="ikongomb" id="kimutbezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></span></div>
        <div class="grafvezerlo">
          <label class="sor-label">Időszak <select id="kimutev"></select></label>
        </div>
        <div id="kimuttabla" class="kimut"></div>
        <div id="kimutreszlet" class="kimutreszlet"></div>
        <div class="kicsi" id="kimutmegj"></div>
      </dialog>
      <dialog id="fszdlg" class="szeles" aria-labelledby="fszcim">
        <div class="dfej"><h3 id="fszcim" tabindex="-1" autofocus>Folyószámla</h3>
          <span class="dfejgombok"><button class="ikongomb" id="fsznyomtat" title="Nyomtatás (mobilon PDF-fájl letöltése)" aria-label="Nyomtatás vagy PDF" disabled><ha-icon icon="mdi:printer-outline"></ha-icon></button>
          <button class="ikongomb" id="fszcsv" title="Letöltés CSV-be (Excelben megnyitható)" aria-label="Letöltés CSV-be" disabled><ha-icon icon="mdi:file-download-outline"></ha-icon></button>
          <button class="ikongomb" id="fszbezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></span></div>
        <div class="grafvezerlo"><span class="fszfulek" role="tablist" aria-label="Nézet"><button type="button" role="tab" data-fsznezet="teljesites">Teljesítés</button><button type="button" role="tab" data-fsznezet="kivonat">Kivonat</button></span>
          <span class="fszfulek" id="fszmod" role="tablist" aria-label="Közös folyószámla" hidden></span>
          <label class="sor-label">Időszak <select id="fszidoszak"></select></label></div>
        <div id="fsztabla"></div>
        <div class="kicsi" id="fszmegj"></div>
      </dialog>
      <dialog id="ddlg" class="szeles" aria-labelledby="dcim">
        <div class="dfej"><h3 id="dcim" tabindex="-1" autofocus>D tarifa elemzés</h3>
          <button class="ikongomb" id="dbezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></div>
        <div class="grafvezerlo">
          <div class="szegmens" role="group" aria-label="Nézet">
            <button type="button" data-dnezet="koltseg" aria-pressed="true">Költség</button>
            <button type="button" data-dnezet="halmozott" aria-pressed="false">Halmozott</button>
            <button type="button" data-dnezet="ar" aria-pressed="false">Egységár</button>
          </div>
          <div class="szegmens" role="group" aria-label="Számítás">
            <button type="button" data-dmod="mvm" aria-pressed="true" title="A keret feletti mennyiség a hónap teljes fogyasztásával súlyozott D-áron – ahogy az MVM számlázza">MVM szerint</button>
            <button type="button" data-dmod="sajat" aria-pressed="false" title="A keret átlépésétől az adott negyedórák D-árán">Átlépés szerint</button>
          </div>
          <label class="sor-label">Hónap <select id="dhonap"></select></label>
          <label class="sor-label">Nap <select id="dnap"></select></label>
        </div>
        <div id="dosszeg" class="grafosszeg"></div>
        <div class="grafdoboz"><div id="dsvg"></div><div id="dtip" class="graftip" hidden></div></div>
        <div id="djel" class="grafjel"></div>
        <div id="dhavi" class="graftabla dhavi"></div>
        <div class="kicsi" id="dmegj"></div>
      </dialog>
      <dialog id="leolv">
        <form method="dialog" id="leolvform">
          <h3 id="leolvcim">Mérőállás rögzítése</h3>
          <label class="pipa" id="cseresor"><input type="checkbox" name="csere"> Mérőcsere (a régi mérőt leszerelték, újat szereltek fel)</label>
          <label>Nap<input type="date" name="datum" required></label>
          <div id="cseremezok" hidden>
            <label>Régi mérő záró állása<input type="number" name="regi_zaro" step="0.001" min="0" inputmode="decimal"></label>
            <label>Új mérő kezdő állása<input type="number" name="uj_kezdo" step="0.001" min="0" value="0" inputmode="decimal"></label>
            <label>Új mérő gyári száma (opcionális)<input type="text" name="uj_gyari"></label>
            <div id="cserehreg" hidden>
              <label>Régi mérő 1.81 (téli) záró<input type="number" name="regi_181" step="0.001" min="0" inputmode="decimal"></label>
              <label>Régi mérő 1.82 (nyári) záró<input type="number" name="regi_182" step="0.001" min="0" inputmode="decimal"></label>
              <label>Új mérő 1.81 (téli) kezdő<input type="number" name="uj_181" step="0.001" min="0" inputmode="decimal"></label>
              <label>Új mérő 1.82 (nyári) kezdő<input type="number" name="uj_182" step="0.001" min="0" inputmode="decimal"></label>
            </div>
            <div class="kicsi">A régi mérő a csere napján lezárul a záró állással, az új innen indul. A fogyasztás a cserén át folytonos, az éves keret és az elszámolási év nem változik. A záró és a kezdő állás a cserelapon (vagy a szolgáltató számláján) szerepel.</div>
          </div>
          <label id="csatsor">Mérő<select name="csatorna"></select></label>
          <div id="allasmezok">
          <label id="allassor"><span id="allascim">Mérőállás</span><input type="number" name="allas" step="0.001" min="0" required inputmode="decimal"></label>
          <div class="kicsi" id="utolsoallas"></div>
          <div id="hregsor" hidden>
            <label>1.81 – téli (H-ár)<input type="number" name="reg181" step="0.001" min="0" inputmode="decimal"></label>
            <label>1.82 – nyári (A1-ár)<input type="number" name="reg182" step="0.001" min="0" inputmode="decimal"></label>
            <div class="kicsi" id="hregmegj">Ahogy az MVM alkalmazásában: a két regiszter (1.81 téli, 1.82 nyári). Az összeset (1.8.0 = 1.81 + 1.82) a Rezsikövető számolja és tárolja.</div>
          </div>
          <label class="pipa" id="korrsor"><input type="checkbox" name="korrekcio"> Csak korrekciós leolvasás – a saját szenzor szerinti állást és a korrekciós szorzót igazítja; nem diktálás, nem elszámoló és nem időszakhatár</label>
          <label class="pipa" id="szolgsor"><input type="checkbox" name="szolgaltatoi"> Szolgáltatói leolvasás (nem saját)</label>
          <label class="pipa" id="evessor"><input type="checkbox" name="eves"> Éves (elszámoló) leolvasás – a szolgáltató leolvasója járt itt; innen indul az új elszámolási év és a kedvezményes keret</label>
          <label class="pipa" id="diktaltsor"><input type="checkbox" name="diktalt"> Diktáltam a szolgáltatónak (itt zárul az elszámolási időszak; átalánynál egyszer, csak a következő számlát írja felül)</label>
          </div>
          <div class="dhiba" id="dhiba"></div>
          <div class="kicsi" id="dered"></div>
          <div class="gombok">
            <button value="megse" type="button" id="megse">Mégse</button>
            <button class="fo" type="submit" id="leolvmentes">Mentés</button>
          </div>
        </form>
      </dialog>
      <dialog id="szamladlg">
        <form method="dialog" id="szamlaform">
          <h3 id="szamlacim">Számla rögzítése</h3>
          <div id="feltoltsor" class="feltoltsor">
            <label>PDF vagy XML számla feltöltése<input type="file" name="fajl" accept=".pdf,.xml,application/pdf,application/xml,text/xml"></label>
            <div class="kicsi" id="feltolteredmeny"></div>
            <div class="kicsi elvalaszto">– vagy add meg kézzel –</div>
          </div>
          <div class="kicsi" id="nincsmappa">Fájl feltöltéséhez adj meg számlamappát a fiók beállításaiban; addig kézzel rögzíthetsz.</div>
          <label>Kelte<input type="date" name="kelte" required></label>
          <label>Fizetendő összeg (Ft)<input type="number" name="osszeg" step="1" required inputmode="decimal"></label>
          <label>Fizetési határidő (nem kötelező)<input type="date" name="hatarido"></label>
          <label>Típus<select name="tipus"><option value="resz">Részszámla</option><option value="elszamolo">Elszámoló számla</option><option value="egyeb">Egyéb</option><option value="eloiras">Közös költség előírás (havi befizetendő)</option></select></label>
          <label>Sorszám (nem kötelező)<input type="text" name="sorszam"></label>
          <div class="ket2"><label>Időszak kezdete<input type="date" name="tol"></label><label>Időszak vége<input type="date" name="ig"></label></div>
          <label class="merosor">Záró mérőállás (nem kötelező)<input type="number" name="zaro" step="0.001" min="0" inputmode="decimal"></label>
          <label class="pipa merosor"><input type="checkbox" name="leolvasott"> A záró állást a szolgáltató olvasta le</label>
          <label id="futosor">Fűtőérték (MJ/m³, nem kötelező)<input type="number" name="futo" step="0.01" min="0" inputmode="decimal"></label>
          <div class="kicsi">A záró állás az időszak utolsó napjára kerül (időszak nélkül a kelte napjára).</div>
          <div class="dhiba" id="szhiba"></div>
          <div class="gombok">
            <button type="button" id="szmegse">Mégse</button>
            <button class="fo" type="submit">Mentés</button>
          </div>
        </form>
      </dialog>
      <dialog id="torlesdlg">
        <h3 id="torlescim">Számlák törlése</h3>
        <ul id="torleslista" class="torleslista"></ul>
        <div class="kicsi" id="torlesfigy"></div>
        <div class="dhiba" id="torleshiba"></div>
        <div class="gombok">
          <button type="button" id="torlesmegse">Mégse</button>
          <button type="button" class="veszely tele" id="torlesok">Végleges törlés</button>
        </div>
      </dialog>
      <dialog id="javdlg" aria-labelledby="javcim">
        <h3 id="javcim">Számla javítása</h3>
        <div id="javszoveg" class="kicsi"></div>
        <div id="javmezok">
          <label class="javsor"><input type="checkbox" id="javfiz"> Kifizetve</label>
          <label>Fizetés napja <input type="date" id="javdatum"></label>
          <label>Fizetési határidő <input type="date" id="javhatarido"></label>
          <label>Megjegyzés <textarea id="javmegj" rows="3" maxlength="500" placeholder="pl. kedvezmény miatt kevesebb; reklamálva szept. 3-án"></textarea></label>
        </div>
        <div class="kicsi">Az összeg, az időszak és a mérőállás a számlából jön, itt nem módosítható (hibánál: reklamáció, stornó vagy a számla újraolvasása). A javítást a számla újraolvasása nem írja felül.</div>
        <div class="dhiba" id="javhiba"></div>
        <div class="gombok">
          <button type="button" id="javdijnet" hidden title="A kézi fizetés-jelölés törlése: a Díjnet / csoportos beszedés szerinti állapot érvényes">Kézi jelölés törlése</button>
          <button type="button" id="javmegse">Mégse</button>
          <button type="button" class="fo" id="javment">Mentés</button>
        </div>
      </dialog>
      <dialog id="lezardlg">
        <h3 id="lezarcim">Fiók lezárása</h3>
        <div id="lezarszoveg" class="kicsi"></div>
        <div id="lezarmezok">
          <label>Lezárás napja (végleolvasás) <input type="date" id="lezardatum"></label>
          <label>Záró óraállás (a végszámla szerint) <input type="number" step="0.001" min="0" id="lezarallas" inputmode="decimal"></label>
        </div>
        <div class="dhiba" id="lezarhiba"></div>
        <div class="gombok">
          <button type="button" id="lezarmegse">Mégse</button>
          <button type="button" class="veszely tele" id="lezarok">Lezárás</button>
        </div>
      </dialog>
      <dialog id="emaildlg" class="emaildlg" aria-labelledby="emailcim">
        <div class="dfej"><h3 id="emailcim">📧 Számlák e-mailből</h3>
          <button class="ikongomb" id="emailbezar" title="Bezárás"><ha-icon icon="mdi:close"></ha-icon></button></div>
        <div id="emailbody"></div>
      </dialog>
      <dialog id="dijablak">
        <h3 id="dijcim">Saját díjak</h3>
        <div class="kicsi">A díj településenként, edényméret vagy ürítési gyakoriság szerint eltér: írd be a saját számládon szereplő <b>bruttó</b> díjakat. Az „érvényes ettől” naptól számol velük (a korábbi időszak marad).</div>
        <form id="dijform"><div id="dijmezok"></div>
          <label class="mezo">Érvényes ettől<input type="date" name="tol" required></label>
          <div class="kicsi hiba" id="dijhiba"></div>
          <div class="gombok"><button type="button" id="dijmegse">Mégse</button><button type="submit" class="fo">Mentés</button></div>
        </form>
      </dialog>
      <dialog id="aiablak" class="aiablak">
        <h3 id="aicim">Számla kiolvasása AI-val</h3>
        <div id="aitorzs"></div>
        <div class="kicsi hiba" id="aihiba"></div>
        <div class="gombok" id="aigombok"></div>
      </dialog>
      <dialog id="beallit">
        <h3 id="beallitcim">Entitások</h3>
        <div class="kicsi">Koppints egy entitásra a beállításaihoz (név, ikon, láthatóság).</div>
        <div id="entlista"></div>
        <div class="gombok">
          <button type="button" id="eszkozoldal">Eszköz oldala</button>
          <button type="button" class="fo" id="beallitbezar">Bezárás</button>
        </div>
      </dialog>`;
  }

  // ---------------------------------------------------------------- számlák e-mailből: vezetett beállítás

  _emailNyit(entry_id) {
    this._em = { entry_id, lepes: 1, email: "", lv: null, hiba: null, sid: null };
    this._emailRajzol();
    const d = this.shadowRoot.getElementById("emaildlg");
    if (!d.open) d.showModal();
  }

  _emailRajzol() {
    const g = this._em, body = this.shadowRoot.getElementById("emailbody");
    if (!g || !body) return;
    const lepesjel = `<ol class="emlepesek" aria-label="Lépések">${["Mi kell?", "Belépés", "Keresés", "Kész"].map((n, i) =>
      `<li class="${i + 1 === g.lepes ? "aktiv" : i + 1 < g.lepes ? "kesz" : ""}"${i + 1 === g.lepes ? ' aria-current="step"' : ""}>${n}</li>`).join("")}</ol>`;
    const lv = g.lv;
    const sugo = lv && g.email.includes("@") ? `<div class="emsugo"><b>${esc(lv.nev || "Levelező")}</b>${lv.nem_tamogatott ? "" : lv.alkalmazasjelszo ? ": ide <b>alkalmazásjelszó</b> kell, nem a szokásos jelszavad." : lv.ismert ? ": a szokásos jelszavad kell." : ": ismeretlen levelező – ha nem sikerül, a Haladó részben add meg a szervert."}
        <ol>${(lv.lepesek || []).map((x) => `<li>${esc(x).replace(/(https:\/\/[^\s)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')}</li>`).join("")}</ol>
        ${lv.link && lv.alkalmazasjelszo && !lv.nem_tamogatott ? `<a class="emlink" href="${esc(lv.link)}" target="_blank" rel="noopener">Alkalmazásjelszó készítése ↗</a>` : ""}</div>` : "";
    let html;
    if (g.lepes === 1) {
      html = `<p>Ha a szolgáltatóid (MVM, vízmű, Telekom…) e-mailben küldik a számlát, a Rezsikövető ki tudja olvasni őket a postafiókodból – utána <b>maguktól bekerülnek</b>, nem kell feltöltened.</p>
        <p><b>Ehhez két dolog kell:</b></p>
        <ol class="emnagy"><li>Az <b>e-mail címed</b>, ahová a számlák jönnek.</li>
          <li>Egy <b>jelszó</b>: Gmailnél <b>alkalmazásjelszó</b> (2 perc alatt elkészíted, a következő lépés megmutatja hogyan), Freemailnél a szokásos jelszavad.</li></ol>
        <p class="kicsi">A Rezsikövető csak olvas: semmit nem töröl, nem helyez át, nem jelöl olvasottnak. A jelszó a saját Home Assistantodban marad.</p>
        <div class="gombok"><button type="button" class="fo" data-emlepes="2">Tovább</button></div>`;
    } else if (g.lepes === 2) {
      html = `<label>E-mail cím<input type="email" id="emcim" autocomplete="email" inputmode="email" placeholder="pl. kovacs.anna@gmail.com" value="${esc(g.email)}"></label>
        ${sugo}
        <label>Jelszó${lv?.alkalmazasjelszo ? " (alkalmazásjelszó)" : ""}<input type="password" id="emjelszo" autocomplete="off" placeholder="${lv?.alkalmazasjelszo ? "pl. abcd efgh ijkl mnop" : ""}"></label>
        <details class="emhalado"${g.halado ? " open" : ""}><summary>Haladó</summary>
          <label>Név (a panelen így látod)<input type="text" id="emnev" placeholder="${esc((g.email.split("@")[0]) || "pl. Saját")}"></label>
          <label>IMAP-szerver<input type="text" id="emszerver" placeholder="${esc(lv?.szerver || "imap.pelda.hu")}" value="${esc(g.szerver || "")}"></label>
          <label>Port<input type="number" id="emport" min="1" max="65535" value="${g.port || 993}"></label>
        </details>
        ${g.hiba ? `<div class="dhiba emhiba" role="alert">${esc(g.hiba).replace(/(https:\/\/[^\s)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')}</div>` : ""}
        <div class="gombok"><button type="button" data-emlepes="1">Vissza</button><button type="button" class="fo" id="emkuld"${g.kuldes ? " disabled" : ""}>${g.kuldes ? "Belépés…" : "Kapcsolódás"}</button></div>`;
    } else if (g.lepes === 3) {
      html = `<div class="emkeres"><span class="porgo nagy" aria-hidden="true"></span><div><b>Keresem a számláidat…</b>
        <div class="kicsi">Az utolsó fél év leveleit nézem át (a Kukát is), és a számlákat a fiókjaidhoz rendelem. Ez több percig is tarthat – nyugodtan bezárhatod, a háttérben folytatódik.</div></div></div>
        <div class="gombok"><button type="button" id="emhatter">Bezárás (fut tovább)</button></div>`;
    } else {
      const f = g.eredmeny?.felderites, e = g.eredmeny?.email;
      const ossz = (f?.osszekotve || []), mar = (f?.mar_bekotve || []);
      html = f?.hiba ? `<p class="figyszoveg">A keresés nem sikerült: ${esc(f.hiba)}</p>` : f ? `<p class="emkesz">✓ Kész! Az utolsó fél évben <b>${f.talalt || 0} számlát</b> találtam.</p>
        ${ossz.length ? `<p>Mostantól e-mailből jönnek:</p><ul>${ossz.map((x) => `<li><b>${esc(x.nev)}</b> – ${esc((x.tipusok || []).join(", "))}</li>`).join("")}</ul>` : ""}
        ${mar.length ? `<p class="kicsi">Már be volt kötve: ${mar.map((x) => esc(x.nev)).join(", ")}.</p>` : ""}
        ${(e?.kerdesek || []).length ? `<p>❓ ${(e.kerdesek || []).length} számláról nem tudom biztosan, melyik fiókhoz tartozik – a panelen egy gombnyomással eldöntheted.</p>` : ""}
        ${(e?.ajanlatok || []).length ? `<p>➕ Olyan szolgáltató számláit is találtam, amelyhez még nincs fiók – a panelen felveheted.</p>` : ""}
        ${!f.talalt ? `<p class="kicsi">Nem találtam számlát. Ha a szolgáltató csak most kezd e-mailben számlázni, semmi teendőd: óránként újra megnézem.</p>` : ""}`
        : `<p>A keresés a háttérben tovább fut – az eredményt a panelen, az otthon összesítőjében látod.</p>`;
      html += `<div class="gombok"><button type="button" class="fo" id="emkesz">Rendben</button></div>`;
    }
    body.innerHTML = lepesjel + html;
    body.querySelector("#emcim")?.focus({ preventScroll: true });
  }

  _emailKezelo() {
    const r = this.shadowRoot, d = r.getElementById("emaildlg");
    if (!d) return;
    const bezar = () => { d.close(); this._em = null; this._betolt(); };
    r.getElementById("emailbezar").addEventListener("click", bezar);
    d.addEventListener("cancel", () => { this._em = null; setTimeout(() => this._betolt(), 0); });
    const body = r.getElementById("emailbody");
    let idozito;
    body.addEventListener("input", (ev) => {
      if (ev.target.id !== "emcim") return;
      this._em.email = ev.target.value.trim();
      clearTimeout(idozito);
      idozito = setTimeout(async () => {
        if (!this._em?.email.includes("@")) return;
        try {
          this._em.lv = await this._hass.callWS({ type: "hu_rezsi/postafiok_felismeres", email: this._em.email });
          this._em.halado = this._em.halado || (this._em.lv.cim_jo && !this._em.lv.ismert);
        } catch (e) { return; }
        const jelszo = r.getElementById("emjelszo")?.value || "", aktiv = r.activeElement?.id, poz = r.getElementById("emcim")?.selectionStart;
        this._emailRajzol();
        r.getElementById("emjelszo").value = jelszo;
        if (aktiv) { const el = r.getElementById(aktiv); el?.focus(); if (aktiv === "emcim" && poz != null) el.setSelectionRange(poz, poz); }
      }, 450);
    });
    body.addEventListener("click", async (ev) => {
      const lep = ev.target.closest("[data-emlepes]");
      if (lep) { this._em.lepes = Number(lep.dataset.emlepes); this._em.hiba = null; this._emailRajzol(); return; }
      if (ev.target.closest("#emhatter")) { bezar(); return; }
      if (ev.target.closest("#emkesz")) { bezar(); return; }
      if (!ev.target.closest("#emkuld")) return;
      const g = this._em;
      g.email = r.getElementById("emcim").value.trim();
      const jelszo = r.getElementById("emjelszo").value;
      const nev = r.getElementById("emnev")?.value.trim(), szerver = r.getElementById("emszerver")?.value.trim(), port = Number(r.getElementById("emport")?.value || 993);
      g.szerver = szerver; g.port = port;
      if (!g.email.includes("@")) { g.hiba = "Írd be az e-mail címed."; this._emailRajzol(); return; }
      if (!jelszo) { g.hiba = "Írd be a jelszót."; this._emailRajzol(); r.getElementById("emjelszo").focus(); return; }
      g.kuldes = true; g.hiba = null;
      this._emailRajzol();
      r.getElementById("emjelszo").value = jelszo;
      try {
        const v = await this._hass.callWS({ type: "hu_rezsi/postafiok_hozzaad", entry_id: g.entry_id, email_cim: g.email, jelszo,
          ...(nev ? { nev } : {}), ...(szerver ? { imap_szerver: szerver } : {}), ...(port && port !== 993 ? { imap_port: port } : {}) });
        g.kuldes = false;
        if (v.hiba) {
          g.hiba = v.szoveg; g.halado = g.halado || v.halado;
          this._emailRajzol();
          r.getElementById("emjelszo").value = jelszo;
          return;
        }
        g.sid = v.sid; g.lepes = 3;
        this._emailRajzol();
        this._emailVar();
      } catch (e) {
        g.kuldes = false; g.hiba = `Nem sikerült: ${e.message || e}`;
        this._emailRajzol();
      }
    });
  }

  // A felderítés végéig a panel adatait lekérdezi (az otthon közben újratöltődik); újrarajzolás nélkül, hogy a
  // nyitott ablak megmaradjon.
  async _emailVar() {
    const g = this._em, kezd = Date.now();
    while (this._em === g && g.lepes === 3) {
      await new Promise((ok) => setTimeout(ok, 2500));
      if (this._em !== g) return;
      let adat;
      try { adat = await this._hass.callWS({ type: "hu_rezsi/adatok" }); } catch (e) { continue; }
      this._adat = adat;
      const h = adat.haztartasok.find((x) => x.entry_id === g.entry_id);
      const p = h?.email?.postafiokok?.find((x) => x.sid === g.sid);
      if (p && p.felderites && !p.felderites_fut) {
        g.eredmeny = { felderites: p.felderites, email: h.email };
        g.lepes = 4;
      } else if (Date.now() - kezd > 240000) {
        g.lepes = 4;
      } else continue;
      this._emailRajzol();
    }
  }

  // „Keresés újra” után: a felderítés végéig néhány másodpercenként frissít (szerkesztés alatt nem).
  _emailFut() {
    return (this._adat?.haztartasok || []).some((h) => h.email?.fut || (h.email?.postafiokok || []).some((p) => p.felderites_fut));
  }

  // Amíg valamelyik postafiókban keresés vagy átnézés fut, 5 mp-enként újratölt (időkorlát nélkül: a fél év
  // átnézése több percig is tarthat); a _betolt a végén magától nem ütemez újat. Megnyitáskor is elindul.
  _emailFigyel() {
    if (this._emailFigyIdo) return;
    this._emailFigyIdo = setTimeout(async () => {
      this._emailFigyIdo = null;
      if (!this.isConnected) return;
      if (this._szerkesztesAlatt()) this._emailFigyel();
      else await this._betolt();
    }, 5000);
  }

  _dialogusNyit(f) {
    if (!f) return;
    this._dfiok = f;
    const d = this.shadowRoot.getElementById("leolv");
    this.shadowRoot.getElementById("leolvcim").textContent = `Mérőállás – ${f.nev}`;
    const form = this.shadowRoot.getElementById("leolvform");
    form.datum.value = new Date().toISOString().slice(0, 10);
    form.allas.value = "";
    // H-tarifa: egy ablakban az összes (1.8.0) és a két regiszter (1.81, 1.82), mint az MVM-diktálásnál.
    const h = f.dijszabas === "villany/h";
    this.shadowRoot.getElementById("hregsor").hidden = !h;
    this.shadowRoot.getElementById("allascim").textContent = "Mérőállás";
    // H-tarifa: csak a két regiszter (mint az MVM alkalmazásában); az 1.8.0 rejtett, a kettő összege.
    this.shadowRoot.getElementById("allassor").style.display = h ? "none" : "";
    form.allas.required = !h;
    // Előtöltés a legutolsó rögzített állásokkal (csatornánként); a Mentés csak változás után aktív.
    const ut = f.utolso_allasok || {};
    const ertek = (c) => (ut[c] ? String(ut[c].allas) : "");
    form.allas.value = ertek("vetelezes");
    form.reg181.value = h ? ertek("h_teli") : "";
    form.reg182.value = h ? ertek("h_nyari") : "";
    this._dkezdo = { allas: form.allas.value, reg181: form.reg181.value, reg182: form.reg182.value };
    this._dkezi = new Set();  // a kézzel átírt mezők
    const opciok = [["vetelezes", f.kozmu === "viz" ? "Főmérő" : "Mérő"]];
    const regNev = { h_teli: "H téli regiszter (1.81)", h_nyari: "H nyári regiszter (1.82)", zona_csucs: "A2 csúcsidőszak (1.8.1)", zona_volgy: "A2 völgyidőszak (1.8.2)" };
    for (const r of f.regiszterek || []) if (!h) opciok.push([r, regNev[r] || r]);  // H-nál a regiszterek külön mezőben
    // A locsolási almérő: idénykorlátos díjszabásnál csak az idényben (máj. 1. – szept. 30., zárás okt. 1-jén), DAKÖV-nál egész évben.
    const md = new Date().toISOString().slice(5, 10);
    if (f.almero && (!f.almero_idenyben || (md >= "05-01" && md <= "10-01"))) opciok.push(["almero", "Locsolási almérő"]);
    if (f.napelem_mod && f.napelem_mod !== "nincs") opciok.push(["betaplalas", "Betáplálás (2.8.0)"]);
    form.csatorna.innerHTML = opciok.map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
    this.shadowRoot.getElementById("csatsor").style.display = opciok.length > 1 ? "" : "none";
    this.shadowRoot.getElementById("diktaltsor").style.display = ["diktalas", "atalany"].includes(f.elszamolas_mod) ? "" : "none";
    form.diktalt.checked = false;
    // Éves (elszámoló) leolvasás: fix díjas fióknál nincs értelme. A már rögzített állás így utólag is megjelölhető.
    this.shadowRoot.getElementById("evessor").style.display = f.fix_dij ? "none" : "";
    form.eves.checked = false;
    // Mérőcsere: a fő mérőn (H-nál a két regiszterrel), víznél az almérőn is – csak rendszergazda.
    this.shadowRoot.getElementById("cseresor").style.display = this._admin ? "" : "none";
    form.csere.checked = false;
    for (const n of ["regi_zaro", "uj_gyari", "regi_181", "regi_182", "uj_181", "uj_182"]) form[n].value = "";
    form.uj_kezdo.value = "0";
    this.shadowRoot.getElementById("cserehreg").hidden = !h;
    // Korrekciós leolvasás: csak saját szenzoros fióknál van értelme.
    this.shadowRoot.getElementById("korrsor").style.display = (f.szenzor_allasok || []).length ? "" : "none";
    form.korrekcio.checked = false;
    this.shadowRoot.getElementById("dered").innerHTML = "";
    this.shadowRoot.getElementById("megse").textContent = "Mégse";
    this._korrValt();
    this._csereValt();
    this._utolsoJelzes();
    this.shadowRoot.getElementById("dhiba").textContent = "";
    this._mentesAllapot();
    d.showModal();
  }

  // Korrekciós leolvasásnál a többi jelölés (szolgáltatói, éves, diktáltam, mérőcsere) nem választható.
  _korrValt() {
    const r = this.shadowRoot, form = r.getElementById("leolvform"), k = form.korrekcio.checked;
    for (const n of ["szolgaltatoi", "eves", "diktalt", "csere"]) {
      if (k) form[n].checked = false;
      form[n].disabled = k;
    }
    for (const id of ["szolgsor", "evessor", "diktaltsor", "cseresor"]) r.getElementById(id).classList.toggle("tiltva", k);
  }

  // A kiválasztott csatorna legutolsó állása a mező alatt (H-nál a regiszterekkel együtt).
  _utolsoJelzes() {
    const r = this.shadowRoot, form = r.getElementById("leolvform"), f = this._dfiok, ut = f?.utolso_allasok || {};
    const h = f?.dijszabas === "villany/h";
    const c = h ? "vetelezes" : form.csatorna.value || "vetelezes";
    const sor = (x, nev) => (x ? `${nev}${allas(x.allas)} (${nap(x.datum)})` : "");
    const reszek = h ? [sor(ut.h_teli, "1.81: "), sor(ut.h_nyari, "1.82: ")].filter(Boolean) : [sor(ut[c], "")].filter(Boolean);
    // A saját szenzor szerinti mostani állás is (ehhez veti össze a korrekciós leolvasást).
    const sz = Object.fromEntries((f?.szenzor_allasok || []).map((a) => [a.szerep, a.allas]));
    const szs = h ? [["h_teli", "1.81: "], ["h_nyari", "1.82: "]].filter(([x]) => sz[x] != null).map(([x, n]) => `${n}${SZAM.format(Math.round(sz[x] * 10) / 10)}`)
      : sz[c] != null ? [SZAM.format(Math.round(sz[c] * 10) / 10)] : [];
    r.getElementById("utolsoallas").textContent = (reszek.length ? `Legutóbb rögzítve: ${reszek.join(" · ")}` : "Ehhez a mérőhöz még nincs rögzített állás.")
      + (szs.length ? ` · saját szenzor szerint most: ${szs.join(" · ")}` : "");
  }

  // H-tarifa: a (rejtett) 1.8.0 mindig a két regiszter összege.
  _hSzamol() {
    const form = this.shadowRoot.getElementById("leolvform");
    const sz = (x) => (x.value === "" ? null : Number(x.value.replace(",", ".")));
    const t = sz(form.reg181), n = sz(form.reg182);
    form.allas.value = t !== null && n !== null ? String(Math.round((t + n) * 1000) / 1000) : "";
  }

  // Mentés csak akkor, ha valamelyik állás eltér az előtöltöttől (mérőcserénél: ha megvan a régi mérő záró állása).
  _mentesAllapot() {
    const r = this.shadowRoot, form = r.getElementById("leolvform"), k = this._dkezdo || {};
    const valt = form.csere.checked ? form.regi_zaro.value !== ""
      : form.eves.checked || ["allas", "reg181", "reg182"].some((n) => form[n].value !== "" && form[n].value !== (k[n] ?? ""));
    r.getElementById("leolvmentes").disabled = !valt;
  }

  _csereValt() {
    const r = this.shadowRoot, form = r.getElementById("leolvform"), f = this._dfiok;
    const csere = form.csere.checked;
    r.getElementById("cseremezok").hidden = !csere;
    r.getElementById("allasmezok").hidden = csere;
    form.allas.required = !csere && f?.dijszabas !== "villany/h";
    form.regi_zaro.required = csere;
    r.getElementById("leolvcim").textContent = `${csere ? "Mérőcsere" : "Mérőállás"} – ${f?.nev || ""}`;
    // Csere: a csatorna csak fő mérő vagy almérő lehet (a többi regiszter a fő mérővel cserélődik).
    if (csere && f) {
      const opc = [["vetelezes", f.kozmu === "viz" ? "Főmérő" : "Mérő"], ...(f.almero ? [["almero", "Locsolási almérő"]] : [])];
      form.csatorna.innerHTML = opc.map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
      r.getElementById("csatsor").style.display = opc.length > 1 ? "" : "none";
    }
  }

  _szamlaNyit(f) {
    if (!f) return;
    this._szfiok = f;
    const r = this.shadowRoot;
    const kozos = f.kozmu === "kozos";  // társasház: nincs számla, a kimutatás szerinti havi előírás
    r.getElementById("szamlacim").textContent = `${kozos ? "Előírás" : "Számla"} – ${f.nev}`;
    const form = r.getElementById("szamlaform");
    form.reset();
    form.kelte.value = new Date().toISOString().slice(0, 10);
    form.tipus.value = kozos ? "eloiras" : f.fix_dij ? "egyeb" : "resz";
    r.querySelectorAll("#szamlaform .merosor").forEach((el) => (el.style.display = f.fix_dij ? "none" : ""));
    r.getElementById("futosor").style.display = f.kozmu === "gaz" ? "" : "none";
    r.getElementById("szhiba").textContent = "";
    r.getElementById("feltolteredmeny").textContent = "";
    r.getElementById("feltoltsor").style.display = f.szamlamappa ? "" : "none";
    r.getElementById("nincsmappa").style.display = f.szamlamappa ? "none" : "";
    r.getElementById("szamladlg").showModal();
  }

  _kijeloltek(f) {
    return (f.szamlak || []).filter((x) => this._jelolt.has(`${f.sid}|${x.sorszam}`));
  }

  _torlesGomb(f) {
    const db = this._kijeloltek(f).length;
    return `<span data-torolsor="${f.sid}">
      <button type="button" class="veszely" data-torolkijelolt="${f.sid}"${db ? "" : " disabled"}>Kijelöltek törlése${db ? ` (${db})` : ""}</button>
      ${db ? `<button type="button" data-jelolesmegszunt="${f.sid}">Kijelölés megszüntetése</button>` : ""}</span>`;
  }

  _torlesGombKotes(fiokok) {
    const r = this.shadowRoot;
    r.querySelectorAll("[data-torolkijelolt]").forEach((el) => {
      el.onclick = () => this._torlesNyit(fiokok.find((f) => f.sid === el.dataset.torolkijelolt));
    });
    r.querySelectorAll("[data-jelolesmegszunt]").forEach((el) => {
      el.onclick = () => {
        [...this._jelolt].filter((k) => k.startsWith(el.dataset.jelolesmegszunt + "|")).forEach((k) => this._jelolt.delete(k));
        this._rajzol();
      };
    });
  }

  // Törlés megerősítése: a kijelölt számlák listája; a beolvasottakra külön figyelmeztetés.
  _torlesNyit(f) {
    const lista = f ? this._kijeloltek(f) : [];
    if (!lista.length) return;
    this._tfiok = f;
    const r = this.shadowRoot;
    const beolvasott = lista.filter((x) => !x.kezi).length;
    r.getElementById("torlescim").textContent = `${lista.length} számla törlése – ${f.nev}`;
    r.getElementById("torleslista").innerHTML = lista.map((x) =>
      `<li>${nap(x.kelte)} · ${esc(x.sorszam)} · ${x.osszeg === null ? "–" : ft(Number(x.osszeg))}${x.kezi ? ' <span class="cimkeszalag">kézi</span>' : ""}</li>`).join("");
    r.getElementById("torlesfigy").innerHTML =
      "A számlákkal együtt a belőlük jött befizetés és mérőállás is törlődik. Ez nem vonható vissza."
      + (beolvasott ? `<br><b>${beolvasott} számla a Díjnet-mappából jött:</b> ezek csak a „Számlák újraolvasása” szolgáltatással jönnek vissza.` : "");
    r.getElementById("torleshiba").textContent = "";
    r.getElementById("torlesdlg").showModal();
  }

  _lezarNyit(f) {
    const r = this.shadowRoot;
    const d = r.getElementById("lezardlg");
    this._lfiok = f;
    const vissza = !!f.megszunt;
    r.getElementById("lezarcim").textContent = vissza ? `${f.nev} – lezárás visszavonása` : `${f.nev} – fiók lezárása`;
    r.getElementById("lezarszoveg").innerHTML = vissza
      ? `A fiók ${nap(f.megszunt.datum)} óta lezárt. Visszavonáskor a végleolvasás és a végelszámolás törlődik, a fiók újra számol.`
      : f.fix_dij
        ? "Költözés, lemondás vagy szolgáltatóváltás: a díj a lezárás napjáig jár; az utolsó (töredék) időszakról a szokásos ütem szerint, utólag jön a végszámla, utána nincs több. Visszavonható."
        : "Költözés, lemondás vagy szolgáltatóváltás: a megadott napon végleolvasás, a fiók számolása ott megáll, az utolsó időszak lezárul, a kártya a végelszámolást mutatja (az utolsó éves elszámolás óta mért díj és a befizetések egyenlege). Visszavonható.";
    r.getElementById("lezarmezok").hidden = vissza;
    // Fix díjnál (pl. hulladékszállítás) nincs mérő: csak a lezárás napja kell.
    r.getElementById("lezarallas").closest("label").hidden = !!f.fix_dij;
    const most = new Date();
    r.getElementById("lezardatum").value = `${most.getFullYear()}-${String(most.getMonth() + 1).padStart(2, "0")}-${String(most.getDate()).padStart(2, "0")}`;
    r.getElementById("lezarallas").value = "";
    r.getElementById("lezarhiba").textContent = "";
    r.getElementById("lezarok").textContent = vissza ? "Visszavonás" : "Lezárás";
    d.showModal();
  }

  // Számla kézi javítása: csak a fájlban nem szereplő adatok (fizetés, határidő, megjegyzés).
  _javitasNyit(sid, sorszam) {
    const hs = Array.isArray(this._adat) ? this._adat : (this._adat?.otthonok || this._adat?.haztartasok || []);
    const f = hs.flatMap((h) => h.fiokok).find((x) => x.sid === sid);
    const x = f?.szamlak?.find((y) => y.sorszam === sorszam);
    if (!x) return;
    const r = this.shadowRoot, z = x.fizetes || {};
    this._jav = { sid, sorszam, eredeti: { fizetve: !!z.fizetve, datum: z.datum || "" } };
    r.getElementById("javszoveg").textContent = `${f.nev} · ${sorszam} · kelte ${nap(x.kelte)} · ${x.osszeg === null ? "–" : ft(Number(x.osszeg))}`;
    r.getElementById("javfiz").checked = !!z.fizetve;
    r.getElementById("javfiz").disabled = !!z.nincs_fizetendo;
    r.getElementById("javdatum").value = z.datum || "";
    r.getElementById("javhatarido").value = x.javitas?.hatarido || x.hatarido || z.hatarido || "";
    r.getElementById("javmegj").value = x.javitas?.megjegyzes || "";
    r.getElementById("javdijnet").hidden = z.forras !== "kezi";
    r.getElementById("javhiba").textContent = "";
    r.getElementById("javdlg").showModal();
  }

  _javitasKezelo() {
    const r = this.shadowRoot, d = r.getElementById("javdlg");
    r.addEventListener("click", (ev) => {
      const b = ev.target.closest?.("[data-javit]");
      if (b) { const i = b.dataset.javit.indexOf("|"); this._javitasNyit(b.dataset.javit.slice(0, i), b.dataset.javit.slice(i + 1)); }
    });
    r.getElementById("javmegse").addEventListener("click", () => d.close());
    r.getElementById("javfiz").addEventListener("change", (ev) => {
      const dm = r.getElementById("javdatum");
      if (ev.target.checked && !dm.value) dm.value = new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
    });
    const kuld = async (dijnet) => {
      const j = this._jav, fiz = r.getElementById("javfiz").checked, datum = r.getElementById("javdatum").value;
      const msg = { type: "hu_rezsi/szamla_javitas", entry_id: this._entryId(j.sid), sid: j.sid, sorszam: j.sorszam,
        hatarido: r.getElementById("javhatarido").value || null, megjegyzes: r.getElementById("javmegj").value };
      // A fizetést csak akkor írjuk, ha változott (különben a Díjnet szerinti állapot maradjon).
      if (dijnet) msg.fizetve = null;
      else if (fiz !== j.eredeti.fizetve || (fiz && datum !== j.eredeti.datum)) Object.assign(msg, { fizetve: fiz, datum: fiz ? datum || null : null });
      r.getElementById("javment").disabled = true;
      try {
        await this._hass.callWS(msg);
        d.close();
        this._betolt();
        this._kesoBetolt(3000);  // a háttérszámolás (egyenleg, beszámítás) után még egyszer
      } catch (err) {
        r.getElementById("javhiba").textContent = err.message || String(err);
      } finally {
        r.getElementById("javment").disabled = false;
      }
    };
    r.getElementById("javment").addEventListener("click", () => kuld(false));
    r.getElementById("javdijnet").addEventListener("click", () => kuld(true));
  }

  _lezarKezelo() {
    const r = this.shadowRoot;
    const d = r.getElementById("lezardlg");
    r.getElementById("lezarmegse").onclick = () => d.close();
    r.getElementById("lezarok").onclick = async () => {
      const f = this._lfiok;
      const adat = { device_id: f.device_id };
      if (f.megszunt) adat.visszavonas = true;
      else {
        adat.datum = r.getElementById("lezardatum").value;
        const a = r.getElementById("lezarallas").value.replace(",", ".");
        if (a !== "") adat.zaro_allas = Number(a);
      }
      try {
        await this._hass.callService("hu_rezsi", "fiok_lezarasa", adat);
      } catch (e) {
        r.getElementById("lezarhiba").textContent = e.message || String(e);
        return;
      }
      d.close();
      setTimeout(() => this._betolt(), 1500);
    };
  }

  _torlesKezelo() {
    const r = this.shadowRoot;
    const d = r.getElementById("torlesdlg");
    r.getElementById("torlesmegse").onclick = () => d.close();
    r.getElementById("torlesok").onclick = async () => {
      const f = this._tfiok;
      const hibak = [];
      for (const x of this._kijeloltek(f)) {
        try {
          await this._hass.callService("hu_rezsi", "szamla_torles", { device_id: f.device_id, sorszam: x.sorszam });
          this._jelolt.delete(`${f.sid}|${x.sorszam}`);
        } catch (e) {
          hibak.push(`${x.sorszam}: ${e.message || e}`);
        }
      }
      if (hibak.length) {
        r.getElementById("torleshiba").textContent = hibak.join("; ");
        return;
      }
      d.close();
      setTimeout(() => this._betolt(), 1500);
    };
  }

  _szamlaKezelo() {
    const r = this.shadowRoot;
    const d = r.getElementById("szamladlg");
    const form = r.getElementById("szamlaform");
    r.getElementById("szmegse").addEventListener("click", () => d.close());
    // Feltöltés: HA /api/file_upload → hu_rezsi.szamla_feltoltes (a fiók számlamappájába, azonnali feldolgozás).
    form.fajl.addEventListener("change", async () => {
      const f = this._szfiok;
      const fajl = form.fajl.files[0];
      const ki = r.getElementById("feltolteredmeny");
      if (!fajl) return;
      ki.textContent = "Feltöltés és feldolgozás…";
      try {
        const adat = new FormData();
        adat.append("file", fajl);
        const valasz = await this._hass.fetchWithAuth("/api/file_upload", { method: "POST", body: adat });
        if (!valasz.ok) throw new Error(`a feltöltés nem sikerült (${valasz.status})`);
        const { file_id } = await valasz.json();
        const v = await this._hass.callWS({
          type: "call_service", domain: "hu_rezsi", service: "szamla_feltoltes",
          service_data: { device_id: f.device_id, file_id }, return_response: true,
        });
        const e = v.response || {};
        if (e.rogzitve) {
          ki.innerHTML = `<span class="ok">✓ Beolvasva:</span> ${esc(e.sorszam)} · ${nap(e.kelte)} · ${ft(e.osszeg)}`;
          setTimeout(() => { d.close(); this._betolt(); }, 2500);
        } else if (e.mar_volt) {
          ki.textContent = `Ez a számla (${e.sorszam}) már szerepelt, nem rögzítettem újra.`;
        } else if (e.felismert) {
          ki.textContent = `A számlát felismertem (${e.sorszam}), de nem ehhez a fiókhoz tartozik (más mérő). A fájl a mappában maradt.`;
        } else {
          ki.innerHTML = `A fájl (${esc(e.fajl)}) a mappába került, de nem ismertem fel – add meg az adatait lent kézzel${this._aiLehet() && /\.pdf$/i.test(e.fajl || "")
            ? `, vagy <button type="button" class="linkgomb" data-aifajl="${esc(`${f.sid}|${e.fajl}`)}">olvastasd ki AI-val ›</button>` : ""}.`;
          ki.querySelector("[data-aifajl]")?.addEventListener("click", (ev) => { ev.stopPropagation(); d.close(); this._aiNyit(f.sid, e.fajl); });
        }
      } catch (err) {
        ki.textContent = `Hiba: ${err.message || err}`;
      }
      form.fajl.value = "";
    });
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = this._szfiok;
      const adat = { device_id: f.device_id, kelte: form.kelte.value, osszeg: Number(form.osszeg.value), tipus: form.tipus.value };
      if (form.sorszam.value.trim()) adat.sorszam = form.sorszam.value.trim();
      if (form.hatarido.value) adat.hatarido = form.hatarido.value;
      if (form.tol.value || form.ig.value) Object.assign(adat, { idoszak_tol: form.tol.value, idoszak_ig: form.ig.value });
      if (!f.fix_dij && form.zaro.value !== "") Object.assign(adat, { zaro_allas: Number(form.zaro.value), leolvasott: form.leolvasott.checked });
      if (f.kozmu === "gaz" && form.futo.value !== "") adat.futoertek = Number(form.futo.value);
      try {
        const v = await this._hass.callWS({
          type: "call_service", domain: "hu_rezsi", service: "szamla_rogzites", service_data: adat, return_response: true,
        });
        if (v?.response?.kihagyott_meroallas)
          alert("A számla rögzítve, de a záró mérőállás kimaradt: ellentmond a meglévő mérőállásoknak (a mérő nem mehet visszafelé), vagy azon a napon nincs aktív mérő.");
        d.close();
        setTimeout(() => this._betolt(), 1500);
      } catch (e) {
        r.getElementById("szhiba").textContent = e.message || String(e);
      }
    });
  }

  // ---- Mentés és visszaállítás (csak admin) ----
  _mentesKezelo() {
    const r = this.shadowRoot, d = r.getElementById("mentesdlg");
    if (!d) return;
    const el = (id) => r.getElementById(id);
    el("mentesbezar").addEventListener("click", () => d.close());
    d.addEventListener("click", (ev) => ev.target === d && d.close());
    const ered = (html) => { el("mentesered").innerHTML = html; };
    el("autobezarasment").addEventListener("click", async () => {
      const gomb = el("autobezarasment"); // az esemény célpontja await után a shadow DOM-ban már nem elérhető
      gomb.disabled = true;
      try {
        const v = await this._hass.callWS({ type: "hu_rezsi/panel_beallitas", beallitas: { auto_bezaras_mp: Number(el("autobezaras").value || 0) } });
        if (this._adat) this._adat.panel_beallitas = v;
        el("autobezaras").value = v.auto_bezaras_mp;
        el("autobezarasered").innerHTML = `<span class="ok">✓ Mentve:</span> ${v.auto_bezaras_mp ? `${v.auto_bezaras_mp} másodperc` : "soha nem zárul be magától"}.`;
      } catch (err) {
        el("autobezarasered").innerHTML = `<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`;
      }
      gomb.disabled = false;
    });
    el("aiment").addEventListener("click", async () => {
      const gomb = el("aiment");
      gomb.disabled = true;
      try {
        const be = el("aibeolvasas").checked;
        if (be && !this._adat?.panel_beallitas?.ai_beolvasas && !window.confirm(this._aiBeleegyezesSzoveg())) { el("aibeolvasas").checked = false; gomb.disabled = false; return; }
        const v = await this._hass.callWS({ type: "hu_rezsi/panel_beallitas", beallitas: { ai_beolvasas: be, ai_entitas: el("aientitas").value || null } });
        if (this._adat) this._adat.panel_beallitas = v;
        el("aiered").innerHTML = `<span class="ok">✓ Mentve:</span> ${v.ai_beolvasas ? "bekapcsolva" : "kikapcsolva"}.`;
        this._rajzol?.();
      } catch (err) {
        el("aiered").innerHTML = `<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`;
      }
      gomb.disabled = false;
    });
    el("ertment").addEventListener("click", async () => {
      const gomb = el("ertment");
      gomb.disabled = true;
      try {
        const celok = [...r.querySelectorAll("#ertcelok input:checked")].map((x) => x.value);
        const ob = [...r.querySelectorAll("#ertotthonok input")], oj = ob.filter((x) => x.checked).map((x) => x.value);
        if (ob.length && !oj.length) throw new Error("Válassz legalább egy otthont.");
        const v = await this._hass.callWS({ type: "hu_rezsi/panel_beallitas", beallitas: {
          hatarido_otthonok: oj.length === ob.length ? [] : oj,
          hatarido_ertesites: el("ertbe").checked, hatarido_napok: Number(el("ertnapok").value || 3),
          hatarido_ido: el("ertido").value || "09:00", hatarido_celok: celok } });
        if (this._adat) this._adat.panel_beallitas = v;
        el("ertered").innerHTML = `<span class="ok">✓ Mentve:</span> ${v.hatarido_ertesites
          ? `bekapcsolva – ${v.hatarido_napok} nappal a határidő előtt, ${esc(v.hatarido_ido)}-kor, ${v.hatarido_celok.length} telefonra` : "kikapcsolva"}; otthonok: ${(v.hatarido_otthonok || []).length ? (this._adat?.haztartasok || []).filter((h) => v.hatarido_otthonok.includes(h.entry_id)).map((h) => esc(h.nev)).join(", ") : "mindegyik"}.`;
        this._fejlecFrissit();
      } catch (err) {
        el("ertered").innerHTML = `<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`;
      }
      gomb.disabled = false;
    });
    el("ertproba").addEventListener("click", async () => {
      const gomb = el("ertproba");
      const celok = [...r.querySelectorAll("#ertcelok input:checked")].map((x) => x.value);
      if (!celok.length) { el("ertered").innerHTML = `<span class="figyszoveg">Válassz legalább egy telefont.</span>`; return; }
      gomb.disabled = true;
      el("ertered").textContent = "Küldés…";
      try {
        const v = await this._hass.callWS({ type: "hu_rezsi/ertesites_proba", celok });
        el("ertered").innerHTML = `<span class="ok">✓ Elküldve:</span> ${esc(v.szoveg).replace(/\n/g, "<br>")}`;
      } catch (err) {
        el("ertered").innerHTML = `<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`;
      }
      gomb.disabled = false;
    });
    el("mentesmost").addEventListener("click", async (ev) => {
      const gomb = ev.currentTarget;  // az await után az ev már nem megbízható (a lista újrarajzolása közben)
      gomb.disabled = true;
      ered("Mentés készül…");
      try {
        const otthon = el("mentesotthon").value;
        const v = await this._hass.callWS({ type: "call_service", domain: "hu_rezsi", service: "mentes", return_response: true,
          service_data: { szamlak: el("mentesszamlak").checked, ...(otthon ? { otthon } : {}) } });
        const e = v.response || {};
        ered(`<span class="ok">✓ Kész:</span> ${esc(e.fajl)} · ${meret(e.meret)} · ${esc((e.otthonok || []).join(", "))}${e.szamlak ? ` · ${e.szamlak} számla-fájl` : ""}<br>${(e.helyek || []).map((h) =>
          h.ok ? `✓ ${esc(h.hely)}` : `<span class="figyszoveg">✗ ${esc(h.hely)}: ${esc(h.hiba)}</span>`).join(" · ")}`);
        await this._mentesLista();
      } catch (err) {
        ered(`<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`);
      } finally {
        gomb.disabled = false;
        const most = el("mentesmost");
        if (most) most.disabled = false;
      }
    });
    // Mentési helyek: a táblázat a this._mentesB (beállítás) másolatát szerkeszti, a „Beállítások mentése” küldi el.
    el("helytabla").addEventListener("input", (ev) => {
      const i = +ev.target.dataset.hely, k = ev.target.dataset.mezo;
      if (!this._mentesB || Number.isNaN(i) || !k) return;
      this._mentesB.helyek[i][k] = k === "aktiv" ? ev.target.checked : k === "megtart" ? +ev.target.value : ev.target.value;
    });
    el("helytabla").addEventListener("click", (ev) => {
      const t = ev.target.closest("[data-helytorol]");
      if (!t || !this._mentesB) return;
      this._mentesB.helyek.splice(+t.dataset.helytorol, 1);
      this._helyRajzol();
    });
    el("helyhozzaad").addEventListener("click", () => {
      const alap = el("helyjelolt").value, alm = el("helyalmappa").value.trim().replace(/^\/+|\/+$/g, "");
      if (!alap || !this._mentesB) return;
      const utvonal = alm ? `${alap}/${alm}` : alap;
      if (this._mentesB.helyek.some((h) => h.utvonal === utvonal)) return;
      const jelolt = (this._helyJeloltek || []).find((x) => x.utvonal === alap);
      this._mentesB.helyek.push({ nev: jelolt?.halozati ? `${jelolt.nev} (hálózati)` : (jelolt?.nev || alap), utvonal, megtart: 12, aktiv: true });
      this._helyRajzol();
    });
    el("utemgyak").addEventListener("change", () => { el("utemnapcimke").hidden = el("utemgyak").value !== "heti"; });
    el("beallitasment").addEventListener("click", async (ev) => {
      if (!this._mentesB) return;
      const gomb = ev.currentTarget;
      gomb.disabled = true;
      try {
        const b = { helyek: this._mentesB.helyek, utemezes: { gyakorisag: el("utemgyak").value, nap: +el("utemnap").value, ido: el("utemido").value, szamlak: el("utemszamlak").checked } };
        this._mentesB = await this._hass.callWS({ type: "hu_rezsi/mentes_beallitas", beallitas: b });
        ered(`<span class="ok">✓ Beállítások mentve.</span>`);
        await this._mentesLista();
      } catch (err) {
        ered(`<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`);
      } finally {
        gomb.disabled = false;
      }
    });
    el("menteslista").addEventListener("click", async (ev) => {
      const le = ev.target.closest("[data-letolt]"), vi = ev.target.closest("[data-visszaallit]");
      if (le) {
        const [hely, fajl] = le.dataset.letolt.split("|");
        const v = await this._hass.fetchWithAuth(`/api/hu_rezsi/mentes/${hely}/${encodeURIComponent(fajl)}`);
        if (!v.ok) { ered(`<span class="figyszoveg">A letöltés nem sikerült (${v.status}).</span>`); return; }
        const a = document.createElement("a");
        a.href = URL.createObjectURL(await v.blob());
        a.download = fajl;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      }
      if (vi) {
        const [hely, fajl] = vi.dataset.visszaallit.split("|");
        await this._mentesVisszaallit({ fajl, hely: +hely }, vi.dataset.otthonok);
      }
    });
    el("hamentesek").addEventListener("toggle", () => { if (el("hamentesek").open) this._haMentesLista(); });
    el("halista").addEventListener("click", async (ev) => {
      const t = ev.target.closest("[data-hakiolvas]");
      if (!t) return;
      t.disabled = true;
      ered("Kiolvasás a Home Assistant-mentésből… (nagy mentésnél egy-két perc)");
      try {
        const e = await this._hass.callWS({ type: "hu_rezsi/ha_mentesbol", backup_id: t.dataset.hakiolvas });
        ered(`<span class="ok">✓ Rezsikövető-mentés készült a(z) „${esc(e.ha_mentes)}” HA-mentésből:</span> ${esc(e.fajl)} · ${esc((e.otthonok || []).join(", "))}${e.szamlak ? ` · ${e.szamlak} számla-fájl` : ""} – a Mentések listájából visszaállítható.`);
        await this._mentesLista();
      } catch (err) {
        ered(`<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`);
      }
      t.disabled = false;
    });
    el("mentesfeltolt").addEventListener("change", async (ev) => {
      const fajl = ev.target.files[0];
      if (!fajl) return;
      ered("Feltöltés…");
      try {
        const adat = new FormData();
        adat.append("file", fajl);
        const v = await this._hass.fetchWithAuth("/api/file_upload", { method: "POST", body: adat });
        if (!v.ok) throw new Error(`a feltöltés nem sikerült (${v.status})`);
        const { file_id } = await v.json();
        await this._mentesVisszaallit({ file_id }, fajl.name);
      } catch (err) {
        ered(`<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`);
      }
      ev.target.value = "";
    });
    // Szenzor-hozzárendelés
    const sd = el("szenzordlg");
    el("szenzorbezar").addEventListener("click", () => sd.close());
    el("szenzormegse").addEventListener("click", () => sd.close());
    el("szenzorment").addEventListener("click", async (ev) => {
      const csere = [...el("szenzortabla").querySelectorAll("input[data-sor]")]
        .map((i) => ({ i, sor: this._szenzorSorok[+i.dataset.sor] }))
        .filter(({ i, sor }) => i.value.trim() !== sor.entity_id)
        .map(({ i, sor }) => ({ sid: sor.sid, kulcs: sor.kulcs, idx: sor.idx, uj: i.value.trim() }));
      if (!csere.length) { sd.close(); return; }
      const gomb = ev.currentTarget;
      gomb.disabled = true;
      try {
        const v = await this._hass.callWS({ type: "hu_rezsi/szenzor_csere", entry_id: this._szenzorEntry, csere });
        el("szenzorered").innerHTML = `<span class="ok">✓ ${v.modositott} fiók módosítva</span> – az otthon újraszámol.`;
        setTimeout(() => { sd.close(); this._betolt(); }, 2000);
      } catch (err) {
        el("szenzorered").innerHTML = `<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`;
      } finally {
        gomb.disabled = false;
      }
    });
    this._egyszer("deleg3", () => this.shadowRoot.addEventListener("click", (ev) => {
      const t = ev.target.closest?.("[data-szenzorok]");
      if (t) this._szenzorNyit(t.dataset.szenzorok);
    }));
  }

  // Értesítés a határidő előtt (2.4.0b1): a fejléc telefon ikonja, ha be van kapcsolva.
  _ertesitesIkon() {
    const pb = this._adat?.panel_beallitas;
    if (!pb?.hatarido_ertesites) return "";
    const n = (pb.hatarido_celok || []).length;
    const cim = `Értesítés a mobilra: ${pb.hatarido_napok} nappal a fizetési határidő előtt, ${pb.hatarido_ido}-kor, ${n} telefonra`;
    return this._hass?.user?.is_admin
      ? `<button class="ikongomb" id="ertesitesgomb" title="${esc(cim)} – beállítás" aria-label="${esc(cim)}"><ha-icon icon="mdi:cellphone-message"></ha-icon></button>`
      : `<span class="ikongomb fejjel" title="${esc(cim)}" aria-label="${esc(cim)}"><ha-icon icon="mdi:cellphone-message"></ha-icon></span>`;
  }

  _fejlecFrissit() {
    // csak a fejléc ikonja változik: a nyitott ablakot nem rajzoljuk újra
    const fej = this.shadowRoot.querySelector(".fej");
    if (!fej) return;
    fej.querySelector("#ertesitesgomb, .fejjel")?.remove();
    const t = document.createElement("template");
    t.innerHTML = this._ertesitesIkon().trim();
    const uj = t.content.firstElementChild;
    if (uj) {
      fej.insertBefore(uj, fej.querySelector("#mentesgomb") || fej.querySelector("#frissit"));
      uj.addEventListener?.("click", () => uj.id === "ertesitesgomb" && this._mentesNyit("ertesites"));
    }
  }

  _ertesitoCelok(valasztott) {
    const szolg = Object.keys(this._hass?.services?.notify || {});
    const lista = [...new Set([...szolg.filter((k) => k.startsWith("mobile_app_")).map((k) => `notify.${k}`), ...valasztott])].sort();
    const eszkozNev = (cel) => {
      const slug = cel.replace(/^notify\.mobile_app_/, "");
      const d = Object.values(this._hass?.devices || {}).find((x) => (x.name_by_user || x.name || "").toLowerCase().normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") === slug);
      return d ? (d.name_by_user || d.name) : slug.replace(/_/g, " ");
    };
    if (!lista.length) return `<span class="kicsi">Nincs telefon: telepítsd a Home Assistant mobilalkalmazást, és jelentkezz be vele.</span>`;
    return `<span class="kicsi">Telefonok:</span>` + lista.map((c) => `<label class="jelolo"><input type="checkbox" value="${esc(c)}" ${valasztott.includes(c) ? "checked" : ""}> ${esc(eszkozNev(c))}${szolg.includes(c.slice(7)) ? "" : " (nem elérhető)"}</label>`).join("");
  }

  async _mentesNyit(fokusz) {
    const r = this.shadowRoot, d = r.getElementById("mentesdlg");
    const hazak = this._adat?.haztartasok || [];
    r.getElementById("mentesotthon").innerHTML = `<option value="">Minden otthon</option>${hazak.map((h) => `<option value="${esc(h.entry_id)}">${esc(h.nev)}</option>`).join("")}`;
    r.getElementById("mentesered").innerHTML = "";
    r.getElementById("autobezaras").value = this._autoMp;
    r.getElementById("autobezarasered").innerHTML = "";
    r.getElementById("nezetbeall").value = this._nezetBeall;
    r.getElementById("nezetbeall").onchange = (ev) => { this._nezetBeall = ev.target.value; this._mentLap(); this._rajzol(); this._mentesNyit(); };
    {
      const pb = this._adat?.panel_beallitas || {};
      r.getElementById("aibeolvasas").checked = !!pb.ai_beolvasas;
      r.getElementById("aientitas").innerHTML = `<option value="">az első elérhető</option>${this._aiEntitasok().map((e) =>
        `<option value="${esc(e.id)}" ${e.id === pb.ai_entitas ? "selected" : ""}>${esc(e.nev)}</option>`).join("")}`;
      r.getElementById("aiered").innerHTML = "";
      r.getElementById("ertbe").checked = !!pb.hatarido_ertesites;
      r.getElementById("ertnapok").value = pb.hatarido_napok ?? 3;
      r.getElementById("ertido").value = pb.hatarido_ido || "09:00";
      r.getElementById("ertcelok").innerHTML = this._ertesitoCelok(pb.hatarido_celok || []);
      {
        const hz = this._adat?.haztartasok || [], val = pb.hatarido_otthonok || [];
        r.getElementById("ertotthonok").innerHTML = hz.length > 1 ? `<span class="kicsi">Otthonok (értesítés és hangutasítás):</span>`
          + hz.map((h) => `<label class="jelolo"><input type="checkbox" value="${esc(h.entry_id)}" ${!val.length || val.includes(h.entry_id) ? "checked" : ""}> ${esc(h.nev)}</label>`).join("") : "";
      }
      r.getElementById("ertered").innerHTML = "";
    }
    if (!d.open) d.showModal();
    if (fokusz === "ertesites") {
      r.getElementById("panelbeall").open = true;
      r.getElementById("ertblokk")?.scrollIntoView({ block: "center" });
      r.getElementById("ertbe")?.focus();
    }
    try {
      this._helyJeloltek = await this._hass.callWS({ type: "hu_rezsi/mentes_helyek" });
      r.getElementById("helyjelolt").innerHTML = this._helyJeloltek.map((x) =>
        `<option value="${esc(x.utvonal)}">${esc(x.utvonal)}${x.halozati ? " (hálózati)" : ""}${x.szabad_gb != null ? ` – ${x.szabad_gb} GB szabad` : ""}</option>`).join("");
    } catch (err) { /* a lista nélkül is használható */ }
    await this._mentesLista();
  }

  _helyRajzol() {
    const b = this._mentesB;
    this.shadowRoot.getElementById("helytabla").innerHTML = `<table class="menteslista"><thead><tr><th>Be</th><th>Név</th><th>Hely</th><th>Megtart</th><th></th></tr></thead><tbody>${b.helyek.map((h, i) =>
      `<tr><td><input type="checkbox" data-hely="${i}" data-mezo="aktiv"${h.aktiv ? " checked" : ""}></td>
        <td><input type="text" data-hely="${i}" data-mezo="nev" value="${esc(h.nev)}"></td><td class="kicsi">${esc(h.utvonal)}</td>
        <td><input type="number" min="0" max="1000" data-hely="${i}" data-mezo="megtart" value="${h.megtart}" title="ennyi legutóbbi mentés marad (0 = mind)"></td>
        <td>${b.helyek.length > 1 ? `<button type="button" class="linkgomb" data-helytorol="${i}">törlés</button>` : ""}</td></tr>`).join("")}</tbody></table>`;
  }

  async _mentesLista() {
    const r = this.shadowRoot, lista = r.getElementById("menteslista");
    lista.innerHTML = `<div class="kicsi">Betöltés…</div>`;
    try {
      const v = await this._hass.callWS({ type: "hu_rezsi/mentesek" });
      this._mentesB = JSON.parse(JSON.stringify(v.beallitas));
      this._helyRajzol();
      const u = this._mentesB.utemezes;
      r.getElementById("utemgyak").value = u.gyakorisag;
      r.getElementById("utemnap").value = String(u.nap);
      r.getElementById("utemido").value = u.ido;
      r.getElementById("utemszamlak").checked = !!u.szamlak;
      r.getElementById("utemnapcimke").hidden = u.gyakorisag !== "heti";
      const ut = this._mentesB.utolso;
      r.getElementById("utolsomentes").innerHTML = ut ? `Utolsó ütemezett mentés: ${new Date(ut.ido).toLocaleString("hu-HU")} – ${ut.ok ? `<span class="ok">sikeres</span> (${esc(ut.fajl)})` : `<span class="figyszoveg">hiba: ${esc(ut.hiba)}</span>`}` : "Ütemezett mentés még nem futott.";
      lista.innerHTML = v.mentesek.length ? `<table class="menteslista"><thead><tr><th>Készült</th><th>Otthonok</th><th>Méret</th><th>Hol</th><th></th></tr></thead><tbody>${v.mentesek.map((m) =>
        `<tr><td>${m.keszult ? new Date(m.keszult).toLocaleString("hu-HU", { dateStyle: "short", timeStyle: "short" }) : esc(m.fajl)}</td>
          <td>${m.hiba ? `<span class="figyszoveg">${esc(m.hiba)}</span>` : esc((m.otthonok || []).join(", "))}${m.szamlak ? ` <span class="kicsi">· ${m.szamlak} számla</span>` : ""}${/_hamentes-/.test(m.fajl) ? ` <span class="kicsi">· HA-mentésből</span>` : ""}</td>
          <td>${meret(m.meret)}</td><td class="kicsi">${esc(m.helyek.map((h) => h.nev).join(", "))}</td>
          <td class="mentesgombok"><button type="button" class="linkgomb" data-letolt="${m.helyek[0].idx}|${esc(m.fajl)}">Letöltés</button>
            ${m.hiba ? "" : `<button type="button" class="linkgomb" data-visszaallit="${m.helyek[0].idx}|${esc(m.fajl)}" data-otthonok="${esc((m.otthonok || []).join(", "))}">Visszaállítás</button>`}</td></tr>`).join("")}</tbody></table>`
        : `<div class="kicsi">Még nincs mentés.</div>`;
    } catch (err) {
      lista.innerHTML = `<div class="figyszoveg">${esc(err.message || err)}</div>`;
    }
  }

  async _haMentesLista() {
    const el = this.shadowRoot.getElementById("halista");
    el.innerHTML = `<div class="kicsi">Betöltés…</div>`;
    try {
      const v = await this._hass.callWS({ type: "hu_rezsi/ha_mentesek" });
      el.innerHTML = v.length ? `<table class="menteslista"><thead><tr><th>Készült</th><th>Név</th><th>Hol</th><th></th></tr></thead><tbody>${v.slice(0, 25).map((b) =>
        `<tr><td>${new Date(b.datum).toLocaleString("hu-HU", { dateStyle: "short", timeStyle: "short" })}</td><td>${esc(b.nev)}</td>
          <td class="kicsi">${b.helyek.map((h) => `${esc(h.agent_id.replace("hassio.local", "helyi").replace("cloud.cloud", "Nabu Casa"))} · ${meret(h.meret)}${h.titkositott ? " · titkosított" : ""}`).join("<br>")}</td>
          <td class="mentesgombok"><button type="button" class="linkgomb" data-hakiolvas="${esc(b.backup_id)}">Kiolvasás</button></td></tr>`).join("")}</tbody></table>`
        : `<div class="kicsi">Nincs Home Assistant-mentés.</div>`;
    } catch (err) {
      el.innerHTML = `<div class="figyszoveg">${esc(err.message || err)}</div>`;
    }
  }

  async _mentesVisszaallit(forras, leiras) {
    const r = this.shadowRoot;
    if (!confirm(`Visszaállítás: ${leiras}\n\nA mentés otthonai ÚJ otthonként jönnek létre (a meglévőket nem írja felül; névütközésnél „(visszaállítva)” utótaggal). A számla-fájlok csak oda kerülnek vissza, ahol még nincsenek. Folytatod?`)) return;
    r.getElementById("mentesered").innerHTML = "Visszaállítás…";
    try {
      const v = await this._hass.callWS({ type: "call_service", domain: "hu_rezsi", service: "visszaallitas", return_response: true, service_data: forras });
      const e = v.response || {};
      r.getElementById("mentesered").innerHTML = `<span class="ok">✓ Visszaállítva:</span> ${(e.otthonok || []).map((o) =>
        `${esc(o.nev)} (${o.fiokok} fiók/rendszer${o.szamlak_kiirt ? `, ${o.szamlak_kiirt} számla-fájl visszaírva` : ""}${o.szamlak_mar_megvolt ? `, ${o.szamlak_mar_megvolt} már megvolt` : ""})${(o.email_jelszo_kell || []).length
          ? ` – <span class="figyszoveg">add meg újra az e-mail fiók jelszavát (${(o.email_jelszo_kell || []).map(esc).join(", ")}): Beállítások → Eszközök és szolgáltatások → Rezsikövető → ${esc(o.nev)} → az e-mail fiók → Újrakonfigurálás</span>` : ""}${o.hianyzo_szenzorok
          ? ` – <span class="figyszoveg">${o.hianyzo_szenzorok} szenzor nem található</span> <button type="button" class="linkgomb" data-szenzorok="${esc(o.entry_id)}">Szenzorok hozzárendelése ›</button>` : ""}`).join("; ")}`;
      await this._mentesLista();
      setTimeout(() => this._betolt(), 3000);
    } catch (err) {
      r.getElementById("mentesered").innerHTML = `<span class="figyszoveg">Hiba: ${esc(err.message || err)}</span>`;
    }
  }

  async _szenzorNyit(entryId) {
    const r = this.shadowRoot, d = r.getElementById("szenzordlg");
    this._szenzorEntry = entryId;
    r.getElementById("szenzorered").innerHTML = "";
    r.getElementById("szenzortabla").innerHTML = `<div class="kicsi">Betöltés…</div>`;
    if (!d.open) d.showModal();
    try {
      const v = await this._hass.callWS({ type: "hu_rezsi/szenzor_lista", entry_id: entryId });
      this._szenzorSorok = v.sorok;
      r.getElementById("szenzorcim").textContent = `Szenzorok hozzárendelése – ${v.otthon}`;
      r.getElementById("szenzorjeloltek").innerHTML = v.jeloltek.map((j) => `<option value="${esc(j.entity_id)}">${esc(j.nev)}${j.egyseg ? ` (${esc(j.egyseg)})` : ""}</option>`).join("");
      r.getElementById("szenzortabla").innerHTML = v.sorok.length ? `<table class="menteslista szenzortabla"><thead><tr><th>Fiók</th><th>Mire való</th><th>Szenzor (mentéskor)</th><th>Új szenzor</th></tr></thead><tbody>${v.sorok.map((s, i) =>
        `<tr class="${s.letezik ? "" : "hianyzik"}"><td>${esc(s.fiok)}</td><td>${esc(s.szerep)}</td>
          <td>${s.regi_nev ? `<b>${esc(s.regi_nev)}</b><br>` : ""}<span class="kicsi">${esc(s.entity_id)}${s.regi_egyseg ? ` · ${esc(s.regi_egyseg)}` : ""}</span>${s.letezik ? "" : `<br><span class="figyszoveg">nem található</span>`}</td>
          <td><input type="text" list="szenzorjeloltek" data-sor="${i}" value="${esc(s.entity_id)}" placeholder="sensor.…" autocomplete="off"></td></tr>`).join("")}</tbody></table>`
        : `<div class="kicsi">Ez az otthon nem használ szenzort (kézi leolvasásokból számol).</div>`;
    } catch (err) {
      r.getElementById("szenzortabla").innerHTML = `<div class="figyszoveg">${esc(err.message || err)}</div>`;
    }
  }

  _dialogusKezelo() {
    const d = this.shadowRoot.getElementById("leolv");
    const form = this.shadowRoot.getElementById("leolvform");
    this.shadowRoot.getElementById("megse").addEventListener("click", () => d.close());
    form.csere.addEventListener("change", () => { this._csereValt(); this._mentesAllapot(); });
    form.korrekcio.addEventListener("change", () => { this._korrValt(); this._csereValt(); this._mentesAllapot(); });
    form.regi_zaro.addEventListener("input", () => this._mentesAllapot());
    form.eves.addEventListener("change", () => { if (form.eves.checked) form.szolgaltatoi.checked = true; this._mentesAllapot(); });
    for (const n of ["allas", "reg181", "reg182"]) form[n].addEventListener("input", () => {
      this._dkezi.add(n);
      if (this._dfiok?.dijszabas === "villany/h") this._hSzamol();
      this._mentesAllapot();
    });
    form.csatorna.addEventListener("change", () => {
      // Másik csatorna (pl. almérő): annak a legutolsó állása az induló érték.
      const ut = this._dfiok?.utolso_allasok || {}, c = form.csatorna.value || "vetelezes";
      if (!form.csere.checked && this._dfiok?.dijszabas !== "villany/h") {
        form.allas.value = ut[c] ? String(ut[c].allas) : "";
        this._dkezdo = { ...this._dkezdo, allas: form.allas.value };
        this._dkezi.delete("allas");
      }
      this._utolsoJelzes();
      this._mentesAllapot();
    });
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = this._dfiok;
      const hiba = this.shadowRoot.getElementById("dhiba");
      const alap = {
        device_id: f.device_id,
        datum: form.datum.value,
        tipus: form.szolgaltatoi.checked || form.eves.checked ? "szolgaltatoi" : "kezi",
        megjegyzes: form.korrekcio.checked ? "korrekciós leolvasás (panel)" : "Rezsikövető panel",
        ...(form.eves.checked ? { elszamolasi: true } : {}),
        ...(form.korrekcio.checked ? { korrekcio: true } : {}),
      };
      const dikt = ["diktalas", "atalany"].includes(f.elszamolas_mod) && form.diktalt.checked ? { diktalt: true } : {};
      try {
        if (form.csere.checked) {
          const sz = (x) => (x.value === "" ? undefined : Number(x.value.replace(",", ".")));
          const adat = {
            device_id: f.device_id, datum: form.datum.value, regi_zaro_allas: sz(form.regi_zaro),
            uj_kezdo_allas: sz(form.uj_kezdo) ?? 0, uj_gyari_szam: form.uj_gyari.value.trim(),
            csatorna: form.csatorna.value || "vetelezes",
          };
          if (f.dijszabas === "villany/h") {
            for (const [k, n] of [["regi_zaro_h_teli", "regi_181"], ["regi_zaro_h_nyari", "regi_182"], ["uj_kezdo_h_teli", "uj_181"], ["uj_kezdo_h_nyari", "uj_182"]])
              if (sz(form[n]) !== undefined) adat[k] = sz(form[n]);
          }
          if (adat.regi_zaro_allas === undefined) { hiba.textContent = "Add meg a régi mérő záró állását."; return; }
          await this._hass.callService("hu_rezsi", "merocsere", adat);
          d.close();
          setTimeout(() => this._betolt(), 1500);
          return;
        }
        if (f.dijszabas === "villany/h") {
          const sz = (x) => (x.value === "" ? null : Number(x.value));
          let ossz = sz(form.allas);
          const t = sz(form.reg181), n = sz(form.reg182);
          if (t === null || n === null) { hiba.textContent = "Add meg mindkét regisztert (1.81 téli, 1.82 nyári)."; return; }
          ossz = t + n;
          if (t !== null && n !== null && Math.abs(t + n - ossz) > 1) {
            hiba.textContent = `1.81 + 1.82 = ${SZAM.format(t + n)}, de az 1.8.0 = ${SZAM.format(ossz)} – ellenőrizd a számokat.`;
            return;
          }
          await this._hass.callService("hu_rezsi", "leolvasas_rogzites", { ...alap, ...dikt, allas: ossz, csatorna: "vetelezes" });
          if (t !== null) await this._hass.callService("hu_rezsi", "leolvasas_rogzites", { ...alap, allas: t, csatorna: "h_teli" });
          if (n !== null) await this._hass.callService("hu_rezsi", "leolvasas_rogzites", { ...alap, allas: n, csatorna: "h_nyari" });
        } else {
          await this._hass.callService("hu_rezsi", "leolvasas_rogzites", {
            ...alap, ...dikt, allas: Number(form.allas.value), csatorna: form.csatorna.value || "vetelezes",
          });
        }
        d.close();
        if (form.korrekcio.checked) {
          // A visszajelzés a panel tetején (a háttér újraszámolása után): eltérés a szenzorhoz, szorzó előtte → utána.
          const ertekek = f.dijszabas === "villany/h" ? [["h_teli", Number(form.reg181.value)], ["h_nyari", Number(form.reg182.value)]]
            : [[form.csatorna.value || "vetelezes", Number(form.allas.value)]];
          this._sav = { html: `${esc(f.nev)}: korrekciós leolvasás rögzítve – a korrekciót számolom…` };
          if (!this._szerkesztesAlatt()) this._rajzol();
          const html = await this._korrekcioEredmeny(f, ertekek, form.datum.value);
          this._sav = { html: `<b>${esc(f.nev)}</b> – ${html}` };
          if (this._szerkesztesAlatt()) this._rajzolVar = true; else this._rajzol();
          return;
        }
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
  .fulek { display: flex; gap: 4px; overflow-x: auto; margin: -4px 0 16px; border-bottom: 1px solid var(--divider-color); scrollbar-width: thin; }
  .ful { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; min-width: 120px; max-width: 220px; padding: 8px 14px 7px;
         border: 1px solid transparent; border-bottom: 0; border-radius: 10px 10px 0 0; background: transparent; color: var(--secondary-text-color);
         font: inherit; cursor: pointer; text-align: left; margin-bottom: -1px; }
  .ful:hover { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
  .ful.aktiv { background: var(--card-background-color); color: var(--primary-text-color); border-color: var(--divider-color);
               box-shadow: inset 0 3px 0 var(--primary-color); }
  .ful:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  .fulnev { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; display: flex; align-items: center; gap: 6px; }
  .fulosszeg { font-size: 12px; font-variant-numeric: tabular-nums; }
  .fulpont { width: 7px; height: 7px; border-radius: 50%; background: var(--warning-color, #ff9800); flex: none; }
  .osszesito { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); padding: 16px 20px; margin-bottom: 16px;
               box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); }
  .hnev { font-size: 14px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .05em; }
  .nagyszamok { display: flex; gap: 32px; flex-wrap: wrap; margin: 8px 0 4px; }
  .nagy { font-size: 32px; font-weight: 500; }
  .nagy.masodlagos { font-size: 22px; color: var(--secondary-text-color); padding-top: 8px; }
  ul.esedekes { margin: 4px 0 6px; padding-left: 18px; font-size: 14px; }
  ul.esedekes li { margin: 2px 0; }
  .cimke { font-size: 12px; color: var(--secondary-text-color); }
  .megj, .kicsi { font-size: 12px; color: var(--secondary-text-color); }
  .elsoszamla { margin-top: 8px; padding: 6px 10px; border-left: 3px solid var(--primary-color); background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.06); border-radius: 4px; }
  .elsoszamla .escim { font-size: 12px; display: flex; align-items: center; gap: 4px; }
  .elsoszamla .essor { font-size: 12px; color: var(--secondary-text-color); white-space: normal; margin-top: 4px; padding-left: 10px; text-indent: -10px; }
  .elsoszamla .essor::before { content: "• "; }
  .dolt { font-size: 12px; font-style: italic; color: var(--secondary-text-color); }
  /* Becsült (még nem érkezett számla) fizetendő a kártyákon: ugyanaz a narancs, mint a számlakimutatás várható sorai. */
  .esedekesmajd { font-style: italic; font-weight: 400; color: var(--rezsi-varhato, #c76a00); }
  .figylista { margin: 12px 0 0; padding: 0; list-style: none; }
  .figylista .ellgombok { display: flex; gap: 14px; margin-top: 4px; }
  .folyosor { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; }
  .folyosor .cimke { margin: 0; }
  #reklambody .level { background: var(--card-background-color, #fff); border: 1px solid var(--divider-color); border-radius: 8px; padding: 16px; line-height: 1.5; }
  #reklambody .level p { margin: 0 0 10px; }
  .figylista li[data-ugrik] { cursor: pointer; }
  ha-icon.javjel { --mdc-icon-size: 14px; color: var(--secondary-text-color); vertical-align: -2px; }
  #javmezok { display: grid; gap: 10px; margin: 12px 0; }
  #javmezok label { display: grid; gap: 4px; font-size: 14px; }
  #javmezok label.javsor { display: flex; flex-direction: row; align-items: center; justify-content: flex-start; gap: 8px; text-align: left; }
  #javmezok label.javsor input { width: auto; margin: 0; }
  #javmegj { font: inherit; padding: 6px 8px; border-radius: 6px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); resize: vertical; }
  .kartya.kiemelt { animation: kiemel 1.6s ease-out; }
  @keyframes kiemel { 0%, 40% { box-shadow: 0 0 0 3px var(--primary-color); } 100% { box-shadow: 0 0 0 0 transparent; } }
  .figylista li { padding: 6px 10px; margin-top: 6px; border-radius: 6px; font-size: 14px; border-left: 4px solid; }
  .figylista .figy { border-color: var(--warning-color, #ff9800); background: color-mix(in srgb, var(--warning-color, #ff9800) 12%, transparent); }
  .figylista .hiba { border-color: var(--error-color, #db4437); background: color-mix(in srgb, var(--error-color, #db4437) 12%, transparent); }
  .figylista .info { border-color: var(--info-color, #039be5); background: color-mix(in srgb, var(--info-color, #039be5) 10%, transparent); }
  .rendben { margin-top: 10px; color: var(--success-color, #43a047); font-size: 14px; }
  .racs { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
  .kartya { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); padding: 16px; border: 1px solid var(--divider-color);
            box-shadow: var(--ha-card-box-shadow, none); display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .kfej { display: flex; gap: 12px; align-items: center; }
  .kinfo { font-size: 12px; line-height: 1.5; color: var(--secondary-text-color); margin-top: -4px; }
  .kinfo strong { color: var(--primary-text-color); font-weight: 500; }
  .kfej ha-icon { color: var(--state-icon-color, var(--primary-color)); background: color-mix(in srgb, var(--primary-color) 12%, transparent);
                  border-radius: 50%; padding: 8px; }
  .knev { font-size: 18px; font-weight: 500; }
  .inaktiv, .inaktiv .ertek, .inaktiv .figyszoveg { color: var(--disabled-text-color, #9e9e9e) !important; }
  .inaktiv .ertek { opacity: .7; }
  .nemesedekes { font-size: 13px; color: var(--secondary-text-color); background: color-mix(in srgb, var(--primary-text-color) 6%, transparent);
                 border-radius: 8px; padding: 6px 10px; }
  .kfej > div:nth-child(2) { flex: 1; min-width: 0; }
  .menu3 { position: relative; align-self: flex-start; margin: -8px -8px 0 0; }
  .kfej .pontok { color: var(--secondary-text-color); padding: 8px; line-height: 0; border: 0; }
  .kfej .pontok ha-icon { background: none; padding: 0; color: inherit; }
  .kfej .grafgomb { color: var(--primary-color); }
  .kfej .pontok:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
  .menulista { position: absolute; right: 0; top: 40px; z-index: 5; min-width: 190px; padding: 6px 0; border-radius: 10px;
               background: var(--card-background-color); border: 1px solid var(--divider-color); box-shadow: 0 6px 20px rgba(0,0,0,.25); }
  .mtetel { display: flex; align-items: center; gap: 14px; width: 100%; border: 0; border-radius: 0; padding: 10px 16px;
            color: var(--primary-text-color); text-align: left; }
  .mtetel:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
  .mtetel ha-icon { color: var(--secondary-text-color); background: none !important; padding: 0 !important; }
  #beallit { width: min(460px, 92vw); }
  #entlista { margin: 10px 0 14px; max-height: 60vh; overflow-y: auto; }
  .entsor { display: flex; align-items: center; gap: 12px; width: 100%; border: 0; border-radius: 8px; padding: 8px; text-align: left;
            color: var(--primary-text-color); }
  .entsor:hover { background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); }
  .entsor ha-state-icon { color: var(--state-icon-color, var(--primary-color)); }
  .entnev { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .entnev .kicsi { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .entertek { white-space: nowrap; font-size: 13px; color: var(--secondary-text-color); }
  .ket { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .fejlec { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px 12px; padding-bottom: 12px; border-bottom: 1px solid var(--divider-color); }
  .fejlec .fjfolyo { grid-column: 1 / -1; padding-top: 8px; border-top: 1px dashed var(--divider-color); }
  .fejlec .fjsor { display: flex; justify-content: space-between; align-items: baseline; gap: 4px 12px; flex-wrap: wrap; }
  .fejlec .fjkozep { font-size: 18px; font-weight: 500; }
  .fejlec .fjblokk { min-width: 0; }
  .fejlec .fjjobb { text-align: right; }
  .fejlec .ertek { white-space: normal; font-size: 20px; }
  .fejlec .fjures { color: var(--secondary-text-color); }
  .fejlec .fjsav { margin: 6px 0 2px; }
  .mjel { display: inline-block; font-size: 11px; font-weight: 500; font-style: normal; line-height: 16px; padding: 0 6px; border-radius: 8px; vertical-align: middle; color: var(--primary-text-color); }
  .mjel-pontos { background: color-mix(in srgb, var(--success-color, #43a047) 22%, transparent); }
  .mjel-mert { background: color-mix(in srgb, var(--info-color, #039be5) 22%, transparent); }
  .mjel-becsult { background: color-mix(in srgb, var(--warning-color, #ff9800) 25%, transparent); }

  .ertek { font-size: 22px; font-weight: 500; white-space: nowrap; }
  .ertek.minusz { color: var(--error-color, #db4437); }
  .ertek.plusz { color: var(--success-color, #43a047); }
  .sor { display: flex; justify-content: space-between; align-items: center; gap: 12px; border-top: 1px solid var(--divider-color); padding-top: 10px; }
  .sav { height: 8px; background: var(--divider-color); border-radius: 4px; overflow: hidden; margin: 4px 0; }
  .sav .toltes { height: 100%; background: var(--success-color, #43a047); }
  .sav .toltes.kozel { background: var(--warning-color, #ff9800); }
  .sav .toltes.tele { background: var(--error-color, #db4437); }
  .figyszoveg { color: var(--warning-color, #ff9800); }
  .joszoveg { color: var(--success-color, #4caf50); }
  .cimkeszalag.atalany { background: var(--info-color, #039be5); }
  .cimkeszalag { font-size: 10px; padding: 1px 6px; border-radius: 8px; background: var(--warning-color, #ff9800); color: #fff; margin-left: 4px; }
  .gombok { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; margin-top: auto; }
  button { font: inherit; font-size: 14px; padding: 8px 14px; border-radius: 18px; cursor: pointer; border: 1px solid var(--divider-color);
           background: transparent; color: var(--primary-color); }
  button.fo { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  button:disabled { opacity: .45; cursor: default; }
  .reszletek h4 { margin: 12px 0 6px; font-size: 14px; font-weight: 500; }
  .tablagorgeto { overflow-x: auto; }
  .feltoltsor { margin-bottom: 4px; }
  .feltoltsor .ok { color: var(--success-color, #43a047); font-weight: 500; }
  .elvalaszto { text-align: center; margin: 8px 0 4px; }
  .ket2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  table.szamlalista td:nth-child(3) { white-space: normal; overflow-wrap: anywhere; }
  table.szamlalista td, table.szamlalista th { padding: 4px 4px; }
  input.jelol { width: 16px; height: 16px; margin: 0; accent-color: var(--error-color, #db4437); }
  tr.szsor { cursor: pointer; }
  tr.szsor:hover td { background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); }
  .nyil { --mdc-icon-size: 16px; color: var(--secondary-text-color); vertical-align: -3px; margin-right: 2px; }
  tr.szreszlet td { background: color-mix(in srgb, var(--primary-text-color) 3%, transparent); white-space: normal; text-align: left; cursor: pointer; }
  dl.szamlaadat { display: grid; grid-template-columns: max-content 1fr; gap: 3px 12px; margin: 4px 0; font-size: 13px; text-align: left; }
  dl.szamlaadat dt { color: var(--secondary-text-color); }
  dl.szamlaadat dd { margin: 0; overflow-wrap: anywhere; }
  .torlessor { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
  .torlessor > span { display: flex; gap: 8px; flex-wrap: wrap; }
  button.veszely { color: var(--error-color, #db4437); border-color: color-mix(in srgb, var(--error-color, #db4437) 50%, transparent); }
  button.veszely:disabled { opacity: .4; cursor: default; }
  button.veszely.tele { background: var(--error-color, #db4437); color: #fff; border-color: var(--error-color, #db4437); }
  ul.torleslista { margin: 0 0 10px; padding-left: 18px; font-size: 14px; max-height: 40vh; overflow: auto; }
  h4 .dijnev { font-weight: 400; margin-left: 4px; }
  .tabletsav { display: flex; align-items: flex-end; gap: 12px; border-bottom: 1px solid var(--divider-color); margin: 8px 0 14px; }
  .lapfulek { display: flex; gap: 2px; overflow-x: auto; flex: 1; scrollbar-width: thin; }
  .lapful { border: none; background: none; padding: 8px 12px 6px; border-bottom: 3px solid transparent; cursor: pointer; color: var(--secondary-text-color);
    display: grid; grid-template-columns: auto auto; grid-template-rows: auto auto; column-gap: 6px; align-items: center; white-space: nowrap; font: inherit; text-align: left; }
  .lapful ha-icon { --mdc-icon-size: 20px; grid-row: 1 / span 2; }
  .lapful .lapnev { font-size: 14px; font-weight: 500; color: var(--primary-text-color); }
  .lapful .lapal { font-size: 12px; }
  .lapful.aktiv { border-bottom-color: var(--primary-color); }
  .lapful.aktiv ha-icon, .lapful.aktiv .lapnev { color: var(--primary-color); }
  .lapful:hover { background: var(--secondary-background-color); }
  .nezetvalto { display: flex; flex: none; border: 1px solid var(--divider-color); border-radius: 8px; overflow: hidden; margin-bottom: 6px; }
  .nezetvalto button { border: none; background: none; padding: 5px 10px; cursor: pointer; display: flex; gap: 4px; align-items: center; color: var(--secondary-text-color); font: inherit; font-size: 13px; }
  .nezetvalto button ha-icon { --mdc-icon-size: 18px; }
  .nezetvalto button.aktiv { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .egylap .kartya { display: block; column-count: 3; column-gap: 32px; column-rule: 1px solid var(--divider-color); padding: 20px 24px; }
  .egylap .kartya > * { break-inside: avoid; margin-bottom: 14px; }
  .csempe .plusz { color: var(--success-color, #43a047); }
  .csempe .minusz { color: var(--error-color, #db4437); }
  .egylap .kartya > .kfej, .egylap .kartya > .fejlec, .egylap .kartya > .gombok, .egylap .kartya > .reszletek, .egylap .kartya > .hiba { column-span: all; }
  .egylap .kartya > .gombok { justify-content: flex-end; margin-top: 12px; }
  @media (max-width: 1150px) { .egylap .kartya { column-count: 2; } }
  .lapozo { display: flex; justify-content: center; align-items: center; gap: 6px; margin: 12px 0 4px; }
  .lappotty { width: 10px; height: 10px; padding: 0; border-radius: 50%; border: none; background: var(--divider-color); cursor: pointer; }
  .lappotty.aktiv { background: var(--primary-color); width: 22px; border-radius: 5px; }
  .csempek { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 12px; margin: 14px 0; }
  .csempe { text-align: left; border: 1px solid var(--divider-color); border-radius: var(--ha-card-border-radius, 12px); background: var(--card-background-color);
    padding: 12px 14px; font: inherit; color: inherit; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
  .csempe:hover { border-color: var(--primary-color); }
  .csempe.figy { border-left: 4px solid var(--warning-color, #ff9800); }
  .csfej { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
  .csfej ha-icon { --mdc-icon-size: 20px; color: var(--primary-color); }
  .cscimke { font-size: 12px; color: var(--secondary-text-color); }
  .csertek { font-size: 20px; font-weight: 500; }
  .cssor { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
  .mxlap { display: grid; gap: 10px; font-size: 14px; line-height: 1.4; }
  .mxfej { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; justify-content: space-between; }
  .mxteendok { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; flex: 1; }
  .mxteendok > b { margin-right: 4px; }
  .mxchip { border: 0; border-radius: 999px; padding: 4px 10px; font: inherit; font-size: 13px; cursor: pointer; color: var(--mx-tenni);
    background: color-mix(in srgb, var(--mx-tenni) 14%, var(--card-background-color)); }
  .mxchip b { color: var(--primary-text-color); font-weight: 500; }
  .mxvalto { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 8px; padding: 2px; gap: 2px; }
  .mxvalto button { border: 0; background: none; font: inherit; font-size: 13px; font-weight: 500; padding: 5px 12px; border-radius: 6px; cursor: pointer; color: var(--secondary-text-color); }
  .mxvalto button.aktiv { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .mxreszlet { display: grid; grid-template-columns: minmax(200px, 280px) minmax(0, 1fr); gap: 4px 20px; padding: 12px 16px; border: 1px solid var(--divider-color);
    border-radius: 10px; background: var(--card-background-color); }
  .mxbal, .mxjobb { display: grid; gap: 4px; align-content: start; }
  .mxjobb > div:not(.kicsi) { max-width: 75ch; }
  .mxr1 { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--secondary-text-color); }
  .mxcim { font-weight: 700; font-size: 16px; }
  .mxertek { font-size: 20px; font-weight: 700; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .mxpill { font-size: 12px; font-weight: 500; border-radius: 999px; padding: 2px 9px; color: var(--mx-s); background: color-mix(in srgb, var(--mx-s) 14%, var(--card-background-color)); }
  .mxnyit { justify-self: start; border: 0; background: none; color: var(--primary-color); font: inherit; font-size: 13px; cursor: pointer; padding: 2px 0; }
  .mxnyit ha-icon { --mdc-icon-size: 16px; vertical-align: -3px; }
  .mxtabla { border-collapse: separate; border-spacing: 3px; min-width: 980px; width: 100%; font-variant-numeric: tabular-nums; font-size: 13px; }
  .mxtabla.mxnaptar { min-width: 1120px; }
  .mxtabla th { text-align: left; font-weight: 400; font-size: 12px; color: var(--secondary-text-color); padding: 4px 8px; vertical-align: bottom; }
  .mxtabla th .mxo { display: block; font-weight: 700; font-size: 13px; color: var(--primary-text-color); }
  .mxtabla th.mxmost, .mxtabla th.mxmost .mxo { color: var(--primary-color); }
  .mxfiok { position: sticky; left: 0; z-index: 1; background: var(--card-background-color); border-left: 4px solid var(--km-szin, var(--primary-color)); border-radius: 4px;
    padding: 6px 10px; min-width: 160px; }
  .mxfb { display: flex; gap: 8px; align-items: center; }
  .mxfiok ha-icon { --mdc-icon-size: 18px; color: var(--km-szin, var(--primary-color)); flex: none; }
  .mxn { font-weight: 700; }
  .km-villany { --km-szin: #f0a020; } .km-gaz { --km-szin: #4a8fe0; } .km-viz { --km-szin: #27a5c4; } .km-hulladek { --km-szin: #7b9a52; }
  .km-tavho { --km-szin: #d0603a; } .km-kozos { --km-szin: #8a6fb0; } .km-tavkozles { --km-szin: #d04a8a; }
  .mxcella { background: color-mix(in srgb, var(--mx-s) 13%, var(--card-background-color)); border: 1px solid transparent; border-radius: 6px; padding: 6px 8px;
    vertical-align: top; cursor: pointer; min-width: 100px; }
  .mxcella:hover, .mxcella:focus-visible { border-color: var(--mx-s); outline: none; }
  .mxcella.valasztott { border-color: var(--mx-s); box-shadow: inset 0 0 0 1px var(--mx-s); }
  .mxt { font-weight: 500; display: flex; gap: 6px; align-items: baseline; }
  .mxt::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--mx-s); flex: none; transform: translateY(-1px); }
  .mxcella.mx-na .mxt { font-weight: 400; color: var(--secondary-text-color); }
  .mxsav { height: 4px; border-radius: 2px; margin-top: 5px; background: color-mix(in srgb, var(--mx-s) 22%, transparent); overflow: hidden; }
  .mxsav i { display: block; height: 100%; background: var(--mx-s); }
  .mx-ok { --mx-s: var(--mx-ok); } .mx-becs { --mx-s: var(--mx-becs); } .mx-ata { --mx-s: var(--mx-ata); } .mx-tenni { --mx-s: var(--mx-tenni); } .mx-na { --mx-s: var(--mx-na); }
  .mxlap, .mxjelm { --mx-ok: var(--success-color, #2e7d4f); --mx-becs: #b8900a; --mx-ata: #4a68c4; --mx-tenni: #d9641e; --mx-na: #8a94a3; }
  .mxnc, .mxures { border-radius: 6px; padding: 4px 5px; vertical-align: top; min-width: 72px; }
  .mxures { background: color-mix(in srgb, var(--secondary-text-color) 7%, transparent); }
  .mxmostosz { box-shadow: inset 0 0 0 1px var(--primary-color); }
  .mxszla { display: flex; gap: 4px; align-items: center; white-space: nowrap; font-size: 12px; cursor: pointer; border-radius: 4px; padding: 1px 2px; }
  .mxszla:hover, .mxszla:focus-visible { background: color-mix(in srgb, var(--mx-s) 15%, transparent); outline: none; }
  .mxbetu { font-size: 10px; font-weight: 700; min-width: 15px; height: 15px; padding: 0 2px; border-radius: 3px; display: inline-grid; place-items: center; background: var(--mx-s);
    color: var(--card-background-color); flex: none; box-sizing: border-box; }
  .mxvarhato .mxbetu { background: none; color: var(--mx-s); border: 1px dashed var(--mx-s); }
  .mxstorno { text-decoration: line-through; color: var(--secondary-text-color); }
  .mxjel { display: inline-block; font-size: 10px; font-weight: 700; color: var(--primary-color); border: 1px solid var(--primary-color); border-radius: 3px; padding: 0 3px; margin: 2px 2px 0 0; }
  .mxjelm { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; color: var(--secondary-text-color); }
  .mxjelm > span { display: inline-flex; gap: 5px; align-items: center; }
  .mxnegyzet { width: 12px; height: 12px; border-radius: 3px; border: 2px solid var(--mx-s); background: color-mix(in srgb, var(--mx-s) 15%, transparent); }
  .keskeny .mxreszlet { grid-template-columns: 1fr; }
  .keskeny .mxfej { flex-direction: column-reverse; align-items: stretch; }
  .keskeny .mxvalto { align-self: flex-start; }
  .keskeny .mxchip { font-size: 12px; text-align: left; }
  .keskeny .mxfiok { min-width: 118px; padding: 5px 6px; }
  .keskeny .mxfiok ha-icon { display: none; }
  .tematabla { width: 100%; border-collapse: collapse; font-size: 14px; font-variant-numeric: tabular-nums; background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: var(--ha-card-border-radius, 12px); overflow: hidden; }
  .tematabla th { text-align: right; font-weight: 500; font-size: 12px; color: var(--secondary-text-color); padding: 10px; border-bottom: 1px solid var(--divider-color); }
  .tematabla th:first-child { text-align: left; }
  .tematabla td { padding: 9px 10px; border-bottom: 1px solid var(--divider-color); vertical-align: middle; }
  .tematabla td.szam { text-align: right; white-space: nowrap; }
  .tematabla td.tfiok { white-space: nowrap; font-weight: 500; }
  .tematabla td.tfiok ha-icon { --mdc-icon-size: 18px; color: var(--primary-color); margin-right: 8px; vertical-align: -3px; }
  .tematabla tbody tr { cursor: pointer; }
  .tematabla tbody tr:hover { background: var(--secondary-background-color); }
  .tematabla tfoot td { font-weight: 600; border-bottom: none; }
  .tematabla .plusz { color: var(--success-color, #43a047); }
  .tematabla .minusz { color: var(--error-color, #db4437); }
  .temamegj { margin-top: 6px; }
  .minisav { height: 6px; width: 72px; background: var(--divider-color); border-radius: 3px; display: inline-block; vertical-align: middle; }
  .minisav > div { height: 100%; background: var(--primary-color); border-radius: 3px; }
  .minisav.tullepve > div { background: var(--error-color, #db4437); }
  .kisgomb { font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 14px; border: 1px solid var(--primary-color); background: none; color: var(--primary-color); cursor: pointer; }
  .keskeny .nagyszamok { display: grid; grid-template-columns: 1fr auto; gap: 4px 16px; }
  .keskeny .nagyszamok .nagy { font-size: 26px; }
  .mobilemail { margin: 8px 0; border: 1px solid var(--divider-color); border-radius: 8px; padding: 6px 10px; }
  .mobilemail > summary { cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 14px; color: var(--secondary-text-color); }
  .mobilemail > summary ha-icon { --mdc-icon-size: 18px; }
  .mobilemail[open] > summary { margin-bottom: 6px; }
  .keskeny .tabletsav { position: sticky; top: 56px; z-index: 1; background: var(--primary-background-color); margin: 0 -8px 10px; padding: 2px 8px 0; gap: 6px; }
  .keskeny .lapful { padding: 6px 8px 4px; grid-template-rows: auto; }
  .keskeny .lapful ha-icon { grid-row: auto; --mdc-icon-size: 18px; }
  .keskeny .lapful .lapal { display: none; }
  .keskeny .lapful .lapnev { font-size: 13px; }
  .keskeny .nezetvalto button { padding: 5px 7px; }
  .keskeny .nvszoveg { display: none; }
  .keskeny .csempek { grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0; }
  .keskeny .csempe { padding: 10px; }
  .keskeny .csertek { font-size: 17px; }
  .keskeny .cssor { flex-direction: column; gap: 0; }
  .keskeny .lapozo { margin-top: 10px; }
  .temakartyak { display: flex; flex-direction: column; gap: 10px; }
  .temakartya { border: 1px solid var(--divider-color); border-radius: var(--ha-card-border-radius, 12px); background: var(--card-background-color); padding: 10px 12px; cursor: pointer; }
  .temakartya.osszes { cursor: default; background: var(--secondary-background-color); }
  .tkfej { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .tkfej ha-icon { --mdc-icon-size: 20px; color: var(--primary-color); }
  .tkfej .tknyil { margin-left: auto; color: var(--secondary-text-color); }
  .tkracs { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; font-size: 14px; font-variant-numeric: tabular-nums; align-items: baseline; }
  .tkc { color: var(--secondary-text-color); font-size: 13px; }
  .tkv { text-align: right; }
  .temakartya .plusz { color: var(--success-color, #43a047); }
  .temakartya .minusz { color: var(--error-color, #db4437); }
  .mmkorr { margin-top: 2px; }
  .tematabla td .tor { white-space: normal; }
  .korrsav { display: flex; align-items: flex-start; gap: 8px; justify-content: space-between; margin-bottom: 12px; font-size: 14px; line-height: 1.5; }
  .pipa.tiltva { opacity: .45; }
  label.jelolo { display: flex; flex-direction: row; align-items: center; gap: 6px; }
  label.jelolo input[type="checkbox"] { width: auto; margin: 0; }
  .aiablak { width: min(1200px, 96vw); max-width: 96vw; }
  .aiketoszlop { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(280px, 1fr); gap: 12px; margin: 8px 0; }
  @media (max-width: 760px) { .aiketoszlop { grid-template-columns: 1fr; } }
  .aiadatok { max-height: 62vh; overflow: auto; padding-right: 4px; }
  .aiadatok h4 { margin: 10px 0 4px; }
  .aimezo { display: grid; grid-template-columns: 18px 150px 1fr; align-items: center; gap: 6px; margin: 3px 0; font-size: 13px; }
  .aimezo input, .aimezo select, .aitabla input, .aitabla select { font: inherit; padding: 3px 5px; min-width: 0; width: 100%; box-sizing: border-box; }
  .aitabla { border-collapse: collapse; font-size: 12px; }
  .aitabla td { padding: 2px 3px; vertical-align: top; white-space: nowrap; }
  .aitabla td input { width: 96px; }
  .aitabla td .aijel { margin-right: 2px; }
  .aijel { display: inline-block; width: 16px; text-align: center; font-weight: 700; }
  .aijel-ok { color: var(--success-color, #43a047); }
  .aijel-figy { color: var(--warning-color, #ff9800); }
  .aijel-ellentmondas { color: var(--error-color, #db4437); }
  .aiuzenet { font-size: 12px; margin: 0 0 4px 24px; white-space: normal; }
  .aiszoveg { max-height: 62vh; overflow: auto; margin: 0; padding: 8px; font-size: 11px; line-height: 1.35; white-space: pre; background: var(--secondary-background-color, #f5f5f5); border-radius: 6px; }
  .aiszoveg mark { background: rgba(255, 213, 79, .55); color: inherit; border-radius: 2px; }
  .aiszoveg mark.aktiv { background: rgba(255, 152, 0, .9); outline: 2px solid var(--warning-color, #ff9800); }
  .aitolt { display: flex; align-items: center; gap: 10px; padding: 16px 0; }
  .aimeger { display: flex; align-items: center; gap: 8px; margin: 8px 0; font-weight: 500; }
  .aimeger input { width: auto; margin: 0; }
  .fuggo { margin-top: 12px; padding: 10px 14px; border-left: 4px solid var(--warning-color, #ff9800); border-radius: 6px;
           background: color-mix(in srgb, var(--warning-color, #ff9800) 10%, transparent); display: grid; gap: 8px; }
  .fuggocim { display: flex; align-items: center; gap: 8px; font-size: 15px; }
  .fuggocim ha-icon { color: var(--warning-color, #ff9800); }
  .fuggoszamla { font-size: 14px; }
  .fuggotabla { border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  .fuggotabla th, .fuggotabla td { padding: 3px 10px 3px 0; text-align: right; }
  .fuggotabla th[scope="row"] { text-align: left; font-weight: 400; color: var(--secondary-text-color); }
  .fuggotabla thead th { font-weight: 500; font-size: 12px; color: var(--secondary-text-color); }
  .fuggotabla tr.valt td:last-child { font-weight: 600; }
  .fuggogombok { justify-content: flex-start; }
  button.info { background: none; border: 0; padding: 0 2px; margin: 0; cursor: pointer; color: var(--secondary-text-color); vertical-align: middle; line-height: 0; border-radius: 50%; }
  button.info ha-icon { --mdc-icon-size: 16px; }
  button.info:hover, button.info.aktiv { color: var(--primary-color); }
  .buborek hr { border: 0; border-top: 1px solid var(--divider-color); margin: 8px 0; }
  .ketsor { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .buborek { position: fixed; z-index: 10; max-width: min(320px, calc(100vw - 24px)); padding: 10px 12px; border-radius: 10px; font-size: 13px; line-height: 1.45;
             background: var(--card-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color);
             box-shadow: 0 4px 16px rgba(0, 0, 0, .35); }
  table.bontas td:first-child { white-space: normal; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--divider-color); white-space: nowrap; }
  th { color: var(--secondary-text-color); font-weight: 500; }
  td:last-child, th:last-child { text-align: right; }
  .hiba { color: var(--error-color, #db4437); }
  .toltes, .ures { padding: 24px; text-align: center; color: var(--secondary-text-color); }
  .labjegyzet { margin: 24px 0 8px; font-size: 12px; color: var(--secondary-text-color); text-align: center; }
  dialog { border: 0; border-radius: 16px; padding: 20px; background: var(--card-background-color); color: var(--primary-text-color); width: min(360px, 90vw); }
  dialog.szeles { width: min(760px, 94vw); max-height: 92vh; }
  dialog.evesdlg { width: min(1100px, 96vw); }
  .fizcella { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
  .fizdatum { font: inherit; font-size: 12px; padding: 1px 2px; max-width: 128px; }
  .lejart { color: var(--error-color, #db4437); font-weight: 500; }
  .kmnyit { display: inline-block; margin-left: 3px; padding: 0 4px; border-radius: 3px; font-size: 10px; font-weight: 700; color: #fff; background: var(--error-color, #db4437); }
  .evtabla td, .evtabla th { white-space: nowrap; } .evtabla .bal { text-align: left; white-space: normal; }
  .evtabla tr.evhiba td { background: rgba(255, 152, 0, 0.14); } .evtabla tr.evossz td { font-weight: 600; }
  .evtabla tr.evfugg td { color: var(--secondary-text-color); font-style: italic; } .evdij { max-width: 560px; }
  .evmeg { margin: 4px 0 8px 18px; padding: 0; font-size: 13px; } .evmeg li { margin-bottom: 4px; }
  .evdoboz { border-left: 3px solid var(--warning-color, #ff9800); background: rgba(255, 152, 0, 0.1); padding: 6px 10px; margin: 6px 0; font-size: 13px; }
  #evesev { font: inherit; font-size: 13px; padding: 2px 4px; max-width: 220px; }
  .emailblokk { margin: 10px 0; padding: 10px 12px; border: 1px solid var(--divider-color); border-radius: 10px; font-size: 14px; display: flex; flex-direction: column; gap: 8px; }
  .emailfej { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--secondary-text-color); }
  .emailfej > span { flex: 1; font-weight: 500; }
  .emailfej ha-icon, .emailures ha-icon { --mdc-icon-size: 18px; }
  .emailnyit { font: inherit; font-weight: 500; font-size: 14px; border-radius: 18px; padding: 6px 14px; cursor: pointer;
    border: 1px solid var(--primary-color); background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .emailnyit.masodik { background: none; color: var(--primary-color); }
  .emailpf { display: flex; flex-direction: column; gap: 2px; }
  .emailgombok { display: flex; flex-wrap: wrap; gap: 4px 12px; }
  .emailfut { display: inline-flex; align-items: center; gap: 6px; color: var(--primary-color); }
  .porgo { width: 14px; height: 14px; border: 2px solid var(--divider-color); border-top-color: var(--primary-color); border-radius: 50%;
    display: inline-block; animation: forog 0.9s linear infinite; flex: none; }
  .porgo.nagy { width: 32px; height: 32px; border-width: 4px; }
  @keyframes forog { to { transform: rotate(360deg); } }
  .emailuzenet { display: flex; align-items: flex-start; gap: 8px; padding: 8px 10px; border-radius: 8px; background: rgba(var(--rgb-success-color, 67, 160, 71), .12); }
  .emailuzenet > div { flex: 1; }
  .emailuzenet ha-icon { color: var(--success-color, #43a047); --mdc-icon-size: 20px; }
  .emailuzenet button, .ekgombok button { font: inherit; font-size: 14px; border-radius: 16px; padding: 6px 14px; cursor: pointer;
    border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
  .ekgombok button.fo { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .emailkartya { padding: 10px 12px; border-left: 4px solid var(--primary-color); border-radius: 8px; background: var(--secondary-background-color, rgba(127,127,127,.08));
    display: flex; flex-direction: column; gap: 6px; }
  .ekcim { display: flex; align-items: center; gap: 8px; }
  .ekcim ha-icon { color: var(--primary-color); --mdc-icon-size: 20px; }
  .ekgombok { justify-content: flex-start; flex-wrap: wrap; margin-top: 2px; }
  dialog.emaildlg { width: min(520px, 94vw); max-height: 92vh; }
  .emaildlg p, .emaildlg li { font-size: 15px; line-height: 1.45; }
  .emnagy li { margin: 6px 0; }
  .emlepesek { display: flex; gap: 6px; list-style: none; padding: 0; margin: 0 0 12px; counter-reset: lep; }
  .emlepesek li { flex: 1; font-size: 12px !important; text-align: center; padding: 4px 2px; border-bottom: 3px solid var(--divider-color); color: var(--secondary-text-color); counter-increment: lep; }
  .emlepesek li::before { content: counter(lep) ". "; }
  .emlepesek li.aktiv { border-color: var(--primary-color); color: var(--primary-text-color); font-weight: 600; }
  .emlepesek li.kesz { border-color: var(--success-color, #43a047); }
  .emsugo { padding: 10px 12px; margin: 0 0 12px; border-radius: 8px; background: var(--secondary-background-color, rgba(127,127,127,.08)); font-size: 14px; }
  .emsugo ol { margin: 6px 0; padding-left: 20px; }
  .emsugo li { font-size: 14px !important; margin: 4px 0; }
  .emlink { display: inline-block; margin-top: 4px; font-weight: 500; color: var(--primary-color); }
  .emhalado { margin: 0 0 12px; }
  .emhalado summary { cursor: pointer; color: var(--secondary-text-color); font-size: 14px; margin-bottom: 8px; }
  .emhiba a { color: inherit; }
  .emkeres { display: flex; align-items: center; gap: 16px; padding: 12px 0; }
  .emkesz { font-size: 17px !important; color: var(--success-color, #43a047); }
  .emailsor { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 8px 0; font-size: 14px; color: var(--secondary-text-color); }
  .emailsor ha-icon { --mdc-icon-size: 18px; }
  .emailsor .emailpf { color: var(--primary-text-color); }
  .linkgomb { background: none; border: 0; padding: 0 2px; color: var(--primary-color); cursor: pointer; font: inherit; text-decoration: underline; }
  .teteltabla { border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }
  .teteltabla th, .teteltabla td { padding: 5px 8px; border-bottom: 1px solid var(--divider-color); text-align: right; white-space: nowrap; }
  .teteltabla th[scope="row"] { text-align: left; font-weight: 400; white-space: normal; }
  .teteltabla thead th { font-size: 12px; color: var(--secondary-text-color); font-weight: 500; }
  .teteltabla tbody td:nth-child(2), .teteltabla thead th:first-child { text-align: left; }
  .teteltabla tfoot th, .teteltabla tfoot td { border-bottom: 0; }
  .teteltabla tr.osszeg th, .teteltabla tr.osszeg td { font-weight: 700; font-size: 14px; border-top: 2px solid var(--primary-text-color); }
  .dfej { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: -4px -8px 4px 0; }
  .dfej h3 { margin: 0; outline: none; }
  .grafvezerlo { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 12px; }
  .grafvezerlo label.sor-label { flex-direction: row; align-items: center; gap: 6px; margin: 0; }
  .grafvezerlo select { font-size: 14px; padding: 4px 8px; }
  .szegmens { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 8px; overflow: hidden; }
  .szegmens button { font: inherit; font-size: 13px; padding: 6px 12px; border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer; }
  .szegmens button[aria-pressed="true"] { background: color-mix(in srgb, var(--primary-color) 16%, transparent); color: var(--primary-text-color); font-weight: 500; }
  .grafosszeg { display: flex; flex-wrap: wrap; gap: 8px 24px; margin-bottom: 8px; }
  .nagyobb { font-size: 20px; font-weight: 500; }
  .nagyobb.masodlagos { color: var(--secondary-text-color); }
  .grafdoboz { position: relative; }
  .grafdoboz svg { width: 100%; height: auto; display: block; touch-action: pan-y; }
  .grafvar { padding: 40px 0; text-align: center; }
  .grafdoboz .racs { stroke: var(--divider-color); stroke-width: 1; }
  .grafdoboz .alap { stroke: var(--secondary-text-color); stroke-width: 1; opacity: .6; }
  .grafdoboz .tengely { fill: var(--secondary-text-color); font-size: 11px; }
  .grafdoboz .hover { fill: transparent; }
  .grafdoboz .hover.aktiv { fill: color-mix(in srgb, var(--primary-text-color) 6%, transparent); }
  .grafdoboz .rud { pointer-events: none; }
  .rud.idei, .tjel.idei { fill: var(--primary-color); background: var(--primary-color); }
  .rud.elozo, .tjel.elozo { fill: color-mix(in srgb, var(--secondary-text-color) 55%, var(--card-background-color));
                            background: color-mix(in srgb, var(--secondary-text-color) 55%, var(--card-background-color)); }
  .rud.idei.becsult { fill: url(#csik-idei); }
  .napelemtabla th { text-align: center; }
  .mentesblokk { margin-top: 12px; } .mentesblokk summary { cursor: pointer; font-weight: 500; }
  .mentesblokk input[type="text"] { width: 100%; min-width: 120px; font-size: 14px; padding: 4px 6px; }
  .mentesblokk input[type="number"] { width: 70px; font-size: 14px; padding: 4px 6px; }
  .szenzortabla input { width: 100%; min-width: 220px; font-size: 14px; padding: 6px; }
  .szenzortabla tr.hianyzik td { background: color-mix(in srgb, var(--error-color, #db4437) 10%, transparent); }
  .szenzorgomb { position: absolute; top: 8px; right: 48px; color: var(--primary-color); }
  .szenzorhiany { background: color-mix(in srgb, var(--error-color, #db4437) 14%, transparent); border-radius: 8px; padding: 8px 12px; margin: 8px 0; font-size: 14px; }
  .mentessor { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
  .mentessor.ertcelok { gap: 6px 16px; }
  .fej .fejjel { display: inline-flex; align-items: center; justify-content: center; opacity: .8; }
  .mentessor label { margin-bottom: 0; }
  table.menteslista { width: 100%; border-collapse: collapse; font-size: 13px; }
  table.menteslista th, table.menteslista td { text-align: left; padding: 5px 6px; border-bottom: 1px solid var(--divider-color); vertical-align: top; }
  .mentesgombok { white-space: nowrap; text-align: right !important; }
  .szigetossz { list-style: none; padding: 0; margin: 10px 0 2px; font-size: 14px; }
  .szigetossz li::before { content: "☀ "; color: var(--warning-color, #ff9800); }
  .szigetido { display: flex; flex-wrap: wrap; gap: 4px; margin: 10px 0; }
  .szigetido button { font: inherit; font-size: 12px; padding: 3px 9px; border-radius: 12px; border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color); cursor: pointer; }
  .szigetido button[aria-pressed="true"] { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .szblokk { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--divider-color); }
  .szsorsz { display: flex; justify-content: space-between; gap: 8px; font-size: 14px; padding: 2px 0; }
  .szsorsz b { font-weight: 500; white-space: nowrap; }
  .szminoseg { margin-top: 10px; font-size: 13px; display: flex; align-items: center; gap: 6px; }
  .szminoseg.ok { color: var(--success-color, #43a047); } .szminoseg.figy { color: var(--warning-color, #ff9800); } .szminoseg.hiba { color: var(--error-color, #db4437); }
  .szminoseg ha-icon { --mdc-icon-size: 18px; }
  .szhavi { margin-top: 10px; } .szhavi summary { cursor: pointer; font-size: 13px; color: var(--secondary-text-color); }
  .szhavi table { width: 100%; border-collapse: collapse; font-size: 12px; } .szhavi th, .szhavi td { text-align: right; padding: 3px 5px; border-bottom: 1px solid var(--divider-color); white-space: nowrap; }
  .szhavi th:first-child, .szhavi td:first-child { text-align: left; }
  .napelemtabla td.tobblet { color: var(--success-color, #3f7a45); }
  .rud.elozo.becsult { fill: url(#csik-elozo); }
  .rud.becsult { stroke: currentColor; stroke-width: 0; }
  .mintaalap { fill-opacity: .35; }
  .rud.profil { fill-opacity: .7; }
  .rud.reszleges { stroke: var(--primary-text-color); stroke-width: 1.5; stroke-dasharray: 3 2; fill-opacity: .55; }
  .grafbecs { flex-basis: 100%; order: 9; }
  .graftip { position: absolute; top: 0; z-index: 2; pointer-events: none; background: var(--card-background-color); border: 1px solid var(--divider-color);
             border-radius: 8px; padding: 8px 10px; font-size: 13px; box-shadow: 0 2px 8px rgba(0,0,0,.25); white-space: nowrap; }
  .graftip .tcim { font-weight: 500; margin-bottom: 2px; }
  .osszesito { position: relative; }
  .kimutgomb { position: absolute; top: 8px; right: 8px; color: var(--primary-color); }
  .kimutgomb ha-icon { --mdc-icon-size: 22px; }
  .kimut table { border-collapse: separate; border-spacing: 0; font-size: 13px; min-width: 100%; font-variant-numeric: tabular-nums; }
  .kimut th, .kimut td { padding: 6px 10px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--divider-color); }
  .kimut thead th { position: sticky; top: 0; background: var(--card-background-color); vertical-align: bottom; font-weight: 500; }
  .kimut thead th ha-icon { --mdc-icon-size: 18px; display: block; margin-left: auto; color: var(--km-szin, var(--primary-color)); }
  .kimut thead th span { display: block; }
  .kimut thead th small { display: block; font-weight: 400; color: var(--secondary-text-color); font-size: 11px; }
  .kimut thead th { border-bottom: 2px solid var(--km-szin, var(--divider-color)); }
  .kimut .km-villany { --km-szin: #f0a020; } .kimut .km-gaz { --km-szin: #4a8fe0; } .kimut .km-viz { --km-szin: #27a5c4; } .kimut .km-hulladek { --km-szin: #7b9a52; } .kimut .km-tavho { --km-szin: #d0603a; } .kimut .km-kozos { --km-szin: #8a6fb0; } .kimut .km-tavkozles { --km-szin: #d04a8a; }
  .kimut th:first-child, .kimut td:first-child { position: sticky; left: 0; background: var(--card-background-color); text-align: left; z-index: 1; }
  .kimut tbody th { font-weight: 400; text-align: left; }
  .kimut tbody tr:nth-child(even) td, .kimut tbody tr:nth-child(even) th { background: color-mix(in srgb, var(--primary-text-color) 3%, var(--card-background-color)); }
  .kimut tbody tr.uressor { color: var(--secondary-text-color); }
  .kimut td.ures { color: var(--disabled-text-color, #9e9e9e); }
  .kimut td[data-cella] { cursor: pointer; }
  /* Várható (még nem érkezett) számla: narancs, dőlt – a táblázatban, a részletekben és a fiókkártyákon is. */
  .kmvarh { color: var(--rezsi-varhato, #c76a00); font-style: italic; }
  .kimut tr.kmvarhsor > * { background: color-mix(in srgb, #e08a00 9%, transparent) !important; font-size: .92em; }
  .kimut tr.kmvarhsor th { color: var(--rezsi-varhato, #c76a00); font-weight: 400; font-style: italic; padding-left: 1.2em; }
  .kimut tr.kmjovo th { color: var(--secondary-text-color); }
  .kimut td[data-cella]:hover, .kimut td.aktiv { background: color-mix(in srgb, var(--primary-color) 14%, transparent) !important; }
  .kimut td.minuszft { color: var(--success-color, #4caf50); }
  .fszkimut td, .fszkimut th { vertical-align: top; }
  .fszkimut .fszmegn { text-align: left; white-space: normal; min-width: 16em; }
  .fszkimut .fszmegn small { display: block; color: var(--secondary-text-color); font-size: 11px; font-weight: 400; }
  .fszkimut td.fszdatum { white-space: nowrap; }
  .fszkimut tr.fsznyito td, .fszkimut tr.fszzaro > * { font-weight: 600; }
  .fszkimut tr.fszfelt td { font-style: italic; color: var(--secondary-text-color); }
  .fszkimut tr.fsz-befizetes .fszmegn > span { color: var(--secondary-text-color); }
  .fszkimut tfoot td, .fszkimut tfoot th { border-top: 2px solid var(--divider-color); font-weight: 600; text-align: right; }
  .fszkimut tfoot th.fszmegn { text-align: left; }
  .fszelteres { color: var(--error-color, #db4437); }
  .turfizetes { color: var(--success-color, #4caf50); }
  .ertek.fedezett { color: var(--disabled-text-color, #9e9e9e); font-style: normal; }
  .fszfulek { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 8px; overflow: hidden; }
  .fszfulek button { font: inherit; padding: 5px 12px; border: 0; background: none; color: var(--primary-text-color); cursor: pointer; }
  .fszfulek button.aktiv { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .fszfulek[hidden] { display: none; }
  .fszkimut thead th small { display: block; font-weight: 400; font-size: 11px; color: var(--secondary-text-color); }
  .fszkimut td small { display: block; color: var(--secondary-text-color); font-size: 11px; }
  .fszallapot { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; white-space: normal; max-width: 9em; text-align: center; background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
  .fszallapot.all-fizetve { color: var(--success-color, #4caf50); background: color-mix(in srgb, var(--success-color, #4caf50) 14%, transparent); }
  .fszallapot.all-lejart { color: var(--error-color, #db4437); background: color-mix(in srgb, var(--error-color, #db4437) 14%, transparent); }
  .fszallapot.all-nyitott { color: var(--warning-color, #ffa600); background: color-mix(in srgb, var(--warning-color, #ffa600) 14%, transparent); }
  .fszallapot.all-tulfizetes, .fszallapot.all-beszamitva, .fszallapot.all-nincs { color: var(--info-color, #039be5); background: color-mix(in srgb, var(--info-color, #039be5) 12%, transparent); }
  .fszkimut tr.fszt-varhato td { font-style: italic; color: var(--rezsi-varhato, #c76a00); }
  .fszkozos { margin: 0 0 8px; }
  .fsznyitoszerk { margin-top: 12px; } .fsznyitoszerk summary { cursor: pointer; color: var(--primary-color); }
  .fsznyitosor { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; margin-top: 6px; }
  .fsznyitosor label { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--secondary-text-color); }
  .fsznyitosor .fszszeles { flex: 1 1 16em; } .fsznyitosor select { font: inherit; padding: 6px 8px; border: 1px solid var(--divider-color); border-radius: 6px; background: var(--card-background-color); color: var(--primary-text-color); }
  .fszkimut tr.fsz-kezi td { background: color-mix(in srgb, var(--primary-color) 6%, transparent); }
  .fsznyitosor input { font: inherit; padding: 6px 8px; border: 1px solid var(--divider-color); border-radius: 6px; background: var(--card-background-color); color: var(--primary-text-color); }
  .kimut .osszcella { font-weight: 500; border-left: 1px solid var(--divider-color); }
  .kimut tfoot th, .kimut tfoot td { font-weight: 600; border-top: 2px solid var(--divider-color); border-bottom: 0; }
  .kmdb { font-size: 10px; color: var(--secondary-text-color); margin-left: 3px; }
  .kmjel { display: inline-block; font-size: 9px; font-weight: 600; line-height: 1; padding: 2px 3px; margin-left: 4px; border-radius: 3px;
           vertical-align: 1px; color: var(--primary-color); border: 1px solid currentColor; }
  .dfejgombok { display: flex; gap: 4px; }
  .kimutreszlet { margin: 10px 0 4px; display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
  .kmsor .kicsi { display: block; }
  .lezartfiok { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px; border-radius: 8px; font-size: 13px;
                background: color-mix(in srgb, var(--warning-color, #ff9800) 14%, transparent); }
  .lezartfiok ha-icon { --mdc-icon-size: 18px; color: var(--warning-color, #ff9800); flex: none; }
  .dlink { display: flex; align-items: center; gap: 10px; width: 100%; font: inherit; font-size: 14px; color: var(--primary-text-color);
           background: transparent; border: 0; border-top: 1px solid var(--divider-color); padding: 10px 0 2px; cursor: pointer; text-align: left; }
  .dlink ha-icon { --mdc-icon-size: 20px; color: var(--primary-color); }
  .dlink span { flex: 1; }
  .dlink .chev { color: var(--secondary-text-color); }
  .grafdoboz .racs.fugg { opacity: .5; }
  .dvonal { fill: none; stroke-width: 1.4; stroke-linejoin: round; pointer-events: none; }
  .dvonal.a1, .tjel.a1 { stroke: var(--primary-color); background: var(--primary-color); }
  .dvonal.d, .tjel.d { stroke: var(--rezsi-d-szin, #e8710a); background: var(--rezsi-d-szin, #e8710a); }
  .dfogy, .tjel.dfogyjel { fill: color-mix(in srgb, var(--secondary-text-color) 30%, transparent); background: color-mix(in srgb, var(--secondary-text-color) 30%, transparent); }
  .dkeretben { fill: color-mix(in srgb, var(--success-color, #4caf50) 9%, transparent); }
  .dkeretfelirat { fill: var(--success-color, #4caf50); }
  .datlep { stroke: var(--warning-color, #ff9800); stroke-width: 1.5; }
  .datlepfelirat { fill: var(--warning-color, #ff9800); }
  .dkurzor { stroke: var(--secondary-text-color); stroke-width: 1; stroke-dasharray: 3 3; pointer-events: none; }
  .dhavi { margin: 8px 0; }
  .dhavi .tablagorgeto { overflow-x: auto; }
  .dhavi table { min-width: 0; }
  @media (max-width: 560px) { .dhavi .szeles { display: none; } .dhavi th, .dhavi td { padding: 4px 3px; } }
  .dhavi tbody tr { cursor: pointer; }
  .dhavi tbody tr.aktiv td { background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
  .dhavi tfoot td { font-weight: 500; border-top: 2px solid var(--divider-color); }
  #dmegj { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
  .tjel { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
  .grafjel { display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center; font-size: 13px; margin: 6px 0 8px; }
  .graftabla summary { cursor: pointer; font-size: 13px; color: var(--secondary-text-color); margin-bottom: 6px; }
  .graftabla table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .graftabla th, .graftabla td { text-align: right; padding: 4px 6px; border-bottom: 1px solid var(--divider-color); }
  .graftabla th:first-child, .graftabla td:first-child { text-align: left; }
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
