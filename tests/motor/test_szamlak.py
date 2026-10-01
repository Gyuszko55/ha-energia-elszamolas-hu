"""Számlatesztek: valódi, anonimizált MVM Next számlák. A motornak a számla végösszegét kell kihoznia.

Csak mennyiségek, dátumok és összegek – név, cím, azonosító nincs benne.
"""

from datetime import date, datetime
from decimal import Decimal as D

from tests.conftest import DIJSZABASOK
from motor.dijszabas import DijszabasTar
from motor.elszamolas import szamol
from motor.szamlalo import Pont, Szamlalo
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu, Leolvasas, Mero

TAR = DijszabasTar.mappabol(DIJSZABASOK)


def test_villany_a1_reszszamla_2026_06():
    """Villany 2. részszámla, 2026.05.14–06.08 (26 nap), 19 120 → 19 413 kWh (293 kWh).

    Számla: 180 kWh kedvezményes + 113 kWh piaci; energiadíj + rendszerhasználati díj bruttó 5 763 + 8 707,
    elosztói alapdíj 154 (1 db), végösszeg 14 624 Ft. Rezsicsökkentés nélkül: 20 693 Ft.
    """
    fiok = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/a1", date(2024, 1, 1))], [Csatorna()])
    tol, ig = date(2026, 5, 14), date(2026, 6, 9)
    s = Szamlalo([Pont(datetime(2026, 5, 14), D(19120), True), Pont(datetime(2026, 6, 9), D(19413), True)])
    r = szamol(fiok, TAR, tol, ig, [s])
    sz = r.szeletek[0]
    assert (sz.keret, sz.kedvezmenyes, sz.piaci) == (D(180), D(180), D(113))
    assert r.osszesen_ft == D(14624)
    assert (r.energia_ft, r.alapdij_ft) == (D(14470), D(154))  # (945 + 3 593 + 6 856) × 1,27; 121 × 1,27
    # Ellenpróba a számla „rezsicsökkentett díj nélkül” sorával (minden kWh piaci áron); a szolgáltató
    # kerekítési módját itt nem ismerjük, ezért ±1 Ft.
    assert abs((D(293) * D("70.104") + D("153.035")).quantize(D(1)) - D(20693)) <= 1


def test_gaz_reszszamla_2026_08():
    """Gáz 1. részszámla, 2026.07.15–08.13, 103 m³ (58 + 45), korrekció 1,0, fűtőérték 34,61 MJ/m³.

    Számla: 2 007 + 1 557 MJ × 2,256 Ft/MJ nettó (4 528 + 3 513), alapdíj 766 nettó, ÁFA 27% → 11 185 Ft.
    A részszámla mennyisége itt becsült (a gázóra ennyit nem mért), a teszt a számla mennyiségét veszi át.
    """
    fiok = Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/lakossagi", date(2024, 1, 1))], [Csatorna()],
                eves_bazis=date(2026, 7, 14), futoertekek={"2026-07": D("34.61"), "2026-08": D("34.61")})
    s = Szamlalo([Pont(datetime(2026, 7, 14), D(8668), True), Pont(datetime(2026, 7, 15), D(8668), True),
                  Pont(datetime(2026, 8, 1), D(8726), True), Pont(datetime(2026, 8, 14), D(8771), True)])
    r = szamol(fiok, TAR, date(2026, 7, 15), date(2026, 8, 14), [s])
    assert [sz.elszamolt for sz in r.szeletek] == [D(2007), D(1557)]
    assert all(sz.piaci == 0 and not sz.becsult for sz in r.szeletek)
    assert r.energia_ft == D(10212) and r.alapdij_ft == D(973)
    assert r.osszesen_ft == D(11185)


def _viz_fiok(levonas: bool):
    return Fiok(Kozmu.VIZ, "dakov", [DijszabasHozzarendeles("viz/dakov", date(2024, 1, 1))],
                [Csatorna(szerep="fo"), Csatorna(szerep="almero", csatornadij_aktiv=False, levonas_fobol=levonas)])


def _alapdij(honap: int) -> D:
    """A DAKÖV-számla alapdíj-tételei: 2 × 177,21 Ft/hó nettó × hónapok, fillérre (a számla saját ütemezése szerint)."""
    return (D("354.42") * honap * D("1.27")).quantize(D("0.01"))


def test_viz_dakov_2026_03():
    """DAKÖV víz 1. részszámla, 2026.01.24–03.02 (becsült): fővízmérő 741 → 749 (8 m³), locsolási mérő 89 → 92 (3 m³).

    Ezen a számlán még nincs almérő-levonás: ivóvíz 11 m³, csatorna 8 m³, alapdíj 1 hónap → 8 013 Ft.
    """
    tol, ig = date(2026, 1, 24), date(2026, 3, 3)
    fo = Szamlalo([Pont(datetime(2026, 1, 24), D(741), True), Pont(datetime(2026, 3, 3), D(749), True)])
    almero = Szamlalo([Pont(datetime(2026, 1, 24), D(89), True), Pont(datetime(2026, 3, 3), D(92), True)])
    r = szamol(_viz_fiok(levonas=False), TAR, tol, ig, [fo, almero])
    energia = sum(s.energia_ft for s in r.szeletek)
    assert sum(s.csatorna_ft for s in r.szeletek) == D("3798.01")
    assert (energia + _alapdij(1)).quantize(D(1)) == D(8013)


def test_viz_dakov_2026_07_almero_levonas_es_merocsere():
    """DAKÖV víz, 2026.05.31–07.15: fővízmérő 793 → 812 (19 m³), aztán mérőcsere (új óra 0-ról),
    locsolási ALMÉRŐ 106 → 117 (11 m³), levonva a főmérő csatornadíjából.

    Számla: ivóvíz 19 m³ (5 120,88 nettó), csatorna 19 − 11 = 8 m³ (7 102,58 − 4 112,02), alapdíj 2 hónap → 11 202 Ft.
    """
    fiok = _viz_fiok(levonas=True)
    fo = Szamlalo.csatornabol(Csatorna(merok=[
        Mero("1106871", date(2020, 1, 1), D(0), kiszerelve=date(2026, 7, 15), zaro_allas=D(812),
             leolvasasok=[Leolvasas(date(2026, 5, 31), D(793))]),
        Mero("234626HB", date(2026, 7, 15), D(0)),
    ]))
    almero = Szamlalo([Pont(datetime(2026, 5, 31), D(106), True), Pont(datetime(2026, 7, 15), D(117), True)])
    r = szamol(fiok, TAR, date(2026, 5, 31), date(2026, 7, 15), [fo, almero])
    fo_sz = [s for s in r.szeletek if s.csatorna == "fo"]
    al_sz = [s for s in r.szeletek if s.csatorna == "almero"]
    assert sum(s.mennyiseg for s in fo_sz) == D(19) and sum(s.mennyiseg for s in al_sz) == D(11)
    assert sum(s.csatorna_ft for s in fo_sz) == D("9020.28")
    assert sum(s.csatorna_ft for s in al_sz) == D("-5222.27")
    energia = sum(s.energia_ft for s in r.szeletek)
    assert (energia + _alapdij(2)).quantize(D(1)) == D(11202)
