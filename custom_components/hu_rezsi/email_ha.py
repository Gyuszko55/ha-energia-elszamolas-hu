"""Számlák beolvasása e-mailből – a Home Assistant-oldal: ütemezés, postafiók-állapot a tárban, javítandó probléma
(hibás jelszó, elérhetetlen szerver), a melléklet nélküli számlaértesítők rögzítése, a panel és a szolgáltatás.

Óránként és a HA elindulása után (a háttérben) minden postafiókot külön átnéz (végrehajtó szálon, email_szamlak);
egy hibás postafiók a többit és a fiókok számolását nem akadályozza. A mentett PDF/XML a fiók számlamappájába kerül,
onnan a szokásos mappa-feldolgozás olvassa be (jóváhagyásra váró számlaként).

Tartalom szerinti besorolás (email_auto): a fiók számláit nem a feladó/tárgy szűrő, hanem a melléklet beolvasása
(mérő gyári száma, mérési pont, szolgáltató, közmű) választja ki. Új postafiók után (és kérésre: „Keresés újra”) a
felderítés az utolsó 180 nap számláit megkeresi, és a fiókokhoz rendeli: egyértelmű esetben magától bekapcsolja az
e-mailes számlákat a fióknál, kétes esetben kérdést, ismeretlen szolgáltatónál fiók-ajánlatot tesz a panelre.
A változás (alárendelt bejegyzés frissítése) után az otthon újratöltődik; a felzárkózó átnézés (180 nap) az
újratöltött otthonban fut le (a jelzője a tárban van, így HA-újraindítás után is)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from . import email_szamlak as es
from types import MappingProxyType

from .const import (
    CONF_EMAIL_AUTO,
    CONF_EMAIL_CIM,
    CONF_EMAIL_FELADOK,
    CONF_EMAIL_KUKA,
    CONF_EMAIL_NAPOK,
    CONF_EMAIL_POSTAFIOKOK,
    CONF_IMAP_PORT,
    CONF_IMAP_SSL,
    CONF_IMAP_SZERVER,
    CONF_JELSZO,
    CONF_KOZMU,
    CONF_SZAMLA_MAPPA,
    CONF_SZOLGALTATO,
    DOMAIN,
    EMAIL_ATNEZES_ORA,
    EMAIL_INDULAS_MP,
    FIOK,
    POSTAFIOK,
)

_LOGGER = logging.getLogger(__name__)
UTOLSO_TALALATOK = 10
UZENET_NAP = 14  # a panel ennyi napig mutatja a felderítés üzeneteit (vagy amíg „Rendben”-t nem nyomnak)
INTEGRACIO_OLDAL = "/config/integrations/integration/hu_rezsi"

# A bejelentkezés-ellenőrzés hibái közérthetően (a panel párbeszédablakához; a beállító felületen a fordítás).
HIBA_SZOVEGEK = {
    "cim_hibas": "Ez nem tűnik e-mail címnek – ellenőrizd (pl. valaki@gmail.com).",
    "jelszo_kell": "Add meg a jelszót (Gmailnél az alkalmazásjelszót).",
    "nem_tamogatott": "A Microsoft (Outlook, Hotmail, Live) jelszóval már nem enged be levelezőprogramot. Állíts be ott "
                      "továbbítást a számlalevelekről egy Gmail- vagy Freemail-címre, és azt add meg itt.",
    "kapcsolat": "A levelezőszerver nem érhető el. Ellenőrizd az internetkapcsolatot; ha nem Gmail/Freemail címed van, "
                 "a Haladó részben a szerver nevét.",
    "szerver_ismeretlen": "Nem találtam a levelezőszerveredet. Nézd meg a levelező súgójában az „IMAP-szerver” nevét, "
                          "és írd be a Haladó részbe.",
    "ismeretlen": "Váratlan hiba a bejelentkezéskor – lásd a Home Assistant naplóját.",
    "mar_van": "Ez az e-mail cím már fel van véve ennél az otthonnál.",
}


def hiba_szoveg(kulcs: str, szerver: str = "") -> str:
    if kulcs.startswith("hitelesites"):
        return es.hitelesites_szoveg(szerver)
    return HIBA_SZOVEGEK.get(kulcs, HIBA_SZOVEGEK["ismeretlen"])


def postafiok_adat(bemenet: dict[str, Any], regi: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    """A postafiók tárolt adatai a (beállító felület vagy a panel) bemenetéből: a szerver/port/SSL a cím
    domainjéből, ha nincs megadva; a jelszó szóközök nélkül, ahol a levelező csoportokban mutatja; a név alapból a
    cím „@” előtti része. Visszaad: (adat, név)."""
    regi = regi or {}
    cim = str(bemenet.get(CONF_EMAIL_CIM) or "").strip()
    lv = es.levelezo(cim)
    szerver = str(bemenet.get(CONF_IMAP_SZERVER) or "").strip() or lv["szerver"]
    jelszo = str(bemenet.get(CONF_JELSZO) or "") or str(regi.get(CONF_JELSZO) or "")  # üresen hagyva marad a régi
    adat = {
        CONF_EMAIL_CIM: cim,
        CONF_JELSZO: es.jelszo_tisztitas(jelszo, szerver),
        CONF_IMAP_SZERVER: szerver,
        CONF_IMAP_PORT: int(bemenet.get(CONF_IMAP_PORT) or regi.get(CONF_IMAP_PORT) or es.ALAP_PORT),
        CONF_IMAP_SSL: bool(bemenet.get(CONF_IMAP_SSL, regi.get(CONF_IMAP_SSL, True))),
        CONF_EMAIL_NAPOK: int(bemenet.get(CONF_EMAIL_NAPOK) or regi.get(CONF_EMAIL_NAPOK) or es.ALAP_NAPOK),
        CONF_EMAIL_KUKA: bool(bemenet.get(CONF_EMAIL_KUKA, regi.get(CONF_EMAIL_KUKA, True))),
    }
    nev = str(bemenet.get("nev") or "").strip() or str(regi.get("nev") or "").strip() or es.alap_nev(cim)
    return adat, nev


async def bejelentkezes_ellenorzes(hass: HomeAssistant, adat: dict[str, Any], nev: str = "") -> str | None:
    """A beállító felület és a panel közös ellenőrzése: None, ha be tud lépni; különben a hiba kulcsa
    (cim_hibas, jelszo_kell, nem_tamogatott, hitelesites_<levelező>, kapcsolat, szerver_ismeretlen, ismeretlen)."""
    cim = adat.get(CONF_EMAIL_CIM) or ""
    if not es.CIM_MINTA.match(cim):
        return "cim_hibas"
    if not adat.get(CONF_JELSZO):
        return "jelszo_kell"
    lv = es.levelezo(cim)
    if lv.get("nem_tamogatott") and adat.get(CONF_IMAP_SZERVER) == lv["szerver"]:
        return "nem_tamogatott"
    pf = es.Postafiok.adatbol("", nev, adat)
    try:
        await hass.async_add_executor_job(es.bejelentkezes_proba, pf)
    except es.HitelesitesiHiba:
        kulcs = es.levelezo_szerverbol(pf.szerver)
        return f"hitelesites_{kulcs}" if kulcs != "egyeb" else "hitelesites"
    except es.KapcsolatiHiba:
        return "kapcsolat" if lv["ismert"] or adat.get(CONF_IMAP_SZERVER) != lv["szerver"] else "szerver_ismeretlen"
    except es.EmailHiba:
        return "ismeretlen"
    return None


def nevelo(nev: str) -> str:
    """A névelő a név elé: „az „Áram A1”” / „a „Gáz””."""
    return "az" if (nev or "x").strip()[:1].lower() in "aáeéiíoóöőuúüű" else "a"


def fiokhoz(nev: str) -> str:
    return f"{nevelo(nev)} „{nev}” fiókhoz"


def felado_terkep(tar: Any) -> dict[str, set[str]]:
    """Az ismert szolgáltatói feladók (dijszabasok/szolgaltatok.yaml „email_feladok”): domain → szolgáltató-kulcsok."""
    ki: dict[str, set[str]] = {}
    for kulcs, sz in (getattr(tar, "szolgaltatok", None) or {}).items():
        for f in sz.get("email_feladok") or []:
            ki.setdefault(str(f).lower().lstrip("@"), set()).add(kulcs)
    return ki


def alap_mappa(hass: HomeAssistant, nev: str, sajat: str | None = None) -> str:
    """Alapértelmezett számlamappa az e-mailes számláknak: Szamlak/<fióknév>, ha más fiók még nem használja."""
    import re  # noqa: PLC0415

    tiszta = re.sub(r"[^0-9A-Za-z]+", "_", (nev or "fiok").translate(str.maketrans("áéíóöőúüűÁÉÍÓÖŐÚÜŰ", "aeiooouuuAEIOOOUUU"))).strip("_") or "fiok"
    foglalt = {
        str(s.data.get(CONF_SZAMLA_MAPPA)) for e in hass.config_entries.async_entries(DOMAIN)
        for sid, s in e.subentries.items() if sid != sajat and s.data.get(CONF_SZAMLA_MAPPA)
    }
    jelolt, n = f"Szamlak/{tiszta}", 2
    while jelolt in foglalt:
        jelolt, n = f"Szamlak/{tiszta}_{n}", n + 1
    return jelolt


def issue_id(sid: str) -> str:
    return f"email_hiba_{sid}"


def postafiokok(entry: ConfigEntry) -> dict[str, ConfigSubentry]:
    return {sid: s for sid, s in entry.subentries.items() if s.subentry_type == POSTAFIOK}


def ismert_sorszamok(tarolo_adat: dict[str, Any]) -> set[str]:
    """A háztartás minden már ismert számla-sorszáma: rögzített, jóváhagyásra váró és elvetett."""
    ki: set[str] = set()
    for t in (tarolo_adat.get("fiokok") or {}).values():
        ki |= set(t.get("szamlak") or {})
        ki |= {x.get("sorszam") for x in t.get("fuggo") or [] if x.get("sorszam")}
        ki |= {x.get("sorszam") for x in t.get("elvetett_szamlak") or [] if x.get("sorszam")}
    return ki


def _futtat(pf: es.Postafiok, fiokok: list[tuple[str, str, dict[str, Any]]], config_dir: Path, ismert: set[str],
            latott: dict[str, str], ma: date, auto: list[tuple[str, str, dict[str, Any], dict[str, Any], list[str]]] | None = None,
            terkep: dict[str, set[str]] | None = None, napok: int | None = None) -> es.Eredmeny:
    """Végrehajtó szálon: a fiókok szűrői (a mappák feloldása fájlrendszer-hívás) és a postafiók átnézése."""
    szurok = [es.FiokSzuro.adatbol(sid, nev, data, config_dir) for sid, nev, data in fiokok]
    if not auto:  # csak kézi szűrős fiókok: a régi út, változatlanul
        return es.atnez(pf, szurok, ismert, latott, ma) if napok is None else es.atnez(pf, szurok, ismert, latott, ma, napok=napok)
    af = [es.AutoFiok.adatbol(sid, nev, data, tarolt, config_dir, feladok) for sid, nev, data, tarolt, feladok in auto]
    return es.atnez(pf, szurok, ismert, latott, ma, auto=af, felado_terkep=terkep, napok=napok)


def _felderit(pf: es.Postafiok, ma: date, terkep: dict[str, set[str]],
              fiokok: list[tuple[str, str, dict[str, Any], dict[str, Any], list[str]]], config_dir: Path,
              mellozott: set[str], kezi: set[str]) -> es.Felderites:
    """Végrehajtó szálon: a postafiók felderítése és a talált számlák besorolása a háztartás fiókjaihoz."""
    jelek = es.felderit(pf, ma, terkep)
    af = [es.AutoFiok.adatbol(sid, nev, data, tarolt, config_dir, feladok) for sid, nev, data, tarolt, feladok in fiokok]
    return es.osztalyoz(jelek, af, mellozott, kezi)


class EmailFigyelo:
    """Egy háztartás (bejegyzés) e-mail fiókjainak átnézése, felderítése és a fiókokhoz rendelése."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, koord: Any) -> None:
        self.hass = hass
        self.entry = entry
        self.koord = koord
        self._zar = asyncio.Lock()
        self.felderites_fut: set[str] = set()
        self.felderites_kezdet: dict[str, str] = {}  # sid → a futó felderítés kezdete (a panel „… perce fut” sora)

    # ------------------------------------------------------------------ állapot

    def _allapotok(self) -> dict[str, dict[str, Any]]:
        return self.koord.tarolo.adat.setdefault("postafiokok", {})

    def allapot(self, sid: str) -> dict[str, Any]:
        return self._allapotok().setdefault(sid, {})

    def haztartas(self) -> dict[str, Any]:
        """A háztartás felderítési adatai: nyitott kérdések, fiók-ajánlatok, mellőzött csoportok, üzenetek."""
        h = self.koord.tarolo.adat.setdefault("email_felderites", {})
        for k in ("kerdesek", "ajanlatok", "mellozott", "uzenetek"):
            h.setdefault(k, [])
        return h

    def hozzarendelt(self, pf_sid: str) -> list[tuple[str, str, dict[str, Any]]]:
        """A postafiókhoz kézi szűrővel rendelt fiókok (azonosító, név, beállítás) – a feladó nélküliek kimaradnak.
        A tartalom szerinti (email_auto) fiók is itt van, ha van feladója: a szűrője tartalék."""
        return [
            (sid, sub.title, dict(sub.data)) for sid, sub in self.koord.fiokok().items()
            if pf_sid in (sub.data.get(CONF_EMAIL_POSTAFIOKOK) or []) and es.lista(sub.data.get(CONF_EMAIL_FELADOK))
        ]

    def _feladok(self, data: dict[str, Any]) -> list[str]:
        sz = (getattr(self.koord.tar, "szolgaltatok", None) or {}).get(data.get(CONF_SZOLGALTATO)) or {}
        return [str(f).lower() for f in sz.get("email_feladok") or []]

    def _fiok_info(self, sid: str, sub: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], list[str]]:
        return (sid, sub.title, dict(sub.data), dict(self.koord.tarolo.adat.get("fiokok", {}).get(sid) or {}), self._feladok(dict(sub.data)))

    def auto_fiokok(self, pf_sid: str) -> list[tuple[str, str, dict[str, Any], dict[str, Any], list[str]]]:
        """A postafiókhoz tartalom szerint (email_auto) rendelt fiókok."""
        return [self._fiok_info(sid, sub) for sid, sub in self.koord.fiokok().items()
                if pf_sid in (sub.data.get(CONF_EMAIL_POSTAFIOKOK) or []) and sub.data.get(CONF_EMAIL_AUTO)]

    def bekotott(self, pf_sid: str) -> list[dict[str, Any]]:
        """A postafiókhoz kötött fiókok a panelnek: név és mód (automatikus / kézi szűrő)."""
        ki = []
        for sid, sub in self.koord.fiokok().items():
            if pf_sid not in (sub.data.get(CONF_EMAIL_POSTAFIOKOK) or []):
                continue
            if sub.data.get(CONF_EMAIL_AUTO):
                ki.append({"sid": sid, "nev": sub.title, "mod": "auto"})
            elif es.lista(sub.data.get(CONF_EMAIL_FELADOK)):
                ki.append({"sid": sid, "nev": sub.title, "mod": "kezi"})
        return ki

    def takaritas(self) -> None:
        """A törölt postafiókok állapota és javítandó problémája, és a rájuk vonatkozó kérdések / ajánlatok."""
        megvan = set(postafiokok(self.entry))
        for sid in set(self._allapotok()) - megvan:
            self._allapotok().pop(sid, None)
            ir.async_delete_issue(self.hass, DOMAIN, issue_id(sid))
        if "email_felderites" in self.koord.tarolo.adat:
            h = self.haztartas()
            h["kerdesek"] = [k for k in h["kerdesek"] if k.get("pf") in megvan]
            h["ajanlatok"] = [k for k in h["ajanlatok"] if k.get("pf") in megvan]

    # ------------------------------------------------------------------ ütemezés

    def indit(self) -> None:
        self.takaritas()
        for sid in postafiokok(self.entry):
            if sid not in self._allapotok():  # új postafiók (pl. a beállító felületről): felderítés
                self.allapot(sid)["felderites_kell"] = True
        indulo = not self.hass.is_running  # HA-indulás (vagy csak az otthon újratöltése futó HA-n)

        async def _idozitett(_most: datetime | None = None) -> None:
            await self.atnez_mind()

        @callback
        def _hatter(_most: Any = None) -> None:
            if postafiokok(self.entry):
                self.entry.async_create_background_task(self.hass, _idozitett(), "hu_rezsi e-mail átnézés")

        @callback
        def _teendo(_most: Any = None) -> None:
            self.entry.async_create_background_task(self.hass, self.teendok(), "hu_rezsi e-mail felderítés")

        async def _indulaskor(_hass: HomeAssistant) -> None:
            # A HA elindulása után kicsit később: az indulás ne várjon a levelezőszerverre.
            self.entry.async_on_unload(async_call_later(self.hass, EMAIL_INDULAS_MP if indulo else 30, _hatter))
            if self._teendo_van():  # új postafiók felderítése / besorolás utáni felzárkózás (újratöltés után)
                self.entry.async_on_unload(async_call_later(self.hass, EMAIL_INDULAS_MP if indulo else 3, _teendo))

        self.entry.async_on_unload(async_at_started(self.hass, _indulaskor))
        self.entry.async_on_unload(async_track_time_interval(self.hass, _hatter, timedelta(hours=EMAIL_ATNEZES_ORA)))

    def _teendo_van(self) -> bool:
        pfk = postafiokok(self.entry)
        return any(a.get("felderites_kell") or a.get("felzarkozas_kell") for sid, a in self._allapotok().items() if sid in pfk)

    async def teendok(self) -> None:
        """A tárban jelzett teendők: új postafiók felderítése, besorolás utáni felzárkózó átnézés (180 nap)."""
        for sid, sub in postafiokok(self.entry).items():
            a = self.allapot(sid)
            if a.get("felderites_kell"):
                if await self.felderit(sid):
                    return  # fiókot kötött be: az otthon újratöltődik, a felzárkózás ott fut
            if a.get("felzarkozas_kell"):
                await self.felzarkozas(sid)

    # ------------------------------------------------------------------ átnézés

    async def atnez_mind(self) -> dict[str, Any]:
        """Minden postafiók átnézése egymás után; postafiókonként az eredmény (vagy a hiba)."""
        async with self._zar:
            ki: dict[str, Any] = {}
            uj_fajl = False
            for sid, sub in postafiokok(self.entry).items():
                try:
                    ki[sid] = await self._atnez(sid, sub)
                    uj_fajl |= bool(ki[sid].get("mentett"))
                except Exception as err:  # noqa: BLE001 – egy postafiók hibája ne állítsa meg a többit
                    _LOGGER.exception("%s: váratlan hiba az e-mail átnézésekor", sub.title)
                    self._hiba(sid, sub, es.EmailHiba(f"{type(err).__name__}: {err}"))
                    ki[sid] = {"nev": sub.title, "hiba": str(err)}
            await self.koord.tarolo.ment()
        if uj_fajl:
            await self.koord.async_request_refresh()  # a számlamappák feldolgozása (jóváhagyásra váró számlák)
        return ki

    async def felzarkozas(self, sid: str) -> dict[str, Any]:
        """Besorolás után egyszer: a postafiók utolsó 180 napja (a „látott” levelek nélkül – a korábban más fiókhoz
        nem illő levelek most besorolhatók; a már ismert számla sorszám szerint kimarad)."""
        sub = postafiokok(self.entry).get(sid)
        if sub is None:
            return {}
        async with self._zar:
            try:
                ki = await self._atnez(sid, sub, napok=es.FELDERITES_NAPOK, latott_nelkul=True)
            finally:
                self.allapot(sid).pop("felzarkozas_kell", None)
                await self.koord.tarolo.ment()
        if ki.get("mentett"):
            await self.koord.async_request_refresh()
        return ki

    async def _atnez(self, sid: str, sub: ConfigSubentry, napok: int | None = None, latott_nelkul: bool = False) -> dict[str, Any]:
        all_ = self.allapot(sid)
        most = dt_util.now().replace(microsecond=0)
        fiokok = self.hozzarendelt(sid)
        auto = self.auto_fiokok(sid)
        all_["utolso_atnezes"] = most.isoformat()
        all_["fiokok"] = len({x[0] for x in fiokok} | {x[0] for x in auto})
        if not fiokok and not auto:
            # Nincs hozzárendelt fiók: nem kapcsolódunk (a hibajelzés is lekerül).
            all_.update(hiba=None, hiba_tipus=None, utolso_talalt=0)
            ir.async_delete_issue(self.hass, DOMAIN, issue_id(sid))
            return {"nev": sub.title, "fiokok": 0}
        pf = es.Postafiok.adatbol(sid, sub.title, dict(sub.data))
        ismert = ismert_sorszamok(self.koord.tarolo.adat)
        latott = {} if latott_nelkul else dict(all_.get("latott") or {})
        try:
            if auto:
                er: es.Eredmeny = await self.hass.async_add_executor_job(
                    _futtat, pf, fiokok, Path(self.hass.config.config_dir), ismert, latott, dt_util.now().date(),
                    auto, felado_terkep(self.koord.tar), napok)
            elif napok is not None:
                er = await self.hass.async_add_executor_job(
                    _futtat, pf, fiokok, Path(self.hass.config.config_dir), ismert, latott, dt_util.now().date(), None, None, napok)
            else:
                er = await self.hass.async_add_executor_job(
                    _futtat, pf, fiokok, Path(self.hass.config.config_dir), ismert, latott, dt_util.now().date())
        except es.EmailHiba as err:
            self._hiba(sid, sub, err)
            return {"nev": sub.title, "hiba": str(err), "hiba_tipus": err.tipus}
        if latott_nelkul:  # a felzárkózás a régi „látott” leveleket is megtartja
            er.latott = {**dict(all_.get("latott") or {}), **er.latott}
        rogzitett = await self._ertesitok(er)
        talalatok = [
            {"datum": x["datum"], "fiok": x["fiok_nev"], "fajl": x["fajl"], "sorszam": x["sorszam"], "tipus": "melleklet"}
            for x in er.mentett
        ] + [
            {"datum": x["datum"], "fiok": x["fiok_nev"], "sorszam": x["adat"]["sorszam"], "osszeg": x["adat"]["osszeg"],
             "tipus": "ertesito"} for x in rogzitett
        ] + [
            {"datum": x["datum"], "fiok": ", ".join(x["fiokok"]), "ok": x["ok"], "tipus": "nem_besorolhato"}
            for x in er.nem_besorolhato
        ]
        uj = len(er.mentett) + len(rogzitett)
        all_.update(
            hiba=None, hiba_tipus=None, utolso_sikeres=most.isoformat(), utolso_talalt=uj,
            osszes_talalt=int(all_.get("osszes_talalt") or 0) + uj, latott=er.latott, kihagyva=er.kihagyva,
            nem_besorolhato=len(er.nem_besorolhato),
            utolso_talalatok=(talalatok + list(all_.get("utolso_talalatok") or []))[:UTOLSO_TALALATOK] if talalatok
            else list(all_.get("utolso_talalatok") or []),
        )
        ir.async_delete_issue(self.hass, DOMAIN, issue_id(sid))
        if er.mentett or er.nem_besorolhato:
            _LOGGER.info("%s: %d számla-fájl mentve, %d ismert kihagyva, %d nem besorolható levél", sub.title,
                         len(er.mentett), er.kihagyva, len(er.nem_besorolhato))
        return {"nev": sub.title, "mentett": len(er.mentett), "rogzitett": len(rogzitett), "kihagyva": er.kihagyva,
                "nem_besorolhato": len(er.nem_besorolhato)}

    # ------------------------------------------------------------------ felderítés és besorolás

    def _uzenet(self, szoveg: str) -> None:
        h = self.haztartas()
        h["uzenetek"] = [{"ido": dt_util.now().replace(microsecond=0).isoformat(), "szoveg": szoveg}, *h["uzenetek"]][:10]

    def _kezi(self, pf_sid: str) -> set[str]:
        return {sid for sid, _, data in self.hozzarendelt(pf_sid) if not data.get(CONF_EMAIL_AUTO)}

    def _bekapcsolt_adat(self, sid: str, sub: Any, pf_sid: str) -> dict[str, Any]:
        """A fiók új beállítása: e-mailes számlák ebből a postafiókból, tartalom szerinti besorolással; számlamappa
        nélkül saját mappát kap (a mappa-feldolgozás onnan olvas)."""
        data = dict(sub.data)
        data[CONF_EMAIL_POSTAFIOKOK] = sorted(set(data.get(CONF_EMAIL_POSTAFIOKOK) or []) | {pf_sid})
        data[CONF_EMAIL_AUTO] = True
        if not data.get(CONF_SZAMLA_MAPPA):
            data[CONF_SZAMLA_MAPPA] = alap_mappa(self.hass, sub.title, sid)
        return data

    async def felderit(self, sid: str, mar_jelolt: bool = False) -> bool:
        """A postafiók felderítése (utolsó 180 nap) és a talált számlák besorolása. Egyértelmű esetben a fióknál
        bekapcsolja az e-mailes számlákat (tartalom szerint), kétesnél kérdést, fiók nélkülinél ajánlatot tesz a
        panelre. True: fiókot kötött be (az otthon újratöltődik)."""
        sub = postafiokok(self.entry).get(sid)
        if sub is None:
            self.felderites_fut.discard(sid)
            self.felderites_kezdet.pop(sid, None)
            return False
        if sid in self.felderites_fut and not mar_jelolt:
            return False  # már fut
        all_ = self.allapot(sid)
        self.felderites_fut.add(sid)
        self.felderites_kezdet.setdefault(sid, dt_util.now().replace(microsecond=0).isoformat())
        try:
            h = self.haztartas()
            fiokok = [self._fiok_info(fsid, fsub) for fsid, fsub in self.koord.fiokok().items()]
            pf = es.Postafiok.adatbol(sid, sub.title, dict(sub.data))
            try:
                fe: es.Felderites = await self.hass.async_add_executor_job(
                    _felderit, pf, dt_util.now().date(), felado_terkep(self.koord.tar), fiokok,
                    Path(self.hass.config.config_dir), set(h["mellozott"]), {b["sid"] for b in self.bekotott(sid)})
            except es.EmailHiba as err:
                self._hiba(sid, sub, err)
                all_["felderites"] = {"ido": dt_util.now().replace(microsecond=0).isoformat(), "hiba": str(err), "hiba_tipus": err.tipus}
                all_.pop("felderites_kell", None)
                await self.koord.tarolo.ment()
                return False
            ir.async_delete_issue(self.hass, DOMAIN, issue_id(sid))
            fiok_subs = self.koord.fiokok()
            frissit = {fsid: self._bekapcsolt_adat(fsid, fiok_subs[fsid], sid) for fsid in fe.osszekot if fsid in fiok_subs}
            for fsid, x in fe.osszekot.items():
                for forras in x["forrasok"]:
                    self._uzenet(f"{es.FORRAS_ALANY.get(forras, 'A számlák')} mostantól e-mailből jönnek {fiokhoz(x['nev'])}.")
            h["kerdesek"] = [k for k in h["kerdesek"] if k.get("pf") != sid] + [{**k, "pf": sid} for k in fe.kerdesek]
            h["ajanlatok"] = [k for k in h["ajanlatok"] if k.get("pf") != sid] + [{**k, "pf": sid} for k in fe.ajanlatok]
            all_["felderites"] = {
                "ido": dt_util.now().replace(microsecond=0).isoformat(), "talalt": fe.talalt,
                "osszekotve": [{"sid": k, "nev": v["nev"], "szamlak": v["szamlak"], "tipusok": v["tipusok"]} for k, v in fe.osszekot.items()],
                "mar_bekotve": [{"sid": k, "nev": v["nev"], "szamlak": v["szamlak"], "tipusok": v["tipusok"]} for k, v in fe.mar_bekotve.items()],
                "kerdesek": len(fe.kerdesek), "ajanlatok": len(fe.ajanlatok),
            }
            all_.pop("felderites_kell", None)
            if frissit:
                all_["felzarkozas_kell"] = True
            await self.koord.tarolo.ment()
            sorok = [u["szoveg"] for u in h["uzenetek"][:len(fe.osszekot)]] if fe.osszekot else []
            if fe.kerdesek:
                sorok.append(f"{len(fe.kerdesek)} számláról nem tudom biztosan, melyik fiókhoz tartozik – válassz a Rezsikövető panelen.")
            if fe.ajanlatok:
                sorok.append("Olyan szolgáltató számláit is találtam, amelyhez nincs fiók – a Rezsikövető panelen felveheted.")
            if sorok:
                persistent_notification.async_create(
                    self.hass, "\n".join(f"- {x}" for x in sorok),
                    title=f"Rezsikövető – {self.entry.title}: számlák e-mailből", notification_id=f"{DOMAIN}_felderites_{self.entry.entry_id}")
            # Utolsó lépés (await nélkül): a fiókok frissítése – utána az otthon újratöltődik.
            for fsid, data in frissit.items():
                self.hass.config_entries.async_update_subentry(self.entry, fiok_subs[fsid], data=data)
            return bool(frissit)
        finally:
            self.felderites_fut.discard(sid)
            self.felderites_kezdet.pop(sid, None)

    async def felderites_most(self, sid: str | None = None) -> dict[str, Any]:
        """„Keresés újra”: a megadott (vagy minden) postafiók felderítése."""
        ki = {}
        for psid in ([sid] if sid else list(postafiokok(self.entry))):
            if psid not in postafiokok(self.entry):
                raise ValueError("Nincs ilyen e-mail fiók.")
            ki[psid] = await self.felderit(psid)
        return {"bekotott": any(ki.values())}

    def _keres(self, lista: str, azon: str) -> dict[str, Any]:
        x = next((k for k in self.haztartas()[lista] if k.get("id") == azon), None)
        if x is None:
            raise ValueError("Ez a kérdés már nem aktuális.")
        return x

    async def valasz(self, tipus: str, azon: str, ertek: str) -> dict[str, Any]:
        """A panel kártyáinak gombjai. tipus „kerdes”: ertek = a fiók azonosítója vagy „egyik_sem”; „ajanlat”:
        „letrehoz” vagy „nem_kell”; „uzenet”: az üzenetek nyugtázása; „auto”: azon = postafiók – a kézi szűrős
        fiókjai tartalom szerinti besorolásra váltanak (a szűrő tartalék marad)."""
        h = self.haztartas()
        if tipus == "uzenet":
            h["uzenetek"] = []
            await self.koord.tarolo.ment()
            return {}
        if tipus == "auto":
            pf_sid = azon
            if pf_sid not in postafiokok(self.entry):
                raise ValueError("Nincs ilyen e-mail fiók.")
            subs = self.koord.fiokok()
            valt = {sid: subs[sid] for sid in self._kezi(pf_sid)}
            for sid, sub in valt.items():
                self._uzenet(f"„{sub.title}”: a számlák mostantól a tartalmuk szerint kerülnek a fiókhoz (a feladó-szűrő tartaléknak marad).")
            if valt:
                self.allapot(pf_sid)["felzarkozas_kell"] = True
            await self.koord.tarolo.ment()
            for sid, sub in valt.items():
                self.hass.config_entries.async_update_subentry(self.entry, sub, data={**dict(sub.data), CONF_EMAIL_AUTO: True})
            return {"valtott": len(valt)}
        if tipus == "kerdes":
            k = self._keres("kerdesek", azon)
            h["kerdesek"] = [x for x in h["kerdesek"] if x is not k]
            if ertek == "egyik_sem":
                h["mellozott"] = sorted(set(h["mellozott"]) | {azon})
                await self.koord.tarolo.ment()
                return {}
            subs = self.koord.fiokok()
            if ertek not in subs or ertek not in {j["sid"] for j in k.get("jeloltek") or []}:
                raise ValueError("Ismeretlen fiók.")
            # Ugyanerre a fiókra mutató többi kérdés is megoldódik? Nem: más mérő / szolgáltató – azok maradnak.
            self._uzenet(f"{es.FORRAS_ALANY.get(azon.split('|')[0], 'A számlák')} mostantól e-mailből jönnek {fiokhoz(subs[ertek].title)}.")
            data = self._bekapcsolt_adat(ertek, subs[ertek], k["pf"])
            self.allapot(k["pf"])["felzarkozas_kell"] = True
            await self.koord.tarolo.ment()
            self.hass.config_entries.async_update_subentry(self.entry, subs[ertek], data=data)
            return {"bekotott": ertek}
        if tipus == "ajanlat":
            a = self._keres("ajanlatok", azon)
            if ertek == "nem_kell":
                h["ajanlatok"] = [x for x in h["ajanlatok"] if x is not a]
                h["mellozott"] = sorted(set(h["mellozott"]) | {azon})
                await self.koord.tarolo.ment()
                return {}
            if ertek != "letrehoz":
                raise ValueError("Ismeretlen válasz.")
            lehet = list(a.get("szolgaltatok") or [])
            szolg = lehet[0] if len(lehet) == 1 else None  # MVM villany: az elosztói terület a varázslóban választható
            if a.get("kozmu") == "tavkozles" and szolg:
                # Internet/TV/telefon: fix díjas, mérő nélküli fiók – a varázsló is csak ennyit kér.
                tar = self.koord.tar
                nev = (tar.szolgaltatok.get(szolg) or {}).get("nev", szolg)
                fiok = ConfigSubentry(data=MappingProxyType({
                    CONF_KOZMU: "tavkozles", CONF_SZOLGALTATO: szolg, "dijszabas": "tavkozles/elofizetes", "dijszabas_tol": "2000-01-01",
                    "szamlazas_honap": "1", CONF_SZAMLA_MAPPA: alap_mappa(self.hass, nev), CONF_EMAIL_POSTAFIOKOK: [a["pf"]], CONF_EMAIL_AUTO: True,
                }), subentry_type=FIOK, title=nev, unique_id=None)
                h["ajanlatok"] = [x for x in h["ajanlatok"] if x is not a]
                self._uzenet(f"Új fiók: „{nev}”. {es.FORRAS_ALANY.get(a.get('forras'), 'A számlák')} mostantól e-mailből jönnek ide.")
                self.allapot(a["pf"])["felzarkozas_kell"] = True
                await self.koord.tarolo.ment()
                self.hass.config_entries.async_add_subentry(self.entry, fiok)
                return {"letrehozva": fiok.subentry_id}
            # Mérős közmű: a fiók-varázsló kell (mérő, kezdőállás) – előtöltve nyílik a „Fiók hozzáadása”.
            self.hass.data.setdefault(DOMAIN, {}).setdefault("elotoltes", {})[self.entry.entry_id] = {
                CONF_KOZMU: a.get("kozmu"), CONF_SZOLGALTATO: szolg, "pf": a["pf"], "nev": a.get("nev"), "id": azon}
            return {"navigal": INTEGRACIO_OLDAL}
        raise ValueError("Ismeretlen művelet.")

    def _hiba(self, sid: str, sub: ConfigSubentry, err: es.EmailHiba) -> None:
        all_ = self.allapot(sid)
        elozo = all_.get("hiba")
        all_.update(hiba=str(err), hiba_tipus=err.tipus, utolso_talalt=0)
        if elozo != str(err):
            _LOGGER.warning("%s: az e-mail fiók nem nézhető át: %s", sub.title, err)
        ir.async_create_issue(
            self.hass, DOMAIN, issue_id(sid), is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key="jelszo_hianyzik" if err.tipus == "jelszo_hianyzik" else "email_hiba",
            translation_placeholders={"otthon": self.entry.title, "postafiok": sub.title, "hiba": str(err)[:300]},
        )

    async def _ertesitok(self, er: es.Eredmeny) -> list[dict[str, Any]]:
        """A melléklet nélküli számlaértesítők rögzítése kézi számlaként (tipus egyeb), a szamla_rogzites útján."""
        if not er.ertesitok:
            return []
        from .szolgaltatasok import kezi_szamla_rogzitese  # noqa: PLC0415 – körkörös import elkerülése

        kesz = []
        fiokok = self.koord.fiokok()
        async with self.koord._zar:  # noqa: SLF001 – a számolással egyszerre ne írjuk a tárat
            for x in er.ertesitok:
                a = x["adat"]
                if x["fiok"] not in fiokok:
                    continue
                tarolt = self.koord.tarolo.fiok(x["fiok"])
                if a["sorszam"] in (tarolt.get("szamlak") or {}):
                    continue
                adat = {
                    "kelte": date.fromisoformat(a["kelte"]), "osszeg": a["osszeg"], "tipus": "egyeb", "sorszam": a["sorszam"],
                    "megjegyzes": "Számlaértesítő e-mailből",
                    **({"idoszak_tol": date.fromisoformat(a["idoszak_tol"]), "idoszak_ig": date.fromisoformat(a["idoszak_ig"])}
                       if a.get("idoszak_tol") and a.get("idoszak_ig") else {}),
                    **({"hatarido": date.fromisoformat(a["hatarido"])} if a.get("hatarido") else {}),
                }
                try:
                    kezi_szamla_rogzitese(tarolt, adat)
                except (HomeAssistantError, ValueError, KeyError) as err:
                    _LOGGER.warning("%s: az e-mailes számlaértesítő (%s) nem rögzíthető: %s", x["fiok_nev"], a["sorszam"], err)
                    er.latott.pop(x.get("kulcs"), None)  # a következő átnézéskor újra megpróbáljuk
                    continue
                kesz.append(x)
        if kesz:
            await self.koord.tarolo.ment()
            persistent_notification.async_create(
                self.hass,
                "\n".join(f"- {x['fiok_nev']}: {x['adat']['sorszam']} – {x['adat']['osszeg']} Ft"
                          + (f" (határidő {x['adat']['hatarido']})" if x["adat"].get("hatarido") else "") for x in kesz),
                title=f"Rezsikövető – {self.entry.title}: számla e-mailből", notification_id=f"{DOMAIN}_email_{self.entry.entry_id}",
            )
            await self.koord.async_request_refresh()
        return kesz

    # ------------------------------------------------------------------ panel

    def panel_adat(self) -> dict[str, Any] | None:
        """A panel „E-mail” blokkja: postafiókonként mi van bekötve, az utolsó átnézés, a talált számlák, a hiba, a
        felderítés eredménye; a háztartás nyitott kérdései, fiók-ajánlatai és üzenetei."""
        pfk = postafiokok(self.entry)
        if not pfk:
            return None
        sorok = []
        for sid, sub in pfk.items():
            a = self._allapotok().get(sid) or {}
            bekotott = self.bekotott(sid)
            sorok.append({
                "sid": sid, "nev": sub.title, "cim": sub.data.get(CONF_EMAIL_CIM), "levelezo": es.levelezo(sub.data.get(CONF_EMAIL_CIM) or "")["nev"],
                "utolso_atnezes": a.get("utolso_atnezes"), "utolso_sikeres": a.get("utolso_sikeres"),
                "hiba": a.get("hiba"), "hiba_tipus": a.get("hiba_tipus"), "utolso_talalt": a.get("utolso_talalt") or 0,
                "osszes_talalt": a.get("osszes_talalt") or 0, "nem_besorolhato": a.get("nem_besorolhato") or 0,
                "fiokok": len(bekotott), "bekotott": bekotott, "talalatok": a.get("utolso_talalatok") or [],
                "felderites": a.get("felderites"), "felderites_fut": sid in self.felderites_fut or bool(a.get("felderites_kell")),
                "felderites_kezdet": self.felderites_kezdet.get(sid),
                "felzarkozas": bool(a.get("felzarkozas_kell")),
            })
        h = self.koord.tarolo.adat.get("email_felderites") or {}
        fiokok = self.koord.fiokok()
        hatar = (dt_util.now() - timedelta(days=UZENET_NAP)).isoformat()
        kerdesek = []
        for k in h.get("kerdesek") or []:
            jel = [j for j in k.get("jeloltek") or [] if j["sid"] in fiokok]
            if k.get("pf") in pfk and jel:
                kerdesek.append({**k, "jeloltek": [{"sid": j["sid"], "nev": fiokok[j["sid"]].title} for j in jel]})
        return {
            "postafiokok": sorok, "fut": self._zar.locked() or bool(self.felderites_fut),
            "kerdesek": kerdesek, "ajanlatok": [x for x in h.get("ajanlatok") or [] if x.get("pf") in pfk],
            "uzenetek": [u for u in h.get("uzenetek") or [] if u.get("ido", "") >= hatar][:5],
        }


