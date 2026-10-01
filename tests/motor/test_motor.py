"""Az elszámoló motor egységtesztjei (HA nélkül)."""

from datetime import date, datetime
from decimal import Decimal as D

import pytest

from tests.conftest import DIJSZABASOK
from motor.dijszabas import DijszabasHiba, DijszabasTar, betolt_fajl
from motor.elorejelzes import idoszak, nyitott
from motor.elszamolas import honap_aranya, idenyszak, szamol
from motor.szamlalo import NincsAdat, Pont, Szamlalo
from motor.tipusok import (
    Csatorna,
    DijszabasHozzarendeles,
    Feluliras,
    Fiok,
    Kozmu,
    Leolvasas,
    LeolvasasTipus,
    Mero,
)


@pytest.fixture(scope="module")
def tar() -> DijszabasTar:
    return DijszabasTar.mappabol(DIJSZABASOK)


def dt(*a) -> datetime:
    return datetime(*a)


def fiok(dijszabas: str, szolg: str = "mvm_demasz", **kw) -> Fiok:
    return Fiok(Kozmu.VILLANY, szolg, [DijszabasHozzarendeles(dijszabas, date(2024, 1, 1))], [Csatorna()], **kw)


def egyenes(tol: date, ig: date, q: str) -> Szamlalo:
    return Szamlalo([Pont(dt(tol.year, tol.month, tol.day), D(0), True), Pont(dt(ig.year, ig.month, ig.day), D(q), True)])


# --- Díjszabás -----------------------------------------------------------------------------------


def test_dijfajlok_betoltodnek(tar):
    assert {"villany/a1", "villany/h", "gaz/lakossagi"} <= set(tar.dijszabasok)
    assert "mvm_demasz" in tar.szolgaltatok


def test_szolgaltatoi_sor_es_oroklodes(tar):
    e = tar.felold("villany/a1", date(2026, 9, 1), "eon")
    assert e.dijak["energia_kedvezmenyes"] == D("35.293")
    assert e.dijak["energia_piaci"] == D("70.104")  # az alap sorból öröklődik


def test_feluliras_datumtol(tar):
    f = [Feluliras("dijak.energia_piaci", D("80"), date(2026, 6, 1))]
    assert tar.felold("villany/a1", date(2026, 5, 31), "mvm_demasz", f).dijak["energia_piaci"] == D("70.104")
    assert tar.felold("villany/a1", date(2026, 6, 1), "mvm_demasz", f).dijak["energia_piaci"] == D("80")


@pytest.mark.parametrize(
    "hiba",
    [
        {"verziok": []},
        {"verziok": [{"ervenyes_tol": date(2025, 1, 1), "forras": "", "dijak": {"alap": {}}}]},
        {"verziok": [{"ervenyes_tol": date(2025, 1, 1), "forras": "x", "dijak": {}}]},
        {
            "verziok": [
                {"ervenyes_tol": date(2025, 1, 1), "forras": "x", "dijak": {"alap": {}}},
                {"ervenyes_tol": date(2024, 1, 1), "forras": "x", "dijak": {"alap": {}}},
            ]
        },
    ],
)
def test_hibas_dijfajl(hiba):
    adat = {"azonosito": "t", "nev": "t", "kozmu": "villany", "egyseg": "kWh"} | hiba
    with pytest.raises(DijszabasHiba):
        betolt_fajl(adat)


