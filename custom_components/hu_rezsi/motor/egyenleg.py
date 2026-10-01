"""Részszámlás (átalány) fiók: befizetések kontra tényleges költség, várható éves egyenleg.

Az elszámolási év az éves bázistól (utolsó elszámoló leolvasás) egy évig tart. A tényleges költséget a mért
fogyasztásból számoljuk, a hátralévő részt a tavalyi éves fogyasztás és egy havi profil alapján jelezzük előre
(docs/terv/03_ELSZAMOLO_MOTOR.md, „Részszámlás fiók”).
"""

from __future__ import annotations

import calendar
import dataclasses
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .dijszabas import DijszabasTar
from .elszamolas import _hozzarendeles, honap_kezdetek, szamol
from .szamlalo import Pont, Szamlalo, nap_kezdete
from .tipusok import Fiok

# Lakossági gázfűtés tipikus havi megoszlása (összege 1). Más közműnél egyenletes (napok szerint).
HAVI_PROFIL: dict[str, dict[int, Decimal]] = {
    "gaz": {
        m: Decimal(x)
        for m, x in {
            1: "0.18", 2: "0.15", 3: "0.12", 4: "0.07", 5: "0.03", 6: "0.02",
            7: "0.02", 8: "0.02", 9: "0.03", 10: "0.07", 11: "0.12", 12: "0.17",
        }.items()
    }
}
ELSZAMOLO_NAPON_BELUL = 20  # a bázis utáni ennyi napon belül kelt számla az előző év elszámolója


