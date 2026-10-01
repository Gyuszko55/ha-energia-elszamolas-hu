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
    CONF_ALMERO,
    CONF_ALMERO_FORRAS,
    CONF_BETAPLALAS,
    CONF_DIJNET,
    CONF_NAPELEM,
    CONF_FIZETESI_MOD,
    CONF_ELOZO_EV,
    CONF_RESZSZAMLA_DB,
    CONF_RESZSZAMLA_OSSZEG,
    DIJNET_MINTA,
    CONF_FORRAS,
    CONF_FORRAS_TIPUS,
    CONF_FORRAS_TOL,
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
from pathlib import Path

from . import dijnet
from .modell import betaplalas_csatorna, d, kezdo_almero, elozo_bazis, eredmeny_tarolhato, elszamolasi_napok, fiok_motorba, kezdo_mero
from .motor import napelem
from .motor.egyenleg import EvesEgyenleg, egy_ev_mulva, eves_egyenleg
from .motor.elszamolas import _hozzarendeles, futoertek
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
    egyenleg: EvesEgyenleg | None = None
    napelem: napelem.NapelemEredmeny | None = None
    napelem_hiba: str | None = None
    egyenleg_hiba: str | None = None
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
        tol_nap = d(beall.get(CONF_FORRAS_TOL))
        return Szamlalo.csatornabol(
            csatorna, sorozat, szorzo, meroallas=meroallas,
            sorozat_tol=datetime.combine(tol_nap, datetime.min.time()) if tol_nap else None,
        )

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
        self._ujraszamol_kert = False
        kimenet: dict[str, FiokAllapot] = {}
        valtozott = False
        for sid, sub in self.fiokok().items():
            tarolt = self.tarolo.fiok(sid)
            if not tarolt["merok"]:
                tarolt["merok"].append(kezdo_mero(dict(sub.data)))
                valtozott = True
            if sub.data.get(CONF_ALMERO) and not tarolt.get("almero_merok"):
                tarolt["almero_merok"] = [kezdo_almero(dict(sub.data))]
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
        tovabbi: list[Szamlalo] = []
        for csat in fiok.csatornak[1:]:  # víz-almérő
            sorozat = None
            if csat.szerep == "almero" and sub.data.get(CONF_ALMERO_FORRAS):
                sorozat = await self._sorozat(sub.data[CONF_ALMERO_FORRAS], datetime.combine(tol, datetime.min.time()) - timedelta(days=ELOZMENY_NAPOK), most)
            tovabbi.append(Szamlalo.csatornabol(csat, sorozat, meroallas=True))
        szamlalok = [szamlalo, *tovabbi]

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
                    e = szamol(fiok, self.tar, ptol, pig, szamlalok, extra_hatarok=hatarok)
                    bejegyzes = eredmeny_tarolhato(e) | {"rogzitve": most.isoformat(), "forras": "automatikus"}
                    tarolt["lezart"] = [x for x in tarolt["lezart"] if x["tol"] != bejegyzes["tol"]] + [bejegyzes]
                except NincsAdat as err:
                    _LOGGER.warning("%s: a %s időszak nem zárható le: %s", sub.title, ptol, err)
                ptol = pig
            tarolt["nyitott_tol"] = tol.isoformat()
            lezart_valt = True

        ny = nyitott(fiok, self.tar, tol, ig, szamlalok, most, extra_hatarok=hatarok)
        eves = None
        if fiok.eves_bazis:
            try:
                eves, _ = szamlalo.fogyasztas(datetime.combine(fiok.eves_bazis, datetime.min.time()), most)
            except NincsAdat:
                eves = None
        lezartak = sorted(tarolt["lezart"], key=lambda x: x["tol"])
        napelem_e, napelem_hiba = None, None
        mod = sub.data.get(CONF_NAPELEM, "nincs")
        if mod in ("brutto", "szaldo"):
            try:
                napelem_e = await self._napelem(sub, tarolt, fiok, szamlalo, tol, ig, most, mod)
            except (NincsAdat, ValueError, DijszabasHiba, KeyError) as err:
                napelem_hiba = str(err)
        egyenleg, egyenleg_hiba = None, None
        if sub.data.get(CONF_FIZETESI_MOD) == "reszszamla":
            try:
                egyenleg = await self._egyenleg(sub, tarolt, fiok, szamlalo, most, tovabbi)
            except (NincsAdat, ValueError, DijszabasHiba) as err:
                egyenleg_hiba = str(err)
        return (
            FiokAllapot(
                egyseg=egyseg,
                tol=tol,
                ig=ig,
                nyitott=ny,
                eves_bazis=fiok.eves_bazis,
                eves_fogyasztas=eves,
                aktualis_ar=self._aktualis_ar(fiok, ny, most),
                utolso_lezart=lezartak[-1] if lezartak else None,
                egyenleg=egyenleg,
                egyenleg_hiba=egyenleg_hiba,
                napelem=napelem_e,
                napelem_hiba=napelem_hiba,
            ),
            lezart_valt,
        )


    async def _egyenleg(self, sub: ConfigSubentry, tarolt: dict[str, Any], fiok: Fiok, szamlalo: Szamlalo, most: datetime, tovabbi: list[Szamlalo] | None = None) -> EvesEgyenleg:
        """Részszámlás fiók: kézzel rögzített + Díjnet-számlák, éves egyenleg."""
        reszek = {r["datum"]: Decimal(str(r["osszeg"])) for r in tarolt.get("reszszamlak", [])}
        if sub.data.get(CONF_DIJNET):
            for kelt, osszeg, _ in await self.hass.async_add_executor_job(
                dijnet.szamlak, Path(self.hass.config.config_dir), DIJNET_MINTA, sub.data[CONF_DIJNET]
            ):
                reszek.setdefault(kelt.isoformat(), Decimal(0))
                reszek[kelt.isoformat()] += osszeg  # azonos napon több számla összeadódik
        lista = [(d(k), v) for k, v in reszek.items()]
        return eves_egyenleg(
            fiok, self.tar, szamlalo, most, lista,
            reszszamla_db_ev=int(sub.data.get(CONF_RESZSZAMLA_DB) or 11),
            elozo_bazis=elozo_bazis(tarolt),
            tovabbi=tovabbi,
            reszszamla_osszeg=Decimal(str(sub.data[CONF_RESZSZAMLA_OSSZEG])) if sub.data.get(CONF_RESZSZAMLA_OSSZEG) else None,
            elozo_ev_mennyiseg=Decimal(str(sub.data[CONF_ELOZO_EV])) if sub.data.get(CONF_ELOZO_EV) else None,
        )

    async def _napelem(
        self, sub: ConfigSubentry, tarolt: dict[str, Any], fiok: Fiok, vetel: Szamlalo, tol: date, ig: date, most: datetime, mod: str
    ) -> napelem.NapelemEredmeny:
        """Napelemes fiók (kísérleti): betáplálási számláló a 2.8.0-s leolvasásokból és a betáplálás-szenzorból."""
        csat = betaplalas_csatorna(tarolt)
        sorozat = None
        if sub.data.get(CONF_BETAPLALAS):
            kezdet = min([tol, fiok.eves_bazis or tol, *(m.beepitve for m in csat.merok)])
            sorozat = await self._sorozat(sub.data[CONF_BETAPLALAS], datetime.combine(kezdet, datetime.min.time()) - timedelta(days=1), most)
        tol_nap = d(sub.data.get(CONF_FORRAS_TOL))
        betap = Szamlalo.csatornabol(
            csat, sorozat, Decimal(str(sub.data.get(CONF_SZORZO) or 1)),
            meroallas=sub.data.get(CONF_FORRAS_TIPUS, "meroallas") == "meroallas",
            sorozat_tol=datetime.combine(tol_nap, datetime.min.time()) if tol_nap else None,
        )
        if mod == "brutto":
            return napelem.brutto(fiok, self.tar, tol, ig, vetel, betap, meres_vege=most)
        bazis = fiok.eves_bazis or tol
        return napelem.szaldo(fiok, self.tar, bazis, egy_ev_mulva(bazis), vetel, betap, meres_vege=most)

    def _aktualis_ar(self, fiok: Fiok, ny: NyitottIdoszak, most: datetime) -> Decimal | None:
        """A következő elfogyasztott egység ára a mért egységben (gáznál Ft/m³), a HA Energia irányítópulthoz."""
        for s in ny.eddig.szeletek:
            if datetime.combine(s.tol, datetime.min.time()) <= most < datetime.combine(s.ig, datetime.min.time()):
                ar = s.egysegar_kedvezmenyes if s.keret is None or (s.elszamolt or s.mennyiseg) < s.keret else s.egysegar_piaci
                erv = self.tar.felold(_hozzarendeles(fiok, s.tol), s.tol, fiok.szolgaltato, fiok.feluliras)
                atv = erv.szabalyok.get("atvaltas")
                if erv.szabalyok.get("csatornadij") and fiok.csatornak[0].csatornadij_aktiv and erv.dijak.get("csatorna_m3"):
                    # Víz: a csatornadíj is a következő m³ ára (az almérő levonását itt nem vesszük figyelembe).
                    afa = erv.dijak.get("afa")
                    ar = ar + erv.dijak["csatorna_m3"] * (1 + Decimal(afa) / 100 if afa is not None else 1)
                if atv:
                    fe, _ = futoertek(s.tol, atv, fiok)
                    ar = ar * fe * Decimal(atv.get("korrekcios_tenyezo_alap", 1))
                return ar
        return None
