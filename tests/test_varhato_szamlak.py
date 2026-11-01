"""Várható (még nem érkezett) számlák a számlakimutatáshoz (szintetikus fiók-adatok; HA nélkül)."""

from datetime import date

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from varhato_szamlak import szamla_keses, varhato_szamlak

MA = date(2026, 10, 4)
# Havi elszámoló, az időszak vége után 5 nappal kel.
SZAMLAK = {
    "1": {"kelte": "2026-08-09", "idoszak": ["2026-07-05", "2026-08-04"], "osszeg": "1500", "tipus": "elszamolo"},
    "2": {"kelte": "2026-09-09", "idoszak": ["2026-08-04", "2026-09-04"], "osszeg": "1828", "tipus": "elszamolo"},
}


def test_keses_a_szamlakbol_es_alapertek():
    assert szamla_keses(SZAMLAK) == 5
    assert szamla_keses({}) == 10


def test_mert_fiok_folyo_idoszaka_a_sajat_meresbol():
    # Az előző számla időszaka a folyó időszak első napján ér véget: ez nem átfedés.
    f = {"idoszak": {"tol": "2026-09-04", "ig": "2026-10-07"}, "varhato": {"osszeg": 1881}}
    v = varhato_szamlak(f, SZAMLAK, MA)
    assert v == [{"kelte": "2026-10-11", "honap": "2026-10", "tol": "2026-09-04", "ig": "2026-10-06", "osszeg": 1881, "forras": "meres"}]


def test_mert_fiok_mar_szamlazott_idoszaka_nem_varhato():
    f = {"idoszak": {"tol": "2026-08-04", "ig": "2026-09-05"}, "varhato": {"osszeg": 900}}
    assert varhato_szamlak(f, SZAMLAK, MA) == []


def test_uton_levo_szamla_es_elmaradt_a_mai_honapba():
    f = {"uton_szamlak": [{"tol": "2026-08-01", "ig": "2026-08-31", "osszeg": 5000}], "megszunt": {"datum": "2026-09-01"},
         "idoszak": {"tol": "2026-09-01", "ig": "2026-10-01"}, "varhato": {"osszeg": 1}}
    v = varhato_szamlak(f, {}, MA)
    assert [(x["kelte"], x["osszeg"], x["forras"]) for x in v] == [("2026-10-04", 5000, "meres")]


def test_atalany_kovetkezo_reszszamla_es_eves_elszamolas():
    f = {"reszszamlas": True, "idoszak": {"tol": "2026-09-29", "ig": "2026-11-14"},
         "esedekes": {"kovetkezo_datum": "2026-10-21", "kovetkezo_osszeg": 13467},
         "egyenleg": {"egyenleg": 847, "ev_tol": "2025-11-14"}, "utem": {"kovetkezo_elszamolas": "2026-11-14"}}
    v = varhato_szamlak(f, SZAMLAK, MA)
    assert [(x["kelte"], x["osszeg"], x["forras"]) for x in v] == [
        ("2026-10-21", 13467, "atalany"), ("2026-11-19", -847, "elszamolas")]


def test_diktalt_atalany_es_tavoli_elszamolas_kimarad():
    f = {"reszszamlas": True, "esedekes": {"kovetkezo_datum": "2026-10-15", "kovetkezo_osszeg": 9000},
         "diktalt_szamla": {"tol": "2026-09-10", "datum": "2026-10-05", "osszeg": 7300},
         "egyenleg": {"egyenleg": -2000}, "utem": {"kovetkezo_elszamolas": "2027-09-29"}}
    v = varhato_szamlak(f, {}, MA)
    assert [(x["osszeg"], x["forras"], x["tol"]) for x in v] == [(7300, "diktalas", "2026-09-10")]


def test_fix_dij_a_szamlazasi_ablakkal_es_nincs_tobb():
    f = {"fix_dij": True, "esedekes": {"kovetkezo_datum": "2026-10-08", "kovetkezo_osszeg": 5772},
         "szamlazasi": {"tol": "2026-07-01", "ig": "2026-10-01", "kiallitott": False}}
    assert varhato_szamlak(f, {}, MA) == [
        {"kelte": "2026-10-08", "honap": "2026-10", "tol": "2026-07-01", "ig": "2026-09-30", "osszeg": 5772, "forras": "fix"}]
    f["esedekes"]["nincs_tobb"] = True
    assert varhato_szamlak(f, {}, MA) == []
