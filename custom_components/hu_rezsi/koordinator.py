"""Időszakos újraszámolás: fiókonként a nyitott időszak, az előrejelzés és a lezárások."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_FORRAS,
    CONF_FORRAS_TIPUS,
    CONF_IDOSZAK_MOD,
    CONF_IDOSZAK_NAP,
    CONF_KOZMU,
    CONF_SZORZO,
    DOMAIN,
    EGYSEG,
    FIOK,
    FRISSITES_PERC,
    LEZARAS_KESLELTETES_ORA,
)
from .modell import d, eredmeny_tarolhato, elszamolasi_napok, fiok_motorba, kezdo_mero
from .motor.dijszabas import DijszabasHiba, DijszabasTar
from .motor.elorejelzes import NyitottIdoszak, idoszak, nyitott
from .motor.elszamolas import szamol
from .motor.szamlalo import NincsAdat, Szamlalo
from .motor.tipusok import Fiok
from .tarolo import Tarolo

_LOGGER = logging.getLogger(__name__)
ELOZMENY_NAPOK = 8  # a 7 napos átlaghoz


def helyi_most() -> datetime:
    return dt_util.now().replace(tzinfo=None, microsecond=0)


@dataclass
class FiokAllapot:
    egyseg: str
    tol: date | None = None
    ig: date | None = None
    nyitott: NyitottIdoszak | None = None
    eves_bazis: date | None = None
    eves_fogyasztas: Decimal | None = None
    aktualis_ar: Decimal | None = None
    utolso_lezart: dict[str, Any] | None = None
    hiba: str | None = None


class RezsiKoordinator(DataUpdateCoordinator[dict[str, FiokAllapot]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, tar: DijszabasTar, tarolo: Tarolo) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=FRISSITES_PERC),
        )
        self.tar = tar
        self.tarolo = tarolo
        self.utolso_szamlalok: dict[str, list] = {}  # diagnosztikához: a számláló utolsó pontjai

    def fiokok(self) -> dict[str, ConfigSubentry]:
        return {sid: s for sid, s in self.config_entry.subentries.items() if s.subentry_type == FIOK}

    def motor_fiok(self, subentry_id: str) -> Fiok:
        sub = self.fiokok()[subentry_id]
        return fiok_motorba(dict(sub.data), self.tarolo.fiok(subentry_id))

    async def szamlalo(self, subentry_id: str, fiok: Fiok, tol: datetime, most: datetime) -> Szamlalo:
        """A fiók számlálója: leolvasások + a forrás-entitás napi statisztikája + élő állapota."""
        beall = self.fiokok()[subentry_id].data
        csatorna = fiok.csatornak[0]
        forras = beall.get(CONF_FORRAS)
        if not forras:
            return Szamlalo.csatornabol(csatorna)
        # A sorozatpontokat a megelőző horgonyhoz igazítjuk, ezért a sorozatnak a szükséges
        # legkorábbi pont előtti utolsó horgonytól kell indulnia.
        horgonyok = [m.beepitve for m in csatorna.merok] + [lo.datum for m in csatorna.merok for lo in m.leolvasasok]
        kell = min(tol.date(), fiok.eves_bazis or tol.date())
        korabbiak = [h for h in horgonyok if h and h <= kell]
        kezdet = max(korabbiak) if korabbiak else kell
        sorozat = await self._sorozat(forras, datetime.combine(kezdet, datetime.min.time()) - timedelta(days=1), most)
        szorzo = Decimal(str(beall.get(CONF_SZORZO) or 1))
        meroallas = beall.get(CONF_FORRAS_TIPUS, "meroallas") == "meroallas"
        return Szamlalo.csatornabol(csatorna, sorozat, szorzo, meroallas=meroallas)

    async def _sorozat(self, entity_id: str, tol: datetime, most: datetime) -> list[tuple[datetime, Decimal]]:
        tz = dt_util.get_default_time_zone()
        kezd = tol.replace(tzinfo=tz)
        stat = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period, self.hass, kezd, None, {entity_id}, "day", None, {"state"}
        )
        sor: list[tuple[datetime, Decimal]] = []
        for r in stat.get(entity_id, []):
            if r.get("state") is None:
                continue
            # A napi sor „state” értéke a nap végén mért állás.
            vege = dt_util.utc_from_timestamp(r["end"]) if isinstance(r["end"], (int, float)) else r["end"]
            sor.append((dt_util.as_local(vege).replace(tzinfo=None), Decimal(str(r["state"]))))
        allapot = self.hass.states.get(entity_id)
        try:
            sor.append((most, Decimal(allapot.state)))
        except (AttributeError, InvalidOperation):
            # Induláskor a forrás még nem kész: hamarosan újraszámolunk.
            self._forras_hianyzik = True
        return sor

    async def _async_update_data(self) -> dict[str, FiokAllapot]:
        most = helyi_most()
        self._forras_hianyzik = False
        kimenet: dict[str, FiokAllapot] = {}
        valtozott = False
        for sid, sub in self.fiokok().items():
            tarolt = self.tarolo.fiok(sid)
            if not tarolt["merok"]:
                tarolt["merok"].append(kezdo_mero(dict(sub.data)))
                valtozott = True
            egyseg = EGYSEG[sub.data[CONF_KOZMU]]
            try:
                allapot, lezart = await self._fiok(sid, sub, tarolt, most, egyseg)
                valtozott |= lezart
            except (NincsAdat, DijszabasHiba, KeyError, ValueError) as err:
                _LOGGER.warning("%s: nem számolható: %s", sub.title, err)
                allapot = FiokAllapot(egyseg=egyseg, hiba=str(err))
            kimenet[sid] = allapot
        for sid in set(self.tarolo.adat["fiokok"]) - set(self.fiokok()):
            self.tarolo.torol_fiok(sid)  # törölt fiók adatai
            valtozott = True
        if valtozott:
            await self.tarolo.ment()
        self.update_interval = timedelta(minutes=1 if self._forras_hianyzik else FRISSITES_PERC)
        return kimenet

    async def _fiok(
        self, sid: str, sub: ConfigSubentry, tarolt: dict[str, Any], most: datetime, egyseg: str
    ) -> tuple[FiokAllapot, bool]:
        fiok = fiok_motorba(dict(sub.data), tarolt)
        mod = sub.data.get(CONF_IDOSZAK_MOD, "naptari_honap")
        nap = int(sub.data.get(CONF_IDOSZAK_NAP) or 1)
        tol, ig = idoszak(most.date(), mod, nap)
        szamlalo = await self.szamlalo(sid, fiok, datetime.combine(tol, datetime.min.time()) - timedelta(days=ELOZMENY_NAPOK), most)
        self.utolso_szamlalok[sid] = szamlalo.pontok[-15:]
        hatarok = elszamolasi_napok(tarolt)

        # Lezárás: ha a tárolt nyitott időszak már véget ért (és eltelt a késleltetés).
        lezart_valt = False
        nyitott_tol = d(tarolt.get("nyitott_tol"))
        if nyitott_tol is None:
            tarolt["nyitott_tol"] = tol.isoformat()
            lezart_valt = True
        elif nyitott_tol < tol and most >= datetime.combine(tol, datetime.min.time()) + timedelta(hours=LEZARAS_KESLELTETES_ORA):
            ptol = nyitott_tol
            while ptol < tol:
                _, pig = idoszak(ptol, mod, nap)
                try:
                    e = szamol(fiok, self.tar, ptol, pig, [szamlalo], extra_hatarok=hatarok)
                    bejegyzes = eredmeny_tarolhato(e) | {"rogzitve": most.isoformat(), "forras": "automatikus"}
                    tarolt["lezart"] = [x for x in tarolt["lezart"] if x["tol"] != bejegyzes["tol"]] + [bejegyzes]
                except NincsAdat as err:
                    _LOGGER.warning("%s: a %s időszak nem zárható le: %s", sub.title, ptol, err)
                ptol = pig
            tarolt["nyitott_tol"] = tol.isoformat()
            lezart_valt = True

        ny = nyitott(fiok, self.tar, tol, ig, [szamlalo], most, extra_hatarok=hatarok)
        eves = None
        if fiok.eves_bazis:
            try:
                eves, _ = szamlalo.fogyasztas(datetime.combine(fiok.eves_bazis, datetime.min.time()), most)
            except NincsAdat:
                eves = None
        lezartak = sorted(tarolt["lezart"], key=lambda x: x["tol"])
        return (
            FiokAllapot(
                egyseg=egyseg,
                tol=tol,
                ig=ig,
                nyitott=ny,
                eves_bazis=fiok.eves_bazis,
                eves_fogyasztas=eves,
                aktualis_ar=_aktualis_ar(ny, most),
                utolso_lezart=lezartak[-1] if lezartak else None,
            ),
            lezart_valt,
        )


def _aktualis_ar(ny: NyitottIdoszak, most: datetime) -> Decimal | None:
    """A következő elfogyasztott egység ára (a HA Energia irányítópult ár-entitásához)."""
    for s in ny.eddig.szeletek:
        if datetime.combine(s.tol, datetime.min.time()) <= most < datetime.combine(s.ig, datetime.min.time()):
            if s.keret is None or s.mennyiseg < s.keret:
                return s.egysegar_kedvezmenyes
            return s.egysegar_piaci
    return None
