"""A számolómotor hibajavításainak regressziós tesztjei (nullázódás, nullás meredekség, túlcsordulás, első verzió
előtti nap, hónaponkénti alapdíj, szaldó alapdíj, éves keret megújulása, beépítés napi leolvasás, nan/inf)."""

from datetime import date, datetime, timedelta
from decimal import Decimal as D

from motor.dijszabas import DijszabasTar
from motor.egyenleg import havi_alapdij_brutto, havi_alapdij_honapokra, varhato_elszamolas
from motor.elorejelzes import nyitott
from motor.elszamolas import eves_keret_kezdete, szamol
from motor.kalibracio import kalibral
from motor.napelem import szaldo
from motor.szamlalo import Pont, Szamlalo, kijelzett_allas
from motor.sziget import szamlalo_sorozatbol
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu, Leolvasas, Mero

from tests.conftest import DIJSZABASOK

TAR = DijszabasTar.mappabol(DIJSZABASOK)
A1_HAVI = D(121) * D("1.27")  # 120,50 nettó → számlán 121 Ft, bruttó 153,67


def _sz(*pontok):
    return Szamlalo([Pont(datetime(*t), D(v), True) for t, v in pontok])


def _villany(ds="villany/a1", csatornak=None):
    return Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles(ds, date(2024, 1, 1))], csatornak or [Csatorna()])


# 1. Fogyasztás-szenzor (meroallas=False) nullázódása
def test_fogyasztas_szenzor_nullazodas_utan_nem_vesz_el():
    m = Mero("x", date(2026, 10, 1), D(1000), leolvasasok=[Leolvasas(date(2026, 10, 1), D(1000))])
    sor = [(datetime(2026, 10, 1), D(500)), (datetime(2026, 10, 2), D(510)), (datetime(2026, 10, 3), D(520)),
           (datetime(2026, 10, 4), D(5)), (datetime(2026, 10, 5), D(25))]  # 10-04: a szenzor nullázódott
    s = Szamlalo.csatornabol(Csatorna(merok=[m]), sor)
    assert s.fogyasztas(datetime(2026, 10, 1), datetime(2026, 10, 5))[0] == D(45)  # 20 + 5 + 20


def test_fogyasztas_szenzor_kis_visszaugras_zaj():
    m = Mero("x", date(2026, 10, 1))
    sor = [(datetime(2026, 10, 1), D(500)), (datetime(2026, 10, 2), D("499.9")), (datetime(2026, 10, 3), D(510))]
    s = Szamlalo.csatornabol(Csatorna(merok=[m]), sor)
    assert s.fogyasztas(datetime(2026, 10, 1), datetime(2026, 10, 3))[0] == D(10)


# 2. Kalibráció: a mérőóra állása nem változik, a forrás igen (meredekség 0)
def test_kalibral_nulla_meredekseg_nem_dob_hibat():
    le = [(datetime(2026, m, 1), D(100)) for m in (7, 8, 9, 10)]
    sor = [(datetime(2026, 6, 25) + timedelta(days=i), D(i) * D("0.5")) for i in range(110)]
    k = kalibral(le, sor, datetime(2026, 10, 10))
    assert k.szorzo is None and k.arany == 0 and "nem mért" in k.ok


# 3. Várható keretátlépés igen kicsi napi átlagnál
def test_keretatlepes_kis_atlagnal_nincs_tulcsordulas():
    s = Szamlalo([Pont(datetime(2026, 10, 1) + timedelta(hours=h), D("0.000001") * h, False) for h in range(24 * 30)])
    ny = nyitott(_villany(), TAR, date(2026, 10, 1), date(2026, 11, 1), [s], datetime(2026, 10, 30, 23))
    assert ny.varhato_keretatlepes is None and ny.hatralevo_keret > 0


# 4. A díjszabás első verziója előtti nap
def test_drv_a_2024_es_kezdettel_szamol():
    f = Fiok(Kozmu.VIZ, "drv", [DijszabasHozzarendeles("viz/drv", date(2024, 1, 1))], [Csatorna()])
    r = szamol(f, TAR, date(2025, 5, 1), date(2025, 6, 1), [_sz(((2025, 5, 1), 0), ((2025, 6, 1), 5))])
    assert r.szeletek[0].dijszabas_verzio == "viz/drv@2013-07-01" and not r.becsult
    assert r.osszesen_ft > 0


def test_elso_verzio_elotti_nap_az_elso_verzioval_becsult():
    # hulladek/mohu_udulo 2025-03-01-től ismert: a 2024-es nap az első verzió díjával, becsültként (nem hiba)
    f = Fiok(Kozmu.HULLADEK, "mohu", [DijszabasHozzarendeles("hulladek/mohu_udulo", date(2024, 1, 1))],
             [Csatorna(keret_aktiv=False)])
    r = szamol(f, TAR, date(2024, 6, 1), date(2024, 7, 1), [_sz(((2024, 1, 1), 0))])
    assert r.becsult and r.szeletek[0].dijszabas_verzio == "hulladek/mohu_udulo@2025-03-01"
    assert TAR.felold("hulladek/mohu_udulo", date(2024, 6, 1), "mohu").verzio_elott
    assert not TAR.felold("hulladek/mohu_udulo", date(2025, 6, 1), "mohu").verzio_elott


