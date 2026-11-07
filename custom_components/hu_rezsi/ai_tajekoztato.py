"""AI-tájékoztató (KÍSÉRLETI): az otthon számláinak állása és a kilátások szövegesen, egy AI Task entitással.

A számokat a Rezsikövető számolja (a panel adataiból, tömörítve); az AI csak megfogalmaz. Az utolsó tájékoztató
otthononként tárolódik (`.storage/hu_rezsi.ai_tajekoztato`), így a kártya felugró ablaka azonnal mutatja, és csak
kérésre („Új tájékoztató”) készül új – minden új egy AI-hívás.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

TAROLO_KULCS = f"{DOMAIN}.ai_tajekoztato"
KOZMU_NEV = {"villany": "villany", "gaz": "gáz", "viz": "víz és csatorna", "tavho": "távhő", "hulladek": "szemétszállítás",
             "kozos": "közös költség", "tavkozles": "internet/TV/telefon"}

UTASITAS = """Egy magyar háztartás rezsiszámláiról kérek rövid tájékoztatót, MAGYARUL, közérthetően, tegező formában
(a család olvassa a telefonján). Csak a lenti JSON adataiból dolgozz: ne találj ki számot, dátumot vagy szolgáltatót, és
ne ismételd vissza az összes adatot – a lényeget emeld ki. Az összegeket egész forintra, ezres tagolással írd
(pl. 12 345 Ft), a dátumokat „okt. 26.” alakban. A becsült értékeknél mondd, hogy becslés.

Az adatok jelentése:
- "ma": a mai nap. "fiokok": szolgáltatásonként (villany, gáz, víz…) egy-egy fiók.
- "kifizetetlen": a kiállított, még nem fizetett számlák ("lejart_ft": a határidőn túliak). "nyitott_szamlak": ezek
  sorszám, kelte, összeg és határidő szerint.
- "kovetkezo_szamla": a következő várható számla időszaka, várható fizetendője ("fizetendo_ft") és kiállítási napja
  ("varhato_kelte"). "alap": "atalany" = a szerződött havi részszámla/átalány (a fogyasztástól független),
  "diktalas" = lezárt időszak, a mérőállás megvan, a díj a Rezsikövető számítása, "fix" = fix díj. "kesik": true =
  a számla a szokott időpontig nem érkezett meg.
- "folyo_idoszak": a most futó számlázási időszak eddigi és várható költsége ("tajekoztato": true = ezt nem így
  számlázzák, mert átalány megy; a különbség az éves elszámoláskor rendeződik). "becsult": nincs friss mérés.
- "eves_elszamolas": részszámlás (átalányos) fióknál az elszámolási év becslése: "befizetve_ft" eddig,
  "hatralevo_reszszamla_ft" még fizetendő részszámlák, "varhato_eves_koltseg_ft"; "varhato_egyenleg_ft" POZITÍV =
  visszatérítés (túlfizetés) várható, NEGATÍV = ráfizetés várható. "megbizhato": false esetén csak durva becslés.
- "elszamolas_ota": az utolsó elszámolás óta a tényleges költség és a befizetett összeg ("egyenleg_ft" POZITÍV =
  eddig többet fizettünk a tényleges fogyasztásnál).
- "folyoszamla_egyenleg_ft": a szolgáltatói folyószámla a legutóbbi számla szerint; NEGATÍV = túlfizetés (jóváírás),
  POZITÍV = tartozás. "kozos": több fiók közös folyószámlája (pl. MVM: minden villanyfiók egy számlán).
- "kedvezmenyes_keret": a rezsicsökkentett keret (villanynál kWh, gáznál MJ) – "felhasznalt", "osszes", és ha van,
  "varhato_atlepes" napja (utána drágább piaci ár jön).
- "szamlahibak": a Rezsikövető számla-ellenőrzésének eltérései (a számla és a saját számítás különbsége,
  "hatas_ft"); "sulyos": true = reklamálni érdemes.
