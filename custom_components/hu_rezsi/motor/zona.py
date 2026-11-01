"""A2 kétzónás tarifa: csúcs- és völgyidőszak órára pontosan.

Völgyidőszak (MVM): munkanapokon 22–06 óra, nyári időszámítás idején 23–07 óra; nem munkanapokon (hétvége,
ünnepnap, áthelyezett pihenőnap) egész nap. Az áthelyezett (ledolgozós) szombat munkanap – a munkarend a
motor/munkarend.py táblájából (rendeletenként, forrással), nem a holidays csomagból.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .munkarend import munkanap  # noqa: F401 – a munkarend saját táblából (lásd munkarend.py)

BUDAPEST = ZoneInfo("Europe/Budapest")


def nyari_idoszamitas(ido: datetime) -> bool:
    """Helyi (naiv) időpont nyári időszámítás szerinti-e (Europe/Budapest)."""
    return bool(ido.replace(tzinfo=BUDAPEST).dst())


def volgy_ora(ora_kezdete: datetime) -> bool:
    """A helyi idő szerinti [ora_kezdete, +1 óra) óra völgyidőszak-e."""
    if not munkanap(ora_kezdete.date()):
        return True
    h = ora_kezdete.hour
    if nyari_idoszamitas(ora_kezdete):
        return h >= 23 or h < 7
    return h >= 22 or h < 6


def volgy_orak_aranya(nap: date) -> Decimal:
    """A nap völgyidőszaki óráinak aránya – becslés egyenletes fogyasztásnál (órás adat híján)."""
    kezdet = datetime.combine(nap, datetime.min.time())
    return Decimal(sum(volgy_ora(kezdet + timedelta(hours=i)) for i in range(24))) / Decimal(24)


def napi_zonak(orak: list[tuple[datetime, Decimal]]) -> dict[date, tuple[Decimal, Decimal]]:
    """Órás fogyasztásokból (óra kezdete helyi időben, kWh) naponként (völgy, összes)."""
    out: dict[date, list[Decimal]] = {}
    for ido, q in orak:
        if q <= 0:
            continue
        x = out.setdefault(ido.date(), [Decimal(0), Decimal(0)])
        if volgy_ora(ido):
            x[0] += q
        x[1] += q
    return {k: (v[0], v[1]) for k, v in out.items()}


def volgy_resz(napok: dict[date, tuple[Decimal, Decimal]], tol: date, ig: date) -> tuple[Decimal, bool]:
    """A [tol, ig) szakasz fogyasztásából a völgyidőszaki rész aránya, és hogy becsült-e.

    Órás adatból mérve, ahol van; a hiányzó napokra az órák aránya (egyenletes fogyasztás) – a mért napok
    átlagos napi fogyasztásával súlyozva. Ha egyáltalán nincs adat, csak az órák aránya (becsült)."""
    volgy = ossz = Decimal(0)
    hianyzo: list[date] = []
    d = tol
    while d < ig:
        if d in napok:
            volgy += napok[d][0]
            ossz += napok[d][1]
        else:
            hianyzo.append(d)
        d += timedelta(days=1)
    if not hianyzo:
        return (volgy / ossz if ossz > 0 else volgy_orak_aranya(tol)), False
    mert_napok = (ig - tol).days - len(hianyzo)
    atlag = ossz / mert_napok if mert_napok and ossz > 0 else Decimal(1)
    for h in hianyzo:
        volgy += atlag * volgy_orak_aranya(h)
        ossz += atlag
    return volgy / ossz, True
