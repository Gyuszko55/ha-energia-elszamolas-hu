"""Diagnosztika: a fiókok beállításai, tárolt adatai és a számláló utolsó pontjai."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .koordinator import RezsiKoordinator


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    koord: RezsiKoordinator = entry.runtime_data
    fiokok = {}
    for sid, sub in koord.fiokok().items():
        a = (koord.data or {}).get(sid)
        fiokok[sub.title] = {
            "beallitas": dict(sub.data),
            "tarolt": koord.tarolo.fiok(sid),
            "hiba": a.hiba if a else None,
            "idoszak": [a.tol.isoformat(), a.ig.isoformat()] if a and a.tol else None,
            "napi_atlag": [str(x) for x in a.nyitott.napi_atlag] if a and a.nyitott else None,
            "szamlalo_utolso_pontok": [
                [p.ido.isoformat(), str(p.ertek), p.horgony] for p in (koord.utolso_szamlalok.get(sid) or [])
            ],
        }
    return {"fiokok": fiokok}
