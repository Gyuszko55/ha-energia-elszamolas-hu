"""Hónap közben (pl. ma) beállított fiók: a mérő kezdőnapja a nyitott időszak kezdete utáni."""

from datetime import date, datetime
from decimal import Decimal as D

from tests.motor.test_motor import egyenes, fiok, tar  # noqa: F401 – fixture
from motor.elorejelzes import nyitott


def test_honap_kozbeni_kezdonap_nem_hiba(tar):
    sz = egyenes(date(2026, 10, 2), date(2026, 10, 3), "10")
    ny = nyitott(fiok("villany/a1"), tar, date(2026, 10, 1), date(2026, 11, 1), [sz], datetime(2026, 10, 3, 12))
    assert ny.eddig.mennyiseg == D(10)


def test_kezdonap_elotti_idoszak_tovabbra_is_nincs_adat(tar):
    import pytest
    from motor.elszamolas import szamol
    from motor.szamlalo import NincsAdat

    sz = egyenes(date(2026, 10, 2), date(2026, 10, 3), "10")
    with pytest.raises(NincsAdat):
        szamol(fiok("villany/a1"), tar, date(2026, 9, 1), date(2026, 10, 1), [sz])
