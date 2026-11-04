"""Számlasablon (2.3.0b2): készítés a jóváhagyott adatból, önpróba, alkalmazás egy második (azonos formájú, más
értékű) számlán, személyesadat-szűrő, tár. A mintaszámlák kitaláltak."""
from pathlib import Path

from custom_components.hu_rezsi import ai_beolvaso as A
from custom_components.hu_rezsi import sablon as S
from tests.test_ai_beolvaso import AI_VALASZ, SZAMLA

JOVAHAGYOTT = A.normalizal(A.Kitakaro(merok=["A77123456"]).visszair(AI_VALASZ))

MASODIK = (SZAMLA.replace("PV-2026/004512", "PV-2026/005871").replace("2026.10.05", "2026.12.04").replace("2026.10.20", "2026.12.19")
           .replace("2026.08.01 - 2026.09.30", "2026.10.01 - 2026.11.30").replace("2026.08.01  412   2026.09.30  431", "2026.10.01  431   2026.11.30  453")
           .replace("Ivóvíz 19 m3, Csatorna 19 m3", "Ivóvíz 22 m3, Csatorna 22 m3")
           .replace("19         m3       400,00     7 600", "22         m3       400,00     8 800")
           .replace("19         m3       500,00     9 500", "22         m3       500,00    11 000")
           .replace("19 551 Ft", "22 251 Ft").replace("Minta Anna", "Próba Béla"))


def _sab():
    return S.keszit(JOVAHAGYOTT, SZAMLA, SZAMLA)


def test_keszit_es_onproba():
    s = _sab()
    assert s["azonosito"] == "peldaviz_vizikozmu_zrt_viz"
    assert set(s["mezok"]) >= {"sorszam", "kelte", "fizetesi_hatarido", "fizetendo", "idoszak_tol", "idoszak_ig"}
    assert len(s["merok"]) == 1 and len(s["tetelek"]) == 3 and len(s["mennyisegek"]) == 2
    assert S.onproba(s, JOVAHAGYOTT, SZAMLA, SZAMLA) == []


def test_masodik_szamla_ai_nelkul():
    d = S.alkalmaz(_sab(), MASODIK, MASODIK)
    assert d["sorszam"] == "PV-2026/005871" and d["kelte"] == "2026-12-04" and d["fizetesi_hatarido"] == "2026-12-19"
    assert (d["idoszak_tol"], d["idoszak_ig"]) == ("2026-10-01", "2026-11-30") and d["fizetendo"] == 22251
    m = d["merok"][0]
    assert (m["gyari_szam"], m["tol_datum"], m["tol_allas"], m["ig_datum"], m["ig_allas"], m["mod"]) == (
        "A77123456", "2026-10-01", 431, "2026-11-30", 453, "leolvasott")
    assert [t["brutto"] for t in d["tetelek"]] == [8800, 11000, 2451]
    assert [q["mennyiseg"] for q in d["mennyisegek"]] == [22, 22]
    assert d["kozmu"] == "viz" and d["tipus"] == "elszamolo" and S.hianyzo(d) == []


def test_mas_szolgaltato_nem_ismeri():
    assert S.alkalmaz(_sab(), SZAMLA.replace("PÉLDAVÍZ", "MÁSVÍZ"), SZAMLA.replace("PÉLDAVÍZ", "MÁSVÍZ")) is None


def test_nincs_szemelyes_adat():
    s = _sab()
    import json
    szoveg = json.dumps(s, ensure_ascii=False)
    for tilos in ("Minta Anna", "Példafalu", "Kitalált", "55443322", "minta.anna", "A77123456", "11773000", "PV-2026/004512"):
        assert tilos not in szoveg, tilos
    assert S.szemelyes(s, ["Minta Anna", "A77123456", "55443322"]) == []
    s["felismeres"]["szovegek"].append("minta.anna@example.com")
    assert S.szemelyes(s, []) == ["minta.anna@example.com"]


def test_hianyzo_mezo_elavult():
    d = S.alkalmaz(_sab(), MASODIK.replace("Fizetendő összeg:", "Összesen:"), MASODIK.replace("Fizetendő összeg:", "Összesen:"))
    assert S.hianyzo(d) == ["fizetendo"]


