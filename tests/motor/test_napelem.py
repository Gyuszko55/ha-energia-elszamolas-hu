"""Napelemes (HMKE) elszámolás: bruttó és szaldó."""

from datetime import date, datetime
from decimal import Decimal as D

from tests.conftest import DIJSZABASOK
from motor.dijszabas import DijszabasTar
from motor.napelem import brutto, szaldo
from motor.szamlalo import Pont, Szamlalo
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu

TAR = DijszabasTar.mappabol(DIJSZABASOK)


def _fiok(szolg="mvm_demasz"):
    return Fiok(Kozmu.VILLANY, szolg, [DijszabasHozzarendeles("villany/a1", date(2024, 1, 1))],
                [Csatorna(szerep="vetelezes"), Csatorna(szerep="betaplalas", keret_aktiv=False)])


def _sz(tol, ig, q):
    return Szamlalo([Pont(datetime(*tol), D(0), True), Pont(datetime(*ig), D(q), True)])


def test_brutto_honap():
    # június: 150 kWh vételezés (keret alatt), 400 kWh betáplálás 5,25 Ft-on
    r = brutto(_fiok(), TAR, date(2026, 6, 1), date(2026, 7, 1), _sz((2026, 6, 1), (2026, 7, 1), 150), _sz((2026, 6, 1), (2026, 7, 1), 400))
    assert r.energia_ft == ((round(D(150) * D("5.25")) + round(D(150) * D("23.4"))) * D("1.27")).quantize(D(1))
    assert r.jovairas_ft == D("2100.00")
    assert r.egyenleg_ft == (r.energia_ft + r.alapdij_ft - D(2100)).quantize(D(1))


def test_brutto_elosztonkent_mas_ar():
    r = brutto(_fiok("eon"), TAR, date(2026, 6, 1), date(2026, 7, 1), _sz((2026, 6, 1), (2026, 7, 1), 0), _sz((2026, 6, 1), (2026, 7, 1), 100))
    assert r.jovairas_ft == D("439.00")


def test_szaldo_vetelezesi_tobblet():
    # egy év: 4 000 kWh vételezés, 3 000 kWh betáplálás → 1 000 kWh nettó, a 2 523-as kereten belül
    ev = ((2025, 7, 1), (2026, 7, 1))
    r = szaldo(_fiok(), TAR, date(2025, 7, 1), date(2026, 7, 1), _sz(*ev, 4000), _sz(*ev, 3000))
    assert (r.elszamolt_vetelezes, r.tobblet, r.jovairas_ft) == (D(1000), D(0), D(0))
    assert r.energia_ft == ((round(D(1000) * D("5.25")) + round(D(1000) * D("23.4"))) * D("1.27")).quantize(D(1))
    assert r.alapdij_ft == (D(121) * D("1.27") * 12).quantize(D("0.01"))  # 12 hónap alapdíj


def test_szaldo_betaplalasi_tobblet():
    ev = ((2025, 7, 1), (2026, 7, 1))
    r = szaldo(_fiok(), TAR, date(2025, 7, 1), date(2026, 7, 1), _sz(*ev, 3000), _sz(*ev, 3500))
    assert (r.elszamolt_vetelezes, r.tobblet, r.energia_ft) == (D(0), D(500), D(0))
    assert r.jovairas_ft == D("500.00")  # 1 Ft/kWh (ellenőrizendő)
    assert r.egyenleg_ft == (r.alapdij_ft - D(500)).quantize(D(1))


def test_szaldo_ev_kozben_aranyos_keret():
    # fél év után 2 000 kWh nettó: a keret az eltelt napokkal arányos (~1 260), a felette lévő piaci áron
    vetel = Szamlalo([Pont(datetime(2025, 7, 1), D(0), True), Pont(datetime(2026, 1, 1), D(2500), True)])
    betap = Szamlalo([Pont(datetime(2025, 7, 1), D(0), True), Pont(datetime(2026, 1, 1), D(500), True)])
    r = szaldo(_fiok(), TAR, date(2025, 7, 1), date(2026, 7, 1), vetel, betap, meres_vege=datetime(2026, 1, 1))
    assert r.elszamolt_vetelezes == D(2000)
    assert r.alapdij_ft == (D(121) * D("1.27") * 6).quantize(D("0.01"))  # júl.–dec.: 6 megkezdett hónap
