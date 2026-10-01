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

KERET_TIPUSOK = {"napi_aranyos", "eves", "nincs"}


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


@dataclass(frozen=True)
class Verzio:
    ervenyes_tol: date
    forras: str
    szabalyok: dict[str, Any]
    dijak: dict[str, dict[str, Decimal]]


@dataclass(frozen=True)
class Dijszabas:
    azonosito: str
    nev: str
    kozmu: str
    egyseg: str
    verziok: tuple[Verzio, ...]

    def verzio(self, nap: date) -> Verzio:
        jo = [v for v in self.verziok if v.ervenyes_tol <= nap]
        if not jo:
            raise DijszabasHiba(f"{self.azonosito}: nincs érvényes verzió {nap} napra")
        return jo[-1]


@dataclass(frozen=True)
class Ervenyes:
    """Egy díjszabás feloldva egy napra, egy szolgáltatóra, a felülírásokkal együtt."""

    azonosito: str
    verzio_tol: date
    szabalyok: dict[str, Any]
    dijak: dict[str, Decimal]

    @property
    def cimke(self) -> str:
        return f"{self.azonosito}@{self.verzio_tol.isoformat()}"


def ellenoriz(adat: dict[str, Any], hely: str = "") -> None:
    hiba = lambda msg: DijszabasHiba(f"{hely or adat.get('azonosito', '?')}: {msg}")  # noqa: E731
    for kulcs in ("azonosito", "nev", "kozmu", "egyseg", "verziok"):
        if kulcs not in adat:
            raise hiba(f"hiányzó mező: {kulcs}")
    if adat["kozmu"] not in ("villany", "gaz", "viz", "hulladek"):
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
        if "alap" not in (v.get("dijak") or {}):
            raise hiba(f"{tol}: hiányzik a dijak.alap sor")
        sz = v.get("szabalyok") or {}
        keret = sz.get("keret")
        if keret is not None and keret.get("tipus") not in KERET_TIPUSOK:
            raise hiba(f"{tol}: ismeretlen kerettípus: {keret.get('tipus')}")
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
        return Ervenyes(azonosito, v.ervenyes_tol, szabalyok, dijak)

    def valtozasi_napok(self, azonosito: str) -> set[date]:
        """Minden nap, amikor a díjszabás vagy egy általa hivatkozott díjszabás új verzióra vált."""
        napok: set[date] = set()
        for v in self[azonosito].verziok:
            napok.add(v.ervenyes_tol)
            for i in v.szabalyok.get("idenyszak") or []:
                if i.get("dijszabas"):
                    napok |= {x.ervenyes_tol for x in self[i["dijszabas"]].verziok}
        return napok
