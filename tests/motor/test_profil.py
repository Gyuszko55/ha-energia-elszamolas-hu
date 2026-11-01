"""Ritka leolvasások közti fogyasztás elosztása profil-szenzor (kazánbecslés) szerint."""

from datetime import date, datetime, timedelta
from decimal import Decimal as D

from motor.profil import napi_valtozas, profillal
from motor.szamlalo import Pont, Szamlalo

T0 = datetime(2025, 7, 1)


def _ket_leolvasas(osszes, napok=365):
    return Szamlalo([Pont(T0, D(0), True), Pont(T0 + timedelta(days=napok), D(osszes), True)])


def _fogyasztas(sz, tol, ig):
    return sz.fogyasztas(T0 + timedelta(days=tol), T0 + timedelta(days=ig))[0]


def test_alap_plusz_profil_es_pontos_vegosszeg():
    # 200 napon át napi 5 m³ fűtés (1000), a valódi éves fogyasztás 1365 → az alap napi 1 m³.
    napi = {(T0 + timedelta(days=n)).date(): D(5) if 100 <= n < 300 else D(0) for n in range(365)}
    sz, kitoltott = profillal(_ket_leolvasas(1365), napi)
    assert kitoltott == [(T0, T0 + timedelta(days=365))]
    assert _fogyasztas(sz, 0, 365) == D(1365)
    assert abs(_fogyasztas(sz, 0, 30) - D(30)) < D("0.001")  # nyáron csak az alap
    assert abs(_fogyasztas(sz, 150, 180) - D(180)) < D("0.001")  # télen alap + fűtés


def test_tulbecslo_profil_skalazva_alap_nulla():
    napi = {(T0 + timedelta(days=n)).date(): D(10) for n in range(0, 365)}  # 3650 > 1000
    sz, _ = profillal(_ket_leolvasas(1000), napi)
    assert _fogyasztas(sz, 0, 365) == D(1000)
    assert abs(_fogyasztas(sz, 0, 73) - D(200)) < D("0.001")


def test_keves_lefedettseg_nem_alkalmaz():
    napi = {(T0 + timedelta(days=n)).date(): D(5) for n in range(0, 100)}  # a hézag 27%-a
    sz, kitoltott = profillal(_ket_leolvasas(1000), napi)
    assert kitoltott == [] and len(sz.pontok) == 2


def test_napi_valtozas_nullazodassal():
    sor = [(datetime(2026, 1, 1), D(100)), (datetime(2026, 1, 2), D(105)), (datetime(2026, 1, 3), D(2)), (datetime(2026, 1, 4), D(6))]
    assert napi_valtozas(sor) == {date(2026, 1, 1): D(5), date(2026, 1, 2): D(0), date(2026, 1, 3): D(4)}