def test_uj_verzio_szeletet_nyit():
    adat = {
        "azonosito": "t/x",
        "nev": "t",
        "kozmu": "villany",
        "egyseg": "kWh",
        "verziok": [
            {"ervenyes_tol": date(2026, 1, 1), "forras": "x", "szabalyok": {"keret": {"tipus": "nincs"}},
             "dijak": {"alap": {"energia_kedvezmenyes": 10, "alapdij_ho": 0}}},
            {"ervenyes_tol": date(2026, 1, 16), "forras": "y", "szabalyok": {"keret": {"tipus": "nincs"}},
             "dijak": {"alap": {"energia_kedvezmenyes": 20, "alapdij_ho": 0}}},
        ],
    }
    t = DijszabasTar({"t/x": betolt_fajl(adat)})
    f = Fiok(Kozmu.VILLANY, "egyedi", [DijszabasHozzarendeles("t/x", date(2026, 1, 1))], [Csatorna()])
    s = Szamlalo([Pont(dt(2026, 1, 1), D(0), True), Pont(dt(2026, 1, 16), D(15), True), Pont(dt(2026, 2, 1), D(31), True)])
    r = szamol(f, t, date(2026, 1, 1), date(2026, 2, 1), [s])
    assert [x.energia_ft for x in r.szeletek] == [D("150.00"), D("320.00")]
    assert r.szeletek[1].dijszabas_verzio == "t/x@2026-01-16"


# --- Számláló ------------------------------------------------------------------------------------


def test_merocsere_folytonos():
    regi = Mero("R", date(2025, 1, 1), D(1000), kiszerelve=date(2025, 6, 1), zaro_allas=D(1500),
                leolvasasok=[Leolvasas(date(2025, 3, 1), D(1200))])
    uj = Mero("U", date(2025, 6, 1), D(0), leolvasasok=[Leolvasas(date(2025, 7, 1), D(100))])
    s = Szamlalo.csatornabol(Csatorna(merok=[regi, uj]))
    assert s.fogyasztas(dt(2025, 1, 1), dt(2025, 7, 1))[0] == D(600)
    assert s.ertek(dt(2025, 6, 1))[0] == D(500)


def test_interpolacio_becsult():
    s = Szamlalo([Pont(dt(2025, 1, 1), D(0), True), Pont(dt(2025, 1, 11), D(100), True)])
    ertek, becsult = s.ertek(dt(2025, 1, 6))
    assert ertek == D(50) and becsult
    with pytest.raises(NincsAdat):
        s.ertek(dt(2024, 12, 31))


def test_leolvasas_elsobbsege():
    m = Mero("M", date(2025, 1, 1), leolvasasok=[
        Leolvasas(date(2025, 2, 1), D(90), LeolvasasTipus.AUTOMATIKUS),
        Leolvasas(date(2025, 2, 1), D(100), LeolvasasTipus.SZOLGALTATOI),
        Leolvasas(date(2025, 2, 1), D(95), LeolvasasTipus.KEZI),
    ])
    assert Szamlalo.csatornabol(Csatorna(merok=[m])).ertek(dt(2025, 2, 1))[0] == D(100)


def test_sorozat_a_leolvasashoz_igazodik():
    m = Mero("M", date(2025, 1, 1), D(5000), leolvasasok=[Leolvasas(date(2025, 1, 10), D(5100))])
    sorozat = [(dt(2025, 1, 10), D(40)), (dt(2025, 1, 11), D(50)), (dt(2025, 1, 12), D(70))]
    s = Szamlalo.csatornabol(Csatorna(merok=[m]), sorozat, szorzo=D(2))
    assert s.ertek(dt(2025, 1, 12))[0] == D(100) + D(30) * 2
    assert s.ertek(dt(2025, 1, 11)) == (D(120), False)


# --- Elszámolás ----------------------------------------------------------------------------------


def test_a1_keret_alatt_es_felett(tar):
    t, i = date(2025, 6, 1), date(2025, 7, 1)
    r = szamol(fiok("villany/a1"), tar, t, i, [egyenes(t, i, "300")])
    s = r.szeletek[0]
    assert s.keret == D("207.30") and s.kedvezmenyes == D("207.30") and s.piaci == D("92.70")
    assert r.energia_ft == (D("207.3") * D("36.386") + D("92.7") * D("70.104")).quantize(D(1))
    assert r.alapdij_ft == D(153)