# 5. Az alapdíj hónaponként a saját díjával (idény, csak bizonyos hónapokban járó díj)
def test_varhato_elszamolas_h_tarifa_honaponkenti_alapdij():
    f = _villany("villany/h")
    assert havi_alapdij_brutto(f, TAR, date(2026, 7, 10)) == A1_HAVI  # nyáron az A1 alapdíja (mint a szamol-ban)
    teli = havi_alapdij_brutto(f, TAR, date(2026, 11, 10))
    assert teli < A1_HAVI
    sz = _sz(((2026, 6, 1), 0), ((2026, 11, 10), 0))
    v = varhato_elszamolas(f, TAR, sz, datetime(2026, 11, 10), date(2026, 6, 1), [])
    assert v.tenyleges == (4 * A1_HAVI + teli).quantize(D(1))  # júl.–okt. A1, nov. H – nem 5 × a novemberi


def test_fix_dij_kovetkezo_szamla_honaponkent():
    f = Fiok(Kozmu.HULLADEK, "mohu", [DijszabasHozzarendeles("hulladek/mohu_udulo", date(2025, 3, 1))],
             [Csatorna(keret_aktiv=False)])
    assert havi_alapdij_honapokra(f, TAR, date(2026, 10, 5), 3) == D(0)  # idényen kívül
    assert havi_alapdij_honapokra(f, TAR, date(2026, 8, 5), 3) == D("2211.00")  # aug., szept. igen, okt. nem


# 6. Szaldó: nem 1-jén kezdődő évre 12 alapdíj
def test_szaldo_nem_elsejei_evre_12_alapdij():
    f = _villany(csatornak=[Csatorna(), Csatorna(szerep="betaplalas", keret_aktiv=False)])
    r = szaldo(f, TAR, date(2025, 10, 2), date(2026, 10, 2),
               _sz(((2025, 10, 2), 0), ((2026, 10, 2), 4000)), _sz(((2025, 10, 2), 0), ((2026, 10, 2), 3000)))
    assert r.alapdij_ft == 12 * A1_HAVI


def test_szaldo_ev_kozben_a_mai_elseje_mar_jar():
    # „ha ma lenne az elszámolás” 11-01 délután, év 01-16-tól: 02-01 … 11-01 = 10 alapdíj (a mai 1-je is, mint a
    # szamol alapdij_eddig szabályánál); 10-31-én még 9
    f = _villany(csatornak=[Csatorna(), Csatorna(szerep="betaplalas", keret_aktiv=False)])
    for most, db in ((datetime(2026, 11, 1, 14), 10), (datetime(2026, 10, 31, 23), 9)):
        r = szaldo(f, TAR, date(2026, 1, 16), date(2027, 1, 16), _sz(((2026, 1, 16), 0), (most.timetuple()[:4], 100)),
                   _sz(((2026, 1, 16), 0), (most.timetuple()[:4], 200)), meres_vege=most)
        assert r.alapdij_ft == db * A1_HAVI


# 7. Éves (részszámlás gáz) keret megújul az éves bázis évfordulóján
def test_eves_keret_megujul_evfordulon():
    f = Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/lakossagi", date(2024, 1, 1))], [Csatorna()],
             eves_bazis=date(2025, 8, 1), reszszamlas=True)
    s = _sz(((2025, 8, 1), 0), ((2026, 8, 1), 1900), ((2026, 9, 1), 2000))
    r = szamol(f, TAR, date(2026, 8, 1), date(2026, 9, 1), [s])
    x = r.szeletek[0]
    assert x.keret == D(63645) and x.piaci == 0 and x.kedvezmenyes == x.elszamolt


def test_eves_keret_evforduloja_honap_kozepen():
    assert eves_keret_kezdete(date(2025, 8, 15), date(2026, 8, 14)) == date(2025, 8, 15)
    assert eves_keret_kezdete(date(2025, 8, 15), date(2027, 9, 1)) == date(2027, 8, 15)
    assert eves_keret_kezdete(date(2024, 2, 29), date(2025, 3, 1)) == date(2025, 2, 28)
    f = Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/lakossagi", date(2024, 1, 1))], [Csatorna()],
             eves_bazis=date(2025, 8, 15), reszszamlas=True)
    s = _sz(((2025, 8, 15), 0), ((2026, 8, 15), 1900), ((2026, 9, 1), 2000))
    r = szamol(f, TAR, date(2026, 8, 1), date(2026, 9, 1), [s])
    uj = next(x for x in r.szeletek if x.tol == date(2026, 8, 15))  # az évfordulón szelethatár
    assert uj.keret == D(63645) and uj.piaci == 0


# 8. Valódi leolvasás a beépítés napján, üresen hagyott kezdőállással
def test_beepites_napi_leolvasas_a_kezdoallas():
    m = Mero("x", date(2026, 10, 1), leolvasasok=[Leolvasas(date(2026, 10, 1), D(12345)),
                                                  Leolvasas(date(2026, 10, 31), D(12545))])
    c = Csatorna(merok=[m])
    s = Szamlalo.csatornabol(c)
    assert s.fogyasztas(datetime(2026, 10, 1), datetime(2026, 10, 31))[0] == D(200)
    assert kijelzett_allas(c, s.ertek(datetime(2026, 10, 31))[0]) == D(12545)


# 9. Sziget: „nan” / „inf” ismeretlen érték
def test_sziget_nem_veges_ertek_ismeretlen():
    sz, esemenyek = szamlalo_sorozatbol([(datetime(2026, 1, 1), "1"), (datetime(2026, 1, 2), "nan"),
                                         (datetime(2026, 1, 3), "inf"), (datetime(2026, 1, 4), "3")])
    assert [e.tipus for e in esemenyek] == ["ismeretlen", "ismeretlen"]
    assert sz.fogyasztas(datetime(2026, 1, 1), datetime(2026, 1, 4))[0] == D(2)
