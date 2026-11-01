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
from .elszamolas import _hozzarendeles, alapdij_ho, honap_kezdetek, idenyszak, kiegeszito_tetelek, szamol
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
    },
    # Nyaraló (idényes használat): tavasszal/ősszel hétvégék, nyáron teli ház, télen szinte üres – villany és víz.
    "nyaralo": {
        m: Decimal(x)
        for m, x in {
            1: "0.01", 2: "0.01", 3: "0.02", 4: "0.04", 5: "0.06", 6: "0.15",
            7: "0.30", 8: "0.28", 9: "0.07", 10: "0.03", 11: "0.02", 12: "0.01",
        }.items()
    },
    # Napelemes termelés (betáplálás) tipikus hazai havi megoszlása – szaldós előrejelzéshez, ha nincs tavalyi adat.
    "napelem": {
        m: Decimal(x)
        for m, x in {
            1: "0.03", 2: "0.05", 3: "0.08", 4: "0.11", 5: "0.13", 6: "0.13",
            7: "0.14", 8: "0.12", 9: "0.09", 10: "0.06", 11: "0.03", 12: "0.03",
        }.items()
    },
}
ELSZAMOLO_NAPON_BELUL = 20  # a bázis utáni ennyi napon belül kelt számla az előző év elszámolója


def _ft(x: Decimal) -> Decimal:
    return x.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def egy_ev_mulva(d: date) -> date:
    return honap_mulva(d, 12)


def honap_mulva(d: date, honap: int) -> date:
    """Ugyanaz a nap n hónappal később (hónap végén a hónap utolsó napja)."""
    ev, ho = divmod(d.month - 1 + honap, 12)
    ev, ho = d.year + ev, ho + 1
    return d.replace(year=ev, month=ho, day=min(d.day, calendar.monthrange(ev, ho)[1]))


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
    """A nap hónapjának havi fix díja (bruttó): alapdíj (ha abban a hónapban jár) + a kiegészítő havi tételek.
    Idényszakos díjszabásnál (H-tarifa) az alapdíj – ahogy a szamol-ban – a hónap 1-jén érvényes idényé (nyáron az A1-é)."""
    e = tar.felold(_hozzarendeles(fiok, nap), nap, fiok.szolgaltato, fiok.feluliras)
    elso = nap.replace(day=1)
    isz = idenyszak(elso, e.szabalyok.get("idenyszak") or [])
    ae = tar.felold(isz["dijszabas"], elso, fiok.szolgaltato, fiok.feluliras) if isz and isz.get("dijszabas") else e
    havi = alapdij_ho(ae, fiok)
    if (honapok := (e.szabalyok.get("alapdij") or {}).get("honapok")) and nap.month not in honapok:
        havi = Decimal(0)
    if ae.dijak.get("afa") is not None:
        havi = _ft(havi) * (1 + Decimal(ae.dijak["afa"]) / 100)
    for k_dij, k_db, k_afa, _ in kiegeszito_tetelek(e, fiok, {nap.replace(day=1)}):
        havi += k_dij * k_db * (1 + k_afa / 100)
    return havi


def _alap_elsok(fiok: Fiok, tol: date, ig: date) -> list[date]:
    """Az alapdíjas hónapok 1-jei (tol, ig)-ben – a szüneteltetett számlázás hónapjai nélkül."""
    return sorted(d for d in honap_kezdetek(tol, ig) if not fiok.szunetel_nap(d))


def alapdij_osszeg(fiok: Fiok, tar: DijszabasTar, elsok: list[date] | set[date]) -> Decimal:
    """A felsorolt hónapok (1-jeik) havi fix díjainak összege – hónaponként a saját díjjal (idény, csak bizonyos
    hónapokban járó alapdíj), nem a mai hónap díja × darabszám."""
    return sum((havi_alapdij_brutto(fiok, tar, d) for d in elsok), Decimal(0))


def havi_alapdij_honapokra(fiok: Fiok, tar: DijszabasTar, nap: date, db: int) -> Decimal:
    """A nap hónapjától kezdődő db hónap havi fix díjainak összege (fix díjas fiók következő számlája)."""
    elso = nap.replace(day=1)
    return alapdij_osszeg(fiok, tar, [honap_mulva(elso, i) for i in range(db)])


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


