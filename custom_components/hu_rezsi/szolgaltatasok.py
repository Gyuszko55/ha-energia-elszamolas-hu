"""Szolgáltatások: leolvasás, mérőcsere, felülírás, napló, CSV-export, v1-import."""

from __future__ import annotations

import csv
import io
import re
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.util import dt as dt_util
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util import slugify

from .const import CONF_SZAMLA_MAPPA, DOMAIN
from .koordinator import RezsiKoordinator
from . import beallitas, szamlak
from .modell import d
from .szamla_import import fajlok_ujraolvasasra, kezi_szamla, mappas_adatok_torlese, rogzit, szamla_torles as _szamla_torles
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


def locsolasi_idenyben(nap: date) -> bool:
    """A locsolási almérő idénye (58/2013. Korm. rendelet): május 1. – szeptember 30.; az október 1-jei állás az
    idény zárása, ezért még rögzíthető."""
    return (5, 1) <= (nap.month, nap.day) <= (10, 1)


def _almero_idenykorlat(koord: RezsiKoordinator, sid: str) -> bool:
    """A fiók díjszabása csak a locsolási idényben vonja-e le az almérőt (DAKÖV: nem – egész évben, a számlák szerint)."""
    sub = koord.fiokok()[sid]
    try:
        v = koord.tar[sub.data.get("dijszabas")].verzio(date.today())
    except Exception:  # noqa: BLE001
        return False
    return bool(v.szabalyok.get("almero_idoszak"))


async def leolvasas_rogzites(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    nap: date = call.data["datum"]
    allas = Decimal(str(call.data["allas"]))
    csatorna = call.data.get("csatorna", "vetelezes")
    if csatorna == "almero":
        if not tarolt.get("almero_merok"):
            raise ServiceValidationError("Ennek a fióknak nincs almérője.")
        if _almero_idenykorlat(koord, sid) and not locsolasi_idenyben(nap):
            raise ServiceValidationError(
                "A locsolási almérőre csak a locsolási idényben (május 1. – szeptember 30., zárás október 1-jén) "
                "rögzíthető mérőállás; azon kívül a fogyasztását nem számoljuk."
            )
        mero = _aktiv_mero({"merok": tarolt["almero_merok"]}, nap)
        csatorna = "vetelezes"  # az almérő saját mérője: a fő regiszterébe kerül
    else:
        mero = _aktiv_mero(tarolt, nap)
    kezdo = mero.get("kezdo_allas" if csatorna == "vetelezes" else f"kezdo_{csatorna}") or 0
    # Számláló-szenzoros automatikus kezdésnél a kezdőállás még a szenzor értéke (nem óraállás): az első valódi
    # leolvasás épp ehhez igazítja, ezért itt nem vetjük össze vele.
    szenzor_alap = (tarolt.get("kezdes") or {}).get("szenzor_alap") and csatorna == "vetelezes"
    if not szenzor_alap and allas < Decimal(str(kezdo)):
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
    # Időpont: a megadott, különben mai saját leolvasásnál a rögzítés pillanata – így az este leolvasott állás nem a nap
    # elejére kerül (a számláló a nap eleje óta mért fogyasztást különben még hozzáadná). Régebbi napra: a nap eleje.
    ido = call.data.get("ido")
    if ido is None and tipus == "kezi" and nap == dt_util.now().date():
        ido = dt_util.now().time()
    # Elsőbbség (villany, gáz, víz): a számlán szereplő állás a hivatalos, amíg kézzel (diktálás) felül nem írjuk – a
    # kézi állás ugyanarra a napra a számla szolgáltatói állását is felülírja (az félrekerül, a kézi törlésekor
    # visszaáll). Távleolvasásnál a szolgáltató távleolvasott állása a legerősebb: azt kézzel nem írjuk felül.
    ugyanaz = [lo for lo in mero["leolvasasok"]
               if lo["datum"] == nap.isoformat() and lo.get("csatorna", "vetelezes") == csatorna and lo.get("tipus") != tipus]
    if tipus == "kezi" and any(lo.get("tipus") == "szolgaltatoi" for lo in ugyanaz):
        if beallitas.elszamolas_mod(koord.fiokok()[sid].data) == "tavleolvasas":
            raise ServiceValidationError(
                "Erre a napra távleolvasott (szolgáltatói) mérőállás van – a távleolvasás az erősebb, kézzel nem írható felül."
            )
        felulirt = [lo for lo in ugyanaz if lo.get("tipus") == "szolgaltatoi"]
        mero.setdefault("felulirt", []).extend(felulirt)
        mero["leolvasasok"] = [lo for lo in mero["leolvasasok"] if not any(lo is f for f in felulirt)]
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
            **({"ido": ido.strftime("%H:%M")} if ido else {}),
            **({"diktalt": True} if call.data.get("diktalt") else {}),
            **({"evkezdet": True, "elszamolasi": True} if call.data.get("evkezdet") else {}),
        }
    ]
    mero["leolvasasok"].sort(key=lambda x: x["datum"])
    await _ment(koord)


