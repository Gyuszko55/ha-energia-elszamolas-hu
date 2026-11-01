"""Automatikus mérő-korrekció: a HA-forrás (pl. Shelly) és a valódi mérőóra eltérésének kiigazítása.

A Shelly-féle mérők jellemzően néhány százalékkal mást mérnek, mint a szolgáltató mérőórája (áramváltó pontossága,
a mért körön kívüli fogyasztó). A valódi leolvasásokból (számla, diktálás, saját leolvasás) kiszámoljuk az arányt
(mérőóra-növekmény / forrás-növekmény), és a forrás változását ezzel szorozzuk.

- A forrás sorozatát előbb megtisztítjuk: a visszalépés nullázódás (nem negatív fogyasztás), a szokatlanul nagy
  ugrás pedig kézi eltolás-igazítás (pl. a mérőállás-szenzor „eltolás” segédjének állítása), nem fogyasztás.
- Az arány Theil–Sen-becslés (a páronkénti meredekségek mediánja), így egy-egy elírt vagy rossz napra tett
  leolvasás nem viszi el.
- Gyanús leolvasás: minden leolvasást a legközelebbi SZOMSZED_DB másikhoz mérünk (a két állás különbsége ≈ arány ×
  a forrás különbsége). Ha a szomszédok többségével nem egyezik, gyanús. Egyetlen globális egyenes helyett ez a
  helyi összevetés nem jelöl meg egy jó leolvasást csak azért, mert a közelében két rossz van, és az arány lassú
  évszakos ingadozása sem halmozódik fel hosszú időn át.
- Csak hihető arányt alkalmazunk (0,8–1,25): ha a forrás a fogyasztásnak csak egy részét látja (pl. egy klíma a
  H-tarifás körön, ahol más fogyasztó is van), nem korrigálunk, csak jelzünk.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

MIN_PONT = 3
MIN_NAP = 45
MIN_PAR_NAP = 20  # ennél közelebbi leolvasás-párok meredeksége túl zajos (a leolvasás napon belüli időpontja ismeretlen)
ABLAK_NAP = 400
HIHETO = (Decimal("0.8"), Decimal("1.25"))
SZOMSZED_DB = 4
SZOMSZED_TURES = Decimal("0.03")  # az arány bizonytalansága a két leolvasás közti fogyasztás arányában
UGRAS_SZORZO = 4  # napi növekmény > 4 × a szokásos (95. percentilis) napi érték → eltolás-igazítás


@dataclass
class Kalibracio:
    szorzo: Decimal | None  # alkalmazott szorzó (None: nem korrigálunk)
    arany: Decimal | None  # becsült arány (akkor is, ha nem alkalmazzuk)
    pontok: int = 0
    napok: int = 0
    gyanus: list[tuple[date, Decimal]] = field(default_factory=list)  # (leolvasás napja, eltérés az egyenestől)
    ugrasok: list[tuple[date, Decimal]] = field(default_factory=list)  # kiszűrt eltolás-ugrások (nap, mennyiség)
    ok: str = ""  # miért nem korrigálunk


def _median(x: list[Decimal]) -> Decimal:
    s = sorted(x)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def tisztit(sor: list[tuple[datetime, Decimal]]) -> tuple[list[tuple[datetime, Decimal]], list[tuple[date, Decimal]]]:
    """Halmozott, csak a valódi fogyasztással növő sorozat (0-ról indul) és a kiszűrt ugrások."""
    sor = sorted(sor)
    if len(sor) < 2:
        return [(t, Decimal(0)) for t, _ in sor], []
    lepesek = []
    for (t0, v0), (t1, v1) in zip(sor, sor[1:]):
        napok = Decimal(max((t1 - t0).total_seconds(), 1)) / Decimal(86400)
        lepesek.append((t1, v1 - v0, napok))
    rata = sorted(d / n for _, d, n in lepesek if d > 0 and n >= Decimal("0.5"))
    p95 = rata[int(len(rata) * 0.95)] if rata else None
    p50 = rata[len(rata) // 2] if rata else Decimal(0)
    ki, ugrasok, osszeg = [(sor[0][0], Decimal(0))], [], Decimal(0)
    for t1, d, n in lepesek:
        if d < 0:
            d = Decimal(0)  # nullázódás / eltolás csökkentése
        elif p95 and p95 > 0 and d > UGRAS_SZORZO * p95 * max(n, Decimal(1)):
            ugrasok.append((t1.date(), d))
            d = p50 * n  # a szokásos napi fogyasztás marad, a többi eltolás
        osszeg += d
        ki.append((t1, osszeg))
    return ki, ugrasok


def _ertek(sor: list[tuple[datetime, Decimal]], idok: list[datetime], t: datetime) -> Decimal | None:
    i = bisect_left(idok, t)
    if i < len(idok) and idok[i] == t:
        return sor[i][1]
    if i == 0 or i == len(idok):
        return None
    (ta, va), (tb, vb) = sor[i - 1], sor[i]
    if (tb - ta) > timedelta(days=3):
        return None  # hosszú hézagban nem becsülünk
    return va + (vb - va) * Decimal((t - ta).total_seconds()) / Decimal((tb - ta).total_seconds())


def _gyanus(pontok: list[tuple[datetime, Decimal, Decimal]], arany: Decimal) -> list[tuple[date, Decimal]]:
    """A szomszédai többségével nem egyező leolvasások (nap, a szomszédokhoz mért eltérés mediánja)."""
    fogyasztas = pontok[-1][2] - pontok[0][2]
    napi = fogyasztas / max((pontok[-1][0] - pontok[0][0]).days, 1)
    alap = max(fogyasztas * Decimal("0.004"), napi, Decimal(1))  # a leolvasás napon belüli időpontja ismeretlen
    ki = []
    for i, (ti, si, ri) in enumerate(pontok):
        szomszed = sorted((p for j, p in enumerate(pontok) if j != i), key=lambda p: abs(p[0] - ti))[:SZOMSZED_DB]
        if len(szomszed) < MIN_PONT:
            continue
        elteres = [(ri - rj) - arany * (si - sj) for _, sj, rj in szomszed]
        rossz = sum(
            abs(e) > alap + SZOMSZED_TURES * abs(arany * (si - sj)) for e, (_, sj, _) in zip(elteres, szomszed)
        )
        if 2 * rossz > len(szomszed):
            ki.append((ti.date(), _median(elteres).quantize(Decimal(1))))
    return ki


def kalibral(
    leolvasasok: list[tuple[datetime, Decimal]],
    sor: list[tuple[datetime, Decimal]],
    most: datetime,
) -> Kalibracio:
    """leolvasasok: (időpont, a csatorna folytonos számlálójának értéke) a valódi leolvasásoknál;
    sor: a forrás nyers (napi) sorozata. Az utolsó ABLAK_NAP napot nézzük."""
    tiszta, ugrasok = tisztit(sor)
    idok = [t for t, _ in tiszta]
    hatar = most - timedelta(days=ABLAK_NAP)
    pontok = []
    for t, r in sorted(leolvasasok):
        if t < hatar:
            continue
        s = _ertek(tiszta, idok, t)
        if s is not None:
            pontok.append((t, s, r))
    k = Kalibracio(None, None, len(pontok), (pontok[-1][0] - pontok[0][0]).days if pontok else 0, ugrasok=ugrasok)
    if len(pontok) < MIN_PONT or k.napok < MIN_NAP:
        k.ok = f"kevés leolvasás a mérés idejéből ({len(pontok)} db, {k.napok} nap; kell {MIN_PONT} db, {MIN_NAP} nap)"
        return k
    meredek = [
        (r2 - r1) / (s2 - s1)
        for i, (t1, s1, r1) in enumerate(pontok) for (t2, s2, r2) in pontok[i + 1:]
        if (t2 - t1).days >= MIN_PAR_NAP and s2 > s1
    ]
    if not meredek:
        k.ok = "a forrás nem mért fogyasztást a leolvasások között"
        return k
    arany = _median(meredek)
    k.arany = arany.quantize(Decimal("0.001"))
    k.gyanus = _gyanus(pontok, arany)
    if arany <= 0:
        # A mérőóra állása nem változott, miközben a forrás fogyasztást mért (pl. elírt vagy ismételt leolvasás).
        k.ok = "a mérőóra a leolvasások között nem mért fogyasztást, a forrás igen – nem korrigálunk"
        return k
    if not HIHETO[0] <= arany <= HIHETO[1]:
        k.ok = f"a forrás a mérőóra fogyasztásának {float(1 / arany):.0%}-át méri – valószínűleg nem a teljes kört látja"
        return k
    k.szorzo = arany
    return k