def _ev_koltseg(fiok: Fiok, tar: DijszabasTar, szamlalo: Szamlalo, tol: date, ig: date, meres_vege: datetime | None, alapdij: Decimal, tovabbi: list[Szamlalo] | None = None) -> Decimal:
    return _energia(fiok, tar, szamlalo, tol, ig, meres_vege, tovabbi) + alapdij


def _szaldo_ft(fiok: Fiok, tar: DijszabasTar, tol: date, ig: date, vetel: Szamlalo, betap: Szamlalo, meres_vege: datetime | None) -> Decimal:
    """Szaldós napelemes fiók költsége [tol, ig)-ra: a vételezés és a betáplálás éves különbözete szerint
    (motor.napelem.szaldo), alapdíjjal, a betáplálási többlet jóváírásával csökkentve."""
    # Helyi import: a napelem modul ezt a modult importálja.
    from .napelem import szaldo

    return szaldo(fiok, tar, tol, ig, vetel, betap, meres_vege=meres_vege).egyenleg_ft


def _betaplalas_elorejelzes(
    betap: Szamlalo, bazis: date, most: datetime, idopontok: list[datetime], elozo_bazis: date | None
) -> Szamlalo:
    """A betáplálás előrejelzése az év hátralévő részére: a tavalyi éves betáplálás (ennek híján az idei eddigi,
    évesítve) × a napelemes havi profil. idopontok: a vételezés-előrejelzés jövőbeli pontjai."""
    ma = most.date()
    alap_q = None
    if elozo_bazis is not None:
        tavaly = betap.fogyasztas(nap_kezdete(elozo_bazis), nap_kezdete(bazis))[0]
        resz = _profil_resz(elozo_bazis, bazis, "napelem")
        if tavaly > 0:
            alap_q = tavaly / resz if resz and resz < Decimal("0.95") else tavaly
    if alap_q is None:
        eltelt = _profil_resz(bazis, ma, "napelem")
        idei = betap.fogyasztas(nap_kezdete(bazis), most)[0] if ma > bazis else Decimal(0)
        alap_q = idei / eltelt if eltelt > 0 and idei > 0 else Decimal(0)
    most_ertek, _ = betap.ertek(most)
    pontok = [p for p in betap.pontok if p.ido <= most] + [Pont(most, most_ertek, False)]
    ertek, elozo = most_ertek, ma
    for t in sorted(idopontok):
        ertek += alap_q * _profil_resz(elozo, t.date(), "napelem")
        pontok.append(Pont(t, ertek, False))
        elozo = t.date()
    return Szamlalo(pontok)


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
    ciklus_honap: int = 12,
    ev_ig: date | None = None,
    betaplalas: Szamlalo | None = None,
    profil: str | None = None,
) -> EvesEgyenleg:
    """tovabbi: a fiók további csatornáinak (pl. víz-almérő) számlálói, előrejelzés nélkül. ev_ig: tört évnél (pl.
    beköltözés) a szolgáltató következő éves leolvasása – különben a bázis + egy ciklus. betaplalas: szaldós
    napelemes fióknál a betáplálás számlálója – a költség ekkor a vételezés és a betáplálás éves különbözetéből.
    profil: a havi megoszlás kulcsa (HAVI_PROFIL), pl. „nyaralo” – különben a közműé (gáz), ill. egyenletes."""
    bazis = fiok.eves_bazis
    if bazis is None:
        raise ValueError("részszámlás egyenleghez éves bázis (elszámoló leolvasás) kell")
    if ev_ig is None or ev_ig <= bazis:
        ev_ig = honap_mulva(bazis, ciklus_honap)  # az elszámolási ciklus vége (pl. DAKÖV: félév)
    ma = most.date()

    # Befizetések: a bázis utáni első ~20 nap számlája még az előző év elszámolója.
    hatar = bazis + timedelta(days=ELSZAMOLO_NAPON_BELUL)
    ev_szamlai = sorted((d, x) for d, x in reszszamlak if hatar < d <= ma)
    befizetve = sum((x for _, x in ev_szamlai), Decimal(0))
    # Szüneteltetett számlázásnál részszámla sem jön.
    hatralevo_db = 0 if fiok.szunetel_nap(ma) else max(reszszamla_db_ev - len(ev_szamlai), 0)
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
    if betaplalas is not None:
        teny = _szaldo_ft(fiok, tar, bazis, ev_ig, szamlalo, betaplalas, most)
    else:
        alap_eddig = alapdij_osszeg(fiok, tar, _alap_elsok(fiok, bazis, ma + timedelta(days=1)))
        teny = _ev_koltseg(fiok, tar, szamlalo, bazis, ev_ig, most, alap_eddig, tovabbi)

    # Előrejelzés: tavalyi éves fogyasztás × a hátralévő idő profil szerinti része.
    # H-tarifa két regiszterrel: a mennyiséget a két regiszter együtt adja.
    szerepek = [c.szerep for c in fiok.csatornak]
    regiszteres = "h_teli" in szerepek and "h_nyari" in szerepek
    mennyiseg_szamlalok = [szamlalo, *(tovabbi or [])] if regiszteres else [szamlalo]

    def fogy(t1: datetime, t2: datetime) -> Decimal:
        return sum((sz.fogyasztas(t1, t2)[0] for sz in mennyiseg_szamlalok), Decimal(0))

    elozo = None
    if elozo_bazis is not None:
        # Az előző ciklus fogyasztása éves szintre vetítve (a profil éves).
        elozo = fogy(nap_kezdete(elozo_bazis), nap_kezdete(bazis))
        resz = _profil_resz(elozo_bazis, bazis, profil or str(fiok.kozmu))
        if resz and resz < Decimal("0.95"):
            elozo = elozo / resz
    kozmu = profil or str(fiok.kozmu)
    most_ertek, _ = szamlalo.ertek(most)
    pontok = [p for p in szamlalo.pontok if p.ido <= most] + [Pont(most, most_ertek, False)]
    if elozo is not None and elozo > 0:
        alap_q, modszer = elozo, "tavalyi éves fogyasztás × havi profil"
    elif elozo_ev_mennyiseg:
        elozo = Decimal(elozo_ev_mennyiseg)
        alap_q, modszer = elozo, "beállított éves fogyasztás × havi profil"
    else:
        # Idei adatból; ha az év eleje óta kevés (60 napnál rövidebb) az adat, a mérő felszerelése óta
        # (legfeljebb egy évre visszamenőleg) eltelt időből.
        kezd = bazis
        if (ma - bazis).days < 60:
            elso = min((m.beepitve for c in fiok.csatornak for m in c.merok), default=bazis)
            kezd = max(elso, ma - timedelta(days=365))
        eltelt = _profil_resz(kezd, ma, kozmu) or Decimal(1)
        alap_q = fogy(nap_kezdete(kezd), most) / eltelt
        modszer = "az idei eddigi fogyasztásból, havi profillal" if kezd == bazis else f"a {kezd.isoformat()} óta mért fogyasztásból, havi profillal"
    bazis_ertek = fogy(nap_kezdete(bazis), most)
    ertek, elozo_nap = most_ertek, ma
    for d in sorted(x for x in honap_kezdetek(ma, ev_ig) | {ev_ig} if x > ma):
        ertek += alap_q * _profil_resz(elozo_nap, d, kozmu)
        pontok.append(Pont(nap_kezdete(d), ertek, False))
        elozo_nap = d
    elorejelzett = Szamlalo(pontok)
    varhato_q = bazis_ertek + (ertek - most_ertek)

    tovabbi_elore: list[Szamlalo] = []
    if regiszteres:
        # A becsült napi mennyiség naptár szerint a téli vagy a nyári regiszterre kerül.
        from .elorejelzes import _h_regiszter_elorejelzes

        elorejelzett, *tovabbi_elore = _h_regiszter_elorejelzes(
            fiok, tar, [szamlalo, *(tovabbi or [])], szerepek, alap_q / 365, most, nap_kezdete(ev_ig)
        )
    else:
        # A további csatornák (víz-almérő) előrejelzése a főmérőhöz mért idei arányukkal.
        fo_eddig = most_ertek - szamlalo.ertek(nap_kezdete(bazis))[0]
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
    if betaplalas is not None:
        betap_elore = _betaplalas_elorejelzes(betaplalas, bazis, most, [p.ido for p in pontok if p.ido > most], elozo_bazis)
        varhato = _szaldo_ft(fiok, tar, bazis, ev_ig, elorejelzett, betap_elore, None)
    else:
        varhato = _ev_koltseg(fiok, tar, elorejelzett, bazis, ev_ig, None, alapdij_osszeg(fiok, tar, _alap_elsok(fiok, bazis, ev_ig + timedelta(days=1))), tovabbi_elore)

    visszameres = None
    if elozo_bazis is not None:
        elozo_fiok = dataclasses.replace(fiok, eves_bazis=elozo_bazis)
        if betaplalas is not None:
            szamitott = _szaldo_ft(elozo_fiok, tar, elozo_bazis, bazis, szamlalo, betaplalas, None)
        else:
            szamitott = _ev_koltseg(
                elozo_fiok, tar, szamlalo, elozo_bazis, bazis, None, alapdij_osszeg(elozo_fiok, tar, _alap_elsok(elozo_fiok, elozo_bazis, bazis + timedelta(days=1))), tovabbi
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
    betaplalas: Szamlalo | None = None,
) -> VarhatoElszamolas:
    """Ha ma lenne az elszámolás: a [tol, most] fogyasztás költsége mínusz az azóta kiállított számlák.
    betaplalas: szaldós napelemes fióknál a betáplálás számlálója (a nettó vételezés díja, többlet-jóváírással)."""
    ma = most.date()
    if betaplalas is not None:
        tenyleges = _szaldo_ft(fiok, tar, tol, honap_mulva(tol, 12), szamlalo, betaplalas, most)
    else:
        energia = _energia(fiok, tar, szamlalo, tol, ma + timedelta(days=1), most, tovabbi)
        tenyleges = energia + alapdij_osszeg(fiok, tar, _alap_elsok(fiok, tol, ma + timedelta(days=1)))
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


