"""Részszámlák beolvasása a Díjnet-integráció kifizetett-számla fájljából (/config/.dijnet_paid_invoices_*.yaml).

Csak olvasunk; a fájl formátuma a Díjnet-integrációé: lista {provider, amount, issuance_date, invoice_no, ...}.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

_LOGGER = logging.getLogger(__name__)
_GYORSITO: dict[str, tuple[float, list[dict]]] = {}


def _betolt(fajl: Path) -> list[dict]:
    mtime = fajl.stat().st_mtime
    regi = _GYORSITO.get(str(fajl))
    if regi and regi[0] == mtime:
        return regi[1]
    adat = yaml.safe_load(fajl.read_text(encoding="utf-8")) or []
    _GYORSITO[str(fajl)] = (mtime, adat)
    return adat


def szolgaltatok(mappa: Path, minta: str) -> list[str]:
    nevek: set[str] = set()
    for fajl in mappa.glob(minta):
        try:
            nevek |= {x.get("provider") for x in _betolt(fajl) if x.get("provider")}
        except (OSError, yaml.YAMLError) as err:
            _LOGGER.warning("Díjnet-fájl nem olvasható (%s): %s", fajl, err)
    return sorted(nevek)


def szamlak(mappa: Path, minta: str, szolgaltato: str) -> list[tuple[date, Decimal, str]]:
    """(kelt, bruttó összeg, számlaszám) a megadott szolgáltatóra, számlaszám szerint egyedi."""
    lattuk: dict[str, tuple[date, Decimal, str]] = {}
    for fajl in mappa.glob(minta):
        try:
            for x in _betolt(fajl):
                if x.get("provider") != szolgaltato or x.get("amount") is None:
                    continue
                kelt = date.fromisoformat(str(x["issuance_date"])[:10])
                lattuk[str(x.get("invoice_no"))] = (kelt, Decimal(str(x["amount"])), str(x.get("invoice_no")))
        except (OSError, yaml.YAMLError, KeyError, ValueError) as err:
            _LOGGER.warning("Díjnet-fájl nem olvasható (%s): %s", fajl, err)
    return sorted(lattuk.values())