def _ft(x: Decimal) -> Decimal:
    return x.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def egy_ev_mulva(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # febr. 29.
        return d.replace(year=d.year + 1, day=28)


def _profil_resz(tol: date, ig: date, kozmu: str) -> Decimal:
    """Az éves fogyasztás hányad része esik a [tol, ig) szakaszra."""
    profil = HAVI_PROFIL.get(kozmu)
    osszeg = Decimal(0)
    d = tol
    while d < ig:
        honap_napjai = calendar.monthrange(d.year, d.month)[1]
        vege = min((d.replace(day=1) + timedelta(days=32)).replace(day=1), ig)
        napok = Decimal((vege - d).days)
        osszeg += (profil[d.month] * napok / honap_napjai) if profil else napok / Decimal(365)
        d = vege
    return osszeg


def havi_alapdij_brutto(fiok: Fiok, tar: DijszabasTar, nap: date) -> Decimal:
    e = tar.felold(_hozzarendeles(fiok, nap), nap, fiok.szolgaltato, fiok.feluliras)
    havi = e.dijak.get("alapdij_ho") or Decimal(0)
    if e.dijak.get("afa") is not None:
        return _ft(havi) * (1 + Decimal(e.dijak["afa"]) / 100)
    return havi


def _energia(fiok: Fiok, tar: DijszabasTar, szamlalo: Szamlalo, tol: date, ig: date, meres_vege: datetime | None, tovabbi: list[Szamlalo] | None = None) -> Decimal:
    """Energia-(és csatorna)díj [tol, ig)-ra, havi darabokban; alapdíj nélkül (azt havonta külön számoljuk)."""
    hatarok = sorted({tol, ig} | honap_kezdetek(tol, ig))
    osszeg = Decimal(0)
    for a, b in zip(hatarok, hatarok[1:]):
        if meres_vege is not None and nap_kezdete(a) >= meres_vege:
            break
        osszeg += sum((s.energia_ft for s in szamol(fiok, tar, a, b, [szamlalo, *(tovabbi or [])], meres_vege=meres_vege).szeletek), Decimal(0))
    return osszeg


@dataclass
class EvesEgyenleg:
    ev_tol: date
    ev_ig: date
    befizetve: Decimal
    befizetett_db: int
    hatralevo_reszszamla: Decimal
    hatralevo_db: int
    teny_eddig: Decimal
    varhato_eves: Decimal
    varhato_fogyasztas: Decimal
    elozo_ev_fogyasztas: Decimal | None
    modszer: str
    elozo_ev: dict | None = None  # visszamérés: {"fizetve": ..., "szamitott": ...}
    megbizhato: bool = True

    @property
    def varhato_egyenleg(self) -> Decimal:
        """> 0: várható visszatérítés, < 0: várható ráfizetés."""
        return _ft(self.befizetve + self.hatralevo_reszszamla - self.varhato_eves)


def _ev_koltseg(fiok: Fiok, tar: DijszabasTar, szamlalo: Szamlalo, tol: date, ig: date, meres_vege: datetime | None, havi_alap: Decimal, alap_db: int, tovabbi: list[Szamlalo] | None = None) -> Decimal:
    return _energia(fiok, tar, szamlalo, tol, ig, meres_vege, tovabbi) + havi_alap * alap_db


def eves_egyenleg(
    fiok: Fiok,
    tar: DijszabasTar,
    szamlalo: Szamlalo,
    most: datetime,
    reszszamlak: list[tuple[date, Decimal]],
    reszszamla_db_ev: int = 11,
    elozo_bazis: date | None = None,
    tovabbi: list[Szamlalo] | None = None,
    reszszamla_osszeg: Decimal | None = None,
    elozo_ev_mennyiseg: Decimal | None = None,
) -> EvesEgyenleg:
    """tovabbi: a fiók további csatornáinak (pl. víz-almérő) számlálói, előrejelzés nélkül."""
    bazis = fiok.eves_bazis
    if bazis is None:
        raise ValueError("részszámlás egyenleghez éves bázis (elszámoló leolvasás) kell")
    ev_ig = egy_ev_mulva(bazis)
    ma = most.date()
    havi_alap = havi_alapdij_brutto(fiok, tar, ma)

    # Befizetések: a bázis utáni első ~20 nap számlája még az előző év elszámolója.
    hatar = bazis + timedelta(days=ELSZAMOLO_NAPON_BELUL)
    ev_szamlai = sorted((d, x) for d, x in reszszamlak if hatar < d <= ma)
    befizetve = sum((x for _, x in ev_szamlai), Decimal(0))
    hatralevo_db = max(reszszamla_db_ev - len(ev_szamlai), 0)
    # A hátralévő részszámlák összege: beállított összeg > az idei utolsó > a tavalyi év utolsó részszámlája
    # (a bázis előtti; a bázis utáni első napok elszámoló számlája nem részszámla).
    tavalyiak = sorted((d, x) for d, x in reszszamlak if d <= bazis)
    if reszszamla_osszeg:
        utolso = Decimal(reszszamla_osszeg)
    elif ev_szamlai:
        utolso = ev_szamlai[-1][1]
    else:
        utolso = tavalyiak[-1][1] if tavalyiak else Decimal(0)

    # Tényleges eddig: mért fogyasztás + az eddig esedékes havi alapdíjak.
    alap_eddig = len([d for d in honap_kezdetek(bazis, ma + timedelta(days=1))])
    teny = _ev_koltseg(fiok, tar, szamlalo, bazis, ev_ig, most, havi_alap, alap_eddig, tovabbi)

    # Előrejelzés: tavalyi éves fogyasztás × a hátralévő idő profil szerinti része.
    elozo = None
    if elozo_bazis is not None:
        elozo, _ = szamlalo.fogyasztas(nap_kezdete(elozo_bazis), nap_kezdete(bazis))
    kozmu = str(fiok.kozmu)
    most_ertek, _ = szamlalo.ertek(most)
    pontok = [p for p in szamlalo.pontok if p.ido <= most] + [Pont(most, most_ertek, False)]
    if elozo is not None and elozo > 0:
        alap_q, modszer = elozo, "tavalyi éves fogyasztás × havi profil"
    elif elozo_ev_mennyiseg:
        elozo = Decimal(elozo_ev_mennyiseg)
        alap_q, modszer = elozo, "beállított éves fogyasztás × havi profil"
    else:
        eltelt = _profil_resz(bazis, ma, kozmu) or Decimal(1)
        alap_q = (most_ertek - szamlalo.ertek(nap_kezdete(bazis))[0]) / eltelt
        modszer = "az idei eddigi fogyasztásból, havi profillal"
    ertek, elozo_nap = most_ertek, ma
    for d in sorted(x for x in honap_kezdetek(ma, ev_ig) | {ev_ig} if x > ma):
        ertek += alap_q * _profil_resz(elozo_nap, d, kozmu)
        pontok.append(Pont(nap_kezdete(d), ertek, False))
        elozo_nap = d
    elorejelzett = Szamlalo(pontok)

    # A további csatornák (víz-almérő) előrejelzése a főmérőhöz mért idei arányukkal.
    fo_eddig = most_ertek - szamlalo.ertek(nap_kezdete(bazis))[0]
    tovabbi_elore: list[Szamlalo] = []
    for t in tovabbi or []:
        t_most, _ = t.ertek(most)
        arany = (t_most - t.ertek(nap_kezdete(bazis))[0]) / fo_eddig if fo_eddig > 0 else Decimal(0)
        if fo_eddig <= 0 and elozo_bazis is not None and elozo:
            # Még nincs idei adat: a tavalyi év aránya (pl. locsolás a főmérő fogyasztásához képest).
            t_tavaly, _ = t.fogyasztas(nap_kezdete(elozo_bazis), nap_kezdete(bazis))
            arany = max(t_tavaly, Decimal(0)) / elozo
        t_pontok = [p for p in t.pontok if p.ido <= most] + [Pont(most, t_most, False)]
        for p in pontok:
            if p.ido > most:
                t_pontok.append(Pont(p.ido, t_most + (p.ertek - most_ertek) * arany, False))
        tovabbi_elore.append(Szamlalo(t_pontok))
    varhato_q = ertek - szamlalo.ertek(nap_kezdete(bazis))[0]
    varhato = _ev_koltseg(fiok, tar, elorejelzett, bazis, ev_ig, None, havi_alap, len(honap_kezdetek(bazis, ev_ig + timedelta(days=1))), tovabbi_elore)

    visszameres = None
    if elozo_bazis is not None:
        elozo_fiok = dataclasses.replace(fiok, eves_bazis=elozo_bazis)
        szamitott = _ev_koltseg(
            elozo_fiok, tar, szamlalo, elozo_bazis, bazis, None, havi_alap, len(honap_kezdetek(elozo_bazis, bazis + timedelta(days=1))), tovabbi
        )
        e_hatar = elozo_bazis + timedelta(days=ELSZAMOLO_NAPON_BELUL)
        fizetve = sum((x for d, x in reszszamlak if e_hatar < d <= hatar), Decimal(0))
        visszameres = {"tol": elozo_bazis, "ig": bazis, "fizetve": _ft(fizetve), "szamitott": _ft(szamitott)}

    return EvesEgyenleg(
        ev_tol=bazis,
        ev_ig=ev_ig,
        befizetve=_ft(befizetve),
        befizetett_db=len(ev_szamlai),
        hatralevo_reszszamla=_ft(utolso * hatralevo_db),
        hatralevo_db=hatralevo_db,
        teny_eddig=_ft(teny),
        varhato_eves=_ft(varhato),
        varhato_fogyasztas=varhato_q,
        elozo_ev_fogyasztas=elozo,
        modszer=modszer,
        elozo_ev=visszameres,
        megbizhato=elozo is not None and elozo > 0 and utolso > 0,
    )


@dataclass
class VarhatoElszamolas:
    tol: date  # az utolsó valódi elszámolás vége
    tenyleges: Decimal  # a mért fogyasztás költsége azóta, alapdíjjal
    befizetve: Decimal  # az azóta kiállított számlák összege
    szamlak_db: int
    mennyiseg: Decimal
    becsult: bool  # a mostani állás becsült (pl. a legutóbbi leolvasás óta csak szenzor vagy semmi)

    @property
    def egyenleg(self) -> Decimal:
        """> 0: várható visszatérítés, < 0: várható ráfizetés."""
        return _ft(self.befizetve - self.tenyleges)


def varhato_elszamolas(
    fiok: Fiok,
    tar: DijszabasTar,
    szamlalo: Szamlalo,
    most: datetime,
    tol: date,
    befizetesek: list[tuple[date, Decimal]],
    tovabbi: list[Szamlalo] | None = None,
) -> VarhatoElszamolas:
    """Ha ma lenne az elszámolás: a [tol, most] fogyasztás költsége mínusz az azóta kiállított számlák."""
    ma = most.date()
    energia = _energia(fiok, tar, szamlalo, tol, ma + timedelta(days=1), most, tovabbi)
    alap_db = len(honap_kezdetek(tol, ma + timedelta(days=1)))
    tenyleges = energia + havi_alapdij_brutto(fiok, tar, ma) * alap_db
    q, becsult = szamlalo.fogyasztas(nap_kezdete(tol), most)
    for csat, t in zip(fiok.csatornak[1:], tovabbi or [], strict=False):
        if csat.szerep != "almero":  # pl. a H-tarifa nyári regisztere; az almérő a főmérő része
            q += t.fogyasztas(nap_kezdete(tol), most)[0]
    sajat = [(d, x) for d, x in befizetesek if d > tol]
    return VarhatoElszamolas(
        tol=tol,
        tenyleges=_ft(tenyleges),
        befizetve=_ft(sum((x for _, x in sajat), Decimal(0))),
        szamlak_db=len(sajat),
        mennyiseg=max(q, Decimal(0)),
        becsult=becsult,
    )
