"""Az indítókártya mérőállása: a számláló (összesített fogyasztás) → a beépített mérő kijelzett állása mérőcsere után is."""
from datetime import date, datetime
from decimal import Decimal

from motor.szamlalo import Szamlalo, kijelzett_allas
from motor.tipusok import Csatorna, Leolvasas, LeolvasasTipus, Mero


def test_mero_csere_utan_a_kijelzett_allas():
    regi = Mero("A", date(2025, 1, 1), Decimal(18000), kiszerelve=date(2026, 1, 1), zaro_allas=Decimal(18540))
    uj = Mero("B", date(2026, 1, 1), Decimal(0), leolvasasok=[Leolvasas(date(2026, 10, 5), Decimal(5738), LeolvasasTipus.KEZI)])
    cs = Csatorna(merok=[regi, uj])
    sz = Szamlalo.csatornabol(cs)
    ertek, _ = sz.ertek(datetime(2026, 10, 5))
    assert ertek == Decimal(540 + 5738)                    # a két mérő összesített fogyasztása
    assert kijelzett_allas(cs, ertek) == Decimal(5738)     # az új óra kijelzése


def test_egy_mero_kezdoallassal():
    m = Mero("A", date(2025, 1, 1), Decimal(24000), leolvasasok=[Leolvasas(date(2026, 10, 5), Decimal(24278), LeolvasasTipus.KEZI)])
    cs = Csatorna(merok=[m])
    ertek, _ = Szamlalo.csatornabol(cs).ertek(datetime(2026, 10, 5))
    assert kijelzett_allas(cs, ertek) == Decimal(24278)


def test_idoponttal_rogzitett_leolvasas():
    """Este (20:55) leolvasott állás: a számlálóban ott áll, nem a nap elején – a nap eleje óta mért fogyasztás nem adódik
    hozzá még egyszer."""
    from datetime import time

    m = Mero("A", date(2025, 1, 1), Decimal(0), leolvasasok=[
        Leolvasas(date(2026, 10, 8), Decimal(100)),
        Leolvasas(date(2026, 10, 9), Decimal(110), ido=time(20, 55))])
    cs = Csatorna(merok=[m])
    sorozat = [(datetime(2026, 10, 9, 0, 0), Decimal(1000)), (datetime(2026, 10, 9, 20, 55), Decimal(1009)),
               (datetime(2026, 10, 9, 21, 30), Decimal(1009.5))]
    sz = Szamlalo.csatornabol(cs, sorozat)
    assert sz.ertek(datetime(2026, 10, 9, 20, 55))[0] == Decimal(110)
    assert sz.ertek(datetime(2026, 10, 9, 21, 30))[0] == Decimal("110.5")
