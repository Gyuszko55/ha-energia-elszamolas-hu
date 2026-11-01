"""Verziózott díjszabás-fájlok betöltése, ellenőrzése és feloldása egy adott napra.

Formátum: docs/terv/02_DIJSZABAS_FORMATUM.md.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .tipusok import Feluliras

KERET_TIPUSOK = {"napi_aranyos", "havi_sulyozott", "eves", "nincs"}


class DijszabasHiba(ValueError):
    pass


def _dec(x: Any) -> Any:
    """Számok Decimal-ra (szövegen át, hogy a 36.386 pontosan 36.386 maradjon)."""
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, (int, float)):
        return Decimal(str(x))
    if isinstance(x, dict):
        return {k: _dec(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_dec(v) for v in x]
    return x


# A tarifaadat ellenőrzöttsége (a verzió „ellenorzes.allapot” mezője):
ELLENORZES_ALLAPOTOK = {
    "szamlaval_egyezik": "valódi számlával forintra összevetve",
    "szamlabol": "a díjak egy valódi számláról, forintos összevetés nélkül",
    "arlapbol": "a szolgáltató hivatalos árlapjáról",
    "ellenorizendo": "nem hivatalos vagy hiányos forrás – ellenőrizendő",
    "sablon": "sablon, a díjakat a felhasználó adja meg",
}

# „szamlaval_egyezik” állapotnál kötelező a „validalas” lista: mely számlák igazolták (számlacsoportonként).
VALIDALAS_ELSZAMOLAS = {
    "diktalas": "diktálás szerint, havonta",
    "atalany": "átalány (részszámla) + elszámoló",
    "leolvasas": "leolvasás szerint",
    "tavleolvasas": "távleolvasás",
    "fix": "fix díj / mérő nélküli átalány",
}
VALIDALAS_SZAMLA = {
    "havi": "havi", "resz": "részszámla", "elszamolo": "elszámoló", "ketthavi": "kéthavi",
    "negyedeves": "negyedéves", "vegszamla": "végszámla",
}
VALIDALAS_HMKE = {"szaldo": "éves szaldó", "brutto": "bruttó elszámolás"}


def _validalas_hiba(azonosito: str, lista: Any) -> str | None:
    """A „validalas” lista ellenőrzése – hibaszöveg vagy None."""
    if not isinstance(lista, list) or not lista:
        return "„szamlaval_egyezik” állapothoz kell a „validalas” lista (szolgáltató, elszámolási mód, számlatípus, számlák)"
    for i, x in enumerate(lista):
        if not isinstance(x, dict) or not str(x.get("szolgaltato", "")).strip():
            return f"validalas[{i}]: hiányzik a szolgáltató"
        if x.get("elszamolas") not in VALIDALAS_ELSZAMOLAS:
            return f"validalas[{i}]: ismeretlen elszámolási mód: {x.get('elszamolas')!r}"
        tipusok = x.get("szamla_tipusok")
        if not tipusok or any(t not in VALIDALAS_SZAMLA for t in tipusok):
            return f"validalas[{i}]: ismeretlen vagy hiányzó számlatípus: {tipusok!r}"
        db, ok = x.get("szamlak"), x.get("forintra")
        if not isinstance(db, int) or db < 1 or not isinstance(ok, int) or not 0 <= ok <= db:
            return f"validalas[{i}]: a „szamlak” (≥1) és a „forintra” (0…szamlak) egész szám"
        if azonosito == "villany/hmke" and x.get("hmke") not in VALIDALAS_HMKE:
            return f"validalas[{i}]: HMKE-nél kötelező a „hmke”: szaldo / brutto"
    return None


@dataclass(frozen=True)
class Verzio:
    ervenyes_tol: date
    forras: str
    szabalyok: dict[str, Any]
    dijak: dict[str, dict[str, Decimal]]
    ervenyes_ig: date | None = None  # ha ismert a vége (különben a következő verzióig)
    ellenorzes: dict[str, Any] | None = None  # {allapot, datum, mivel, validalas}


@dataclass(frozen=True)
class Dijszabas:
    azonosito: str
    nev: str
    kozmu: str
    egyseg: str
    verziok: tuple[Verzio, ...]

    def verzio(self, nap: date) -> Verzio:
        """A napon érvényes verzió. Az első verzió előtti napra (pl. a fiók 2024-es kezdete, de a díjszabás csak egy
        későbbi árlapról ismert) az első verzió – nem hiba, hogy egy korai nap ne állítsa le az egész fiókot; a
        feloldás „verzio_elott” jelzéssel jelöli (a szelet becsült)."""
        jo = [v for v in self.verziok if v.ervenyes_tol <= nap]
        return jo[-1] if jo else self.verziok[0]


@dataclass(frozen=True)
class Ervenyes:
    """Egy díjszabás feloldva egy napra, egy szolgáltatóra, a felülírásokkal együtt."""

    azonosito: str
    verzio_tol: date
    szabalyok: dict[str, Any]
    dijak: dict[str, Decimal]
    verzio_elott: bool = False  # a nap az első ismert verzió előtti: annak díjaival, becsült

    @property
    def cimke(self) -> str:
        return f"{self.azonosito}@{self.verzio_tol.isoformat()}"


def ellenoriz(adat: dict[str, Any], hely: str = "") -> None:
    hiba = lambda msg: DijszabasHiba(f"{hely or adat.get('azonosito', '?')}: {msg}")  # noqa: E731
    for kulcs in ("azonosito", "nev", "kozmu", "egyseg", "verziok"):
        if kulcs not in adat:
            raise hiba(f"hiányzó mező: {kulcs}")
    if adat["kozmu"] not in ("villany", "gaz", "viz", "hulladek", "tavho", "kozos", "tavkozles"):
        raise hiba(f"ismeretlen közmű: {adat['kozmu']}")
    verziok = adat["verziok"]
    if not isinstance(verziok, list) or not verziok:
        raise hiba("a verziók listája üres")
    elozo = None
    for v in verziok:
        tol = v.get("ervenyes_tol")
        if not isinstance(tol, date):
            raise hiba(f"érvénytelen ervenyes_tol: {tol!r}")
        if elozo is not None and tol <= elozo:
            raise hiba("a verziók nincsenek szigorúan időrendben")
        elozo = tol
        if not str(v.get("forras", "")).strip():
            raise hiba(f"{tol}: a forrás kötelező")
        ig = v.get("ervenyes_ig")
        if ig is not None and (not isinstance(ig, date) or ig <= tol):
            raise hiba(f"{tol}: érvénytelen ervenyes_ig: {ig!r}")
        ell = v.get("ellenorzes")
        if ell is not None:
            if ell.get("allapot") not in ELLENORZES_ALLAPOTOK:
                raise hiba(f"{tol}: ismeretlen ellenőrzési állapot: {ell.get('allapot')!r}")
            if not isinstance(ell.get("datum"), date) or not str(ell.get("mivel", "")).strip():
                raise hiba(f"{tol}: az ellenőrzéshez dátum és „mivel” kell")
            if ell.get("allapot") == "szamlaval_egyezik" and (vh := _validalas_hiba(adat.get("azonosito", ""), ell.get("validalas"))):
                raise hiba(f"{tol}: {vh}")
        if "alap" not in (v.get("dijak") or {}):
            raise hiba(f"{tol}: hiányzik a dijak.alap sor")
        sz = v.get("szabalyok") or {}
        keret = sz.get("keret")
        if keret is not None and keret.get("tipus") not in KERET_TIPUSOK:
            raise hiba(f"{tol}: ismeretlen kerettípus: {keret.get('tipus')}")
        for k in sz.get("kiegeszito") or []:
            if not k.get("nev") or not k.get("dij"):
                raise hiba(f"{tol}: a kiegészítő tételhez „nev” és „dij” kell")
            if k["dij"] not in (v["dijak"].get("alap") or {}):
                raise hiba(f"{tol}: a kiegészítő tétel díja ({k['dij']}) hiányzik a dijak.alap sorból")
        for idx, idenyszak in enumerate(sz.get("idenyszak") or []):
            if "nev" not in idenyszak:
                raise hiba(f"{tol}: az {idx}. idényszaknak nincs neve")
        for szolg, sor in v["dijak"].items():
            for k, ertek in (sor or {}).items():
                if ertek is not None and not isinstance(ertek, (int, float)):
                    raise hiba(f"{tol}: dijak.{szolg}.{k} nem szám: {ertek!r}")


def betolt_fajl(adat: dict[str, Any], hely: str = "") -> Dijszabas:
    ellenoriz(adat, hely)
    verziok = tuple(
        Verzio(
            ervenyes_tol=v["ervenyes_tol"],
            forras=str(v["forras"]),
            szabalyok=_dec(v.get("szabalyok") or {}),
            dijak={k: _dec(s or {}) for k, s in v["dijak"].items()},
            ervenyes_ig=v.get("ervenyes_ig"),
            ellenorzes=v.get("ellenorzes"),
        )
        for v in adat["verziok"]
    )
    return Dijszabas(adat["azonosito"], adat["nev"], adat["kozmu"], adat["egyseg"], verziok)


class DijszabasTar:
    """Az összes díjszabás egy helyen, azonosító szerint."""

    def __init__(self, dijszabasok: dict[str, Dijszabas], szolgaltatok: dict[str, dict] | None = None) -> None:
        self.dijszabasok = dijszabasok
        self.szolgaltatok = szolgaltatok or {}
        for d in dijszabasok.values():
            for v in d.verziok:
                for i in v.szabalyok.get("idenyszak") or []:
                    ref = i.get("dijszabas")
                    if ref and ref not in dijszabasok:
                        raise DijszabasHiba(f"{d.azonosito}: hivatkozott díjszabás nem létezik: {ref}")

    @classmethod
    def mappabol(cls, mappa: Path) -> DijszabasTar:
        dijszabasok: dict[str, Dijszabas] = {}
        szolgaltatok: dict[str, dict] = {}
        for fajl in sorted(mappa.rglob("*.yaml")):
            adat = yaml.safe_load(fajl.read_text(encoding="utf-8"))
            if fajl.name == "szolgaltatok.yaml":
                szolgaltatok = adat or {}
                continue
            d = betolt_fajl(adat, str(fajl.relative_to(mappa)))
            if d.azonosito in dijszabasok:
                raise DijszabasHiba(f"kétszer szereplő azonosító: {d.azonosito}")
            dijszabasok[d.azonosito] = d
        return cls(dijszabasok, szolgaltatok)

    def __getitem__(self, azonosito: str) -> Dijszabas:
        try:
            return self.dijszabasok[azonosito]
        except KeyError as err:
            raise DijszabasHiba(f"ismeretlen díjszabás: {azonosito}") from err

    def felold(
        self, azonosito: str, nap: date, szolgaltato: str, feluliras: list[Feluliras] | None = None
    ) -> Ervenyes:
        v = self[azonosito].verzio(nap)
        dijak = dict(v.dijak["alap"])
        dijak.update({k: x for k, x in v.dijak.get(szolgaltato, {}).items() if x is not None})
        szabalyok = copy.deepcopy(v.szabalyok)
        legutobbi: dict[str, Feluliras] = {}
        for f in feluliras or []:
            if f.ervenyes_tol <= nap and (f.kulcs not in legutobbi or f.ervenyes_tol >= legutobbi[f.kulcs].ervenyes_tol):
                legutobbi[f.kulcs] = f
        for f in legutobbi.values():
            reszek = f.kulcs.split(".")
            if reszek[0] == "dijak" and len(reszek) == 2:
                dijak[reszek[1]] = f.ertek
            elif reszek[0] == "szabalyok":
                cel = szabalyok
                for r in reszek[1:-1]:
                    cel = cel.setdefault(r, {})
                cel[reszek[-1]] = f.ertek
            else:
                raise DijszabasHiba(f"érvénytelen felülírási kulcs: {f.kulcs}")
        return Ervenyes(azonosito, v.ervenyes_tol, szabalyok, dijak, verzio_elott=nap < v.ervenyes_tol)

    def valtozasi_napok(self, azonosito: str) -> set[date]:
        """Minden nap, amikor a díjszabás vagy egy általa hivatkozott díjszabás új verzióra vált."""
        napok: set[date] = set()
        for v in self[azonosito].verziok:
            napok.add(v.ervenyes_tol)
            for i in v.szabalyok.get("idenyszak") or []:
                if i.get("dijszabas"):
                    napok |= {x.ervenyes_tol for x in self[i["dijszabas"]].verziok}
        return napok
