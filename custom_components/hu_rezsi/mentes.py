"""Rezsikövető mentés és visszaállítás – a Home Assistanttól független rész (zip írás/olvasás, átkulcsolás).

A mentés egyetlen zip:
  manifest.json                    formátum, Rezsikövető-verzió, időpont, otthonok listája, van-e benne számla
  otthonok/<n>.json                egy otthon: név, régi azonosító, alárendelt bejegyzései (fiókok, szigetüzem –
                                   típus, cím, beállítások), a tárolt adatai (mérőállások, számlák, fizetések,
                                   lezárt időszakok, szigetüzem…) és a negyedórás gyorstár
  szamlak/<útvonal>                a számlamappák fájljai, a HA konfigurációs mappájához viszonyított útvonalon

Visszaállításkor mindig új otthon jön létre (új azonosítókkal); a régi alárendelt azonosítók szerint kulcsolt
adatokat az újakra kell átkulcsolni (`atkulcsol`).
"""

from __future__ import annotations

import json
import re
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

FORMATUM = 1
MAPPA = "rezsikoveto_mentes"
FAJLNEV_MINTA = re.compile(r"^rezsikoveto_mentes_[0-9A-Za-z_\-]+\.zip$")
SZAMLA_KITERJESZTESEK = {".pdf", ".xml"}
REGI_ID = "_visszaallitas_regi_id"  # az alárendelt bejegyzés adataiban, amíg az új otthon első indulása át nem kulcsol
# Ami soha nem kerül a mentésbe: az e-mail fiók jelszava (visszaállítás után a felhasználó újra megadja).
TITKOS_KULCSOK = {"jelszo"}


class MentesHiba(ValueError):
    """Hibás vagy nem Rezsikövető-mentés."""


@dataclass
class OtthonMentes:
    nev: str
    entry_id: str
    alarendeltek: list[dict[str, Any]]  # {subentry_id, subentry_type, title, data}
    tar: dict[str, Any]
    negyedek: dict[str, Any] = field(default_factory=dict)
    szenzorok: dict[str, dict[str, Any]] = field(default_factory=dict)  # entity_id → {nev, egyseg} a mentés idején
    beallitas: dict[str, Any] = field(default_factory=dict)  # az otthon beállításai (options: fűtés, hőmérséklet)

    def dict(self) -> dict[str, Any]:
        return {"nev": self.nev, "entry_id": self.entry_id, "alarendeltek": self.alarendeltek, "tar": self.tar,
                "negyedek": self.negyedek, "szenzorok": self.szenzorok,
                "beallitas": self.beallitas}


def fajlnev(keszult: str, cimke: str = "osszes") -> str:
    """rezsikoveto_mentes_<cimke>_<YYYYMMDD-HHMMSS>.zip; a címke ékezet és szóköz nélkül."""
    tiszta = re.sub(r"[^0-9A-Za-z]+", "-", _ekezet_nelkul(cimke)).strip("-").lower() or "otthon"
    ido = re.sub(r"[^0-9]", "", keszult)[:14]
    return f"rezsikoveto_mentes_{tiszta}_{ido[:8]}-{ido[8:14]}.zip"


def _ekezet_nelkul(s: str) -> str:
    return s.translate(str.maketrans("áéíóöőúüűÁÉÍÓÖŐÚÜŰ", "aeiooouuuAEIOOOUUU"))


def szamla_mappak(alarendeltek: list[dict[str, Any]]) -> list[str]:
    """Az otthon fiókjainak számlamappái (a konfigurációs mappához viszonyítva), ismétlődés nélkül."""
    ki: list[str] = []
    for a in alarendeltek:
        m = (a.get("data") or {}).get("szamla_mappa")
        if m and m not in ki:
            ki.append(m)
    return ki


