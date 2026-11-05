"""Befizetendő számlák: értesítés a mobilra a fizetési határidő előtt, és hangutasítás (2.4.0b1).

Értesítés (panel → Beállítások → Panel beállításai, alapból ki): naponta a beállított időpontban végignézi minden
otthon nyitott számláit; ha egy számla határideje N napon belül van (alap 3) és nincs befizetve, egy üzenetben
felsorolja a választott telefon(ok)ra. A lejárt, ki nem fizetett számláról a lejárat után egyszer szól. Minden
számláról legfeljebb egyszer (előtte) és egyszer (lejárt) – a küldöttek a HA tárhelyén (`hu_rezsi_ertesites`),
így újraindítás után sem ismétel; ha a küldés időpontjában a HA nem futott, indulás után pótolja.
Kimarad: a csoportos beszedéses / kompenzációs és az állandó átutalásos számla (nincs teendő), a 0 Ft-os, a
stornózott, és a 90 napnál régebbi határidejű (ezekről gyakran nincs fizetési adat).

Mely otthonokra: a beállításban választható (értesítés és hangutasítás együtt; üres: mindegyik, az újak is).

Hangutasítás: a „HuRezsiBefizetendo” szándék (intent) ugyanezt a listát mondja el, hány nap múlva esedékes / hány
napja lejárt. Az Assist-ügynök (pl. Gemini) eszközként kapja (llm.py), a helyi Assist a custom_sentences mondataival.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import intent
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import panel_beallitas as pb
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

KULCS = f"{DOMAIN}_ertesites"
INTENT = "HuRezsiBefizetendo"
PANEL_UT = "/rezsi"
REGI_NAP = 90  # ennél régebbi határidejű számlát nem jelez (mint a fizetési összesítő)
LEJART_NAP = 7  # a lejárt számláról legfeljebb ennyi napig pótolja az egyszeri jelzést
MEGORZES_NAP = 200  # a küldött-jelölések ennyi napig maradnak
INDULAS_MP = 300  # pótlás: a HA indulása után ennyivel (addig a számolás lefut)
BESZEDES = ("beszed", "csoportos", "kompenz")
HONAP = ("jan.", "febr.", "márc.", "ápr.", "máj.", "jún.", "júl.", "aug.", "szept.", "okt.", "nov.", "dec.")


# ---------------------------------------------------------------------------------------- tiszta számolás


def tetelek(fiokok: Iterable[tuple[str, str, str, dict[str, dict], dict[str, dict]]], ma: date) -> list[dict[str, Any]]:
    """A befizetendő számlák: (otthon, sid, fiók neve, számlák, fizetési állapotok) fiókonként → határidő szerint
    rendezve {otthon, fiok, sid, sorszam, osszeg, hatarido, nap (határidőig, negatív: lejárt), lejart}."""
    ki: list[dict[str, Any]] = []
    for otthon, sid, fnev, szamlak, allapotok in fiokok:
        for sorszam, a in allapotok.items():
            if a.get("fizetve") or a.get("nincs_fizetendo") or not a.get("osszeg") or a["osszeg"] <= 0:
                continue
            if a.get("utemezett") or not a.get("hatarido"):
                continue  # állandó átutalás: a bank fizeti; határidő nélkül nincs mihez igazodni
            sz = szamlak.get(sorszam) or {}
            if (sz.get("fizetesi_mod") or "").lower().startswith(BESZEDES):
                continue
            try:
                hat = date.fromisoformat(str(a["hatarido"])[:10])
            except ValueError:
                continue
            nap = (hat - ma).days
            if nap < -REGI_NAP:
                continue
            ki.append({"otthon": otthon, "fiok": fnev, "sid": sid, "sorszam": sorszam, "osszeg": int(a["osszeg"]),
                       "hatarido": hat.isoformat(), "nap": nap, "lejart": nap < 0})
    return sorted(ki, key=lambda t: (t["hatarido"], t["otthon"], t["fiok"]))


def kuldendok(tet: list[dict[str, Any]], napok: int, kuldott: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """(határidő előtti, lejárt) tételek, amelyekről még nem ment értesítés."""
    elotte = [t for t in tet if 0 <= t["nap"] <= napok and kulcs(t, "elotte") not in kuldott]
    lejart = [t for t in tet if -LEJART_NAP <= t["nap"] <= -1 and kulcs(t, "lejart") not in kuldott]
    return elotte, lejart


def kulcs(t: dict[str, Any], fajta: str) -> str:
    return f"{t['sid']}|{t['sorszam']}|{fajta}"


def ft(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " Ft"


def nap_szoveg(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{HONAP[x.month - 1]} {x.day}."


def mikor(nap: int) -> str:
    if nap == 0:
        return "ma"
    if nap == 1:
        return "holnap"
    if nap > 1:
        return f"{nap} nap múlva"
    return "tegnap lejárt" if nap == -1 else f"{-nap} napja lejárt"


def _nev(t: dict[str, Any], tobb_otthon: bool) -> str:
    return f"{t['otthon']} · {t['fiok']}" if tobb_otthon or t.get("tobb_otthon") else t["fiok"]


def uzenet(elotte: list[dict], lejart: list[dict]) -> tuple[str, str] | None:
    """(cím, szöveg) a mobil-értesítéshez; None, ha nincs mit küldeni."""
    if not elotte and not lejart:
        return None
    tobb = len({t["otthon"] for t in elotte + lejart}) > 1
    sorok = [f"{_nev(t, tobb)}: {ft(t['osszeg'])}, határidő {nap_szoveg(t['hatarido'])} ({mikor(t['nap'])})" for t in elotte]
    sorok += [f"{_nev(t, tobb)}: {ft(t['osszeg'])} – {mikor(t['nap'])} ({nap_szoveg(t['hatarido'])}), még nincs befizetve"
              for t in lejart]
    if lejart and not elotte:
        cim = "Lejárt számla" if len(lejart) == 1 else f"{len(lejart)} lejárt számla"
    else:
        db = len(elotte) + len(lejart)
        cim = "Befizetendő számla" if db == 1 else f"{db} befizetendő számla"
    return f"Rezsikövető – {cim}", "\n".join(sorok)


def hang_valasz(tet: list[dict[str, Any]]) -> str:
    """A hangutasítás válasza: minden befizetendő számla, összeggel és hogy mikor esedékes."""
    if not tet:
        return "Nincs befizetendő számlád."
    tobb = len({t["otthon"] for t in tet}) > 1
    osszes = sum(t["osszeg"] for t in tet)
    eleje = "Egy befizetendő számlád van" if len(tet) == 1 else f"{len(tet)} befizetendő számlád van, összesen {_ft_hang(osszes)}"
    reszek = []
    for t in tet:
        m = mikor(t["nap"])
        reszek.append(f"{_nev(t, tobb)} {_ft_hang(t['osszeg'])}, {m if t['lejart'] else m + ' esedékes'}")
    vege = "" if any(t["lejart"] for t in tet) else " Lejárt számla nincs."
    return f"{eleje}: " + "; ".join(reszek) + "." + vege


def _ft_hang(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " forint"


# ---------------------------------------------------------------------------------------- Home Assistant


def _gyujt(hass: HomeAssistant, ma: date) -> list[dict[str, Any]]:
    fiokok = []
    entries = hass.config_entries.async_entries(DOMAIN)
    if valasztott := set(pb.aktualis(hass).get(pb.ERT_OTTHONOK) or []):  # üres: minden otthon
        entries = [e for e in entries if e.entry_id in valasztott]
    for entry in entries:
        koord = getattr(entry, "runtime_data", None)
        if koord is None or not hasattr(koord, "fiokok"):
            continue
        for sid, sub in koord.fiokok().items():
            try:
                fiokok.append((entry.title, sid, sub.title, koord.javitott_szamlak(sid), koord.fizetes_allapotok(sid)))
            except Exception:  # noqa: BLE001 – egy fiók hibája ne állítsa meg a többit
                _LOGGER.exception("%s: a befizetendő számlák nem olvashatók", sub.title)
    tet = tetelek(fiokok, ma)
    if len(entries) > 1:  # több otthon: az üzenetben mindig az otthon neve is (akkor is, ha most csak egyé jelez)
        for t in tet:
            t["tobb_otthon"] = True
    return tet


def befizetendok(hass: HomeAssistant) -> list[dict[str, Any]]:
    return _gyujt(hass, dt_util.now().date())


class Ertesito:
    """A napi ellenőrzés ütemezése, a küldött-jelölések tárolása."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store[dict[str, Any]] = Store(hass, 1, KULCS)
        self.adat: dict[str, Any] = {"kuldott": {}, "utolso": None}
        self._le: CALLBACK_TYPE | None = None

    async def betolt(self) -> None:
        self.adat = {"kuldott": {}, "utolso": None} | (await self.store.async_load() or {})

    @callback
    def utemez(self) -> None:
        if self._le:
            self._le()
            self._le = None
        b = pb.aktualis(self.hass)
        if not b.get(pb.ERT_BE):
            return
        o, p = (int(x) for x in b.get(pb.ERT_IDO, pb.ERT_IDO_ALAP).split(":"))
        self._le = async_track_time_change(self.hass, self._idoben, hour=o, minute=p, second=0)

    async def _idoben(self, _most: datetime) -> None:
        await self.fut()

    @callback
    def potlas(self) -> None:
        """Indulás után: ha ma a küldés időpontja már elmúlt, de ma még nem futott, pótolja."""
        b = pb.aktualis(self.hass)
        if not b.get(pb.ERT_BE):
            return
        most = dt_util.now()
        o, p = (int(x) for x in b.get(pb.ERT_IDO, pb.ERT_IDO_ALAP).split(":"))
        if (most.hour, most.minute) >= (o, p) and self.adat.get("utolso") != most.date().isoformat():
            async_call_later(self.hass, INDULAS_MP, self._kesleltetve)

    async def _kesleltetve(self, _most: datetime) -> None:
        await self.fut()

    async def fut(self) -> int:
        """A napi ellenőrzés; visszaadja, hány számláról ment értesítés."""
        b = pb.aktualis(self.hass)
        if not b.get(pb.ERT_BE) or not b.get(pb.ERT_CELOK):
            return 0
        ma = dt_util.now().date()
        tet = _gyujt(self.hass, ma)
        kuldott: dict[str, str] = self.adat.setdefault("kuldott", {})
        elotte, lejart = kuldendok(tet, int(b.get(pb.ERT_NAPOK, pb.ERT_NAPOK_ALAP)), kuldott)
        db = 0
        if (u := uzenet(elotte, lejart)) and await self._kuld(b[pb.ERT_CELOK], *u):
            for t in elotte:
                kuldott[kulcs(t, "elotte")] = ma.isoformat()
            for t in lejart:
                kuldott[kulcs(t, "lejart")] = ma.isoformat()
            db = len(elotte) + len(lejart)
            _LOGGER.info("Határidő-értesítés elküldve: %s számla", db)
        hatar = (ma - timedelta(days=MEGORZES_NAP)).isoformat()
        self.adat["kuldott"] = {k: v for k, v in kuldott.items() if v >= hatar}
        self.adat["utolso"] = ma.isoformat()
        await self.store.async_save(self.adat)
        return db

    async def proba(self, celok: list[str]) -> str:
        """Próbaüzenet a választott telefon(ok)ra: a mostani befizetendő számlák, a küldött-jelölések érintése nélkül."""
        tet = _gyujt(self.hass, dt_util.now().date())
        napok = int(pb.aktualis(self.hass).get(pb.ERT_NAPOK, pb.ERT_NAPOK_ALAP))
        u = uzenet(*kuldendok(tet, napok, {}))  # amit ma küldene (a már küldöttekkel együtt)
        cim, szoveg = u or ("Rezsikövető – próbaüzenet",
                            f"Az értesítés működik. Most nincs {napok} napon belül esedékes vagy friss lejárt számla.")
        if u:
            cim += " (próba)"
        if not await self._kuld(celok, cim, szoveg):
            raise ValueError("Az üzenetet egyik telefonra sem sikerült elküldeni (lásd a HA naplóját).")
        return szoveg

    async def _kuld(self, celok: list[str], cim: str, szoveg: str) -> bool:
        ok = False
        for cel in celok:
            szolg = cel.split(".", 1)[1] if "." in cel else cel
            if not self.hass.services.has_service("notify", szolg):
                _LOGGER.warning("Határidő-értesítés: nincs ilyen értesítő szolgáltatás: notify.%s", szolg)
                continue
            try:
                await self.hass.services.async_call("notify", szolg, {
                    "title": cim, "message": szoveg,
                    "data": {"url": PANEL_UT, "clickAction": PANEL_UT, "group": "hu_rezsi", "tag": "hu_rezsi_hatarido"},
                }, blocking=True)
                ok = True
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Határidő-értesítés: notify.%s nem sikerült: %s", szolg, err)
        return ok


