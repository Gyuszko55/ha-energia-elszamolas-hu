"""Rezsikövető mentés és visszaállítás – Home Assistant oldal (mentes.py-ra épül).

Mentés: a kiválasztott (vagy minden) otthon beállításai (alárendelt bejegyzések: fiókok, szigetüzem), tárolt adatai és
a használt szenzorok neve, kérésre a számlamappák fájljaival, egy zipbe – minden bekapcsolt mentési helyre (helyi
mappa, hálózati tárhely /media vagy /share alatt), helyenként saját megtartással. Ütemezés: napi / heti, a panelről.
Visszaállítás: mindig ÚJ otthon jön létre (meglévőt nem ír felül; névütközésnél „(visszaállítva)”). Az adatokat a
`hass.data`-ba tesszük egy jeggyel, az új otthon első indulása (`befejezes`) – még a koordinátor előtt – átkulcsolja a
régi alárendelt azonosítókat az újakra, és elmenti. A számla-fájlokat csak oda írja vissza, ahol még nincsenek.
Home Assistant mentésből (pl. a Google Drive-ra feltöltöttből, visszatöltve a HA-ba): a mentésben lévő Rezsikövető-
adatokból egy szabályos Rezsikövető-mentés készül (titkosított mentésnél a HA mentéskulcsával).
Visszaállítás után a szenzor-hozzárendelés (`szenzor_lista` / `szenzor_csere`): az új rendszerben hiányzó szenzorok
helyett újak választhatók.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import mentes as m
from .const import DOMAIN
from .tarolo import VERZIO, Tarolo

_LOGGER = logging.getLogger(__name__)
JEGY = "visszaallitas"
BEALLITAS_KULCS = f"{DOMAIN}_mentes"
NAPOK = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]
MERTEKEGYSEGEK = {"kWh", "Wh", "MWh", "m³", "m3", "L", "MJ", "GJ"}


# ------------------------------------------------------------------------------------------------- beállítások

def mappa(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(m.MAPPA))


def alap_beallitas(hass: HomeAssistant) -> dict[str, Any]:
    return {
        "helyek": [{"nev": "Helyi (HA konfiguráció)", "utvonal": str(mappa(hass)), "megtart": 8, "aktiv": True}],
        "utemezes": {"gyakorisag": "heti", "nap": 6, "ido": "03:30", "szamlak": False},
        "utolso": None,
    }


async def beallitas(hass: HomeAssistant) -> dict[str, Any]:
    d = hass.data.setdefault(DOMAIN, {})
    if "mentes_beallitas" not in d:
        d["mentes_beallitas"] = await Store(hass, 1, BEALLITAS_KULCS).async_load() or alap_beallitas(hass)
    return d["mentes_beallitas"]


def _engedett(hass: HomeAssistant, utvonal: str) -> bool:
    """Mentési hely csak a HA konfigurációs mappájában, a /share vagy a /media alatt lehet."""
    p = Path(utvonal).resolve()
    gyokerek = [Path(hass.config.config_dir).resolve(), Path("/share"), Path("/media")]
    return any(p == g or g in p.parents for g in gyokerek)


async def beallitas_ment(hass: HomeAssistant, uj: dict[str, Any]) -> dict[str, Any]:
    regi = await beallitas(hass)
    helyek = []
    for h in uj.get("helyek") or []:
        utvonal = str(h.get("utvonal") or "").strip()
        if not utvonal or not _engedett(hass, utvonal):
            raise m.MentesHiba(f"Nem engedett mentési hely: {utvonal or '(üres)'} – a HA konfigurációs mappája, /share vagy /media alatt lehet.")
        helyek.append({"nev": str(h.get("nev") or Path(utvonal).name), "utvonal": utvonal,
                       "megtart": max(0, int(h.get("megtart") or 0)), "aktiv": bool(h.get("aktiv", True))})
    if not helyek:
        raise m.MentesHiba("Legalább egy mentési hely kell.")
    ut = uj.get("utemezes") or regi["utemezes"]
    if ut.get("gyakorisag") not in ("ki", "napi", "heti"):
        raise m.MentesHiba("Ismeretlen gyakoriság.")
    datetime.strptime(ut.get("ido", "03:30"), "%H:%M")
    b = {"helyek": helyek, "utemezes": {"gyakorisag": ut["gyakorisag"], "nap": int(ut.get("nap", 6)) % 7,
                                        "ido": ut.get("ido", "03:30"), "szamlak": bool(ut.get("szamlak", False))},
         "utolso": regi.get("utolso")}
    hass.data[DOMAIN]["mentes_beallitas"] = b
    await Store(hass, 1, BEALLITAS_KULCS).async_save(b)
    return b


async def hely_jeloltek(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Választható mentési helyek: a helyi mappa, és a /media, /share közvetlen almappái (a hálózati tárhelyek –
    Beállítások → Rendszer → Tárhely → Hálózati tárhely – ide csatolódnak), szabad hellyel."""
    def gyujt() -> list[dict[str, Any]]:
        ki = [{"utvonal": str(mappa(hass)), "nev": "Helyi (HA konfiguráció)", "halozati": False}]
        for gyoker in (Path("/media"), Path("/share")):
            if not gyoker.is_dir():
                continue
            for d in sorted(gyoker.iterdir()):
                if d.is_dir() and not d.name.startswith("."):
                    try:
                        halozati = d.is_mount()
                    except OSError:
                        halozati = False
                    ki.append({"utvonal": str(d), "nev": d.name, "halozati": halozati})
        for x in ki:
            try:
                du = shutil.disk_usage(x["utvonal"] if Path(x["utvonal"]).exists() else Path(x["utvonal"]).parent)
                x["szabad_gb"] = round(du.free / 1e9, 1)
            except OSError:
                x["szabad_gb"] = None
        return sorted(ki, key=lambda x: (not x["halozati"], x["utvonal"] != str(mappa(hass)), x["utvonal"]))
    return await hass.async_add_executor_job(gyujt)