def test_tar_tobb_szamlaforma(tmp_path: Path):
    """Ugyanannak a szolgáltatónak egy újabb sablonja (más számlaforma) külön fájlba kerül, a régi is marad."""
    s = _sab()
    S.ment(tmp_path, dict(s))
    S.ment(tmp_path, dict(s))
    betolt = S.betolt(tmp_path)
    assert [x["azonosito"] for x in betolt] == ["peldaviz_vizikozmu_zrt_viz", "peldaviz_vizikozmu_zrt_viz_2"]
    assert S.alkalmaz(betolt[0], MASODIK, MASODIK)["fizetendo"] == 22251


def test_tipus_szamlankent():
    """A sablon nem rögzíti az első számla típusát: a szövegből (elszámoló / részszámla / sztornó)."""
    s = _sab()
    assert "tipus" not in s["allando"]
    resz = MASODIK.replace("Számla sorszáma:", "Részszámla sorszáma:")
    assert S.alkalmaz(s, resz, resz)["tipus"] == "resz"
    sz = MASODIK + "\nSztornó számla"
    assert S.alkalmaz(s, sz, sz)["tipus"] == "storno"


def test_szemelyes_adat_a_sormintaban():
    """A mérősor elején álló név nem kerül a sablonba (a sor az első kiolvasott értéktől indul)."""
    sz = SZAMLA.replace("A77123456          2026.08.01", "Kiss János   A77123456   2026.08.01")
    s = S.keszit(JOVAHAGYOTT, sz, sz)
    import json
    assert "Kiss" not in json.dumps(s, ensure_ascii=False)
    s["merok"][0]["sor"] = "Kiss\\s+János\\s+" + s["merok"][0]["sor"]  # ha mégis bekerülne: a szűrő megfogja
    assert S.szemelyes(s, ["Kiss János"]) == ["Kiss János"]


def test_nincs_robbanasszeru_visszalepes():
    import time
    s = _sab()
    t0 = time.time()
    rossz = "Ivóvíz díj 12 m3 300 " + "1" * 200 + "% " + "1" * 200 + " x\n" + MASODIK
    S.alkalmaz(s, rossz, rossz)
    assert time.time() - t0 < 1.0


def test_szamlak_sablonnal_es_fiokhoz_rendeles(monkeypatch):
    from custom_components.hu_rezsi import szamlak, szamla_import
    monkeypatch.setattr(szamlak, "SABLONOK", [_sab()])
    sz = szamlak.sablonnal(MASODIK, MASODIK, "pv2.pdf")
    assert sz.forras == "sablon:peldaviz_vizikozmu_zrt_viz" and sz.sorszam == "PV-2026/005871" and int(sz.osszeg) == 22251
    assert {m.mero for m in sz.meroallasok} == {"A77123456"}
    assert szamla_import.hozzatartozik(sz, {"A77123456"}) and not szamla_import.hozzatartozik(sz, {"B1"})
    sz.meroallasok = []
    assert szamla_import.hozzatartozik(sz, {"B1"})  # mérő nélküli sablonos számla: a mappa választja a fiókot
    hianyos = MASODIK.replace("Fizetendő összeg:", "Összesen:")
    assert szamlak.sablonnal(hianyos, hianyos, "x.pdf") is None


def test_koordinator_sablon_keszit(tmp_path: Path):
    from types import SimpleNamespace
    import custom_components.hu_rezsi.koordinator as K

    k = object.__new__(K.RezsiKoordinator)
    k.hass = SimpleNamespace(config=SimpleNamespace(config_dir=str(tmp_path)))
    e = k._sablon_keszit(JOVAHAGYOTT, SZAMLA, SZAMLA, ["Minta Anna", "A77123456"])
    assert e["mentve"] and e["fajl"] == "hu_rezsi_sablonok/peldaviz_vizikozmu_zrt_viz.yaml"
    szoveg = (tmp_path / e["fajl"]).read_text(encoding="utf-8")
    assert "Minta Anna" not in szoveg and "A77123456" not in szoveg
    assert S.betolt(tmp_path / "hu_rezsi_sablonok")[0]["mezok"]["kelte"]["minta"].startswith("Számla")
    rossz = dict(JOVAHAGYOTT, fizetendo=19651)  # a forrásszámlán nem ezt adná: nem mentjük
    e = k._sablon_keszit(rossz, SZAMLA, SZAMLA, [])
    assert not e["mentve"] and "fizetendo" in e["uzenet"]
