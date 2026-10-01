"""Számla-beolvasás és -rögzítés (szintetikus, anonimizált minták; HA nélkül)."""

from datetime import date
from decimal import Decimal as D

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from szamla_import import IMPORT_VERZIO, rogzit, ujraertekel
from szamlak import dakov_szoveg, mohu_xml, mvm_xml

MVM_GAZ = """<?xml version="1.0" encoding="UTF-8"?><szamla szlaszam="111"><fejlec><szamlainfo>
<szlanev>részszámla</szlanev><szlaszam>111</szlaszam><szlakelte>2026.08.24</szlakelte>
<szolgaltatas>Földgáz egyetemes szolgáltatás és földgázelosztás</szolgaltatas>
<elsz_kezdete>2026.07.15</elsz_kezdete><elsz_vege>2026.08.13</elsz_vege></szamlainfo></fejlec>
<fogyhely><tetel index="1"><mero_gyartasi_szama>M1</mero_gyartasi_szama><elszamolasi_idoszak_kezdete>2026.07.15</elszamolasi_idoszak_kezdete>
<elszamolasi_idoszak_vege>2026.07.31</elszamolasi_idoszak_vege><futoertek>34,6100000000</futoertek></tetel>
<tetel index="2"><mero_gyartasi_szama>M1</mero_gyartasi_szama><elszamolasi_idoszak_kezdete>2026.08.01</elszamolasi_idoszak_kezdete>
<elszamolasi_idoszak_vege>2026.08.13</elszamolasi_idoszak_vege><futoertek>34,5</futoertek></tetel></fogyhely>
<osszesites><sor_megnevezes_szoveg>Fizetendő összeg összesen</sor_megnevezes_szoveg><brutto_osszeg>11185</brutto_osszeg></osszesites></szamla>"""

MVM_ARAM = """<?xml version="1.0" encoding="UTF-8"?><szamla><fejlec><szamlainfo>
<szlanev>Villamos energia elszámoló számla</szlanev><szlaszam>222</szlaszam><szlakelte>2025.10.10</szlakelte>
<szolgaltatas>Villamos energia egyetemes szolgáltatás</szolgaltatas><elsz_kezdete>2025.09.01</elsz_kezdete><elsz_vege>2025.09.30</elsz_vege>
</szamlainfo></fejlec><fogyhely><tetel index="1"><mero_gyartasi_szama>0035001</mero_gyartasi_szama>
<elszamolasi_idoszak_kezdete>2025.09.01</elszamolasi_idoszak_kezdete><elszamolasi_idoszak_vege>2025.09.30</elszamolasi_idoszak_vege>
<indulo_meroallas>15900</indulo_meroallas><zaro_meroallas>16210</zaro_meroallas><lm_megnevezes>Leol.</lm_megnevezes></tetel>
<tetel index="2"><mero_gyartasi_szama>41002</mero_gyartasi_szama><elszamolasi_idoszak_vege>2025.09.30</elszamolasi_idoszak_vege>
<zaro_meroallas>20</zaro_meroallas><lm_megnevezes>Becs</lm_megnevezes></tetel></fogyhely>
<osszesites><sor_megnevezes_szoveg>Fizetendő összeg</sor_megnevezes_szoveg><brutto_osszeg>-1200</brutto_osszeg></osszesites></szamla>"""

DAKOV = """ Víziközmű-szolgáltatás elszámoló számla  DAKÖV
 Fizetendő összeg: 11 202 Ft
 Számla sorszáma: 9128X   Számla kelte: 2026.08.04
 21-086530 számú vízmérőn 2026.05.31-2026.07.15 106-117 11 m3 269,52 Ft/m3 2 964,72 27 3 765,19
 1106871 számú vízmérőn 2026.05.31-2026.07.15 793-812 19 m3 269,52 Ft/m3 5 120,88 27 6 503,52
 Leolvasás módja (LM) jelen számlában: Leol
"""

