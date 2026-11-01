"""Szenzor nélküli (csak leolvasásos) fiók előrejelzése az utolsó leolvasás után."""

from datetime import date, datetime
from decimal import Decimal as D

from tests.motor.test_motor import fiok, tar  # noqa: F401 – fixture
from motor.elorejelzes import napi_atlag, nyitott
from motor.szamlalo import Pont, Szamlalo


def _leolvasasok():
    # 08-05 → 09-04: 60 kWh (napi 2), azóta nincs adat.
    return Szamlalo([Pont(datetime(2026, 8, 5), D(0), True), Pont(datetime(2026, 9, 4), D(60), True)])


def test_napi_atlag_a_leolvasasi_utembol():
    assert napi_atlag(_leolvasasok(), datetime(2026, 10, 2, 12)) == D(2)


def test_nyitott_idoszak_becsul_az_utolso_leolvasas_utan(tar):
    most = datetime(2026, 10, 2, 0)
    ny = nyitott(fiok("villany/a1"), tar, date(2026, 9, 4), date(2026, 10, 7), [_leolvasasok()], most)
    assert ny.eddig.mennyiseg == D(56) and ny.eddig.becsult  # 28 nap × 2
    assert ny.varhato.mennyiseg == D(66)  # 33 nap × 2
    assert ny.eddig.osszesen_ft > 154  # nem csak az alapdíj


def test_friss_szenzorral_valtozatlan():
    s = Szamlalo([Pont(datetime(2026, 9, 25, 12), D(0), True), Pont(datetime(2026, 10, 2, 12), D(70), False)])
    assert napi_atlag(s, datetime(2026, 10, 2, 12)) == D(10)
