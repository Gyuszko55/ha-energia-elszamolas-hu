"""Ritka leolvasások közti fogyasztás elosztása egy alak-szenzor szerint (pl. a kazán becsült fűtési gáza).

Évi egy gázleolvasásnál a két leolvasás közti fogyasztás egyenletes elosztása lapos havi képet ad. Ha van egy
szenzor, amely a fogyasztás alakját mutatja (a kazán működési idejéből becsült gáz), a hézagot így osztjuk el:

    napi fogyasztás = alap + s × a szenzor napi változása

ahol az alap (melegvíz, főzés – amit a fűtésbecslés nem lát) egyenletes, és úgy választjuk, hogy a hézag végösszege
pontosan a két leolvasás különbsége legyen. Ha a szenzor többet mutat, mint a valódi fogyasztás, az alap 0, és a
szenzort arányosan lejjebb skálázzuk (s < 1). A leolvasások így változatlanok; csak a köztük lévő alak más.

Csak akkor alkalmazzuk, ha a szenzor a hézag napjainak legalább MIN_LEFEDETTSEG részét lefedi; a le nem fedett
napokra a szenzor-változás 0 (csak az alap jut).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from .kalibracio import tisztit
from .szamlalo import Pont, Szamlalo

MIN_LEFEDETTSEG = Decimal("0.66")
MIN_HEZAG = timedelta(days=3)


def napi_valtozas(sor: list[tuple[datetime, Decimal]]) -> dict[date, Decimal]:
    """A halmozott szenzor-sorozat (nap végi állások) napi változása; a nullázódás nem negatív fogyasztás."""
    tiszta, _ = tisztit(sor)
    ki: dict[date, Decimal] = {}
    for (t0, v0), (t1, v1) in zip(tiszta, tiszta[1:]):
        if t1 - t0 > timedelta(hours=36):
            continue  # adathiány: nem tudjuk, melyik napra esett
        nap = (t1 - timedelta(seconds=1)).date()
        ki[nap] = ki.get(nap, Decimal(0)) + (v1 - v0)
    return ki


def _napok(a: datetime, b: datetime) -> list[tuple[date, datetime, Decimal]]:
    """[a, b) napjai: (nap, a nap vége a hézagon belül, a nap lefedett hányada)."""
    ki = []
    d = a.date()
    while datetime.combine(d, time()) < b:
        eleje = max(datetime.combine(d, time()), a)
        vege = min(datetime.combine(d + timedelta(days=1), time()), b)
        ki.append((d, vege, Decimal((vege - eleje).total_seconds()) / Decimal(86400)))
        d += timedelta(days=1)
    return ki


def profillal(sz: Szamlalo, napi: dict[date, Decimal]) -> tuple[Szamlalo, list[tuple[datetime, datetime]]]:
    """A számláló hosszú hézagait a napi alak szerint kitöltő új számláló, és a kitöltött hézagok."""
    if not napi or len(sz.pontok) < 2:
        return sz, []
    uj: list[Pont] = []
    kitoltott: list[tuple[datetime, datetime]] = []
    for a, b in zip(sz.pontok, sz.pontok[1:]):
        uj.append(a)
        osszes = b.ertek - a.ertek
        if b.ido - a.ido <= MIN_HEZAG or osszes <= 0:
            continue
        napok = _napok(a.ido, b.ido)
        hossz = sum((f for _, _, f in napok), Decimal(0))
        lefedett = sum((f for d, _, f in napok if d in napi), Decimal(0))
        alak = sum((max(napi.get(d, Decimal(0)), Decimal(0)) * f for d, _, f in napok), Decimal(0))
        if lefedett < MIN_LEFEDETTSEG * hossz or alak <= 0:
            continue
        alap, s = ((osszes - alak) / hossz, Decimal(1)) if osszes >= alak else (Decimal(0), osszes / alak)
        ertek = a.ertek
        for d, vege, f in napok[:-1]:  # az utolsó nap vége maga a b pont
            ertek += (alap + s * max(napi.get(d, Decimal(0)), Decimal(0))) * f
            uj.append(Pont(vege, ertek, False))
        kitoltott.append((a.ido, b.ido))
    uj.append(sz.pontok[-1])
    return Szamlalo(uj), kitoltott
