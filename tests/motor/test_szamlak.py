"""Számlatesztek: valódi, anonimizált MVM Next számlák. A motornak a számla végösszegét kell kihoznia.

Csak mennyiségek, dátumok és összegek – név, cím, azonosító nincs benne.
"""

from datetime import date, datetime
from decimal import Decimal as D

from tests.conftest import DIJSZABASOK
from motor.dijszabas import DijszabasTar
from motor.elszamolas import szamol
from motor.szamlalo import Pont, Szamlalo
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu

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


def test_viz_dakov_2026_03():
    """DAKÖV víz 1. részszámla, 2026.01.24–03.02, két mérő (becsült fogyasztás):

    fővízmérő 741 → 749 (8 m³: ivóvíz + szennyvíz), locsolási mérő 89 → 92 (3 m³: csak ivóvíz).
    Tételek (bruttó): 1 026,87 + 2 738,32 + 225,06 + 3 798,01 + 225,06 = 8 013,32 → 8 013 Ft.
    """
    fiok = Fiok(Kozmu.VIZ, "dakov", [DijszabasHozzarendeles("viz/dakov", date(2024, 1, 1))],
                [Csatorna(szerep="fo"), Csatorna(szerep="locsolo", csatornadij_aktiv=False)])
    tol, ig = date(2026, 1, 24), date(2026, 3, 3)
    fo = Szamlalo([Pont(datetime(2026, 1, 24), D(741), True), Pont(datetime(2026, 3, 3), D(749), True)])
    locsolo = Szamlalo([Pont(datetime(2026, 1, 24), D(89), True), Pont(datetime(2026, 3, 3), D(92), True)])
    r = szamol(fiok, TAR, tol, ig, [fo, locsolo])
    fo_sz = [s for s in r.szeletek if s.csatorna == "fo"]
    assert sum(s.csatorna_ft for s in fo_sz) == D("3798.01")
    assert r.osszesen_ft == D(8013)
    assert sum(s.alapdij_ft for s in r.szeletek) == D("450.11")  # 354,42 × 1,27 (a számlán 2 × 225,06)
