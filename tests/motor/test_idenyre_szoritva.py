"""H-regiszter: két leolvasás között a növekmény csak a regiszter idénye napjaira oszlik (Kertes ház 2026-02-03 – 08-08)."""
from datetime import date, datetime
from decimal import Decimal

from motor.szamlalo import Pont, Szamlalo, idenyre_szoritva


def _teli(nap: date) -> bool:
    return (nap.month, nap.day) >= (10, 15) or (nap.month, nap.day) < (4, 15)


def test_nyari_regiszter_telen_nem_no():
    sz = Szamlalo([Pont(datetime(2026, 2, 3), Decimal(0), True), Pont(datetime(2026, 8, 8), Decimal(349), True)])
    uj = idenyre_szoritva(sz, lambda n: not _teli(n))
    assert uj.fogyasztas(datetime(2026, 2, 3), datetime(2026, 4, 15))[0] == 0
    assert uj.fogyasztas(datetime(2026, 4, 15), datetime(2026, 8, 8))[0] == 349


def test_teli_regiszter_nyaron_nem_no():
    sz = Szamlalo([Pont(datetime(2026, 2, 3), Decimal(0), True), Pont(datetime(2026, 8, 8), Decimal(474), True)])
    uj = idenyre_szoritva(sz, _teli)
    assert uj.fogyasztas(datetime(2026, 2, 3), datetime(2026, 4, 15))[0] == 474
    assert uj.fogyasztas(datetime(2026, 4, 15), datetime(2026, 8, 8))[0] == 0


def test_idenyen_beluli_hezag_valtozatlan():
    sz = Szamlalo([Pont(datetime(2026, 5, 1), Decimal(0), True), Pont(datetime(2026, 6, 1), Decimal(31), True)])
    assert idenyre_szoritva(sz, lambda n: not _teli(n)) is sz
