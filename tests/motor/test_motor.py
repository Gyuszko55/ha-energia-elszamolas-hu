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
    assert e.dijak["energia_kedvezmenyes"] == D("4.39")  # MVM árlap, E.ON terület
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
    assert teli.egysegar_kedvezmenyes == D("22.9616")  # (1,90 + 16,18) × 1,27; az MVM árlapon kerekítve 22,962
    # Az alapdíj a hónap 1-jén érvényes idényé: okt. 1. még nyári → az A1 alapdíja (nettó 120,50 → 121 × 1,27 = 154);
    # a városi lakás H-számlái (MVM Démász) ezt mutatják: nyári hónapban 120,50 (bruttó 154, pl. 845700000002), télen 39,50.
    assert r.alapdij_ft == D(154)


def test_idenyszak_fordulo():
    sz = [{"nev": "teli", "tol": "10-15", "ig": "04-15"}, {"nev": "nyari"}]
    assert idenyszak(date(2026, 1, 1), sz)["nev"] == "teli"
    assert idenyszak(date(2026, 4, 15), sz)["nev"] == "nyari"
    assert idenyszak(date(2026, 10, 15), sz)["nev"] == "teli"


def test_alapdij_honaphataron_at():
    assert honap_aranya(date(2026, 1, 16), date(2026, 2, 15)) == D(16) / D(31) + D(14) / D(28)


def test_gaz_eves_keret_mj(tar):
    # Átalányos (egyenletes részszámlás) fiók: éves keret. 34,61 MJ/m³ (alap) → 1 800 m³ ≈ 62 298 MJ; keret 63 645 MJ.
    f = Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/lakossagi", date(2024, 1, 1))], [Csatorna()],
             eves_bazis=date(2025, 7, 1), futoertekek={"2026-01": D("34.00")}, reszszamlas=True)
    s = Szamlalo([Pont(dt(2025, 7, 1), D(0), True), Pont(dt(2026, 1, 1), D(1800), True), Pont(dt(2026, 2, 1), D(1900), True)])
    r = szamol(f, tar, date(2026, 1, 1), date(2026, 2, 1), [s])
    sz = r.szeletek[0]
    felhasznalt = sum(round(q * D("34.61")) for q in [D(1800) * n / 184 for n in (31, 31, 30, 31, 30, 31)])
    assert sz.elszamolt == D(3400) and not sz.becsult  # januárra megadott fűtőérték: 100 m³ × 34,00
    assert sz.keret == D(63645) - felhasznalt
    assert sz.kedvezmenyes == sz.keret and sz.piaci == D(3400) - sz.keret
    assert sz.keret_eves and sz.keret_evi == D(63645)
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


def test_h_ket_regiszter_oktober(tar):
    # okt. 1–14: a nyári regiszter (1.82) nő 30 kWh-t; okt. 15-től a téli (1.81) 50 kWh-t – külön csatornán mérve
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/h", date(2024, 1, 1))],
             [Csatorna(szerep="h_teli", keret_aktiv=False), Csatorna(szerep="h_nyari")])
    teli = Szamlalo([Pont(dt(2026, 10, 1), D(474), True), Pont(dt(2026, 10, 15), D(474), True), Pont(dt(2026, 11, 1), D(524), True)])
    nyari = Szamlalo([Pont(dt(2026, 10, 1), D(528), True), Pont(dt(2026, 10, 15), D(558), True), Pont(dt(2026, 11, 1), D(558), True)])
    r = szamol(f, tar, date(2026, 10, 1), date(2026, 11, 1), [teli, nyari])
    t = [s for s in r.szeletek if s.csatorna == "h_teli"]
    n = [s for s in r.szeletek if s.csatorna == "h_nyari"]
    assert sum(s.mennyiseg for s in t) == D(50) and all(s.idenyszak == "teli" and s.keret is None for s in t)
    assert sum(s.mennyiseg for s in n) == D(30) and all(s.idenyszak == "nyari" for s in n)
    assert n[0].egysegar_kedvezmenyes == D("36.3855")  # nyári regiszter: A1 ár
    assert r.alapdij_ft == D(154)  # egyszer, a fiókra – okt. 1-jén még nyári idény: az A1 alapdíja (bruttó 154)