async def postafiok_letrehoz(hass: HomeAssistant, entry: ConfigEntry, bemenet: dict[str, Any]) -> dict[str, Any]:
    """Postafiók felvétele a panelről (a beállító felülettel azonos ellenőrzéssel): sikeres bejelentkezés után új
    „E-mail fiók” alárendelt bejegyzés, és a felderítés jelzője a tárban (az újratöltött otthon elvégzi).
    Visszaad: {sid} vagy {hiba, szoveg}."""
    adat, nev = postafiok_adat(bemenet)
    cim = adat[CONF_EMAIL_CIM].lower()
    if any((s.data.get(CONF_EMAIL_CIM) or "").lower() == cim for s in postafiokok(entry).values()):
        return {"hiba": "mar_van", "szoveg": hiba_szoveg("mar_van")}
    if hiba := await bejelentkezes_ellenorzes(hass, adat, nev):
        lv = es.levelezo(cim)
        return {"hiba": hiba, "szoveg": hiba_szoveg(hiba, adat[CONF_IMAP_SZERVER]), "levelezo": lv["kulcs"], "link": lv.get("link") or "",
                "halado": hiba in ("kapcsolat", "szerver_ismeretlen") or not lv["ismert"]}
    sub = ConfigSubentry(data=MappingProxyType(adat), subentry_type=POSTAFIOK, title=nev, unique_id=None)
    koord = entry.runtime_data
    koord.tarolo.adat.setdefault("postafiokok", {})[sub.subentry_id] = {"felderites_kell": True}
    await koord.tarolo.ment()
    hass.config_entries.async_add_subentry(entry, sub)
    return {"sid": sub.subentry_id, "nev": nev}


async def atnezes_most(hass: HomeAssistant, entry_id: str | None = None) -> dict[str, Any]:
    """Kézi átnézés (panel „Átnézés most”, hu_rezsi.email_atnezes): a megadott vagy minden betöltött otthon."""
    from homeassistant.config_entries import ConfigEntryState  # noqa: PLC0415

    entries = [e for e in hass.config_entries.async_entries(DOMAIN)
               if e.state is ConfigEntryState.LOADED and (entry_id is None or e.entry_id == entry_id)]
    if entry_id and not entries:
        raise ValueError("Nincs ilyen (betöltött) otthon.")
    ki: dict[str, Any] = {}
    for e in entries:
        figyelo = getattr(e.runtime_data, "email", None)
        if figyelo is not None and postafiokok(e):
            ki[e.entry_id] = {"nev": e.title, "postafiokok": await figyelo.atnez_mind()}
    return {"otthonok": ki}
