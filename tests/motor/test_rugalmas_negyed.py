"""D árszabás: negyedórás árak az MVM-listából és a HUPX-ból (az MVM képletével)."""

import pytest
from motor.rugalmas import (
    arfolyam_napra,
    hupx_negyed_arak,
    mnb_arfolyamok,
    negyed_ora_atlag,
    sorok_negyed_arak,
)


def test_mvm_sorok_negyedorasan():
    n = sorok_negyed_arak(["2026.08.04 0:00 0:15 94,33", "2026.08.04 0:15 0:30 89,29", "2026.04.26 12:15 12:30 -114,73", "Edd"])
    assert n == {"2026-08-04T00:00": 94.33, "2026-08-04T00:15": 89.29, "2026-04-26T12:15": -114.73}
    assert negyed_ora_atlag(n)["2026-08-04T00"] == 91.81


def test_hupx_az_mvm_listaval_egyezik():
    # MVM-lista 2026.08.04 0:00 = 94,33; 08.01 (szombat, a péntek 07.31-i árfolyammal) = 80,60
    arf = {"2026-07-31": 362.99, "2026-08-03": 363.58, "2026-08-04": 363.84}
    out = hupx_negyed_arak(["2026-08-04T00:00", "2026-08-01T00:00", "2026-08-02T00:00", "2026-08-04T00:15"],
                           [221.62, 184.29, 188.98, None], arf, 13.70)
    assert out == {"2026-08-04T00:00": 94.33, "2026-08-01T00:00": 80.60, "2026-08-02T00:00": 82.30}


def test_arfolyam_munkaszuneti_napra():
    arf = {"2026-07-31": 362.99}
    assert arfolyam_napra(arf, "2026-08-02") == 362.99
    assert arfolyam_napra(arf, "2026-07-30") is None


# --- MNB-árfolyam: szigorú ellenőrzés (HTTP-végpont) -------------------------------------------------------------

def _mnb(eredmeny: str) -> str:
    from xml.sax.saxutils import escape

    return ('<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            '<soap:Body><GetExchangeRatesResponse xmlns="http://www.mnb.hu/webservices/"><GetExchangeRatesResult>'
            f"{escape(eredmeny)}</GetExchangeRatesResult></GetExchangeRatesResponse></soap:Body></soap:Envelope>")


def test_mnb_valasz_ervenyes():
    v = _mnb('<MNBExchangeRates><Day date="2026-10-30"><Rate unit="1" curr="EUR">386,44</Rate></Day>'
             '<Day date="2026-10-29"><Rate unit="1" curr="EUR">387,1</Rate></Day></MNBExchangeRates>')
    assert mnb_arfolyamok(v) == {"2026-10-30": 386.44, "2026-10-29": 387.1}


@pytest.mark.parametrize("valasz", [
    "<html>hiba</html>",  # nem SOAP
    "<soap:Envelope>",  # nem jól formált
    _mnb('<MNBExchangeRates><Day date="2026-10-30"><Rate unit="1" curr="EUR">3,86</Rate></Day></MNBExchangeRates>'),
    _mnb('<MNBExchangeRates><Day date="2026-10-30"><Rate unit="1" curr="EUR">NaN</Rate></Day></MNBExchangeRates>'),
    _mnb('<MNBExchangeRates><Day date="2026-10-30"><Rate unit="1" curr="EUR">inf</Rate></Day></MNBExchangeRates>'),
    _mnb('<MNBExchangeRates><Day date="2026-10-30"><Rate unit="1" curr="EUR">-386</Rate></Day></MNBExchangeRates>'),
    _mnb('<MNBExchangeRates><Day date="2026-13-45"><Rate unit="1" curr="EUR">386,44</Rate></Day></MNBExchangeRates>'),
    _mnb('<MNBExchangeRates><Day date="2026-10-30"><Rate unit="1" curr="EUR">386,44</Rate></Day>'),  # csonka
])
def test_mnb_hibas_valasz_eldobva(valasz):
    with pytest.raises(ValueError):
        mnb_arfolyamok(valasz)
