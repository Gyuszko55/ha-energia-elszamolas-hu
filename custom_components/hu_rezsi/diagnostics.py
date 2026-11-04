"""Diagnosztika: a fiókok beállításai, a tárolt adatok összegzése és a számláló utolsó pontjai (személyes adatok nélkül)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import POSTAFIOK
from .koordinator import RezsiKoordinator

# Személyes / azonosító adatok: a számlák ügyfél-adatai (név, cím, azonosítók), mérő- és mérésipont-azonosítók,
# a számlamappa útvonala, a Díjnet-szolgáltató, a mentésben tárolt szenzornevek. A fiók (felhasználó adta) neve sem
# kerül a kimenetbe: a fiókokat az alfiók azonosítója kulcsolja.
REDACT = {
    "ugyfel", "nev", "cim", "hely", "azonosito", "ugyfelszam", "ugyfel_azonosito", "felhasznalasi_hely",
    "gyari_szam", "uj_gyari_szam", "mero", "szamla_merok", "meresi_pont", "meresi_pontok", "pod",
    "szamla_mappa", "dijnet_szolgaltato", "szenzor_nevek", "email",
    # E-mail fiók: a jelszó, a cím / felhasználónév, és a fiókok e-mailes szűrői (személyes feladó-cím, mérő, irsz.).
    "jelszo", "email_cim", "email_feladok", "email_mero", "email_irsz", "latott", "utolso_talalatok",
    # Felderítés: a kérdésekben / ajánlatokban mérőszám, sorszám és összeg, az üzenetekben fióknév.
    "email_felderites", "felderites", "kerdesek", "ajanlatok", "uzenetek",
}


DATUM_MEZOK = ("datum", "kelte", "tol", "ig", "ido", "rogzitve", "beepitve", "kiszerelve")


def _datumok(elemek: list[Any]) -> list[str] | None:
    """A rekordok dátum-mezőiből a legkorábbi és a legkésőbbi (ÉÉÉÉ-HH-NN), vagy None."""
    d = sorted(
        str(x[m])[:10] for x in elemek if isinstance(x, dict) for m in DATUM_MEZOK
        if isinstance(x.get(m), str) and len(x[m]) >= 10 and x[m][4] == "-"
    )
    return [d[0], d[-1]] if d else None


def _osszegzes(ertek: Any) -> Any:
    """Egy tárolt mező összegzése azonosítók nélkül: darabszám és dátumtartomány, a kulcsok (sorszámok, fájlnevek) nélkül."""
    if isinstance(ertek, bool) or isinstance(ertek, (int, float)) or ertek is None:
        return ertek
    if isinstance(ertek, str):
        return ertek[:10] if len(ertek) >= 10 and ertek[4:5] == "-" else "…"
    elemek = list(ertek.values()) if isinstance(ertek, dict) else list(ertek)
    return {"db": len(elemek), "datumok": _datumok(elemek)}


def _fiok_osszegzes(tarolt: dict[str, Any]) -> dict[str, Any]:
    """A fiók tárolt adatai összegezve: a számlák sorszámai, a fájlnevek, a mérőszámok és a mappák nem kerülnek bele."""
    ki: dict[str, Any] = {}
    for kulcs, ertek in tarolt.items():
        if kulcs == "szamlak" and isinstance(ertek, dict):
            szamlak = [x for x in ertek.values() if isinstance(x, dict)]
            tipusok: dict[str, int] = {}
            for x in szamlak:
                t = str(x.get("tipus") or "ismeretlen")
                tipusok[t] = tipusok.get(t, 0) + 1
            ki[kulcs] = {"db": len(szamlak), "tipusok": tipusok, "kezi": sum(1 for x in szamlak if x.get("kezi")),
                         "datumok": _datumok(szamlak)}
        elif kulcs == "merok" and isinstance(ertek, list):
            ki[kulcs] = [{"beepitve": str(m.get("beepitve") or "")[:10] or None,
                          "kiszerelve": str(m.get("kiszerelve") or "")[:10] or None,
                          "leolvasasok": _osszegzes(m.get("leolvasasok") or [])}
                         for m in ertek if isinstance(m, dict)]
        elif isinstance(ertek, dict) and kulcs.endswith("_beallitas"):
            ki[kulcs] = sorted(ertek)  # csak a beállított mezők neve
        else:
            ki[kulcs] = _osszegzes(ertek)
    return ki


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    koord: RezsiKoordinator = entry.runtime_data
    fiokok = {}
    for sid, sub in koord.fiokok().items():
        a = (koord.data or {}).get(sid)
        fiokok[sid] = {
            "beallitas": async_redact_data(dict(sub.data), REDACT),
            "tarolt": _fiok_osszegzes(koord.tarolo.fiok(sid) or {}),
            "hiba": a.hiba if a else None,
            "idoszak": [a.tol.isoformat(), a.ig.isoformat()] if a and a.tol else None,
            "napi_atlag": [str(x) for x in a.nyitott.napi_atlag] if a and a.nyitott else None,
            "szamlalo_utolso_pontok": [
                [p.ido.isoformat(), str(p.ertek), p.horgony] for p in (koord.utolso_szamlalok.get(sid) or [])
            ],
        }
    # E-mail fiókok: a beállítás (jelszó és cím nélkül) és az állapot (a látott levelek és a talált számlák nélkül).
    tarolt_pf = (getattr(koord.tarolo, "adat", None) or {}).get("postafiokok") or {}
    postafiokok = {
        sid: {
            "beallitas": async_redact_data(dict(sub.data), REDACT),
            "allapot": async_redact_data(dict(tarolt_pf.get(sid) or {}), REDACT),
        }
        for sid, sub in (getattr(entry, "subentries", None) or {}).items() if sub.subentry_type == POSTAFIOK
    }
    return {"fiokok": fiokok, "postafiokok": postafiokok}
