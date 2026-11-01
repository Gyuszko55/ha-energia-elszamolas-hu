"""Magyar munkarend: munkaszüneti napok és a rendeletben áthelyezett munka-/pihenőnapok.

A munkaszüneti napokat a Munka törvénykönyve (2012. évi I. tv. 102. § (1)) szerint magunk számoljuk (a húsvét és a
pünkösd a húsvétvasárnapból). Az áthelyezéseket évente külön miniszteri rendelet adja – ezeket NEM a holidays
csomagból vesszük (régebbi változatában a friss év hiányzik vagy eltér), hanem az alábbi táblából, forrással és az
ellenőrzés dátumával. Olyan évre, amely nincs a táblában, a holidays csomag áthelyezéseit használjuk, ha elérhető
(nem ellenőrzött), különben áthelyezés nélkül számolunk.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache

# Év → (rendelet, ellenőrizve, [(ledolgozós szombat = munkanap, áthelyezett pihenőnap)]).
ATHELYEZESEK: dict[int, dict] = {
    2024: {
        "rendelet": "15/2023. (VII. 13.) GFM rendelet a 2024. évi munkaszüneti napok körüli munkarendről",
        "ellenorizve": "2026-10-04",
        "parok": [("2024-08-03", "2024-08-19"), ("2024-12-07", "2024-12-24"), ("2024-12-14", "2024-12-27")],
    },
    2025: {
        "rendelet": "11/2024. (IV. 8.) NGM rendelet a 2025. évi munkaszüneti napok körüli munkarendről",
        "ellenorizve": "2026-10-04",
        "parok": [("2025-05-17", "2025-05-02"), ("2025-10-18", "2025-10-24"), ("2025-12-13", "2025-12-24")],
    },
    2026: {
        "rendelet": "10/2025. (IV. 30.) NGM rendelet a 2026. évi munkaszüneti napok körüli munkarendről",
        "ellenorizve": "2026-10-04",
        "parok": [("2026-01-10", "2026-01-02"), ("2026-08-08", "2026-08-21"), ("2026-12-12", "2026-12-24")],
    },
}
_HELYETTESITVE = re.compile(r"(\d{4})\. (\d{2})\. (\d{2})\.-től helyettesítve")


def husvetvasarnap(ev: int) -> date:
    """Gergely-naptári húsvétvasárnap (anonim gregorián algoritmus)."""
    a, b, c = ev % 19, ev // 100, ev % 100
    d_, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d_ - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    ho = (h + l_ - 7 * m + 114) // 31
    nap = (h + l_ - 7 * m + 114) % 31 + 1
    return date(ev, ho, nap)


def unnepnapok(ev: int) -> frozenset[date]:
    """Munkaszüneti napok (Mt. 102. § (1)): újév, márc. 15., nagypéntek, húsvét, máj. 1., pünkösd, aug. 20.,
    okt. 23., nov. 1., karácsony (dec. 25–26.)."""
    hv = husvetvasarnap(ev)
    fix = [(1, 1), (3, 15), (5, 1), (8, 20), (10, 23), (11, 1), (12, 25), (12, 26)]
    mozgo = [hv - timedelta(days=2), hv, hv + timedelta(days=1), hv + timedelta(days=49), hv + timedelta(days=50)]
    return frozenset([date(ev, h, n) for h, n in fix] + mozgo)


@lru_cache(maxsize=32)
def athelyezesek(ev: int) -> tuple[frozenset[date], frozenset[date], str]:
    """(ledolgozós munkanapok, áthelyezett pihenőnapok, forrás) egy évre."""
    if ev in ATHELYEZESEK:
        x = ATHELYEZESEK[ev]
        return (frozenset(date.fromisoformat(m) for m, _ in x["parok"]),
                frozenset(date.fromisoformat(p) for _, p in x["parok"]), x["rendelet"])
    try:
        import holidays  # noqa: PLC0415 – csak tartaléknak (a HA tartalmazza)
    except ImportError:
        return frozenset(), frozenset(), "nincs adat (áthelyezés nélkül)"
    munka, piheno = set(), set()
    for nap, nev in holidays.country_holidays("HU", years=[ev]).items():
        if nap.year == ev and (m := _HELYETTESITVE.search(nev)):
            piheno.add(nap)
            munka.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return frozenset(munka), frozenset(piheno), "holidays csomag (nem ellenőrzött)"


def munkanap(nap: date) -> bool:
    """Munkanap-e: hétköznap, nem munkaszüneti és nem áthelyezett pihenőnap – vagy ledolgozós szombat."""
    munka, piheno, _ = athelyezesek(nap.year)
    if nap in munka:
        return True
    return nap.weekday() < 5 and nap not in unnepnapok(nap.year) and nap not in piheno
