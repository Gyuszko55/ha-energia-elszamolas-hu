"""Számlakezelési javítások (regresszió): stornó / sztornózott számla, kelte nélküli számla, fel nem ismert fájl
újrapróbálása, XML–PDF pár, Díjnet-számlaszám vezető nullái, azonos napi azonos összegű számlák. Csak kitalált adatok."""
import os
from datetime import date
from decimal import Decimal as D

import tests.conftest  # noqa: F401
import fizetes
import kimutatas
import szamla_import as si
import szamlak as S

M = S.Meroallas
EV = (date(2025, 7, 1), date(2026, 6, 30))
MA = date(2026, 8, 15)


def _ures() -> dict:
    return {"merok": [{"gyari_szam": "1", "beepitve": "2020-01-01", "kezdo_allas": "0", "leolvasasok": []}],
            "almero_merok": [], "reszszamlak": []}


def _harmas():
    """Eredeti elszámoló, a stornója (PDF: sztornózott sorszámmal), és az újra kiállított, helyesbített számla."""
    o = S.Szamla("mvm_aram", "100", date(2026, 7, 1), D(20000), "elszamolo", EV, szamlaertek=D(20000), hatarido=date(2026, 7, 20))
    o.meroallasok = [M("1", EV[0], D(500), "Leol"), M("1", EV[1], D(9000), "Leol")]
    s = S.Szamla("mvm_aram", "101", date(2026, 7, 10), D(0), "storno", szamlaertek=D(-20000), sztornozott="100")
    n = S.Szamla("mvm_aram", "102", date(2026, 7, 11), D(18000), "elszamolo", EV, szamlaertek=D(18000), hatarido=date(2026, 7, 30))
    n.meroallasok = [M("1", EV[0], D(500), "Leol"), M("1", EV[1], D(2500), "Leol")]
    return o, s, n


def _leolvasasok(t: dict) -> list:
    return [(lo["datum"], lo["allas"], lo["megjegyzes"]) for lo in t["merok"][0]["leolvasasok"]]


# --- 1. A sztornózott eredeti mindenhol kimarad --------------------------------------------------------------


def test_sztornozott_eredeti_befizetese_es_eves_osszege_kimarad():
    t = _ures()
    si.rogzit(t, list(_harmas()))
    assert [(r["sorszam"], r["osszeg"]) for r in t["reszszamlak"]] == [("102", "18000")]
    st = si.szamla_statisztika(t, date(2026, 8, 1))
    assert (st["eves_osszeg"], st["eves_db"]) == (18000, 1)
    assert si.befizetesek_egyesitese(t) == {"102": (date(2026, 7, 11), D(18000))}


def test_sztornozott_eredeti_allasa_nem_blokkolja_a_helyesbitettet():
    t = _ures()
    si.rogzit(t, list(_harmas()))
    assert _leolvasasok(t) == [("2025-07-01", "500", "számla 102 (Leol)"), ("2026-06-30", "2500", "számla 102 (Leol)")]


def test_kesobb_erkezo_storno_torli_az_eredeti_befizeteset_es_allasait():
    o, s, n = _harmas()
    t = _ures()
    si.rogzit(t, [o])
    assert [r["sorszam"] for r in t["reszszamlak"]] == ["100"] and len(_leolvasasok(t)) == 2
    si.rogzit(t, [s, n])
    assert [r["sorszam"] for r in t["reszszamlak"]] == ["102"]
    assert [x[1] for x in _leolvasasok(t)] == ["500", "2500"]


def test_sztornozott_szamla_nem_lejart_es_nem_nyitott():
    t = _ures()
    si.rogzit(t, list(_harmas()))
    torolt = S.sztornozott_kulcsok(t["szamlak"])
    assert torolt == {"100"}
    al = {k: fizetes.allapot(k, x, None, None, MA, sztornozva=k in torolt) for k, x in t["szamlak"].items()}
    assert al["100"]["nincs_fizetendo"] and not al["100"]["lejart"] and al["100"]["sztornozva"]
    o = fizetes.osszesito(list(al.values()), MA)
    assert (o["nyitott_db"], o["nyitott_ft"], o["lejart_ft"]) == (1, 18000, 18000)
    assert S.ervenytelenek(t["szamlak"]) == {"100", "101"}


def test_teljes_dij_nem_szamolja_a_sztornozott_reszszamlat():
    sz = {"r1": {"tipus": "resz", "idoszak": ["2025-08-01", "2025-08-31"], "szamlaertek": "5000"},
          "r1b": {"tipus": "resz", "idoszak": ["2025-08-01", "2025-08-31"], "szamlaertek": "5000"},
          "s": {"tipus": "storno", "sztornozott": "r1", "szamlaertek": "-5000"}}
    e = {"tipus": "elszamolo", "idoszak": ["2025-07-01", "2026-06-30"], "szamlaertek": "1000"}
    assert S.szamla_teljes_dija(e, sz) == (6000, "szamlaertek+levont")


