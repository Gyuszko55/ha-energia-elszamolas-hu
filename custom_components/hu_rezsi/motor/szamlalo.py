"""Halmozott fogyasztás-számláló egy csatornára.

A csatorna összes mérőjéből egyetlen, a mérőcseréken át folytonos számlálót épít:
érték(t) = a csatorna első mérőjének beépítése óta elfogyasztott mennyiség.
Két időpont közti fogyasztás = érték(ig) − érték(tól).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from .tipusok import LEOLVASAS_ELSOBBSEG, Csatorna, LeolvasasTipus, Mero

# Ennél nagyobb hézagban interpolált érték „becsült”.
BECSLESI_HEZAG = timedelta(hours=36)


def kezdo_allas(mero: Mero) -> Decimal:
    """A mérő tényleges kezdőállása: a megadott kezdőállás; ha üresen maradt (0), a beépítés napjának (legkorábbi)
    valódi leolvasása – különben az első hónap fogyasztása a teljes óraállás lenne."""
    if mero.kezdo_allas:
        return mero.kezdo_allas
    aznapi = [lo for lo in mero.leolvasasok if lo.datum == mero.beepitve and lo.tipus != LeolvasasTipus.AUTOMATIKUS]
    if not aznapi:
        return mero.kezdo_allas
    return min(aznapi, key=lambda lo: (lo.idopont, -LEOLVASAS_ELSOBBSEG[lo.tipus])).allas


def novekmenyes(sor: list[tuple[datetime, Decimal]]) -> list[tuple[datetime, Decimal]]:
    """Fogyasztás-szenzor sorozata nullázódás-biztosan: halmozott, csak növő érték (az első pontnál 0). Visszalépésnél
    ha az új érték az előző felénél kisebb, nullázódás (az új érték már a nullázódás óta mért fogyasztás), különben
    zaj (0 fogyasztás, az addigi legnagyobb értéktől folytatjuk) – így a nullázódás utáni pontok nem esnek a horgony alá."""
    ki: list[tuple[datetime, Decimal]] = []
    osszeg, elozo = Decimal(0), None
    for t, v in sor:
        if elozo is not None:
            if v >= elozo:
                osszeg += v - elozo
            elif v < elozo / 2:  # nullázódás
                osszeg += max(v, Decimal(0))
            else:  # zaj: az előző (nagyobb) érték marad a viszonyítási alap
                ki.append((t, osszeg))
                continue
        elozo = v
        ki.append((t, osszeg))
    return ki


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
        meroallas: bool = False,
        sorozat_tol: datetime | None = None,
    ) -> Szamlalo:
        """Számláló a mérők leolvasásaiból, opcionálisan egy automatikus (HA) sorozattal kiegészítve.

        meroallas=True: a sorozat értéke (× szorzó) maga az éppen beépített mérő állása.
        meroallas=False: a sorozat csak egy növekvő számláló; minden pontját a megelőző horgonyhoz
        igazítjuk, és csak a változását (× szorzó) adjuk hozzá.
        A leolvasás mindkét esetben felülbírálja a sorozatot. A sorozat_tol előtti pontokat (pl. egy szenzor
        képletének javítása előtti, hibás adatot) figyelmen kívül hagyjuk, és a leolvasásoknak ellentmondó
        pontokat (a számláló nem mehet visszafelé) is eldobjuk.
        """
        horgonyok: dict[datetime, tuple[int, Pont]] = {}

        def tesz(ido: datetime, ertek: Decimal, elsobbseg: int) -> None:
            regi = horgonyok.get(ido)
            if regi is None or elsobbseg >= regi[0]:
                horgonyok[ido] = (elsobbseg, Pont(ido, ertek, True))

        eltolas = Decimal(0)
        merok: list[tuple[Mero, Decimal]] = []
        for mero in sorted(csatorna.merok, key=lambda m: m.beepitve):
            kezdo = kezdo_allas(mero)
            merok.append((mero, eltolas))
            tesz(nap_kezdete(mero.beepitve), eltolas, 10)
            for lo in mero.leolvasasok:
                tesz(lo.idopont, eltolas + lo.allas - kezdo, LEOLVASAS_ELSOBBSEG[lo.tipus])
            if mero.kiszerelve is not None:
                zaro = mero.zaro_allas if mero.zaro_allas is not None else kezdo
                tesz(nap_kezdete(mero.kiszerelve), eltolas + zaro - kezdo, 10)
                eltolas += zaro - kezdo

        alap = cls([p for _, p in horgonyok.values()])
        if not sorozat:
            return alap

        sor = sorted((t, v) for t, v in sorozat if sorozat_tol is None or t >= sorozat_tol)
        if meroallas:
            pontok = list(alap.pontok)
            for t, v in sor:
                if t in horgonyok:
                    continue
                for mero, elt in reversed(merok):
                    if nap_kezdete(mero.beepitve) <= t and (mero.kiszerelve is None or t < nap_kezdete(mero.kiszerelve)):
                        ertek = elt + v * szorzo - kezdo_allas(mero)
                        if alap._hiheto(t, ertek):
                            pontok.append(Pont(t, ertek, False))
                        break
            return cls(pontok)

        # A szenzor nullázódása (pl. Shelly újraindulás) ne vigye a pontokat a horgony alá (ott eldobnánk őket).
        sor = novekmenyes(sor)
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
                # A szenzor előzménye a horgony után indul (pl. ma felvett fiók): a szenzor első értéke
                # a horgonyhoz tartozik, onnan számolunk.
                sh = sor[0][1]
            ertek = h.ertek + (v - sh) * szorzo
            if alap._hiheto(t, ertek):
                pontok.append(Pont(t, ertek, False))
        return cls(pontok)

    def _hiheto(self, t: datetime, ertek: Decimal) -> bool:
        """A sorozatpont nem lehet kisebb az előtte lévő, és nem lehet nagyobb az utána lévő horgonynál."""
        i = bisect_right(self._idok, t)
        if i > 0 and ertek < self.pontok[i - 1].ertek:
            return False
        if i < len(self.pontok) and ertek > self.pontok[i].ertek:
            return False
        return True

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


def idenyre_szoritva(szamlalo: Szamlalo, idenyben: Callable[[date], bool]) -> Szamlalo:
    """H-tarifa regisztere (1.81 téli, 1.82 nyári) csak a saját idénye napjain nő. Két pont között (pl. két diktálás,
    szenzoradat nélkül) a növekményt ezért csak az idénybe eső napokra osztjuk el – különben a lineáris kitöltés a
    nyári regiszterből télre (és fordítva) is jutna. Ha a két pont közt nincs (vagy csak) idénybeli nap, marad a lineáris."""
    pontok = szamlalo.pontok
    uj: list[Pont] = []
    for p, q in zip(pontok, pontok[1:]):
        delta = q.ertek - p.ertek
        if delta <= 0 or q.ido - p.ido <= timedelta(days=1):
            continue
        szakaszok: list[tuple[datetime, datetime, bool]] = []
        t = p.ido
        while t < q.ido:
            kov = min(q.ido, nap_kezdete(t.date() + timedelta(days=1)))
            bent = idenyben(t.date())
            if szakaszok and szakaszok[-1][2] == bent:
                szakaszok[-1] = (szakaszok[-1][0], kov, bent)
            else:
                szakaszok.append((t, kov, bent))
            t = kov
        osszes = sum(((b - a).total_seconds() for a, b, bent in szakaszok if bent), 0.0)
        if len(szakaszok) < 2 or osszes <= 0:
            continue
        eddig = 0.0
        for a, b, bent in szakaszok[:-1]:
            if bent:
                eddig += (b - a).total_seconds()
            uj.append(Pont(b, p.ertek + delta * Decimal(str(eddig / osszes)), False))
    return Szamlalo([*pontok, *uj]) if uj else szamlalo


def kijelzett_allas(csatorna: Csatorna, ertek: Decimal) -> Decimal:
    """A számláló értéke (a csatorna mérőinek összesített fogyasztása, ahogy a Szamlalo.csatornabol építi) → az éppen
    beépített mérő kijelzett állása: − a korábbi (kiszerelt) mérők fogyasztása + a mostani mérő kezdőállása."""
    eltolas, utolso = Decimal(0), None
    for mero in sorted(csatorna.merok, key=lambda m: m.beepitve):
        utolso = (mero, eltolas)
        if mero.kiszerelve is not None:
            zaro = mero.zaro_allas if mero.zaro_allas is not None else kezdo_allas(mero)
            eltolas += zaro - kezdo_allas(mero)
    if utolso is None:
        return ertek
    mero, elt = utolso
    return ertek - elt + kezdo_allas(mero)
