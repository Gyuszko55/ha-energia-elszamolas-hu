"""Számla-beolvasás és -rögzítés (szintetikus, anonimizált minták; HA nélkül)."""

from datetime import date
from decimal import Decimal as D

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from szamla_import import IMPORT_VERZIO, esedekes, hozzatartozik, kezi_szamla, mappas_adatok_torlese, rogzit, szamla_torles, szamlazasi_ablak, ujraertekel
from szamlak import dakov_szoveg, mohu_xml, mvm_aram_szoveg, mvm_atalany, mvm_xml
from motor.elorejelzes import idoszak

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
 21-000001 számú vízmérőn 2026.05.31-2026.07.15 106-117 11 m3 269,52 Ft/m3 2 964,72 27 3 765,19
 9000001 számú vízmérőn 2026.05.31-2026.07.15 793-812 19 m3 269,52 Ft/m3 5 120,88 27 6 503,52
 Leolvasás módja (LM) jelen számlában: Leol
"""

MOHU = """<?xml version="1.0" encoding="UTF-8"?><szamla><fejlec><szlasorszam>333</szlasorszam><szladatum>2026.07.08</szladatum>
<elszam_ido_tol>2026.07.01</elszam_ido_tol><elszam_ido_ig>2026.09.30</elszam_ido_ig></fejlec><osszesites><szla_fizetendo>5772</szla_fizetendo></osszesites>
<fizetes><fiz_hatarido>2026.07.31</fiz_hatarido><fiz_mod>Csoportos beszedési megbízás (Dí</fiz_mod></fizetes></szamla>"""


def test_mvm_gaz_xml():
    sz = mvm_xml(MVM_GAZ.encode())
    assert (sz.forras, sz.sorszam, sz.kelte, sz.osszeg, sz.tipus) == ("mvm_gaz", "111", date(2026, 8, 24), D(11185), "resz")
    assert sz.futoertekek == {"2026-07": D("34.6100000000"), "2026-08": D("34.5")}


def test_mvm_gaz_xml_tamogatas_tulfizetes():
    """Gáz-részszámla: a „Támogatás, túlfizetés” sor (egy korábbi elszámoló jóváírása) egyéb tétel, a számlaérték bruttó."""
    xml = MVM_GAZ.replace(
        "<osszesites><sor_megnevezes_szoveg>Fizetendő összeg összesen</sor_megnevezes_szoveg><brutto_osszeg>11185</brutto_osszeg>",
        "<osszesites><sor_megnevezes_szoveg>Kerekítés</sor_megnevezes_szoveg><brutto_osszeg>0</brutto_osszeg></osszesites>"
        "<osszesites><sor_megnevezes_szoveg>Bruttó számlaérték összesen**</sor_megnevezes_szoveg><brutto_osszeg>11642</brutto_osszeg></osszesites>"
        "<osszesites><sor_megnevezes_szoveg>Támogatás, túlfizetés:</sor_megnevezes_szoveg><brutto_osszeg>-8835</brutto_osszeg></osszesites>"
        "<osszesites><sor_megnevezes_szoveg>Fizetendő összeg összesen</sor_megnevezes_szoveg><brutto_osszeg>2807</brutto_osszeg>")
    sz = mvm_xml(xml.encode())
    assert (sz.osszeg, sz.szamlaertek) == (2807, 11642)
    assert sz.egyeb_tetelek == [("Támogatás, túlfizetés", -8835)]
    assert mvm_xml(MVM_GAZ.encode()).egyeb_tetelek == []


def test_dakov_hatarido_es_folyoszamla_egyenleg():
    sz = dakov_szoveg(DAKOV + " Fizetési határidő: 2026.08.24\n A nyilvántartás szerint a folyószámla egyenlege a számla kibocsátásakor 3 093 Ft.\n")
    assert sz.hatarido == date(2026, 8, 24) and sz.folyoszamla == 3093


def test_mvm_aram_xml_leolvasott_es_becsult():
    sz = mvm_xml(MVM_ARAM.encode())
    assert sz.tipus == "elszamolo" and sz.osszeg == D(-1200)
    valodi = [m for m in sz.meroallasok if m.valodi]
    assert {(m.mero, m.datum, m.allas) for m in valodi} == {("35001", date(2025, 9, 1), D(15900)), ("35001", date(2025, 9, 30), D(16210))}
    assert not [m for m in sz.meroallasok if m.mero == "41002" and m.valodi]  # becsült: kimarad


def test_dakov_szoveg():
    sz = dakov_szoveg(DAKOV)
    assert (sz.sorszam, sz.kelte, sz.osszeg, sz.tipus) == ("9128X", date(2026, 8, 4), D(11202), "elszamolo")
    assert {(m.mero, m.datum, m.allas) for m in sz.meroallasok if m.datum == date(2026, 7, 15)} == {("21-000001", date(2026, 7, 15), D(117)), ("9000001", date(2026, 7, 15), D(812))}


def test_mohu_xml():
    sz = mohu_xml(MOHU.encode())
    assert (sz.forras, sz.sorszam, sz.osszeg, sz.idoszak) == ("mohu", "333", D(5772), (date(2026, 7, 1), date(2026, 9, 30)))
    # a határidő és a fizetési mód kell, különben a számla kimarad a kifizetetlenek közül
    assert (sz.hatarido, sz.fizetesi_mod) == (date(2026, 7, 31), "Csoportos beszedési megbízás (Dí")


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


MVM_ARAM_PDF_H = """Szolgáltató neve: MVM Next Energiakereskedelmi Zrt.
Villamos energia elszámoló számla
Számla sorszáma: 333
Elszámolási időszak: 2026.02.03-2026.08.08
Számla kelte: 2026.08.31
Fizetendő összeg:-25.522 Ft
Fogyasztás összesen: "H" 823 kWh
Mérési pont azonosító: HU000TESZT "H"
00000000000000012026.02.03-2026.08.080 474Dikt474 1 474
00000000000000012026.02.03-2026.08.080 349Dikt349 1 349
Bruttó számlaérték összesen 22.607
"""


def test_mvm_aram_pdf_ket_regiszter_osszege():
    # A H-mérő két regisztere (téli/nyári) egy-egy sor: a sorrend nem egyértelmű, az összegüket vesszük át.
    sz = mvm_aram_szoveg(MVM_ARAM_PDF_H, "x.pdf")
    # A fizetendő (részszámlák és túlfizetés levonása után, itt visszajár), nem a bruttó számlaérték.
    assert sz.tipus == "elszamolo" and sz.osszeg == D(-25522)
    allasok = {(m.datum, m.allas, m.valodi) for m in sz.meroallasok}
    assert allasok == {(date(2026, 8, 8), D(823), True), (date(2026, 2, 3), D(0), True)}


def test_mvm_aram_pdf_storno():
    """MVM stornó PDF (Kertes ház H, 845100000001): a fejléc csak „Sztornó számla”; a sztornózott számla sorszáma, az
    érték −991, fizetendő nincs (a fejléc „47 138” a közös egyenleg), mérőállás nem rögzül."""
    t = MVM_ARAM_PDF_H.replace("Villamos energia elszámoló számla", "Sztornó számla").replace(
        "Számla kelte: 2026.08.31", "Számla kelte: 2026.08.27\nSztornózott számla sorszáma: 222\nVillamos energia egyetemes szolgáltatás").replace(
        "Bruttó számlaérték összesen 22.607", "Bruttó számlaérték összesen -991")
    sz = mvm_aram_szoveg(t, "x.pdf")
    assert sz.tipus == "storno" and sz.sztornozott == "222" and sz.osszeg == 0 and sz.szamlaertek == D(-991)
    assert not sz.meroallasok


def test_rogzit_szamlahatar_nem_duplikal():
    # Az előző számla záró állása (szept. 30.) a következő számlán induló állásként (okt. 1.) ugyanaz a leolvasás.
    t = _tarolt()
    rogzit(t, [mvm_xml(MVM_ARAM.encode())], {"0035001"})
    kov = mvm_xml(MVM_ARAM.encode())
    kov.sorszam = "223"
    for ma in kov.meroallasok:
        if ma.allas == D(16210):
            ma.datum = date(2025, 10, 1)
    rogzit(t, [kov], {"0035001"})
    assert [lo["allas"] for lo in t["merok"][0]["leolvasasok"] if lo["allas"] == "16210"] == ["16210"]


def _szamlak(*kelte_osszeg):
    return {"szamlak": {str(i): {"kelte": k, "osszeg": o} for i, (k, o) in enumerate(kelte_osszeg)}}


def test_szamlazasi_ablak_viz_utolagos_kethavi():
    t = _szamlak(("2026-06-02", 24616), ("2026-08-04", 11202))
    # Októberben számláz: az aug.–szept. időszakot (lezárt), napi átalánnyal.
    es = esedekes(t, date(2026, 10, 1), 2, D(16064))
    a = szamlazasi_ablak(date(2026, 10, 1), 2, es, D("263.4"))
    assert (a["tol"], a["ig"], a["lezart"], a["esedekes_most"], a["kiallitott"]) == (date(2026, 8, 1), date(2026, 10, 1), True, True, False)
    assert a["fizetendo"] == round(D("263.4") * 61) and a["szamla_datum"] == "2026-10-04"
    # Novemberben nincs számla: a folyó okt.–nov. időszak (a decemberi számla), nem esedékes.
    t["szamlak"]["9"] = {"kelte": "2026-10-04", "osszeg": 16000}
    es = esedekes(t, date(2026, 11, 10), 2, D(16064))
    a = szamlazasi_ablak(date(2026, 11, 10), 2, es, D("263.4"))
    assert (a["tol"], a["ig"], a["lezart"], a["esedekes_most"]) == (date(2026, 10, 1), date(2026, 12, 1), False, False)
    assert a["eltelt_nap"] == 41


def test_szamlazasi_ablak_kiallitott_szamla_osszege():
    t = _szamlak(("2026-08-04", 11202), ("2026-10-04", 15000))
    es = esedekes(t, date(2026, 10, 20), 2, D(16064))
    a = szamlazasi_ablak(date(2026, 10, 20), 2, es, D("263.4"))
    assert a["kiallitott"] and a["fizetendo"] == 15000 and a["szamla_datum"] == "2026-10-04"


def test_szamlazasi_ablak_mohu_negyedev_utolag():
    t = _szamlak(("2026-04-15", 5772), ("2026-07-08", 5772))
    es = esedekes(t, date(2026, 10, 1), 3, D(5772))
    a = szamlazasi_ablak(date(2026, 10, 1), 3, es)
    assert (a["tol"], a["ig"], a["lezart"], a["fizetendo"]) == (date(2026, 7, 1), date(2026, 10, 1), True, 5772)


def test_szamlazasi_ablak_havi_nincs():
    assert szamlazasi_ablak(date(2026, 10, 1), 1, {"e_havi_osszesen": 1}) is None


def test_kezi_szamla_rogzites_es_torles():
    t = _tarolt()
    t["merok"][0]["gyari_szam"] = "35001"
    sz = kezi_szamla(t, date(2025, 10, 10), D(12000), "elszamolo", idoszak=(date(2025, 9, 1), date(2025, 9, 30)),
                     zaro_allas=D(16210), leolvasott=True)
    assert sz.sorszam == "kezi-2025-10-10-1"
    j = rogzit(t, [sz])
    assert j.szamlak == ["kezi-2025-10-10-1"] and j.leolvasasok == 1
    lo = t["merok"][0]["leolvasasok"][0]
    assert (lo["datum"], lo["allas"], lo["tipus"], lo["elszamolasi"]) == ("2025-09-30", "16210", "szolgaltatoi", True)
    assert t["reszszamlak"][0]["sorszam"] == "kezi-2025-10-10-1"
    # második kézi számla ugyanarra a napra: új sorszám
    assert kezi_szamla(t, date(2025, 10, 10), D(1)).sorszam == "kezi-2025-10-10-2"
    assert szamla_torles(t, "kezi-2025-10-10-1")
    assert t["szamlak"] == {} and t["reszszamlak"] == [] and t["merok"][0]["leolvasasok"] == []
    assert not szamla_torles(t, "nincs")


def test_kezi_szamla_futoertek_honapokra():
    sz = kezi_szamla(_tarolt(), date(2026, 9, 24), D(11185), idoszak=(date(2026, 8, 14), date(2026, 9, 13)), futoertek=D("34.6"))
    assert sz.futoertekek == {"2026-08": D("34.6"), "2026-09": D("34.6")}


def test_mvm_aram_pdf_fizetendo_nelkul_brutto():
    sz = mvm_aram_szoveg(MVM_ARAM_PDF_H.replace("Fizetendő összeg:-25.522 Ft\n", ""), "x.pdf")
    assert sz.osszeg == D(22607)


def test_diktalasi_idoszak():
    # Határ = a diktálás napja: [előző diktálás, diktálás) – a számlán „előző diktálás másnapja – diktálás napja”.
    h = [date(2026, 4, 10), date(2026, 8, 8), date(2026, 9, 9)]
    assert idoszak(date(2026, 9, 8), "diktalas", 1, h) == (date(2026, 8, 8), date(2026, 9, 9))
    assert idoszak(date(2026, 9, 9), "diktalas", 1, h) == (date(2026, 9, 9), date(2026, 10, 9))
    # Újabb diktálás/számla nélkül havonta új időszak (az évente leolvasott, havonta részszámlás fióknál is).
    assert idoszak(date(2026, 11, 20), "diktalas", 1, h) == (date(2026, 11, 9), date(2026, 12, 9))
    assert idoszak(date(2026, 10, 2), "diktalas", 1, [date(2026, 1, 16)]) == (date(2026, 9, 16), date(2026, 10, 16))
    # Távleolvasás: naptári hónap.
    assert idoszak(date(2026, 10, 2), "naptari_honap") == (date(2026, 10, 1), date(2026, 11, 1))


def test_mvm_atalany_a_szamlarol():
    assert mvm_atalany("A következő részszámla becsült mennyisége: 24 órás 293 kWh") == D(293)
    assert mvm_atalany("A következő részszámla becsült mennyisége: Vezérelt 23 kWh") == D(23)
    assert mvm_atalany("A következő részszámla becsült mennyisége: 24 órás 1.150 kWh, Vezérelt 23 kWh") == D(1173)
    assert mvm_atalany("nincs ilyen sor") is None
    sz = mvm_aram_szoveg(MVM_ARAM_PDF_H + "A következő részszámla becsült mennyisége: Vezérelt 23 kWh\n", "x.pdf")
    assert sz.atalany_mennyiseg == D(23)


def test_diktalasi_ablak_szerinti_hatar():
    # Diktálás 09-09-én: az időszak [08-08, 09-09) – a számlán 08-09 – 09-09 (32 nap).
    h = [date(2026, 8, 8), date(2026, 9, 9)]
    # Diktálás nélkül a következő az ablak (minden hónap 8–14.) utolsó napján zárul: [09-09, 10-14).
    assert idoszak(date(2026, 10, 2), "diktalas", 1, h, (8, 14)) == (date(2026, 9, 9), date(2026, 10, 14))
    # Ha 10-11-én diktál (és jelöli), az a határ.
    assert idoszak(date(2026, 10, 2), "diktalas", 1, h + [date(2026, 10, 11)], (8, 14)) == (date(2026, 9, 9), date(2026, 10, 11))
    # 20 napnál rövidebb időszak nem lehet: 09-09 után nem szeptember 14., hanem október 14.
    assert idoszak(date(2026, 9, 12), "diktalas", 1, h, (8, 14)) == (date(2026, 9, 9), date(2026, 10, 14))


def test_mvm_diktalasi_ablak():
    from szamlak import mvm_diktalasi_ablak
    assert mvm_diktalasi_ablak("Következő diktálási időszak: Minden hónap 08-14 között     ") == (8, 14)
    assert mvm_diktalasi_ablak("nincs") is None


def test_arszabas_szerinti_valogatas():
    sz_a1 = mvm_aram_szoveg(MVM_ARAM_PDF_H.replace('"H" 823', '"A1" 61') + 'Árszabás: ESZ "A1" Lakosság\n', "a.pdf")
    sz_h = mvm_aram_szoveg(MVM_ARAM_PDF_H + 'Árszabás: ESZ "H" Lakosság\n', "h.pdf")
    assert (sz_a1.arszabas, sz_h.arszabas) == ("A1", "H")
    # Üres számla-mérők: a fiók díjszabása (A1/H) dönt; megadott számla-mérők: azok döntenek.
    assert hozzatartozik(sz_a1, set(), "A1") and not hozzatartozik(sz_h, set(), "A1")
    assert hozzatartozik(sz_h, set(), "H") and not hozzatartozik(sz_a1, set(), "H")
    assert hozzatartozik(sz_h, {"1"}, "A1")  # a gyári szám (0…01 → 1) erősebb az árszabásnál
    assert hozzatartozik(sz_h, set(), None)  # se szűrő, se díjszabás: minden számla


def test_kezdonap_elotti_allas_ertheto_figyelmeztetessel():
    t = _tarolt()
    t["merok"][0]["beepitve"] = "2026-10-02"
    j = rogzit(t, [mvm_xml(MVM_ARAM.encode())])
    assert j.leolvasasok == 0 and len(j.kezdonap_elotti) == 2 and not j.ismeretlen_merok
    assert "kezdőnapja (2026-10-02) előtti" in j.figyelmeztetesek[0]


def test_mappas_adatok_torlese_a_kezit_megtartja():
    t = _tarolt()
    t["merok"][0]["gyari_szam"] = "35001"
    rogzit(t, [mvm_xml(MVM_ARAM.encode())])
    k = kezi_szamla(t, date(2025, 11, 10), D(5000), idoszak=(date(2025, 10, 1), date(2025, 10, 31)), zaro_allas=D(16500))
    rogzit(t, [k]); t["szamlak"][k.sorszam]["kezi"] = True
    t["feldolgozott_fajlok"] = ["x.xml"]
    mappas_adatok_torlese(t)
    assert list(t["szamlak"]) == [k.sorszam] and t["feldolgozott_fajlok"] == []
    assert [r["sorszam"] for r in t["reszszamlak"]] == [k.sorszam]
    assert [lo["allas"] for lo in t["merok"][0]["leolvasasok"]] == ["16500"]


MVM_VEGSZAMLA = """VÉGSZÁMLA
Számla sorszáma: 444
Szolgáltató neve: MVM Next Energiakereskedelmi Zrt.
Elszámolási időszak: 2025.10.15 -  2025.11.15.
Fizetendő összeg: 1 336 Ft
Villamos energia egyetemes szolgáltatás
Számla kelte: 2026.01.16
Árszabás: lakossági Elosztói engedélyes: MVM Démász Áramhálózati Kft.
000000000000000001 2025.10.15-2025.11.15 1 458 1 458 Leol. 0 1 0
000000000000000001 2025.10.15-2025.11.15 2 930 2 986 Leol. 56 1 56
ESZ Lakossági H kedv. téli 2025.10.15-2025.11.15 56,00 kWh 1,9000 Ft/kWh 106 27 135
Bruttó számlaérték összesen** 1 336
Következő részszámla becsült mennyisége: 106 KWH
"""


def test_mvm_vegszamla():
    # Más nyomtató: „VÉGSZÁMLA” fejléc, szóközzel tagolt számok, 18 jegyű (vezető nullás) gyári szám.
    sz = mvm_aram_szoveg(MVM_VEGSZAMLA, "v.pdf")
    assert (sz.sorszam, sz.tipus, sz.osszeg, sz.arszabas, sz.atalany_mennyiseg) == ("444", "elszamolo", D(1336), "H", D(106))
    assert sz.idoszak == (date(2025, 10, 15), date(2025, 11, 15))
    assert {(m.mero, m.datum, m.allas) for m in sz.meroallasok} == {("1", date(2025, 11, 15), D(4444)), ("1", date(2025, 10, 15), D(4388))}


def test_b_tarifa_dija_a_szamla_szerint():
    # 845100000003 (ELMŰ, „B Alap”): 315 + 252 kWh, energiadíj 2,05, rendszerhasználati 16,18 Ft/kWh nettó; a fogyasztás
    # a keret alatt maradt. A vezérelt mérőnek saját 2523 kWh kerete van, felette piaci ár (bruttó 60,935 Ft/kWh).
    import yaml, pathlib
    d = yaml.safe_load((pathlib.Path(__file__).parents[1] / "custom_components/hu_rezsi/dijszabasok/villany/b.yaml").read_text())
    v = d["verziok"][0]
    k = v["szabalyok"]["keret"]
    assert (k["tipus"], k["ev_mennyiseg"], k["osszesitett"]) == ("napi_aranyos", 2523, True)
    a = v["dijak"]["alap"]
    assert round((a["energia_piaci"] + a["rendszerhasznalati"]) * 1.27, 3) == 60.935
    assert a["energia_kedvezmenyes"] == 1.90  # MVM Démász (árlap)
    elmu = v["dijak"]["elmu"]["energia_kedvezmenyes"]  # a számla ELMŰ-területi
    assert round(315 * elmu) == 646 and round(252 * elmu) == 517
    assert round(567 * a["rendszerhasznalati"]) == 9174  # 2662 + 58 + 6237 + 217 a számlán
    assert mvm_aram_szoveg(MVM_ARAM_PDF_H.replace('"H" 823', '"B Alap" 567') + 'Árszabás: ESZ "B Alap" Lakosság\n', "b.pdf").arszabas == "B"


MVM_ARAM_PDF_EVHATAR = """Szolgáltató neve: MVM Next Energiakereskedelmi Zrt.
Villamos energia elszámoló számla
Számla sorszáma: 444
Elszámolási időszak: 2026.04.11-2026.08.08
Számla kelte: 2026.08.17
Fizetendő összeg:-48.129 Ft
Mérési pont azonosító: HU000TESZT "A1"
35000000000000012026.04.11-2026.07.3118.82720.028Dikt1.2011 1.201
35000000000000012026.07.31-2026.08.0820.02820.061Dikt33 1 33
Bruttó számlaérték összesen** -48.129
"""


def test_mvm_aram_pdf_belso_vagas_evhatar():
    # Az időszakon belül kettévált mérősor (07.31): valódi leolvasás, de NEM éves elszámoló (az évhatár az éves
    # leolvasás – a felhasználó szerint a kertes házban szeptember 29.).
    sz = mvm_aram_szoveg(MVM_ARAM_PDF_EVHATAR, "x.pdf")
    assert sz.evhatarok == {date(2026, 7, 31)}
    t = _tarolt()
    t["merok"][0]["gyari_szam"] = "3500000000000001"
    t["merok"][0]["kezdo_allas"] = "18000"
    rogzit(t, [sz], {"3500000000000001"})
    los = {lo["datum"]: (lo["allas"], lo["elszamolasi"]) for lo in t["merok"][0]["leolvasasok"]}
    assert los["2026-07-31"] == ("20028", False)
    assert los["2026-08-08"] == ("20061", False) and los["2026-04-11"] == ("18827", False)


def test_ujraertekel_potolja_az_evhatart():
    # Régebbi importnál a 07.31-i (belső) állás kimaradt: az újraértékelés pótolja, valódi (nem elszámoló) állásként.
    sz = mvm_aram_szoveg(MVM_ARAM_PDF_EVHATAR, "x.pdf")
    t = _tarolt()
    t["merok"][0].update(gyari_szam="3500000000000001", kezdo_allas="18000")
    rogzit(t, [sz], {"3500000000000001"})
    t["merok"][0]["leolvasasok"] = [lo for lo in t["merok"][0]["leolvasasok"] if lo["datum"] != "2026-07-31"]
    assert ujraertekel(t, [sz]) == 1
    assert [(lo["datum"], lo["elszamolasi"]) for lo in t["merok"][0]["leolvasasok"]] == [
        ("2026-04-11", False), ("2026-07-31", False), ("2026-08-08", False)]


def test_dakov_kovetkezo_idopontok_es_elszamolt_mennyiseg():
    """DAKÖV (layout-szöveg): a következő éves leolvasás és diktálás, a számla tetején az elszámolt mennyiség."""
    from szamlak import dakov_idopontok
    t = """Számla sorszáma: 90002LHE26
    Számla kelte: 2026.10.01
    Elszámolt időszak: 2026.08.01-2026.09.30
    Fizetendő összeg: 20 929 Ft
    Víziközmű-szolgáltatás 1. részszámla
    Elszámolt mennyiség: Ivóvíz 28 m3
    Elszámolt mennyiség: Csatorna 22 m3
    100001HB Ivóvíz-szolgáltatás átalánydíj
    Következő diktálás várható időpontja: 2026.11.25-2026.11.30
    Következő leolvasás várható időpontja: 2027.07.01-2027.07.25
    DAKÖV"""
    assert dakov_idopontok(t) == {"diktalas": (date(2026, 11, 25), date(2026, 11, 30)), "leolvasas": (date(2027, 7, 1), date(2027, 7, 25))}
    sz = dakov_szoveg(t, "x.pdf")
    assert (sz.tipus, sz.osszeg, sz.kovetkezo_leolvasas) == ("resz", D(20929), (date(2027, 7, 1), date(2027, 7, 25)))
    assert sz.elszamolt_viz == {"ivoviz": D(28), "csatorna": D(22), "atalany": True, "idoszak": ["2026-08-01", "2026-09-30"]}
    assert dakov_idopontok("Következő mérőállás bejelentés időpontja: 2026.09.25-2026.09.30")["diktalas"] == (date(2026, 9, 25), date(2026, 9, 30))


def test_mvm_kovetkezo_leolvasas():
    """MVM áramszámla: a következő (éves, elosztói) leolvasás időszaka – mindkét nyomtatási formátumban."""
    from szamlak import mvm_kovetkezo_leolvasas
    assert mvm_kovetkezo_leolvasas("Következő leolvasás várható időpontja: 2026.09.22 - 2026.10.09 között") == (date(2026, 9, 22), date(2026, 10, 9))
    assert mvm_kovetkezo_leolvasas("Következő leolvasás várható időpontja: 2026.09.26-2026.10.10") == (date(2026, 9, 26), date(2026, 10, 10))
    assert mvm_kovetkezo_leolvasas("nincs benne") is None


def test_mvm_gaz_mennyisegek():
    from szamlak import mvm_gaz_mennyisegek, mvm_kovetkezo_leolvasas
    t = """Elszámolt mennyiség: 44 694 MJ (1 280,64 m3)
    Következő leolvasás várható időpontja: 2027.07.13.-2027.07.19.
    A következő részszámla becsült mennyisége: 103 m3"""
    assert mvm_gaz_mennyisegek(t) == ({"mj": D(44694), "m3": D("1280.64")}, D(103))
    assert mvm_kovetkezo_leolvasas(t) == (date(2027, 7, 13), date(2027, 7, 19))


def test_mvm_reszszamla_osszeg_a_brutto_szamlaertek():
    """MVM részszámla: a fizetendő a folyószámla egyenlegét is tartalmazhatja; a számla értéke a bruttó számlaérték."""
    t = MVM_ARAM_PDF_EVHATAR.replace("Villamos energia elszámoló számla", "Villamos energia 6. sz. részszámla").replace(
        "Fizetendő összeg:-48.129 Ft", "Fizetendő összeg:-47.138 Ft").replace("Bruttó számlaérték összesen** -48.129", "Bruttó számlaérték összesen** 991")
    assert mvm_aram_szoveg(t, "x.pdf").osszeg == D(991)


def test_leolvasasos_idoszak_ket_leolvasas_kozott():
    from motor.elorejelzes import idoszak as idsz
    from modell import diktalasi_hatarok

    tarolt = {"merok": [{"beepitve": "2026-08-01", "kezdo_allas": "1000", "leolvasasok": [
        {"datum": "2026-09-03", "allas": "1254"}, {"datum": "2026-08-20", "allas": "1100", "csatorna": "betaplalas"}]}],
        "szamlak": {"x": {"idoszak": ["2026-08-05", "2026-09-04"], "tipus": "elszamolo"}}}
    h = diktalasi_hatarok(tarolt, minden_leolvasas=True)
    assert h == [date(2026, 8, 1), date(2026, 9, 3)]  # a számla időszaka és a betáplálás nem határ
    # a lezárt időszak a két leolvasás között; az utolsó után nyitva marad a következő leolvasásig (nincs havi görgetés)
    assert idsz(date(2026, 8, 20), "leolvasas", 1, h) == (date(2026, 8, 1), date(2026, 9, 3))
    assert idsz(date(2026, 10, 4), "leolvasas", 1, h) == (date(2026, 9, 3), date(2026, 11, 3))
    assert idsz(date(2026, 10, 4), "diktalas", 1, h) == (date(2026, 10, 3), date(2026, 11, 3))


def test_mvm_gaz_pdf_mero_nelkuli():
    """MVM gázszámla PDF-ből (XML nélkül), mérő nélküli negyedéves átalány: a negyedév közepén, az adott negyedévről."""
    from szamlak import mvm_gaz_szoveg
    from szamla_import import szamlazasi_eltolas
    t = """MVM Next Energiakereskedelmi Zrt.
Földgáz elszámoló számla
Számla sorszáma: 101300000009
Elszámolási időszak: 2025.04.01.-2025.06.30.
Fizetendő összeg: 3 475 Ft
Számla kelte: 2025.05.27.
Elszámolt mennyiség: 1 110 MJ (32,01 m3)
Árszabás: Mérő nélküli
Számla összesen: 2 736 739 3 475
"""
    sz = mvm_gaz_szoveg(t, "x.pdf")
    assert (sz.sorszam, sz.kelte, sz.tipus, sz.idoszak, sz.osszeg, sz.szamlaertek) == (
        "101300000009", date(2025, 5, 27), "elszamolo", (date(2025, 4, 1), date(2025, 6, 30)), D(3475), D(3475))
    assert sz.elszamolt_gaz == {"mj": D(1110), "m3": D("32.01")}
    tarolt = {"szamlak": {"a": {"kelte": "2025-05-27", "idoszak": ["2025-04-01", "2025-06-30"], "tipus": "elszamolo"}}}
    assert szamlazasi_eltolas(tarolt) == -1
    tarolt = {"szamlak": {"m": {"kelte": "2026-07-08", "idoszak": ["2026-04-01", "2026-06-30"], "tipus": "egyeb"}}}
    assert szamlazasi_eltolas(tarolt) == -3  # MOHU: utólagos


def test_h_regiszterek_elso_sor_nyari_masodik_teli():
    from szamlak import h_regiszterek
    # Nyári időszak: az első sor nő → 1.82 nyári; a második (0 fogyasztás) a téli.
    r = h_regiszterek([("M", date(2026, 8, 4), date(2026, 9, 4), D(1549), D(1595), "Dikt"),
                       ("M", date(2026, 8, 4), date(2026, 9, 4), D(4020), D(4020), "Dikt")])
    assert sorted((m.csatorna, m.datum.isoformat(), m.allas) for m in r) == [
        ("h_nyari", "2026-08-04", D(1549)), ("h_nyari", "2026-09-04", D(1595)),
        ("h_teli", "2026-08-04", D(4020)), ("h_teli", "2026-09-04", D(4020))]
    # Tisztán téli időszak, fordított sorrendben nyomtatva (csak az első sor nő): megfordul.
    r = h_regiszterek([("M", date(2025, 11, 16), date(2026, 2, 6), D(2986), D(3759), "Dikt"),
                       ("M", date(2025, 11, 16), date(2026, 2, 6), D(1458), D(1458), "Dikt")])
    assert {(m.csatorna, m.allas) for m in r if m.datum == date(2026, 2, 6)} == {("h_teli", D(3759)), ("h_nyari", D(1458))}


def test_regiszter_rogzit_csak_valodi_es_nem_duplikal():
    from szamla_import import regiszter_rogzit
    from szamlak import Meroallas, Szamla
    tarolt = {"merok": [{"gyari_szam": "M", "beepitve": "2020-01-01", "leolvasasok": []}]}
    sz = Szamla(forras="mvm_aram", sorszam="1", kelte=date(2026, 9, 9), osszeg=D(1), tipus="elszamolo",
                idoszak=(date(2026, 8, 4), date(2026, 9, 4)), fajl="x.pdf")
    sz.regiszter_allasok = [Meroallas("M", date(2026, 9, 4), D(1595), "Dikt", "h_nyari"),
                            Meroallas("M", date(2026, 8, 4), D(1549), "Dikt", "h_nyari"),
                            Meroallas("M", date(2026, 9, 4), D(4020), "Becs", "h_teli")]
    assert regiszter_rogzit(tarolt, sz) == 2
    assert regiszter_rogzit(tarolt, sz) == 0  # másodszor nem duplikál
    assert {(lo["datum"], lo["csatorna"]) for lo in tarolt["merok"][0]["leolvasasok"]} == {("2026-08-04", "h_nyari"), ("2026-09-04", "h_nyari")}


def test_kezi_szamla_hataridovel_lejart():
    # Kézi számla fizetési határidővel: tárolódik, és ha lejárt, a fizetés-állapot jelzi (eddig kézinél nem lehetett).
    from fizetes import allapot, osszesito

    t = {"merok": [{"gyari_szam": "X", "beepitve": "2025-01-01", "kezdo_allas": "0", "leolvasasok": []}], "szamlak": {}, "reszszamlak": []}
    sz = kezi_szamla(t, date(2026, 9, 10), D(11862), "resz", "G-08", idoszak=(date(2026, 8, 1), date(2026, 8, 31)),
                     hatarido=date(2026, 9, 25))
    rogzit(t, [sz])
    assert t["szamlak"]["G-08"]["hatarido"] == "2026-09-25"
    a = allapot("G-08", t["szamlak"]["G-08"], None, None, date(2026, 10, 6))
    assert a["lejart"] and osszesito([a], date(2026, 10, 6))["lejart_ft"] == 11862


_ALFOLDVIZ_RESZ = """ALFÖLDVÍZ Zrt.
                                         Víziközmű-szolgáltatás 2. részszámla
 Fizetendő összeg:                         3 699 Ft              Felhasználó neve:              Teszt Elek
 Fizetési határidő:                     2026-09-21
                                                                 Felhasználási hely címe:       1234 Példaváros, Minta utca 1.
 Elszámolt időszak:           2026.05.01-2026.08.31
 bejelentésre minden hónap 10-e és 15-e között van lehetőség.
Vevő (fizető) azonosító száma: 100000000001
Számla sorszáma: 900001LV26                                                                Számla kelte: 2026-08-24
Elszámolt mennyiség: Ivóvíz 4 m3, Szennyvíz 8 m3
   12345678 számú vízmérőn mért ivóvíz          2026.05.01-              64-68            4 m3    234,00 Ft/m3            936,00        27          1 188,72
         fogyasztással arányos díj               2026.08.31
      Bruttó számlaérték összesen*:                                                                                                                   3 699
Fogyasztás megállapításának módja:                                        kalkulált
Következő leolvasás várható időpontja:                     2027.02.15-2027.02.19
Következő diktálás várható időpontja:                      2026.09.10-2026.09.15
"""

_ALFOLDVIZ_ELSZ = """ALFÖLDVÍZ Zrt.
                                         Víziközmű-szolgáltatás elszámoló számla
 Fizetendő összeg:                         3 098 Ft
Számla sorszáma: 900002LV25                                                                Számla kelte: 2025-02-19
Elszámolt mennyiség:Ivóvíz 16 m3, Szennyvíz 16 m3
   12345678 számú vízmérőn mért ivóvíz                 2024.02.13-                32-48              16 m3      234,00 Ft/m3           3 744,00        27           4 754,88
            fogyasztással arányos díj                   2025.02.10
       Bruttó számlaérték összesen*:                                                                                                                                   9 876
     Figyelembe vett hátralék/túlfizetés                                                                                                                              -6 778
Leolvasás módja (LM) jelen számlában:                                                      Leol
Az elszámoló számlában elszámolt részszámlák sorszáma és a számla végösszege:

               Sorszám                             Számla végösszeg(Ft)

             900003LV24                                       617
             900004LV24                                       604
"""


def test_alfoldviz_reszszamla_kalkulalt():
    """ALFÖLDVÍZ részszámla (anonimizált): a „kalkulált” mérőállás nem valódi (Becs), az átalány-jelzés és a
    következő leolvasás / diktálás, a diktálási ablak (minden hónap 10–15.) kiolvasva."""
    from szamlak import alfoldviz_szoveg

    sz = alfoldviz_szoveg(_ALFOLDVIZ_RESZ, "x.pdf")
    assert sz.forras == "alfoldviz" and sz.tipus == "resz" and sz.sorszam == "900001LV26"
    assert sz.kelte == date(2026, 8, 24) and sz.osszeg == 3699 and sz.hatarido == date(2026, 9, 21)
    assert sz.idoszak == (date(2026, 5, 1), date(2026, 8, 31))
    assert [(m.datum, m.allas, m.valodi) for m in sz.meroallasok] == [(date(2026, 5, 1), 64, False), (date(2026, 8, 31), 68, False)]
    assert sz.elszamolt_viz["ivoviz"] == 4 and sz.elszamolt_viz["csatorna"] == 8 and sz.elszamolt_viz["atalany"]
    assert sz.kovetkezo_leolvasas == (date(2027, 2, 15), date(2027, 2, 19)) and sz.kovetkezo_diktalas == (date(2026, 9, 10), date(2026, 9, 15))
    assert sz.diktalasi_ablak == (10, 15) and sz.ugyfel["nev"] == "Teszt Elek" and sz.ugyfel["mero"] == "12345678"


def test_alfoldviz_elszamolo():
    """ALFÖLDVÍZ elszámoló (anonimizált): valódi (Leol) éves leolvasás, időszak a mérősorból, a levont részszámlák
    és a túlfizetés beszámítása (számlaérték 9 876, fizetendő 3 098)."""
    from szamlak import alfoldviz_szoveg

    sz = alfoldviz_szoveg(_ALFOLDVIZ_ELSZ)
    assert sz.tipus == "elszamolo" and sz.idoszak == (date(2024, 2, 13), date(2025, 2, 10))
    assert [(m.allas, m.valodi, m.leolvasott) for m in sz.meroallasok] == [(32, True, True), (48, True, True)]
    assert sz.szamlaertek == 9876 and sz.osszeg == 3098 and sz.egyeb_tetelek == [("figyelembe vett hátralék/túlfizetés", -6778)]
    assert sz.levont_szamlak == [("900003LV24", 617), ("900004LV24", 604)]


def test_tavho_szamla_mero_szuro_nem_zarja_ki():
    """A távhőszámlán (HVSZ) nincs mérőszám: a fiók „számla-mérők” szűrője (pl. a melegvízóra száma) nem zárhatja ki."""
    from szamlak import Szamla
    sz = Szamla(forras="hvsz", sorszam="H1/2026/1", kelte=date(2026, 9, 8), osszeg=D(494), tipus="resz")
    assert hozzatartozik(sz, {"79407642"})
    assert not hozzatartozik(Szamla(forras="mvm_aram", sorszam="1", kelte=date(2026, 9, 8), osszeg=D(1), tipus="resz"), {"79407642"})


def test_idenyes_hulladek_kovetkezo_szamla():
    """Üdülő hulladékdíja (ápr.–szept.), negyedéves számla: az első, tört negyedév (ápr. 5-től) nem „díjváltozás”, és a
    díjmentes 4. és 1. negyedévre nem vár számlát – a következő a jövő évi 2. negyedévé."""
    from szamla_import import szamla_statisztika
    t = {"szamlak": {"A": {"kelte": "2026-05-06", "osszeg": "3169", "idoszak": ["2026-04-05", "2026-06-30"]},
                     "B": {"kelte": "2026-07-06", "osszeg": "3317", "idoszak": ["2026-07-01", "2026-09-30"]}}}
    s = szamla_statisztika(t, date(2026, 10, 7), fix_dij=True, honap=3, idenyes=[4, 5, 6, 7, 8, 9])
    assert s["figyelmeztetes"] is None and s["kovetkezo_datum"] == date(2027, 4, 6)
    s2 = szamla_statisztika(t, date(2026, 10, 7), fix_dij=True, honap=3)
    assert s2["kovetkezo_datum"] == date(2026, 10, 6)


def test_kozos_koltseg_havi_eloiras_ablak():
    """Közös költség (havi fix díj): a hónap előírása „ebben a hónapban fizetendő” (minimum=1); más fix díjnál 2 hónaptól."""
    from szamla_import import szamlazasi_ablak
    es = {"e_havi_osszesen": 23040, "e_havi_kiallitott": 23040, "e_havi_szamlak": [{"kelte": "2026-10-01"}],
          "kovetkezo_datum": date(2026, 11, 1), "kovetkezo_osszeg": 23040}
    assert szamlazasi_ablak(date(2026, 10, 7), 1, es) is None
    a = szamlazasi_ablak(date(2026, 10, 7), 1, es, eltolas=0, minimum=1)
    assert a["esedekes_most"] and a["kiallitott"] and a["fizetendo"] == 23040 and a["tol"] == date(2026, 10, 1)


def test_telekom_xml():
    """Telekom összevont számla (AMDOCSBILL): a számla összege az egyszeri tételekkel, az időszak a Period hónapja."""
    from szamlak import telekom_xml
    xml = ("<Invoice><Header><Source>AMDD</Source><DocType>AMDOCSBILL</DocType><InvNb>111</InvNb><InvDate>2026.07.08</InvDate>"
           "<PaymDue>2026.07.29</PaymDue><InvAmVAT>18439.00</InvAmVAT><PayModeName>Banki átutalás</PayModeName>"
           "<Period>202606</Period></Header></Invoice>")
    sz = telekom_xml(xml.encode())
    assert (sz.forras, sz.sorszam, sz.osszeg, sz.hatarido) == ("telekom", "111", 18439, date(2026, 7, 29))
    assert sz.idoszak == (date(2026, 6, 1), date(2026, 6, 30)) and sz.fizetesi_mod == "Banki átutalás"
    assert telekom_xml(MOHU.encode()) is None


def test_fix_dij_egyszeri_tetel_a_havidijhoz_merve():
    """Fix díj ismert havidíjjal: az egyszeri tételes számla nem „díjváltozás”, hanem eltérés a havidíjtól; egyező számlánál nincs jelzés."""
    from szamla_import import szamla_statisztika
    t = {"szamlak": {"A": {"kelte": "2026-06-05", "osszeg": "9689", "idoszak": ["2026-05-01", "2026-05-31"]},
                     "B": {"kelte": "2026-07-08", "osszeg": "18439", "idoszak": ["2026-06-01", "2026-06-30"]}}}
    s = szamla_statisztika(t, date(2026, 7, 20), fix_dij=True, honap=1, szamla_dij=D(9689))
    assert "8750 Ft-tal több" in s["figyelmeztetes"] and "díjváltozás:" not in s["figyelmeztetes"]
    assert s["dij_elteres"] == {"sorszam": "B", "osszeg": 18439, "dij": 9689, "elteres": 8750, "tol": "2026-06-01", "honap": 1}
    # „Egyszeri eltérés – rendben”: ennél a számlánál nem jelez tovább.
    t["dijelteres_nyugtazva"] = ["B"]
    s = szamla_statisztika(t, date(2026, 7, 20), fix_dij=True, honap=1, szamla_dij=D(9689))
    assert s["figyelmeztetes"] is None and s["dij_elteres"] is None
    del t["dijelteres_nyugtazva"]
    t["szamlak"]["B"]["osszeg"] = "9689"
    assert szamla_statisztika(t, date(2026, 7, 20), fix_dij=True, honap=1, szamla_dij=D(9689))["figyelmeztetes"] is None


def test_hvsz_pdf_folyoszamla_es_elszamolo_idoszak():
    """HVSZ 13. részszámla (hődíj-korrekció + augusztusi melegvíz): az XML-ből csak az augusztus látszik; a PDF-ből a
    teljes elszámolt időszak (a fűtési idény elejétől) és a számlán közölt folyószámla-egyenleg."""
    from szamlak import Szamla, hvsz_pdf
    sz = Szamla(forras="hvsz", sorszam="H90004/2026/10001", kelte=date(2026, 9, 8), osszeg=D("-22137"), tipus="elszamolo",
                fajl="x.xml", idoszak=(date(2026, 8, 1), date(2026, 8, 31)))
    hvsz_pdf(sz, "Elszámolt időszak:    2025.10.01-2026.03.31           Felhasználó azonosító száma: X\n"
                 "A nyilvántartás szerinti folyószámla-egyenlege a számla kibocsátásakor     -22.137 Ft.\n")
    assert sz.idoszak == (date(2025, 10, 1), date(2026, 8, 31)) and sz.folyoszamla == D("-22137")
    hvsz_pdf(sz, "79407642 mérőóra fogyasztása 2026.08.01 - 2026.08.31 között: Nyitó óra állás:26; Záró óra állás:27; Fogyasztás:1 m3")
    assert [(m.mero, m.datum, m.allas, m.valodi, m.leolvasott) for m in sz.meroallasok] == [
        ("79407642", date(2026, 8, 1), D(26), True, False), ("79407642", date(2026, 8, 31), D(27), True, False)]
    resz = Szamla(forras="hvsz", sorszam="H1", kelte=date(2026, 5, 14), osszeg=D("4059"), tipus="resz", fajl="y.xml",
                  idoszak=(date(2026, 4, 1), date(2026, 4, 30)))
    hvsz_pdf(resz, "Elszámolt időszak:    2026.04.01-2026.04.30\nfolyószámla-egyenlege a számla kibocsátásakor  4.059 Ft.")
    assert resz.idoszak == (date(2026, 4, 1), date(2026, 4, 30)) and resz.folyoszamla == D("4059")



def test_telekom_pdf_xml_nelkul():
    """Telekom összevont számla PDF-ből (pdftotext-layout; az ő/ű helyett õ/û is jöhet) – szintetikus szöveg."""
    from datetime import date
    from decimal import Decimal

    from szamlak import telekom_pdf

    szoveg = """Magyar Telekom Nyrt.
               Számla sorszám                      5374000000000092                     Minta
               Számla kelte                        2026.08.06.                          Fő utca 1
               Elszámolási idõszak                 2026.07.01. - 2026.07.31.
                                                                                Beérkezési határidõ    2026.08.28.
                  A szolgáltatások fizetendõ összege*                                       10.107 Ft
                                                                                Fizetés módja          Banki átutalás
               Jelenlegi számla összesen       Nettó összeg 8.400,00 Ft     ÁFA 1.707,00 Ft      Bruttó összeg 10.107,00 Ft
"""
    sz = telekom_pdf(szoveg, "x.pdf")
    assert (sz.sorszam, sz.kelte, sz.osszeg, sz.hatarido, sz.fizetesi_mod) == (
        "5374000000000092", date(2026, 8, 6), Decimal("10107.00"), date(2026, 8, 28), "Banki átutalás")
    assert sz.idoszak == (date(2026, 7, 1), date(2026, 7, 31))
    assert telekom_pdf("Valami más szolgáltató", "y.pdf") is None


def test_one_pdf():
    """One Magyarország (volt DIGI) számla – pypdf plain mód (a teljesítés dátuma külön sorban) és pdftotext-layout
    (három dátum egy sorban); szintetikus szöveg."""
    from datetime import date
    from decimal import Decimal

    from szamlak import one_pdf

    plain = """61.10.43 5% NET MAX 1 DB 2026/08/01 - 2026/08/31 6 180,95 6 180,95 309,05 6 490,00
61.10.11 27% TEL Ideál 1 DB 2026/08/01 - 2026/08/31 787,40 787,40 212,60 1 000,00
Fizetendő: 7 490,00
Szerződésszám Teljesítés időpontja Számla kelte Fizetési határidő Fizetési mód Számla száma
20000001 2026. 08. 16 2026. 09. 06 ÁTUTALÁS 2026/10000001
One Magyarország Zrt.
2026. 09. 06
"""
    sz = one_pdf(plain, "x.pdf")
    assert (sz.forras, sz.sorszam, sz.kelte, sz.hatarido, sz.osszeg, sz.fizetesi_mod) == (
        "one", "2026/10000001", date(2026, 8, 16), date(2026, 9, 6), Decimal("7490.00"), "Átutalás")
    assert sz.idoszak == (date(2026, 8, 1), date(2026, 8, 31))
    layout = """ One Magyarország Zrt.
 Szerződésszám               Teljesítés időpontja             Számla kelte             Fizetési határidő            Fizetési mód            Számla száma
 20000001                    2026. 01. 31                     2026. 01. 08             2026. 01. 31                 ÁTUTALÁS               2026/10000002
61.10.43         5%     Csomag kedvezmény 1.                      1 DB 2026/01/01 - 2026/01/31             -6 952,38     -6 952,38         -347,62     -7 300,00
Fizetendő:                                                                                                                                              5 510,00
"""
    sz = one_pdf(layout, "y.pdf")
    assert (sz.sorszam, sz.kelte, sz.hatarido, sz.osszeg) == ("2026/10000002", date(2026, 1, 8), date(2026, 1, 31), Decimal("5510.00"))
    assert one_pdf("Magyar Telekom Nyrt.", "z.pdf") is None


def test_kezi_szamla_idoszak_nelkul_az_uton_levo_idoszakot_fedi_le():
    """Városi lakás 2026-10-12: időszak nélkül, kézzel rögzített számla – a lezárt szeptemberi időszakot kell lefednie,
    különben a kártya és a panel tovább „várható” (sárga dőlt) számlát mutat."""
    from szamla_import import kezi_idoszak_potlas

    tarolt = {"szamlak": {
        "845700000002": {"kelte": "2026-09-09", "idoszak": ["2026-08-04", "2026-09-04"], "osszeg": "1828", "tipus": "elszamolo"},
        "kezi-2026-10-12-1": {"kelte": "2026-10-12", "osszeg": "700.0", "tipus": "resz", "idoszak": None, "kezi": True},
    }}
    uton = [{"tol": "2026-09-05", "ig": "2026-10-01", "osszeg": 700}]
    assert kezi_idoszak_potlas(tarolt, uton) is True
    assert tarolt["szamlak"]["kezi-2026-10-12-1"]["idoszak"] == ["2026-09-05", "2026-10-01"]
    # Másodszor nincs mit pótolni; a szolgáltatói számlához és a kelte utáni időszakhoz nem nyúl.
    assert kezi_idoszak_potlas(tarolt, uton) is False
    t2 = {"szamlak": {"kezi-2026-09-20-1": {"kelte": "2026-09-20", "osszeg": "1", "tipus": "resz", "kezi": True}}}
    assert kezi_idoszak_potlas(t2, uton) is False and not t2["szamlak"]["kezi-2026-09-20-1"].get("idoszak")