- "fuggo_szamlak_db": jóváhagyásra váró, beolvasott számlák a panelen.
- "utem": szolgáltató, következő éves elszámolás/leolvasás, diktálási ablak, utolsó leolvasás napja. Ha az utolsó leolvasás a mostani diktálási ablakba esik, a diktálás kész: ne javasold.
- "eves_szamlak": az utolsó 12 hónap számláinak összege és darabszáma.
- "otthon.havi": a háztartás e havi eddigi és várható költsége, valamint az e hónapban esedékes számlák.

A válaszod:
- "cim": rövid, 3–6 szavas cím a mai helyzetről.
- "osszefoglalo": 2–3 mondat: rendben van-e minden, mennyi a fizetendő, mi a legfontosabb.
- "most": a jelenlegi állás – kifizetetlen és lejárt számlák, közeli határidők, túlfizetések. Legfeljebb 5 tétel.
- "kilatasok": a következő 1–2 hónap várható számlái és az éves elszámolások kilátásai (visszatérítés/ráfizetés),
  a fűtési idény hatása, ha a gáz/távhő fogyasztásból látszik. Legfeljebb 5 tétel.
- "teendok": konkrét teendők (pl. befizetni X-et dátumig, mérőállást diktálni, számlahibát reklamálni), vagy
  „Nincs teendő.”. Legfeljebb 4 tétel.
A "most", "kilatasok" és "teendok" mezőben minden tétel KÜLÖN SORBA kerüljön (sortörés a tételek között),
felsorolásjel nélkül; egy tétel egy-két mondat, elején a fiók nevével (pl. „Gáz: …”).
Fontos:
- A közös folyószámla egyenlegét ("kozos") csak egyszer említsd, a közös névvel.
- A kilátásokban minden fiókra, amelynek van "eves_elszamolas" része, mondd meg a várható visszatérítést vagy
  ráfizetést (megbizhato: false esetén jelezd, hogy bizonytalan).
