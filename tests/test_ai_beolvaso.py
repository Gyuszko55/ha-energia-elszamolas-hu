"""AI-számlabeolvasó (2.3.0b1): kitakarás, adatszerkezet, egységesítés, Számla, ellenőrző szabályok.

A mintaszámla kitalált (nem létező szolgáltató, személy, cím és azonosítók)."""
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.hu_rezsi import ai_beolvaso as A
from custom_components.hu_rezsi import szamla_ellenorzo as E
from custom_components.hu_rezsi import panel_beallitas as PB

SZAMLA = """PÉLDAVÍZ Víziközmű Zrt.                         Adószám: 12345678-2-07
Számla sorszáma: PV-2026/004512                    Számla kelte: 2026.10.05
Fizetési határidő: 2026.10.20
Felhasználó neve: Minta Anna
Felhasználási hely címe: 9999 Példafalu, Kitalált utca 12.
Ügyfél azonosító: 55443322
E-mail: minta.anna@example.com   Telefon: +36 30 123 4567
Bankszámla: 11773000-00112233-00000000
Elszámolási időszak: 2026.08.01 - 2026.09.30
Mérő gyári száma   Induló            Záró              Mód
A77123456          2026.08.01  412   2026.09.30  431   Leolvasott
Elszámolt mennyiség: Ivóvíz 19 m3, Csatorna 19 m3
Tétel              Mennyiség  Egység   Egységár   Bruttó
Ivóvíz díj         19         m3       400,00     7 600
Csatorna díj       19         m3       500,00     9 500
Alapdíj            2          hó       1 225,50   2 451
Fizetendő összeg:                                  19 551 Ft
"""

AI_VALASZ = {  # amit egy jól működő AI ad (a kitakart szövegből: MERO_1)
    "szolgaltato_nev": "PÉLDAVÍZ Víziközmű Zrt.", "szolgaltato_adoszam": "12345678-2-07", "kozmu": "viz",
    "sorszam": "PV-2026/004512", "kelte": "2026-10-05", "fizetesi_hatarido": "2026-10-20", "tipus": "elszamolo",
    "fizetendo": 19551, "idoszak_tol": "2026-08-01", "idoszak_ig": "2026-09-30",
    "merok": [{"gyari_szam": "MERO_1", "tol_datum": "2026-08-01", "tol_allas": 412, "ig_datum": "2026-09-30", "ig_allas": 431, "mod": "leolvasott"}],
    "mennyisegek": [{"megnevezes": "Ivóvíz", "mennyiseg": 19, "egyseg": "m3"}, {"megnevezes": "Csatorna", "mennyiseg": 19, "egyseg": "m3"}],
    "tetelek": [{"megnevezes": "Ivóvíz díj", "mennyiseg": 19, "egyseg": "m3", "egysegar": 400, "brutto": 7600},
                {"megnevezes": "Csatorna díj", "mennyiseg": 19, "egyseg": "m3", "egysegar": 500, "brutto": 9500},
                {"megnevezes": "Alapdíj", "mennyiseg": 2, "egyseg": "hó", "egysegar": "1 225,50", "brutto": "2 451"}],
}


def _tarolt(allas=400, nap="2026-07-31"):
    return {"szamlak": {}, "merok": [{"gyari_szam": "A77123456", "beepitve": "2020-01-01", "kezdo_allas": "0",
                                      "leolvasasok": [{"datum": nap, "allas": str(allas)}]}]}


def test_kitakaras_es_visszairas():
    kt = A.Kitakaro(ismert=["Minta Anna", "55443322"], merok=["A77123456"])
    ki = kt.kitakar(SZAMLA)
    for tilos in ("Minta Anna", "Példafalu", "Kitalált utca", "55443322", "minta.anna@example.com", "123 4567",
                  "11773000-00112233", "A77123456"):
        assert tilos not in ki, tilos
    # a szolgáltató adatai és a számlaadatok maradnak
    for marad in ("PÉLDAVÍZ", "12345678-2-07", "PV-2026/004512", "19 551", "2026.10.05"):
        assert marad in ki, marad
    assert "MERO_1" in ki and kt.kategoriak["mérőszám"] == 1
    vissza = kt.visszair({"merok": [{"gyari_szam": "MERO_1"}], "x": "KITAKART_1"})
    assert vissza["merok"][0]["gyari_szam"] == "A77123456"
    assert vissza["x"] in ("Minta Anna", "55443322")


