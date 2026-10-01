"""„Rezsi” oldalsáv-panel: statikus frontend (frontend/hu-rezsi-panel.js) és egy websocket-végpont az adatokhoz."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import CONF_ALMERO, CONF_FIZETESI_MOD, CONF_KOZMU, CONF_NAPELEM, CONF_SZAMLA_MAPPA, DOMAIN, FIX_DIJAS
from .modell import szelet_dict
from .sensor import idenyszakok

_LOGGER = logging.getLogger(__name__)
STATIC_URL = "/hu_rezsi_static"
PANEL_URL = "rezsi"
MAPPA = Path(__file__).parent / "frontend"


def _f(x: Any, jegy: int = 2) -> float | None:
    return None if x is None else round(float(x), jegy)


def _ft(x: Any) -> int | None:
    return None if x is None else int(round(float(x)))


def _iso(x: date | datetime | None) -> str | None:
    return x.isoformat() if x else None


def _honapok(tol: date, ig: date) -> int:
    return max(1, (ig.year - tol.year) * 12 + ig.month - tol.month)


def _fiok_adat(hass: HomeAssistant, koord: Any, sid: str, sub: Any) -> dict[str, Any]:
    a = (koord.data or {}).get(sid)
    tarolt = koord.tarolo.fiok(sid)
    eszkoz = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, sid)})
    kozmu = sub.data.get(CONF_KOZMU)
    adat: dict[str, Any] = {
        "sid": sid,
        "device_id": eszkoz.id if eszkoz else None,
        "nev": sub.title,
        "kozmu": kozmu,
        "fix_dij": kozmu in FIX_DIJAS,
        "almero": bool(sub.data.get(CONF_ALMERO)),
        "napelem_mod": sub.data.get(CONF_NAPELEM, "nincs"),
        "reszszamlas": sub.data.get(CONF_FIZETESI_MOD) == "reszszamla",
        "szamlamappa": sub.data.get(CONF_SZAMLA_MAPPA),
        "hiba": a.hiba if a else "még nincs adat",
    }
    if a is None or a.nyitott is None:
        return adat
    ny = a.nyitott
    honap = _honapok(a.tol, a.ig)
    szeletek = ny.eddig.szeletek
    keret_csat = next((s.csatorna for s in szeletek if s.keret is not None), None)  # H-tarifánál a nyári regiszter
    keretes = [s for s in szeletek if s.keret is not None and s.csatorna == keret_csat]
    keret = None
    if keretes:
        ossz = sum((s.keret for s in keretes), Decimal(0))
        felh = sum(((s.elszamolt if s.elszamolt is not None else s.mennyiseg) for s in keretes), Decimal(0))
        keret = {
            "osszes": _f(ossz, 1),
            "felhasznalt": _f(felh, 1),
            "hatralevo": _f(ny.hatralevo_keret, 1),
            "egyseg": {"m3": "m³"}.get(keretes[0].egyseg, keretes[0].egyseg) or a.egyseg,
            "atlepes": _iso(ny.varhato_keretatlepes),
        }
    adat.update(
        {
            "egyseg": a.egyseg,
            "idoszak": {"tol": _iso(a.tol), "ig": _iso(a.ig), "honapok": honap},
            "eddig": {
                "osszeg": _ft(ny.eddig.osszesen_ft),
                "havi_resz": _ft(ny.eddig.osszesen_ft / honap) if honap > 1 else None,
                "energia": _ft(ny.eddig.energia_ft),
                "alapdij": _ft(ny.eddig.alapdij_ft),
                "mennyiseg": _f(ny.eddig.mennyiseg, 2),
                "becsult": ny.eddig.becsult,
                "szeletek": [szelet_dict(s) for s in szeletek],
            },
            "varhato": {
                "osszeg": _ft(ny.varhato.osszesen_ft),
                "havi_resz": _ft(ny.varhato.osszesen_ft / honap) if honap > 1 else None,
                "mennyiseg": _f(ny.varhato.mennyiseg, 1),
                "napi_atlag": _f(ny.napi_atlag[0], 2) if ny.napi_atlag else None,
                "eltelt_nap": _f(ny.eltelt_nap, 1),
                "hatralevo_nap": _f(ny.hatralevo_nap, 1),
            },
            "keret": keret,
            "idenyszakok": {"eddig": idenyszakok(ny.eddig), "varhato": idenyszakok(ny.varhato)} if idenyszakok(ny.eddig) else None,
            "atalany": a.atalany,
            "esedekes": {**a.esedekes, "kovetkezo_datum": _iso(a.esedekes["kovetkezo_datum"])} if a.esedekes else None,
            "utem": {**a.utem, "kovetkezo_elszamolas": _iso(a.utem.get("kovetkezo_elszamolas"))} if a.utem else None,
            "aktualis_ar": _f(a.aktualis_ar, 3),
            "eves": {"fogyasztas": _f(a.eves_fogyasztas, 1), "bazis": _iso(a.eves_bazis)},
            "utolso_lezart": a.utolso_lezart,
        }
    )
    if a.egyenleg:
        e = a.egyenleg
        adat["egyenleg"] = {
            "ev_tol": _iso(e.ev_tol), "ev_ig": _iso(e.ev_ig), "befizetve": _ft(e.befizetve),
            "hatralevo_reszszamla": _ft(e.hatralevo_reszszamla), "hatralevo_db": e.hatralevo_db,
            "teny_eddig": _ft(e.teny_eddig), "varhato_eves": _ft(e.varhato_eves), "egyenleg": _ft(e.varhato_egyenleg),
            "varhato_fogyasztas": _f(e.varhato_fogyasztas, 1), "modszer": e.modszer, "megbizhato": e.megbizhato,
            "elozo_ev": None if not e.elozo_ev else {
                "tol": _iso(e.elozo_ev["tol"]), "ig": _iso(e.elozo_ev["ig"]),
                "fizetve": _ft(e.elozo_ev["fizetve"]), "szamitott": _ft(e.elozo_ev["szamitott"]),
            },
        }
    if a.elszamolas:
        el = a.elszamolas
        adat["elszamolas"] = {
            "tol": _iso(el.tol), "tenyleges": _ft(el.tenyleges), "befizetve": _ft(el.befizetve),
            "egyenleg": _ft(el.egyenleg), "szamlak_db": el.szamlak_db, "mennyiseg": _f(el.mennyiseg, 1),
        }
    if a.napelem:
        n = a.napelem
        adat["napelem"] = {
            "mod": n.mod, "vetelezes": _f(n.vetelezes, 1), "betaplalas": _f(n.betaplalas, 1),
            "jovairas": _ft(n.jovairas_ft), "egyenleg": _ft(n.egyenleg_ft),
        }
    if a.szamla_stat:
        st = dict(a.szamla_stat)
        st["kovetkezo_datum"] = _iso(st.get("kovetkezo_datum"))
        adat["szamla_stat"] = st
    # Részletek: utolsó lezárt időszakok, leolvasások, számlák
    adat["lezart"] = sorted(tarolt.get("lezart", []), key=lambda x: x["tol"], reverse=True)[:12]
    adat["lezart"] = [{k: v for k, v in x.items() if k != "szeletek"} for x in adat["lezart"]]
    leolv = []
    for csat, lista in (("fo", tarolt.get("merok", [])), ("almero", tarolt.get("almero_merok", []))):
        for m in lista:
            for lo in m.get("leolvasasok", []):
                leolv.append({
                    "datum": lo["datum"], "allas": _f(Decimal(str(lo["allas"])), 3), "tipus": lo.get("tipus"),
                    "csatorna": "betaplalas" if lo.get("csatorna") == "betaplalas" else csat,
                    "mero": m.get("gyari_szam") or "", "elszamolasi": bool(lo.get("elszamolasi")),
                    "megjegyzes": lo.get("megjegyzes", ""),
                })
    adat["leolvasasok"] = sorted(leolv, key=lambda x: x["datum"], reverse=True)[:15]
    adat["szamlak"] = sorted(
        ({"sorszam": k, **{kk: v.get(kk) for kk in ("kelte", "osszeg", "tipus")}} for k, v in (tarolt.get("szamlak") or {}).items()),
        key=lambda x: x["kelte"], reverse=True,
    )[:12]
    return adat


@websocket_api.websocket_command({vol.Required("type"): "hu_rezsi/adatok"})
@callback
def ws_adatok(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    haztartasok = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        koord = entry.runtime_data
        fiokok = [_fiok_adat(hass, koord, sid, sub) for sid, sub in koord.fiokok().items()]
        # Havi fizetendő: átalánynál az átalány napra leosztva, egyébként a költség (több hónapos időszakból a havi rész).
        eddig = sum(
            (f["atalany"]["eddig"] if f.get("atalany") else f["eddig"]["havi_resz"] or f["eddig"]["osszeg"]) for f in fiokok if f.get("eddig")
        )
        varhato = sum(
            (f["atalany"]["havi"] if f.get("atalany") else f["varhato"]["havi_resz"] or f["varhato"]["osszeg"]) for f in fiokok if f.get("varhato")
        )
        haztartasok.append({
            "entry_id": entry.entry_id,
            "nev": entry.title,
            "frissitve": _iso(koord.last_update_success_time) if hasattr(koord, "last_update_success_time") else None,
            "osszesen": {"eddig": eddig, "varhato": varhato, "esedekes": sum((f.get("esedekes") or {}).get("e_havi_osszesen", 0) for f in fiokok)},
            "fiokok": fiokok,
        })
    connection.send_result(msg["id"], {"haztartasok": haztartasok, "ma": date.today().isoformat()})


async def regisztral_panel(hass: HomeAssistant) -> None:
    """Egyszer, az integráció betöltésekor: statikus fájlok, websocket, oldalsáv-menüpont."""
    if hass.data.setdefault(DOMAIN, {}).get("panel"):
        return
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(MAPPA), cache_headers=False)])
    websocket_api.async_register_command(hass, ws_adatok)
    verzio = (MAPPA / "hu-rezsi-panel.js").stat().st_mtime_ns  # gyorsítótár-ürítés frissítéskor
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name="hu-rezsi-panel",
        sidebar_title="Rezsi",
        sidebar_icon="mdi:home-lightning-bolt-outline",
        module_url=f"{STATIC_URL}/hu-rezsi-panel.js?v={verzio}",
        embed_iframe=False,
        require_admin=False,
    )
    hass.data[DOMAIN]["panel"] = True
