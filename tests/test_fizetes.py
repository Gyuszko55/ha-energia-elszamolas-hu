"""Számlák pénzügyi teljesítése (fizetes.py)."""
from datetime import date

import tests.conftest  # noqa: F401
from fizetes import allapot, osszesito

MA = date(2026, 10, 6)
DN = {"111": {"fizetve": "2026-09-20", "hatarido": "2026-09-24"}, "222": {"fizetve": None, "hatarido": "2026-09-01"}}


def test_dijnet_kezi_es_nincs_fizetendo():
    a = allapot("111", {"osszeg": "5000", "tipus": "resz"}, None, DN, MA)
    assert (a["fizetve"], a["datum"], a["forras"], a["hatarido"], a["lejart"]) == (True, "2026-09-20", "dijnet", "2026-09-24", False)
    # a kézi bejegyzés erősebb a Díjnetnél
    k = allapot("111", {"osszeg": "5000"}, {"fizetve": False}, DN, MA)
    assert (k["fizetve"], k["forras"], k["lejart"]) == (False, "kezi", True)
    # a számla saját határideje erősebb; lejárt, ha nincs fizetve
    l_ = allapot("333", {"osszeg": "100", "hatarido": "2026-10-01"}, None, DN, MA)
    assert l_["lejart"] and l_["hatarido"] == "2026-10-01"
    # visszatérítés / folyószámláról rendezett / sztornó: nincs fizetendő
    assert allapot("444", {"osszeg": "-48129"}, None, DN, MA)["nincs_fizetendo"]
    assert allapot("445", {"osszeg": "0", "tipus": "storno"}, None, DN, MA)["nincs_fizetendo"]
    # vezető nullák nélkül is megtalálja a Díjnetben
    assert allapot("0111", {"osszeg": "1"}, None, DN, MA)["fizetve"]


def test_osszesito_csak_friss():
    lista = [allapot("222", {"osszeg": "7000"}, None, DN, MA),                          # lejárt, 35 napja
             allapot("555", {"osszeg": "3000", "hatarido": "2026-10-20"}, None, DN, MA),  # nyitott, még nem járt le
             allapot("666", {"osszeg": "9000", "hatarido": "2026-06-01"}, None, DN, MA)]  # 90 napnál régebbi: nem jelezzük
    o = osszesito(lista, MA)
    assert (o["nyitott_db"], o["nyitott_ft"], o["lejart_db"], o["lejart_ft"], o["kovetkezo_hatarido"]) == (2, 10000, 1, 7000, "2026-10-20")


def test_folyoszamlarol_rendezett_reszszamla():
    # MVM: 991 Ft-os részszámla, a közös folyószámla túlfizetése után −47 138 Ft fizetendő – nincs mit fizetni.
    x = {"tipus": "resz", "osszeg": "991", "szamlaertek": "991", "egyeb_tetelek": [["Egyéb fizetendőt csökkentő tétel", "-30477"], ["Túlfizetés", "-17652"]],
         "hatarido": "2026-09-14"}
    a = allapot("845", x, None, {}, MA)
    assert a["nincs_fizetendo"] and not a["lejart"] and a["osszeg"] == -47138


def test_beszedesi_megbizas_hataridon_fizetett():
    """Távhő (HVSZ): „Beszed.megbízás” fizetési módnál a határidő napján fizetettnek vesszük; előtte nyitott, kézi
    jelölés felülírja."""
    from datetime import date
    from fizetes import allapot
    sz = {"osszeg": "494", "tipus": "resz", "hatarido": "2026-08-31", "fizetesi_mod": "Beszed.megbízás"}
    a = allapot("H1", sz, None, None, date(2026, 10, 6))
    assert a["fizetve"] and a["forras"] == "beszedes" and a["datum"] == "2026-08-31" and not a["lejart"]
    assert not allapot("H1", sz, None, None, date(2026, 8, 30))["fizetve"]
    assert allapot("H1", sz, {"fizetve": False}, None, date(2026, 10, 6))["lejart"]


def test_allando_atutalas():
    """Állandó átutalás a hónap 16-án; munkaszüneti napon az utána következő első munkanapon."""
    from datetime import date

    from fizetes import utemezett_nap

    assert utemezett_nap(date(2026, 10, 1), 16) == date(2026, 10, 16)   # péntek
    assert utemezett_nap(date(2026, 8, 1), 16) == date(2026, 8, 17)     # vasárnap → hétfő
    assert utemezett_nap(date(2026, 5, 1), 16) == date(2026, 5, 18)     # szombat → hétfő
    assert utemezett_nap(date(2026, 3, 1), 16) == date(2026, 3, 16)     # hétfő (03-15 az ünnep)
    assert utemezett_nap(date(2026, 10, 20), 16) == date(2026, 11, 16)  # a kelte után: következő hónap
    assert utemezett_nap(date(2026, 2, 1), 31) == date(2026, 3, 2)      # 02-28 szombat → hétfő
    sz = {"kelte": "2026-10-01", "osszeg": "12960", "hatarido": "2026-10-10"}
    a = allapot("KK-2026-10", sz, None, None, date(2026, 10, 12), 16)
    assert (a["fizetve"], a["lejart"], a["utemezett"]) == (False, False, "2026-10-16")
    a = allapot("KK-2026-10", sz, None, None, date(2026, 10, 16), 16)
    assert (a["fizetve"], a["datum"], a["forras"]) == (True, "2026-10-16", "utemezett")
    a = allapot("KK-2026-10", sz, {"fizetve": True, "datum": "2026-10-05"}, None, date(2026, 10, 16), 16)
    assert (a["datum"], a["forras"]) == ("2026-10-05", "kezi")  # a kézi rögzítés erősebb
    a = allapot("KK-2026-10", sz, None, None, date(2026, 10, 12))
    assert a["lejart"]  # állandó átutalás nélkül a határidő számít
    from fizetes import osszesito
    o = osszesito([allapot("KK-2026-10", sz, None, None, date(2026, 10, 12), 16)], date(2026, 10, 12))
    assert (o["nyitott_ft"], o["lejart_db"], o["kovetkezo_hatarido"]) == (12960, 0, "2026-10-16")