# ------------------------------------------------------------------------------------------------------ mentés

def _verzio() -> str:
    try:
        return json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return "?"


def _szenzor_nevek(hass: HomeAssistant, alar: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    reg = er.async_get(hass)
    ki = {}
    for h in m.szenzor_hivatkozasok(alar):
        eid = h["entity_id"]
        st = hass.states.get(eid)
        r = reg.async_get(eid)
        nev = (st.attributes.get("friendly_name") if st else None) or (r and (r.name or r.original_name)) or eid
        ki[eid] = {"nev": nev, "egyseg": (st.attributes.get("unit_of_measurement") if st else None) or (r and r.unit_of_measurement)}
    return ki


async def _otthon_mentes(hass: HomeAssistant, entry: ConfigEntry) -> m.OtthonMentes:
    koord = getattr(entry, "runtime_data", None)
    if koord is not None and hasattr(koord, "tarolo"):
        await koord.tarolo.ment()  # a memóriában lévő legfrissebb állapot kerüljön a mentésbe
        tar = json.loads(json.dumps(koord.tarolo.adat))
        negyed = json.loads(json.dumps(await koord._negyed_tar()))
    else:
        tar = await Store(hass, VERZIO, f"{DOMAIN}.{entry.entry_id}").async_load() or {"fiokok": {}}
        negyed = await Store(hass, 1, f"{DOMAIN}_negyedek.{entry.entry_id}").async_load() or {}
    alar = [{"subentry_id": sid, "subentry_type": s.subentry_type, "title": s.title, "data": dict(s.data)}
            for sid, s in entry.subentries.items()]
    # A visszaállítás óta megőrzött régi szenzornevek is maradjanak (ha a szenzor még mindig hiányzik).
    nevek = (tar.get("szenzor_nevek") or {}) | _szenzor_nevek(hass, alar)
    return m.OtthonMentes(entry.title, entry.entry_id, alar, tar, negyed, nevek, dict(entry.options))


async def ment(hass: HomeAssistant, entry_ids: list[str] | None = None, szamlak: bool = True, megtart: int | None = None,
               helyek: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Mentés minden bekapcsolt helyre (az elsőre írja, a többire másolja); helyenként a régiek törlése."""
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if not entry_ids or e.entry_id in entry_ids]
    if not entries:
        raise m.MentesHiba("nincs mentendő otthon")
    if helyek is None:
        helyek = [h for h in (await beallitas(hass))["helyek"] if h.get("aktiv", True)]
    if not helyek:
        raise m.MentesHiba("nincs bekapcsolt mentési hely")
    otthonok = [await _otthon_mentes(hass, e) for e in entries]
    keszult = dt_util.now().replace(microsecond=0).isoformat()
    nev = m.fajlnev(keszult, otthonok[0].nev if len(otthonok) == 1 else "osszes")
    cfg = Path(hass.config.config_dir)

    def ir() -> tuple[int, int, list[dict[str, Any]]]:
        sz = m.szamla_fajlok(cfg, [x for o in otthonok for x in m.szamla_mappak(o.alarendeltek)]) if szamlak else []
        eredmeny, elso, meret = [], None, 0
        for h in helyek:
            cel = Path(h["utvonal"]) / nev
            try:
                if elso is None:
                    meret = m.zip_ir(cel, otthonok, sz, _verzio(), keszult)
                    elso = cel
                else:
                    cel.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(elso, cel.with_suffix(".zip.tmp"))
                    cel.with_suffix(".zip.tmp").replace(cel)
                torolt = m.regiek_torlese(cel.parent, megtart if megtart is not None else int(h.get("megtart") or 0))
                eredmeny.append({"hely": h["nev"], "utvonal": str(cel), "ok": True, "torolt": torolt})
            except OSError as err:
                _LOGGER.warning("Rezsikövető mentés – %s nem írható: %s", h["utvonal"], err)
                eredmeny.append({"hely": h["nev"], "utvonal": str(cel), "ok": False, "hiba": str(err)})
        return meret, len(sz), eredmeny

    meret, db, helyek_e = await hass.async_add_executor_job(ir)
    if not any(x["ok"] for x in helyek_e):
        raise m.MentesHiba("egyik mentési hely sem írható: " + "; ".join(f"{x['hely']}: {x['hiba']}" for x in helyek_e))
    _LOGGER.info("Rezsikövető mentés: %s (%d bájt, %d számla-fájl, %d hely)", nev, meret, db, sum(x["ok"] for x in helyek_e))
    return {"fajl": nev, "meret": meret, "otthonok": [o.nev for o in otthonok], "szamlak": db, "helyek": helyek_e,
            "utvonal": next(x["utvonal"] for x in helyek_e if x["ok"])}


async def mentesek(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Minden mentési hely mentései (legújabb elöl); ugyanaz a fájl több helyen egy sorban, a helyek listájával."""
    b = await beallitas(hass)

    def gyujt() -> list[dict[str, Any]]:
        sorok: dict[str, dict[str, Any]] = {}
        for i, h in enumerate(b["helyek"]):
            for x in m.mentesek_listaja(Path(h["utvonal"])):
                s = sorok.setdefault(x["fajl"], x | {"helyek": []})
                s["helyek"].append({"idx": i, "nev": h["nev"]})
        return sorted(sorok.values(), key=lambda x: x.get("keszult") or "", reverse=True)
    return await hass.async_add_executor_job(gyujt)


async def fajl_utvonal(hass: HomeAssistant, hely: int, fajl: str) -> Path:
    b = await beallitas(hass)
    if not m.FAJLNEV_MINTA.match(fajl) or not 0 <= hely < len(b["helyek"]):
        raise m.MentesHiba("ismeretlen mentés")
    p = Path(b["helyek"][hely]["utvonal"]) / fajl
    if not await hass.async_add_executor_job(p.is_file):
        raise m.MentesHiba(f"nincs ilyen mentés: {fajl}")
    return p


# --------------------------------------------------------------------------------------------------- ütemezés

@callback
def utemezo_indit(hass: HomeAssistant) -> None:
    """Percenként megnézi, esedékes-e az ütemezett mentés (napi / heti, adott időpontban)."""
    async def _perc(most: datetime) -> None:
        most = dt_util.as_local(most)
        b = await beallitas(hass)
        u = b["utemezes"]
        if u["gyakorisag"] == "ki" or most.strftime("%H:%M") != u["ido"]:
            return
        if u["gyakorisag"] == "heti" and most.weekday() != u["nap"]:
            return
        if (b.get("utolso") or {}).get("datum") == most.date().isoformat() and (b.get("utolso") or {}).get("utemezett"):
            return
        try:
            e = await ment(hass, None, u["szamlak"])
            b["utolso"] = {"datum": most.date().isoformat(), "ido": most.isoformat(), "utemezett": True, "ok": True,
                           "fajl": e["fajl"], "helyek": e["helyek"]}
        except Exception as err:
            _LOGGER.exception("Rezsikövető ütemezett mentés nem sikerült")
            b["utolso"] = {"datum": most.date().isoformat(), "ido": most.isoformat(), "utemezett": True, "ok": False, "hiba": str(err)}
            persistent_notification.async_create(
                hass, f"A Rezsikövető ütemezett mentése nem sikerült: {err}", "Rezsikövető mentés", f"{DOMAIN}_mentes_hiba")
        await Store(hass, 1, BEALLITAS_KULCS).async_save(b)

    async_track_time_change(hass, _perc, second=10)


# -------------------------------------------------------------------------------------------------- visszaállítás

async def visszaallit(hass: HomeAssistant, forras: Path, otthon_nevek: list[str] | None = None, szamlak: bool = True) -> dict[str, Any]:
    """A mentés otthonainak visszaállítása új otthonként; a számla-fájlok visszaírása (meglévőt nem ír felül)."""
    manifest, otthonok, szamla_nevek = await hass.async_add_executor_job(m.zip_olvas, forras)
    if otthon_nevek:
        otthonok = [o for o in otthonok if o.nev in otthon_nevek]
        if not otthonok:
            raise m.MentesHiba(f"a mentésben nincs ilyen otthon: {', '.join(otthon_nevek)}")
    foglalt = {e.title for e in hass.config_entries.async_entries(DOMAIN)}
    eredmeny: list[dict[str, Any]] = []
    for o in otthonok:
        nev = m.egyedi_nev(o.nev, foglalt)
        foglalt.add(nev)
        jegy = uuid.uuid4().hex
        hass.data.setdefault(DOMAIN, {}).setdefault(JEGY, {})[jegy] = {"tar": o.tar, "negyedek": o.negyedek, "szenzorok": o.szenzorok}
        r = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT},
            data={"nev": nev, JEGY: jegy, "alarendeltek": o.alarendeltek, "beallitas": o.beallitas},
        )
        if r.get("type") != "create_entry":
            hass.data[DOMAIN][JEGY].pop(jegy, None)
            raise m.MentesHiba(f"{o.nev}: az otthon nem hozható létre ({r.get('reason') or r.get('type')})")
        kiirt = kihagyott = 0
        if szamlak:
            nevek = m.otthon_szamlai(o, szamla_nevek)
            kiirt, kihagyott = await hass.async_add_executor_job(m.szamlak_kicsomagol, forras, Path(hass.config.config_dir), nevek)
        hianyzo = sorted({h["entity_id"] for h in m.szenzor_hivatkozasok(o.alarendeltek)} - set(hass.states.async_entity_ids()))
        eredmeny.append({"nev": nev, "eredeti": o.nev, "entry_id": r["result"].entry_id, "fiokok": len(o.alarendeltek),
                         "szamlak_kiirt": kiirt, "szamlak_mar_megvolt": kihagyott, "hianyzo_szenzorok": len(hianyzo)})
    return {"mentes": manifest.get("keszult"), "verzio": manifest.get("rezsikoveto"), "otthonok": eredmeny}


