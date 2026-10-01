"""Szolgáltatások: leolvasás, mérőcsere, felülírás, napló, CSV-export, v1-import."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.util import slugify

from .const import DOMAIN
from .koordinator import RezsiKoordinator
from .modell import d
from .v1_import import v1_import

TIPUSOK = ["kezi", "szolgaltatoi"]


def _celpont(hass: HomeAssistant, device_id: str) -> tuple[RezsiKoordinator, str]:
    eszkoz = dr.async_get(hass).async_get(device_id)
    if eszkoz is None:
        raise ServiceValidationError(f"Ismeretlen eszköz: {device_id}")
    sid = next((i[1] for i in eszkoz.identifiers if i[0] == DOMAIN), None)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED and sid in entry.subentries:
            return entry.runtime_data, sid
    raise ServiceValidationError("Az eszköz nem egy Rezsikövető-fiók (a háztartás-eszköz nem választható).")


def _aktiv_mero(tarolt: dict[str, Any], nap: date) -> dict[str, Any]:
    for m in reversed(tarolt["merok"]):
        if d(m["beepitve"]) <= nap and (m.get("kiszerelve") is None or nap <= d(m["kiszerelve"])):
            return m
    raise ServiceValidationError(f"{nap} napon nincs beépített mérő ebben a fiókban.")


async def _ment(koord: RezsiKoordinator) -> None:
    await koord.tarolo.ment()
    await koord.async_request_refresh()


async def leolvasas_rogzites(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    nap: date = call.data["datum"]
    allas = Decimal(str(call.data["allas"]))
    csatorna = call.data.get("csatorna", "vetelezes")
    if csatorna == "almero":
        if not tarolt.get("almero_merok"):
            raise ServiceValidationError("Ennek a fióknak nincs almérője.")
        mero = _aktiv_mero({"merok": tarolt["almero_merok"]}, nap)
        csatorna = "vetelezes"  # az almérő saját mérője: a fő regiszterébe kerül
    else:
        mero = _aktiv_mero(tarolt, nap)
    kezdo = mero.get("kezdo_betaplalas" if csatorna == "betaplalas" else "kezdo_allas") or 0
    if allas < Decimal(str(kezdo)):
        raise ServiceValidationError("Az állás kisebb, mint a mérő kezdőállása.")
    for lo in mero["leolvasasok"]:
        if lo.get("csatorna", "vetelezes") != csatorna:
            continue
        ld, la = d(lo["datum"]), Decimal(lo["allas"])
        if (ld < nap and la > allas) or (ld > nap and la < allas):
            raise ServiceValidationError(
                f"Az állás nem illeszkedik a {lo['datum']}-i {lo['allas']} leolvasáshoz (a mérő nem mehet visszafelé)."
            )
    tipus = call.data.get("tipus", "kezi")
    mero["leolvasasok"] = [
        lo
        for lo in mero["leolvasasok"]
        if not (lo["datum"] == nap.isoformat() and lo.get("tipus") == tipus and lo.get("csatorna", "vetelezes") == csatorna)
    ] + [
        {
            "datum": nap.isoformat(),
            "allas": str(allas),
            "tipus": tipus,
            "elszamolasi": call.data.get("elszamolasi", False),
            "megjegyzes": call.data.get("megjegyzes", ""),
            "csatorna": csatorna,
        }
    ]
    mero["leolvasasok"].sort(key=lambda x: x["datum"])
    await _ment(koord)


async def leolvasas_torles(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    nap = call.data["datum"].isoformat()
    torolt = 0
    for m in koord.tarolo.fiok(sid)["merok"]:
        elotte = len(m["leolvasasok"])
        m["leolvasasok"] = [lo for lo in m["leolvasasok"] if lo["datum"] != nap]
        torolt += elotte - len(m["leolvasasok"])
    if not torolt:
        raise ServiceValidationError(f"{nap} napon nincs leolvasás.")
    await _ment(koord)


async def merocsere(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    nap: date = call.data["datum"]
    if call.data.get("csatorna") == "almero":
        if not tarolt.get("almero_merok"):
            raise ServiceValidationError("Ennek a fióknak nincs almérője.")
        tarolt = {"merok": tarolt["almero_merok"]}  # ugyanaz a lista, helyben módosul
    regi = _aktiv_mero(tarolt, nap)
    if regi.get("kiszerelve") is not None or d(regi["beepitve"]) >= nap:
        raise ServiceValidationError("A mérőcsere napja a mostani mérő beépítése utáni nap kell legyen.")
    regi["kiszerelve"] = nap.isoformat()
    regi["zaro_allas"] = str(call.data["regi_zaro_allas"])
    tarolt["merok"].append(
        {
            "gyari_szam": call.data.get("uj_gyari_szam", ""),
            "beepitve": nap.isoformat(),
            "kezdo_allas": str(call.data.get("uj_kezdo_allas", 0)),
            "kiszerelve": None,
            "zaro_allas": None,
            "leolvasasok": [],
        }
    )
    await _ment(koord)


async def feluliras(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    kulcs, tol = call.data["kulcs"], call.data["ervenyes_tol"].isoformat()
    if not (kulcs.startswith("dijak.") or kulcs.startswith("szabalyok.")):
        raise ServiceValidationError("A kulcs „dijak.” vagy „szabalyok.” kezdetű legyen, pl. dijak.energia_piaci.")
    lista = [f for f in tarolt["feluliras"] if not (f["kulcs"] == kulcs and f["ervenyes_tol"] == tol)]
    if call.data.get("ertek") is not None:
        lista.append({"kulcs": kulcs, "ertek": str(call.data["ertek"]), "ervenyes_tol": tol})
    tarolt["feluliras"] = lista
    await _ment(koord)


async def futoertek_rogzites(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    honap = call.data["honap"]
    if not re.fullmatch(r"\d{4}-\d{2}", honap):
        raise ServiceValidationError("A hónap formátuma ÉÉÉÉ-HH, pl. 2026-08.")
    tarolt = koord.tarolo.fiok(sid)
    tarolt.setdefault("futoertekek", {})
    if call.data.get("ertek") is None:
        tarolt["futoertekek"].pop(honap, None)
    else:
        tarolt["futoertekek"][honap] = str(call.data["ertek"])
    await _ment(koord)


async def reszszamla_rogzites(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    nap = call.data["datum"].isoformat()
    tarolt["reszszamlak"] = [r for r in tarolt.get("reszszamlak", []) if r["datum"] != nap] + [
        {"datum": nap, "osszeg": str(call.data["osszeg"]), "megjegyzes": call.data.get("megjegyzes", "")}
    ]
    tarolt["reszszamlak"].sort(key=lambda r: r["datum"])
    await _ment(koord)


async def reszszamla_torles(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    nap = call.data["datum"].isoformat()
    elotte = len(tarolt.get("reszszamlak", []))
    tarolt["reszszamlak"] = [r for r in tarolt.get("reszszamlak", []) if r["datum"] != nap]
    if len(tarolt["reszszamlak"]) == elotte:
        raise ServiceValidationError(f"{nap} napon nincs kézzel rögzített részszámla (a Díjnet-számlák nem törölhetők innen).")
    await _ment(koord)


async def naplo(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    return {
        "lezart_idoszakok": sorted(tarolt["lezart"], key=lambda x: x["tol"]),
        "merok": tarolt["merok"],
        "feluliras": tarolt["feluliras"],
        "futoertekek": tarolt.get("futoertekek", {}),
        "reszszamlak": tarolt.get("reszszamlak", []),
        "almero_merok": tarolt.get("almero_merok", []),
        "szamlak": tarolt.get("szamlak", {}),
    }


async def csv_export(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    nev = slugify(koord.fiokok()[sid].title)
    mappa = Path(hass.config.path(DOMAIN))

    def iras() -> list[str]:
        mappa.mkdir(exist_ok=True)
        fajlok = []
        for fajlnev, fejlec, sorok in (
            (
                f"{nev}_idoszakok.csv",
                ["tol", "ig", "mennyiseg", "energia_ft", "alapdij_ft", "osszesen_ft", "becsult", "forras"],
                sorted(tarolt["lezart"], key=lambda x: x["tol"]),
            ),
            (
                f"{nev}_leolvasasok.csv",
                ["mero", "datum", "allas", "tipus", "elszamolasi", "megjegyzes"],
                [lo | {"mero": m.get("gyari_szam", "")} for m in tarolt["merok"] for lo in m["leolvasasok"]],
            ),
        ):
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=fejlec, extrasaction="ignore", delimiter=";")
            w.writeheader()
            w.writerows(sorok)
            (mappa / fajlnev).write_text(buf.getvalue(), encoding="utf-8-sig")
            fajlok.append(str(mappa / fajlnev))
        return fajlok

    return {"fajlok": await hass.async_add_executor_job(iras)}


async def import_v1(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    celok = {}
    for mero, kulcs in (("A", "a_fiok"), ("H", "h_fiok"), ("G", "gaz_fiok")):
        if call.data.get(kulcs):
            celok[mero] = _celpont(hass, call.data[kulcs])
    if not celok:
        raise ServiceValidationError("Legalább egy célfiókot meg kell adni.")
    jelentes = v1_import(hass, celok, call.data.get("probafuttatas", True))
    if not call.data.get("probafuttatas", True):
        for koord in {k for k, _ in celok.values()}:
            await _ment(koord)
    return jelentes


DEV = vol.Required("device_id")


def regisztral(hass: HomeAssistant) -> None:
    reg = hass.services.async_register

    def kezelo(fn):
        async def _kezel(call: ServiceCall):
            return await fn(hass, call)

        return _kezel

    reg(
        DOMAIN,
        "leolvasas_rogzites",
        kezelo(leolvasas_rogzites),
        vol.Schema(
            {
                DEV: cv.string,
                vol.Required("datum"): cv.date,
                vol.Required("allas"): vol.Coerce(float),
                vol.Optional("tipus", default="kezi"): vol.In(TIPUSOK),
                vol.Optional("elszamolasi", default=False): cv.boolean,
                vol.Optional("megjegyzes", default=""): cv.string,
                vol.Optional("csatorna", default="vetelezes"): vol.In(["vetelezes", "betaplalas", "almero"]),
            }
        ),
    )
    reg(DOMAIN, "leolvasas_torles", kezelo(leolvasas_torles), vol.Schema({DEV: cv.string, vol.Required("datum"): cv.date}))
    reg(
        DOMAIN,
        "merocsere",
        kezelo(merocsere),
        vol.Schema(
            {
                DEV: cv.string,
                vol.Required("datum"): cv.date,
                vol.Required("regi_zaro_allas"): vol.Coerce(float),
                vol.Optional("uj_kezdo_allas", default=0): vol.Coerce(float),
                vol.Optional("uj_gyari_szam", default=""): cv.string,
                vol.Optional("csatorna", default="vetelezes"): vol.In(["vetelezes", "almero"]),
            }
        ),
    )
    reg(
        DOMAIN,
        "feluliras",
        kezelo(feluliras),
        vol.Schema(
            {
                DEV: cv.string,
                vol.Required("kulcs"): cv.string,
                vol.Optional("ertek"): vol.Any(None, vol.Coerce(float)),
                vol.Required("ervenyes_tol"): cv.date,
            }
        ),
    )
    reg(
        DOMAIN,
        "futoertek_rogzites",
        kezelo(futoertek_rogzites),
        vol.Schema({DEV: cv.string, vol.Required("honap"): cv.string, vol.Optional("ertek"): vol.Any(None, vol.Coerce(float))}),
    )
    reg(
        DOMAIN,
        "reszszamla_rogzites",
        kezelo(reszszamla_rogzites),
        vol.Schema(
            {
                DEV: cv.string,
                vol.Required("datum"): cv.date,
                vol.Required("osszeg"): vol.Coerce(float),
                vol.Optional("megjegyzes", default=""): cv.string,
            }
        ),
    )
    reg(DOMAIN, "reszszamla_torles", kezelo(reszszamla_torles), vol.Schema({DEV: cv.string, vol.Required("datum"): cv.date}))
    reg(DOMAIN, "naplo", kezelo(naplo), vol.Schema({DEV: cv.string}), supports_response=SupportsResponse.ONLY)
    reg(DOMAIN, "csv_export", kezelo(csv_export), vol.Schema({DEV: cv.string}), supports_response=SupportsResponse.OPTIONAL)
    reg(
        DOMAIN,
        "v1_import",
        kezelo(import_v1),
        vol.Schema(
            {
                vol.Optional("a_fiok"): cv.string,
                vol.Optional("h_fiok"): cv.string,
                vol.Optional("gaz_fiok"): cv.string,
                vol.Optional("probafuttatas", default=True): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