def szamla_fajlok(config_dir: Path, mappak: list[str]) -> list[tuple[str, Path]]:
    """(zip-beli útvonal, valódi fájl) a mappák számla-fájljaira (PDF, XML), alkönyvtárakkal; csak a konfigurációs
    mappán belül."""
    gyoker = config_dir.resolve()
    ki: dict[str, Path] = {}
    for m in mappak:
        mappa = (config_dir / m).resolve()
        if not mappa.is_dir() or gyoker not in mappa.parents:
            continue
        for f in sorted(mappa.rglob("*")):
            if f.is_file() and f.suffix.lower() in SZAMLA_KITERJESZTESEK:
                rel = f.resolve().relative_to(gyoker).as_posix()
                ki.setdefault(rel, f)
    return sorted(ki.items())


def zip_ir(cel: Path, otthonok: list[OtthonMentes], szamlak: list[tuple[str, Path]], verzio: str, keszult: str) -> int:
    """A mentés megírása (előbb ideiglenes fájlba, majd átnevezve – félkész zip nem marad). Visszaadja a méretet."""
    cel.parent.mkdir(parents=True, exist_ok=True)
    tmp = cel.with_suffix(".zip.tmp")
    manifest = {
        "formatum": FORMATUM, "rezsikoveto": verzio, "keszult": keszult,
        "otthonok": [{"nev": o.nev, "entry_id": o.entry_id, "fiokok": len(o.alarendeltek), "fajl": f"otthonok/{i + 1}.json"}
                     for i, o in enumerate(otthonok)],
        "szamlak": len(szamlak),
    }
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        for i, o in enumerate(otthonok):
            z.writestr(f"otthonok/{i + 1}.json", json.dumps(o.dict(), ensure_ascii=False))
        for rel, f in szamlak:
            z.write(f, f"szamlak/{rel}")
    tmp.replace(cel)
    return cel.stat().st_size


def _biztonsagos(nev: str) -> str | None:
    """A zip-beli számla útvonala a konfigurációs mappához viszonyítva – abszolút vagy kilépő („..”) útvonal nincs."""
    p = PurePosixPath(nev)
    if p.is_absolute() or ".." in p.parts or len(p.parts) < 2 or p.parts[0] != "szamlak":
        return None
    rel = PurePosixPath(*p.parts[1:])
    return rel.as_posix() if rel.suffix.lower() in SZAMLA_KITERJESZTESEK else None


def zip_olvas(forras: Path) -> tuple[dict[str, Any], list[OtthonMentes], list[str]]:
    """(manifest, otthonok, számla-fájlok zip-beli nevei). Hibás / idegen fájlnál MentesHiba."""
    try:
        z = zipfile.ZipFile(forras)
    except (zipfile.BadZipFile, OSError) as err:
        raise MentesHiba(f"nem olvasható zip: {err}") from err
    with z:
        try:
            manifest = json.loads(z.read("manifest.json"))
        except KeyError as err:
            raise MentesHiba("nem Rezsikövető-mentés (nincs manifest.json)") from err
        if manifest.get("formatum") != FORMATUM:
            raise MentesHiba(f"ismeretlen mentésformátum: {manifest.get('formatum')!r}")
        otthonok = []
        for o in manifest.get("otthonok") or []:
            d = json.loads(z.read(o["fajl"]))
            if not isinstance(d.get("alarendeltek"), list) or not isinstance(d.get("tar"), dict):
                raise MentesHiba(f"hibás otthon a mentésben: {o.get('nev')}")
            otthonok.append(OtthonMentes(d["nev"], d["entry_id"], d["alarendeltek"], d["tar"], d.get("negyedek") or {},
                                         d.get("szenzorok") or {}, d.get("beallitas") or {}))
        szamlak = [n for n in z.namelist() if n.startswith("szamlak/") and not n.endswith("/") and _biztonsagos(n)]
    return manifest, otthonok, szamlak


def szamlak_kicsomagol(forras: Path, config_dir: Path, nevek: list[str] | None = None) -> tuple[int, int]:
    """A számla-fájlok visszaírása a konfigurációs mappába – meglévő fájlt nem ír felül. (kiírt, kihagyott)."""
    gyoker = config_dir.resolve()
    kiirt = kihagyott = 0
    with zipfile.ZipFile(forras) as z:
        for n in z.namelist():
            if nevek is not None and n not in nevek:
                continue
            rel = _biztonsagos(n)
            if rel is None:
                continue
            cel = (config_dir / rel).resolve()
            if gyoker not in cel.parents:
                continue
            if cel.exists():
                kihagyott += 1
                continue
            cel.parent.mkdir(parents=True, exist_ok=True)
            cel.write_bytes(z.read(n))
            kiirt += 1
    return kiirt, kihagyott


