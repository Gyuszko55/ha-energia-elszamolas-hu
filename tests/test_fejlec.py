"""A fiókkártya fejléce: következő számla · folyó időszak · egyenleg – számlázási módonként (HA nélkül)."""

from datetime import date

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from fejlec import fejlec, folyo_idoszak, kovetkezo_szamla

MA = date(2026, 10, 8)
SZAMLAK = {"1": {"kelte": "2026-09-18", "idoszak": ["2026-08-14", "2026-09-13"], "osszeg": "9000", "tipus": "elszamolo"}}
MERT = {
    "idoszak": {"tol": "2026-09-14", "ig": "2026-10-14", "honapok": 1},
    "eddig": {"osszeg": 6000, "becsult": False},
    "varhato": {"osszeg": 7500, "eltelt_nap": 24.4, "hatralevo_nap": 5.6, "napi_atlag": 6.9},
    "esedekes": {"kovetkezo_datum": "2026-10-18", "kovetkezo_osszeg": 7500},
}


def test_mert_fiok_szenzorral():
    k = kovetkezo_szamla(MERT | {"szenzor": True}, SZAMLAK, MA)
    assert (k["dij"], k["fizetendo"], k["cimke"], k["folyo"]) == (7500, 7500, "mert", True)
    assert "6 napra" in k["magyarazat"]
    fo = folyo_idoszak(MERT | {"szenzor": True})
    assert (fo["eddig"], fo["varhato"], fo["eltelt_nap"], fo["napok"], fo["tajekoztato"]) == (6000, 7500, 24, 30, False)


def test_mert_fiok_szenzor_nelkul_becsult():
    assert kovetkezo_szamla(MERT, SZAMLAK, MA)["cimke"] == "becsult"
    # Szenzor van, de kiesett: a motor becsültnek jelöli az „eddig”-et.
    f = MERT | {"szenzor": True, "eddig": {"osszeg": 6000, "becsult": True}}
    assert kovetkezo_szamla(f, SZAMLAK, MA)["cimke"] == "becsult"


def test_lezart_idoszak_szamla_nelkul_pontos():
    f = MERT | {"szenzor": True, "uton_szamlak": [
        {"tol": "2026-09-14", "ig": "2026-10-07", "osszeg": 0, "osszeg_brutto": 7100, "levonva": 7100, "mennyiseg": 160}]}
    k = kovetkezo_szamla(f, SZAMLAK, MA)
    assert (k["dij"], k["fizetendo"], k["cimke"], k["tol"], k["ig"]) == (7100, 0, "pontos", "2026-09-14", "2026-10-07")


def test_atalany_pontos_es_folyo_tajekoztato():
    f = MERT | {"reszszamlas": True, "szenzor": True,
                "szamlazasi": {"tol": "2026-10-01", "ig": "2026-11-01", "fizetendo": 13654, "kiallitott": False},
                "esedekes": {"kovetkezo_datum": "2026-10-20", "kovetkezo_osszeg": 13654}}
    k = kovetkezo_szamla(f, SZAMLAK, MA)
    assert (k["dij"], k["cimke"], k["forras"], k["ig"]) == (13654, "pontos", "atalany", "2026-10-31")
    assert folyo_idoszak(f)["tajekoztato"] is True


def test_atalany_diktalt_allas_felulirja():
    f = MERT | {"reszszamlas": True, "szamlazasi": {"tol": "2026-10-01", "ig": "2026-11-01", "kiallitott": True},
                "esedekes": {"kovetkezo_datum": "2026-10-20", "kovetkezo_osszeg": 13654},
                "diktalt_szamla": {"tol": "2026-09-14", "datum": "2026-10-10", "osszeg": 8800, "becsult": False}}
    k = kovetkezo_szamla(f, SZAMLAK, MA)
    assert (k["dij"], k["cimke"], k["forras"]) == (8800, "pontos", "diktalas")


