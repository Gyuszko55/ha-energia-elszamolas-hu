"""„Rezsikövető” oldalsáv-panel: statikus frontend (frontend/hu-rezsi-panel.js) és egy websocket-végpont az adatokhoz."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from aiohttp import web

from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .gaz_atalany import havi_mj
from .beallitas import elszamolas_mod, fix_dijas, idoszak_mod, reszszamlas
from . import fizetes
from . import szamlak as szamlak_mod
from .motor.dijszabas import ELLENORZES_ALLAPOTOK, VALIDALAS_ELSZAMOLAS, VALIDALAS_HMKE, VALIDALAS_SZAMLA
from .const import (
    OTTHON_BEALLITASOK,
    CONF_A2_CSUCS, CONF_A2_VOLGY, CONF_ALMERO, CONF_FORRAS, CONF_H_NYARI, CONF_H_TELI, CONF_KOZMU, CONF_NAPELEM,
    CONF_DIJSZABAS, CONF_SZAMLA_MAPPA, DOMAIN, EGYSEG,
)
from .ai_tajekoztato import ws_ai_tajekoztato
from .fejlec import fejlec
from .modell import szelet_dict
from .varhato_szamlak import varhato_szamlak
from .sensor import idenyszakok

_LOGGER = logging.getLogger(__name__)
STATIC_URL = "/hu_rezsi_static"
PANEL_URL = "rezsi"
MAPPA = Path(__file__).parent / "frontend"



def _havira(e: Any, tol: Any, ig: Any) -> int | None:
    """Egyhavi ütemű, de a hónaptól lényegesen eltérő hosszú időszak (pl. az éves leolvasás után a diktálásig tartó
    15 nap) várható díja egy átlagos hónapra arányosítva – a háztartás „Havi átlag”-ához. Az alapdíj számlánként jár,
    ezért azt nem arányosítjuk. Hónapnyi (25–35 napos) időszaknál None: a díj maga a havi összeg."""
    napok = (ig - tol).days if tol and ig else 0
    if not napok or 25 <= napok <= 35:
        return None
    alap = getattr(e, "alapdij_ft", 0) or 0
    return _ft((e.osszesen_ft - alap) * Decimal("30.44") / napok + alap)

def _f(x: Any, jegy: int = 2) -> float | None:
    return None if x is None else round(float(x), jegy)


def _ft(x: Any) -> int | None:
    return None if x is None else int(round(float(x)))


def _iso(x: date | datetime | None) -> str | None:
    return x.isoformat() if x else None


def _honapok(tol: date, ig: date) -> int:
    return max(1, (ig.year - tol.year) * 12 + ig.month - tol.month)


def _gaz_atalany(koord: Any, sub: Any) -> dict[str, Any] | None:
    """Gázmérő nélküli átalány: a havi díj alapja (szobaszám, tűzhely, MJ/hó, egységár) a fiók és a díjszabás szerint."""
    if sub.data.get("dijszabas") != "gaz/mero_nelkuli":
        return None
    mj = havi_mj(sub.data.get("szobaszam"), sub.data.get("tuzhely"))
    try:
        e = koord.tar.felold("gaz/mero_nelkuli", date.today(), sub.data.get("szolgaltato"))
        ar, afa = e.dijak.get("alapdij_ho"), e.dijak.get("afa")
    except Exception:  # noqa: BLE001 – a kártya ár nélkül is megjelenik
        ar, afa = None, None
    netto = (mj * ar).quantize(Decimal(1)) if mj is not None and ar is not None else None
    return {
        "szobaszam": sub.data.get("szobaszam"), "tuzhely": sub.data.get("tuzhely"), "mj": _f(mj, 0),
        "egysegar": _f(ar, 3), "afa": _f(afa, 0),
        "egysegar_brutto": _f(ar * (1 + Decimal(afa) / 100), 3) if ar is not None and afa is not None else None,
        "havi_netto": _f(netto, 0),
    }


def _almero_idenyben(koord: Any, azonosito: str | None) -> bool:
    """A díjszabás a locsolási almérőt csak az idényben vonja le (a panel csak akkor rögzíttet rá állást)."""
    try:
        return bool(koord.tar[azonosito].verzio(date.today()).szabalyok.get("almero_idoszak"))
    except Exception:  # noqa: BLE001
        return False


def _dijszabas_info(koord: Any, azonosito: str | None) -> dict[str, Any] | None:
    """A díjszabás ma érvényes verziójának forrása, érvényessége és ellenőrzöttsége (a Részletekhez)."""
    try:
        d = koord.tar[azonosito]
        v = d.verzio(date.today())
    except Exception:  # noqa: BLE001 – ismeretlen/egyedi díjszabás
        return None
    e = v.ellenorzes or {}
    return {
        "nev": d.nev, "ervenyes_tol": v.ervenyes_tol.isoformat(),
        "ervenyes_ig": v.ervenyes_ig.isoformat() if v.ervenyes_ig else None, "forras": v.forras,
        "allapot": e.get("allapot"), "allapot_szoveg": ELLENORZES_ALLAPOTOK.get(e.get("allapot"), "nincs megadva"),
        "ellenorizve": str(e["datum"]) if e.get("datum") else None, "mivel": e.get("mivel"),
        # Mely számlák igazolták (számlacsoportonként) – szolgáltató, elszámolási mód, számlatípus, egyezés.
        "validalas": [
            {
                "hely": x.get("hely"),
                "szolgaltato": (koord.tar.szolgaltatok.get(x["szolgaltato"]) or {}).get("nev") or x["szolgaltato"],
                "elszamolas": VALIDALAS_ELSZAMOLAS.get(x["elszamolas"], x["elszamolas"]),
                "hmke": VALIDALAS_HMKE.get(x.get("hmke")) if x.get("hmke") else None,
                "szamla_tipusok": [VALIDALAS_SZAMLA.get(t, t) for t in x["szamla_tipusok"]],
                "idoszak": x.get("idoszak"), "szamlak": x["szamlak"], "forintra": x["forintra"],
                "max_elteres_ft": x.get("max_elteres_ft"), "megjegyzes": x.get("megjegyzes"),
            }
            for x in e.get("validalas") or []
        ] or None,
    }


def _h_idenyszuro(leolv: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """H-tarifa a Mérőállások listában: egy napon csak az idényhez tartozó regiszter (nyáron 1.82, télen 1.81) –
    az 1.8.0 és a „befagyott” regiszter nem; ha mindkét regiszter fogyasztást mutat az előző állásához képest, mindkettő.
    Ha egy napon nincs regiszteres állás, az 1.8.0 marad. (Tárolva mind megmarad: a motor az 1.8.0-ból számol.)"""
    napok: dict[str, dict[str, dict[str, Any]]] = {}
    for x in leolv:
        if x["csatorna"] in ("fo", "h_teli", "h_nyari"):
            napok.setdefault(x["datum"], {})[x["csatorna"]] = x
    elozo: dict[str, float] = {}
    kihagy: set[int] = set()
    for nap in sorted(napok):
        n = napok[nap]
        regek = {c: n[c] for c in ("h_teli", "h_nyari") if c in n}
        if regek:
            if "fo" in n:
                kihagy.add(id(n["fo"]))
            nott = [c for c, x in regek.items() if c in elozo and x["allas"] > elozo[c]]
            teli = (int(nap[5:7]), int(nap[8:10])) >= (10, 15) or (int(nap[5:7]), int(nap[8:10])) <= (4, 15)
            marad = nott or ["h_teli" if teli else "h_nyari"]
            for c, x in regek.items():
                if c not in marad and len(regek) == 2:
                    kihagy.add(id(x))
        for c, x in regek.items():
            elozo[c] = x["allas"]
    return [x for x in leolv if id(x) not in kihagy]


def _fiok_adat(hass: HomeAssistant, koord: Any, sid: str, sub: Any) -> dict[str, Any]:
    a = (koord.data or {}).get(sid)
    tarolt = koord.tarolo.fiok(sid)
    # A fiók eszköze a háztartás bejegyzésén belül (az async_get_device 2027.8-tól megszűnik: az azonosítók nem
    # egyediek a bejegyzések között).
    eszkoz = next(
        (e for e in dr.async_entries_for_config_entry(dr.async_get(hass), koord.config_entry.entry_id) if (DOMAIN, sid) in e.identifiers),
        None,
    )
    kozmu = sub.data.get(CONF_KOZMU)
    adat: dict[str, Any] = {
        "sid": sid,
        "device_id": eszkoz.id if eszkoz else None,
        "nev": sub.title,
        "kozmu": kozmu,
        "fix_dij": fix_dijas(sub.data),
        "almero": bool(sub.data.get(CONF_ALMERO)),
        "napelem_mod": sub.data.get(CONF_NAPELEM, "nincs"),
        "dijszabas": sub.data.get("dijszabas"),
        "dijszabas_info": _dijszabas_info(koord, sub.data.get("dijszabas")),
        "almero_idenyben": _almero_idenyben(koord, sub.data.get("dijszabas")),
        # Gázmérő nélküli átalány: miből jön a havi díj (szobaszám, tűzhely → MJ/hó).
        "gaz_atalany": _gaz_atalany(koord, sub),
        # Több regiszteres mérő csatornái (a mérőállás-rögzítőhöz): H téli/nyári, A2 csúcs/völgy.
        "regiszterek": [c.szerep for c in koord.motor_fiok(sid).csatornak if c.szerep.startswith(("h_", "zona_"))],
        "reszszamlas": reszszamlas(sub.data),
        "elszamolas_mod": elszamolas_mod(sub.data),
        # Van-e saját mérő (szenzor) – a fejléc becslésének megbízhatóságához.
        "szenzor": any(sub.data.get(k) for k in (CONF_FORRAS, CONF_H_TELI, CONF_H_NYARI, CONF_A2_CSUCS, CONF_A2_VOLGY)),
        "szamlamappa": sub.data.get(CONF_SZAMLA_MAPPA),
        "hiba": a.hiba if a else "még nincs adat",
        "ismeretlen_fajlok": tarolt.get("ismeretlen_fajlok", []),
        "kezdes": tarolt.get("kezdes"),
        "kalibracio": [
            {
                "csatorna": szerep,
                "szorzo": float(k.szorzo) if k.szorzo else None,
                "arany": float(k.arany) if k.arany else None,
                "pontok": k.pontok,
                "napok": k.napok,
                "gyanus": [{"nap": n.isoformat(), "elteres": float(e)} for n, e in k.gyanus],
                "ugrasok": [{"nap": n.isoformat(), "mennyiseg": round(float(m), 1)} for n, m in k.ugrasok],
                "ok": k.ok,
            }
            for szerep, k in sorted(getattr(koord, "kalibraciok", {}).get(sid, {}).items())
        ],
    }
    # Számla-ellenőrzés (talált számlahibák) és a közös folyószámla egyenlege a legutóbbi számla szerint.
    adat["ellenorzes"] = getattr(koord, "ellenorzesek", {}).get(sid) or None
    folyo = max(((x.get("kelte") or "", k, x) for k, x in (tarolt.get("szamlak") or {}).items() if x.get("folyoszamla") is not None),
                default=None)
    adat["folyoszamla"] = {
        "osszeg": int(Decimal(str(folyo[2]["folyoszamla"]))), "kelte": folyo[0], "sorszam": folyo[1],
        # Érdekes, ha túlfizetés van, vagy a számlán más (átvezetett, kötbér stb.) tétel is áll; a sima tartozás (a
        # legutóbbi számlák fizetendője) nem.
        "erdekes": bool(folyo[2].get("egyeb_tetelek")) or Decimal(str(folyo[2]["folyoszamla"])) < 0,
    } if folyo else None
    ugyfel = max(((x.get("kelte") or "", x["ugyfel"]) for x in (tarolt.get("szamlak") or {}).values() if x.get("ugyfel")), default=None)
    adat["ugyfel"] = ugyfel[1] if ugyfel else None
    if a is None or a.nyitott is None:
        return adat
    ny = a.nyitott
    # Diktálásos/leolvasásos időszak egy számla, akkor is, ha átnyúlik a következő hónapba (pl. az éves leolvasás után a
    # második hónap diktálásáig, ~46 nap) – nem többhavi („negyedéves”) számlázás.
    honap = 1 if idoszak_mod(sub.data)[0] in ("diktalas", "leolvasas") else _honapok(a.tol, a.ig)
    szeletek = ny.eddig.szeletek
    keret_csat = next((s.csatorna for s in szeletek if s.keret is not None), None)  # H-tarifánál a nyári regiszter
    # A2: a két zóna (csúcs + völgy) közös kerete – mindkét csatorna szeletei.
    keretes = [
        s for s in szeletek
        if s.keret is not None and (s.csatorna == keret_csat or (keret_csat or "").startswith("zona_") and s.csatorna.startswith("zona_"))
    ]
    keret = None
    if keretes:
        felh = sum(((s.elszamolt if s.elszamolt is not None else s.mennyiseg) for s in keretes), Decimal(0))
        if keretes[0].keret_eves:
            # Éves keret (pl. gáz átalánynál): minden szelet a még hátralévő éves keretet hordozza; a csík az egész évé –
            # az év elejétől felhasznált (az időszak előtti + az időszakbeli) a teljes éves kerethez.
            evi = keretes[0].keret_evi if keretes[0].keret_evi is not None else keretes[0].keret
            ossz, felh, mod = evi, evi - keretes[0].keret + felh, "eves"
        else:
            # Időszakos keret: a számla napjaira jutó rész (gáz diktálásnál havonta súlyozott, villanynál napi arányos).
            ossz = sum((s.keret for s in keretes), Decimal(0))
            mod = "havi_sulyozott" if kozmu == "gaz" else "idoszak"
        if a.keret_ev:
            # Gáz: mindig az éves keret, az év elejétől ténylegesen felhasznált; diktálásnál mellette a számla
            # (havonta súlyozott) kerete.
            # Szaldónál nincs havi (számlánkénti) keret: csak az éves, a nettó vételezésre.
            idoszak = {"osszes": _f(ossz, 1), "felhasznalt": _f(felh, 1)} if mod != "eves" and not a.keret_ev.get("szaldo") else None
            ossz, felh, mod = Decimal(str(a.keret_ev["osszes"])), Decimal(str(a.keret_ev["felhasznalt"])), "eves"
        else:
            idoszak = None
        keret = {
            "idoszak": idoszak,
            "ev_tol": a.keret_ev["tol"] if a.keret_ev else None,
            "mod": mod,
            "osszes": _f(ossz, 1),
            "felhasznalt": _f(felh, 1),
            "hatralevo": _f(Decimal(str(a.keret_ev["hatralevo"])), 1) if a.keret_ev else _f(ny.hatralevo_keret, 1),
            "egyseg": {"m3": "m³"}.get(keretes[0].egyseg, keretes[0].egyseg) or a.egyseg,
            # Szaldónál a keret éves, a nettó vételezésre: a havi vételezésből számolt átlépés nem értelmes.
            "atlepes": None if a.keret_ev and a.keret_ev.get("szaldo") else _iso(ny.varhato_keretatlepes),
            "savkorrekcio": _f(sum((s.savkorrekcio for s in keretes), Decimal(0)), 1),
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
                "havi_resz": _ft(ny.varhato.osszesen_ft / honap) if honap > 1 else _havira(ny.varhato, a.tol, a.ig),
                "mennyiseg": _f(ny.varhato.mennyiseg, 1),
                "napi_atlag": _f(ny.napi_atlag[0], 2) if ny.napi_atlag else None,
                "eltelt_nap": _f(ny.eltelt_nap, 1),
                "hatralevo_nap": _f(ny.hatralevo_nap, 1),
            },
            "keret": keret,
            "uton_szamlak": a.uton_szamlak or None,
            "beszamitas": a.beszamitas,
            "megszunt": a.megszunt,
            "szunetel": a.szunetel,
            "d_osszevetes": a.d_osszevetes,
            "diktalt_szamla": a.diktalt_szamla,
            "diktalas_szerint": a.diktalas_szerint,
            "egyenleg_hiba": a.egyenleg_hiba,
            "idenyszakok": {"eddig": idenyszakok(ny.eddig), "varhato": idenyszakok(ny.varhato)} if idenyszakok(ny.eddig) else None,
            "atalany": a.atalany,
            "esedekes": {**a.esedekes, "kovetkezo_datum": _iso(a.esedekes["kovetkezo_datum"]),
                         **({"vegszamla": {**a.esedekes["vegszamla"], "datum": _iso(a.esedekes["vegszamla"]["datum"])}}
                            if a.esedekes.get("vegszamla") else {})} if a.esedekes else None,
            "szamlazasi": {**a.szamlazasi, "tol": _iso(a.szamlazasi["tol"]), "ig": _iso(a.szamlazasi["ig"])} if a.szamlazasi else None,
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
                    # A regiszter is (H: h_teli / h_nyari, A2: zona_*), hogy a listában látsszon, melyiké az állás.
                    "csatorna": csat if csat == "almero" else ("fo" if (lo.get("csatorna") or "vetelezes") == "vetelezes" else lo["csatorna"]),
                    "mero": m.get("gyari_szam") or "", "elszamolasi": bool(lo.get("elszamolasi")),
                    "megjegyzes": lo.get("megjegyzes", ""),
                })
    if sub.data.get("dijszabas") == "villany/h":
        leolv = _h_idenyszuro(leolv)
    if origo := tarolt.get("kezdo_origo"):
        # A fiókban megadott kezdő óraállás: az elszámolások origója (lásd modell.kezdo_origo_szinkron).
        leolv.append({
            "datum": origo["datum"], "allas": _f(Decimal(origo["allas"]), 3), "tipus": "kezdo", "csatorna": "fo",
            "mero": (tarolt.get("merok") or [{}])[0].get("gyari_szam") or "", "elszamolasi": True,
            "megjegyzes": "Kezdő óraállás",
        })
    for x in getattr(a, "szamla_allasok", None) or []:
        # Átalányszámla szerinti (feltételezett) állás – tájékoztató, a számolást nem befolyásolja.
        leolv.append({
            "datum": x["datum"], "allas": x["allas"], "tipus": "szamla_atalany", "csatorna": "fo",
            "mero": (tarolt.get("merok") or [{}])[0].get("gyari_szam") or "", "elszamolasi": False,
            "megjegyzes": f"számla alapján (átalány {x['mennyiseg']:g}, {x['sorszam']})",
        })
    # Csatornánként a legutolsó rögzített állás – a mérőállás-ablak ebből tölti elő a mezőket (H-nál a regisztereket is).
    utolso: dict[str, dict[str, Any]] = {}
    for csat, lista in (("vetelezes", tarolt.get("merok", [])), ("almero", tarolt.get("almero_merok", []))):
        for lo in (lo for m in lista[-1:] for lo in m.get("leolvasasok", [])):
            c = "almero" if csat == "almero" else (lo.get("csatorna") or "vetelezes")
            if c not in utolso or lo["datum"] > utolso[c]["datum"]:
                utolso[c] = {"datum": lo["datum"], "allas": _f(Decimal(str(lo["allas"])), 3)}
    adat["utolso_allasok"] = utolso
    # Jóváhagyásra váró számlák (a számlamappából) és az előnézetük: mi változna a jóváhagyással.
    adat["fuggo"] = tarolt.get("fuggo") or []
    adat["fuggo_elonezet"] = koord.elonezet.get(sid) if adat["fuggo"] else None
    # A kezdő óraállás mindig látszik (a legrégebbi), a többi a legutóbbi 15 nap állásai (regiszterenként – H-nál,
    # napelemnél egy napra több sor jut, a 2.8.0 se szoruljon ki).
    leolv = sorted(leolv, key=lambda x: (x["datum"], x["csatorna"] == "fo"), reverse=True)
    napok15 = sorted({x["datum"] for x in leolv}, reverse=True)[:15]
    adat["leolvasasok"] = [x for x in leolv if x["datum"] in napok15 or x.get("tipus") == "kezdo"]
    fiz = koord.fizetes_allapotok(sid) if hasattr(koord, "fizetes_allapotok") else {}
    javitas = tarolt.get("szamla_javitas") or {}
    adat["szamlak"] = sorted(
        # A lenyíló részletekhez a számla minden tárolt adata (a fájl elérési útja nélkül, csak a neve).
        ({"sorszam": k, "javitas": javitas.get(k), **{kk: v.get(kk) for kk in (
            "kelte", "osszeg", "tipus", "kezi", "forras", "fajl", "idoszak", "utolso_valodi_allas", "arszabas",
            "atalany_mennyiseg", "diktalasi_ablak", "kovetkezo_leolvasas", "kovetkezo_diktalas", "elszamolt_kwh",
            "elszamolt_gaz", "elszamolt_viz", "kovetkezo_resz_m3", "megjegyzes", "hatarido",
        )}, "fizetes": fiz.get(k)} for k, v in (koord.javitott_szamlak(sid) if hasattr(koord, "javitott_szamlak") else tarolt.get("szamlak") or {}).items()),
        key=lambda x: x["kelte"], reverse=True,
    )[:24]
    kihagy = szamlak_mod.ervenytelenek(tarolt.get("szamlak") or {})  # stornó + sztornózott
    adat["fizetes"] = fizetes.osszesito([x for k, x in fiz.items() if k not in kihagy], date.today())
    # A kártya fejléce: következő számla · folyó időszak · folyószámla-egyenleg (MVM-nél a közös folyószámláé).
    egyenleg = None
    if tarolt.get("szamlak") and hasattr(koord, "folyoszamla"):
        try:
            k = koord.folyoszamla(sid, True)
            egyenleg = {"osszeg": round(k["zaro"]), "kozos": k["nev"] if k.get("kozos") else None}
        except Exception:  # noqa: BLE001 – a fejléc egyenlege ne vigye el a panelt
            _LOGGER.exception("%s: a folyószámla-egyenleg nem számolható", sub.title)
    try:
        adat["fejlec"] = fejlec(adat, tarolt.get("szamlak") or {}, dt_util.now().date(), egyenleg)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("%s: a kártya fejléce nem számolható", sub.title)
        adat["fejlec"] = None
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
        # Fix díjas (pl. negyedéves szemétszállítás) fiók csak az esedékesség hónapjában, a teljes számlaösszeggel.
        def havi(f: dict[str, Any], kulcs: str, at: str) -> int:
            if f.get("fix_dij"):
                return (f.get("esedekes") or {}).get("e_havi_osszesen", 0)
            # Diktálás szerint számlázott átalányos fióknál a mért díj (átalányt nem számláznak).
            return f["atalany"][at] if f.get("atalany") and not f.get("diktalas_szerint") else f[kulcs]["havi_resz"] or f[kulcs]["osszeg"]

        # A korábbi hónapban lezárt (megszüntetett) fiók a havi összegekben már nem szerepel; a végszámlája (úton lévő
        # számla) igen, amíg meg nem érkezik.
        ho_eleje = date.today().replace(day=1).isoformat()
        aktiv = [f for f in fiokok if not (f.get("megszunt") and f["megszunt"]["datum"] < ho_eleje)]
        eddig = sum(havi(f, "eddig", "eddig") for f in aktiv if f.get("eddig"))
        varhato = sum(havi(f, "varhato", "havi") for f in aktiv if f.get("varhato"))
        # A szolgáltató közös folyószámlája (MVM: egy ügyfél minden villany-fiókja egy számlán): a legutóbbi számla
        # szerinti egyenleg, és ha a talált (nyitott) számlahibákat kijavítják, a várható egyenleg.
        # Csak a közös folyószámla fiókjai (más szolgáltató – pl. a víz – számláján közölt egyenleg nem ez).
        kozos_f = [f for f in fiokok if ((f.get("fejlec") or {}).get("egyenleg") or {}).get("kozos")]
        folyo = max((f["folyoszamla"] | {"fiok": f["nev"]} for f in kozos_f if f.get("folyoszamla")),
                    key=lambda x: (x["kelte"], x["sorszam"]), default=None)
        if folyo:
            hibak = [t for f in kozos_f for t in (f.get("ellenorzes") or []) if t["sulyos"] and not t["rendezve"]]
            folyo["korrigalt"] = folyo["osszeg"] + sum(t["hatas_ft"] for t in hibak)
            folyo["hibak_db"] = len(hibak)
        haztartasok.append({
            "entry_id": entry.entry_id,
            "folyoszamla": folyo,
            "nev": entry.title,
            "frissitve": _iso(koord.last_update_success_time) if hasattr(koord, "last_update_success_time") else None,
            # Esedékes: a számlázási ütem szerinti e havi számlák + a még meg nem érkezett (úton lévő) számlák.
            # A lezárt fiók végszámlája (fix díjnál esedékességként) az esedékes összegben marad.
            "osszesen": {"eddig": eddig, "varhato": varhato, "esedekes": sum((f.get("esedekes") or {}).get("e_havi_osszesen", 0) for f in fiokok)
                         + sum(x["osszeg"] for f in fiokok for x in (f.get("uton_szamlak") or []))},
            "fiokok": fiokok,
            # Szigetüzemi rendszerek (kísérleti): csak kWh, a rezsiösszegbe nem számít.
            "szigetek": [koord.sziget_allapot[sid] for sid in koord.config_entry.subentries if sid in getattr(koord, "sziget_allapot", {})],
            # Hiányzó szenzorok (pl. visszaállítás után új rendszerben): a panel a hozzárendelő táblázatot ajánlja.
            "hianyzo_szenzorok": _hianyzo_szenzorok(hass, entry),
        })
    connection.send_result(msg["id"], {"haztartasok": haztartasok, "ma": date.today().isoformat()})


def _nem_szamlazott(a: Any) -> int:
    """Esedékes, de még nem számlázott összeg: e havi várható számla + úton lévő számlák (mint a panel összesítője)."""
    if not a:
        return 0
    return int((a.esedekes or {}).get("e_havi_varhato") or 0) + sum(int(x.get("osszeg") or 0) for x in (a.uton_szamlak or []))

TARIFA_JEL = {"a1": "A1", "a2": "A2", "b": "B", "b_geo": "GEO", "b_komfort": "B Komfort", "d": "D", "h": "H", "hmke": "HMKE"}


def _tarifa_jel(beall: dict[str, Any]) -> str | None:
    """Villanynál a díjszabás rövid jele a kártyára (A1, H, B…); más közműnél nincs."""
    ds = str(beall.get(CONF_DIJSZABAS) or "")
    return TARIFA_JEL.get(ds.split("/")[-1], ds.split("/")[-1].upper() or None) if ds.startswith("villany/") else None


def fiok_fizetendok(koord: Any, ma: date) -> list[dict[str, Any]]:
    """Fiókonként a kifizetetlen (és ebből lejárt) számlák, valamint az esedékes, még nem számlázott összeg – az
    indítókártya és a háztartás „Fizetendő” szenzora közös forrása."""
    fiokok = []
    for sid, sub in koord.fiokok().items():
        tarolt, a = koord.tarolo.fiok(sid), (koord.data or {}).get(sid)
        szamlak = tarolt.get("szamlak") or {}
        fiz = koord.fizetes_allapotok(sid) if hasattr(koord, "fizetes_allapotok") else {}
        kihagy = szamlak_mod.ervenytelenek(szamlak)  # stornó + sztornózott
        o = fizetes.osszesito([x for k, x in fiz.items() if k not in kihagy], ma)
        fiokok.append({"sid": sid, "nev": sub.title, "kozmu": sub.data.get(CONF_KOZMU), "megszunt": bool(a and a.megszunt),
                       "nyitott_ft": o["nyitott_ft"], "nyitott_db": o["nyitott_db"], "lejart_ft": o["lejart_ft"],
                       "lejart_db": o["lejart_db"], "hatarido": o["kovetkezo_hatarido"],
                       # Esedékes, de még nem számlázott (a panelen sárga dőlt „még nem érkezett”): az e havi várható
                       # számla + a lezárt, még nem számlázott időszakok (úton lévő számlák) fizetendője.
                       "varhato_ft": _nem_szamlazott(a),
                       # Mérőállások (csak a szenzoros csatornák) – a kártya élőben lépteti a szenzor értékével.
                       "allasok": getattr(koord, "mero_allasok", {}).get(sid, []),
                       "tarifa": _tarifa_jel(sub.data), "egyseg": EGYSEG.get(sub.data.get(CONF_KOZMU), "")})
    return fiokok


@websocket_api.websocket_command({vol.Required("type"): "hu_rezsi/kartya"})
@callback
def ws_kartya(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Az indítókártya (rezsikoveto-kartya) adatai: otthononként a fiókok kifizetetlen számlái – könnyű lekérés, a
    panel teljes számítása (hu_rezsi/adatok) nélkül."""
    ma = date.today()
    hazak, kesz = [], True
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            kesz = kesz and entry.state is not ConfigEntryState.SETUP_IN_PROGRESS
            continue
        koord = entry.runtime_data
        # Újraindítás után az első számolásig a Díjnet-fizetések hiányoznak: a kártya addig vár (nem mutat hamis tartozást).
        kesz = kesz and koord.data is not None and getattr(koord, "dijnet_kesz", True)
        fiokok = fiok_fizetendok(koord, ma)
        # Az otthon fűtés- és hőmérséklet-beállítása (Konfigurálás); üresen a kártyán nincs hőmérséklet és füst.
        futes = {k: entry.options[k] for k in OTTHON_BEALLITASOK if entry.options.get(k)}
        hazak.append({"entry_id": entry.entry_id, "nev": entry.title, "fiokok": fiokok, "futes": futes or None})
    connection.send_result(msg["id"], {"haztartasok": hazak, "ma": ma.isoformat(), "kesz": kesz})


