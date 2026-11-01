"""Automatikus mérő-korrekció: arány a valódi leolvasásokból, ugrásszűrés, gyanús leolvasás."""

from datetime import datetime, timedelta
from decimal import Decimal as D

from motor.kalibracio import kalibral, tisztit

T0 = datetime(2026, 1, 1)


def _sor(napok, arany=D("1.05"), ugras=None):
    """Napi Shelly-sorozat: a valódi napi 10 kWh-ból arany-szor kevesebbet lát; ugras=(nap, mennyiség): kézi eltolás."""
    ki, v = [], D(5000)
    for n in range(napok + 1):
        if n:
            v += D(10) / arany
        if ugras and n == ugras[0]:
            v += ugras[1]
        ki.append((T0 + timedelta(days=n), v))
    return ki


def _leolv(napok, rossz=None):
    """Valódi mérőóra (napi 10 kWh) 30 naponta; rossz=(nap, eltérés): elírt/más napra tett leolvasás."""
    return [(T0 + timedelta(days=n), D(10 * n) + (rossz[1] if rossz and rossz[0] == n else 0)) for n in range(0, napok + 1, 30)]


def test_alulmero_shelly_ugrassal_es_rossz_leolvasassal():
    k = kalibral(_leolv(210, rossz=(150, D(-60))), _sor(210, ugras=(100, D(500))), T0 + timedelta(days=211))
    assert abs(k.szorzo - D("1.05")) < D("0.003")
    assert [n for n, _ in k.ugrasok] == [(T0 + timedelta(days=100)).date()]
    assert [(n, e) for n, e in k.gyanus] == [((T0 + timedelta(days=150)).date(), D(-60))]


def test_tisztit_nullazodas_es_ugras():
    sor = [(T0, D(100)), (T0 + timedelta(days=1), D(110)), (T0 + timedelta(days=2), D(5)), (T0 + timedelta(days=3), D(15))]
    tiszta, ugrasok = tisztit(sor)
    assert [v for _, v in tiszta] == [D(0), D(10), D(10), D(20)] and ugrasok == []


def test_reszleges_forras_nem_korrigal():
    # A szenzor csak a kör felét látja (pl. klíma a H-körön): nem korrigálunk, csak jelzünk.
    k = kalibral(_leolv(120), _sor(120, arany=D(2)), T0 + timedelta(days=121))
    assert k.szorzo is None and k.arany == D("2.000") and "50%" in k.ok


def test_keves_leolvasas():
    k = kalibral(_leolv(40), _sor(40), T0 + timedelta(days=41))
    assert k.szorzo is None and "kevés" in k.ok


def _leolv_tobb(napok, rosszak):
    """Mint a _leolv, de több elírt leolvasással: rosszak = {nap: eltérés}."""
    return [(T0 + timedelta(days=n), D(10 * n) + rosszak.get(n, D(0))) for n in range(0, napok + 1, 30)]


def test_jo_leolvasas_ket_rossz_kozott_nem_gyanus():
    # A 150. nap jó, de mindkét közvetlen szomszédja (120., 180.) elírt: csak a két rossz gyanús.
    k = kalibral(_leolv_tobb(240, {120: D(60), 180: D(45)}), _sor(240), T0 + timedelta(days=241))
    napok = [(n - T0.date()).days for n, _ in k.gyanus]
    assert napok == [120, 180]


def test_utolso_jo_leolvasas_rossz_szomszeddal_nem_gyanus():
    # Valós eset (kertes ház): az utolsó előtti (diktálás) elírt, az utolsó saját leolvasás jó.
    k = kalibral(_leolv_tobb(300, {270: D(95)}), _sor(300), T0 + timedelta(days=301))
    assert [((n - T0.date()).days, e) for n, e in k.gyanus] == [(270, D(95))]
