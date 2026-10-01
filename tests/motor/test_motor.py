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
    assert e.dijak["energia_kedvezmenyes"] == D("4.38976")
    assert e.dijak["energia_piaci"] == D("31.80")  # az alap sorból öröklődik
    assert e.dijak["afa"] == D(27)


def test_feluliras_datumtol(tar):
    f = [Feluliras("dijak.energia_piaci", D("80"), date(2026, 6, 1))]
    assert tar.felold("villany/a1", date(2026, 5, 31), "mvm_demasz", f).dijak["energia_piaci"] == D("31.80")
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


def test_sorozat_meroallas_modban():
    # A statisztika később indul, mint az utolsó leolvasás – óraállás-módban ez nem gond.
    regi = Mero("R", date(2025, 1, 1), D(100), kiszerelve=date(2025, 6, 1), zaro_allas=D(300))
    uj = Mero("U", date(2025, 6, 1), D(10))
    sorozat = [(dt(2025, 5, 1), D(250)), (dt(2025, 7, 1), D(60))]
    s = Szamlalo.csatornabol(Csatorna(merok=[regi, uj]), sorozat, meroallas=True)
    assert s.ertek(dt(2025, 5, 1))[0] == D(150)
    assert s.ertek(dt(2025, 7, 1))[0] == D(200) + D(50)


def test_sorozat_ellentmondas_es_ervenyesseg():
    m = Mero("M", date(2026, 7, 14), D(8668))
    # régi, hibás képletű adatok: a leolvasásnál kisebb értékek július–augusztusban, aztán ugrás
    sorozat = [(dt(2026, 7, 20), D(8643)), (dt(2026, 8, 15), D(8676.7)), (dt(2026, 9, 30), D(8678.2)), (dt(2026, 10, 1), D(8687.7))]
    s = Szamlalo.csatornabol(Csatorna(merok=[m]), sorozat, meroallas=True)
    assert dt(2026, 7, 20) not in [p.ido for p in s.pontok]  # visszafelé futna: eldobva
    s2 = Szamlalo.csatornabol(Csatorna(merok=[m]), sorozat, meroallas=True, sorozat_tol=dt(2026, 9, 30))
    assert [p.ido for p in s2.pontok if not p.horgony] == [dt(2026, 9, 30), dt(2026, 10, 1)]


# --- Elszámolás ----------------------------------------------------------------------------------


def test_a1_keret_alatt_es_felett(tar):
    t, i = date(2025, 6, 1), date(2025, 7, 1)
    r = szamol(fiok("villany/a1"), tar, t, i, [egyenes(t, i, "300")])
    s = r.szeletek[0]
    assert s.keret == D(207) and s.kedvezmenyes == D(207) and s.piaci == D(93)  # 2523/365×30 = 207,4 → 207
    # nettó tételsorok: 207 × 5,25 → 1 087; 93 × 31,80 → 2 957; 300 × 23,40 → 7 020; × 1,27
    assert r.energia_ft == ((1087 + 2957 + 7020) * D("1.27")).quantize(D(1))
    assert r.alapdij_ft == D(154)  # 120,50 → 121 nettó × 1,27, ahogy a számlán


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
    assert nyari.keret == D(97) and nyari.egysegar_kedvezmenyes == D("36.3855")  # 2523/365×14 = 96,8 → 97
    assert (teli.idenyszak, teli.mennyiseg, teli.keret) == ("teli", D(200), None)
    assert abs(teli.egysegar_kedvezmenyes - D("22.962")) < D("0.0001")
    assert r.alapdij_ft == D(51)  # a H saját alapdíja: nettó 39,50 → 40 × 1,27, egy tételként (nem az A1-é)


def test_idenyszak_fordulo():
    sz = [{"nev": "teli", "tol": "10-15", "ig": "04-15"}, {"nev": "nyari"}]
    assert idenyszak(date(2026, 1, 1), sz)["nev"] == "teli"
    assert idenyszak(date(2026, 4, 15), sz)["nev"] == "nyari"
    assert idenyszak(date(2026, 10, 15), sz)["nev"] == "teli"


def test_alapdij_honaphataron_at():
    assert honap_aranya(date(2026, 1, 16), date(2026, 2, 15)) == D(16) / D(31) + D(14) / D(28)