def test_kitakaras_vezeto_nullas_meroszam_osszeg_nem():
    """A mérőszám vezető nullákkal is; a tagolt szám (összeg) nem – és a túl rövid mérőszám nem takarható ki."""
    kt = A.Kitakaro(merok=["35001"])
    assert kt.kitakar("Mérő: 0035001, összeg 35 001 Ft") == "Mérő: MERO_1, összeg 35 001 Ft"
    assert A.Kitakaro(merok=["1234"]).kitakar("Mérő: 1234, 1234 Ft") == "Mérő: 1234, 1234 Ft"


def test_kitakaras_felirat_kovetkezo_sorban_es_cim():
    s = "Vevő neve:\nKiss János\n   Számla kelte: 2026.10.05     Felhasználó neve: Nagy Éva\n2000 Szentendre, Fő tér 1."
    ki = A.Kitakaro().kitakar(s)
    for tilos in ("Kiss János", "Nagy Éva", "Szentendre", "Fő tér"):
        assert tilos not in ki, tilos
    assert "Számla kelte: 2026.10.05" in ki


def test_szam_szelsoseges():
    assert A.szam("Infinity") is None and A.szam("1e999999") is None and A.szam(float("inf")) is None and A.szam("0") == 0


def test_struktura_ervenyes_ai_task_es_openapi():
    from homeassistant.components.ai_task.services import _validate_structure_fields
    from homeassistant.helpers.llm import selector_serializer
    import probatio

    sema = _validate_structure_fields(A.STRUKTURA)
    oa = probatio.to_openapi(sema, custom_serializer=selector_serializer)
    assert oa["properties"]["merok"]["type"] == "array"
    assert "ig_allas" in oa["properties"]["merok"]["items"]["properties"]
    assert set(oa["required"]) >= {"sorszam", "kelte", "fizetendo"}


def test_normalizal_szamok_datumok():
    n = A.normalizal({"kelte": "2026. 10. 05.", "fizetendo": "19 551 Ft", "szamlaertek": "1.234,5", "tipus": "x",
                      "merok": [{"ig_allas": "431", "ig_datum": "2026.09.30.", "mod": "?"}], "tetelek": [{"megnevezes": "", "brutto": None}]})
    assert n["kelte"] == "2026-10-05" and n["fizetendo"] == 19551.0 and n["szamlaertek"] == 1234.5
    assert n["tipus"] == "egyeb" and n["merok"][0]["mod"] == "becsult" and n["tetelek"] == []
    assert A.datum("2026. október 5.") == date(2026, 10, 5)


def test_szamlava_viz():
    kt = A.Kitakaro(merok=["A77123456"])
    adat = A.normalizal(kt.visszair(AI_VALASZ))
    sz = A.szamlava(adat, "pv.pdf", _tarolt())
    assert sz.forras == "ai" and sz.osszeg == Decimal("19551") and sz.tipus == "elszamolo"
    assert str(sz.osszeg) == "19551" and str(A.szam(1225.5)) == "1225.5"  # tárolt alak: egész számként
    assert sz.idoszak == (date(2026, 8, 1), date(2026, 9, 30)) and sz.hatarido == date(2026, 10, 20)
    assert [(m.mero, m.datum, m.allas, m.lm) for m in sz.meroallasok] == [
        ("A77123456", date(2026, 8, 1), Decimal("412"), "Leol"), ("A77123456", date(2026, 9, 30), Decimal("431"), "Leol")]
    assert sz.elszamolt_viz["ivoviz"] == Decimal("19") and sz.elszamolt_viz["csatorna"] == Decimal("19")


def test_szamlava_mero_nelkul_az_aktiv_merore():
    adat = A.normalizal({**AI_VALASZ, "merok": [{"gyari_szam": "", "ig_datum": "2026-09-30", "ig_allas": 431, "mod": "diktalt"}]})
    sz = A.szamlava(adat, "pv.pdf", _tarolt())
    assert sz.meroallasok[0].mero == "A77123456" and sz.meroallasok[0].lm == "Dikt"


def test_szamlava_hianyzo_kotelezo():
    with pytest.raises(ValueError):
        A.szamlava(A.normalizal({**AI_VALASZ, "kelte": ""}), "x.pdf")


def _ell(adat, tarolt=None):
    return E.ellenoriz(A.normalizal(adat), SZAMLA, tarolt if tarolt is not None else _tarolt(), "viz")