class BefizetendoIntent(intent.IntentHandler):
    """„Van befizetendő számlám?” – a nyitott számlák összeggel és határidővel."""

    intent_type = INTENT
    description = ("Lists the household's unpaid utility bills (Rezsikövető: electricity, gas, water, district heating, "
                   "waste, internet…) with the amount and how many days until the payment deadline, or how many days "
                   "overdue. Use it when the user asks (e.g. in Hungarian) whether there is a bill to pay: "
                   "'van befizetendő számlám?', 'milyen számlát kell befizetni?', 'mikor esedékes a villanyszámla?'. "
                   "The answer is in Hungarian.")

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        valasz = intent_obj.create_response()
        valasz.async_set_speech(hang_valasz(befizetendok(intent_obj.hass)))
        return valasz


async def indit(hass: HomeAssistant) -> Ertesito:
    """Egyszer, az integráció betöltésekor: tároló, ütemezés, pótlás az indulás után, a hang-szándék."""
    e = Ertesito(hass)
    await e.betolt()
    hass.data.setdefault(DOMAIN, {})["ertesito"] = e
    e.utemez()

    @callback
    def _indult(_hass: HomeAssistant) -> None:
        e.potlas()

    async_at_started(hass, _indult)
    intent.async_register(hass, BefizetendoIntent())
    return e


def ertesito(hass: HomeAssistant) -> Ertesito | None:
    return hass.data.get(DOMAIN, {}).get("ertesito")
