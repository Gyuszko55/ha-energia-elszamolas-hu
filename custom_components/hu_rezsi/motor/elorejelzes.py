"""Időszak-határok és előrejelzés a nyitott időszakra."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from .dijszabas import DijszabasTar
from .elszamolas import szamol
from .szamlalo import NincsAdat, Szamlalo, nap_kezdete
from .tipusok import Fiok, IdoszakEredmeny

ATLAG_NAPOK = 7


def idoszak(nap: date, mod: str = "naptari_honap", kezdo_nap: int = 1) -> tuple[date, date]:
    """A naphoz tartozó [tol, ig) elszámolási időszak."""
    if mod == "negyedev":
        # Naptári negyedév (jan., ápr., júl., okt. 1.) – pl. a negyedévente számlázott hulladékdíj.
        tol = date(nap.year, (nap.month - 1) // 3 * 3 + 1, 1)
        ig = date(tol.year + (tol.month == 10), (tol.month + 2) % 12 + 1, 1)
        return tol, ig
    if mod == "naptari_honap":
        kezdo_nap = 1
    elif mod != "egyedi_nap":
        raise ValueError(f"nem támogatott időszakmód: {mod}")
    kezdo_nap = max(1, min(kezdo_nap, 28))
    tol = nap.replace(day=kezdo_nap) if nap.day >= kezdo_nap else _honap_vissza(nap).replace(day=kezdo_nap)
    ig = (tol.replace(day=1) + timedelta(days=32)).replace(day=kezdo_nap)
    return tol, ig


def _honap_vissza(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def napi_atlag(szamlalo: Szamlalo, most: datetime, napok: int = ATLAG_NAPOK) -> Decimal:
    """Az utolsó `napok` nap napi átlagfogyasztása (ha rövidebb az adatsor, annyiból)."""
    if not szamlalo.pontok:
        return Decimal(0)
    tol = max(most - timedelta(days=napok), szamlalo.pontok[0].ido)
    hossz = Decimal((most - tol).total_seconds()) / Decimal(86400)
    if hossz <= 0:
        return Decimal(0)
    try:
        q, _ = szamlalo.fogyasztas(tol, most)
    except NincsAdat:
        return Decimal(0)
    return max(q, Decimal(0)) / hossz


@dataclass
class NyitottIdoszak:
    eddig: IdoszakEredmeny
    varhato: IdoszakEredmeny
    napi_atlag: list[Decimal]  # csatornánként
    eltelt_nap: Decimal
    hatralevo_nap: Decimal
    hatralevo_keret: Decimal | None
    varhato_keretatlepes: date | None


def nyitott(
    fiok: Fiok,
    tar: DijszabasTar,
    tol: date,
    ig: date,
    szamlalok: list[Szamlalo],
    most: datetime,
    extra_hatarok: set[date] | None = None,
) -> NyitottIdoszak:
    eddig = szamol(fiok, tar, tol, ig, szamlalok, meres_vege=most, extra_hatarok=extra_hatarok)
    vege = nap_kezdete(ig)
    atlagok = [napi_atlag(s, most) for s in szamlalok]
    if most < vege:
        hosszabb = [s.meghosszabbitva(most, n, vege) for s, n in zip(szamlalok, atlagok, strict=True)]
        varhato = szamol(fiok, tar, tol, ig, hosszabb, extra_hatarok=extra_hatarok)
    else:
        varhato = eddig

    eltelt = Decimal(max((min(most, vege) - nap_kezdete(tol)).total_seconds(), 0)) / Decimal(86400)
    hatra = Decimal(max((vege - most).total_seconds(), 0)) / Decimal(86400)

    # Keret: csak a fő (első) csatornára, a keretes szeletekből.
    fo = fiok.csatornak[0].szerep if fiok.csatornak else None
    keretes = [s for s in eddig.szeletek if s.csatorna == fo and s.keret is not None]
    hatralevo = None
    atlepes = None
    if keretes:
        mai = [s for s in keretes if nap_kezdete(s.tol) <= most < nap_kezdete(s.ig)] or keretes[-1:]
        s = mai[0]
        felhasznalt = s.elszamolt if s.elszamolt is not None else s.mennyiseg  # gáznál MJ
        hatralevo = max(s.keret - felhasznalt, Decimal(0))
        n = atlagok[0]
        if s.elszamolt is not None and s.mennyiseg > 0:
            n = n * s.elszamolt / s.mennyiseg  # napi átlag elszámolási egységben
        if s.piaci == 0 and n > 0:
            nap = (most + timedelta(days=float(hatralevo / n))).date()
            if nap < s.ig:
                atlepes = nap
    return NyitottIdoszak(eddig, varhato, atlagok, eltelt, hatra, hatralevo, atlepes)
