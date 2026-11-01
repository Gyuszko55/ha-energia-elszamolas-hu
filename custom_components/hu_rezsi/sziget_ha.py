"""Szigetüzem (kísérleti) – a motor (motor/sziget.py) és a Home Assistant összekötése.

Egy szigetüzemi rendszer egy `sziget` típusú alárendelt bejegyzés (nem fiók: a számla-, keret- és összesítő-kód nem
látja). Szerepkörönként források: energia-szenzorok (HA napi statisztika + mostani érték) vagy – szenzor nélkül –
kézi leolvasások (`hu_rezsi.sziget_leolvasas`). Az eredmény a panelnek és a szenzoroknak szóló, sorosítható szótár.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigSubentry

from .const import SZIGET
from .motor import sziget as m
from .motor.szamlalo import nap_kezdete

if TYPE_CHECKING:
    from .koordinator import RezsiKoordinator

_LOGGER = logging.getLogger(__name__)

ELOZMENY_NAPOK = 800  # két teljes év + a folyó: az előző év összevetéséhez
CONF_SZEREPEK = "szerepek"


def forras_kulcs(szerep: str) -> str:
    return f"forras_{szerep}"


def szigetek(koord: RezsiKoordinator) -> dict[str, ConfigSubentry]:
    return {sid: s for sid, s in koord.config_entry.subentries.items() if s.subentry_type == SZIGET}


def szerepek(sub: ConfigSubentry) -> list[str]:
    """A rendszer szerepkörei: a fogyasztás mindig, a többi a beállítás szerint, rögzített sorrendben."""
    beallitott = set(sub.data.get(CONF_SZEREPEK) or [])
    return [s for s in m.SZEREPEK if s == m.FOGYASZTAS or s in beallitott]


def _f(x: Decimal | None, n: int = 1) -> float | None:
    return None if x is None else round(float(x), n)


def eredmeny_dict(r: m.SzigetEredmeny) -> dict[str, Any]:
    return {
        "tol": r.tol.isoformat(), "ig": r.ig.isoformat(), "kezdet": r.kezdet.isoformat() if r.kezdet else None,
        "minoseg": str(r.minoseg), "ertekek": {k: _f(v) for k, v in r.ertekek.items()}, "becsult": sorted(r.becsult),
        "fogyasztas": _f(r.fogyasztas), "kulso": _f(r.kulso), "sajat": _f(r.sajat),
        "onellatottsag": _f(r.onellatottsag * 100 if r.onellatottsag is not None else None),
        "halozati_reszarany": _f(r.halozati_reszarany * 100 if r.halozati_reszarany is not None else None),
        "generator_reszarany": _f(r.generator_reszarany * 100 if r.generator_reszarany is not None else None),
        "akku_netto": _f(r.akku_netto), "merleg_be": _f(r.merleg_be), "merleg_ki": _f(r.merleg_ki),
        "merleg_elteres": _f(r.merleg_elteres), "utvonalak": {k: _f(v) for k, v in r.utvonalak.items()},
        "megjegyzesek": r.megjegyzesek,
    }


async def _rendszer(
    koord: RezsiKoordinator, sid: str, sub: ConfigSubentry, most: datetime
) -> tuple[m.Rendszer, int, list[str]]:
    """A beállított csatornák számlálói, a naplózott számlálóesemények száma és a kihagyott források oka."""
    tarolt = koord.tarolo.sziget(sid)
    csatornak: dict[str, list[m.Szamlalo]] = {}
    esemenyek = 0
    kihagyott: list[str] = []
    # Napra kerekített kezdet: a napi statisztika így naponta egyszer töltődik le (a koordinátor gyorstárából).
    tol = nap_kezdete((most - timedelta(days=ELOZMENY_NAPOK)).date())
    for szerep in szerepek(sub):
        forrasok: list[m.Szamlalo] = []
        for eid in sub.data.get(forras_kulcs(szerep)) or []:
            allapot = koord.hass.states.get(eid)
            egyseg = allapot.attributes.get("unit_of_measurement") if allapot else None
            if egyseg not in m.EGYSEG_SZORZO:
                # Ismeretlen mértékegységet nem feltételezünk kWh-nak (W, Wh-szorzó…): a csatorna adat nélküli lesz.
                kihagyott.append(f"{eid}: a mértékegység {f'„{egyseg}”' if egyseg else 'nincs megadva'} (Wh, kWh vagy "
                                 "MWh kell) – a forrás nem számít, a csatorna adat nélküli.")
                forrasok.append(m.Szamlalo([]))
                continue
            sor = await koord._sorozat(eid, tol, most, napi_gyorstar=True)  # noqa: SLF001
            sz, esem = m.szamlalo_sorozatbol(sor, egyseg)
            esemenyek += sum(1 for e in esem if e.tipus != "ismeretlen")
            forrasok.append(sz)
        if not forrasok and (lo := tarolt["leolvasasok"].get(szerep)):
            # Szenzor nélkül: a kézi leolvasások (kumulatív állások, kWh) egyetlen forrásként.
            sz, esem = m.szamlalo_sorozatbol([(datetime.fromisoformat(x["ido"]), Decimal(str(x["allas"]))) for x in lo])
            esemenyek += sum(1 for e in esem if e.tipus != "ismeretlen")
            forrasok.append(sz)
        csatornak[szerep] = forrasok or [m.Szamlalo([])]  # beállított, de adat nélküli: „ismeretlen”
    return m.Rendszer(csatornak), esemenyek, kihagyott


async def szamol(koord: RezsiKoordinator, sid: str, sub: ConfigSubentry, most: datetime) -> dict[str, Any]:
    rendszer, esemenyek, kihagyott = await _rendszer(koord, sid, sub, most)
    fogy = [s for s in rendszer.csatornak.get(m.FOGYASZTAS, []) if s.pontok]
    alap = {"sid": sid, "nev": sub.title, "szerepek": szerepek(sub), "kiserleti": True}
    if not fogy:
        hiba = "még nincs fogyasztás-adat (szenzor vagy leolvasás)"
        return alap | {"hiba": " ".join([hiba, *kihagyott]), "idoszakok": {}, "honapok": []}

    def eredmeny(tol: datetime, ig: datetime) -> dict[str, Any]:
        r = eredmeny_dict(m.merleg(rendszer, tol, ig))
        r["megjegyzesek"] = [*kihagyott, *r["megjegyzesek"]]  # a kihagyott forrás minden nézetben látszik
        return r

    elso = min(s.pontok[0].ido for s in fogy)
    idoszakok = {k: eredmeny(tol, ig) for k, (tol, ig) in m.idoszakok(most, elso).items() if ig > elso}
    honapok = []
    for tol, ig in m.honapok(max(elso.date(), (most - timedelta(days=ELOZMENY_NAPOK)).date()), most.date() + timedelta(days=1)):
        honapok.append({"honap": tol.strftime("%Y-%m"), "reszleges": ig > most, **eredmeny(tol, min(ig, most))})
    return alap | {"hiba": None, "kezdet": elso.isoformat(), "esemenyek": esemenyek, "idoszakok": idoszakok, "honapok": honapok}


async def szamol_mind(koord: RezsiKoordinator, most: datetime) -> dict[str, dict[str, Any]]:
    ki: dict[str, dict[str, Any]] = {}
    for sid, sub in szigetek(koord).items():
        try:
            ki[sid] = await szamol(koord, sid, sub, most)
        except Exception as err:  # noqa: BLE001 – a szigetüzem (kísérleti) hibája ne állítsa meg a fiókokat
            _LOGGER.exception("%s: szigetüzem nem számolható", sub.title)
            ki[sid] = {"sid": sid, "nev": sub.title, "szerepek": szerepek(sub), "hiba": str(err), "idoszakok": {}, "honapok": []}
    koord.napi_gyorstar_takaritas()  # csak a most kért (entitás, kezdet) napi statisztikája marad meg
    for sid in set(koord.tarolo.adat.get("szigetek", {})) - set(szigetek(koord)):
        koord.tarolo.adat["szigetek"].pop(sid, None)
    return ki