def test_keret_kikapcsolva_minden_piaci(tar):
    f = fiok("villany/a1")
    f.csatornak[0].keret_aktiv = False
    t, i = date(2025, 6, 1), date(2025, 7, 1)
    s = szamol(f, tar, t, i, [egyenes(t, i, "100")]).szeletek[0]
    assert s.kedvezmenyes == 0 and s.piaci == D(100)


def test_h_idenyvaltas_oktober(tar):
    t, i = date(2025, 10, 1), date(2025, 11, 1)
    s = Szamlalo([Pont(dt(2025, 10, 1), D(0), True), Pont(dt(2025, 10, 15), D(50), True), Pont(dt(2025, 11, 1), D(250), True)])
    r = szamol(fiok("villany/h"), tar, t, i, [s])
    nyari, teli = r.szeletek
    assert (nyari.idenyszak, nyari.tol, nyari.ig, nyari.mennyiseg) == ("nyari", t, date(2025, 10, 15), D(50))
    assert nyari.keret == D("6.91") * 14 and nyari.egysegar_kedvezmenyes == D("36.386")
    assert (teli.idenyszak, teli.mennyiseg, teli.keret, teli.egysegar_kedvezmenyes) == ("teli", D(200), None, D("22.962"))
    assert r.alapdij_ft == D(50)  # a H saját alapdíja, nem az A1-é


def test_idenyszak_fordulo():
    sz = [{"nev": "teli", "tol": "10-15", "ig": "04-15"}, {"nev": "nyari"}]
    assert idenyszak(date(2026, 1, 1), sz)["nev"] == "teli"
    assert idenyszak(date(2026, 4, 15), sz)["nev"] == "nyari"
    assert idenyszak(date(2026, 10, 15), sz)["nev"] == "teli"


def test_alapdij_honaphataron_at():
    assert honap_aranya(date(2026, 1, 16), date(2026, 2, 15)) == D(16) / D(31) + D(14) / D(28)


def test_gaz_eves_keret(tar):
    f = Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/lakossagi", date(2024, 1, 1))], [Csatorna()],
             eves_bazis=date(2025, 7, 1))
    s = Szamlalo([Pont(dt(2025, 7, 1), D(0), True), Pont(dt(2026, 1, 1), D(1700), True), Pont(dt(2026, 2, 1), D(1800), True)])
    r = szamol(f, tar, date(2026, 1, 1), date(2026, 2, 1), [s])
    sz = r.szeletek[0]
    assert sz.keret == D(29) and sz.kedvezmenyes == D(29) and sz.piaci == D(71)
    assert r.energia_ft == D(29 * 102 + 71 * 747)


def test_idoszak_modok():
    assert idoszak(date(2026, 2, 10)) == (date(2026, 2, 1), date(2026, 3, 1))
    assert idoszak(date(2026, 2, 10), "egyedi_nap", 12) == (date(2026, 1, 12), date(2026, 2, 12))
    assert idoszak(date(2026, 12, 20), "egyedi_nap", 12) == (date(2026, 12, 12), date(2027, 1, 12))


def test_nyitott_idoszak_elorejelzes(tar):
    # 10 nap alatt 100 kWh → napi 10; 30 napos hónap: várható 300 kWh, keret 207,3 → túllépés.
    s = Szamlalo([Pont(dt(2025, 6, 1), D(0), True), Pont(dt(2025, 6, 11), D(100), True)])
    n = nyitott(fiok("villany/a1"), tar, date(2025, 6, 1), date(2025, 7, 1), [s], dt(2025, 6, 11))
    assert n.napi_atlag[0] == D(10)
    assert n.varhato.mennyiseg == D(300)
    assert n.hatralevo_keret == D("107.30")
    assert n.varhato_keretatlepes == date(2025, 6, 21)
    assert n.eddig.alapdij_ft == D(153)  # az alapdíj a teljes hónapra jár