def test_h_regiszter_elorejelzes_oktober_15_utan_a_telire(tar):
    # okt. 10-ig 4 kWh/nap a nyári regiszteren; az előrejelzés okt. 15-től a télihez adja
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/h", date(2024, 1, 1))],
             [Csatorna(szerep="h_teli", keret_aktiv=False), Csatorna(szerep="h_nyari")])
    teli = Szamlalo([Pont(dt(2026, 9, 1), D(474), True), Pont(dt(2026, 10, 10), D(474), True)])
    nyari = Szamlalo([Pont(dt(2026, 9, 1), D(400), True), Pont(dt(2026, 10, 10), D(556), True)])
    n = nyitott(f, tar, date(2026, 10, 1), date(2026, 11, 1), [teli, nyari], dt(2026, 10, 10))
    v_teli = sum(s.mennyiseg for s in n.varhato.szeletek if s.csatorna == "h_teli")
    v_nyari = sum(s.mennyiseg for s in n.varhato.szeletek if s.csatorna == "h_nyari")
    assert v_teli == D(4) * 17  # okt. 15–31
    assert v_nyari == D(36) + D(4) * 5  # okt. 1–10 tényleges + okt. 10–15 előrejelzés


def test_h_nyari_regiszter_kerete_csak_nyaron(tar):
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/h", date(2024, 1, 1))],
             [Csatorna(szerep="h_teli", keret_aktiv=False), Csatorna(szerep="h_nyari")])
    lapos = lambda v: Szamlalo([Pont(dt(2026, 10, 1), D(v), True)])  # noqa: E731
    r = szamol(f, tar, date(2026, 10, 1), date(2026, 11, 1), [lapos(474), lapos(528)])
    keretek = {(s.tol, s.ig): s.keret for s in r.szeletek if s.csatorna == "h_nyari"}
    assert keretek == {(date(2026, 10, 1), date(2026, 10, 15)): D(97), (date(2026, 10, 15), date(2026, 11, 1)): D(0)}


def test_minden_dijszabasnak_van_forrasa_es_ellenorzese():
    """Minden beépített díjszabás-verzió: forrás, érvényesség, ellenőrzöttség (állapot, dátum, mivel)."""
    from pathlib import Path

    import yaml
    from motor.dijszabas import ELLENORZES_ALLAPOTOK, betolt_fajl

    mappa = Path(__file__).resolve().parents[2] / "custom_components" / "hu_rezsi" / "dijszabasok"
    fajlok = [f for f in mappa.rglob("*.yaml") if f.name != "szolgaltatok.yaml"]
    assert len(fajlok) >= 15
    for f in fajlok:
        d = betolt_fajl(yaml.safe_load(f.read_text(encoding="utf-8")), str(f))
        for v in d.verziok:
            assert v.forras and v.ellenorzes and v.ellenorzes["allapot"] in ELLENORZES_ALLAPOTOK, f


def test_alapdij_honapkezdetenkent(tar):
    """MVM: annyi havi alapdíj, ahány hónap 1-je esik az elszámolt időszakba (valódi számlák: 07.10–07.31 → 0,
    08.01–09.08 → 2, 11.16–02.06 → 3); a H-nál télen a saját (39,50), nyáron az A1 (120,50) alapdíja."""
    def alap(dsz, t, i):
        s = Szamlalo([Pont(dt(t.year, t.month, t.day), D(0), True), Pont(dt(i.year, i.month, i.day), D(10), True)])
        return szamol(fiok(dsz), tar, t, i, [s]).alapdij_ft
    assert alap("villany/a1", date(2025, 7, 10), date(2025, 8, 1)) == D(0)
    assert alap("villany/a1", date(2025, 8, 1), date(2025, 9, 9)) == D(307)  # 2 × 120,50 = 241 nettó → 306,07 → tételenként kerekítve
    assert alap("villany/a1", date(2025, 11, 16), date(2026, 2, 7)) == D(461)  # 3 hónap, szeletenként kerekítve (a városi lakás számlájával egyezik)
    assert alap("villany/h", date(2025, 12, 10), date(2026, 1, 7)) == D(51)   # jan. 1.: téli idény