def test_diktalas_szerint_becsult_diktalas():
    f = MERT | {"reszszamlas": True, "diktalas_szerint": True, "szenzor": True,
                "diktalt_szamla": {"tol": "2026-09-14", "datum": "2026-10-11", "osszeg": 7300, "becsult": True}}
    k = kovetkezo_szamla(f, SZAMLAK, MA)
    assert (k["dij"], k["cimke"], k["ig"]) == (7300, "mert", "2026-10-11")


def test_fix_dij_negyedeves_messze_is():
    f = MERT | {"fix_dij": True, "szamlazasi": {"tol": "2026-10-01", "ig": "2027-01-01", "kiallitott": False},
                "esedekes": {"kovetkezo_datum": "2027-01-15", "kovetkezo_osszeg": 12000}}
    k = kovetkezo_szamla(f, SZAMLAK, MA)
    assert (k["dij"], k["cimke"], k["kelte"]) == (12000, "pontos", "2027-01-15")
    assert folyo_idoszak(f)["cimke"] == "pontos"


def test_tulfizetes_beszamitasa():
    f = MERT | {"szenzor": True, "beszamitas": {"szamlak": [{"dij": 7500, "fizetendo": 0, "idoszak": None}]}}
    k = kovetkezo_szamla(f, SZAMLAK, MA)
    assert (k["dij"], k["fizetendo"]) == (7500, 0)


def test_szunetel_es_megszunt():
    assert kovetkezo_szamla(MERT | {"esedekes": {"szunetel": True}}, SZAMLAK, MA) is None
    f = MERT | {"megszunt": {"datum": "2026-09-30"}, "esedekes": {"nincs_tobb": True}}
    assert kovetkezo_szamla(f, SZAMLAK, MA) is None
    assert folyo_idoszak(f) is None


def test_fejlec_egyenleg_atmegy():
    fj = fejlec(MERT, SZAMLAK, MA, {"osszeg": -7382, "kozos": "A1 + H"})
    assert fj["egyenleg"] == {"osszeg": -7382, "kozos": "A1 + H"}


def test_atalany_kiallitott_utani_resz_idoszaka_az_utembol():
    f = MERT | {"reszszamlas": True, "utem": {"szamlazas_honap": 1},
                "szamlazasi": {"tol": "2026-09-14", "ig": "2026-10-14", "kiallitott": True},
                "esedekes": {"kovetkezo_datum": "2026-10-20", "kovetkezo_osszeg": 980}}
    k = kovetkezo_szamla(f, SZAMLAK, MA)
    assert (k["tol"], k["ig"], k["dij"], k["forras"]) == ("2026-09-14", "2026-10-13", 980, "atalany")


def test_szaldo_atalany_netto_mennyiseg():
    f = MERT | {"reszszamlas": True, "eddig": {"osszeg": 2240, "becsult": False, "mennyiseg": 61.6},
                "varhato": {**MERT["varhato"], "mennyiseg": 249.6},
                "atalany": {"betaplalas": {"eddig": 27, "varhato": 170.9}}}
    fo = folyo_idoszak(f)
    assert (fo["eddig"], fo["eddig_netto"], fo["varhato_netto"]) == (None, 34.6, 78.7)


def test_fix_dij_honap_az_egyseg():
    f = {"fix_dij": True, "idoszak": {"tol": "2026-10-01", "ig": "2027-01-01", "honapok": 3},
         "eddig": {"osszeg": 497}, "varhato": {"osszeg": 5772, "eltelt_nap": 8, "hatralevo_nap": 84}}
    fo = folyo_idoszak(f, date(2026, 10, 8))
    assert (fo["eddig"], fo["varhato"], fo["eltelt_honap"], fo["honapok"]) == (1924, 5772, 1, 3)
    assert folyo_idoszak(f, date(2026, 11, 15))["eddig"] == 3848
    assert folyo_idoszak(f, date(2026, 12, 31))["eddig"] == 5772
    havi = f | {"idoszak": {"tol": "2026-10-01", "ig": "2026-11-01", "honapok": 1}, "varhato": {"osszeg": 9689}}
    assert (folyo_idoszak(havi, date(2026, 10, 8))["eddig"], folyo_idoszak(havi, date(2026, 10, 8))["honapok"]) == (9689, 1)