def atalany_havi(
    fiok: Fiok, tar: DijszabasTar, tol: date, ig: date, havi_mennyiseg: Decimal, almero_arany: Decimal = Decimal(0)
) -> tuple[Decimal, Decimal, Decimal]:
    """Mennyiségben megadott átalány (pl. 293 kWh/hó) a [tol, ig) időszakra: (napi mennyiség, időszak
    mennyisége, fizetendő Ft). A napi mennyiség = havi × 12 / 365; az időszak mennyiségét a fiók díjszabása
    árazza (keret, alapdíj). H-tarifa két regiszterénél a napi mennyiség naptár szerint a téli vagy a nyári
    regiszterre kerül (okt. 15. / ápr. 15.)."""
    from .elszamolas import _hozzarendeles, idenyszak

    napi = Decimal(havi_mennyiseg) * 12 / 365
    szerepek = [c.szerep for c in fiok.csatornak]
    idenyek = tar.felold(_hozzarendeles(fiok, tol), tol, fiok.szolgaltato, fiok.feluliras).szabalyok.get("idenyszak") or []
    ertek = {sz: Decimal(0) for sz in szerepek}
    # Az éves keret (pl. gáz-részszámla) az éves bázistól halmoz: a számláló onnan induljon (addig 0 – becslés).
    kezd = min(tol, fiok.eves_bazis) if fiok.eves_bazis else tol
    pontok = {sz: [Pont(nap_kezdete(kezd), Decimal(0), True)] + ([Pont(nap_kezdete(tol), Decimal(0), True)] if kezd < tol else [])
              for sz in szerepek}
    d = tol
    while d < ig:
        if "h_teli" in szerepek:
            cel = f"h_{(idenyszak(d, idenyek) or {}).get('nev')}"
        else:
            cel = szerepek[0]  # az almérő nem kap átalányt (a főmérő része)
        if cel in ertek:
            ertek[cel] += napi
        if "almero" in ertek:
            ertek["almero"] += napi * almero_arany  # a locsolóvíz része: a csatornadíjból levonódik
        d = d + timedelta(days=1)
        for sz in szerepek:
            pontok[sz].append(Pont(nap_kezdete(d), ertek[sz], True))
    r = szamol(fiok, tar, tol, ig, [Szamlalo(pontok[sz]) for sz in szerepek])
    return napi, sum((v for k, v in ertek.items() if k != "almero"), Decimal(0)), r.osszesen_ft