async def befejezes(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Visszaállított otthon első indulása (a koordinátor előtt): a tárolt adatok átkulcsolása és mentése."""
    jegy = entry.data.get(JEGY)
    if not jegy:
        return
    adat = (hass.data.get(DOMAIN, {}).get(JEGY) or {}).pop(jegy, None)
    terkep = {s.data[m.REGI_ID]: sid for sid, s in entry.subentries.items() if s.data.get(m.REGI_ID)}
    if adat is None:
        _LOGGER.warning("%s: a visszaállítás adatai elvesztek (újraindítás közben?) – az otthon üresen indul", entry.title)
    else:
        tarolo = Tarolo(hass, entry.entry_id)
        tarolo.adat = m.atkulcsol(adat["tar"], terkep)
        # A mentéskori szenzornevek: a hozzárendelő táblázat ebből mutatja, mi volt a hiányzó szenzor.
        tarolo.adat["szenzor_nevek"] = (tarolo.adat.get("szenzor_nevek") or {}) | (adat.get("szenzorok") or {})
        await tarolo.ment()
        if adat.get("negyedek"):
            await Store(hass, 1, f"{DOMAIN}_negyedek.{entry.entry_id}").async_save(m.negyed_atkulcsol(adat["negyedek"], terkep))
    # A régi azonosító és a jegy eltávolítása (az update listener ekkor még nincs bekötve: nincs újratöltés).
    for s in entry.subentries.values():
        if m.REGI_ID in s.data:
            hass.config_entries.async_update_subentry(entry, s, data={k: v for k, v in s.data.items() if k != m.REGI_ID})
    hass.config_entries.async_update_entry(entry, data={k: v for k, v in entry.data.items() if k != JEGY})
    _LOGGER.info("%s: visszaállítva (%d alárendelt bejegyzés)", entry.title, len(terkep))


# ----------------------------------------------------------------------------------- Home Assistant mentésből

async def ha_mentesek(hass: HomeAssistant) -> list[dict[str, Any]]:
    """A HA mentései (helyi, felhő…), amelyekben benne van a konfiguráció – ezekből kiolvasható a Rezsikövető."""
    from homeassistant.components.backup import DATA_MANAGER

    manager = hass.data.get(DATA_MANAGER)
    if manager is None:
        return []
    backups, _ = await manager.async_get_backups()
    ki = []
    for b in backups.values():
        if not b.homeassistant_included:
            continue
        ki.append({"backup_id": b.backup_id, "nev": b.name, "datum": b.date,
                   "helyek": [{"agent_id": a, "meret": s.size, "titkositott": s.protected} for a, s in b.agents.items()]})
    return sorted(ki, key=lambda x: x["datum"], reverse=True)


async def ha_mentesbol(hass: HomeAssistant, backup_id: str, agent_id: str | None = None) -> dict[str, Any]:
    """Egy HA-mentés Rezsikövető-tartalmából szabályos Rezsikövető-mentés (zip) az első mentési helyre."""
    from homeassistant.components.backup import DATA_MANAGER
    from homeassistant.components.backup.util import DecryptedBackupStreamer
    from homeassistant.util.async_iterator import AsyncIteratorReader

    manager = hass.data.get(DATA_MANAGER)
    if manager is None:
        raise m.MentesHiba("a Home Assistant mentéskezelője nem érhető el")
    backups, _ = await manager.async_get_backups()
    b = backups.get(backup_id)
    if b is None:
        raise m.MentesHiba("nincs ilyen Home Assistant-mentés")
    jelolt = [agent_id] if agent_id else sorted(b.agents, key=lambda a: (not a.endswith(".local"), a))
    agent_id = next((a for a in jelolt if a in b.agents and a in manager.backup_agents), None)
    if agent_id is None:
        raise m.MentesHiba("a mentés egyik helyről sem tölthető le")
    agent = manager.backup_agents[agent_id]
    agent_backup = await agent.async_get_backup(backup_id)

    async def nyit() -> Any:
        # A helyi mentési hely (Supervisor nélküli HA: backup.local) nem ad letöltési folyamot, csak a fájl útját.
        if agent_id in getattr(manager, "local_backup_agents", {}):
            return _fajl_folyam(hass, manager.local_backup_agents[agent_id].get_backup_path(backup_id))
        return await agent.async_download_backup(backup_id)

    if agent_backup.protected:
        jelszo = manager.config.data.create_backup.password
        if not jelszo:
            raise m.MentesHiba("a mentés titkosított, de a HA-ban nincs beállított mentéskulcs")
        stream = await DecryptedBackupStreamer(hass, agent_backup, nyit, jelszo).open_stream()
    else:
        stream = await nyit()
    reader = AsyncIteratorReader(hass.loop, stream)
    cfg = Path(hass.config.config_dir)
    helyek = [h for h in (await beallitas(hass))["helyek"] if h.get("aktiv", True)] or [{"utvonal": str(mappa(hass))}]
    keszult = dt_util.parse_datetime(b.date) or dt_util.now()
    cel = Path(helyek[0]["utvonal"]) / m.fajlnev(keszult.isoformat(), f"hamentes-{b.name}")

    def feldolgoz() -> dict[str, Any]:
        with tempfile.TemporaryDirectory(dir=cfg) as tmp:
            try:
                t = m.ha_mentes_olvas(reader, Path(tmp))
            finally:
                reader.close()
            otthonok = m.ha_mentesbol_otthonok(t)
            mappak = [x.rstrip("/") + "/" for o in otthonok for x in m.szamla_mappak(o.alarendeltek)]
            sz = [(rel, f) for rel, f in sorted(t.szamlak.items()) if any(rel.startswith(x) for x in mappak)]
            meret = m.zip_ir(cel, otthonok, sz, b.homeassistant_version or "?", keszult.replace(microsecond=0).isoformat())
        return {"fajl": cel.name, "meret": meret, "otthonok": [o.nev for o in otthonok], "szamlak": len(sz)}

    eredmeny = await hass.async_add_executor_job(feldolgoz)
    _LOGGER.info("Rezsikövető-mentés HA-mentésből (%s, %s): %s", b.name, agent_id, eredmeny)
    return eredmeny | {"ha_mentes": b.name, "agent": agent_id}


async def _fajl_folyam(hass: HomeAssistant, utvonal: Path, darab: int = 1 << 20) -> Any:
    """Egy helyi fájl aszinkron bájtfolyamként (az olvasás végrehajtó szálban)."""
    f = await hass.async_add_executor_job(utvonal.open, "rb")
    try:
        while chunk := await hass.async_add_executor_job(f.read, darab):
            yield chunk
    finally:
        await hass.async_add_executor_job(f.close)


# ------------------------------------------------------------------------------------------- szenzor-hozzárendelés

def szenzor_lista(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Az otthon szenzor-hivatkozásai: fiók, szerep, a régi (mentéskori) név, az entitás, létezik-e most."""
    koord = getattr(entry, "runtime_data", None)
    nevek = ((koord.tarolo.adat if koord is not None and hasattr(koord, "tarolo") else {}) or {}).get("szenzor_nevek") or {}
    alar = [{"subentry_id": sid, "subentry_type": s.subentry_type, "title": s.title, "data": dict(s.data)}
            for sid, s in entry.subentries.items()]
    sorok = []
    for h in m.szenzor_hivatkozasok(alar):
        st = hass.states.get(h["entity_id"])
        sorok.append(h | {"regi_nev": (nevek.get(h["entity_id"]) or {}).get("nev") or (st.attributes.get("friendly_name") if st else None),
                          "regi_egyseg": (nevek.get(h["entity_id"]) or {}).get("egyseg"),
                          "letezik": st is not None and st.state not in ("unavailable",)})
    # Választható: energia-/térfogat-mértékegységű szenzor, a Rezsikövető saját (számolt) szenzorai nélkül; a növekvő
    # számlálók (total_increasing / total – mérőállás jellegűek) előre.
    reg = er.async_get(hass)
    jeloltek = sorted(
        ({"entity_id": s.entity_id, "nev": s.attributes.get("friendly_name") or s.entity_id, "egyseg": s.attributes.get("unit_of_measurement"),
          "szamlalo": s.attributes.get("state_class") in ("total_increasing", "total")}
         for s in hass.states.async_all("sensor")
         if s.attributes.get("unit_of_measurement") in MERTEKEGYSEGEK and not ((r := reg.async_get(s.entity_id)) and r.platform == DOMAIN)),
        key=lambda x: (not x["szamlalo"], x["nev"].lower()))
    return {"otthon": entry.title, "sorok": sorok, "jeloltek": jeloltek}


async def szenzor_csere(hass: HomeAssistant, entry: ConfigEntry, csere: list[dict[str, Any]]) -> int:
    """A kiválasztott új szenzorok beírása az alárendelt bejegyzésekbe (alárendeltenként egyszer – egy újratöltés)."""
    uj_data: dict[str, dict[str, Any]] = {}
    for c in csere:
        sub = entry.subentries.get(c["sid"])
        if sub is None:
            continue
        uj = (c.get("uj") or "").strip() or None
        if uj and not uj.startswith("sensor."):
            raise m.MentesHiba(f"nem szenzor: {uj}")
        uj_data[c["sid"]] = m.szenzor_csere(uj_data.get(c["sid"], dict(sub.data)), c["kulcs"], c.get("idx"), uj)
    db = 0
    for sid, data in uj_data.items():
        if hass.config_entries.async_update_subentry(entry, entry.subentries[sid], data=data):
            db += 1
    return db