def test_gaz_korrekcios_tenyezo_az_elszamolobol(tar):
    """Az éves gázelszámoló 1,018-as korrekcióval számol (a részszámlák 1,0-val): a hónapra az elszámolóé, más
    hónapra a legutóbbi elszámolóé."""
    from motor.elszamolas import atvalt
    f = fiok("gaz/lakossagi")
    f.futoertekek = {"2026-01": D("34.9"), "2026-09": D("34.61")}
    f.korrekciok = {"2026-01": D("1.018")}
    atv = {"tipus": "gaz_mj", "futoertek_alap": 34.61, "korrekcios_tenyezo_alap": 1}
    assert atvalt(D(280), date(2026, 1, 10), atv, f)[0] == D(9948)  # 280 × 1,018 × 34,9 = 9 947,7 – a számlán 9 948 MJ
    assert atvalt(D(100), date(2026, 9, 10), atv, f)[0] == D(3523)  # 100 × 1,018 × 34,61


def test_keret_szamlankent_kerekitve(tar):
    """MVM (Kertes ház A1, 2024/25): a keret számlánként kerekítve jár (29 nap → 200, 28 → 194), aug. 1-jén tételenként
    (23 nap → 159, 10 → 69); az évkezdettől egyben kerekítve 1 kWh-val eltérne (pl. 06.11–07.08: 193 helyett 194)."""
    from motor.elszamolas import _osszesitett_kedvezmenyes
    hatarok = (date(2024, 10, 2), date(2025, 5, 12), date(2025, 6, 11), date(2025, 7, 9), date(2025, 8, 11))
    f = fiok("villany/a1")
    f.elszamolasi_napok = (date(2024, 10, 2),)
    f.szamlazasi_hatarok = hatarok
    keret = tar.felold("villany/a1", date(2025, 6, 11), "mvm_demasz").szabalyok["keret"]
    # nagy fogyasztás: a keret mindig elfogy – a kedvezményes rész = a járó keret növekménye
    s = Szamlalo([Pont(dt(2024, 10, 2), D(0), True), Pont(dt(2025, 8, 11), D(100000), True)])
    assert _osszesitett_kedvezmenyes(f, tar, "vetelezes", [s], keret, date(2025, 6, 11), date(2025, 7, 9), D(300), None) == D(194)
    assert _osszesitett_kedvezmenyes(f, tar, "vetelezes", [s], keret, date(2025, 7, 9), date(2025, 8, 11), D(300), None) == D(228)


def test_tetelsorok_osszege_a_vegosszeg(tar):
    """A tájékoztató tételsorok (energiadíj, rendszerhasználati díj, alapdíj) nettója ÁFA-val = a számolt bruttó."""
    t, i = date(2025, 10, 1), date(2025, 11, 1)
    s = Szamlalo([Pont(dt(2025, 10, 1), D(0), True), Pont(dt(2025, 10, 15), D(50), True), Pont(dt(2025, 11, 1), D(250), True)])
    r = szamol(fiok("villany/h"), tar, t, i, [s])
    tetelek = [x for sz in r.szeletek for x in sz.tetelek]
    nevek = {x["nev"] for x in tetelek}
    assert {"Rendszerhasználati díj", "Alapdíj"} <= nevek and any("H téli" in n for n in nevek)
    alap = next(x for x in tetelek if x["nev"] == "Alapdíj")
    assert (alap["mennyiseg"], alap["ar"]) == (D(1), D(121))  # nyári hónap 1-je: az A1 alapdíja, egy hónap
    netto = sum(x["netto"] for x in tetelek)
    assert abs(netto * D("1.27") - r.osszesen_ft) <= 2


def test_eddig_csak_az_elmult_honapfordulok_alapdija(tar):
    """A folyó időszak „Eddig” értéke nem tartalmazza a még el nem jött hónap 1-jei alapdíjat (alapdij_eddig)."""
    t, i = date(2026, 10, 2), date(2026, 11, 7)
    s = Szamlalo([Pont(dt(2026, 10, 2), D(0), True), Pont(dt(2026, 10, 5), D(3), True)])
    most = dt(2026, 10, 5)
    teljes = szamol(fiok("villany/a1"), tar, t, i, [s], meres_vege=most)
    eddig = szamol(fiok("villany/a1"), tar, t, i, [s], meres_vege=most, alapdij_eddig=True)
    assert teljes.alapdij_ft > 0 and eddig.alapdij_ft == 0
    assert teljes.osszesen_ft - eddig.osszesen_ft == teljes.alapdij_ft