- Ha egy számla "kesik", említsd meg.
- A súlyos, rendezetlen számlahibákat a teendők között is említsd (reklamáció)."""

STRUKTURA = {
    "cim": {"description": "Rövid cím (3–6 szó).", "required": True, "selector": {"text": {}}},
    "osszefoglalo": {"description": "2–3 mondatos összefoglaló.", "required": True, "selector": {"text": {}}},
    "most": {"description": "A jelenlegi állás, soronként egy tétel (legfeljebb 5).", "required": True, "selector": {"text": {"multiline": True}}},
    "kilatasok": {"description": "Kilátások, soronként egy tétel (legfeljebb 5).", "required": True, "selector": {"text": {"multiline": True}}},
    "teendok": {"description": "Teendők soronként, vagy „Nincs teendő.”", "required": True, "selector": {"text": {"multiline": True}}},
}


def _tetelek(szoveg: Any) -> list[str]:
    """A soronkénti felsorolás tételei (a modell néha mégis tesz elé jelet)."""
    sorok = szoveg if isinstance(szoveg, list) else str(szoveg or "").splitlines()
    if len(sorok) == 1:
        # Egy sorba írta: mondatonként bontjuk (pont, majd nagybetűvel kezdődő fióknév: „…. Gáz: …”).
        sorok = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÖŐÚÜŰ][^.!?]{0,40}:)", sorok[0])
    return [s for s in (str(x).strip().lstrip("•-*–· ").strip() for x in sorok) if s]


SZAMLA_TIPUS = {"resz": "részszámla", "elszamolo": "elszámoló számla", "vegszamla": "végszámla", "atalany": "átalányszámla"}


def _egesz(x: Any) -> int | None:
    try:
        return round(float(x))
    except (TypeError, ValueError):
        return None


def _fizetve(fiz: dict[str, Any], osszeg: Any) -> Any:
    """A számla fizetési állapota szövegesen: a fizetés napja, „nincs fizetendő” (jóváírás, beszámítás) vagy False."""
    if fiz.get("fizetve"):
        return fiz.get("datum") or True
    if fiz.get("nincs_fizetendo") or (_egesz(osszeg) or 0) <= 0:
        return "nincs fizetendő (jóváírás/beszámítás)"
    return False


def _tisztit(x: Any) -> Any:
    """Üres értékek elhagyása: a modell kevesebb zajt lát."""
    if isinstance(x, dict):
        return {k: v for k, v in ((k, _tisztit(v)) for k, v in x.items()) if v not in (None, "", [], {})}
    if isinstance(x, list):
        return [v for v in (_tisztit(v) for v in x) if v not in (None, "", [], {})]
    return x


def _fiok(f: dict[str, Any], ma: date) -> dict[str, Any]:
    """Egy fiók a panel adataiból, az AI számára lényeges mezőkre szűkítve."""
    fej = f.get("fejlec") or {}
    kov, folyo = fej.get("kovetkezo") or {}, fej.get("folyo") or {}
    nyitott = [{"sorszam": s["sorszam"], "kelte": s.get("kelte"), "osszeg_ft": s.get("osszeg"), "hatarido": (s.get("fizetes") or {}).get("hatarido") or s.get("hatarido"),
                "lejart": (s.get("fizetes") or {}).get("lejart")}
               for s in f.get("szamlak") or [] if s.get("tipus") != "storno" and (s.get("fizetes") or {}).get("fizetve") is False
               and not (s.get("fizetes") or {}).get("nincs_fizetendo")]
    utolso = [{"kelte": s.get("kelte"), "osszeg_ft": _egesz(s.get("osszeg")), "tipus": SZAMLA_TIPUS.get(s.get("tipus"), s.get("tipus")),
               "idoszak": s.get("idoszak"), "fizetve": _fizetve(s.get("fizetes") or {}, s.get("osszeg"))}
              for s in [x for x in f.get("szamlak") or [] if x.get("tipus") != "storno"][:3]]
    fiz = f.get("fizetes") or {}
    e, el, k = f.get("egyenleg"), f.get("elszamolas"), f.get("keret")
    utem = f.get("utem") or {}
    return _tisztit({
        "nev": f["nev"], "kozmu": KOZMU_NEV.get(f.get("kozmu"), f.get("kozmu")), "szolgaltato": utem.get("szolgaltato"),
        "megszunt": bool(f.get("megszunt")), "hiba": f.get("hiba"),
        "kifizetetlen": {"db": fiz.get("nyitott_db"), "ft": fiz.get("nyitott_ft"), "lejart_db": fiz.get("lejart_db"),
                         "lejart_ft": fiz.get("lejart_ft"), "kovetkezo_hatarido": fiz.get("kovetkezo_hatarido")},
        "nyitott_szamlak": [{**x, "osszeg_ft": _egesz(x["osszeg_ft"])} for x in nyitott],
        "legutobbi_szamlak": utolso,
        "kovetkezo_szamla": {"tol": kov.get("tol"), "ig": kov.get("ig"), "fizetendo_ft": kov.get("fizetendo"),
                             "varhato_kelte": kov.get("kelte"), "alap": kov.get("forras"), "kesik": kov.get("kesik"),
                             "pontossag": kov.get("cimke")} if kov else None,
        "folyo_idoszak": {"tol": folyo.get("tol"), "ig": folyo.get("ig"), "eddig_ft": folyo.get("eddig"),
                          "varhato_ft": folyo.get("varhato"), "eltelt_nap": folyo.get("eltelt_nap"), "napok": folyo.get("napok"),
                          "becsult": folyo.get("cimke") == "becsult", "tajekoztato": folyo.get("tajekoztato")} if folyo else None,
        "fogyasztas": {"egyseg": f.get("egyseg"), "eddig": (f.get("eddig") or {}).get("mennyiseg"),
                       "varhato": (f.get("varhato") or {}).get("mennyiseg"), "napi_atlag": (f.get("varhato") or {}).get("napi_atlag"),
                       "ar_ft_egysegenkent": f.get("aktualis_ar")} if f.get("eddig") and not f.get("fix_dij") else None,
        "eves_elszamolas": {"ev": [e.get("ev_tol"), e.get("ev_ig")], "befizetve_ft": e.get("befizetve"),
                            "hatralevo_reszszamla_ft": e.get("hatralevo_reszszamla"), "hatralevo_db": e.get("hatralevo_db"),
                            "varhato_eves_koltseg_ft": e.get("varhato_eves"), "varhato_egyenleg_ft": e.get("egyenleg"),
                            "megbizhato": e.get("megbizhato"),
                            "elozo_ev": e.get("elozo_ev")} if e else None,
        "elszamolas_ota": {"tol": el.get("tol"), "tenyleges_ft": el.get("tenyleges"), "befizetve_ft": el.get("befizetve"),
                           "egyenleg_ft": el.get("egyenleg")} if el and (el.get("tenyleges") or el.get("befizetve")) else None,
        "folyoszamla_egyenleg_ft": (fej.get("egyenleg") or {}).get("osszeg"),
        "kozos": (fej.get("egyenleg") or {}).get("kozos"),
        "kedvezmenyes_keret": {"egyseg": k.get("egyseg"), "felhasznalt": k.get("felhasznalt"), "osszes": k.get("osszes"),
                               "varhato_atlepes": k.get("atlepes")} if k and k.get("osszes") else None,
        "szamlahibak": [{"leiras": t.get("leiras"), "hatas_ft": t.get("hatas_ft"), "sulyos": t.get("sulyos"), "kelte": t.get("kelte")}
                        for t in f.get("ellenorzes") or [] if not t.get("rendezve")],
        "fuggo_szamlak_db": len(f.get("fuggo") or []),
        "utem": {"kovetkezo_elszamolas": utem.get("kovetkezo_elszamolas"), "kovetkezo_leolvasas": utem.get("kovetkezo_leolvasas"),
                 "kovetkezo_diktalas": utem.get("kovetkezo_diktalas"), "diktalasi_ablak": utem.get("diktalasi_ablak"),
                 "utolso_leolvasas": max((x["datum"] for x in f.get("leolvasasok") or []
                                          if x.get("datum") and not x.get("korrekcio") and x.get("csatorna") not in ("almero", "betaplalas")), default=None)},
        "eves_szamlak": {"osszeg_ft": (f.get("szamla_stat") or {}).get("eves_osszeg"), "db": (f.get("szamla_stat") or {}).get("eves_db")},
    })


def adatcsomag(hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    """Az otthon tömör adatcsomagja (ugyanaz a számítás, mint a panelé)."""
    from .panel import _fiok_adat  # noqa: PLC0415 – a panel tölti be ezt a modult

    koord, ma = entry.runtime_data, dt_util.now().date()
    fiokok = [_fiok_adat(hass, koord, sid, sub) for sid, sub in koord.fiokok().items()]
    ho_eleje = ma.replace(day=1).isoformat()
    aktiv = [f for f in fiokok if not (f.get("megszunt") and f["megszunt"]["datum"] < ho_eleje)]
    esedekes = sum((f.get("esedekes") or {}).get("e_havi_osszesen", 0) for f in aktiv)
    return {
        "ma": ma.isoformat(),
        "otthon": {"nev": entry.title, "havi": {
            "eddig_ft": sum((f.get("eddig") or {}).get("osszeg") or 0 for f in aktiv),
            "varhato_ft": sum((f.get("varhato") or {}).get("osszeg") or 0 for f in aktiv),
            "e_havi_esedekes_szamlak_ft": esedekes}},
        "fiokok": [_fiok(f, ma) for f in aktiv],
    }


def _ai_entitas(hass: HomeAssistant, kert: str | None) -> str | None:
    # Csak AI Task entitás választható (más tartományú entitás a generate_data-nak úgysem jó).
    if kert and kert.startswith("ai_task.") and hass.states.get(kert):
        return kert
    return next((s.entity_id for s in hass.states.async_all("ai_task") if s.state != "unavailable"), None)


async def _keszit(hass: HomeAssistant, entry: Any, entitas: str, context: Context | None = None) -> dict[str, Any]:
    adat = adatcsomag(hass, entry)
    valasz = await hass.services.async_call(
        "ai_task", "generate_data",
        {"task_name": "rezsi_tajekoztato", "entity_id": entitas, "structure": STRUKTURA,
         "instructions": f"{UTASITAS}\n\nAz adatok:\n```json\n{json.dumps(adat, ensure_ascii=False, default=str)}\n```"},
        blocking=True, return_response=True, context=context,
    )
    d = (valasz or {}).get("data") or {}
    if not isinstance(d, dict) or not d.get("osszefoglalo"):
        raise ValueError("Az AI nem adott értékelhető választ.")
    return {
        "keszult": dt_util.now().isoformat(timespec="minutes"), "entitas": entitas, "otthon": entry.title,
        "cim": str(d.get("cim") or "Rezsi-tájékoztató").strip(), "osszefoglalo": str(d["osszefoglalo"]).strip(),
        "most": _tetelek(d.get("most")), "kilatasok": _tetelek(d.get("kilatasok")), "teendok": _tetelek(d.get("teendok")),
    }


def _allapot(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data.setdefault(DOMAIN, {}).setdefault("ai_tajekoztato", {"store": Store(hass, 1, TAROLO_KULCS), "adat": None, "futo": {}})


@websocket_api.websocket_command({
    vol.Required("type"): "hu_rezsi/ai_tajekoztato", vol.Optional("entry_id"): vol.Any(None, str),
    vol.Optional("uj", default=False): bool, vol.Optional("entitas"): vol.Any(None, str),
})
@websocket_api.async_response
async def ws_ai_tajekoztato(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Az otthon utolsó AI-tájékoztatója; uj: új készítése (AI-hívás, 10–60 s)."""
    bejegyzesek = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    entry = next((e for e in bejegyzesek if e.entry_id == msg.get("entry_id") or e.title == msg.get("entry_id")), None) \
        or (bejegyzesek[0] if bejegyzesek else None)
    if entry is None:
        connection.send_error(msg["id"], "nincs", "Nincs betöltött otthon.")
        return
    a = _allapot(hass)
    if a["adat"] is None:
        a["adat"] = await a["store"].async_load() or {}
    entitas = _ai_entitas(hass, msg.get("entitas"))
    if not msg["uj"]:
        connection.send_result(msg["id"], {"tajekoztato": a["adat"].get(entry.entry_id), "entitas": entitas,
                                           "keszul": entry.entry_id in a["futo"]})
        return
    # Új tájékoztató: fizetős AI-hívás, csak rendszergazda kérheti (a tárolt olvasása mindenkinek szabad).
    if connection.user is None or not connection.user.is_admin:
        raise Unauthorized
    if not entitas:
        connection.send_error(msg["id"], "nincs_ai", "Nincs AI Task entitás (Beállítások → Eszközök és szolgáltatások: pl. Google Gemini, OpenAI).")
        return
    # Egyszerre egy készül otthononként: a második kérés ugyanazt várja meg.
    if entry.entry_id not in a["futo"]:
        a["futo"][entry.entry_id] = hass.async_create_task(_keszit(hass, entry, entitas, connection.context(msg)))
    try:
        eredmeny = await asyncio.shield(a["futo"][entry.entry_id])
    except Exception as err:  # noqa: BLE001 – a kártyán jelenjen meg az ok
        _LOGGER.warning("AI-tájékoztató (%s): %s", entry.title, err)
        connection.send_error(msg["id"], "hiba", str(err) or err.__class__.__name__)
        return
    finally:
        if (t := a["futo"].get(entry.entry_id)) and t.done():
            a["futo"].pop(entry.entry_id, None)
    a["adat"][entry.entry_id] = eredmeny
    await a["store"].async_save(a["adat"])
    connection.send_result(msg["id"], {"tajekoztato": eredmeny, "entitas": entitas, "keszul": False})