async def fiok_lezarasa(hass: HomeAssistant, call: ServiceCall) -> None:
    """Fiók lezárása (költözés, lemondás, szolgáltatóváltás): végleolvasás a lezárás napján, a számolás ott megáll,
    végelszámolás. „visszavonas”: a lezárás és a végleolvasás törlése, a fiók újra fut."""
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    if call.data.get("visszavonas"):
        if not tarolt.pop("megszunt", None):
            raise ServiceValidationError("A fiók nincs lezárva.")
        for m in tarolt.get("merok") or []:
            m["leolvasasok"] = [lo for lo in m.get("leolvasasok", []) if not lo.get("vegleolvasas")]
        tarolt["lezart"] = [x for x in tarolt.get("lezart", []) if x.get("forras") != "végelszámolás"]
        tarolt.pop("nyitott_tol", None)
        await _ment(koord)
        return
    nap: date = call.data.get("datum") or date.today()
    if nap > date.today():
        raise ServiceValidationError("A lezárás napja nem lehet a jövőben.")
    allas = call.data.get("zaro_allas")
    if allas is not None:
        mero = _aktiv_mero(tarolt, nap)
        allas = Decimal(str(allas))
        for lo in mero.get("leolvasasok", []):
            if lo.get("csatorna", "vetelezes") != "vetelezes":
                continue
            ld, la = d(lo["datum"]), Decimal(lo["allas"])
            if (ld < nap and la > allas) or (ld > nap and la < allas):
                raise ServiceValidationError(f"A záró állás nem illeszkedik a {lo['datum']}-i {lo['allas']} leolvasáshoz.")
        mero["leolvasasok"] = [lo for lo in mero["leolvasasok"] if not lo.get("vegleolvasas")] + [{
            "datum": nap.isoformat(), "allas": str(allas), "tipus": "kezi", "elszamolasi": False, "diktalt": True,
            "vegleolvasas": True, "megjegyzes": "végleolvasás (fiók lezárása)", "csatorna": "vetelezes",
        }]
        mero["leolvasasok"].sort(key=lambda x: x["datum"])
    tarolt["megszunt"] = {"datum": nap.isoformat(), "allas": None if allas is None else str(allas)}
    await _ment(koord)