def otthon_szamlai(otthon: OtthonMentes, szamlak: list[str]) -> list[str]:
    """A mentés számla-fájljai közül azok, amelyek ennek az otthonnak a számlamappáiban vannak."""
    mappak = [m.rstrip("/") + "/" for m in szamla_mappak(otthon.alarendeltek)]
    return [n for n in szamlak if any((_biztonsagos(n) or "").startswith(m) for m in mappak)]


def atkulcsol(tar: dict[str, Any], terkep: dict[str, str]) -> dict[str, Any]:
    """A fiókonként / szigetüzemenként kulcsolt adatok átkulcsolása a régi alárendelt azonosítókról az újakra.
    Ami a térképben nincs (pl. a mentéskor már törölt fiók maradványa), kimarad."""
    ki = {k: v for k, v in tar.items() if k not in ("fiokok", "szigetek", "postafiokok")}
    for resz in ("fiokok", "szigetek", "postafiokok"):
        if resz in tar:
            ki[resz] = {terkep[sid]: adat for sid, adat in (tar.get(resz) or {}).items() if sid in terkep}
    ki.setdefault("fiokok", {})
    return ki


def titkok_nelkul(alarendeltek: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Az alárendelt bejegyzések a mentéshez: az e-mail fiók jelszava nélkül."""
    return [a | {"data": {k: v for k, v in (a.get("data") or {}).items() if k not in TITKOS_KULCSOK}} for a in alarendeltek]


def jelszo_nelkuli_postafiokok(alarendeltek: list[dict[str, Any]]) -> list[str]:
    """A jelszó nélküli e-mail fiókok neve (visszaállítás után ezeknél újra meg kell adni a jelszót)."""
    return [a.get("title") or "" for a in alarendeltek if a.get("subentry_type") == "postafiok" and not (a.get("data") or {}).get("jelszo")]


def email_hivatkozas_atkulcsol(data: dict[str, Any], terkep: dict[str, str]) -> dict[str, Any] | None:
    """A fiók e-mailes beállításában a postafiók-hivatkozások a régi azonosítókról az újakra (ami nincs a térképben,
    kimarad). Nincs mit átírni: None."""
    regi = data.get("email_postafiokok")
    if not regi:
        return None
    uj = [terkep[x] for x in regi if x in terkep]
    return None if uj == regi else data | {"email_postafiokok": uj}


def negyed_atkulcsol(negyedek: dict[str, Any], terkep: dict[str, str]) -> dict[str, Any]:
    return {terkep[sid]: v for sid, v in negyedek.items() if sid in terkep}


def egyedi_nev(nev: str, foglalt: set[str]) -> str:
    """Névütközésnél „(visszaállítva)”, szükség esetén sorszámmal."""
    if nev not in foglalt:
        return nev
    jelolt = f"{nev} (visszaállítva)"
    n = 2
    while jelolt in foglalt:
        jelolt = f"{nev} (visszaállítva {n})"
        n += 1
    return jelolt


def regiek_torlese(mappa: Path, megtart: int) -> list[str]:
    """A legrégebbi mentések törlése, hogy legfeljebb `megtart` maradjon (0 = nincs törlés)."""
    if megtart <= 0 or not mappa.is_dir():
        return []
    fajlok = sorted((f for f in mappa.iterdir() if f.is_file() and FAJLNEV_MINTA.match(f.name)), key=lambda f: f.stat().st_mtime)
    torolt = []
    for f in fajlok[: max(len(fajlok) - megtart, 0)]:
        f.unlink()
        torolt.append(f.name)
    return torolt


def mentesek_listaja(mappa: Path) -> list[dict[str, Any]]:
    """A mappában lévő mentések (legújabb elöl): név, méret, idő, otthonok, számlák száma."""
    ki = []
    if not mappa.is_dir():
        return ki
    for f in mappa.iterdir():
        if not (f.is_file() and FAJLNEV_MINTA.match(f.name)):
            continue
        sor: dict[str, Any] = {"fajl": f.name, "meret": f.stat().st_size, "ido": f.stat().st_mtime}
        try:
            with zipfile.ZipFile(f) as z:
                m = json.loads(z.read("manifest.json"))
            sor |= {"keszult": m.get("keszult"), "otthonok": [o["nev"] for o in m.get("otthonok") or []],
                    "szamlak": m.get("szamlak", 0), "verzio": m.get("rezsikoveto")}
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            sor["hiba"] = "nem olvasható"
        ki.append(sor)
    return sorted(ki, key=lambda x: x["ido"], reverse=True)


# ---------------------------------------------------------------------------------------------- szenzor-hivatkozások

# A fiókok beállításaiban szenzorra mutató kulcsok és a panelen mutatott szerepük.
SZENZOR_KULCSOK = {
    "forras_entitas": "mérőállás / fogyasztás",
    "h_teli_forras": "H téli regiszter (1.81)",
    "h_nyari_forras": "H nyári regiszter (1.82)",
    "a2_csucs_forras": "A2 csúcs (1.8.1)",
    "a2_volgy_forras": "A2 völgy (1.8.2)",
    "betaplalas_entitas": "betáplálás (2.8.0)",
    "almero_forras": "locsolási almérő",
    "profil_forras": "havi elosztás (profil)",
}
SZIGET_SZEREP_NEV = {
    "fogyasztas": "fogyasztás", "pv": "PV-termelés", "akku_toltes": "akku töltés", "akku_kisutes": "akku kisütés",
    "halozat": "hálózati vételezés", "halozat_akku": "hálózatról akkuba", "export": "visszatáplálás",
    "generator": "generátor", "egyeb_termeles": "egyéb termelés",
}


def szenzor_hivatkozasok(alarendeltek: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Minden szenzor-hivatkozás: {sid, fiok, kulcs, idx (lista eleme, különben None), szerep, entity_id}."""
    ki = []
    for a in alarendeltek:
        data = a.get("data") or {}
        if a.get("subentry_type") == "sziget":
            for kulcs, ertek in data.items():
                if kulcs.startswith("forras_") and isinstance(ertek, list):
                    nev = SZIGET_SZEREP_NEV.get(kulcs[len("forras_"):], kulcs)
                    ki += [{"sid": a["subentry_id"], "fiok": a["title"], "kulcs": kulcs, "idx": i, "szerep": f"szigetüzem: {nev}",
                            "entity_id": e} for i, e in enumerate(ertek) if e]
            continue
        for kulcs, szerep in SZENZOR_KULCSOK.items():
            if data.get(kulcs):
                ki.append({"sid": a["subentry_id"], "fiok": a["title"], "kulcs": kulcs, "idx": None, "szerep": szerep,
                           "entity_id": data[kulcs]})
    return ki


def szenzor_csere(data: dict[str, Any], kulcs: str, idx: int | None, uj: str | None) -> dict[str, Any]:
    """A beállítás másolata, benne a hivatkozás az új szenzorra (üres: a hivatkozás törlése)."""
    ki = dict(data)
    if idx is None:
        if uj:
            ki[kulcs] = uj
        else:
            ki.pop(kulcs, None)
        return ki
    lista = list(ki.get(kulcs) or [])
    if idx < len(lista):
        lista[idx] = uj or None
    ki[kulcs] = [e for e in lista if e]
    return ki


# ---------------------------------------------------------------------------------- Home Assistant mentésből olvasás

KIHAGYOTT_MAPPAK = {".storage", "custom_components", "www", "deps", "tts", "blueprints", "themes", ".cloud", "image",
                    "rezsikoveto_mentes", "backups", ".cache"}


@dataclass
class HaMentesTartalom:
    config_entries: dict[str, Any] | None = None
    entity_registry: dict[str, Any] | None = None
    tarolok: dict[str, dict[str, Any]] = field(default_factory=dict)  # „hu_rezsi.<id>” / „hu_rezsi_negyedek.<id>” → adat
    szamlak: dict[str, Path] = field(default_factory=dict)  # konfigurációhoz viszonyított út → ideiglenes fájl


def ha_mentes_olvas(kulso: Any, ideiglenes: Path) -> HaMentesTartalom:
    """Egy (visszafejtett) Home Assistant mentés folyamatos olvasása: a homeassistant.tar.gz-ből a Rezsikövető
    beállításai (core.config_entries), tárolói, az entitás-nyilvántartás és a számla-fájlok (PDF, XML) – ez utóbbiak
    az ideiglenes mappába. `kulso`: a külső tar fájlobjektuma (stream is lehet)."""
    t = HaMentesTartalom()
    with tarfile.open(fileobj=kulso, mode="r|") as kt:
        for m in kt:
            if not PurePosixPath(m.name).name.startswith("homeassistant.tar"):
                continue
            with tarfile.open(fileobj=kt.extractfile(m), mode="r|*") as bt:
                for b in bt:
                    if not b.isfile():
                        continue
                    p = PurePosixPath(b.name)
                    if p.parts[:1] != ("data",) or ".." in p.parts:
                        continue
                    rel = PurePosixPath(*p.parts[1:])
                    if rel.parts[:1] == (".storage",) and len(rel.parts) == 2:
                        nev = rel.name
                        if nev in ("core.config_entries", "core.entity_registry") or (
                                re.fullmatch(r"hu_rezsi(_negyedek)?\.[0-9A-Z]+", nev)):
                            adat = json.loads(bt.extractfile(b).read())
                            if nev == "core.config_entries":
                                t.config_entries = adat
                            elif nev == "core.entity_registry":
                                t.entity_registry = adat
                            else:
                                t.tarolok[nev] = adat.get("data") or {}
                        continue
                    if rel.suffix.lower() in SZAMLA_KITERJESZTESEK and rel.parts[0] not in KIHAGYOTT_MAPPAK and len(rel.parts) > 1:
                        cel = ideiglenes / rel.as_posix()
                        cel.parent.mkdir(parents=True, exist_ok=True)
                        with cel.open("wb") as f:
                            shutil.copyfileobj(bt.extractfile(b), f)
                        t.szamlak[rel.as_posix()] = cel
            break
    return t


def ha_mentesbol_otthonok(t: HaMentesTartalom) -> list[OtthonMentes]:
    """A HA-mentés tartalmából Rezsikövető-otthonok (a szenzorok nevét az entitás-nyilvántartásból)."""
    if not t.config_entries:
        raise MentesHiba("a mentésben nincs Home Assistant-konfiguráció (core.config_entries)")
    reg = {e["entity_id"]: e for e in ((t.entity_registry or {}).get("data") or {}).get("entities", [])}
    ki = []
    for e in (t.config_entries.get("data") or {}).get("entries", []):
        if e.get("domain") != "hu_rezsi":
            continue
        alar = [{"subentry_id": s["subentry_id"], "subentry_type": s["subentry_type"], "title": s["title"], "data": s["data"]}
                for s in e.get("subentries") or []]
        szenzorok = {}
        for h in szenzor_hivatkozasok(alar):
            r = reg.get(h["entity_id"]) or {}
            szenzorok[h["entity_id"]] = {"nev": r.get("name") or r.get("original_name") or h["entity_id"],
                                         "egyseg": r.get("unit_of_measurement")}
        ki.append(OtthonMentes(e["title"], e["entry_id"], alar, t.tarolok.get(f"hu_rezsi.{e['entry_id']}") or {"fiokok": {}},
                               t.tarolok.get(f"hu_rezsi_negyedek.{e['entry_id']}") or {}, szenzorok))
    if not ki:
        raise MentesHiba("a mentésben nincs Rezsikövető-otthon")
    return ki
