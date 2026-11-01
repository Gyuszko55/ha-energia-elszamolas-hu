"""D (dinamikus) árszabás: az MVM által közzétett negyedórás rugalmas egységárak letöltése és tárolása.

Az MVM a D árszabás oldalán havonta frissíti az utolsó teljes 12 hónap negyedórás rugalmas egységárait (PDF,
Ft/kWh nettó, a HUPX-ár MNB-árfolyamon + a kereskedői díj). Ezt naponta legfeljebb egyszer ellenőrizzük; új fájlnál
letöltjük, negyedórás és órás árként a korábbi hónapok mellé tároljuk – így a 12 hónapnál régebbi árak sem vesznek el.

A még közzé nem tett napokra (a folyó és az előző hónap) az árat az MVM képletével magunk számoljuk: a HUPX negyedórás
másnapi ára (energy-charts.info, a HUPX/ENTSO-E adataiból) × az MNB napi EUR-középárfolyama + kereskedői díj. Ez az
MVM közzétett árlistájával fillérre egyezik; az MVM-lista megjelenésekor az felülírja.
"""

from __future__ import annotations

import html
import io
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .motor.rugalmas import hupx_negyed_arak, mnb_arfolyamok, negyed_ora_atlag, sorok_negyed_arak

_LOGGER = logging.getLogger(__name__)

OLDAL = "https://www.mvmnext.hu/aram/pages/aloldal.jsp?id=16455187"
LETOLTES = "https://www.mvmnext.hu/aram/servlet/download?type=file&id={}"
_LINK = re.compile(r'href="/aram/servlet/download\?type=file&id=(\d+)"[^>]*>\s*D árszabás – negyedórás rugalmas egységárak')
ELLENORZES = timedelta(hours=20)
HUPX_URL = "https://api.energy-charts.info/price?bzn=HU&start={}&end={}"
# Az MNB ezt a SOAP-végpontot csak HTTP-n szolgálja ki (HTTPS-en 404) – ezért a válaszát szigorúan ellenőrizzük
# (motor/rugalmas.mnb_arfolyamok), hibás válasznál a korábbi árfolyamok maradnak.
MNB_URL = "http://www.mnb.hu/arfolyamok.asmx"
MNB_SOAP = (
    '<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    '<soap:Body><GetExchangeRates xmlns="http://www.mnb.hu/webservices/"><startDate>{}</startDate><endDate>{}</endDate>'
    "<currencyNames>EUR</currencyNames></GetExchangeRates></soap:Body></soap:Envelope>"
)
HUPX_ELLENORZES = timedelta(hours=3)
KERESKEDOI_DIJ = 13.70  # Ft/kWh nettó (MVM hirdetmény, 2026.09.10-től; az augusztusi árlista is ezzel egyezik)
MEGORZES_NAP = 460  # a negyedórás árak ennyi napig maradnak meg (13 hónap + ráhagyás)


def pdf_negyed_arak(tartalom: bytes) -> dict[str, float]:
    """A PDF negyedórás sorai → negyedórás ár (kulcs: helyi idő „ÉÉÉÉ-HH-NNTÓÓ:PP”, Ft/kWh nettó)."""
    from pypdf import PdfReader  # noqa: PLC0415 – csak itt kell

    return sorok_negyed_arak(
        sor for oldal in PdfReader(io.BytesIO(tartalom)).pages for sor in (oldal.extract_text() or "").splitlines()
    )