async def leolvasas_torles(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    nap = call.data["datum"].isoformat()
    torolt = 0
    for m in koord.tarolo.fiok(sid)["merok"]:
        elotte = len(m["leolvasasok"])
        m["leolvasasok"] = [lo for lo in m["leolvasasok"] if lo["datum"] != nap]
        torolt += elotte - len(m["leolvasasok"])
        # A kézi diktálással felülírt (számla szerinti) állás visszaáll.
        vissza = [lo for lo in m.get("felulirt") or [] if lo["datum"] == nap]
        if vissza:
            m["leolvasasok"] = sorted(m["leolvasasok"] + vissza, key=lambda x: x["datum"])
            m["felulirt"] = [lo for lo in m["felulirt"] if lo["datum"] != nap]
    if not torolt:
        raise ServiceValidationError(f"{nap} napon nincs leolvasás.")
    await _ment(koord)


async def merocsere(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    nap: date | None = call.data.get("datum")
    if call.data.get("csatorna") == "almero":
        if not tarolt.get("almero_merok"):
            raise ServiceValidationError("Ennek a fióknak nincs almérője.")
        tarolt = {"merok": tarolt["almero_merok"]}  # ugyanaz a lista, helyben módosul
    if call.data.get("visszavonas"):
        # Az utolsó mérőcsere visszavonása: az új mérő törlése (ha még nincs rajta leolvasás), a régi újra aktív.
        if len(tarolt["merok"]) < 2:
            raise ServiceValidationError("Nincs visszavonható mérőcsere.")
        utolso = tarolt["merok"][-1]
        if any(not lo.get("vegleolvasas") for lo in utolso.get("leolvasasok", [])):
            raise ServiceValidationError("Az új mérőn már van leolvasás – előbb azokat töröld.")
        tarolt["merok"].pop()
        elozo = tarolt["merok"][-1]
        for k in [k for k in elozo if k.startswith("zaro_") and k != "zaro_allas"]:
            elozo.pop(k)
        elozo["kiszerelve"] = None
        elozo["zaro_allas"] = None
        await _ment(koord)
        return
    if nap is None or call.data.get("regi_zaro_allas") is None:
        raise ServiceValidationError("A mérőcseréhez a nap és a régi mérő záró állása kell.")
    regi = _aktiv_mero(tarolt, nap)
    if regi.get("kiszerelve") is not None or d(regi["beepitve"]) >= nap:
        raise ServiceValidationError("A mérőcsere napja a mostani mérő beépítése utáni nap kell legyen.")
    zaro = Decimal(str(call.data["regi_zaro_allas"]))
    # A régi mérő záró állása illeszkedjen a leolvasásaihoz: nem lehet kisebb a korábbiaknál, és a csere után a régi
    # mérőn nem lehet leolvasás.
    for lo in regi.get("leolvasasok", []):
        if lo.get("csatorna", "vetelezes") != "vetelezes":
            continue
        if d(lo["datum"]) > nap:
            raise ServiceValidationError(f"A régi mérőn a csere utáni napra ({lo['datum']}) is van leolvasás – előbb azt töröld.")
        if Decimal(lo["allas"]) > zaro:
            raise ServiceValidationError(f"A záró állás kisebb, mint a {lo['datum']}-i {lo['allas']} leolvasás.")
    if zaro < Decimal(str(regi.get("kezdo_allas") or 0)):
        raise ServiceValidationError("A záró állás kisebb, mint a régi mérő kezdőállása.")
    regi["kiszerelve"] = nap.isoformat()
    regi["zaro_allas"] = str(zaro)
    uj = {
        "gyari_szam": call.data.get("uj_gyari_szam", ""),
        "beepitve": nap.isoformat(),
        "kezdo_allas": str(call.data.get("uj_kezdo_allas", 0)),
        "kiszerelve": None,
        "zaro_allas": None,
        "leolvasasok": [],
    }
    # H-tarifa: a két regiszter (1.81 téli, 1.82 nyári) záró és kezdő állása (a csatornák mero_motorba kulcsai).
    for reg in ("h_teli", "h_nyari"):
        if call.data.get(f"regi_zaro_{reg}") is not None:
            regi[f"zaro_{reg}"] = str(call.data[f"regi_zaro_{reg}"])
        if call.data.get(f"uj_kezdo_{reg}") is not None:
            uj[f"kezdo_{reg}"] = str(call.data[f"uj_kezdo_{reg}"])
    tarolt["merok"].append(uj)
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


async def szamla_rogzites(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Kézi számla: befizetés, (opcionálisan) záró mérőállás és fűtőérték – mint egy beolvasott számla."""
    koord, sid = _celpont(hass, call.data["device_id"])
    tarolt = koord.tarolo.fiok(sid)
    tol, ig = call.data.get("idoszak_tol"), call.data.get("idoszak_ig")
    if (tol is None) != (ig is None) or (tol and ig and ig < tol):
        raise ServiceValidationError("Az időszakhoz a kezdő és a záró nap is kell (a záró nem lehet korábbi).")
    sorszam = str(call.data.get("sorszam") or "").strip()
    if sorszam and sorszam in (tarolt.get("szamlak") or {}):
        raise ServiceValidationError(f"Már van {sorszam} sorszámú számla – előbb töröld (hu_rezsi.szamla_torles).")
    sztornozott = str(call.data.get("sztornozott") or "").strip()
    if call.data["tipus"] == "storno" and sztornozott and sztornozott not in (tarolt.get("szamlak") or {}):
        raise ServiceValidationError(f"Nincs {sztornozott} sorszámú számla ebben a fiókban – a stornó ennek a fióknak a számláját érvényteleníti.")
    zaro = call.data.get("zaro_allas")
    futo = call.data.get("futoertek")
    sz = kezi_szamla(
        tarolt, call.data["kelte"], Decimal(str(call.data["osszeg"])), call.data["tipus"], sorszam,
        (tol, ig) if tol else None, None if zaro is None else Decimal(str(zaro)),
        call.data["leolvasott"], None if futo is None else Decimal(str(futo)), call.data.get("hatarido"),
    )
    j = rogzit(tarolt, [sz])
    if not j.szamlak:
        raise ServiceValidationError("A számla nem rögzíthető.")
    tarolt["szamlak"][sz.sorszam]["kezi"] = True
    if call.data["tipus"] == "storno" and sztornozott:
        tarolt["szamlak"][sz.sorszam]["sztornozott"] = sztornozott
    if call.data.get("megjegyzes"):
        tarolt["szamlak"][sz.sorszam]["megjegyzes"] = call.data["megjegyzes"]
    await _ment(koord)
    return {
        "sorszam": sz.sorszam,
        "meroallas": j.leolvasasok,
        "kihagyott_meroallas": j.kihagyott_ellentmondas + len(j.ismeretlen_merok),
    }


async def mentes(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Rezsikövető mentés (zip) a konfigurációs mappa rezsikoveto_mentes/ alá: beállítások, adatok, számlák."""
    from . import mentes as mt, mentes_ha  # noqa: PLC0415

    otthon = call.data.get("otthon")
    try:
        return await mentes_ha.ment(hass, [otthon] if otthon else None, call.data["szamlak"], call.data.get("megtart"))
    except mt.MentesHiba as err:
        raise ServiceValidationError(str(err)) from err


async def visszaallitas(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Visszaállítás mentésből – mindig új otthonként (meglévőt nem ír felül). Forrás: a rezsikoveto_mentes/ mappa
    egy fájlja (`fajl`) vagy feltöltött zip (`file_id`, amelyet előbb a mentések közé másolunk)."""
    from . import mentes as mt, mentes_ha  # noqa: PLC0415

    mappa = mentes_ha.mappa(hass)
    if call.data.get("file_id"):
        def masol() -> Path:
            with process_uploaded_file(hass, call.data["file_id"]) as forras:
                cel = mappa / mt.fajlnev(dt_util.now().isoformat(), "feltoltott")
                mappa.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(forras, cel)
            return cel
        try:
            forras = await hass.async_add_executor_job(masol)
        except ValueError as err:
            raise ServiceValidationError(f"A feltöltött fájl nem található: {err}") from err
    elif call.data.get("fajl"):
        try:
            forras = await mentes_ha.fajl_utvonal(hass, call.data.get("hely", 0), Path(call.data["fajl"]).name)
        except mt.MentesHiba as err:
            raise ServiceValidationError(str(err)) from err
    else:
        raise ServiceValidationError("Add meg a mentés fájlnevét (fajl) vagy tölts fel egy mentést (file_id).")
    otthon = call.data.get("otthon")
    try:
        return await mentes_ha.visszaallit(hass, forras, [otthon] if otthon else None, call.data["szamlak"])
    except mt.MentesHiba as err:
        raise ServiceValidationError(str(err)) from err


async def sziget_leolvasas(hass: HomeAssistant, call: ServiceCall) -> None:
    """Szigetüzem (kísérleti): egy szerepkör kumulatív energiaszámlálójának kézi állása (kWh), szenzor helyett."""
    from . import sziget_ha  # noqa: PLC0415
    from .motor import sziget as m  # noqa: PLC0415

    koord, sid = _celpont(hass, call.data["device_id"])
    sub = sziget_ha.szigetek(koord).get(sid)
    if sub is None:
        raise ServiceValidationError("Az eszköz nem szigetüzemi rendszer.")
    szerep = call.data["szerep"]
    if szerep not in sziget_ha.szerepek(sub):
        raise ServiceValidationError(f"A rendszerben nincs „{szerep}” szerepkör (beállításban adható hozzá).")
    ido = call.data["ido"]
    ido = ido.replace(tzinfo=None) if isinstance(ido, datetime) else datetime.combine(ido, datetime.min.time())
    allas = m.kwh(call.data["allas"], call.data.get("egyseg", "kWh"))
    lista = koord.tarolo.sziget(sid)["leolvasasok"].setdefault(szerep, [])
    lista[:] = sorted([x for x in lista if x["ido"] != ido.isoformat()] + [{"ido": ido.isoformat(), "allas": str(allas)}], key=lambda x: x["ido"])
    await _ment(koord)


async def szamla_feltoltes(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """A panelről feltöltött PDF/XML számla a fiók számlamappájába, majd azonnali feldolgozás."""
    koord, sid = _celpont(hass, call.data["device_id"])
    mappa_rel = koord.fiokok()[sid].data.get(CONF_SZAMLA_MAPPA)
    if not mappa_rel:
        raise ServiceValidationError("Ennek a fióknak nincs számlamappája – add meg a fiók beállításaiban (pl. szamlak/viz).")
    mappa = Path(hass.config.config_dir) / mappa_rel

    def masol() -> tuple[str, Any]:
        with process_uploaded_file(hass, call.data["file_id"]) as forras:
            nev = Path(forras.name).name
            if Path(nev).suffix.lower() not in (".pdf", ".xml"):
                raise ServiceValidationError("Csak PDF vagy XML számla tölthető fel.")
            cel = mappa / nev
            if cel.exists():
                raise ServiceValidationError(f"Már van {nev} nevű fájl a számlamappában.")
            mappa.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(forras, cel)
        return nev, szamlak.beolvas_fajl(cel)

    try:
        nev, sz = await hass.async_add_executor_job(masol)
    except ValueError as err:  # a feltöltött fájl nem található (lejárt / már feldolgozott)
        raise ServiceValidationError(f"A feltöltött fájl nem található: {err}") from err
    tarolt = koord.tarolo.fiok(sid)
    mar_volt = bool(sz and sz.sorszam in (tarolt.get("szamlak") or {}))
    koord.azonnali_fajlok.add(nev)  # a felhasználó maga töltötte fel: nem kell külön jóváhagyás
    await koord.async_refresh()  # a mappa feldolgozása most (új fájl → számla, értesítés)
    meta = (tarolt.get("szamlak") or {}).get(sz.sorszam) if sz else None
    return {
        "fajl": nev,
        "felismert": sz is not None,
        "rogzitve": bool(meta) and not mar_volt and meta.get("fajl") == nev,
        "mar_volt": mar_volt,
        "sorszam": sz.sorszam if sz else None,
        "kelte": sz.kelte.isoformat() if sz else None,
        "osszeg": float(sz.osszeg) if sz and sz.osszeg is not None else None,
        "tipus": sz.tipus if sz else None,
    }


async def szamla_torles(hass: HomeAssistant, call: ServiceCall) -> None:
    koord, sid = _celpont(hass, call.data["device_id"])
    if not _szamla_torles(koord.tarolo.fiok(sid), call.data["sorszam"]):
        raise ServiceValidationError(f"Nincs {call.data['sorszam']} sorszámú számla ennél a fióknál.")
    await _ment(koord)


async def szamla_osszevetes(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    koord, sid = _celpont(hass, call.data["device_id"])
    return await koord.szamla_osszevetes(sid, call.data.get("honap", 24))


async def lezartak_ujraszamolasa(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    koord, sid = _celpont(hass, call.data["device_id"])
    return await koord.lezartak_ujraszamolasa(sid, call.data.get("tol"))


async def szamlak_ujraolvasasa(hass: HomeAssistant, call: ServiceCall) -> None:
    """A számlamappából jött adatok törlése, majd a mappa teljes újraolvasása.

    A kézi mérőállások maradnak, hacsak minden_meroallas=True (akkor a fiók összes mérőállása törlődik)."""
    koord, sid = _celpont(hass, call.data["device_id"])
    if not koord.fiokok()[sid].data.get(CONF_SZAMLA_MAPPA):
        raise ServiceValidationError("Ennek a fióknak nincs számlamappája.")
    tarolt = koord.tarolo.fiok(sid)
    if call.data.get("fajlok"):
        # Csak a megnevezett fájlok újraolvasása: a többi adat érintetlen (a következő frissítés feldolgozza őket).
        nevek = {Path(x).name for x in call.data["fajlok"]}
        fajlok_ujraolvasasra(tarolt, nevek)
        await koord.tarolo.ment()
        await koord.async_refresh()
        return
    # A kézzel rögzített számlák (hu_rezsi.szamla_rogzites) a befizetésükkel és a mérőállásukkal maradnak.
    mappas_adatok_torlese(tarolt, call.data["minden_meroallas"])
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


# Nem rendszergazda felhasználó is hívhatja: mérőállás rögzítése (fiók és szigetüzem), valamint a csak olvasó
# szolgáltatások. Minden más (adatot író/törlő, mentés, visszaállítás, import) csak rendszergazdának.
NYITOTT_SZOLGALTATASOK = {"leolvasas_rogzites", "sziget_leolvasas", "szamla_osszevetes", "naplo"}


def regisztral(hass: HomeAssistant) -> None:
    def reg(domain: str, nev: str, *args: Any, **kw: Any) -> None:
        if nev in NYITOTT_SZOLGALTATASOK:
            hass.services.async_register(domain, nev, *args, **kw)
        else:
            async_register_admin_service(hass, domain, nev, *args, **kw)

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
                vol.Optional("ido"): cv.time,
                vol.Required("allas"): vol.Coerce(float),
                vol.Optional("tipus", default="kezi"): vol.In(TIPUSOK),
                vol.Optional("elszamolasi", default=False): cv.boolean,
                vol.Optional("diktalt", default=False): cv.boolean,
                vol.Optional("evkezdet", default=False): cv.boolean,
                vol.Optional("megjegyzes", default=""): cv.string,
                vol.Optional("csatorna", default="vetelezes"): vol.In(["vetelezes", "betaplalas", "almero", "h_teli", "h_nyari", "zona_csucs", "zona_volgy"]),
            }
        ),
    )
    reg(DOMAIN, "leolvasas_torles", kezelo(leolvasas_torles), vol.Schema({DEV: cv.string, vol.Required("datum"): cv.date}))
    reg(
        DOMAIN,
        "fiok_lezarasa",
        kezelo(fiok_lezarasa),
        vol.Schema({
            DEV: cv.string,
            vol.Optional("datum"): cv.date,
            vol.Optional("zaro_allas"): vol.Coerce(float),
            vol.Optional("visszavonas", default=False): cv.boolean,
        }),
    )
    reg(
        DOMAIN,
        "merocsere",
        kezelo(merocsere),
        vol.Schema(
            {
                DEV: cv.string,
                vol.Optional("datum"): cv.date,
                vol.Optional("regi_zaro_allas"): vol.Coerce(float),
                vol.Optional("visszavonas", default=False): cv.boolean,
                vol.Optional("uj_kezdo_allas", default=0): vol.Coerce(float),
                vol.Optional("uj_gyari_szam", default=""): cv.string,
                vol.Optional("csatorna", default="vetelezes"): vol.In(["vetelezes", "almero"]),
                vol.Optional("regi_zaro_h_teli"): vol.Coerce(float),
                vol.Optional("regi_zaro_h_nyari"): vol.Coerce(float),
                vol.Optional("uj_kezdo_h_teli"): vol.Coerce(float),
                vol.Optional("uj_kezdo_h_nyari"): vol.Coerce(float),
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
    reg(
        DOMAIN,
        "sziget_leolvasas",
        kezelo(sziget_leolvasas),
        vol.Schema(
            {
                DEV: cv.string,
                vol.Required("ido"): vol.Any(cv.datetime, cv.date),
                vol.Required("szerep"): cv.string,
                vol.Required("allas"): vol.Coerce(float),
                vol.Optional("egyseg", default="kWh"): vol.In(["Wh", "kWh", "MWh"]),
            }
        ),
    )
    reg(
        DOMAIN,
        "szamla_rogzites",
        kezelo(szamla_rogzites),
        vol.Schema(
            {
                DEV: cv.string,
                vol.Required("kelte"): cv.date,
                vol.Required("osszeg"): vol.Coerce(float),
                vol.Optional("tipus", default="resz"): vol.In(["resz", "elszamolo", "egyeb", "eloiras", "storno"]),
                vol.Optional("sorszam", default=""): cv.string,
                vol.Optional("sztornozott", default=""): cv.string,
                vol.Optional("idoszak_tol"): cv.date,
                vol.Optional("idoszak_ig"): cv.date,
                vol.Optional("zaro_allas"): vol.Coerce(float),
                vol.Optional("leolvasott", default=False): cv.boolean,
                vol.Optional("futoertek"): vol.Coerce(float),
                vol.Optional("hatarido"): cv.date,
                vol.Optional("megjegyzes", default=""): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "szamla_osszevetes",
        kezelo(szamla_osszevetes),
        vol.Schema({DEV: cv.string, vol.Optional("honap", default=24): vol.All(vol.Coerce(int), vol.Range(min=1, max=120))}),
        supports_response=SupportsResponse.ONLY,
    )
    reg(
        DOMAIN,
        "lezartak_ujraszamolasa",
        kezelo(lezartak_ujraszamolasa),
        vol.Schema({DEV: cv.string, vol.Optional("tol"): cv.date}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "szamla_feltoltes",
        kezelo(szamla_feltoltes),
        vol.Schema({DEV: cv.string, vol.Required("file_id"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    reg(DOMAIN, "szamla_torles", kezelo(szamla_torles), vol.Schema({DEV: cv.string, vol.Required("sorszam"): cv.string}))
    reg(
        DOMAIN,
        "mentes",
        kezelo(mentes),
        vol.Schema(
            {
                vol.Optional("otthon"): cv.string,
                vol.Optional("szamlak", default=True): cv.boolean,
                vol.Optional("megtart"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1000)),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "visszaallitas",
        kezelo(visszaallitas),
        vol.Schema(
            {
                vol.Optional("fajl"): cv.string,
                vol.Optional("hely", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=50)),
                vol.Optional("file_id"): cv.string,
                vol.Optional("otthon"): cv.string,
                vol.Optional("szamlak", default=True): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "szamlak_ujraolvasasa",
        kezelo(szamlak_ujraolvasasa),
        vol.Schema({
            DEV: cv.string,
            vol.Optional("minden_meroallas", default=False): cv.boolean,
            vol.Optional("fajlok"): vol.All(cv.ensure_list, [cv.string]),
        }),
    )
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