def test_gaz_eves_keret_mj(tar):
    # 34,61 MJ/m³ (alap) → 1 800 m³ ≈ 62 298 MJ; keret 63 645 MJ.
    f = Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/lakossagi", date(2024, 1, 1))], [Csatorna()],
             eves_bazis=date(2025, 7, 1), futoertekek={"2026-01": D("34.00")})
    s = Szamlalo([Pont(dt(2025, 7, 1), D(0), True), Pont(dt(2026, 1, 1), D(1800), True), Pont(dt(2026, 2, 1), D(1900), True)])
    r = szamol(f, tar, date(2026, 1, 1), date(2026, 2, 1), [s])
    sz = r.szeletek[0]
    felhasznalt = sum(round(q * D("34.61")) for q in [D(1800) * n / 184 for n in (31, 31, 30, 31, 30, 31)])
    assert sz.elszamolt == D(3400) and not sz.becsult  # januárra megadott fűtőérték: 100 m³ × 34,00
    assert sz.keret == D(63645) - felhasznalt
    assert sz.kedvezmenyes == sz.keret and sz.piaci == D(3400) - sz.keret
    assert r.alapdij_ft == D(973)


def test_gaz_futoertek_hianyzik_becsult(tar):
    f = Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/lakossagi", date(2024, 1, 1))], [Csatorna()],
             eves_bazis=date(2026, 1, 1))
    s = Szamlalo([Pont(dt(2026, 1, 1), D(0), True), Pont(dt(2026, 2, 1), D(100), True)])
    sz = szamol(f, tar, date(2026, 1, 1), date(2026, 2, 1), [s]).szeletek[0]
    assert sz.elszamolt == D(3461) and sz.becsult and sz.egyseg == "MJ"


def test_viz_csatornadij(tar):
    f = Fiok(Kozmu.VIZ, "vizmu", [DijszabasHozzarendeles("viz/egyedi", date(2024, 1, 1))], [Csatorna()],
             feluliras=[Feluliras("dijak.viz_m3", D("400"), date(2024, 1, 1)),
                        Feluliras("dijak.csatorna_m3", D("600"), date(2024, 1, 1)),
                        Feluliras("dijak.alapdij_ho", D("500"), date(2024, 1, 1))])
    s = Szamlalo([Pont(dt(2026, 1, 1), D(0), True), Pont(dt(2026, 2, 1), D(10), True)])
    r = szamol(f, tar, date(2026, 1, 1), date(2026, 2, 1), [s])
    assert (r.energia_ft, r.szeletek[0].csatorna_ft, r.alapdij_ft) == (D(10000), D(6000), D(500))
    f.csatornak[0].csatornadij_aktiv = False  # locsolási almérő
    assert szamol(f, tar, date(2026, 1, 1), date(2026, 2, 1), [s]).energia_ft == D(4000)


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
    assert n.hatralevo_keret == D(107)
    assert n.varhato_keretatlepes == date(2025, 6, 21)
    assert n.eddig.alapdij_ft == D(154)  # az alapdíj a teljes hónapra jár


def test_fix_dij_hulladek(tar):
    f = Fiok(Kozmu.HULLADEK, "mohu", [DijszabasHozzarendeles("hulladek/mohu", date(2024, 1, 1))], [Csatorna(keret_aktiv=False)])
    s = Szamlalo([Pont(dt(2026, 1, 1), D(0), True)])
    r = szamol(f, tar, date(2026, 10, 1), date(2026, 11, 1), [s])
    assert (r.energia_ft, r.alapdij_ft, r.osszesen_ft) == (D(0), D(1924), D(1924))  # 5 772 / negyedév


def test_negyedeves_idoszak_es_fix_dij(tar):
    assert idoszak(date(2026, 10, 1), "negyedev") == (date(2026, 10, 1), date(2027, 1, 1))
    assert idoszak(date(2026, 2, 15), "negyedev") == (date(2026, 1, 1), date(2026, 4, 1))
    assert idoszak(date(2026, 9, 30), "negyedev") == (date(2026, 7, 1), date(2026, 10, 1))
    f = Fiok(Kozmu.HULLADEK, "mohu", [DijszabasHozzarendeles("hulladek/mohu", date(2024, 1, 1))], [Csatorna(keret_aktiv=False)])
    r = szamol(f, tar, date(2026, 10, 1), date(2027, 1, 1), [Szamlalo([Pont(dt(2026, 1, 1), D(0), True)])])
    assert r.osszesen_ft == D(5772)  # a negyedéves számla összege