MOHU = """<?xml version="1.0" encoding="UTF-8"?><szamla><fejlec><szlasorszam>333</szlasorszam><szladatum>2026.07.08</szladatum>
<elszam_ido_tol>2026.07.01</elszam_ido_tol><elszam_ido_ig>2026.09.30</elszam_ido_ig></fejlec><osszesites><szla_fizetendo>5772</szla_fizetendo></osszesites></szamla>"""


def test_mvm_gaz_xml():
    sz = mvm_xml(MVM_GAZ.encode())
    assert (sz.forras, sz.sorszam, sz.kelte, sz.osszeg, sz.tipus) == ("mvm_gaz", "111", date(2026, 8, 24), D(11185), "resz")
    assert sz.futoertekek == {"2026-07": D("34.6100000000"), "2026-08": D("34.5")}


def test_mvm_aram_xml_leolvasott_es_becsult():
    sz = mvm_xml(MVM_ARAM.encode())
    assert sz.tipus == "elszamolo" and sz.osszeg == D(-1200)
    valodi = [m for m in sz.meroallasok if m.valodi]
    assert {(m.mero, m.datum, m.allas) for m in valodi} == {("35001", date(2025, 9, 1), D(15900)), ("35001", date(2025, 9, 30), D(16210))}
    assert not [m for m in sz.meroallasok if m.mero == "41002" and m.valodi]  # becsült: kimarad


def test_dakov_szoveg():
    sz = dakov_szoveg(DAKOV)
    assert (sz.sorszam, sz.kelte, sz.osszeg, sz.tipus) == ("9128X", date(2026, 8, 4), D(11202), "elszamolo")
    assert {(m.mero, m.datum, m.allas) for m in sz.meroallasok if m.datum == date(2026, 7, 15)} == {("21-086530", date(2026, 7, 15), D(117)), ("1106871", date(2026, 7, 15), D(812))}


def test_mohu_xml():
    sz = mohu_xml(MOHU.encode())
    assert (sz.forras, sz.sorszam, sz.osszeg, sz.idoszak) == ("mohu", "333", D(5772), (date(2026, 7, 1), date(2026, 9, 30)))


def _tarolt():
    return {
        "merok": [{"gyari_szam": "", "beepitve": "2025-01-01", "kezdo_allas": "15000", "kiszerelve": None, "zaro_allas": None, "leolvasasok": []}],
        "almero_merok": [], "feluliras": [], "lezart": [], "reszszamlak": [],
    }


def test_rogzit_meroszammal_es_duplikacio_nelkul():
    t = _tarolt()
    sz = mvm_xml(MVM_ARAM.encode())
    j = rogzit(t, [sz], {"0035001"})
    assert j.szamlak == ["222"] and j.leolvasasok == 2
    assert t["merok"][0]["gyari_szam"] == "35001"  # a szám nélküli mérő átvette a számot
    lo = t["merok"][0]["leolvasasok"][-1]
    assert (lo["allas"], lo["tipus"], lo["elszamolasi"]) == ("16210", "szolgaltatoi", True)
    assert t["reszszamlak"] == [{"datum": "2025-10-10", "osszeg": "-1200", "sorszam": "222", "megjegyzes": "mvm_aram elszamolo ()"}]
    assert rogzit(t, [sz], {"0035001"}).szamlak == []  # másodszor nem


def test_rogzit_mas_fiok_szamlaja_kimarad():
    t = _tarolt()
    assert rogzit(t, [mvm_xml(MVM_ARAM.encode())], {"99999"}).szamlak == []


def test_rogzit_futoertek_nem_irja_felul_a_kezit():
    t = _tarolt() | {"futoertekek": {"2026-07": "35.00"}}
    j = rogzit(t, [mvm_xml(MVM_GAZ.encode())])
    assert t["futoertekek"] == {"2026-07": "35.00", "2026-08": "34.5"} and j.futoertekek == 1