@websocket_api.websocket_command({vol.Required("type"): "hu_rezsi/folyoszamla", vol.Required("sid"): str,
                                  vol.Optional("egyutt", default=False): bool})
@websocket_api.async_response
async def ws_folyoszamla(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Egy fiók folyószámla-kivonata; egyutt: MVM közös folyószámlánál a csoport (minden tarifa) együtt."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED and msg["sid"] in entry.runtime_data.fiokok():
            try:
                connection.send_result(msg["id"], entry.runtime_data.folyoszamla(msg["sid"], msg["egyutt"]))
            except Exception as err:  # noqa: BLE001 – a panelen jelenjen meg az ok
                _LOGGER.exception("Folyószámla hiba")
                connection.send_error(msg["id"], "hiba", str(err))
            return
    connection.send_error(msg["id"], "nincs", "Ismeretlen fiók.")


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/folyoszamla_nyito", vol.Required("sid"): str,
    vol.Optional("datum"): vol.Any(None, str), vol.Optional("osszeg"): vol.Any(None, vol.Coerce(float)),
    vol.Optional("egyutt", default=False): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_folyoszamla_nyito(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """A folyószámla nyitó egyenlegének kézi megadása (osszeg: None → törlés)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED and msg["sid"] in entry.runtime_data.fiokok():
            await entry.runtime_data.folyoszamla_nyito(msg["sid"], msg.get("datum"), msg.get("osszeg"))
            connection.send_result(msg["id"], entry.runtime_data.folyoszamla(msg["sid"], msg["egyutt"]))
            return
    connection.send_error(msg["id"], "nincs", "Ismeretlen fiók.")


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/folyoszamla_tetel", vol.Required("sid"): str, vol.Required("datum"): str,
    vol.Optional("megnevezes", default=""): str, vol.Optional("kovetel", default=0): vol.Coerce(float),
    vol.Optional("tartozik", default=0): vol.Coerce(float), vol.Optional("torles"): str,
    vol.Optional("egyutt", default=False): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_folyoszamla_tetel(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Kézi könyvelési tétel felvétele a folyószámlára, vagy „torles”: id szerinti törlése."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED and msg["sid"] in entry.runtime_data.fiokok():
            k = entry.runtime_data
            if msg.get("torles"):
                await k.folyoszamla_tetel_torles(msg["sid"], msg["torles"])
            else:
                await k.folyoszamla_tetel(msg["sid"], msg["datum"], msg.get("megnevezes", ""), msg.get("kovetel", 0), msg.get("tartozik", 0))
            connection.send_result(msg["id"], k.folyoszamla(msg["sid"], msg["egyutt"]))
            return
    connection.send_error(msg["id"], "nincs", "Ismeretlen fiók.")


@websocket_api.websocket_command({vol.Required("type"): "hu_rezsi/osszevetes", vol.Required("sid"): str})
@websocket_api.async_response
async def ws_osszevetes(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Egy fiók naptári havi fogyasztása és költsége az éves összevetés grafikonjához."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        koord = entry.runtime_data
        sub = koord.fiokok().get(msg["sid"])
        if sub is None:
            continue
        if fix_dijas(sub.data):
            connection.send_error(msg["id"], "nem_merheto", "Fix díjas szolgáltatásnál nincs fogyasztás-összevetés.")
            return
        try:
            honapok = await koord.havi_osszevetes(msg["sid"])
        except Exception as err:  # noqa: BLE001 – a panelen jelenjen meg az ok
            _LOGGER.exception("Éves összevetés hiba (%s)", sub.title)
            connection.send_error(msg["id"], "hiba", str(err))
            return
        a = (koord.data or {}).get(msg["sid"])
        connection.send_result(msg["id"], {"nev": sub.title, "egyseg": getattr(a, "egyseg", None), "honapok": honapok,
                                           "napelem": sub.data.get("napelem_mod") if sub.data.get("napelem_mod") in ("brutto", "szaldo") else None})
        return
    connection.send_error(msg["id"], "nincs_fiok", "Nincs ilyen fiók.")


@websocket_api.websocket_command(
    {vol.Required("type"): "hu_rezsi/d_elemzes", vol.Required("sid"): str, vol.Optional("honap"): str}
)
@websocket_api.async_response
async def ws_d_elemzes(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """A1 fiók: D-tarifa elemzés egy hónapra negyedórás bontásban (a panel D-elemzés ablakához)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        koord = entry.runtime_data
        sub = koord.fiokok().get(msg["sid"])
        if sub is None:
            continue
        try:
            adat = await koord.d_elemzes(msg["sid"], msg.get("honap"))
        except Exception as err:  # noqa: BLE001 – a panelen jelenjen meg az ok
            _LOGGER.exception("D-elemzés hiba (%s)", sub.title)
            connection.send_error(msg["id"], "hiba", str(err))
            return
        connection.send_result(msg["id"], adat)
        return
    connection.send_error(msg["id"], "nincs_fiok", "Nincs ilyen fiók.")


@websocket_api.websocket_command({vol.Required("type"): "hu_rezsi/szamla_kimutatas", vol.Required("entry_id"): str})
@callback
def ws_szamla_kimutatas(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Egy otthon összes fiókjának összes tárolt számlája (a panel számlakimutatás-táblázatához)."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "nincs_otthon", "Nincs ilyen otthon.")
        return
    koord = entry.runtime_data
    sorrend = {"villany": 0, "gaz": 1, "viz": 2, "tavho": 3, "hulladek": 4, "kozos": 5, "tavkozles": 6}
    fiokok = []
    for sid, sub in koord.fiokok().items():
        tarolt = koord.tarolo.fiok(sid)
        fiz_ = koord.fizetes_allapotok(sid)
        szolg = sub.data.get("szolgaltato")
        try:
            varhato = varhato_szamlak(_fiok_adat(hass, koord, sid, sub), tarolt.get("szamlak") or {}, dt_util.now().date())
        except Exception:  # noqa: BLE001 – a várható számlák hiánya ne vigye el a kimutatást
            _LOGGER.exception("%s: várható számlák nem számolhatók", sub.title)
            varhato = []
        fiokok.append({
            "sid": sid,
            "nev": sub.title,
            "kozmu": sub.data.get("kozmu"),
            "varhato": varhato,
            "szolgaltato": (koord.tar.szolgaltatok.get(szolg) or {}).get("nev") or szolg,
            "szamlak": sorted(
                ({"sorszam": k, **{kk: x.get(kk) for kk in ("kelte", "osszeg", "szamlaertek", "tipus", "idoszak", "kezi",
                                                               "elszamolt_kwh", "elszamolt_gaz", "elszamolt_viz",
                                                               "egyeb_tetelek", "folyoszamla", "hatarido")},
                  "fizetes": fiz_.get(k)}
                 for k, x in (tarolt.get("szamlak") or {}).items() if x.get("kelte")),
                key=lambda y: y["kelte"],
            ),
        })
    fiokok.sort(key=lambda f: (sorrend.get(f["kozmu"], 9), f["nev"]))
    connection.send_result(msg["id"], {"nev": entry.title, "fiokok": fiokok})


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/ellenorzes_dontes", vol.Required("entry_id"): str, vol.Required("sid"): str,
    vol.Required("kulcs"): str, vol.Required("dontes"): vol.In(["rendezve", "nyitott"]),
})
@websocket_api.require_admin  # adatot ír: csak rendszergazda (a fizetés – hu_rezsi/fizetes – mindenkinek)
@websocket_api.async_response
async def ws_ellenorzes_dontes(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Talált számlahiba „rendezve” (reklamáltam / megjött a helyesbítés) vagy vissza „nyitott”-ra."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "nincs_otthon", "Nincs ilyen otthon.")
        return
    await entry.runtime_data.ellenorzes_dontes(msg["sid"], msg["kulcs"], msg["dontes"])
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/fuggo_dontes", vol.Required("entry_id"): str, vol.Required("sid"): str,
    vol.Required("dontes"): vol.In(["jovahagy", "elvet"]), vol.Optional("sorszamok"): [str],
})
@websocket_api.require_admin  # adatot ír: csak rendszergazda (a fizetés – hu_rezsi/fizetes – mindenkinek)
@websocket_api.async_response
async def ws_fuggo_dontes(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Jóváhagyásra váró számla jóváhagyása vagy elvetése a panelről."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "nincs_otthon", "Nincs ilyen otthon.")
        return
    try:
        eredmeny = await entry.runtime_data.fuggo_dontes(msg["sid"], msg["dontes"], msg.get("sorszamok"))
    except (KeyError, ValueError) as err:
        connection.send_error(msg["id"], "hiba", str(err))
        return
    connection.send_result(msg["id"], eredmeny)


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/varhato_tetelek", vol.Required("entry_id"): str, vol.Required("sid"): str,
    vol.Optional("tol"): str, vol.Optional("ig"): str,
})
@websocket_api.async_response
async def ws_varhato_tetelek(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Tételes (számlaszerű) bontás egy még nem érkezett számlára: a megadott időszakra, vagy a fiók következő
    várható számlájára (saját mérés / becslés)."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "nincs_otthon", "Nincs ilyen otthon.")
        return
    koord = entry.runtime_data
    sid = msg["sid"]
    if sid not in koord.fiokok():
        connection.send_error(msg["id"], "nincs_fiok", "Nincs ilyen fiók.")
        return
    tol, ig, forras = msg.get("tol"), msg.get("ig"), None
    if not (tol and ig):
        sub = koord.fiokok()[sid]
        tarolt = koord.tarolo.fiok(sid)
        lista = [v for v in varhato_szamlak(_fiok_adat(hass, koord, sid, sub), tarolt.get("szamlak") or {}, dt_util.now().date())
                 if v.get("tol") and v.get("ig") and v["forras"] in ("meres", "diktalas")]
        if not lista:
            connection.send_error(msg["id"], "nincs", "Ennél a fióknál nincs mérésből becsülhető következő számla (átalány vagy fix díj).")
            return
        tol, ig, forras = lista[0]["tol"], lista[0]["ig"], lista[0]["forras"]
    try:
        eredmeny = await koord.tetelek(sid, date.fromisoformat(tol), date.fromisoformat(ig))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "hiba", f"A tételes bontás nem számolható: {err}")
        return
    connection.send_result(msg["id"], eredmeny | {"forras": forras, "fiok": koord.fiokok()[sid].title})


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/fizetes", vol.Required("entry_id"): str, vol.Required("sid"): str,
    vol.Required("sorszam"): str, vol.Required("fizetve"): vol.Any(bool, None), vol.Optional("datum"): vol.Any(str, None),
})
@websocket_api.async_response
async def ws_fizetes(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Egy számla pénzügyi teljesítése: fizetve (dátummal) / nincs fizetve / None: vissza a Díjnet szerintire."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "nincs_otthon", "Nincs ilyen otthon.")
        return
    try:
        await entry.runtime_data.fizetes_rogzit(
            msg["sid"], msg["sorszam"], msg["fizetve"], date.fromisoformat(msg["datum"]) if msg.get("datum") else None)
    except ValueError as err:
        connection.send_error(msg["id"], "hiba", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/szamla_javitas", vol.Required("entry_id"): str, vol.Required("sid"): str,
    vol.Required("sorszam"): str, vol.Optional("fizetve"): vol.Any(bool, None), vol.Optional("datum"): vol.Any(str, None),
    vol.Optional("hatarido"): vol.Any(str, None), vol.Optional("megjegyzes", default=""): vol.All(str, vol.Length(max=500)),
})
@websocket_api.require_admin  # adatot ír: csak rendszergazda (a fizetés – hu_rezsi/fizetes – mindenkinek)
@websocket_api.async_response
async def ws_szamla_javitas(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Számla kézi javítása: fizetés (ha a kérés tartalmazza; None: vissza a Díjnet szerintire), határidő, megjegyzés."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "nincs_otthon", "Nincs ilyen otthon.")
        return
    try:
        fiz = None
        if "fizetve" in msg:
            fiz = {"fizetve": msg["fizetve"], "datum": date.fromisoformat(msg["datum"]) if msg.get("datum") else None}
        await entry.runtime_data.szamla_javitas(
            msg["sid"], msg["sorszam"], fizetes=fiz,
            hatarido=date.fromisoformat(msg["hatarido"]) if msg.get("hatarido") else None, megjegyzes=msg["megjegyzes"])
    except ValueError as err:
        connection.send_error(msg["id"], "hiba", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/dij_elteres", vol.Required("entry_id"): str, vol.Required("sid"): str,
    vol.Required("sorszam"): str, vol.Required("dontes"): vol.In(["uj_dij", "egyszeri"]),
})
@websocket_api.require_admin  # adatot ír: csak rendszergazda (a fizetés – hu_rezsi/fizetes – mindenkinek)
@websocket_api.async_response
async def ws_dij_elteres(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Fix díjas fiók díjeltérése: a számla összege az új havidíj, vagy egyszeri eltérés (nem jelez tovább)."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "nincs_otthon", "Nincs ilyen otthon.")
        return
    try:
        await entry.runtime_data.dij_elteres_dontes(msg["sid"], msg["sorszam"], msg["dontes"])
    except ValueError as err:
        connection.send_error(msg["id"], "hiba", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/hatarido", vol.Required("entry_id"): str, vol.Required("sid"): str,
    vol.Required("sorszam"): str, vol.Required("hatarido"): vol.Any(str, None),
})
@websocket_api.require_admin  # adatot ír: csak rendszergazda (a fizetés – hu_rezsi/fizetes – mindenkinek)
@websocket_api.async_response
async def ws_hatarido(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Egy számla fizetési határideje kézzel (kézi számla); None: törlés."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "nincs_otthon", "Nincs ilyen otthon.")
        return
    try:
        await entry.runtime_data.hatarido_rogzit(
            msg["sid"], msg["sorszam"], date.fromisoformat(msg["hatarido"]) if msg.get("hatarido") else None)
    except ValueError as err:
        connection.send_error(msg["id"], "hiba", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/eves_kimutatas", vol.Required("entry_id"): str, vol.Required("sid"): str,
    vol.Optional("ev_tol"): str,
})
@websocket_api.async_response
async def ws_eves_kimutatas(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Éves elszámolási kimutatás egy villanyfiókra (A1, H): a mérés és a díjszabás szerint vs. az elszámoló számlák."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "nincs_otthon", "Nincs ilyen otthon.")
        return
    koord = entry.runtime_data
    if msg["sid"] not in koord.fiokok():
        connection.send_error(msg["id"], "nincs_fiok", "Nincs ilyen fiók.")
        return
    try:
        eredmeny = await koord.eves_kimutatas(msg["sid"], date.fromisoformat(msg["ev_tol"]) if msg.get("ev_tol") else None)
    except ValueError as err:
        connection.send_error(msg["id"], "nem_keszitheto", str(err))
        return
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("éves kimutatás")
        connection.send_error(msg["id"], "hiba", f"A kimutatás nem készíthető: {err}")
        return
    connection.send_result(msg["id"], eredmeny)


def _hianyzo_szenzorok(hass: HomeAssistant, entry: Any) -> int:
    from . import mentes as mt  # noqa: PLC0415

    alar = [{"subentry_id": sid, "subentry_type": x.subentry_type, "title": x.title, "data": dict(x.data)} for sid, x in entry.subentries.items()]
    return len({h["entity_id"] for h in mt.szenzor_hivatkozasok(alar)} - set(hass.states.async_entity_ids("sensor")))


def _mentes_ws(fn):
    """Közös burok a mentés-parancsokhoz: csak admin, a MentesHiba üzenete a panelen jelenik meg."""
    @websocket_api.require_admin
    @websocket_api.async_response
    async def kezel(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
        from . import mentes as mt  # noqa: PLC0415

        try:
            connection.send_result(msg["id"], await fn(hass, msg))
        except mt.MentesHiba as err:
            connection.send_error(msg["id"], "mentes_hiba", str(err))
    return kezel


async def _mentesek(hass: HomeAssistant, msg: dict[str, Any]) -> dict[str, Any]:
    from . import mentes_ha  # noqa: PLC0415

    return {"mentesek": await mentes_ha.mentesek(hass), "beallitas": await mentes_ha.beallitas(hass)}


async def _mentes_beallitas(hass: HomeAssistant, msg: dict[str, Any]) -> dict[str, Any]:
    from . import mentes_ha  # noqa: PLC0415

    return await mentes_ha.beallitas_ment(hass, msg["beallitas"])


async def _mentes_helyek(hass: HomeAssistant, msg: dict[str, Any]) -> list[dict[str, Any]]:
    from . import mentes_ha  # noqa: PLC0415

    return await mentes_ha.hely_jeloltek(hass)


async def _ha_mentesek(hass: HomeAssistant, msg: dict[str, Any]) -> list[dict[str, Any]]:
    from . import mentes_ha  # noqa: PLC0415

    return await mentes_ha.ha_mentesek(hass)


async def _ha_mentesbol(hass: HomeAssistant, msg: dict[str, Any]) -> dict[str, Any]:
    from . import mentes_ha  # noqa: PLC0415

    return await mentes_ha.ha_mentesbol(hass, msg["backup_id"], msg.get("agent_id"))


def _otthon(hass: HomeAssistant, entry_id: str):  # noqa: ANN202
    from . import mentes as mt  # noqa: PLC0415

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise mt.MentesHiba("nincs ilyen otthon")
    return entry


async def _szenzor_lista(hass: HomeAssistant, msg: dict[str, Any]) -> dict[str, Any]:
    from . import mentes_ha  # noqa: PLC0415

    return mentes_ha.szenzor_lista(hass, _otthon(hass, msg["entry_id"]))


async def _szenzor_csere(hass: HomeAssistant, msg: dict[str, Any]) -> dict[str, Any]:
    from . import mentes_ha  # noqa: PLC0415

    return {"modositott": await mentes_ha.szenzor_csere(hass, _otthon(hass, msg["entry_id"]), msg["csere"])}


ws_mentesek = websocket_api.websocket_command({vol.Required("type"): "hu_rezsi/mentesek"})(_mentes_ws(_mentesek))
ws_mentes_beallitas = websocket_api.websocket_command(
    {vol.Required("type"): "hu_rezsi/mentes_beallitas", vol.Required("beallitas"): dict})(_mentes_ws(_mentes_beallitas))
ws_mentes_helyek = websocket_api.websocket_command({vol.Required("type"): "hu_rezsi/mentes_helyek"})(_mentes_ws(_mentes_helyek))
ws_ha_mentesek = websocket_api.websocket_command({vol.Required("type"): "hu_rezsi/ha_mentesek"})(_mentes_ws(_ha_mentesek))
ws_ha_mentesbol = websocket_api.websocket_command(
    {vol.Required("type"): "hu_rezsi/ha_mentesbol", vol.Required("backup_id"): str, vol.Optional("agent_id"): str})(_mentes_ws(_ha_mentesbol))
ws_szenzor_lista = websocket_api.websocket_command(
    {vol.Required("type"): "hu_rezsi/szenzor_lista", vol.Required("entry_id"): str})(_mentes_ws(_szenzor_lista))
ws_szenzor_csere = websocket_api.websocket_command(
    {vol.Required("type"): "hu_rezsi/szenzor_csere", vol.Required("entry_id"): str, vol.Required("csere"): list})(_mentes_ws(_szenzor_csere))


class MentesLetoltes(HomeAssistantView):
    """Egy mentés letöltése (csak adminnak) – a panel „Letöltés” gombja; hely sorszáma + mentésminta szerinti fájlnév."""

    url = "/api/hu_rezsi/mentes/{hely}/{fajl}"
    name = "api:hu_rezsi:mentes"
    requires_auth = True

    async def get(self, request: web.Request, hely: str, fajl: str) -> web.StreamResponse:
        from . import mentes as mt, mentes_ha  # noqa: PLC0415

        hass = request.app["hass"]
        if not request["hass_user"].is_admin:
            return web.Response(status=403)
        try:
            utvonal = await mentes_ha.fajl_utvonal(hass, int(hely), fajl)
        except (mt.MentesHiba, ValueError):
            return web.Response(status=404)
        return web.FileResponse(utvonal, headers={"Content-Disposition": f'attachment; filename="{fajl}"'})


async def _kartya_eroforras(hass: HomeAssistant, url: str) -> None:
    """Az indítókártya Lovelace-erőforrása (storage módban): felveszi, vagy új változatnál frissíti az URL-t."""
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415

        lv = hass.data[LOVELACE_DATA]
        res = lv.resources
        if getattr(lv, "resource_mode", "storage") != "storage" or not hasattr(res, "async_create_item"):
            return  # YAML-módú erőforrások: marad az extra modul
        await res.async_get_info()  # betölti a tárolt listát
        alap = url.split("?")[0]
        for elem in res.async_items():
            if str(elem.get("url", "")).split("?")[0] == alap:
                if elem["url"] != url:
                    await res.async_update_item(elem["id"], {"res_type": "module", "url": url})
                return
        await res.async_create_item({"res_type": "module", "url": url})
    except Exception:  # noqa: BLE001 – az erőforrás hiánya nem akadályozza az integrációt
        _LOGGER.warning("Az indítókártya Lovelace-erőforrása nem vehető fel", exc_info=True)


async def regisztral_panel(hass: HomeAssistant) -> None:
    """Egyszer, az integráció betöltésekor: statikus fájlok, websocket, oldalsáv-menüpont."""
    if hass.data.setdefault(DOMAIN, {}).get("panel"):
        return
    # A jelzőt az első await ELŐTT állítjuk: több otthon párhuzamosan töltődik be, különben kettő is regisztrálna.
    hass.data[DOMAIN]["panel"] = True
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(MAPPA), cache_headers=False)])
    websocket_api.async_register_command(hass, ws_adatok)
    websocket_api.async_register_command(hass, ws_kartya)
    websocket_api.async_register_command(hass, ws_osszevetes)
    websocket_api.async_register_command(hass, ws_folyoszamla)
    websocket_api.async_register_command(hass, ws_folyoszamla_nyito)
    websocket_api.async_register_command(hass, ws_folyoszamla_tetel)
    websocket_api.async_register_command(hass, ws_d_elemzes)
    websocket_api.async_register_command(hass, ws_szamla_kimutatas)
    websocket_api.async_register_command(hass, ws_fuggo_dontes)
    websocket_api.async_register_command(hass, ws_ellenorzes_dontes)
    websocket_api.async_register_command(hass, ws_varhato_tetelek)
    websocket_api.async_register_command(hass, ws_eves_kimutatas)
    websocket_api.async_register_command(hass, ws_fizetes)
    websocket_api.async_register_command(hass, ws_dij_elteres)
    websocket_api.async_register_command(hass, ws_szamla_javitas)
    websocket_api.async_register_command(hass, ws_hatarido)
    websocket_api.async_register_command(hass, ws_mentesek)
    websocket_api.async_register_command(hass, ws_ai_tajekoztato)  # kísérleti
    for parancs in (ws_mentes_beallitas, ws_mentes_helyek, ws_ha_mentesek, ws_ha_mentesbol, ws_szenzor_lista, ws_szenzor_csere):
        websocket_api.async_register_command(hass, parancs)
    hass.http.register_view(MentesLetoltes())
    # A betöltő verziója; a valódi panelt (rezsi-panel-fo.js) a betöltő a módosítási ideje szerint tölti be.
    verzio = (MAPPA / "hu-rezsi-panel.js").stat().st_mtime_ns
    # Az indítókártya (custom:rezsikoveto-kartya) minden oldalon betöltődik – erőforrásként nem kell felvenni.
    kv = (MAPPA / "rezsikoveto-kartya.js").stat().st_mtime_ns
    frontend.add_extra_js_url(hass, f"{STATIC_URL}/rezsikoveto-kartya.js?v={kv}")
    # Lovelace-erőforrásként is: a mobilalkalmazás HA-újraindítás után nem tölti újra az oldalt (az extra modul így
    # hiányozna – „Konfigurációs hiba”), az irányítópult erőforrásait viszont igen.
    async def _eroforras(_esemeny: Any = None) -> None:
        await _kartya_eroforras(hass, f"{STATIC_URL}/rezsikoveto-kartya.js?v={kv}")

    if hass.is_running:
        hass.async_create_task(_eroforras())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _eroforras)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name="hu-rezsi-panel",
        sidebar_title="Rezsikövető",
        sidebar_icon="mdi:home-lightning-bolt-outline",
        module_url=f"{STATIC_URL}/hu-rezsi-panel.js?v={verzio}",
        embed_iframe=False,
        require_admin=False,
    )
