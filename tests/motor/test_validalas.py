"""A díjszabás „szamlaval_egyezik” állapotához kötelező validálási adatok (szolgáltató, mód, számlatípus, számlák)."""
from datetime import date

import pytest

from motor.dijszabas import DijszabasHiba, _validalas_hiba, ellenoriz

JO = {"hely": "X", "szolgaltato": "mvm_demasz", "elszamolas": "diktalas", "szamla_tipusok": ["havi"], "szamlak": 3, "forintra": 3}


def _adat(azon, ell):
    return {"azonosito": azon, "nev": "n", "kozmu": "villany", "egyseg": "kWh",
            "verziok": [{"ervenyes_tol": date(2024, 1, 1), "forras": "f", "ellenorzes": ell, "dijak": {"alap": {}}}]}


def test_szamlaval_egyezik_validalas_nelkul_hiba():
    with pytest.raises(DijszabasHiba, match="validalas"):
        ellenoriz(_adat("villany/a1", {"allapot": "szamlaval_egyezik", "datum": date(2026, 10, 5), "mivel": "x"}))
    ellenoriz(_adat("villany/a1", {"allapot": "szamlaval_egyezik", "datum": date(2026, 10, 5), "mivel": "x", "validalas": [JO]}))
    # más állapotnál nem kötelező
    ellenoriz(_adat("villany/a2", {"allapot": "arlapbol", "datum": date(2026, 10, 5), "mivel": "x"}))


def test_validalas_mezok():
    assert _validalas_hiba("villany/a1", [JO]) is None
    assert "elszámolási mód" in _validalas_hiba("villany/a1", [JO | {"elszamolas": "valami"}])
    assert "számlatípus" in _validalas_hiba("villany/a1", [JO | {"szamla_tipusok": []}])
    assert "egész" in _validalas_hiba("villany/a1", [JO | {"forintra": 4}])
    assert "szolgáltató" in _validalas_hiba("villany/a1", [JO | {"szolgaltato": ""}])


def test_hmke_szaldo_vagy_brutto_kotelezo():
    assert "szaldo" in _validalas_hiba("villany/hmke", [JO])
    assert _validalas_hiba("villany/hmke", [JO | {"hmke": "szaldo"}]) is None
