"""Beolvasott számlák rögzítése egy fiók tárolt adataiba (HA nélkül tesztelhető).

Egy számla akkor tartozik a fiókhoz, ha a fiók „számla-mérők” listája üres (a mappa minden számlája az övé),
vagy ha a számlán szereplő valamelyik mérő gyári száma szerepel a listában.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

try:
    from .szamlak import Meroallas, Szamla, ervenytelenek, mero_azonosito, szamlazott_idoszak, sztornozott_kulcsok, sztornozottak
except ImportError:  # tesztek: a csomag HA nélkül, közvetlenül
    from szamlak import Meroallas, Szamla, ervenytelenek, mero_azonosito, szamlazott_idoszak, sztornozott_kulcsok, sztornozottak

_LOGGER = logging.getLogger(__name__)

# 2: a számla időszakán belüli (számított) állások kimaradnak; elszámoló csak az időszak végén.
# 3: a számla időszaka és utolsó valódi mérőállásának napja is tárolva (várható elszámoláshoz).
# 4: a DAKÖV-számlák elszámolt időszaka is (átalány napi összegéhez).
IMPORT_VERZIO = 5  # 5: MVM villany belső évhatár-leolvasás (sávkorrekció)


@dataclass
class ImportJelentes:
    szamlak: list[str] = field(default_factory=list)
    leolvasasok: int = 0
    futoertekek: int = 0
    kihagyott_ellentmondas: int = 0
    kihagyott_szamitott: int = 0
    ismeretlen_merok: set[str] = field(default_factory=set)
    kezdonap_elotti: list[date] = field(default_factory=list)  # a mérő kezdőnapja előtti állások (kimaradtak)
    figyelmeztetesek: list[str] = field(default_factory=list)


def _d(x: Any) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


# Ezek a számlák soha nem hordoznak mérőszámot: a „számla-mérők” szűrő nem zárhatja ki őket.
MERO_NELKULI_FORRAS = {"hvsz", "mohu", "telekom", "one"}


def hozzatartozik(szamla: Szamla, szuro: set[str], arszabas: str | None = None) -> bool:
    """A számla ehhez a fiókhoz tartozik-e: a számla-mérők szerint, ezek nélkül a számla árszabása (A1/H)
    és a fiók díjszabása szerint; ha egyik sem ad támpontot, igen."""
    if szuro and not szamla.merok and (szamla.forras in MERO_NELKULI_FORRAS or szamla.forras.startswith("sablon:")):
        return True  # pl. távhő (HVSZ): a számlán nincs mérőszám, a mappa maga választja ki a fiókot
    if szuro:
        return bool(szamla.merok & szuro)
    if arszabas and szamla.arszabas:
        return szamla.arszabas == arszabas
    return True


def _kezdonap_elotti(tarolt: dict[str, Any], ma: Meroallas) -> bool:
    """Az állás egy (ugyanilyen számú vagy még szám nélküli) mérő kezdőnapja előtti-e."""
    for m in (tarolt.get("merok") or []) + (tarolt.get("almero_merok") or []):
        gy = mero_azonosito(m.get("gyari_szam", ""))
        if (gy == ma.mero or not gy) and ma.datum < _d(m["beepitve"]):
            return True
    return False


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


def _szomszedos_azonos(mero: dict[str, Any], nap: date, allas: Decimal) -> bool:
    """Van-e már ugyanez az állás egy nappal előtte vagy utána (számlahatár: záró = következő induló)."""
    return any(
        lo.get("csatorna", "vetelezes") == "vetelezes"
        and abs((_d(lo["datum"]) - nap).days) == 1
        and Decimal(str(lo["allas"])) == allas
        for lo in mero["leolvasasok"]
    )


def szamla_allasok(sz: Szamla) -> list[dict[str, Any]]:
    """A számlán szereplő induló és záró mérőállás mérőnként (a fő regiszteren) – becsült/kalkulált is, a leolvasás
    módjával (Dikt, Leol, Becs …): [{mero, indulo: [nap, állás], zaro: [nap, állás], lm}]."""
    merok: dict[str, list] = {}
    for m in sz.meroallasok:
        if getattr(m, "csatorna", "vetelezes") == "vetelezes":
            merok.setdefault(m.mero, []).append(m)
    out = []
    for mero, lista in merok.items():
        lista.sort(key=lambda m: m.datum)
        a, z = lista[0], lista[-1]
        out.append({"mero": mero, "indulo": [a.datum.isoformat(), str(a.allas)], "zaro": [z.datum.isoformat(), str(z.allas)],
                    "lm": z.lm or a.lm})
    return out


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
        **({"allasok": szamla_allasok(sz)} if sz.meroallasok else {}),
        **({"arszabas": sz.arszabas} if sz.arszabas else {}),
        **({"atalany_mennyiseg": str(sz.atalany_mennyiseg)} if sz.atalany_mennyiseg is not None else {}),
        **({"diktalasi_ablak": list(sz.diktalasi_ablak)} if sz.diktalasi_ablak else {}),
        **({"kovetkezo_leolvasas": [x.isoformat() for x in sz.kovetkezo_leolvasas]} if sz.kovetkezo_leolvasas else {}),
        **({"kovetkezo_diktalas": [x.isoformat() for x in sz.kovetkezo_diktalas]} if sz.kovetkezo_diktalas else {}),
        **({"elszamolt_kwh": str(sz.elszamolt_kwh)} if sz.elszamolt_kwh is not None else {}),
        **({"elszamolt_gaz": {k: str(v) for k, v in sz.elszamolt_gaz.items()}} if sz.elszamolt_gaz else {}),
        **({"kovetkezo_resz_m3": str(sz.kovetkezo_resz_m3)} if sz.kovetkezo_resz_m3 is not None else {}),
        **({"elszamolt_viz": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in sz.elszamolt_viz.items()}} if sz.elszamolt_viz else {}),
        **({"elszamolt_tavho": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in sz.elszamolt_tavho.items()}} if sz.elszamolt_tavho else {}),
        **({"szamlaertek": str(sz.szamlaertek)} if sz.szamlaertek is not None else {}),
        **({"levont_szamlak": [[s, None if o is None else str(o)] for s, o in sz.levont_szamlak]} if sz.levont_szamlak else {}),
        **folyoszamla_meta(sz),
    }


def folyoszamla_meta(sz: Szamla) -> dict[str, Any]:
    """MVM: a folyószámla-tételek (túlfizetés, átvezetés), az egyenleg és a kiszámlázott mennyiség – a tároláshoz."""
    return {
        **({"egyeb_tetelek": [[n, str(o)] for n, o in sz.egyeb_tetelek]} if sz.egyeb_tetelek else {}),
        **({"folyoszamla": str(sz.folyoszamla)} if sz.folyoszamla is not None else {}),
        **({"szamlazott_kwh": str(sz.szamlazott_kwh)} if sz.szamlazott_kwh is not None else {}),
        **({"szamlazott_idenyek": {k: str(v) for k, v in sz.szamlazott_idenyek.items()}} if sz.szamlazott_idenyek else {}),
        **({"ugyfel": sz.ugyfel} if sz.ugyfel else {}),
        **({"tetelek": sz.tetelek} if sz.tetelek else {}),
        **({"hatarido": sz.hatarido.isoformat()} if sz.hatarido else {}),
        **({"fizetesi_mod": sz.fizetesi_mod} if sz.fizetesi_mod else {}),
        **({"sztornozott": sz.sztornozott} if sz.sztornozott else {}),
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
                if sz.idoszak and nap not in sz.idoszak and nap not in sz.evhatarok:
                    valtozas += 1  # számított köztes állás: törölve
                    continue
                ma = next((x for x in sz.meroallasok if x.datum == nap), None)
                # A számla belső évhatára (pl. 07.31., a kedvezményes év fordulója) NEM éves elszámoló leolvasás.
                elsz = bool(ma and _elszamolo_allas(sz, ma))
                if lo.get("elszamolasi") != elsz:
                    lo["elszamolasi"] = elsz
                    valtozas += 1
                uj.append(lo)
            mero["leolvasasok"] = uj
    ismert = tarolt.get("szamlak") or {}
    for sorszam, sz in szerint.items():
        if sorszam in ismert:
            # A párosított (a számlán nem szereplő) stornó-hivatkozás megmarad.
            regi = ismert[sorszam].get("sztornozott")
            ismert[sorszam] = szamla_meta(sz)
            if regi and not ismert[sorszam].get("sztornozott"):
                ismert[sorszam]["sztornozott"] = regi
    torolt = sztornozott_kulcsok(ismert)
    # Pótlás: a már rögzített számlák belső vágás-leolvasása (korábban „köztes” állásként kimaradt) – valódi állás,
    # de nem éves elszámoló leolvasás (az évhatár az éves leolvasás).
    for sorszam, sz in szerint.items():
        if sorszam not in ismert or sorszam in torolt:
            continue  # a sztornózott számla állásai nem számítanak
        for ma in sz.meroallasok:
            if ma.datum not in sz.evhatarok or not ma.valodi:
                continue
            mero = next((m for lista in (tarolt.get("merok") or [], tarolt.get("almero_merok") or []) for m in lista
                         if mero_azonosito(m.get("gyari_szam", "")) == ma.mero), None)
            if mero is None or _kezdonap_elotti(tarolt, ma) or any(
                lo["datum"] == ma.datum.isoformat() and lo.get("csatorna", "vetelezes") == "vetelezes" for lo in mero["leolvasasok"]
            ) or not _illeszkedik(mero, ma.datum, ma.allas):
                continue
            mero["leolvasasok"].append({
                "datum": ma.datum.isoformat(), "allas": str(ma.allas), "tipus": "szolgaltatoi" if ma.leolvasott else "kezi",
                # Valódi mérőállás (a számla időszakán belüli vágás), de nem éves elszámoló leolvasás.
                "elszamolasi": False, "megjegyzes": f"számla {sz.sorszam} ({ma.lm})", "csatorna": "vetelezes",
            })
            mero["leolvasasok"].sort(key=lambda x: x["datum"])
            valtozas += 1
    tarolt["szamla_import_verzio"] = IMPORT_VERZIO
    return valtozas


def regiszter_rogzit(tarolt: dict[str, Any], sz: Szamla, szuro: set[str] | None = None) -> int:
    """A számla H-regiszter állásai (1.82 nyári, 1.81 téli) a mérő leolvasásai közé, h_nyari / h_teli csatornán.
    Csak valódi (diktált, leolvasott) állás az elszámolt időszak két végén; ha azon a napon (vagy a szomszédos
    számlahatáron ugyanazzal az értékkel) már van ilyen regiszter-leolvasás, kimarad. Visszaad: a rögzítettek száma."""
    szuro = {mero_azonosito(x) for x in (szuro or set()) if x}
    db = 0
    for ma in sz.regiszter_allasok:
        if not ma.valodi or (sz.idoszak and ma.datum not in sz.idoszak) or _kezdonap_elotti(tarolt, ma):
            continue
        mero = _cel_mero(tarolt, ma, szuro)
        if mero is None or any(
            lo.get("csatorna") == ma.csatorna and (lo["datum"] == ma.datum.isoformat() or (
                abs((_d(lo["datum"]) - ma.datum).days) == 1 and Decimal(str(lo["allas"])) == ma.allas))
            for lo in mero["leolvasasok"]
        ):
            continue
        mero["leolvasasok"].append({
            "datum": ma.datum.isoformat(), "allas": str(ma.allas), "tipus": "szolgaltatoi" if ma.leolvasott else "kezi",
            "elszamolasi": False, "megjegyzes": f"számla {sz.sorszam} ({ma.lm})", "csatorna": ma.csatorna,
        })
        mero["leolvasasok"].sort(key=lambda x: x["datum"])
        db += 1
    return db


def rogzit(
    tarolt: dict[str, Any], szamlak: list[Szamla], szuro: set[str] | None = None, arszabas: str | None = None
) -> ImportJelentes:
    """Az új (még nem látott sorszámú) számlák rögzítése: befizetés, valódi mérőállások, fűtőértékek."""
    szuro = {mero_azonosito(x) for x in (szuro or set()) if x}
    j = ImportJelentes()
    ismert = tarolt.setdefault("szamlak", {})
    reszek = tarolt.setdefault("reszszamlak", [])
    szamlak = [sz for sz in szamlak if isinstance(sz.kelte, date)]  # kelte nélkül nem rögzíthető (a beolvasó kiszűri)
    torolt = _stornok_rendezese(tarolt, [sz for sz in szamlak if sz.sorszam and sz.sorszam not in ismert
                                          and hozzatartozik(sz, szuro, arszabas)])
    for sz in sorted(szamlak, key=lambda x: x.kelte):
        if not sz.sorszam or sz.sorszam in ismert or not hozzatartozik(sz, szuro, arszabas):
            continue
        # Egy hibás számla ne akassza meg a többit: a félig rögzített állapotot visszaállítjuk, és figyelmeztetünk.
        mentes, j_mentes = copy.deepcopy(tarolt), copy.deepcopy(j)
        try:
            ismert[sz.sorszam] = szamla_meta(sz)
            j.szamlak.append(sz.sorszam)
            if sz.tipus == "storno" or sz.sorszam.lstrip("0") in torolt:
                continue  # stornó / sztornózott számla: se befizetés, se mérőállás, se fűtőérték (az újra kiállított számít)
            # Befizetés: ha kézzel már rögzítve ugyanaz a nap és összeg (vagy a sorszám), nem duplikáljuk. Közös
            # folyószámlánál (túlfizetés, átvezetés a számlán) a számla saját értéke – a többi nem e fiók díja.
            # A nap+összeg egyezés csak a sorszám nélküli (kézi) tételre: egy másik, ugyanazon a napon ugyanannyiról
            # szóló számla külön befizetés.
            bef = sz.szamlaertek if (sz.egyeb_tetelek or (sz.forras == "mvm_aram" and sz.tipus != "storno")) and sz.szamlaertek is not None else sz.osszeg
            if bef is not None and bef != 0 and not any(
                r.get("sorszam") == sz.sorszam
                or (not r.get("sorszam") and r["datum"] == sz.kelte.isoformat() and r.get("osszeg") not in (None, "")
                    and Decimal(str(r["osszeg"])) == bef)
                for r in reszek
            ):
                reszek.append({"datum": sz.kelte.isoformat(), "osszeg": str(bef), "sorszam": sz.sorszam,
                               "megjegyzes": f"{sz.forras} {sz.tipus} ({sz.fajl})"})
            for ma in sz.meroallasok:
                if not ma.valodi:
                    continue
                if sz.idoszak and ma.datum not in sz.idoszak and ma.datum not in sz.evhatarok:
                    j.kihagyott_szamitott += 1  # pl. az éves gázszámla jan. 1-jei, számított bontása
                    continue
                if _kezdonap_elotti(tarolt, ma):
                    j.kezdonap_elotti.append(ma.datum)
                    continue
                mero = _cel_mero(tarolt, ma, szuro)
                if mero is None:
                    j.ismeretlen_merok.add(ma.mero)
                    continue
                if any(lo["datum"] == ma.datum.isoformat() and lo.get("csatorna", "vetelezes") == "vetelezes" for lo in mero["leolvasasok"]):
                    continue  # azon a napon már van leolvasás (a kézi felülbírálja a számlát)
                if _szomszedos_azonos(mero, ma.datum, ma.allas):
                    continue  # az előző számla záró állása a következő napon, induló állásként: ugyanaz a leolvasás
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
            j.leolvasasok += regiszter_rogzit(tarolt, sz, szuro)
            fe = tarolt.setdefault("futoertekek", {})
            vegleges = sz.tipus == "elszamolo"
            for honap, ertek in sz.futoertekek.items():
                # Az elszámoló (leolvasott) számla végleges fűtőértéke felülírja a részszámlák becsült havi értékét.
                if honap not in fe or vegleges:
                    fe[honap] = str(ertek.normalize())
                    j.futoertekek += 1
            if vegleges and sz.korrekciok:
                ko = tarolt.setdefault("korrekciok", {})
                for honap, ertek in sz.korrekciok.items():
                    ko[honap] = str(ertek.normalize())
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("A(z) %s számla nem rögzíthető (%s): %s", sz.sorszam, sz.fajl, err)
            tarolt.clear()
            tarolt.update(mentes)
            j.__dict__.update(j_mentes.__dict__)
            ismert, reszek = tarolt["szamlak"], tarolt["reszszamlak"]
            j.figyelmeztetesek.append(f"A(z) {sz.sorszam} számla nem rögzíthető ({sz.fajl}): {err}")
    reszek.sort(key=lambda r: r["datum"])
    if j.kezdonap_elotti:
        kezdo = min((_d(m["beepitve"]) for m in tarolt.get("merok") or []), default=None)
        j.figyelmeztetesek.append(
            f"{len(j.kezdonap_elotti)} mérőállás ({min(j.kezdonap_elotti).isoformat()} – {max(j.kezdonap_elotti).isoformat()}) "
            f"a mérő kezdőnapja ({kezdo.isoformat() if kezdo else '?'}) előtti, ezért kimaradt. Állítsd korábbira a kezdőnapot "
            "(és add meg az akkori óraállást) a fiók beállításainak 3. lépésében – utána a számlákat magától újraolvassa."
        )
    if j.ismeretlen_merok:
        j.figyelmeztetesek.append(
            "Ismeretlen mérő a számlákon: " + ", ".join(sorted(j.ismeretlen_merok))
            + " – ha mérőcsere volt, rögzítsd (hu_rezsi.merocsere), vagy vedd fel a fiók számla-mérői közé."
        )
    return j


def _ertekek(x: dict[str, Any]) -> set[Decimal]:
    return {Decimal(str(x[k])) for k in ("szamlaertek", "osszeg") if x.get(k) not in (None, "")} - {Decimal(0)}


def storno_parositas(szamlak: dict[str, dict[str, Any]]) -> None:
    """A sztornózott sorszám nélküli stornó (pl. MVM XML) párosítása: a fiók azonos forrású, azonos időszakú, ellentétes
    összegű, nem későbbi kelte, még nem sztornózott számlája (több közül a legutóbbi). A stornón beállítja a sztornozott-at."""
    foglalt = {str(x).lstrip("0") for x in sztornozottak(szamlak.values())}
    for k, st in sorted(szamlak.items(), key=lambda kv: kv[1].get("kelte") or ""):
        if st.get("tipus") != "storno" or st.get("sztornozott") or not st.get("idoszak") or not (v := _ertekek(st)):
            continue
        jelolt = [(x.get("kelte") or "", s) for s, x in szamlak.items()
                  if s != k and x.get("tipus") != "storno" and x.get("forras") == st.get("forras")
                  and list(x.get("idoszak") or []) == list(st["idoszak"]) and (x.get("kelte") or "") <= (st.get("kelte") or "")
                  and str(s).lstrip("0") not in foglalt and {-y for y in v} & _ertekek(x)]
        if jelolt:
            # A stornó a korábbi számlát érvényteleníti: a nála korábbi keltűek közül a legutóbbi; azonos napi csak akkor,
            # ha nincs korábbi (az MVM az újra kiállítottat a stornóval egy napon adja ki – azt ne sztornózza).
            st["sztornozott"] = max(jelolt, key=lambda j: (j[0] < (st.get("kelte") or ""), j[0]))[1]
            foglalt.add(str(st["sztornozott"]).lstrip("0"))


def _stornok_rendezese(tarolt: dict[str, Any], ujak: list[Szamla]) -> set[str]:
    """Stornó ↔ eredeti a tárolt és az új számlák között (storno_parositas), majd a sztornózott számlák befizetése
    és a belőlük jött mérőállások törlése – így az újra kiállított számla (akár ugyanarra a napra szóló, helyesbített)
    állásai rögzülhetnek. Visszaad: a sztornózott sorszámok (vezető nullák nélkül)."""
    osszes = {sz.sorszam: szamla_meta(sz) for sz in ujak} | (tarolt.get("szamlak") or {})
    storno_parositas(osszes)
    for sz in ujak:
        if sz.tipus == "storno" and not sz.sztornozott and (s := (osszes.get(sz.sorszam) or {}).get("sztornozott")):
            sz.sztornozott = s
    torolt = {str(x).lstrip("0") for x in sztornozottak(osszes.values())}
    if not torolt:
        return torolt
    reszek = tarolt.setdefault("reszszamlak", [])
    reszek[:] = [r for r in reszek if not r.get("sorszam") or str(r["sorszam"]).lstrip("0") not in torolt]
    for lista in (tarolt.get("merok") or [], tarolt.get("almero_merok") or []):
        for mero in lista:
            mero["leolvasasok"] = [
                lo for lo in mero["leolvasasok"]
                if not ((m := re.match(r"számla (\S+) \(", lo.get("megjegyzes", ""))) and m.group(1).lstrip("0") in torolt)
            ]
    return torolt


def _bef_kulcs(datum: Any, osszeg: Any) -> str:
    """Befizetés azonosítója sorszám híján: nap + összeg egységes formában (11202 = 11202.0)."""
    return f"{str(datum)[:10]}|{Decimal(str(osszeg)).quantize(Decimal('0.01'))}"


def fajlok_ujraolvasasra(tarolt: dict[str, Any], nevek: set[str]) -> None:
    """A megnevezett számlafájlok a következő frissítéskor újra beolvasandók: kikerülnek a feldolgozottak és a fel nem
    ismertek (név → aláírás) közül is – különben a változatlan, fel nem ismert fájlt a mappa-figyelő nem próbálná újra."""
    tarolt["feldolgozott_fajlok"] = [f for f in tarolt.get("feldolgozott_fajlok", []) if f not in nevek]
    if nem_olv := tarolt.get("nem_olvasott_fajlok"):
        tarolt["nem_olvasott_fajlok"] = {k: v for k, v in nem_olv.items() if k not in nevek}


def befizetesek_egyesitese(tarolt: dict[str, Any], dijnet: list[tuple[date, Decimal, str]] | None = None) -> dict[str, tuple[date, Decimal]]:
    """A fiók befizetései számlaszám (vezető nullák nélkül – a Díjnet és a számlafájl eltérhet) vagy nap+összeg szerint
    egyesítve: a számlamappa és a Díjnet (kelt, összeg, számlaszám) ugyanazt a számlát ne számolja kétszer. A stornóval
    sztornózott számla nem befizetés."""
    torolt = {k.lstrip("0") for k in sztornozott_kulcsok(tarolt.get("szamlak") or {})}
    reszek: dict[str, tuple[date, Decimal]] = {}
    for r in tarolt.get("reszszamlak", []):
        n = str(r.get("sorszam") or "").lstrip("0")
        if (n and n in torolt) or r.get("osszeg") in (None, ""):  # összeg nélküli tétel nem befizetés
            continue
        reszek[n or _bef_kulcs(r["datum"], r["osszeg"])] = (_d(r["datum"]), Decimal(str(r["osszeg"])))
    for kelt, osszeg, szlaszam in dijnet or []:
        n = str(szlaszam).lstrip("0")
        if n not in reszek and n not in torolt and _bef_kulcs(kelt.isoformat(), osszeg) not in reszek:
            reszek[n] = (kelt, osszeg)
    return reszek


def sajat_ertek(x: dict[str, Any]) -> Decimal | None:
    """Egy tárolt számla saját bruttó értéke (a folyószámla-tételek – túlfizetés, átvezetés, kötbér – nélkül); MVM
    villanynál mindig a számlaérték (a fizetendő a közös folyószámla egyenlegét is tartalmazhatja); ha a számlán nincs
    külön számlaérték, a fizetendő."""
    sajat = x.get("egyeb_tetelek") or (x.get("forras") == "mvm_aram" and x.get("tipus") != "storno")
    v = x.get("szamlaertek") if sajat and x.get("szamlaertek") is not None else x.get("osszeg")
    return None if v is None else Decimal(str(v))


def _honap_mulva(d: date, honap: int) -> date:
    import calendar  # noqa: PLC0415

    ev, ho = divmod(d.month - 1 + honap, 12)
    ev, ho = d.year + ev, ho + 1
    return d.replace(year=ev, month=ho, day=min(d.day, calendar.monthrange(ev, ho)[1]))


def szamla_statisztika(tarolt: dict[str, Any], ma: date, fix_dij: bool = False, honap: int | None = None,
                       idenyes: list[int] | None = None, szamla_dij: Decimal | None = None) -> dict[str, Any] | None:
    """Az utolsó 12 hónap számláinak összege, és a következő számla várható napja és összege
    (a beállított számlázási gyakoriság, ennek híján a legutóbbi számlák szokásos időköze alapján). Figyelmeztet
    díjváltozásra és elmaradt számlára. idenyes: idényes díjnál (pl. üdülő hulladékdíja) a díjköteles hónapok – a
    díjmentes időszakra nem jön számla, a következő a következő idényben."""
    # A számla saját (bruttó) értéke – nem a fizetendő: az MVM közös folyószámláján a fizetendő egy másik fiók
    # jóváírását / túlfizetését is tartalmazhatja (pl. H-számla 22 607 Ft, fizetendő −25 522 Ft).
    # A stornó és az általa sztornózott számla kimarad (az újra kiállított számít).
    kihagy = ervenytelenek(tarolt.get("szamlak") or {})
    szamlak = sorted(
        (_d(x["kelte"]), v, x.get("idoszak") or [x.get("idoszak_tol"), x.get("idoszak_ig")], k)
        for k, x in (tarolt.get("szamlak") or {}).items()
        if k not in kihagy and (v := sajat_ertek(x)) is not None and v != 0
    )
    if not szamlak:
        return None
    sz = [(d, v) for d, v, *_ in szamlak]
    eves = [x for d, x in sz if (ma - d).days <= 365]
    utolsok = sz[-5:]
    kozok = sorted((b[0] - a[0]).days for a, b in zip(utolsok, utolsok[1:]))
    idokoz = kozok[len(kozok) // 2] if kozok else None
    kovetkezo = date.fromordinal(sz[-1][0].toordinal() + idokoz) if idokoz else None
    if honap:
        kovetkezo, idokoz = _honap_mulva(sz[-1][0], honap), idokoz or honap * 30
        ig = szamlak[-1][2][1] if szamlak[-1][2] and szamlak[-1][2][1] else None
        if idenyes and ig:
            # A következő számlázási időszak(ok) díjmentesek (idényen kívül): a következő számla a következő idényben.
            kezd = _d(ig).replace(day=1)
            kezd = _honap_mulva(kezd, 1)
            for _ in range(12 // honap):
                if any(_honap_mulva(kezd, i).month in idenyes for i in range(honap)):
                    break
                kezd, kovetkezo = _honap_mulva(kezd, honap), _honap_mulva(kovetkezo, honap)
    figy = []
    dij_elteres = None

    def napok(i: int) -> int | None:
        tol, ig = (szamlak[i][2] or [None, None])[:2]
        return (_d(ig) - _d(tol)).days if tol and ig else None

    if fix_dij and szamla_dij:
        # Ismert havidíjnál (× számlázási hónapok) a legutóbbi számla ehhez mérve: egyszeri tétel (kiszállás, munkadíj)
        # vagy díjváltozás – a két számla közti különbség önmagában félrevezető.
        elt = sz[-1][1] - szamla_dij
        nyugtazva = szamlak[-1][3] in (tarolt.get("dijelteres_nyugtazva") or [])
        if abs(elt) > 1 and not nyugtazva and not (napok(-1) is not None and honap and abs(napok(-1) - honap * 30.4) > 5):
            # A panel gombjaihoz: „ez az új havidíj” (felülírás a számla időszakának kezdetétől) / „egyszeri eltérés”.
            tol_ = (szamlak[-1][2] or [None])[0]
            dij_elteres = {"sorszam": szamlak[-1][3], "osszeg": int(sz[-1][1]), "dij": int(szamla_dij), "elteres": int(elt),
                           "tol": str(tol_)[:10] if tol_ else sz[-1][0].isoformat(), "honap": honap or 1}
            figy.append(f"a legutóbbi számla {int(sz[-1][1])} Ft – {int(abs(elt))} Ft-tal {'több' if elt > 0 else 'kevesebb'}, "
                        f"mint a díj ({int(szamla_dij)} Ft): egyszeri tétel vagy díjváltozás")
    # Változó számláknál ez csak zaj; és csak azonos hosszú időszakokat vet össze (az első, tört időszak arányos).
    elif fix_dij and len(sz) >= 2 and sz[-1][1] != sz[-2][1] and not (
            napok(-1) is not None and napok(-2) is not None and abs(napok(-1) - napok(-2)) > 3):
        figy.append(f"díjváltozás: {sz[-2][1]} → {sz[-1][1]} Ft")
    if kovetkezo and honap:
        lemondott, n, alap = lemondott_datumok(tarolt), 1, kovetkezo
        while kovetkezo.isoformat() in lemondott:
            n += 1
            kovetkezo = _honap_mulva(sz[-1][0], honap * n) if not idenyes else _honap_mulva(alap, honap * (n - 1))
    if kovetkezo and (ma - kovetkezo).days > 21:
        figy.append(f"elmaradt számla: {kovetkezo.isoformat()} körül kellett volna jönnie")
    return {
        "eves_osszeg": int(sum(eves, Decimal(0))),
        "eves_db": len(eves),
        "kovetkezo_datum": kovetkezo,
        "kovetkezo_osszeg": int(sz[-1][1]),
        "idokoz_nap": idokoz,
        "figyelmeztetes": "; ".join(figy) or None,
        "dij_elteres": dij_elteres,
    }


def atalany_szamitas(beallitott: Any, tarolt: dict[str, Any], tol: date, ig: date, most: Any) -> dict[str, Any] | None:
    """Átalányos (részszámlás) fiók havi fizetendője: az átalány napra leosztva × a hónap napjai.

    A napi összeg: a beállított átalány × 12 / 365, vagy az utolsó részszámla összege / a számla időszakának napjai
    (ha a számlán nincs időszak: összeg × 12 / 365).
    """
    napi, forras = None, None
    if beallitott:
        napi = Decimal(str(beallitott)) * 12 / 365
        forras = f"beállított átalány: {int(Decimal(str(beallitott)))} Ft/hó"
    else:
        torolt = sztornozott_kulcsok(tarolt.get("szamlak") or {})
        reszek = sorted(
            ((k, x) for k, x in (tarolt.get("szamlak") or {}).items()
             if k not in torolt and x.get("tipus") == "resz" and x.get("osszeg") is not None and Decimal(str(x["osszeg"])) > 0),
            key=lambda kv: kv[1]["kelte"],
        )
        if reszek:
            sorszam, x = reszek[-1]
            osszeg = Decimal(str(x["osszeg"]))
            if x.get("idoszak"):
                napok = (_d(x["idoszak"][1]) - _d(x["idoszak"][0])).days + 1
                napi, forras = osszeg / napok, f"{sorszam} részszámla: {int(osszeg)} Ft / {napok} nap"
            else:
                napi, forras = osszeg * 12 / 365, f"{sorszam} részszámla: {int(osszeg)} Ft/hó"
        elif tarolt.get("reszszamlak"):
            utolso = sorted(tarolt["reszszamlak"], key=lambda r: r["datum"])[-1]
            napi = Decimal(str(utolso["osszeg"])) * 12 / 365
            forras = f"kézi részszámla {utolso['datum']}: {utolso['osszeg']} Ft/hó"
    if napi is None:
        return None
    honap_napjai = (ig - tol).days
    eltelt = min(max((most.date() - tol).days + 1, 0), honap_napjai)
    # Több hónapos (pl. kéthavi számlázási) időszakban a havi egy átlagos hónap, az időszaké az idoszak_ft.
    havi = napi * honap_napjai if honap_napjai <= 31 else napi * 365 / 12
    return {
        "napi": round(float(napi), 2),
        "havi": int(round(havi)),
        "idoszak_ft": int(round(napi * honap_napjai)),
        "eddig": int(round(napi * eltelt)),
        "napok": honap_napjai,
        "eltelt_nap": eltelt,
        "forras": forras,
    }


def _honap_mulva(d: date, honap: int) -> date:
    import calendar  # noqa: PLC0415

    ev, ho = divmod(d.month - 1 + honap, 12)
    ev, ho = d.year + ev, ho + 1
    return d.replace(year=ev, month=ho, day=min(d.day, calendar.monthrange(ev, ho)[1]))


def lemondott_datumok(tarolt: dict[str, Any]) -> set[str]:
    """A lemondott várt számlák (várt kelte, ISO) – csak a legutóbbi valódi számla utániak számítanak: ha azóta jött
    számla, a várt számla innen újraszámolódik, a régi lemondás hatástalan."""
    utolso = max((str(x.get("kelte") or "")[:10] for x in (tarolt.get("szamlak") or {}).values()), default="")
    return {x["kovetkezo_datum"] for x in tarolt.get("lemondott_szamlak") or [] if x.get("kovetkezo_datum", "") > utolso}


def esedekes(
    tarolt: dict[str, Any], ma: date, periodus_honap: int | None, varhato_osszeg: Decimal | None,
    kozos_utolso: date | None = None,
) -> dict[str, Any] | None:
    """Ebben a hónapban esedékes számlák: a már kiállítottak és a számlázási ütem szerint még várható.

    kozos_utolso: közös számlázásnál (MVM: egy ügyfél áramfiókjai együtt) a társfiókok legutóbbi számlájának kelte –
    ha későbbi a sajátnál, a következő számla ettől az ütem szerint (a számlák együtt jönnek).

    periodus_honap: számlázási ütem (1 havi, 2 kéthavi, 3 negyedéves); ha nincs megadva, a számlák
    szokásos időközéből. varhato_osszeg: a következő számla várható összege (átalány × időszak, fix díj);
    ha nincs, az utolsó számla összege.
    """
    sz = sorted(
        (_d(x["kelte"]), Decimal(str(x["osszeg"])), k)
        for k, x in (tarolt.get("szamlak") or {}).items()
        if x.get("osszeg") is not None and Decimal(str(x["osszeg"])) != 0
    )
    if not sz:
        return None
    if not periodus_honap:
        utolsok = sz[-5:]
        kozok = sorted((b[0] - a[0]).days for a, b in zip(utolsok, utolsok[1:]))
        periodus_honap = max(1, round((kozok[len(kozok) // 2] if kozok else 30) / 30.4))
    ho_eleje = ma.replace(day=1)
    ho_vege = _honap_mulva(ho_eleje, 1)
    e_havi = [(d, x, k) for d, x, k in sz if ho_eleje <= d < ho_vege]
    alap = max(sz[-1][0], kozos_utolso) if kozos_utolso else sz[-1][0]
    kovetkezo = _honap_mulva(alap, periodus_honap)
    # A felhasználó jóváhagyásával lemondott (soha meg nem érkező) várt számla: a következő az utána jövő ütem.
    lemondott, n = lemondott_datumok(tarolt), 1
    while kovetkezo.isoformat() in lemondott:
        n += 1
        kovetkezo = _honap_mulva(alap, periodus_honap * n)  # a hónap vége ne csússzon (aug. 31. → okt. 31.)
    elmaradt = kovetkezo < ho_eleje
    osszeg = Decimal(varhato_osszeg) if varhato_osszeg is not None else sz[-1][1]
    e_havi_varhato = osszeg if (ho_eleje <= kovetkezo < ho_vege) else (osszeg if elmaradt else Decimal(0))
    return {
        "periodus_honap": periodus_honap,
        "kovetkezo_datum": kovetkezo,
        "kovetkezo_osszeg": int(round(osszeg)),
        "elmaradt": elmaradt,
        "e_havi_kiallitott": int(sum((x for _, x, _ in e_havi), Decimal(0))),
        "e_havi_szamlak": [{"kelte": d.isoformat(), "osszeg": int(x), "sorszam": k} for d, x, k in e_havi],
        "e_havi_varhato": int(round(e_havi_varhato)),
        "e_havi_osszesen": int(sum((x for _, x, _ in e_havi), Decimal(0)) + round(e_havi_varhato)),
    }


def szamlazasi_eltolas(tarolt: dict[str, Any]) -> int | None:
    """A számla elszámolt időszakának kezdete hány hónappal van a kiállítás hónapja előtt/után a legutóbbi időszakos
    számlán (MOHU: júl. 1. – okt. 8. → −3, utólagos; mérő nélküli gáz: ápr. 1. – máj. 27. → −1, a negyedév közepén)."""
    lista = sorted((x["kelte"], x["idoszak"]) for x in (tarolt.get("szamlak") or {}).values()
                   if x.get("idoszak") and x.get("kelte") and x.get("tipus") != "storno")
    if not lista:
        return None
    kelte, (tol, _) = lista[-1]
    k, t = _d(kelte), _d(tol)
    return (t.year - k.year) * 12 + t.month - k.month


def szamlazasi_ablak(
    ma: date, periodus: int, es: dict[str, Any], napi_atalany: Decimal | None = None, eltolas: int | None = None,
    minimum: int = 2,
) -> dict[str, Any] | None:
    """Többhavi, UTÓLAGOS számlázás (víz: kéthavi, hulladék: negyedéves) ablaka.

    A B hónapban kiállított számla a megelőző „periodus” hónapot számolja el: [B − periodus, B).
    Ha ebben a hónapban van (kiállított vagy várható) számla, B = ez a hónap, és az ablak már lezárt;
    különben B a következő számla hónapja, az ablak a mostani hónapot is tartalmazza (folyó, „nem esedékes”).
    Fizetendő: a kiállított számla, különben átalánynál napi átalány × az ablak napjai, fix díjnál a várható összeg.
    """
    if periodus < minimum or not es:
        return None  # minimum=1: havi fix díj (pl. közös költség előírása) – a hónap fizetendője
    ho = ma.replace(day=1)
    most_esedekes = es["e_havi_osszesen"] > 0
    b = ho if most_esedekes else es["kovetkezo_datum"].replace(day=1)
    # Alapból utólagos: a B hónapban kiállított számla a megelőző időszakot számolja el; „eltolas” a számlák szerint
    # (pl. −1: a negyedév 2. hónapjában az adott negyedévről).
    tol = _honap_mulva(b, eltolas if eltolas is not None else -periodus)
    ig = _honap_mulva(tol, periodus)
    napok = (ig - tol).days
    lezart = ma >= ig
    eltelt = napok if lezart else (ma - tol).days + 1
    kiallitott = es["e_havi_kiallitott"] if most_esedekes and es["e_havi_kiallitott"] else None
    if kiallitott is not None:
        fizetendo = kiallitott
    elif napi_atalany is not None:
        fizetendo = int(round(napi_atalany * napok))
    else:
        fizetendo = es["kovetkezo_osszeg"]
    return {
        "honap": periodus,
        "tol": tol,
        "ig": ig,
        "napok": napok,
        "eltelt_nap": eltelt,
        "lezart": lezart,
        "esedekes_most": most_esedekes,
        "kiallitott": kiallitott is not None,
        "szamla_datum": (es["e_havi_szamlak"][-1]["kelte"] if kiallitott is not None else es["kovetkezo_datum"].isoformat())
        if most_esedekes else es["kovetkezo_datum"].isoformat(),
        "kovetkezo_datum": es["kovetkezo_datum"].isoformat(),
        "kovetkezo_osszeg": es["kovetkezo_osszeg"],
        "fizetendo": fizetendo,
        "fizetendo_eddig": fizetendo if lezart else int(round(fizetendo * eltelt / napok)),
    }


def kezi_idoszak_potlas(tarolt: dict[str, Any], uton: list[dict[str, Any]]) -> bool:
    """Időszak nélkül, kézzel rögzített számla időszaka: a legrégebbi lezárt, még nem számlázott („úton lévő”) időszak,
    amely a számla kelte előtt (60 napon belül) zárult. Enélkül a kézi számla nem „fedi le” az időszakot: a panel és a
    kártya tovább várja (sárga dőlt) a már megérkezett számlát. Visszatérés: változott-e valami."""
    szamlak = tarolt.get("szamlak") or {}
    szabad = sorted(uton, key=lambda x: x["tol"])
    valt = False
    for k, x in sorted(szamlak.items(), key=lambda kv: kv[1].get("kelte") or ""):
        if not x.get("kezi") or x.get("idoszak") or x.get("tipus") == "storno" or not x.get("kelte"):
            continue
        kelte = _d(x["kelte"])
        for u in szabad:
            if _d(u["ig"]) <= kelte and (kelte - _d(u["ig"])).days <= 60:
                x["idoszak"] = [u["tol"], u["ig"]]
                x["idoszak_potolva"] = True
                szabad.remove(u)
                valt = True
                break
    return valt


def kezi_szamla(
    tarolt: dict[str, Any],
    kelte: date,
    osszeg: Decimal,
    tipus: str = "resz",
    sorszam: str = "",
    idoszak: tuple[date, date] | None = None,
    zaro_allas: Decimal | None = None,
    leolvasott: bool = False,
    futoertek: Decimal | None = None,
    hatarido: date | None = None,
) -> Szamla:
    """Kézzel bevitt számla, ugyanabban a formában, mint a mappából beolvasott (rogzit() dolgozza fel).

    A záró mérőállás az időszak utolsó napjára (időszak nélkül a kelte napjára) kerül, a fiók azon a napon
    aktív fő mérőjéhez. Fűtőérték (gáz, MJ/m³): az időszak minden hónapjára, időszak nélkül a kelte hónapjára.
    """
    if not sorszam:
        ismert = tarolt.get("szamlak") or {}
        n = 1
        while f"kezi-{kelte.isoformat()}-{n}" in ismert:
            n += 1
        sorszam = f"kezi-{kelte.isoformat()}-{n}"
    if tipus == "storno":
        # Stornó: a számla értéke a sztornózott számla értékének mínusza (jóváírás); fizetendő nincs.
        sz = Szamla(forras="kezi", sorszam=sorszam, kelte=kelte, osszeg=Decimal(0), tipus=tipus, idoszak=idoszak, fajl="",
                    hatarido=hatarido, szamlaertek=-abs(osszeg))
        return sz
    sz = Szamla(forras="kezi", sorszam=sorszam, kelte=kelte, osszeg=osszeg, tipus=tipus, idoszak=idoszak, fajl="", hatarido=hatarido)
    if zaro_allas is not None:
        nap = idoszak[1] if idoszak else kelte
        mero = _aktiv(tarolt.get("merok") or [], nap)
        sz.meroallasok.append(
            Meroallas(mero_azonosito((mero or {}).get("gyari_szam", "")), nap, Decimal(zaro_allas), "Leol" if leolvasott else "Dikt")
        )
    if futoertek is not None:
        tol, ig = idoszak or (kelte, kelte)
        ho = date(tol.year, tol.month, 1)
        while ho <= ig:
            sz.futoertekek[f"{ho.year:04d}-{ho.month:02d}"] = Decimal(futoertek)
            ho = date(ho.year + ho.month // 12, ho.month % 12 + 1, 1)
    return sz


def szamla_torles(tarolt: dict[str, Any], sorszam: str) -> bool:
    """Egy számla és a belőle jött befizetés, mérőállások törlése. Igaz, ha volt ilyen számla."""
    if sorszam not in (tarolt.get("szamlak") or {}):
        return False
    del tarolt["szamlak"][sorszam]
    tarolt["reszszamlak"] = [r for r in tarolt.get("reszszamlak", []) if r.get("sorszam") != sorszam]
    for lista in (tarolt.get("merok") or [], tarolt.get("almero_merok") or []):
        for mero in lista:
            mero["leolvasasok"] = [
                lo for lo in mero["leolvasasok"] if not lo.get("megjegyzes", "").startswith(f"számla {sorszam} (")
            ]
    return True


def mappas_adatok_torlese(tarolt: dict[str, Any], minden_meroallas: bool = False) -> None:
    """A számlamappából jött számlák, befizetések és mérőállások törlése (újraolvasás előtt). A kézzel rögzített
    számlák a befizetésükkel és a mérőállásukkal maradnak; minden_meroallas=True: a többi mérőállás is törlődik."""
    # A kézi és az AI-val kiolvasott (jóváhagyott) számlák maradnak – ez utóbbiak a fájlból nem olvashatók újra.
    kezi = {k: v for k, v in (tarolt.get("szamlak") or {}).items() if v.get("kezi") or v.get("forras") == "ai"}
    tarolt["szamlak"] = kezi
    tarolt["feldolgozott_fajlok"] = []
    tarolt["ismeretlen_fajlok"] = []
    tarolt.pop("nem_olvasott_fajlok", None)
    tarolt["reszszamlak"] = [r for r in tarolt.get("reszszamlak", []) if not r.get("sorszam") or r["sorszam"] in kezi]
    kezi_megj = tuple(f"számla {k} (" for k in kezi)
    for lista in (tarolt.get("merok") or [], tarolt.get("almero_merok") or []):
        for mero in lista:
            mero["leolvasasok"] = [
                lo for lo in mero["leolvasasok"]
                if (kezi_megj and lo.get("megjegyzes", "").startswith(kezi_megj))
                or (not minden_meroallas and not lo.get("megjegyzes", "").startswith("számla "))
            ]


def automatikus_rendezes(fiokok: dict[str, tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]] | None]],
                         csoport: dict[str, list[str]], most: str) -> list[tuple[str, str, dict[str, Any]]]:
    """A ki nem számlázott (soha meg nem érkező) várt számlák automatikus rendezése, ha egy későbbi számla jött.

    fiokok: {sid: (tarolt, esedekes, uton_szamlak)}; csoport: {sid: a közös folyószámla fiókjai (önmagát is)} –
    MVM-nél a fizetendő a folyószámla szerint, az áramfiókok összevonva, így egy társfiók későbbi számlája is
    elszámolhatja. Szabályok:
    - úton lévő (lezárt, saját számítású) számla: ha azóta jött későbbi kelte számla a fióknak vagy egy társfióknak;
    - késő várt számla (átalány, fix díj, diktálás): ha a várt kelte után egy társfiók számlája jött (a saját későbbi
      számla úgyis újraindítja a várakozást).
    Az eredményt a tárolt adatba írja (rendezett_uton / lemondott_szamlak, auto jelöléssel); visszaadja: (sid, fajta, bejegyzés)."""
    def valodi(t: dict[str, Any]) -> list[tuple[str, str, str]]:
        """(kelte, sorszám, az elszámolt időszak utolsó napja – vagy "" ha nincs a számlán)."""
        kihagy = ervenytelenek(t.get("szamlak") or {})
        def vege(x: dict[str, Any]) -> str:
            i = szamlazott_idoszak(x)
            return i[1].isoformat() if i else ""
        return sorted((str(x.get("kelte"))[:10], k, vege(x)) for k, x in (t.get("szamlak") or {}).items()
                      if x.get("kelte") and k not in kihagy and x.get("tipus") != "storno")
    out: list[tuple[str, str, dict[str, Any]]] = []
    for sid, (tarolt, es, uton) in fiokok.items():
        tars = [s for s in csoport.get(sid) or [sid] if s != sid and s in fiokok]
        tars_sz = sorted(x for s in tars for x in valodi(fiokok[s][0]))
        sajat_sz = valodi(tarolt)
        mar = {x.get("tol") for x in tarolt.get("rendezett_uton") or []}
        for u in uton or []:
            # Közös (MVM) folyószámlán bármely későbbi számla elszámolhatja (a befizetés mindent kiegyenlít); máshol a saját
            # számla csak akkor, ha az időszaka eléri az úton lévőt (egy késve jött korábbi számla nem rendezi).
            jelolt = sajat_sz + tars_sz if tars else [x for x in sajat_sz if x[2] and x[2] >= str(u.get("tol") or "")]
            kesobbi = next((x for x in sorted(jelolt) if x[0] > str(u.get("ig") or "9999")), None)
            if kesobbi and u.get("tol") and u["tol"] not in mar:
                bej = {"tol": u["tol"], "ig": u.get("ig"), "osszeg": u.get("osszeg"), "auto": True, "sorszam": kesobbi[1],
                       "rogzitve": most}
                tarolt.setdefault("rendezett_uton", []).append(bej)
                out.append((sid, "uton", bej))
        if es and es.get("elmaradt") and es.get("kovetkezo_datum"):
            varva = es["kovetkezo_datum"]
            varva = varva.isoformat() if hasattr(varva, "isoformat") else str(varva)[:10]
            kesobbi = next((x for x in tars_sz if x[0] > varva), None)
            if kesobbi and varva not in lemondott_datumok(tarolt):
                bej = {"kovetkezo_datum": varva, "tol": None, "ig": None, "osszeg": es.get("kovetkezo_osszeg"), "auto": True,
                       "sorszam": kesobbi[1], "rogzitve": most}
                tarolt.setdefault("lemondott_szamlak", []).append(bej)
                out.append((sid, "lemondas", bej))
    return out
