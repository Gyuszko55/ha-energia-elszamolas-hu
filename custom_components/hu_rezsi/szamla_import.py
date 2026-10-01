"""Beolvasott számlák rögzítése egy fiók tárolt adataiba (HA nélkül tesztelhető).

Egy számla akkor tartozik a fiókhoz, ha a fiók „számla-mérők” listája üres (a mappa minden számlája az övé),
vagy ha a számlán szereplő valamelyik mérő gyári száma szerepel a listában.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

try:
    from .szamlak import Meroallas, Szamla, mero_azonosito
except ImportError:  # tesztek: a csomag HA nélkül, közvetlenül
    from szamlak import Meroallas, Szamla, mero_azonosito


# 2: a számla időszakán belüli (számított) állások kimaradnak; elszámoló csak az időszak végén.
# 3: a számla időszaka és utolsó valódi mérőállásának napja is tárolva (várható elszámoláshoz).
IMPORT_VERZIO = 3


@dataclass
class ImportJelentes:
    szamlak: list[str] = field(default_factory=list)
    leolvasasok: int = 0
    futoertekek: int = 0
    kihagyott_ellentmondas: int = 0
    kihagyott_szamitott: int = 0
    ismeretlen_merok: set[str] = field(default_factory=set)
    figyelmeztetesek: list[str] = field(default_factory=list)


def _d(x: Any) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def hozzatartozik(szamla: Szamla, szuro: set[str]) -> bool:
    return not szuro or bool(szamla.merok & szuro)


def _aktiv(merok: list[dict[str, Any]], nap: date) -> dict[str, Any] | None:
    for m in reversed(merok):
        if _d(m["beepitve"]) <= nap and (m.get("kiszerelve") is None or nap <= _d(m["kiszerelve"])):
            return m
    return None


def _cel_mero(tarolt: dict[str, Any], ma: Meroallas, szuro: set[str]) -> dict[str, Any] | None:
    """A mérőállás melyik tárolt mérőhöz tartozik: gyári szám szerint, vagy egy még szám nélküli mérőhöz."""
    for lista in (tarolt["merok"], tarolt.get("almero_merok") or []):
        for m in lista:
            if mero_azonosito(m.get("gyari_szam", "")) == ma.mero:
                return m
    if szuro and ma.mero not in szuro:
        return None
    # Szám nélküli mérő átveszi a számát: előbb a fő, aztán az almérő (ha a fő már más számú).
    fo = _aktiv(tarolt["merok"], ma.datum)
    if fo is not None and not fo.get("gyari_szam"):
        fo["gyari_szam"] = ma.mero
        return fo
    al = _aktiv(tarolt.get("almero_merok") or [], ma.datum)
    if al is not None and not al.get("gyari_szam"):
        al["gyari_szam"] = ma.mero
        return al
    return None


def _illeszkedik(mero: dict[str, Any], nap: date, allas: Decimal) -> bool:
    """Nem mehet visszafelé a mérő a többi leolvasáshoz képest, és a mérő élettartamán belül kell lennie."""
    if nap < _d(mero["beepitve"]) or (mero.get("kiszerelve") and nap > _d(mero["kiszerelve"])):
        return False
    if allas < Decimal(str(mero.get("kezdo_allas") or 0)):
        return False
    for lo in mero["leolvasasok"]:
        if lo.get("csatorna", "vetelezes") != "vetelezes":
            continue
        ld, la = _d(lo["datum"]), Decimal(str(lo["allas"]))
        if (ld < nap and la > allas) or (ld > nap and la < allas):
            return False
    return True


def szamla_meta(sz: Szamla) -> dict[str, Any]:
    valodi = [m.datum for m in sz.meroallasok if m.valodi and (not sz.idoszak or m.datum in sz.idoszak)]
    return {
        "kelte": sz.kelte.isoformat(),
        "osszeg": None if sz.osszeg is None else str(sz.osszeg),
        "tipus": sz.tipus,
        "forras": sz.forras,
        "fajl": sz.fajl,
        "idoszak": [sz.idoszak[0].isoformat(), sz.idoszak[1].isoformat()] if sz.idoszak and all(sz.idoszak) else None,
        "utolso_valodi_allas": max(valodi).isoformat() if valodi else None,
    }


def _elszamolo_allas(sz: Szamla, ma: Meroallas) -> bool:
    """Elszámoló (éves) leolvasás: leolvasott állás egy elszámoló számla időszakának VÉGÉN."""
    if not (ma.leolvasott and sz.tipus == "elszamolo"):
        return False
    return sz.idoszak is None or ma.datum == sz.idoszak[1]


def ujraertekel(tarolt: dict[str, Any], szamlak: list[Szamla]) -> int:
    """Régebbi import-verzióval rögzített, számlából jött állások rendbetétele az új szabályok szerint.

    Csak a „számla <sorszám>” megjegyzésű leolvasásokhoz nyúl (a kézi és a v1-ből jöttekhez nem).
    Visszaadja a módosított/törölt leolvasások számát.
    """
    szerint = {sz.sorszam: sz for sz in szamlak}
    valtozas = 0
    for lista in (tarolt.get("merok") or [], tarolt.get("almero_merok") or []):
        for mero in lista:
            uj = []
            for lo in mero["leolvasasok"]:
                m = re.match(r"számla (\S+) \(", lo.get("megjegyzes", ""))
                sz = szerint.get(m.group(1)) if m else None
                if sz is None:
                    uj.append(lo)
                    continue
                nap = _d(lo["datum"])
                if sz.idoszak and nap not in sz.idoszak:
                    valtozas += 1  # számított köztes állás: törölve
                    continue
                ma = next((x for x in sz.meroallasok if x.datum == nap), None)
                elsz = bool(ma and _elszamolo_allas(sz, ma))
                if lo.get("elszamolasi") != elsz:
                    lo["elszamolasi"] = elsz
                    valtozas += 1
                uj.append(lo)
            mero["leolvasasok"] = uj
    ismert = tarolt.get("szamlak") or {}
    for sorszam, sz in szerint.items():
        if sorszam in ismert:
            ismert[sorszam] = szamla_meta(sz)
    tarolt["szamla_import_verzio"] = IMPORT_VERZIO
    return valtozas


def rogzit(tarolt: dict[str, Any], szamlak: list[Szamla], szuro: set[str] | None = None) -> ImportJelentes:
    """Az új (még nem látott sorszámú) számlák rögzítése: befizetés, valódi mérőállások, fűtőértékek."""
    szuro = {mero_azonosito(x) for x in (szuro or set()) if x}
    j = ImportJelentes()
    ismert = tarolt.setdefault("szamlak", {})
    reszek = tarolt.setdefault("reszszamlak", [])
    for sz in sorted(szamlak, key=lambda x: x.kelte):
        if not sz.sorszam or sz.sorszam in ismert or not hozzatartozik(sz, szuro):
            continue
        ismert[sz.sorszam] = szamla_meta(sz)
        j.szamlak.append(sz.sorszam)
        # Befizetés: ha kézzel már rögzítve ugyanaz a nap és összeg (vagy a sorszám), nem duplikáljuk.
        if sz.osszeg is not None and not any(
            r.get("sorszam") == sz.sorszam or (r["datum"] == sz.kelte.isoformat() and Decimal(str(r["osszeg"])) == sz.osszeg)
            for r in reszek
        ):
            reszek.append({"datum": sz.kelte.isoformat(), "osszeg": str(sz.osszeg), "sorszam": sz.sorszam,
                           "megjegyzes": f"{sz.forras} {sz.tipus} ({sz.fajl})"})
        for ma in sz.meroallasok:
            if not ma.valodi:
                continue
            if sz.idoszak and ma.datum not in sz.idoszak:
                j.kihagyott_szamitott += 1  # pl. az éves gázszámla jan. 1-jei, számított bontása
                continue
            mero = _cel_mero(tarolt, ma, szuro)
            if mero is None:
                j.ismeretlen_merok.add(ma.mero)
                continue
            if any(lo["datum"] == ma.datum.isoformat() and lo.get("csatorna", "vetelezes") == "vetelezes" for lo in mero["leolvasasok"]):
                continue  # azon a napon már van leolvasás (a kézi felülbírálja a számlát)
            if not _illeszkedik(mero, ma.datum, ma.allas):
                j.kihagyott_ellentmondas += 1
                continue
            mero["leolvasasok"].append({
                "datum": ma.datum.isoformat(),
                "allas": str(ma.allas),
                "tipus": "szolgaltatoi" if ma.leolvasott else "kezi",
                "elszamolasi": _elszamolo_allas(sz, ma),
                "megjegyzes": f"számla {sz.sorszam} ({ma.lm})",
                "csatorna": "vetelezes",
            })
            mero["leolvasasok"].sort(key=lambda x: x["datum"])
            j.leolvasasok += 1
        fe = tarolt.setdefault("futoertekek", {})
        for honap, ertek in sz.futoertekek.items():
            if honap not in fe:
                fe[honap] = str(ertek.normalize())
                j.futoertekek += 1
    reszek.sort(key=lambda r: r["datum"])
    if j.ismeretlen_merok:
        j.figyelmeztetesek.append(
            "Ismeretlen mérő a számlákon: " + ", ".join(sorted(j.ismeretlen_merok))
            + " – ha mérőcsere volt, rögzítsd (hu_rezsi.merocsere), vagy vedd fel a fiók számla-mérői közé."
        )
    return j