def test_rogzit_ellentmondo_allas_kimarad():
    t = _tarolt()
    t["merok"][0]["leolvasasok"].append({"datum": "2025-10-15", "allas": "16000", "tipus": "kezi"})
    j = rogzit(t, [mvm_xml(MVM_ARAM.encode())])
    assert j.kihagyott_ellentmondas == 1  # 09-30-i 16 210 > 10-15-i 16 000


MVM_GAZ_ELSZAMOLO = """<?xml version="1.0" encoding="UTF-8"?><szamla><fejlec><szamlainfo>
<szlanev>Földgáz elszámoló számla</szlanev><szlaszam>444</szlaszam><szlakelte>2026.07.27</szlakelte>
<szolgaltatas>Földgáz egyetemes szolgáltatás</szolgaltatas><elsz_kezdete>2025.07.12</elsz_kezdete><elsz_vege>2026.07.14</elsz_vege>
</szamlainfo></fejlec><fogyhely>
<tetel index="1"><mero_gyartasi_szama>M1</mero_gyartasi_szama><elszamolasi_idoszak_kezdete>2025.07.12</elszamolasi_idoszak_kezdete>
<elszamolasi_idoszak_vege>2026.02.01</elszamolasi_idoszak_vege><indulo_meroallas>7410</indulo_meroallas><zaro_meroallas>8224</zaro_meroallas><lm_kod>Leol</lm_kod></tetel>
<tetel index="2"><mero_gyartasi_szama>M1</mero_gyartasi_szama><elszamolasi_idoszak_kezdete>2026.02.02</elszamolasi_idoszak_kezdete>
<elszamolasi_idoszak_vege>2026.07.14</elszamolasi_idoszak_vege><indulo_meroallas>8224</indulo_meroallas><zaro_meroallas>8668</zaro_meroallas><lm_kod>Leol</lm_kod></tetel>
</fogyhely><osszesites><sor_megnevezes_szoveg>Fizetendő összeg</sor_megnevezes_szoveg><brutto_osszeg>556</brutto_osszeg></osszesites></szamla>"""


def test_eves_szamla_kozbenso_szamitott_allasa_kimarad():
    t = _tarolt()
    t["merok"][0]["beepitve"] = "2025-01-01"
    t["merok"][0]["kezdo_allas"] = "7000"
    j = rogzit(t, [mvm_xml(MVM_GAZ_ELSZAMOLO.encode())])
    datumok = {(lo["datum"], lo["elszamolasi"]) for lo in t["merok"][0]["leolvasasok"]}
    assert datumok == {("2025-07-12", False), ("2026-07-14", True)}  # a febr. 1-jei számított bontás kimaradt
    assert j.kihagyott_szamitott == 2


def test_ujraertekel_regi_importot():
    t = _tarolt()
    t["merok"][0]["leolvasasok"] = [
        {"datum": "2026-02-01", "allas": "8224", "elszamolasi": True, "megjegyzes": "számla 444 (Leol)"},
        {"datum": "2025-07-12", "allas": "7410", "elszamolasi": True, "megjegyzes": "számla 444 (Leol)"},
        {"datum": "2025-07-11", "allas": "7410", "elszamolasi": True, "megjegyzes": "v1 éves leolvasás"},
    ]
    db = ujraertekel(t, [mvm_xml(MVM_GAZ_ELSZAMOLO.encode())])
    assert db == 2 and t["szamla_import_verzio"] == IMPORT_VERZIO
    assert [(lo["datum"], lo["elszamolasi"]) for lo in t["merok"][0]["leolvasasok"]] == [("2025-07-12", False), ("2025-07-11", True)]


def test_szamla_meta_idoszak_es_valodi_allas():
    from szamla_import import szamla_meta
    m = szamla_meta(mvm_xml(MVM_GAZ_ELSZAMOLO.encode()))
    assert m["idoszak"] == ["2025-07-12", "2026-07-14"] and m["utolso_valodi_allas"] == "2026-07-14" and m["tipus"] == "elszamolo"


