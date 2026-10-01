"""Halmozott fogyasztás-számláló egy csatornára.

A csatorna összes mérőjéből egyetlen, a mérőcseréken át folytonos számlálót épít:
érték(t) = a csatorna első mérőjének beépítése óta elfogyasztott mennyiség.
Két időpont közti fogyasztás = érték(ig) − érték(tól).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from .tipusok import LEOLVASAS_ELSOBBSEG, Csatorna

# Ennél nagyobb hézagban interpolált érték „becsült”.
BECSLESI_HEZAG = timedelta(hours=36)


class NincsAdat(ValueError):
    """Az adott időpontra nem számolható érték (az első mérő beépítése előtt)."""


@dataclass(frozen=True)
class Pont:
    ido: datetime
    ertek: Decimal
    horgony: bool  # leolvasás, beépítés vagy kiszerelés (nem automatikus sorozatpont)


def nap_kezdete(d: date) -> datetime:
    return datetime.combine(d, time())


class Szamlalo:
    def __init__(self, pontok: list[Pont]) -> None:
        self.pontok = sorted(pontok, key=lambda p: p.ido)
        self._idok = [p.ido for p in self.pontok]

    @classmethod
    def csatornabol(
        cls,
        csatorna: Csatorna,
        sorozat: list[tuple[datetime, Decimal]] | None = None,
        szorzo: Decimal = Decimal(1),
    ) -> Szamlalo:
        """Számláló a mérők leolvasásaiból, opcionálisan egy automatikus (HA) sorozattal kiegészítve.

        A sorozat nyers értékei nem a mérőóra állásai: minden sorozatpontot a megelőző horgonyhoz
        igazítunk, és csak a változását (× szorzó) adjuk hozzá. A leolvasás mindig felülbírálja.
        """
        horgonyok: dict[datetime, tuple[int, Pont]] = {}

        def tesz(ido: datetime, ertek: Decimal, elsobbseg: int) -> None:
            regi = horgonyok.get(ido)
            if regi is None or elsobbseg >= regi[0]:
                horgonyok[ido] = (elsobbseg, Pont(ido, ertek, True))

        eltolas = Decimal(0)
        for mero in sorted(csatorna.merok, key=lambda m: m.beepitve):
            tesz(nap_kezdete(mero.beepitve), eltolas, 10)
            for lo in mero.leolvasasok:
                tesz(nap_kezdete(lo.datum), eltolas + lo.allas - mero.kezdo_allas, LEOLVASAS_ELSOBBSEG[lo.tipus])
            if mero.kiszerelve is not None:
                zaro = mero.zaro_allas if mero.zaro_allas is not None else mero.kezdo_allas
                tesz(nap_kezdete(mero.kiszerelve), eltolas + zaro - mero.kezdo_allas, 10)
                eltolas += zaro - mero.kezdo_allas

        alap = cls([p for _, p in horgonyok.values()])
        if not sorozat:
            return alap

        sor = sorted(sorozat)
        sor_idok = [t for t, _ in sor]

        def sor_ertek(t: datetime) -> Decimal | None:
            i = bisect_right(sor_idok, t) - 1
            return sor[i][1] if i >= 0 else None

        pontok = list(alap.pontok)
        for t, v in sor:
            if t in horgonyok:
                continue
            i = bisect_right(alap._idok, t) - 1
            if i < 0:
                continue
            h = alap.pontok[i]
            sh = sor_ertek(h.ido)
            if sh is None:
                continue
            pontok.append(Pont(t, h.ertek + (v - sh) * szorzo, False))
        return cls(pontok)

    @property
    def utolso(self) -> Pont | None:
        return self.pontok[-1] if self.pontok else None

    def ertek(self, t: datetime) -> tuple[Decimal, bool]:
        """(érték, becsült-e) a t időpontban; két pont között lineárisan interpolál."""
        if not self.pontok or t < self._idok[0]:
            raise NincsAdat(t)
        i = bisect_left(self._idok, t)
        if i < len(self.pontok) and self._idok[i] == t:
            return self.pontok[i].ertek, False
        if i == len(self.pontok):
            u = self.pontok[-1]
            return u.ertek, (t - u.ido) > BECSLESI_HEZAG
        a, b = self.pontok[i - 1], self.pontok[i]
        hanyad = Decimal((t - a.ido).total_seconds()) / Decimal((b.ido - a.ido).total_seconds())
        return a.ertek + (b.ertek - a.ertek) * hanyad, (b.ido - a.ido) > BECSLESI_HEZAG

    def fogyasztas(self, tol: datetime, ig: datetime) -> tuple[Decimal, bool]:
        e1, b1 = self.ertek(tol)
        e2, b2 = self.ertek(ig)
        return e2 - e1, b1 or b2

    def meghosszabbitva(self, tol: datetime, napi: Decimal, ig: datetime) -> Szamlalo:
        """Előrejelzéshez: a tol utáni pontok helyett napi ütemű egyenes ig-ig."""
        kezdo, _ = self.ertek(tol)
        pontok = [p for p in self.pontok if p.ido <= tol]
        if not pontok or pontok[-1].ido != tol:
            pontok.append(Pont(tol, kezdo, False))
        napok = Decimal((ig - tol).total_seconds()) / Decimal(86400)
        pontok.append(Pont(ig, kezdo + napi * napok, False))
        return Szamlalo(pontok)