def test_eves_kimutatas_kihagyja_a_sztornozottat_akkor_is_ha_kesobbi():
    i = ["2025-07-01", "2026-06-30"]
    sz = {"A": {"tipus": "elszamolo", "idoszak": i, "kelte": "2026-07-01", "tetelek": {"x": 1}},
          "B": {"tipus": "elszamolo", "idoszak": i, "kelte": "2026-07-20", "tetelek": {"x": 2}},
          "S": {"tipus": "storno", "sztornozott": "B", "kelte": "2026-07-25"}}
    assert [x["sorszam"] for x in kimutatas.elszamolok(sz, date(2025, 7, 1), date(2026, 6, 30))] == ["A"]


# --- 2. Stornó az XML-úton és a gáz-PDF-nél --------------------------------------------------------------------

XML_STORNO = """<szamla><fejlec><szamlainfo><szlanev>Villamos energia sztornó számla</szlanev><szlaszam>101</szlaszam>
<szlakelte>2026.07.10</szlakelte><elsz_kezdete>2025.07.01</elsz_kezdete><elsz_vege>2026.06.30</elsz_vege>{extra}
<szolgaltatas>Villamos energia</szolgaltatas></szamlainfo></fejlec>
<tetel><mero_gyartasi_szama>0001</mero_gyartasi_szama><elszamolasi_idoszak_kezdete>2025.07.01</elszamolasi_idoszak_kezdete>
<elszamolasi_idoszak_vege>2026.06.30</elszamolasi_idoszak_vege><indulo_meroallas>500</indulo_meroallas>
<zaro_meroallas>9000</zaro_meroallas><lm_megnevezes>Leol</lm_megnevezes></tetel>
<osszesites><sor_megnevezes_szoveg>Fizetendő összeg</sor_megnevezes_szoveg><brutto_osszeg>{osszeg}</brutto_osszeg></osszesites></szamla>"""


def test_mvm_xml_storno_allas_nelkul_es_parositas_osszeg_szerint():
    x = S.mvm_xml(XML_STORNO.format(extra="", osszeg="-20000").encode())
    assert (x.tipus, x.sztornozott, x.meroallasok, x.kapcsolt_merok) == ("storno", "", [], {"1"})
    o, _, n = _harmas()
    t = _ures()
    si.rogzit(t, [o, x, n])
    assert t["szamlak"]["101"]["sztornozott"] == "100"
    assert [r["sorszam"] for r in t["reszszamlak"]] == ["102"]
    assert si.szamla_statisztika(t, date(2026, 8, 1))["eves_osszeg"] == 18000


def test_mvm_xml_storno_mas_osszeggel_nem_parosit():
    x = S.mvm_xml(XML_STORNO.format(extra="", osszeg="-1234").encode())
    o, _, _ = _harmas()
    t = _ures()
    si.rogzit(t, [o, x])
    assert not t["szamlak"]["101"].get("sztornozott")
    assert [r["sorszam"] for r in t["reszszamlak"]] == ["100"]


def test_mvm_xml_storno_sorszam_mezobol():
    x = S.mvm_xml(XML_STORNO.format(extra="<eredeti_szlaszam>100</eredeti_szlaszam>", osszeg="-1").encode())
    assert x.sztornozott == "100"


GAZ_STORNO = """MVM Next Energiakereskedelmi Zrt.
Sztornó számla
Számla sorszáma: 123
Számla kelte: 2026.08.27
Sztornózott számla sorszáma: 122
{cim}
Fizetendő összeg: -3 475 Ft
"""


def test_mvm_gaz_pdf_sztorno_fejlec():
    x = S.mvm_gaz_szoveg(GAZ_STORNO.format(cim="Földgáz egyetemes szolgáltatás"))
    assert x is not None and (x.forras, x.tipus, x.sztornozott, x.osszeg) == ("mvm_gaz", "storno", "122", D(0))
    y = S.mvm_gaz_szoveg(GAZ_STORNO.format(cim="Földgáz részszámla"))
    assert (y.tipus, y.sztornozott) == ("storno", "122")


# --- 3. Kelte nélküli számla -----------------------------------------------------------------------------------


def test_kelte_nelkul_nem_ismert_es_iso_datum():
    assert S._d("2026-07-08") == date(2026, 7, 8) and S._d("2026.07.08") == date(2026, 7, 8) and S._d("2026.13.40") is None
    tk = b"<Invoice><DocType>AMDOCSBILL</DocType><InvNb>1</InvNb><InvDate>{}</InvDate><InvAmVAT>100</InvAmVAT></Invoice>"
    assert S.telekom_xml(tk.replace(b"{}", b"2026-07-08")).kelte == date(2026, 7, 8)
    assert S.telekom_xml(tk.replace(b"{}", b"")) is None
    assert S.mvm_xml(XML_STORNO.format(extra="", osszeg="1").replace("<szlakelte>2026.07.10</szlakelte>", "").encode()) is None
    # biztonsági háló: a rögzítés nem áll meg rajta, a többi számla bekerül
    rossz = S.Szamla("telekom", "T0", None, D(1), "egyeb")
    jo = S.Szamla("telekom", "T1", date(2026, 8, 5), D(2), "egyeb")
    t = _ures()
    si.rogzit(t, [rossz, jo])
    assert list(t["szamlak"]) == ["T1"]