class DArak:
    """A tárolt órás D-árak (minden bejegyzés közös példánya: hass.data[DOMAIN]["d_arak"])."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, 1, "hu_rezsi_d_arak")
        self.adat: dict[str, Any] = {"orak": {}}

    async def betolt(self) -> None:
        self.adat = await self._store.async_load() or {"orak": {}}

    @property
    def orak(self) -> dict[str, float]:
        return self.adat.get("orak", {})

    @property
    def valtozat(self) -> str:
        """Változik, ha új MVM-árlista vagy újabb számított (HUPX) nap érkezett – a számolások gyorsítótárához."""
        return f"{self.adat.get('fajl')}/{self.szamitott_ig}"

    @property
    def szamitott_ig(self) -> str | None:
        """Az utolsó negyedóra, amelynek ára a HUPX-ból számolt (az MVM még nem tette közzé)."""
        sz = self.adat.get("szamitott") or {}
        return max(sz) if sz else None

    def ar(self, ido: datetime) -> Decimal | None:
        """Az óra (helyi idő, az óra kezdete) rugalmas egységára, ha ismert (MVM-lista, ennek híján HUPX-ból számolt)."""
        k = ido.strftime("%Y-%m-%dT%H")
        v = self.orak.get(k)
        if v is None:
            v = (self.adat.get("szamitott_orak") or {}).get(k)
        return None if v is None else Decimal(str(v))

    def negyed_ar(self, kulcs: str) -> tuple[float | None, str | None]:
        """A negyedóra („ÉÉÉÉ-HH-NNTÓÓ:PP”) ára és forrása: „mvm” (közzétett), „hupx” (számolt), „ora” (csak órás ár)."""
        v = (self.adat.get("negyedek") or {}).get(kulcs)
        if v is not None:
            return v, "mvm"
        v = (self.adat.get("szamitott") or {}).get(kulcs)
        if v is not None:
            return v, "hupx"
        v = self.orak.get(kulcs[:13])
        return (v, "ora") if v is not None else (None, None)

    async def hupx_frissit(self, kenyszer: bool = False) -> bool:
        """A közzétett MVM-árlista utáni napok (holnapig) árának számolása HUPX-ból és MNB-árfolyamból."""
        most = dt_util.now()
        utolso = self.adat.get("hupx_ellenorizve")
        if not kenyszer and utolso and dt_util.utcnow() - datetime.fromisoformat(utolso) < HUPX_ELLENORZES:
            return False
        mvm_ig = (self.adat.get("utolso_ora") or "")[:10]
        tol = date.fromisoformat(mvm_ig) + timedelta(days=1) if mvm_ig else most.date() - timedelta(days=35)
        tol = max(tol, most.date() - timedelta(days=70))
        ig = most.date() + timedelta(days=2)  # kizárólagos: holnap végéig
        if tol >= ig:
            return False
        tz = dt_util.get_default_time_zone()
        sess = async_get_clientsession(self.hass)
        try:
            kezd = datetime.combine(tol, datetime.min.time(), tz).isoformat()
            veg = datetime.combine(ig, datetime.min.time(), tz).isoformat()
            async with sess.get(HUPX_URL.format(kezd.replace("+", "%2B"), veg.replace("+", "%2B")), timeout=60) as v:
                hupx = await v.json(content_type=None)
            async with sess.post(
                MNB_URL, data=MNB_SOAP.format((tol - timedelta(days=10)).isoformat(), most.date().isoformat()),
                headers={"Content-Type": "text/xml; charset=utf-8",
                         "SOAPAction": '"http://www.mnb.hu/webservices/MNBArfolyamServiceSoap/GetExchangeRates"'},
                timeout=60,
            ) as v:
                mnb_status, mnb = v.status, await v.text()
        except Exception as err:  # noqa: BLE001 – hálózati hiba: legközelebb újra
            _LOGGER.warning("D árszabás: a HUPX-ár vagy az MNB-árfolyam lekérése nem sikerült: %s", err)
            return False
        try:
            if mnb_status != 200:
                raise ValueError(f"HTTP {mnb_status}")
            uj_arfolyamok = mnb_arfolyamok(mnb)
        except ValueError as err:
            _LOGGER.warning("D árszabás: az MNB-árfolyam válasza hibás, a korábbi árfolyamok maradnak: %s", err)
            uj_arfolyamok = {}
        arfolyamok = {**(self.adat.get("arfolyamok") or {}), **uj_arfolyamok}
        idok = [dt_util.as_local(dt_util.utc_from_timestamp(t)).strftime("%Y-%m-%dT%H:%M") for t in hupx.get("unix_seconds") or []]
        uj = hupx_negyed_arak(idok, list(hupx.get("price") or []), arfolyamok, KERESKEDOI_DIJ)
        self.adat["hupx_ellenorizve"] = dt_util.utcnow().isoformat()
        hatar = (most.date() - timedelta(days=40)).isoformat()
        self.adat["arfolyamok"] = {k: v for k, v in arfolyamok.items() if k >= hatar}
        regi = self.szamitott_ig
        sz = {k: v for k, v in (self.adat.get("szamitott") or {}).items() if k[:10] > mvm_ig}
        sz.update({k: v for k, v in uj.items() if k[:10] > mvm_ig})
        self.adat["szamitott"] = sz
        self.adat["szamitott_orak"] = negyed_ora_atlag(sz)
        await self._store.async_save(self.adat)
        if self.szamitott_ig != regi:
            _LOGGER.info("D árszabás: HUPX-ból számolt árak %s-ig", self.szamitott_ig)
            return True
        return False

    async def frissit(self, kenyszer: bool = False) -> bool:
        """Új árlista letöltése, ha az MVM oldalán más fájl van, mint amit legutóbb feldolgoztunk. Igaz, ha változott."""
        most = dt_util.utcnow()
        utolso = self.adat.get("ellenorizve")
        # A negyedórás árak még hiányoznak (régebbi változat tárolója): a napi korlát nélkül, egyszer újra letöltjük.
        if not kenyszer and utolso and most - datetime.fromisoformat(utolso) < ELLENORZES and self.adat.get("negyedek"):
            return False
        sess = async_get_clientsession(self.hass)
        try:
            async with sess.get(OLDAL, timeout=30) as v:
                oldal = html.unescape(await v.text())
            m = _LINK.search(oldal)
            if not m:
                _LOGGER.warning("D árszabás: az árlista hivatkozása nem található az MVM oldalán")
                return False
            fajl = m.group(1)
            self.adat["ellenorizve"] = most.isoformat()
            if fajl == self.adat.get("fajl") and not kenyszer and self.adat.get("negyedek"):
                await self._store.async_save(self.adat)
                return False
            async with sess.get(LETOLTES.format(fajl), timeout=120) as v:
                tartalom = await v.read()
        except Exception as err:  # noqa: BLE001 – hálózati hiba: legközelebb újra
            _LOGGER.warning("D árszabás: az árlista letöltése nem sikerült: %s", err)
            return False
        negyedek = await self.hass.async_add_executor_job(pdf_negyed_arak, tartalom)
        uj = negyed_ora_atlag(negyedek)
        if len(uj) < 24 * 28:
            _LOGGER.warning("D árszabás: az árlista feldolgozása hiányos (%s óra)", len(uj))
            return False
        self.adat["orak"] = {**self.orak, **uj}
        hatar = (dt_util.now().date() - timedelta(days=MEGORZES_NAP)).isoformat()
        self.adat["negyedek"] = {k: v for k, v in {**(self.adat.get("negyedek") or {}), **negyedek}.items() if k >= hatar}
        self.adat["fajl"] = fajl
        self.adat["utolso_ora"] = max(uj)
        # A most közzétett napok számolt ára felesleges (a közzétett felülírja).
        mvm_ig = self.adat["utolso_ora"][:10]
        self.adat["szamitott"] = {k: v for k, v in (self.adat.get("szamitott") or {}).items() if k[:10] > mvm_ig}
        self.adat["szamitott_orak"] = negyed_ora_atlag(self.adat["szamitott"])
        await self._store.async_save(self.adat)
        _LOGGER.info("D árszabás: %s órás ár tárolva (legutóbbi: %s)", len(self.orak), self.adat["utolso_ora"])
        return True