def test_ellenorzes_jo_szamla():
    j = _ell(A.Kitakaro(merok=["A77123456"]).visszair(AI_VALASZ))
    assert j["_osszes"] == {"ellentmondas": 0, "figy": 0}, j
    assert j["fizetendo"]["jel"] == "ok" and j["merok.0.ig_allas"]["jel"] == "ok" and j["kelte"]["jel"] == "ok"
    assert j["tetelek.2.egysegar"]["jel"] == "ok"  # 1 225,50 tagolt tizedes


def test_ellenorzes_kitalalt_ertek_ellentmondas():
    rossz = {**AI_VALASZ, "fizetendo": 19651, "kelte": "2026-10-06"}
    j = _ell(rossz)
    assert j["fizetendo"]["jel"] == "ellentmondas" and j["kelte"]["jel"] == "ellentmondas"
    assert j["_osszes"]["ellentmondas"] >= 2


def test_ellenorzes_tetelek_osszege_es_szorzat():
    t = [dict(x) for x in AI_VALASZ["tetelek"]]
    t[0]["brutto"] = 7700  # nincs a szövegben, és a szorzat sem jön ki, és az összeg sem
    j = _ell({**AI_VALASZ, "tetelek": t})
    assert j["tetelek.0.brutto"]["jel"] == "ellentmondas"
    assert "egységár" in j["tetelek.0.brutto"]["uzenet"]
    assert j["fizetendo"]["jel"] == "figy" and "tételek" in j["fizetendo"]["uzenet"]


def test_ellenorzes_meroallas_visszafele_es_csokkeno():
    j = _ell(A.Kitakaro(merok=["A77123456"]).visszair(AI_VALASZ), _tarolt(allas=500))
    assert j["merok.0.ig_allas"]["jel"] == "ellentmondas" and "visszafelé" in j["merok.0.ig_allas"]["uzenet"]
    m = [{**AI_VALASZ["merok"][0], "gyari_szam": "A77123456", "tol_allas": 431, "ig_allas": 412}]
    j = _ell({**AI_VALASZ, "merok": m})
    assert "kisebb az indulónál" in j["merok.0.ig_allas"]["uzenet"]


def test_ellenorzes_mar_szerepel_es_ismeretlen_mero():
    t = _tarolt()
    t["szamlak"]["PV-2026/004512"] = {}
    j = _ell({**AI_VALASZ, "merok": [{**AI_VALASZ["merok"][0], "gyari_szam": "A77123456"}]}, t)
    assert j["sorszam"]["jel"] == "ellentmondas"
    t = _tarolt()
    t["merok"][0]["gyari_szam"] = "B1"
    j = _ell({**AI_VALASZ, "merok": [{**AI_VALASZ["merok"][0], "gyari_szam": "A77123456"}]}, t)
    assert j["merok.0.gyari_szam"]["jel"] == "figy"


def test_szamok_halmaz():
    s = E.szamok("Fizetendő: 19 551 Ft, egységár 1 225,50, 20.061 kWh, -1 200")
    assert {Decimal("19551"), Decimal("1225.50"), Decimal("20061"), Decimal("20.061"), Decimal("-1200"), Decimal("1200")} <= s


def test_panel_beallitas_ai():
    assert PB.alap()["ai_beolvasas"] is False
    assert PB.ervenyes({"ai_beolvasas": True, "ai_entitas": "ai_task.gemini"}) == {"ai_beolvasas": True, "ai_entitas": "ai_task.gemini"}
    with pytest.raises(ValueError):
        PB.ervenyes({"ai_entitas": "sensor.x"})
    with pytest.raises(ValueError):
        PB.ervenyes({"ai_beolvasas": "igen"})


def test_fuggo_szamlak_ai_tetel(tmp_path: Path):
    import custom_components.hu_rezsi.koordinator as K

    k = object.__new__(K.RezsiKoordinator)
    (tmp_path / "pv.pdf").write_bytes(b"%PDF-1.4")
    adat = A.normalizal(A.Kitakaro(merok=["A77123456"]).visszair(AI_VALASZ))
    ki = k._fuggo_szamlak(tmp_path, [{"fajl": "pv.pdf", "sorszam": adat["sorszam"], "ai": adat},
                                     {"fajl": "nincs.pdf", "sorszam": "x", "ai": adat}], _tarolt())
    assert len(ki) == 1 and ki[0].sorszam == "PV-2026/004512" and ki[0].forras == "ai"