def test_kelte_nelkuli_xml_fajl_fel_nem_ismert(tmp_path):
    f = tmp_path / "a.xml"
    f.write_text(XML_STORNO.format(extra="", osszeg="1").replace("<szlakelte>2026.07.10</szlakelte>", ""), encoding="utf-8")
    assert S.beolvas_fajl(f) is None


# --- 4. A fel nem ismert fájlt (változás után) újrapróbáljuk ---------------------------------------------------


def test_fel_nem_ismert_fajl_valtozas_utan_ujra_uj(tmp_path):
    f = tmp_path / "letoltes.xml"
    f.write_text("<fel/>", encoding="utf-8")
    assert S.uj_fajlok(tmp_path, set()) == [f]
    nem = S.nem_olvasott_frissites(tmp_path, {}, [f])
    assert S.uj_fajlok(tmp_path, set(), nem) == []  # változatlan: nem olvassuk újra
    f.write_text("<fel>kesz</fel>", encoding="utf-8")
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 1_000_000_000))
    assert S.uj_fajlok(tmp_path, set(), nem) == [f]  # kicserélték / befejeződött a letöltés
    f.unlink()
    assert S.nem_olvasott_frissites(tmp_path, nem, []) == {}


# --- 5. PDF XML-párral: csak akkor marad ki, ha az XML felismert -------------------------------------------------

DAKOV = " DAKÖV\n Számla sorszáma: X1 Számla kelte: 2026.08.04\n Fizetendő összeg: 1 202 Ft\n"


def test_pdf_xml_parral_csak_olvashato_xml_mellett_marad_ki(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "pdf_szoveg", lambda fajl, mod="layout": DAKOV)
    monkeypatch.setattr(S, "_mvm_pdf", lambda fajl: False)
    pdf, xml = tmp_path / "sz.pdf", tmp_path / "sz.xml"
    pdf.write_bytes(b"%PDF")
    xml.write_text("<valami/>", encoding="utf-8")
    x = S.beolvas_fajl(pdf)
    assert x is not None and (x.forras, x.sorszam) == ("dakov", "X1")
    xml.write_text(XML_STORNO.format(extra="", osszeg="1"), encoding="utf-8")
    assert S.beolvas_fajl(pdf) is None  # az XML-t olvassuk helyette


# --- 6. Díjnet ↔ számlamappa: számlaszám vezető nullák nélkül ---------------------------------------------------


def test_befizetesek_vezeto_nullak_nelkul_egyszer():
    t = {"reszszamlak": [{"datum": "2026-07-01", "osszeg": "5000", "sorszam": "0012345"}], "szamlak": {}}
    b = si.befizetesek_egyesitese(t, [(date(2026, 7, 2), D(5000), "12345"), (date(2026, 8, 1), D(700), "0099")])
    assert b == {"12345": (date(2026, 7, 1), D(5000)), "99": (date(2026, 8, 1), D(700))}
    # a Díjnetben szereplő sztornózott számla sem befizetés
    t["szamlak"] = {"0099": {"tipus": "resz"}, "S": {"tipus": "storno", "sztornozott": "99"}}
    assert "99" not in si.befizetesek_egyesitese(t, [(date(2026, 8, 1), D(700), "0099")])


# --- 7. Azonos napi, azonos összegű, de külön sorszámú számlák ----------------------------------------------------


def test_azonos_napi_azonos_osszegu_szamlak_kulon_befizetes():
    a = S.Szamla("telekom", "T1", date(2026, 8, 5), D(9990), "egyeb", szamlaertek=D(9990))
    b = S.Szamla("telekom", "T2", date(2026, 8, 5), D(9990), "egyeb", szamlaertek=D(9990))
    t = _ures()
    si.rogzit(t, [a, b])
    assert [r["sorszam"] for r in t["reszszamlak"]] == ["T1", "T2"]
    # a sorszám nélküli (kézi) tétel nap+összeg szerint továbbra is ugyanaz a befizetés
    t2 = _ures()
    t2["reszszamlak"] = [{"datum": "2026-08-05", "osszeg": "9990"}]
    si.rogzit(t2, [a])
    assert len(t2["reszszamlak"]) == 1


def test_mvm_mero_15_jegyu_gyari_szam():
    """A 15 jegyű gyári számú (pl. H-tarifás) mérő sora is illeszkedik – 2.2.0b5 előtt csak 16–18 jegyű, így a
    számla mérő nélkül maradt, és a fiókszűrő „más mérő”-nek vette (kitalált számokkal)."""
    from custom_components.hu_rezsi.szamlak import _MVM_SOR

    sor = "1234567890123452025.10.18-2026.04.140 5.441Dikt5.4411 5.441"
    m = _MVM_SOR.search(sor)
    assert m and m.group(1) == "123456789012345" and m.group(2) == "2025.10.18" and m.group(5) == "Dikt"
    regi = "12345678901234562025.10.18-2026.04.1417 17 Dikt0 1 0"               # 16 jegyű: továbbra is jó
    assert _MVM_SOR.search(regi).group(1) == "1234567890123456"