def test_szamla_statisztika_negyedeves():
    from szamla_import import szamla_statisztika
    t = {"szamlak": {str(i): {"kelte": k, "osszeg": "5772"} for i, k in enumerate(
        ["2025-10-10", "2026-01-14", "2026-04-15", "2026-07-08"])}}
    st = szamla_statisztika(t, date(2026, 10, 1))
    assert st["eves_osszeg"] == 4 * 5772 and st["kovetkezo_osszeg"] == 5772
    assert st["idokoz_nap"] == 91 and st["kovetkezo_datum"] == date(2026, 10, 7) and st["figyelmeztetes"] is None
    t["szamlak"]["9"] = {"kelte": "2026-10-09", "osszeg": "6100"}
    assert "díjváltozás" in szamla_statisztika(t, date(2026, 10, 10), fix_dij=True)["figyelmeztetes"]
    assert szamla_statisztika(t, date(2026, 10, 10))["figyelmeztetes"] is None  # változó számlánál nem zaj
    assert "elmaradt" in szamla_statisztika({"szamlak": {k: v for k, v in t["szamlak"].items() if k != "9"}}, date(2026, 11, 15))["figyelmeztetes"]


def test_atalany_napra_leosztva():
    from datetime import datetime
    from szamla_import import atalany_szamitas
    t = {"szamlak": {
        "1": {"kelte": "2026-07-27", "osszeg": "556", "tipus": "elszamolo", "idoszak": ["2025-07-12", "2026-07-14"]},
        "2": {"kelte": "2026-08-24", "osszeg": "11185", "tipus": "resz", "idoszak": ["2026-07-15", "2026-08-13"]},
    }}
    a = atalany_szamitas(None, t, date(2026, 10, 1), date(2026, 11, 1), datetime(2026, 10, 10, 12))
    assert a["napi"] == round(11185 / 30, 2) and a["havi"] == round(11185 / 30 * 31) and a["eltelt_nap"] == 10
    b = atalany_szamitas(12000, t, date(2026, 10, 1), date(2026, 11, 1), datetime(2026, 10, 10, 12))
    assert b["havi"] == round(12000 * 12 / 365 * 31) and "beállított" in b["forras"]


def test_esedekes_ketthavi_es_negyedeves():
    from decimal import Decimal as D2
    from szamla_import import esedekes
    viz = {"szamlak": {"a": {"kelte": "2026-06-02", "osszeg": "24616"}, "b": {"kelte": "2026-08-04", "osszeg": "11202"}}}
    e = esedekes(viz, date(2026, 10, 1), 2, D2(13000))
    assert e["kovetkezo_datum"] == date(2026, 10, 4) and e["e_havi_varhato"] == 13000 and e["e_havi_osszesen"] == 13000
    assert esedekes(viz, date(2026, 11, 1), 2, D2(13000)) is not None
    mohu = {"szamlak": {"1": {"kelte": "2026-04-15", "osszeg": "5772"}, "2": {"kelte": "2026-07-08", "osszeg": "5772"}}}
    m = esedekes(mohu, date(2026, 10, 1), 3, D2(5772))
    assert m["kovetkezo_datum"] == date(2026, 10, 8) and m["e_havi_osszesen"] == 5772
    assert esedekes(mohu, date(2026, 11, 2), 3, D2(5772))["e_havi_osszesen"] == 5772  # késik: még várható
    mohu["szamlak"]["3"] = {"kelte": "2026-10-09", "osszeg": "5772"}
    n = esedekes(mohu, date(2026, 11, 2), 3, D2(5772))
    assert n["e_havi_osszesen"] == 0 and n["kovetkezo_datum"] == date(2027, 1, 9)  # novemberben nincs számla
