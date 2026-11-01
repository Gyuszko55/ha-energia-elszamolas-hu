"""Diagnosztika: a fiókok beállításai, tárolt adatai és a számláló utolsó pontjai (személyes adatok nélkül)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .koordinator import RezsiKoordinator

# Személyes / azonosító adatok: a számlák ügyfél-adatai (név, cím, azonosítók), mérő- és mérésipont-azonosítók,
# a számlamappa útvonala, a Díjnet-szolgáltató, a mentésben tárolt szenzornevek. A fiók (felhasználó adta) neve sem
# kerül a kimenetbe: a fiókokat az alfiók azonosítója kulcsolja.
REDACT = {
    "ugyfel", "nev", "cim", "hely", "azonosito", "ugyfelszam", "ugyfel_azonosito", "felhasznalasi_hely",
    "gyari_szam", "uj_gyari_szam", "mero", "szamla_merok", "meresi_pont", "meresi_pontok", "pod",
    "szamla_mappa", "dijnet_szolgaltato", "szenzor_nevek", "email",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    koord: RezsiKoordinator = entry.runtime_data
    fiokok = {}
    for sid, sub in koord.fiokok().items():
        a = (koord.data or {}).get(sid)
        fiokok[sid] = {
            "beallitas": async_redact_data(dict(sub.data), REDACT),
            "tarolt": async_redact_data(koord.tarolo.fiok(sid), REDACT),
            "hiba": a.hiba if a else None,
            "idoszak": [a.tol.isoformat(), a.ig.isoformat()] if a and a.tol else None,
            "napi_atlag": [str(x) for x in a.nyitott.napi_atlag] if a and a.nyitott else None,
            "szamlalo_utolso_pontok": [
                [p.ido.isoformat(), str(p.ertek), p.horgony] for p in (koord.utolso_szamlalok.get(sid) or [])
            ],
        }
    return {"fiokok": fiokok}
