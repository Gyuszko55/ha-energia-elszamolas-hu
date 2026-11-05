"""Időszakos újraszámolás: fiókonként a nyitott időszak, az előrejelzés és a lezárások."""

from __future__ import annotations

import asyncio
import copy
import json
import dataclasses
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    FIX_DIJAS,
    CONF_KOV_EVES,
    CONF_DIJSZABAS,
    CONF_GYARI_SZAM,
    CONF_KEZDO_ALLAS,
    CONF_BEEPITVE,
    CONF_DIJSZABAS_TOL,
    CONF_ALMERO,
    CONF_ALMERO_FORRAS,
    CONF_BETAPLALAS,
    CONF_DIJNET,
    CONF_NAPELEM,
    CONF_ELSZAMOLAS_HONAP,
    CONF_SZAMLAZAS_HONAP,
    CONF_ELOZO_EV,
    CONF_HASZNALAT,
    CONF_SZUNETEL_IG,
    CONF_SZUNETEL_TOL,
    CONF_UTALAS_NAP,
    CONF_ATALANY_MENNYISEG,
    CONF_RESZSZAMLA_DB,
    CONF_RESZSZAMLA_OSSZEG,
    CONF_SZAMLA_MAPPA,
    CONF_SZAMLA_MEROK,
    CONF_SZOLGALTATO,
    DIJNET_MINTA,
    CONF_FORRAS,
    CONF_FORRAS_TIPUS,
    CONF_FORRAS_KORREKCIO,
    CONF_FORRAS_TOL,
    CONF_PROFIL_FORRAS,
    CONF_H_NYARI,
    CONF_H_TELI,
    CONF_A2_CSUCS,
    CONF_A2_VOLGY,
    CONF_KOZMU,
    CONF_KERET_AKTIV,
    CONF_SZORZO,
    DOMAIN,
    EGYSEG,
    FIOK,
    FRISSITES_PERC,
    LEZARAS_KESLELTETES_ORA,
)
from pathlib import Path

from homeassistant.components import persistent_notification

from . import beallitas, dijnet, szamlak
from .beallitas import atalany_mennyiseg
from . import ellenorzes
from . import ai_beolvaso, sablon, szamla_ellenorzo
from . import folyoszamla as folyoszamla_
from .szamla_import import (
    szamla_allasok,
    IMPORT_VERZIO, befizetesek_egyesitese, folyoszamla_meta, hozzatartozik, mappas_adatok_torlese, regiszter_rogzit, szamla_meta, atalany_szamitas, esedekes, rogzit, szamla_statisztika, szamlazasi_ablak,
    szamlazasi_eltolas, ujraertekel, sajat_ertek, kezi_idoszak_potlas, automatikus_rendezes, storno_parositas,
)
from . import fizetes, kimutatas, sziget_ha
from .modell import kovetkezo_idopont, szenzor_ertek, frissitesi_perc, FORRAS_PROBAK
from .motor.kovetkezo_szamla import diktalas_szerint_szamlaz, kovetkezo_szamla_idoszak
from .modell import utem_szerinti_diktalas, kezdo_origo_szinkron, kezdopont, mero_szinkron, diktalasi_ablak, diktalasi_hatarok, betaplalas_csatorna, d, kezdo_almero, elozo_bazis, eredmeny_tarolhato, elszamolasi_napok, fiok_motorba, kezdo_mero
from .motor import napelem
from .motor.egyenleg import (
    EvesEgyenleg,
    VarhatoElszamolas,
    atalany_havi,
    egy_ev_mulva,
    teljes_honapok,
    eves_egyenleg,
    havi_alapdij_honapokra,
    honap_mulva,
    varhato_elszamolas,
)
from .motor.elszamolas import _hozzarendeles, _keret_nyers, _kerekit_keret, _modhoz, elszamolt_mennyiseg, eves_keret_kezdete, futoertek, idenyszak
from .motor.dijszabas import DijszabasHiba, DijszabasTar
from .motor.elorejelzes import NyitottIdoszak, idoszak, nyitott
from .motor.elszamolas import szamol
from .motor.kalibracio import ABLAK_NAP, Kalibracio, kalibral, tisztit
from .motor.profil import napi_valtozas, profillal
from .motor.szamlalo import NincsAdat, Pont, Szamlalo, idenyre_szoritva, kijelzett_allas, nap_kezdete
from .motor.rugalmas import rugalmas_ar
from .motor.zona import napi_zonak
from .motor.tipusok import Csatorna, Fiok, LeolvasasTipus
from .tarolo import Tarolo

_LOGGER = logging.getLogger(__name__)
ELOZMENY_NAPOK = 8  # a 7 napos átlaghoz


def _stat_esedekessel(stat: dict[str, Any] | None, es: dict[str, Any] | None) -> dict[str, Any] | None:
    """A számla-statisztika „következő számla” adata az ütem szerinti esedékességből (a várható összeggel,
    nem az utolsó számla összegével – az utolsó lehetett elszámoló is)."""
    if stat is not None and es and es.get("szunetel"):
        return stat | {"kovetkezo_datum": None, "kovetkezo_osszeg": None, "figyelmeztetes": None}  # szünetel: nem jön számla
    if stat is None or not es or not es.get("kovetkezo_osszeg"):
        return stat  # 0 Ft-os „következő” (idényen kívüli negyedév): nem jön számla – a statisztika becslése marad
    return stat | {"kovetkezo_datum": es["kovetkezo_datum"], "kovetkezo_osszeg": es["kovetkezo_osszeg"]}


ARSZABAS = {"villany/a1": "A1", "villany/h": "H", "villany/b": "B"}  # a díjszabás → a számla árszabása (válogatáshoz)


def helyi_most() -> datetime:
    return dt_util.now().replace(tzinfo=None, microsecond=0)


def _ismert_masolat(nev: str, tarolt: dict[str, Any]) -> bool:
    """A fájlnévben egy már rögzített számla sorszáma áll (ugyanannak a számlának egy másolata), vagy egy rögzített
    számla ebből a fájlból jött (pl. AI-val kiolvasva – a beépített olvasó nem ismeri fel)."""
    szamlak = tarolt.get("szamlak") or {}
    tores = {k for k in szamlak if len(k) >= 6}
    return any(k in nev for k in tores) or any(x.get("fajl") == nev for x in szamlak.values())


def _iso_d(x: Any) -> str | None:
    return x.isoformat() if hasattr(x, "isoformat") else x


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
    utolso_szamla: dict[str, Any] | None = None
    elszamolas: VarhatoElszamolas | None = None
    szamla_stat: dict[str, Any] | None = None
    atalany: dict[str, Any] | None = None
    esedekes: dict[str, Any] | None = None
    utem: dict[str, Any] | None = None  # szolgáltató, számlázási ütem, elszámolási ciklus
    szamlazasi: dict[str, Any] | None = None  # többhavi utólagos számlázás ablaka (víz, hulladék)
    napelem_hiba: str | None = None
    egyenleg_hiba: str | None = None
    hiba: str | None = None
    d_osszevetes: dict[str, Any] | None = None  # A1 fióknál: „mi lenne D árszabással”
    keret_ev: dict[str, Any] | None = None
    megszunt: dict[str, Any] | None = None  # lezárt (megszüntetett) fiók: {datum, allas} – végelszámolás
    szunetel: dict[str, Any] | None = None  # szüneteltetett számlázás: {tol, ig (utolsó nap, None: tart), most (ma szünetel-e)}
    diktalt_szamla: dict[str, Any] | None = None  # átalánynál: a diktált állás szerinti következő számla (felülírja az átalányt)
    diktalas_szerint: bool = False  # átalányos, de diktálás szerint (havonta elszámolóval) számlázott fiók
    szamla_allasok: list[dict[str, Any]] | None = None  # átalányszámlákból: az előző állás + a számlázott mennyiség (tájékoztató)
    # A folyószámla túlfizetése a várható számlákba beszámítva: {turfizetes, levonva, marad} (Ft).
    beszamitas: dict[str, Any] | None = None
    uton_szamlak: list[dict[str, Any]] | None = None  # lezárt időszak, amelyre még nem jött számla (becsült összeggel)  # gáz: éves kedvezményes keret és az év elejétől ténylegesen felhasznált


DIKT_MODOK = ("diktalas", "leolvasas")  # időszakmódok, amelyeknél a határok leolvasások/diktálások
D_DIJSZABASOK = ("villany/a1", "villany/d")  # ezeknél kell az órás fogyasztás × rugalmas ár (D, ill. összevetés)


def _uton_szamlak(sub: ConfigSubentry, tarolt: dict[str, Any], lezartak: list[dict[str, Any]], ma: date) -> list[dict[str, Any]]:
    """Fogyasztás szerinti fióknál a lezárt időszakok (az elmúlt 45 napban zárultak), amelyekre még nem érkezett
    számla – pl. új fióknál a számla „úton van”. Az összeg a Rezsikövető számítása (becsült). Átalányos és fix díjas
    fióknál nincs: ott a részszámla összege ismert."""
    if beallitas.reszszamlas(sub.data) or beallitas.fix_dijas(sub.data):
        return []
    kihagy = _ervenytelenek(tarolt.get("szamlak") or {})
    szamlazott = [(d(x["idoszak"][0]), d(x["idoszak"][1])) for k, x in (tarolt.get("szamlak") or {}).items()
                  if x.get("idoszak") and k not in kihagy]
    # A felhasználó szerint egy későbbi számlában már elszámolt (rendezett) úton lévő időszakok – kezdőnapjuk (ISO).
    rendezett = {x.get("tol") for x in tarolt.get("rendezett_uton") or []}
    out = []
    for lz in lezartak:
        tol, ig = d(lz["tol"]), d(lz["ig"])  # ig: kizárólagos
        # Ha a fióknak még egy számlája sincs (új fiók), a régebbi lezárt időszakok számlája is „úton” lehet.
        if ig > ma or (ma - ig).days > (45 if szamlazott else 120) or not lz.get("osszesen_ft"):
            continue
        # Számlázott, ha egy számla legalább két napon átfedi (az előző számla utolsó napja = az időszak első napja:
        # a záró állás napja – ez nem átfedés).
        if any((min(b, ig - timedelta(days=1)) - max(a, tol)).days >= 1 for a, b in szamlazott):
            continue
        # Diktálásos/leolvasásos villanynál a számla „előző leolvasás másnapja – leolvasás napja” (MVM, Kertes ház A1 2025:
        # éves leolvasás 10-01 → számla 09-10 – 10-01, a következő 10-02-től); máshol [tol, ig).
        dikt = beallitas.idoszak_mod(sub.data)[0] in DIKT_MODOK
        if ((tol + timedelta(days=1)).isoformat() if dikt else lz["tol"]) in rendezett:
            continue
        out.append({"tol": (tol + timedelta(days=1)).isoformat() if dikt else lz["tol"],
                    "ig": (ig if dikt else ig - timedelta(days=1)).isoformat(), "osszeg": int(lz["osszesen_ft"]),
                    "mennyiseg": lz.get("mennyiseg")})
    return out


def _rendezett_vegek(tarolt: dict[str, Any]) -> list[date]:
    """A rendezettnek jelölt (egy későbbi számlában elszámolt) úton lévő időszakok utolsó napjai: ezek kiszámlázottnak
    számítanak – a következő számla utánuk indul."""
    return [d(x["ig"]) for x in tarolt.get("rendezett_uton") or [] if x.get("ig")]


_szamlazott_idoszak = szamlak.szamlazott_idoszak
_szamla_teljes_dija = szamlak.szamla_teljes_dija
_ervenytelenek = szamlak.ervenytelenek  # stornók + az általuk sztornózott számlák


def _tobbhavi_folyo_idoszak(tarolt: dict[str, Any], periodus: int, ma: date) -> tuple[date, date] | None:
    """Több havonta (2, 4 … hónaponként) számlázott fiók folyó számlázási időszaka, [tol, ig): a legutóbbi számla
    utolsó napja utántól az ütem szerint, a mai napig továbbléptetve (pl. kéthavi: 08.01–09.30 után 10.01–11.30)."""
    kihagy = _ervenytelenek(tarolt.get("szamlak") or {})
    vegek = [i[1] for k, x in (tarolt.get("szamlak") or {}).items()
             if k not in kihagy and x.get("tipus") != "storno" and (i := _szamlazott_idoszak(x))]
    if not vegek or periodus < 2:
        return None
    alap = max(vegek) + timedelta(days=1)
    k = 1
    while honap_mulva(alap, k * periodus) <= ma:  # mindig az alapnaptól lépve (hónapvégnél ne csússzon 31 → 28)
        k += 1
    return honap_mulva(alap, (k - 1) * periodus), honap_mulva(alap, k * periodus)


def _atalany_mennyiseg_szamlan(x: dict[str, Any]) -> Decimal | None:
    """Az átalány (rész)számlán számlázott mennyiség: villany kWh, gáz m³, víz ivóvíz m³."""
    if x.get("tipus") != "resz":
        return None
    if x.get("elszamolt_kwh") is not None:
        return Decimal(str(x["elszamolt_kwh"]))
    if (g := x.get("elszamolt_gaz")) and g.get("m3") is not None:
        return Decimal(str(g["m3"]))
    if (v := x.get("elszamolt_viz")) and v.get("atalany") and v.get("ivoviz") is not None:
        return Decimal(str(v["ivoviz"]))
    return None


def _utolso_elszamolt_viz(tarolt: dict[str, Any]) -> dict[str, Any] | None:
    szamlak = [(x["kelte"], k, x) for k, x in (tarolt.get("szamlak") or {}).items() if x.get("elszamolt_viz")]
    if not szamlak:
        return None
    kelte, sorszam, x = max(szamlak)
    e = x["elszamolt_viz"]
    return {
        "ivoviz": float(e["ivoviz"]), "csatorna": float(e["csatorna"]), "atalany": e.get("atalany", False),
        "idoszak": e.get("idoszak"), "sorszam": sorszam, "kelte": kelte, "osszeg": x.get("osszeg"),
    }


def _utolso_elszamolt_kwh(tarolt: dict[str, Any]) -> dict[str, Any] | None:
    """Villany: a legutóbbi számla szerint elszámolt mennyiség (kWh), időszaka és fajtája."""
    szamlak = [(x["kelte"], k, x) for k, x in (tarolt.get("szamlak") or {}).items()
               if x.get("elszamolt_kwh") is not None and x.get("tipus") in ("resz", "elszamolo")]
    if not szamlak:
        return None
    kelte, sorszam, x = max(szamlak)
    return {"kwh": float(x["elszamolt_kwh"]), "idoszak": x.get("idoszak"), "tipus": x["tipus"], "sorszam": sorszam, "kelte": kelte}


def _utolso_elszamolt_gaz(tarolt: dict[str, Any]) -> dict[str, Any] | None:
    """Gáz: a legutóbbi számla szerint elszámolt mennyiség (m³, MJ), és a legutóbbi közölt részszámla-mennyiség."""
    szamlak = sorted(((x["kelte"], k, x) for k, x in (tarolt.get("szamlak") or {}).items() if x.get("elszamolt_gaz")), key=lambda t: t[0])
    if not szamlak:
        return None
    kelte, sorszam, x = szamlak[-1]
    resz = [(y["kelte"], y["kovetkezo_resz_m3"]) for y in (tarolt.get("szamlak") or {}).values() if y.get("kovetkezo_resz_m3")]
    return {
        "m3": float(x["elszamolt_gaz"]["m3"]), "mj": float(x["elszamolt_gaz"]["mj"]), "idoszak": x.get("idoszak"),
        "tipus": x["tipus"], "sorszam": sorszam, "kelte": kelte,
        "resz_m3": float(max(resz)[1]) if resz else None,
    }


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
        self.mero_allasok: dict[str, list[dict[str, Any]]] = {}  # az indítókártyának: szenzoros csatornák mostani állása
        # A számlamappát az első frissítés kihagyja (a PDF-olvasás percekig tarthat, és az indulást ne fogja meg);
        # a HA elindulása után egy külön frissítés dolgozza fel.
        self.mappa_halasztva = True
        # Jóváhagyásra váró (a számlamappába érkezett) számlák előnézete fiókonként: mi változna a jóváhagyással.
        self.elonezet: dict[str, dict[str, Any]] = {}
        self.sziget_allapot: dict[str, dict[str, Any]] = {}  # szigetüzemi rendszerek (kísérleti, sziget_ha)
        self.email: Any = None  # számlák e-mailből (email_ha.EmailFigyelo) – az __init__ köti be
        self._elonezet_kulcs: dict[str, Any] = {}
        self.ellenorzesek: dict[str, list[dict[str, Any]]] = {}
        self.dijnet_kesz = False  # a Díjnet-fizetések beolvasva (addig a fizetett számlák is kifizetetlennek látszanának)
        self.dijnet_fizetett: dict[str, dict[str, Any]] = {}  # Díjnet: kifizetett számlák (számlaszám → fizetve, határidő)  # számla-ellenőrzés: fiókonként a talált hibák
        self._ellenorzes_kulcs: dict[str, Any] = {}
        self._ellenorzes_nyers: dict[str, list[dict[str, Any]]] = {}
        # A panelről feltöltött fájlok: a felhasználó maga választotta, nem kell külön jóváhagyás.
        self.azonnali_fajlok: set[str] = set()
        # Fájl → beolvasott számla (útvonal, módosítás, méret szerint): több fiók is használhatja ugyanazt a mappát.
        self._fajl_cache: dict[tuple[str, float, int], Any] = {}
        # Automatikus mérő-korrekció fiókonként és csatornánként (a panel is ezt mutatja); naponta, ill. új
        # leolvasáskor számoljuk újra.
        self.kalibraciok: dict[str, dict[str, Kalibracio]] = {}
        self._kal_kulcs: dict[tuple[str, str], tuple] = {}
        self._zar = asyncio.Lock()
        # Hiányzó forrás-szenzor: hányszor egymás után, és melyik entitás (percenkénti újrapróba csak korlátozottan).
        self._forras_probak = 0
        self._hianyzo_forrasok: set[str] = set()
        self._naplozott_hibak: set[tuple[str, str]] = set()  # váratlan fiókhibák: mindegyiket egyszer, részletesen naplózzuk
        # D árszabás: fiókonként az órás fogyasztásból képzett napi (q, q×ár, becsült) – 6 óránként, ill. új árlistánál.
        self._d_cache: dict[str, tuple[datetime, str | None, dict]] = {}
        # Szigetüzem: a lezárt napok napi statisztikája (entitás, kezdet) szerint, a letöltés helyi napjával – naponta
        # egyszer töltjük le (800 nap); a mai nap, az órás rész és a mostani érték minden frissítéskor friss.
        self._napi_stat: dict[tuple[str, datetime], tuple[date, list[dict[str, Any]]]] = {}
        self._napi_stat_kert: set[tuple[str, datetime]] = set()
        # D-elemzéshez a forrás-szenzor negyedórás fogyasztása. A recorder az 5 perces statisztikát csak néhány napig
        # őrzi, ezért óránként átmásoljuk a saját tárba (fiókonként „ÉÉÉÉ-HH-NNTÓÓ:PP” → kWh); így halmozódik.
        self._negyed_store: Store[dict[str, dict[str, float]]] = Store(hass, 1, f"{DOMAIN}_negyedek.{entry.entry_id}")
        self._negyedek: dict[str, dict[str, float]] | None = None
        self._negyed_frissitve: dict[str, datetime] = {}
        # D havi kimutatás: lezárt hónaponként (árforrás-kulcs, sor), és a 12 lezárt hónap összege a szenzorhoz.
        self._d_havi_cache: dict[str, dict[str, tuple[tuple, dict[str, Any]]]] = {}
        self._d_12ho: dict[str, dict[str, Any]] = {}
        self._d_havi_fut: set[str] = set()

    def fiokok(self) -> dict[str, ConfigSubentry]:
        return {sid: s for sid, s in self.config_entry.subentries.items() if s.subentry_type == FIOK}

    def motor_fiok(self, subentry_id: str) -> Fiok:
        sub = self.fiokok()[subentry_id]
        return self._otthon_bazissal(sub, fiok_motorba(dict(sub.data), self.tarolo.fiok(subentry_id)))

    async def szamlalo(self, subentry_id: str, fiok: Fiok, tol: datetime, most: datetime, index: int = 0) -> Szamlalo:
        """Egy csatorna számlálója: leolvasások + a forrás-entitás napi statisztikája + élő állapota. H-tarifánál a
        regiszter (téli / nyári) a hézagokban csak a saját idénye napjain nő (motor.szamlalo.idenyre_szoritva)."""
        sz = await self._szamlalo(subentry_id, fiok, tol, most, index)
        szerep = fiok.csatornak[index].szerep
        if szerep in ("h_teli", "h_nyari"):
            from .motor.elszamolas import _hozzarendeles, idenyszak  # noqa: PLC0415

            ma = most.date()
            idenyek = self.tar.felold(_hozzarendeles(fiok, ma), ma, fiok.szolgaltato, fiok.feluliras).szabalyok.get("idenyszak") or []
            if idenyek:
                sz = idenyre_szoritva(sz, lambda nap: (idenyszak(nap, idenyek) or {}).get("nev") == szerep[2:])
        return sz

    async def _szamlalo(self, subentry_id: str, fiok: Fiok, tol: datetime, most: datetime, index: int = 0) -> Szamlalo:
        beall = self.fiokok()[subentry_id].data
        csatorna = fiok.csatornak[index]
        forras = {
            "vetelezes": beall.get(CONF_FORRAS),
            "h_teli": beall.get(CONF_H_TELI),
            "h_nyari": beall.get(CONF_H_NYARI),
            "zona_csucs": beall.get(CONF_A2_CSUCS),
            "zona_volgy": beall.get(CONF_A2_VOLGY),
            "almero": beall.get(CONF_ALMERO_FORRAS),
        }.get(csatorna.szerep)
        if not forras:
            return Szamlalo.csatornabol(csatorna)
        # A sorozatpontokat a megelőző horgonyhoz igazítjuk, ezért a sorozatnak a szükséges
        # legkorábbi pont előtti utolsó horgonytól kell indulnia.
        horgonyok = [m.beepitve for m in csatorna.merok] + [lo.datum for m in csatorna.merok for lo in m.leolvasasok]
        kell = min(tol.date(), fiok.eves_bazis or tol.date())
        korabbiak = [h for h in horgonyok if h and h <= kell]
        kezdet = max(korabbiak) if korabbiak else kell
        korrekcio = beall.get(CONF_FORRAS_KORREKCIO, True)
        sor_tol = datetime.combine(kezdet, datetime.min.time()) - timedelta(days=1)
        if korrekcio:  # a korrekcióhoz az utolsó ~egy év leolvasásai kellenek
            sor_tol = min(sor_tol, most - timedelta(days=ABLAK_NAP + 1))
        sorozat = await self._sorozat(forras, sor_tol, most)
        szorzo = Decimal(str(beall.get(CONF_SZORZO) or 1))
        meroallas = beall.get(CONF_FORRAS_TIPUS, "meroallas") == "meroallas"
        tol_nap = d(beall.get(CONF_FORRAS_TOL))
        sorozat_tol = datetime.combine(tol_nap, datetime.min.time()) if tol_nap else None
        if korrekcio:
            ervenyes = [(t, v * szorzo) for t, v in sorozat if sorozat_tol is None or t >= sorozat_tol]
            kal = self._kalibracio(subentry_id, csatorna, ervenyes, most)
            if kal.szorzo:
                # A megtisztított sorozat változását (ugrás és nullázódás nélkül) szorozzuk; a leolvasások horgonyok.
                tiszta, _ = tisztit(ervenyes)
                return Szamlalo.csatornabol(csatorna, tiszta, kal.szorzo, meroallas=False)
        else:
            self.kalibraciok.get(subentry_id, {}).pop(csatorna.szerep, None)
        return Szamlalo.csatornabol(csatorna, sorozat, szorzo, meroallas=meroallas, sorozat_tol=sorozat_tol)

    def _kalibracio(self, sid: str, csatorna: Csatorna, sor: list[tuple[datetime, Decimal]], most: datetime) -> Kalibracio:
        """A csatorna mérő-korrekciója (gyorsítótárból, ha aznap és ugyanazokkal a leolvasásokkal már kiszámoltuk)."""
        valodi = [lo for m in csatorna.merok for lo in m.leolvasasok if lo.tipus != LeolvasasTipus.AUTOMATIKUS]
        kulcs = (most.date(), tuple(sorted((lo.datum, lo.allas) for lo in valodi)), len(sor) > 0)
        kal = self.kalibraciok.get(sid, {}).get(csatorna.szerep)
        if kal is not None and self._kal_kulcs.get((sid, csatorna.szerep)) == kulcs:
            return kal
        alap = Szamlalo.csatornabol(csatorna)
        pontok = []
        for lo in valodi:
            try:
                pontok.append((lo.idopont, alap.ertek(lo.idopont)[0]))
            except NincsAdat:
                continue
        kal = kalibral(pontok, sor, most)
        self.kalibraciok.setdefault(sid, {})[csatorna.szerep] = kal
        self._kal_kulcs[(sid, csatorna.szerep)] = kulcs
        return kal

    async def _orak(self, forras: str, tol: datetime) -> list[tuple[datetime, Decimal]]:
        """A forrás-szenzor órás fogyasztása (az óra kezdete helyi időben, a változás az órára) a statisztikából."""
        tz = dt_util.get_default_time_zone()
        stat = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period, self.hass, tol.replace(tzinfo=tz), None, {forras}, "hour", None, {"state"}
        )
        orak: list[tuple[datetime, Decimal]] = []
        elozo: Decimal | None = None
        for r in stat.get(forras, []):
            if r.get("state") is None:
                elozo = None
                continue
            ertek = Decimal(str(r["state"]))
            kezd = dt_util.utc_from_timestamp(r["start"]) if isinstance(r["start"], (int, float)) else r["start"]
            if elozo is not None and ertek >= elozo:
                orak.append((dt_util.as_local(kezd).replace(tzinfo=None), ertek - elozo))
            elozo = ertek
        return orak

    async def _d_fiok(self, sid: str, sub: ConfigSubentry, fiok: Fiok, most: datetime) -> Fiok:
        """D árszabáshoz és az A1 fiók „mi lenne D-n” összevetéséhez: az órás fogyasztás × az MVM által közzétett órás
        rugalmas ár, naponként összesítve (az elmúlt ~13 hónapra). Ahol az óra ára még nincs közzétéve, a legutóbbi
        teljes közzétett hónap fogyasztással súlyozott ára helyettesíti (becsült)."""
        d_arak = self.hass.data.get(DOMAIN, {}).get("d_arak")
        forras = sub.data.get(CONF_FORRAS)
        if sub.data.get(CONF_DIJSZABAS) not in D_DIJSZABASOK or d_arak is None or not d_arak.orak:
            return fiok
        fajl = d_arak.valtozat
        cache = self._d_cache.get(sid)
        if cache and cache[1] == fajl and most - cache[0] < timedelta(hours=6):
            return dataclasses.replace(fiok, **cache[2])
        orak = await self._orak(forras, most - timedelta(days=400)) if forras else []
        # Tartalék: a legutóbbi teljes közzétett hónap (fogyasztással súlyozott, ennek híján egyszerű) átlagára.
        utolso = d_arak.adat.get("utolso_ora") or max(d_arak.orak)
        ho = utolso[:7]
        ho_orak = {k: v for k, v in d_arak.orak.items() if k.startswith(ho)}
        q_ho = {o.strftime("%Y-%m-%dT%H"): q for o, q in orak if o.strftime("%Y-%m") == ho}
        sq = sum((q_ho.get(k, Decimal(0)) for k in ho_orak), Decimal(0))
        tartalek = (
            sum((q_ho.get(k, Decimal(0)) * Decimal(str(v)) for k, v in ho_orak.items()), Decimal(0)) / sq
            if sq > 0 else Decimal(str(sum(ho_orak.values()) / len(ho_orak)))
        )
        napok: dict[date, list] = {}
        for o, q in orak:
            ar = d_arak.ar(o)
            x = napok.setdefault(o.date(), [Decimal(0), Decimal(0), False])
            x[0] += q
            x[1] += q * (ar if ar is not None else tartalek)
            x[2] = x[2] or ar is None
        ar_napok: dict[date, list[float]] = {}
        for k, v in d_arak.orak.items():
            ar_napok.setdefault(date.fromisoformat(k[:10]), []).append(v)
        mezok = {
            "d_napok": {k: (v[0], v[1], v[2]) for k, v in napok.items()},
            "d_ar_napok": {k: Decimal(str(sum(v) / len(v))) for k, v in ar_napok.items()},
            "d_tartalek": tartalek,
        }
        self._d_cache[sid] = (most, fajl, mezok)
        return dataclasses.replace(fiok, **mezok)

    async def _negyed_tar(self) -> dict[str, dict[str, float]]:
        if self._negyedek is None:
            self._negyedek = await self._negyed_store.async_load() or {}
        return self._negyedek

    async def negyedek_frissit(self, sid: str, forras: str, most: datetime, kenyszer: bool = False) -> None:
        """A forrás 5 perces statisztikájából a negyedórás fogyasztás a saját tárba (óránként legfeljebb egyszer)."""
        if not kenyszer and most - self._negyed_frissitve.get(sid, datetime.min) < timedelta(hours=1):
            return
        self._negyed_frissitve[sid] = most
        tar = await self._negyed_tar()
        sajat = tar.setdefault(sid, {})
        tz = dt_util.get_default_time_zone()
        tol = most - timedelta(days=10)
        if sajat:
            tol = max(tol, datetime.fromisoformat(max(sajat)) - timedelta(hours=2))
        stat = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period, self.hass, tol.replace(tzinfo=tz), None, {forras}, "5minute", None, {"state"}
        )
        uj: dict[str, float] = {}
        elozo: float | None = None
        for r in stat.get(forras, []):
            if r.get("state") is None:
                elozo = None
                continue
            ertek = float(r["state"])
            kezd = dt_util.utc_from_timestamp(r["start"]) if isinstance(r["start"], (int, float)) else r["start"]
            if elozo is not None and ertek >= elozo:
                h = dt_util.as_local(kezd)
                k = h.replace(minute=h.minute - h.minute % 15).strftime("%Y-%m-%dT%H:%M")
                uj[k] = uj.get(k, 0.0) + ertek - elozo
            elozo = ertek
        if not uj:
            return
        # Az első (csonka) negyedórát nem írjuk felül, ha már volt rá teljesebb adat.
        elso = min(uj)
        if elso in sajat and sajat[elso] > uj[elso]:
            del uj[elso]
        sajat.update({k: round(v, 5) for k, v in uj.items()})
        hatar = (most - timedelta(days=460)).strftime("%Y-%m-%d")
        tar[sid] = {k: v for k, v in sajat.items() if k >= hatar}
        self._negyed_store.async_delay_save(lambda: self._negyedek or {}, 30)

    async def d_elemzes(self, sid: str, honap: str | None) -> dict[str, Any]:
        """D-tarifa elemzés egy naptári hónapra negyedórás bontásban (lásd `_d_honap`), és a havi kimutatás."""
        sub = self.fiokok()[sid]
        d_arak = self.hass.data.get(DOMAIN, {}).get("d_arak")
        if d_arak is None or not d_arak.orak:
            raise ValueError("A D árszabás árlistája még nem töltődött le.")
        most = helyi_most()
        forras = sub.data.get(CONF_FORRAS)
        if forras:
            await self.negyedek_frissit(sid, forras, most, kenyszer=True)
        honapok = self._d_honapok(d_arak, most)
        honap = honap if honap in honapok else honapok[0]
        adat = await self._d_honap(sid, honap, most)
        havi = await self.d_havi_kimutatas(sid, most, (honap, adat))
        return adat | {
            "nev": sub.title,
            "honapok": honapok,
            "havi": havi,
            "mvm_ig": (d_arak.adat.get("utolso_ora") or "")[:10] or None,
            "szamitott_ig": d_arak.szamitott_ig,
            "kereskedoi_dij": 13.70,
            "van_szenzor": bool(forras),
            "szaldo_napelem": sub.data.get(CONF_NAPELEM) == "szaldo",
        }

    @staticmethod
    def _d_honapok(d_arak: Any, most: datetime) -> list[str]:
        """Választható hónapok: a folyó hónaptól visszafelé (legfeljebb 13 + a folyó), ameddig van ár."""
        legelso = min(d_arak.orak)[:7]
        honapok = []
        h = most.date().replace(day=1)
        while h.isoformat()[:7] >= legelso and len(honapok) < 13:
            honapok.append(h.isoformat()[:7])
            h = (h - timedelta(days=1)).replace(day=1)
        return honapok

    async def d_havi_kimutatas(
        self, sid: str, most: datetime, kesz: tuple[str, dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """Havonta (a folyó és az előző 12 naptári hónap): fogyasztás, keret feletti rész, A1 és D költsége mindkét
        számítással. A lezárt hónapok eredménye gyorsítótárban (amíg az árforrásuk nem változik)."""
        d_arak = self.hass.data.get(DOMAIN, {}).get("d_arak")
        sub = self.fiokok()[sid]
        if d_arak is None or not d_arak.orak:
            return []
        mvm_ig = (d_arak.adat.get("utolso_ora") or "")[:7]
        cache = self._d_havi_cache.setdefault(sid, {})
        ki = []
        folyo = most.date().isoformat()[:7]
        for i, h in enumerate(self._d_honapok(d_arak, most)):
            kulcs = (d_arak.adat.get("fajl"), None if h <= mvm_ig else d_arak.szamitott_ig)
            if kesz and kesz[0] == h:
                adat = kesz[1]
            elif h != folyo and h in cache and cache[h][0] == kulcs:
                ki.append(cache[h][1])
                continue
            else:
                try:
                    adat = await self._d_honap(sid, h, most)
                except (NincsAdat, DijszabasHiba, ValueError) as err:
                    _LOGGER.debug("%s: D havi kimutatás, %s: %s", sub.title, h, err)
                    continue
            o = adat["osszeg"]
            sor = {"honap": h, "kwh": o["kwh"], "keret": adat["keret_ho"], "keret_felett": o["keret_felett"],
                   "atlepes": adat["atlepes"], "a1": o["a1"], "d_sajat": o["d"], "d_mvm": o["d_szamla"],
                   "orabol": adat["orabol"], "egyenletes": adat["egyenletes"],
                   "adat_ig": adat["adat_ig"], "folyo": h == folyo}
            if h != folyo:
                cache[h] = (kulcs, sor)
            ki.append(sor)
        # A 12 lezárt hónap összesítése a szenzorhoz is.
        lezart = [x for x in ki if not x["folyo"] and not x.get("adat_ig") and x["kwh"] > 0 and x["d_mvm"] is not None][:12]
        self._d_12ho[sid] = {
            "honapok": len(lezart),
            "mvm": sum(x["d_mvm"] - x["a1"] for x in lezart),
            "sajat": sum(x["d_sajat"] - x["a1"] for x in lezart),
            "tol": lezart[-1]["honap"] if lezart else None,
            "ig": lezart[0]["honap"] if lezart else None,
            "szamolva": most,
        }
        return ki

    def _d_12ho_mezok(self, sid: str, sub: ConfigSubentry, most: datetime) -> dict[str, Any]:
        """A szenzor 12 havi D-különbsége a naptári havi kimutatásból (MVM szerinti számítás), ha már elkészült;
        6 óránként a háttérben újraszámoljuk (a lezárt hónapok gyorsítótárból)."""
        x = self._d_12ho.get(sid)
        if sid not in self._d_havi_fut and (x is None or most - x["szamolva"] > timedelta(hours=6)):
            self._d_havi_fut.add(sid)

            async def fut() -> None:
                try:
                    await self.d_havi_kimutatas(sid, helyi_most())
                    await self.async_request_refresh()
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("%s: D havi kimutatás hiba", sub.title)
                finally:
                    self._d_havi_fut.discard(sid)

            self.config_entry.async_create_background_task(self.hass, fut(), f"hu_rezsi D havi {sid}")
        if x is None or not x["honapok"]:
            return {}
        return {
            "kulonbseg_12ho": x["mvm"], "kulonbseg_12ho_sajat": x["sajat"],
            "naptari_honapok": x["honapok"], "naptari_tol": x["tol"], "naptari_ig": x["ig"],
        }

    async def _d_honap(self, sid: str, honap: str, most: datetime) -> dict[str, Any]:
        """Egy naptári hónap negyedórás D-elemzése: a fogyasztás, a D rugalmas egységár és az A1 ára. A hónap
        kedvezményes kerete (napi 6,91 kWh × a hónap napjai) a hónap elejétől a fogyasztással fogy; amíg tart, mindkét
        árszabáson a kedvezményes ár jár, az átlépés negyedórájától (azon belül arányosan) az A1 piaci, ill. a D
        negyedórás ára („saját” számítás). Az MVM D-számlája a keret feletti mennyiséget a hónap összes negyedórás
        fogyasztásával súlyozott áron számlázza („MVM szerint”). Mindegyikhez a rendszerhasználati díj, bruttó; az
        alapdíj azonos, kimarad."""
        sub = self.fiokok()[sid]
        tarolt = self.tarolo.fiok(sid)
        d_arak = self.hass.data.get(DOMAIN, {}).get("d_arak")
        forras = sub.data.get(CONF_FORRAS)
        tol = date.fromisoformat(honap + "-01")
        kov = (tol + timedelta(days=32)).replace(day=1)
        ig_nap = min(kov, most.date() + timedelta(days=2))  # a holnapi ár már ismert lehet

        # Fogyasztás negyedóránként: a saját tárból, ahol nincs, az órás statisztika negyede (egyenletesen).
        q: dict[str, float] = {}
        orabol: set[str] = set()
        if forras:
            sajat = (await self._negyed_tar()).get(sid, {})
            q = {k: v for k, v in sajat.items() if k.startswith(honap)}
            lefedett_orak = {k[:13] for k in q}
            for o, v in await self._orak(forras, nap_kezdete(tol)):
                if o.date() >= kov:
                    break
                ok = o.strftime("%Y-%m-%dT%H")
                if ok in lefedett_orak:
                    continue
                for perc in ("00", "15", "30", "45"):
                    q[f"{ok}:{perc}"] = float(v) / 4
                    orabol.add(f"{ok}:{perc}")

        # A hónap mennyisége a Rezsikövető (mérőleolvasásokhoz igazított) havi elszámolásából – ehhez igazítjuk a
        # szenzor negyedórás értékeit.
        fiok = self._otthon_bazissal(sub, fiok_motorba(dict(sub.data), tarolt))
        e_ig = min(kov, most.date() + timedelta(days=1))
        menny = Decimal(0)
        if tol <= most.date() and (q or not forras):
            try:
                szamlalok = [await self.szamlalo(sid, fiok, nap_kezdete(tol) - timedelta(days=1), most, i) for i in range(len(fiok.csatornak))]
                e = szamol(fiok, self.tar, tol, e_ig, szamlalok, meres_vege=most if e_ig > most.date() else None,
                           extra_hatarok=elszamolasi_napok(tarolt))
                menny = sum((sz.mennyiseg for sz in e.szeletek if sz.csatorna == "vetelezes"), Decimal(0))
            except (NincsAdat, DijszabasHiba, ValueError) as err:
                _LOGGER.debug("%s: D-elemzés, %s havi elszámolás nem számolható: %s", sub.title, honap, err)
        ervenyes = self.tar.felold(_hozzarendeles(fiok, tol), tol, fiok.szolgaltato, fiok.feluliras)
        keret_sz = ervenyes.szabalyok.get("keret")
        keret_ho = (
            float(_kerekit_keret(keret_sz, _keret_nyers(keret_sz, tol, kov) * fiok.keret_szorzo))
            if keret_sz and fiok.csatornak and fiok.csatornak[0].keret_aktiv else 0.0
        )
        dij = ervenyes.dijak
        afa = 1 + float(dij.get("afa") or 0) / 100
        rhd = float(dij.get("rendszerhasznalati") or 0)

        # A szenzor negyedórás alakja, de a mennyiség a mérőleolvasásokhoz igazított havi elszámolásé (a nyers
        # szenzor eltérhet a hiteles mérőtől); csak észszerű eltérésnél, különben a nyers érték marad.
        igazitas = None
        egyenletes = False
        # Szenzor nélkül a hónap csak az utolsó mérőállásig ismert; ha az a hónap vége előtt van, a hónap hiányos.
        utolso_leol = max((d(lo.get("datum")) for m in tarolt.get("merok", []) for lo in m.get("leolvasasok", []) if lo.get("datum")), default=None)
        adat_ig = utolso_leol if not forras and utolso_leol is not None and utolso_leol < min(kov, most.date()) else None
        if not forras and menny > 0:
            # Szenzor nélkül: a hónap (leolvasásokból számolt) mennyisége a hónap eltelt negyedóráira egyenletesen –
            # a napszaki alak ismeretlen, a D-ár így a hónap egyszerű átlaga (közelítés).
            vege = min(datetime.combine(kov, datetime.min.time()), most.replace(minute=most.minute - most.minute % 15, second=0))
            kulcsok = []
            t_ = datetime.combine(tol, datetime.min.time())
            while t_ < vege:
                kulcsok.append(t_.strftime("%Y-%m-%dT%H:%M"))
                t_ += timedelta(minutes=15)
            if kulcsok:
                q = {k: float(menny) / len(kulcsok) for k in kulcsok}
                egyenletes = True
        q_szenzor = sum(q.values())
        if menny > 0 and q_szenzor > 0:
            f_ = float(menny) / q_szenzor
            if 0.5 < f_ < 2:
                igazitas = f_
                q = {k: v * f_ for k, v in q.items()}
        idok: list[str] = []
        fogy: list[float | None] = []
        d_ar: list[float | None] = []
        forrasok: dict[str, int] = {}
        t = datetime.combine(tol, datetime.min.time())
        while t.date() < ig_nap:
            k = t.strftime("%Y-%m-%dT%H:%M")
            ar, f = d_arak.negyed_ar(k)
            idok.append(k)
            d_ar.append(ar)
            if f:
                forrasok[f] = forrasok.get(f, 0) + 1
            fogy.append(round(q[k], 5) if k in q else None)
            t += timedelta(minutes=15)
        # Összesítés: a keret a hónap elejétől, időrendben fogy; az átlépés negyedórájában arányosan.
        kedv, piac = float(dij["energia_kedvezmenyes"]), float(dij["energia_piaci"])
        a1_ft = d_ft = q_ossz = qd_ar = felett = q_arral = qd_minden = 0.0
        atlepes = None
        for k_, qq, dd in zip(idok, fogy, d_ar, strict=True):
            if qq is None:
                continue
            fel = min(qq, max(0.0, q_ossz + qq - keret_ho))
            if fel > 0 and atlepes is None:
                atlepes = k_
            q_ossz += qq
            if dd is None:
                continue
            a1_ft += ((qq - fel) * kedv + fel * piac + qq * rhd) * afa
            d_ft += ((qq - fel) * kedv + fel * dd + qq * rhd) * afa
            felett += fel
            qd_ar += fel * dd
            q_arral += qq
            qd_minden += qq * dd
        # Az MVM D-számlája a keret feletti mennyiséget a hónap ÖSSZES negyedórás fogyasztásával súlyozott áron
        # számlázza (nem csak az átlépés utániakkal) – ez a „számla szerinti” D.
        d_atlag = qd_minden / q_arral if q_arral else None
        d_szamla = (((q_arral - felett) * kedv + felett * d_atlag + q_arral * rhd) * afa) if d_atlag is not None else None
        return {
            "honap": honap,
            "idok": idok,
            "fogyasztas": fogy,
            "d_ar": d_ar,
            "orabol": len([k for k in idok if k in orabol]),
            "igazitas": round(igazitas, 4) if igazitas else None,
            "egyenletes": egyenletes,
            "adat_ig": adat_ig.isoformat() if adat_ig else None,
            "ar_forras": forrasok,
            "arak": {"kedvezmenyes": kedv, "piaci": piac, "rendszerhasznalati": rhd, "afa": afa},
            "keret_ho": keret_ho,
            "atlepes": atlepes,
            "osszeg": {
                "kwh": round(q_ossz, 3), "keret_felett": round(felett, 3), "a1": round(a1_ft), "d": round(d_ft),
                "kulonbseg": round(d_ft - a1_ft),
                "d_sulyozott": round(qd_ar / felett, 2) if felett else None,
                "d_szamla": round(d_szamla) if d_szamla is not None else None,
                "d_atlag": round(d_atlag, 2) if d_atlag is not None else None,
            },
        }

    def _d_osszevetes(self, fiok: Fiok, tarolt: dict[str, Any], ny: NyitottIdoszak | None, most: datetime) -> dict[str, Any] | None:
        """A1 fióknál: mennyivel kerülne többe/kevesebbe D árszabással. A kedvezményes rész, a rendszerhasználati díj és
        az alapdíj azonos; csak a keret feletti (piaci) mennyiség ára más: rugalmas egységár az A1 piaci ára helyett."""
        if not fiok.d_napok and not fiok.d_ar_napok:
            return None
        hatar = (most - timedelta(days=365)).date()
        idoszakok: list[tuple[date, date, list[tuple[date, date, Decimal]]]] = []
        for x in sorted(tarolt.get("lezart", []), key=lambda x: x["tol"]):
            if date.fromisoformat(x["ig"]) <= hatar:
                continue
            szel = [(date.fromisoformat(s["tol"]), date.fromisoformat(s["ig"]), Decimal(str(s.get("piaci") or 0)))
                    for s in x.get("szeletek", []) if s.get("csatorna", "vetelezes") == "vetelezes"]
            idoszakok.append((date.fromisoformat(x["tol"]), date.fromisoformat(x["ig"]), szel))
        if ny is not None:
            szel = [(s.tol, s.ig, s.piaci) for s in ny.eddig.szeletek if s.csatorna == "vetelezes"]
            idoszakok.append((ny.eddig.tol, ny.eddig.ig, szel))
        sorok = []
        for tol, ig, szel in idoszakok:
            kul = Decimal(0)
            tobblet = Decimal(0)
            becsult = False
            d_arak = []
            for a, b, piaci in szel:
                if piaci <= 0:
                    continue
                d_ar, bec = rugalmas_ar(fiok, a, b)
                if d_ar is None:
                    continue
                e = self.tar.felold(_hozzarendeles(fiok, a), a, fiok.szolgaltato, fiok.feluliras)
                afa = 1 + Decimal(e.dijak.get("afa") or 0) / 100
                kul += piaci * (d_ar - e.dijak["energia_piaci"]) * afa
                tobblet += piaci
                becsult |= bec
                d_arak.append((piaci, d_ar))
            sulyozott = sum((p * a for p, a in d_arak), Decimal(0)) / tobblet if tobblet else None
            sorok.append({
                "tol": tol.isoformat(), "ig": ig.isoformat(), "keret_felett": round(float(tobblet), 1),
                "d_ar": round(float(sulyozott), 2) if sulyozott is not None else None,
                "kulonbseg": int(kul.quantize(Decimal(1))), "becsult": becsult,
            })
        lezart = [s for s in sorok[:-1]] if ny is not None else sorok
        return {
            "idoszakok": sorok,
            "kulonbseg_12ho": sum(s["kulonbseg"] for s in sorok),
            "kulonbseg_lezart": sum(s["kulonbseg"] for s in lezart),
            "folyo": sorok[-1] if ny is not None and sorok else None,
            "arlista_ig": (self.hass.data.get(DOMAIN, {}).get("d_arak").adat.get("utolso_ora") or "")[:10] or None,
            "szamitott_ig": (self.hass.data.get(DOMAIN, {}).get("d_arak").szamitott_ig or "")[:10] or None,
            # Órás fogyasztás nélkül (nincs szenzor) a napi egyszerű átlagár számít, nem a saját fogyasztásod szerinti.
            "oras_adat": bool(fiok.d_napok),
        }

    async def _zona_fiok(self, sub: ConfigSubentry, fiok: Fiok, tol: datetime) -> Fiok:
        """A2 regiszter-szenzorok nélkül: a fogyasztás-szenzor órás statisztikájából naponként a völgy- és az összes
        fogyasztás, hogy a motor órára pontosan bontsa csúcsra és völgyre (lásd motor/zona.py)."""
        forras = sub.data.get(CONF_FORRAS)
        if sub.data.get(CONF_DIJSZABAS) != "villany/a2" or not forras or any(c.szerep.startswith("zona_") for c in fiok.csatornak):
            return fiok
        tz = dt_util.get_default_time_zone()
        stat = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period, self.hass, tol.replace(tzinfo=tz), None, {forras}, "hour", None, {"state"}
        )
        orak: list[tuple[datetime, Decimal]] = []
        elozo: Decimal | None = None
        for r in stat.get(forras, []):
            if r.get("state") is None:
                elozo = None
                continue
            ertek = Decimal(str(r["state"]))
            kezd = dt_util.utc_from_timestamp(r["start"]) if isinstance(r["start"], (int, float)) else r["start"]
            # Az órás sor „state” értéke az óra végén mért állás: a változás az előző órához képest az órára esik.
            if elozo is not None and ertek >= elozo:
                orak.append((dt_util.as_local(kezd).replace(tzinfo=None), ertek - elozo))
            elozo = ertek
        return dataclasses.replace(fiok, zona_napok=napi_zonak(orak))

    ORAS_NAPOK = 3  # ennyi napra az órás statisztika is a sorozatba kerül

    async def _napi_statisztika(self, entity_id: str, kezd: datetime, most: datetime) -> list[dict[str, Any]]:
        """Napi statisztika kezd-től: a ma előtti (lezárt) napok gyorstárból, a mai nap friss lekérdezéssel.

        A „day” sorokat a recorder az órás statisztikából a helyi napokra vonja össze, így a ma éjfélnél kettévágott
        lekérdezés ugyanazt adja, mint az egyben futó. Ha egy lezárt nap utolsó órája a gyorstárazás pillanatában még
        nem volt összesítve, az órás rész (az utolsó napokra) felülírja a nap végi pontot."""
        tz = dt_util.get_default_time_zone()
        hatar = datetime.combine(most.date(), datetime.min.time(), tz)  # ma 0:00 (helyi)
        lekeres = get_instance(self.hass).async_add_executor_job
        if kezd >= hatar:
            return (await lekeres(statistics_during_period, self.hass, kezd, None, {entity_id}, "day", None, {"state"})).get(entity_id, [])
        kulcs = (entity_id, kezd)
        self._napi_stat_kert.add(kulcs)
        tarolt = self._napi_stat.get(kulcs)
        if tarolt is None or tarolt[0] != most.date():
            lezart = (await lekeres(statistics_during_period, self.hass, kezd, hatar, {entity_id}, "day", None, {"state"})).get(entity_id, [])
            tarolt = (most.date(), lezart)
            if lezart:  # üres eredményt nem tárolunk (pl. induláskor): a következő frissítés újra lekéri
                self._napi_stat[kulcs] = tarolt
        mai = await lekeres(statistics_during_period, self.hass, hatar, None, {entity_id}, "day", None, {"state"})
        return [*tarolt[1], *mai.get(entity_id, [])]

    def napi_gyorstar_takaritas(self) -> None:
        """A napi statisztika gyorstárából kikerül, amit az utolsó számolás nem kért (törölt forrás, más kezdet)."""
        self._napi_stat = {k: v for k, v in self._napi_stat.items() if k in self._napi_stat_kert}
        self._napi_stat_kert = set()

    async def _sorozat(
        self, entity_id: str, tol: datetime, most: datetime, napi_gyorstar: bool = False
    ) -> list[tuple[datetime, Decimal]]:
        """A forrás állássorozata: napi statisztika tol-tól, az utolsó napokra órás, végén a mostani érték.

        napi_gyorstar: a lezárt napok napi statisztikája naponta egyszer (szigetüzem: 800 nap, napra kerekített tol)."""
        tz = dt_util.get_default_time_zone()
        kezd = tol.replace(tzinfo=tz)
        if napi_gyorstar:
            napi = await self._napi_statisztika(entity_id, kezd, most)
        else:
            napi = (await get_instance(self.hass).async_add_executor_job(
                statistics_during_period, self.hass, kezd, None, {entity_id}, "day", None, {"state"}
            )).get(entity_id, [])
        # Az utolsó napokra óránként is: a napközben (időponttal) rögzített leolvasásnak legyen közeli szenzorpontja,
        # különben a számláló a nap eleje óta mért fogyasztást még hozzáadná az este leolvasott álláshoz.
        orak_tol = max(kezd, (most - timedelta(days=self.ORAS_NAPOK)).replace(tzinfo=tz))
        oras = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period, self.hass, orak_tol, None, {entity_id}, "hour", None, {"state"}
        )
        pontok: dict[datetime, Decimal] = {}
        for r in [*napi, *oras.get(entity_id, [])]:
            if r.get("state") is None:
                continue
            # A sor „state” értéke az időszak (nap / óra) végén mért állás.
            vege = dt_util.utc_from_timestamp(r["end"]) if isinstance(r["end"], (int, float)) else r["end"]
            pontok[dt_util.as_local(vege).replace(tzinfo=None)] = Decimal(str(r["state"]))
        sor: list[tuple[datetime, Decimal]] = sorted(pontok.items())
        allapot = self.hass.states.get(entity_id)
        ertek = szenzor_ertek(allapot.state) if allapot is not None else None
        if ertek is not None:
            sor.append((most, ertek))
        else:
            # Induláskor a forrás még nem kész (vagy „nan”/„inf”, ami nem mérőállás): hamarosan újraszámolunk.
            self._forras_hianyzik = True
            self._hianyzo_forrasok.add(entity_id)
        return sor

    async def _async_update_data(self) -> dict[str, FiokAllapot]:
        # Egyszerre egy számolás: a háttérben induló első számolás és a HA elindulása utáni (számlamappás)
        # frissítés különben ugyanazt a tárolt adatot módosítaná.
        async with self._zar:
            return await self._szamol()

    async def _szamol(self) -> dict[str, FiokAllapot]:
        most = helyi_most()
        self._forras_hianyzik = False
        self._hianyzo_forrasok = set()
        self._ujraszamol_kert = False
        kimenet: dict[str, FiokAllapot] = {}
        valtozott = False
        self._kredit_maradek: dict[tuple[str, ...], Decimal] = {}  # a folyószámla túlfizetése (közös csoportonként) ebben a körben
        for sid, sub in self.fiokok().items():
            tarolt = self.tarolo.fiok(sid)
            egyseg = EGYSEG[sub.data[CONF_KOZMU]]
            valtozott |= mero_szinkron(tarolt, dict(sub.data)) if tarolt["merok"] else False
            if not tarolt["merok"] or tarolt.get("kezdes_ujra"):
                kesz = await self._kezdes(sub, tarolt, most)
                valtozott |= kesz
                if not tarolt["merok"]:
                    # A szenzor még nem adott értéket: a fiók addig nem számolható (később újra próbáljuk).
                    self._forras_hianyzik = True
                    if sub.data.get(CONF_FORRAS):
                        self._hianyzo_forrasok.add(sub.data[CONF_FORRAS])
                    kimenet[sid] = FiokAllapot(egyseg=egyseg, hiba="várakozás a mérőállás-szenzor első értékére")
                    continue
                valtozott |= mero_szinkron(tarolt, dict(sub.data))
            valtozott |= await self._kezdes_ujrabazis(sub, tarolt, most)
            valtozott |= kezdo_origo_szinkron(tarolt, dict(sub.data))
            if sub.data.get(CONF_ALMERO) and not tarolt.get("almero_merok"):
                tarolt["almero_merok"] = [kezdo_almero(dict(sub.data), tarolt["merok"][0]["beepitve"])]
                valtozott = True
            if sub.data.get(CONF_SZAMLA_MAPPA) and not self.mappa_halasztva:
                try:
                    valtozott |= await self._szamlak_feldolgozasa(sid, sub, tarolt)
                except Exception as err:  # noqa: BLE001 – a számlamappa hibája ne állítsa meg a számolást
                    _LOGGER.warning("%s: számlamappa hiba: %s", sub.title, err)
            try:
                allapot, lezart = await self._fiok(sid, sub, tarolt, most, egyseg)
                valtozott |= lezart
            except (NincsAdat, DijszabasHiba, KeyError, ValueError) as err:
                _LOGGER.warning("%s: nem számolható: %s", sub.title, err)
                allapot = FiokAllapot(egyseg=egyseg, hiba=str(err))
            except Exception as err:  # noqa: BLE001 – egy hibás fiók ne vigye magával a többit (és a mentést)
                kulcs = (sid, f"{type(err).__name__}: {err}")
                if kulcs not in self._naplozott_hibak:
                    self._naplozott_hibak.add(kulcs)
                    _LOGGER.exception("%s: váratlan hiba, a fiók nem számolható", sub.title)
                else:
                    _LOGGER.debug("%s: nem számolható (ismétlődő hiba): %s", sub.title, kulcs[1])
                allapot = FiokAllapot(egyseg=egyseg, hiba=kulcs[1])
            kimenet[sid] = allapot
            try:
                await self._ellenorzes(sid, tarolt)
            except Exception:  # noqa: BLE001 – az ellenőrzés hibája ne állítsa meg a számolást
                _LOGGER.exception("%s: a számla-ellenőrzés nem sikerült", sub.title)
            if tarolt.get("fuggo"):
                try:
                    await self._fuggo_elonezet(sid, sub, tarolt, most, egyseg, allapot)
                except Exception:  # noqa: BLE001 – az előnézet hibája ne állítsa meg a számolást
                    _LOGGER.exception("%s: a függő számla előnézete nem számolható", sub.title)
            else:
                self.elonezet.pop(sid, None)
            if tol_ujra := tarolt.pop("lezart_ujra", None):
                # A fiók kezdőnapját/kezdőállását módosították: a lezárt időszakok a frissítés után újraszámolódnak.
                valtozott = True

                async def ujra(sid: str = sid, tol: str = tol_ujra) -> None:
                    try:
                        await self.lezartak_ujraszamolasa(sid, date.fromisoformat(tol))
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("A lezárt időszakok újraszámolása nem sikerült (%s)", sid)

                self.config_entry.async_create_background_task(self.hass, ujra(), f"hu_rezsi lezárt újraszámolás {sid}")
        # Ki nem számlázott várt számlák automatikus rendezése, ha egy későbbi számla (közös folyószámlán a társfiókoké
        # is) valószínűleg elszámolta; a változás után még egy számolás (a rendezett tétel kimarad).
        try:
            haztartas = {s: (sub.title, self.tarolo.fiok(s).get("szamlak") or {}) for s, sub in self.fiokok().items()}
            rendezve = automatikus_rendezes(
                {s: (self.tarolo.fiok(s), a.esedekes, a.uton_szamlak) for s, a in kimenet.items() if not a.hiba},
                {s: folyoszamla_.kozos_csoport(s, haztartas) for s in haztartas}, most.isoformat(timespec="seconds"))
        except Exception:  # noqa: BLE001 – az automatikus rendezés hibája ne állítsa meg a számolást
            _LOGGER.exception("A várt számlák automatikus rendezése nem sikerült")
            rendezve = []
        for s, fajta, bej in rendezve:
            _LOGGER.info("%s: %s automatikusan rendezve – egy későbbi számla (%s) elszámolta", self.fiokok()[s].title,
                         f"a {bej['tol']} – {bej['ig']} úton lévő számla" if fajta == "uton" else f"a {bej['kovetkezo_datum']} körül várt számla",
                         bej["sorszam"])
        if rendezve:
            valtozott = True
            self._hatter_frissites()
        for sid in set(self.tarolo.adat["fiokok"]) - set(self.fiokok()):
            self.tarolo.torol_fiok(sid)  # törölt fiók adatai
            valtozott = True
        # Szigetüzemi rendszerek (kísérleti): külön, a fiókoktól függetlenül; hibájuk a fiókokat nem érinti.
        self.sziget_allapot = await sziget_ha.szamol_mind(self, most)
        if valtozott:
            await self.tarolo.ment()
        # Pénzügyi teljesítés: a Díjnet-integráció kifizetett számlái (a fájlok gyorsítótárazva, csak változáskor olvasva).
        try:
            self.dijnet_fizetett = await self.hass.async_add_executor_job(dijnet.fizetett, Path(self.hass.config.config_dir), DIJNET_MINTA)
        except OSError as err:
            _LOGGER.debug("Díjnet-fizetések nem olvashatók: %s", err)
        except Exception as err:  # noqa: BLE001 – egy hibás Díjnet-YAML ne állítsa meg a frissítést
            _LOGGER.warning("Díjnet-fizetések nem olvashatók (hibás fájl?): %s", err)
        self.dijnet_kesz = True
        self.mappa_halasztva = False
        self._forras_probak = self._forras_probak + 1 if self._forras_hianyzik else 0
        self.update_interval = timedelta(minutes=frissitesi_perc(self._forras_hianyzik, self._forras_probak, FRISSITES_PERC))
        self._hianyzo_forras_jelzes()
        return kimenet

    def _hianyzo_forras_jelzes(self) -> None:
        """Ha a percenkénti újrapróbák után is hiányzik egy forrás-szenzor: javítandó probléma (Beállítások → Javítások)
        a hiányzó entitás(ok) nevével; amint mind megvan, a jelzés magától eltűnik."""
        issue_id = f"hianyzo_forras_{self.config_entry.entry_id}"
        if self._forras_hianyzik and self._forras_probak > FORRAS_PROBAK:
            if self._forras_probak == FORRAS_PROBAK + 1:
                _LOGGER.warning(
                    "A forrás-szenzor(ok) %d próbálkozás után is hiányoznak, ezentúl %d percenként próbáljuk: %s",
                    FORRAS_PROBAK, FRISSITES_PERC, ", ".join(sorted(self._hianyzo_forrasok)) or "?",
                )
            ir.async_create_issue(
                self.hass, DOMAIN, issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                translation_key="hianyzo_forras",
                translation_placeholders={"entitasok": ", ".join(sorted(self._hianyzo_forrasok)) or "?"},
            )
        elif not self._forras_hianyzik:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def _kezdes(self, sub: ConfigSubentry, tarolt: dict[str, Any], most: datetime) -> bool:
        """Az első mérő kezdőpontja, ha a kezdőállás nincs megadva: HA-statisztika → mostani érték (lásd kezdopont)."""
        adat = dict(sub.data)
        forras = adat.get(CONF_FORRAS)
        szorzo = Decimal(str(adat.get(CONF_SZORZO) or 1))
        mod, nap = beallitas.idoszak_mod(adat)
        dhatarok = diktalasi_hatarok(tarolt, mod == "leolvasas") if mod in DIKT_MODOK else None
        dablak = diktalasi_ablak(tarolt, sub.data) if mod in DIKT_MODOK else None
        cel = d(adat.get(CONF_BEEPITVE)) or idoszak(most.date(), mod, nap, dhatarok, dablak)[0]
        stat_ertek = aktualis = None
        reszleges = False
        if forras and adat.get(CONF_KEZDO_ALLAS) in (None, ""):
            t = nap_kezdete(cel)
            sor = [(ti, v) for ti, v in await self._sorozat(forras, t - timedelta(days=2), most) if ti < most]
            elotte = [v for ti, v in sor if ti <= t and t - ti <= timedelta(hours=36)]
            stat_ertek = elotte[-1] * szorzo if elotte else None
            if stat_ertek is None:
                # A szenzor előzménye a kezdőnap után indul: a legkorábbi napi statisztikától (nem a mostani értéktől).
                utana = [(ti, v) for ti, v in sor if ti > t]
                if utana:
                    cel, stat_ertek = utana[0][0].date(), utana[0][1] * szorzo
                    reszleges = True
            allapot = self.hass.states.get(forras)
            ertek = szenzor_ertek(allapot.state) if allapot else None
            aktualis = ertek * szorzo if ertek is not None else None
        kp = kezdopont(adat, cel, stat_ertek, aktualis, most.date())
        if kp is None:
            return False
        beepitve, kezdo, forras_mod = kp
        if forras_mod == "statisztika" and reszleges:
            forras_mod = "reszleges"  # a követés a szenzor legkorábbi statisztikájától indul (panelüzenet)
        if tarolt["merok"]:  # a kezdőállást utólag ürítették ki: az egyetlen mérőt állítjuk át
            if len(tarolt["merok"]) == 1:
                tarolt["merok"][0]["beepitve"], tarolt["merok"][0]["kezdo_allas"] = str(beepitve), str(kezdo)
        else:
            tarolt["merok"].append(kezdo_mero(adat, beepitve, kezdo))
        tarolt.pop("kezdes_ujra", None)
        szamlalo_forras = adat.get(CONF_FORRAS_TIPUS, "meroallas") != "meroallas"
        tarolt["kezdes"] = {
            "mod": forras_mod, "datum": beepitve.isoformat(), "ido": most.isoformat() if forras_mod == "aktualis" else None,
            # Számláló-szenzornál a kezdőállás a szenzor értéke, nem óraállás: az első valódi leolvasás igazítja.
            "szenzor_alap": szamlalo_forras and forras_mod in ("statisztika", "reszleges", "aktualis"),
        }
        _LOGGER.info("%s: kezdőpont %s, %s (%s)", sub.title, beepitve, kezdo, forras_mod)
        return True

    async def _kezdes_ujrabazis(self, sub: ConfigSubentry, tarolt: dict[str, Any], most: datetime) -> bool:
        """Számláló-szenzoros automatikus kezdésnél az első valódi leolvasás óraállásra igazítja a kezdőállást."""
        k = tarolt.get("kezdes") or {}
        if not k.get("szenzor_alap") or len(tarolt["merok"]) != 1:
            return False
        m = tarolt["merok"][0]
        valodi = sorted((lo for lo in m.get("leolvasasok", []) if lo.get("tipus") != "automatikus"), key=lambda x: x["datum"])
        forras = sub.data.get(CONF_FORRAS)
        if not valodi or not forras:
            return False
        lo = valodi[0]
        t = nap_kezdete(d(lo["datum"]))
        szorzo = Decimal(str(sub.data.get(CONF_SZORZO) or 1))
        sor = await self._sorozat(forras, t - timedelta(days=2), max(t + timedelta(hours=1), most))
        elotte = [v for ti, v in sor if ti <= t + timedelta(hours=12)]
        if not elotte:
            return False
        # óra(t) = kezdő óraállás + (szenzor(t) − szenzor a kezdéskor) × szorzó  →  új kezdő óraállás
        uj = Decimal(str(lo["allas"])) - (elotte[-1] * szorzo - Decimal(str(m["kezdo_allas"])))
        m["kezdo_allas"] = str(uj)
        k["szenzor_alap"] = False
        k["igazitva"] = lo["datum"]
        _LOGGER.info("%s: a kezdőállás a %s-i leolvasáshoz igazítva: %s", sub.title, lo["datum"], uj)
        return True

    async def havi_osszevetes(self, sid: str, evek: int = 3) -> list[dict[str, Any]]:
        """Naptári havi fogyasztás és költség az utolsó `evek` naptári évre (éves összevetéshez).

        A mennyiség a számlálóból jön (szenzor + leolvasások, hézagban arányosítva), a költség a motor havi
        elszámolásából – ugyanazzal a díjszabással és összesített kerettel, mint a lezárt időszakok."""
        sub = self.fiokok()[sid]
        tarolt = self.tarolo.fiok(sid)
        fiok = self._otthon_bazissal(sub, fiok_motorba(dict(sub.data), tarolt))
        most = helyi_most()
        elso = min((m.beepitve for cs in fiok.csatornak for m in cs.merok if m.beepitve), default=most.date())
        kezd = max(date(most.year - evek + 1, 1, 1), elso.replace(day=1))
        fiok = await self._zona_fiok(sub, fiok, nap_kezdete(kezd))
        fiok = await self._d_fiok(sid, sub, fiok, most)
        szamlalok = [await self.szamlalo(sid, fiok, nap_kezdete(kezd), most, i) for i in range(len(fiok.csatornak))]
        # Napelemes fiók: a betáplálás (2.8.0) is, havonta – a nettó (vételezés − betáplálás) az összevetéshez.
        betap = None
        if sub.data.get(CONF_NAPELEM, "nincs") in ("brutto", "szaldo"):
            try:
                betap = await self._betap_szamlalo(sub, tarolt, fiok, kezd, most)
            except (NincsAdat, ValueError, KeyError) as err:
                _LOGGER.debug("%s: betáplálás nem olvasható: %s", sub.title, err)
        hatarok = elszamolasi_napok(tarolt)
        kitoltott: list[tuple[datetime, datetime]] = []
        napi: dict[date, Decimal] = {}
        if profil := sub.data.get(CONF_PROFIL_FORRAS):
            # Ritka leolvasásnál a hézagokat a profil-szenzor (pl. kazán becsült gáza) alakja szerint osztjuk el.
            napi = napi_valtozas(await self._sorozat(profil, nap_kezdete(kezd) - timedelta(days=1), most))
            szamlalok[0], kitoltott = profillal(szamlalok[0], napi)
        ki: list[dict[str, Any]] = []
        h = kezd
        while h <= most.date():
            kov = (h + timedelta(days=32)).replace(day=1)
            tol = max(h, elso)
            vege = min(nap_kezdete(kov), most)
            sor: dict[str, Any] = {"honap": h.isoformat()[:7], "mennyiseg": None, "ft": None, "becsult": False,
                                   "reszleges": kov > most.date() or tol > h}
            try:
                menny, becsult = Decimal(0), False
                for sz, cs in zip(szamlalok, fiok.csatornak, strict=True):
                    if cs.szerep == "almero":
                        continue
                    m, b = sz.fogyasztas(nap_kezdete(tol), vege)
                    menny += m
                    becsult = becsult or b
                # „Profil szerint” csak az a hónap, amelynek legalább a felére van profil-adat; a többi a hézagban
                # csak az egyenletes alapot kapta, az becsült marad.
                lefedett = sum(1 for i in range((kov - tol).days) if tol + timedelta(days=i) in napi)
                profilos = 2 * lefedett >= (kov - tol).days and any(a < nap_kezdete(kov) and b > nap_kezdete(tol) for a, b in kitoltott)
                hezagban = any(a < nap_kezdete(kov) and b > nap_kezdete(tol) for a, b in kitoltott)
                sor["mennyiseg"], sor["becsult"], sor["profil"] = float(round(menny, 2)), becsult or hezagban, profilos
                if betap is not None and betap.pontok and betap.pontok[0].ido <= nap_kezdete(tol):
                    q_be, b_be = betap.fogyasztas(nap_kezdete(tol), vege)
                    sor["betaplalas"] = float(round(max(q_be, Decimal(0)), 2))
                    sor["netto"] = float(round(menny - max(q_be, Decimal(0)), 2))
                    sor["betap_becsult"] = b_be
                # A folyamatban lévő hónap csak máig (a keret és az alapdíj is csak az eltelt napokra), különben
                # egy-két nap fogyasztására a teljes havi keret és a sávkorrekció jutna.
                ig = min(kov, most.date() + timedelta(days=1))
                e = szamol(fiok, self.tar, tol, ig, szamlalok, meres_vege=most if ig > most.date() else None, extra_hatarok=hatarok)
                sor["ft"] = int(e.osszesen_ft)
            except (NincsAdat, DijszabasHiba, ValueError) as err:
                _LOGGER.debug("%s: %s hónap nem számolható: %s", sub.title, h, err)
            ki.append(sor)
            h = kov
        return ki

    async def _fiok(
        self, sid: str, sub: ConfigSubentry, tarolt: dict[str, Any], most: datetime, egyseg: str
    ) -> tuple[FiokAllapot, bool]:
        fiok = self._otthon_bazissal(sub, fiok_motorba(dict(sub.data), tarolt))
        mod, nap = beallitas.idoszak_mod(sub.data)
        dhatarok = diktalasi_hatarok(tarolt, mod == "leolvasas") if mod in DIKT_MODOK else None
        dablak = diktalasi_ablak(tarolt, sub.data) if mod in DIKT_MODOK else None
        # Lezárt (megszüntetett) fiók: a lezárás napján megáll – az utolsó időszak ott zárul, előrejelzés nincs.
        veg = d((tarolt.get("megszunt") or {}).get("datum"))
        if veg and veg <= most.date():
            most = datetime.combine(veg, datetime.min.time())
            tol, _ = idoszak(veg - timedelta(days=1), mod, nap, dhatarok, dablak)
            ig = veg
        else:
            veg = None
            tol, ig = idoszak(most.date(), mod, nap, dhatarok, dablak)
        # Víz, több havonta számlázva: a folyó időszak (fogyasztás eddig, várható, átalány) a számlázási időszak – a havi
        # lezárás (előzmény) marad naptári havi. Diktálás után a diktálás szerinti időszak lép helyébe (lent).
        szamlazasi_ip = None
        if (not veg and sub.data.get(CONF_KOZMU) == "viz" and not beallitas.fix_dijas(sub.data)
                and int(sub.data.get(CONF_SZAMLAZAS_HONAP) or 0) > 1):
            szamlazasi_ip = _tobbhavi_folyo_idoszak(tarolt, int(sub.data[CONF_SZAMLAZAS_HONAP]), most.date())
        elozmeny = datetime.combine(min(tol, szamlazasi_ip[0]) if szamlazasi_ip else tol, datetime.min.time()) - timedelta(days=ELOZMENY_NAPOK)
        fiok = await self._zona_fiok(sub, fiok, min(elozmeny, datetime.combine(fiok.eves_bazis or tol, datetime.min.time())))
        fiok = await self._d_fiok(sid, sub, fiok, most)
        if sub.data.get(CONF_DIJSZABAS) in D_DIJSZABASOK and (forras := sub.data.get(CONF_FORRAS)):
            try:
                await self.negyedek_frissit(sid, forras, most)
            except Exception:  # noqa: BLE001 – a D-elemzés adata ne akassza meg a számolást
                _LOGGER.exception("%s: a negyedórás fogyasztás mentése nem sikerült", sub.title)
        # Csatornánként saját számláló (fő; H-tarifánál téli és nyári regiszter; víznél almérő).
        szamlalok = [await self.szamlalo(sid, fiok, elozmeny, most, i) for i in range(len(fiok.csatornak))]
        szamlalo, tovabbi = szamlalok[0], szamlalok[1:]
        self.utolso_szamlalok[sid] = szamlalo.pontok[-15:]
        hatarok = elszamolasi_napok(tarolt)

        # Lezárás: ha a tárolt nyitott időszak már véget ért (és eltelt a késleltetés).
        lezart_valt = False
        if mod == "leolvasas":
            # Tiszta diktálás: a lezárt időszakok mindig két egymást követő leolvasás között – minden frissítéskor
            # összevetjük a leolvasásokkal (új, utólag rögzített vagy törölt állás után is rendbe jön).
            lezart_valt = await self._leolvasasos_lezartak(sid, fiok, tarolt, dhatarok or [], veg or tol, most, hatarok)
        nyitott_tol = d(tarolt.get("nyitott_tol"))
        if nyitott_tol is None:
            tarolt["nyitott_tol"] = tol.isoformat()
            lezart_valt = True
        elif nyitott_tol < tol and most >= datetime.combine(tol, datetime.min.time()) + timedelta(hours=LEZARAS_KESLELTETES_ORA):
            ptol = nyitott_tol
            while ptol < tol:
                _, pig = idoszak(ptol, mod, nap, dhatarok, dablak)
                try:
                    e = szamol(fiok, self.tar, ptol, pig, szamlalok, extra_hatarok=hatarok)
                    bejegyzes = eredmeny_tarolhato(e) | {"rogzitve": most.isoformat(), "forras": "automatikus"}
                    tarolt["lezart"] = [x for x in tarolt["lezart"] if x["tol"] != bejegyzes["tol"]] + [bejegyzes]
                except NincsAdat as err:
                    _LOGGER.warning("%s: a %s időszak nem zárható le: %s", sub.title, ptol, err)
                ptol = pig
            tarolt["nyitott_tol"] = tol.isoformat()
            lezart_valt = True

        if szamlazasi_ip:
            tol, ig = szamlazasi_ip
        ny = nyitott(fiok, self.tar, tol, ig, szamlalok, most, extra_hatarok=hatarok)
        ny = self._viz_potlek(sub, fiok, ny, tol, ig, most)
        keret_ev = self._gaz_eves_keret(sub, fiok, szamlalo, most)
        eves = None
        if fiok.eves_bazis:
            try:
                bazis = datetime.combine(fiok.eves_bazis, datetime.min.time())
                eves = sum(
                    (sz.fogyasztas(bazis, most)[0] for sz, cs in zip(szamlalok, fiok.csatornak, strict=True) if cs.szerep != "almero"),
                    Decimal(0),
                )
            except NincsAdat:
                eves = None
        if veg and mod != "leolvasas":
            # Végelszámolás: az utolsó (töredék) időszak a lezárás napjáig, lezárt időszakként.
            try:
                e = szamol(fiok, self.tar, tol, veg, szamlalok, extra_hatarok=hatarok)
                bej = eredmeny_tarolhato(e) | {"rogzitve": helyi_most().isoformat(), "forras": "végelszámolás"}
                regi = next((x for x in tarolt["lezart"] if x["tol"] == bej["tol"]), None)
                if not regi or (regi["ig"], regi["osszesen_ft"], regi.get("forras")) != (bej["ig"], bej["osszesen_ft"], "végelszámolás"):
                    tarolt["lezart"] = [x for x in tarolt["lezart"] if x["tol"] != bej["tol"]] + [bej]
                    lezart_valt = True
            except (NincsAdat, DijszabasHiba) as err:
                _LOGGER.warning("%s: a végelszámolás időszaka nem számolható: %s", sub.title, err)
        if veg and tarolt.get("nyitott_tol") != veg.isoformat():
            tarolt["nyitott_tol"] = veg.isoformat()
            lezart_valt = True
        lezartak = sorted(tarolt["lezart"], key=lambda x: x["tol"])
        uton = _uton_szamlak(sub, tarolt, lezartak, most.date())
        if uton and szamlazasi_ip:
            # Több havonta számlázva: a folyó számlázási időszak havi lezárásai nem „úton” – a folyó időszakban számítanak.
            uton = [x for x in uton if x["tol"] < szamlazasi_ip[0].isoformat()] or None
        if uton and kezi_idoszak_potlas(tarolt, uton):
            # Időszak nélküli kézi számla: az úton lévő időszakot fedi le (különben a számla tovább „várható” maradna).
            uton = _uton_szamlak(sub, tarolt, lezartak, most.date())
            if uton and szamlazasi_ip:
                uton = [x for x in uton if x["tol"] < szamlazasi_ip[0].isoformat()] or None
            lezart_valt = True
        napelem_e, napelem_hiba, betap_sz = None, None, None
        mod = sub.data.get(CONF_NAPELEM, "nincs")
        if mod in ("brutto", "szaldo"):
            try:
                betap_sz = await self._betap_szamlalo(sub, tarolt, fiok, tol, most)
                napelem_e = self._napelem(fiok, szamlalo, betap_sz, tol, ig, most, mod)
            except (NincsAdat, ValueError, DijszabasHiba, KeyError) as err:
                napelem_hiba = str(err)
        # Szaldónál az éves elszámolás a vételezés és a betáplálás különbözetén megy: az egyenleg, a „ha ma lenne”
        # és a kedvezményes keret is ebből (a havi vételezés nem számlázódik külön).
        szaldo_betap = betap_sz if mod == "szaldo" and napelem_e is not None else None
        self.mero_allasok[sid] = self._mero_allasok(sid, sub, fiok, szamlalok, betap_sz, betaplalas_csatorna(tarolt), most)
        if szaldo_betap is not None and sub.data.get(CONF_KERET_AKTIV, True):
            keret_ev = self._szaldo_keret(fiok, napelem_e, most) or keret_ev
        elszamolas = None
        if beallitas.fix_dijas(sub.data):
            pass  # fix díjnál nincs mért fogyasztás, így elszámolás sem
        else:
            try:
                elszamolas = await self._varhato_elszamolas(sub, tarolt, fiok, szamlalo, most, tovabbi, szaldo_betap)
            except (NincsAdat, ValueError, DijszabasHiba) as err:
                _LOGGER.debug("%s: várható elszámolás nem számolható: %s", sub.title, err)
        atalany_e = None
        if beallitas.reszszamlas(sub.data):
            if atalany_mennyiseg(sub.data, tarolt):
                atalany_e = self._mennyisegi_atalany(sub, fiok, tol, ig, most, szamlalok, tarolt)
            else:
                atalany_e = atalany_szamitas(sub.data.get(CONF_RESZSZAMLA_OSSZEG), tarolt, tol, ig, most)
        if szaldo_betap is not None and atalany_e and atalany_e.get("mennyiseg_idoszak") is not None:
            # Szaldónál az átalány (MVM: a nettó fogyasztás havi része) a nettóval vethető össze, nem a vételezéssel.
            atalany_e["betaplalas"] = napelem.idoszak_betaplalas(szaldo_betap, tol, ig, most)
        periodus = int(sub.data.get(CONF_SZAMLAZAS_HONAP) or 0) or None
        tavleolv = beallitas.elszamolas_mod(sub.data) == "tavleolvasas"
        # Átalánynál a számla az átalány szerint jön – de ha a legutóbbi számla után diktáltunk, a diktált állás
        # felülírja az átalány mennyiségét: a következő számla a diktált fogyasztás díja.
        diktalt_e = self._diktalt_szamla(fiok, tarolt, szamlalok) if atalany_e else None
        dny = None
        if atalany_e and not diktalt_e:
            diktalt_e, dny = self._becsult_diktalt_szamla(fiok, tarolt, szamlalok, most, int(sub.data.get(CONF_SZAMLAZAS_HONAP) or 0) or None)
        if atalany_e and not diktalt_e and not veg and (kozos_ip := self._kozos_szamlazasi_idoszak(sid, tarolt)):
            # MVM közös folyószámla: egy ügyfél áramfiókjait együtt számlázzák – ha a társfiók diktálás szerint számláz,
            # ez is, azonos időszakkal (pl. a H-tarifa az A1-gyel: a 10.09-i leolvasás után 10.10-től a következő
            # diktálásig). A társfiók későbbi számlája az előző időszakot is elszámolta (automatikus rendezés).
            try:
                dny = nyitott(fiok, self.tar, kozos_ip[0], kozos_ip[1] + timedelta(days=1), szamlalok, most, extra_hatarok=hatarok)
                diktalt_e = {"datum": kozos_ip[1].isoformat(), "allas": None, "tol": kozos_ip[0].isoformat(), "becsult": True,
                             "kozos": True, "mennyiseg": round(float(dny.varhato.mennyiseg), 1), "osszeg": int(dny.varhato.osszesen_ft)}
            except (NincsAdat, DijszabasHiba, ValueError) as err:
                _LOGGER.debug("%s: a közös számlázási időszak nem számolható: %s", sub.title, err)
                dny = None
        # Átalányos, de diktálás szerint számlázott fiók: minden hónapot elszámoló számla zár, átalányt nem számláznak.
        # A kártya ezért a mért diktálásos fiókét mutatja: a folyó időszak a legutóbbi számla (ill. diktálás) utántól a
        # következő diktálásig; a diktált, még nem számlázott időszak „még nem érkezett számla”; éves egyenleg és „ha
        # ma lenne az elszámolás” nincs (minden hónap ki van egyenlítve).
        diktalas_szerint = False
        if diktalt_e and not veg:
            if diktalt_e.get("becsult"):
                ip = (d(diktalt_e["tol"]), d(diktalt_e["datum"]))
            else:
                ip = kovetkezo_szamla_idoszak(d(diktalt_e["datum"]), most.date(), diktalasi_ablak(tarolt, sub.data), periodus or 1)
                dny = None
                if ip:
                    try:
                        dny = nyitott(fiok, self.tar, ip[0], ip[1] + timedelta(days=1), szamlalok, most, extra_hatarok=hatarok)
                    except (NincsAdat, DijszabasHiba, ValueError) as err:
                        _LOGGER.debug("%s: a diktálás utáni időszak nem számolható: %s", sub.title, err)
            if ip and dny is not None:
                tol, ig, ny = ip[0] - timedelta(days=1), ip[1], dny
                diktalas_szerint = True
                if not diktalt_e.get("kozos"):
                    self._kozos_ip[sid] = ip  # a közös folyószámla társfiókjainak (ugyanaz a számlázási időszak)
                elszamolas = None
                if not diktalt_e.get("becsult") and diktalt_e["tol"] not in {x.get("tol") for x in tarolt.get("rendezett_uton") or []}:
                    uton = [*(uton or []), {"tol": diktalt_e["tol"], "ig": diktalt_e["datum"],
                                            "osszeg": diktalt_e["osszeg"], "mennyiseg": diktalt_e["mennyiseg"]}]
        if not diktalas_szerint or (diktalt_e or {}).get("kozos"):
            self._kozos_ip.pop(sid, None)
        szamla_allasok = self._szamla_alapu_allasok(tarolt, most) if atalany_e else None
        ciklus, leolvasas = self._ciklus(sub, tarolt, fiok)
        diktalas = kovetkezo_idopont(tarolt, "kovetkezo_diktalas")
        if (periodus or 0) > 1 and (diktalas is None or diktalas[1] < most.date()):
            # Több havonta számlázó szolgáltató: a következő diktálás a díjszabás szabálya szerint (az időszak vége
            # utáni vagy a záró hónapban); a napokat a fiók / a számla ablaka, ennek híján a díjszabás adja.
            try:
                szab = self.tar.felold(_hozzarendeles(fiok, most.date()), most.date(), fiok.szolgaltato, fiok.feluliras).szabalyok.get("diktalas") or {}
            except DijszabasHiba:
                szab = {}
            ablak_ = diktalasi_ablak(tarolt, sub.data) or (tuple(szab["ablak"]) if szab.get("ablak") else None)
            vegek = [x["idoszak"][1] for x in (tarolt.get("szamlak") or {}).values() if x.get("idoszak") and x["idoszak"][1]]
            if szab.get("honap") and ablak_ and vegek:
                diktalas = utem_szerinti_diktalas(d(max(vegek)), periodus, ablak_, most.date(), szab["honap"])
        # A következő számla várható összege: fix díjnál a díj × ütem, átalánynál a napi átalány × az ütem napjai.
        varhato_szamla = None
        if beallitas.fix_dijas(sub.data):
            varhato_szamla = havi_alapdij_honapokra(fiok, self.tar, most.date(), periodus or 3)
        elif diktalt_e:
            varhato_szamla = Decimal(diktalt_e["osszeg"])
        elif atalany_e:
            varhato_szamla = Decimal(str(atalany_e["napi"])) * Decimal(round((periodus or 1) * 365 / 12))
        elif ny is not None and not beallitas.reszszamlas(sub.data):
            # Mért fióknál a következő számla a folyó (még nem számlázott) időszak díja a saját mérésből, a végéig
            # előrevetítve – nem a legutóbbi számla összege.
            varhato_szamla = Decimal(ny.varhato.osszesen_ft)
        esedekes_ma, szamlazasi_most = most.date(), most
        if veg:
            # Lezárt fiók: a hátralévő számlák a szokásos ütem szerint, utólag jönnek – a mai nap szerint.
            esedekes_ma, szamlazasi_most = helyi_most().date(), helyi_most()
        esedekes_e = esedekes(tarolt, esedekes_ma, periodus, varhato_szamla,
                              self._kozos_utolso_kelte(sid) if (diktalt_e or {}).get("kozos") else None)
        if uton and esedekes_e and not beallitas.reszszamlas(sub.data) and not beallitas.fix_dijas(sub.data) and not veg:
            # Mért fióknál a lezárt, még nem számlázott időszak a következő számla (az ütem szerinti napon); a folyó
            # időszaké az azutáni. A becsült összeg a „még nem érkezett” sorban számít (nem duplán).
            esedekes_e["kovetkezo_osszeg"] = sum(x["osszeg"] for x in uton)
            esedekes_e["e_havi_osszesen"] -= esedekes_e["e_havi_varhato"]
            esedekes_e["e_havi_varhato"] = 0
            esedekes_e["uton"] = True
        if veg and esedekes_e:
            fix = beallitas.fix_dijas(sub.data)
            # A végszámla az, amelyik a lezárás (utolsó, töredék) időszakát is elszámolja; ha ez megjött, nincs több.
            kihagy = _ervenytelenek(tarolt.get("szamlak") or {})
            megjott = any(
                x.get("idoszak") and d(x["idoszak"][1]) >= tol
                for k, x in (tarolt.get("szamlak") or {}).items() if k not in kihagy
            )
            if fix and not megjott and ny is not None:
                # Utólagos számlázás: a végszámla az első, amelyik már a lezárás időszakáról szól – a töredék díjjal.
                p = esedekes_e["periodus_honap"]
                k = esedekes_e["kovetkezo_datum"]
                while k.replace(day=1) <= tol:
                    k = honap_mulva(k, p)
                if esedekes_e["kovetkezo_datum"] == k:
                    esedekes_e = esedekes(tarolt, esedekes_ma, periodus, Decimal(ny.eddig.osszesen_ft))
                esedekes_e["vegszamla"] = {"datum": k, "osszeg": int(ny.eddig.osszesen_ft)}
            # Mért fióknál a végszámlát a „még nem érkezett számla” sor jelzi, fix díjnál ez az esedékesség.
            if megjott or not fix:
                esedekes_e |= {"e_havi_varhato": 0, "e_havi_osszesen": esedekes_e["e_havi_kiallitott"],
                               "kovetkezo_osszeg": 0, "elmaradt": False, "nincs_tobb": True}
        szunetel_e = None
        if sub.data.get(CONF_SZUNETEL_TOL):
            szunetel_e = {"tol": sub.data[CONF_SZUNETEL_TOL], "ig": sub.data.get(CONF_SZUNETEL_IG),
                          "most": fiok.szunetel_nap(most.date())}
            if szunetel_e["most"] and esedekes_e:
                # Szünetel: számla nem várható, „elmaradt számla” sincs.
                esedekes_e |= {"e_havi_varhato": 0, "e_havi_osszesen": esedekes_e["e_havi_kiallitott"],
                               "kovetkezo_osszeg": 0, "elmaradt": False, "nincs_tobb": True, "szunetel": True}
            if szunetel_e["most"]:
                atalany_e = None  # részszámla sem jön
        szamlazasi_e = None if (esedekes_e or {}).get("nincs_tobb") else await self._szamlazasi(
            sid, fiok, ny, atalany_e, esedekes_e, periodus or (esedekes_e or {}).get("periodus_honap"), szamlazasi_most,
            fix=beallitas.fix_dijas(sub.data),
        )
        if szamlazasi_e and diktalt_e and not szamlazasi_e.get("kiallitott"):
            szamlazasi_e["fizetendo"] = diktalt_e["osszeg"]
            szamlazasi_e["diktalt"] = True
        utem = {
            "szolgaltato": (self.tar.szolgaltatok.get(sub.data.get(CONF_SZOLGALTATO)) or {}).get("nev") or sub.data.get(CONF_SZOLGALTATO),
            "szamlazas_honap": periodus or (esedekes_e or {}).get("periodus_honap"),
            "elszamolas_honap": ciklus,
            "kovetkezo_elszamolas": (
                leolvasas if leolvasas and leolvasas >= most.date() - timedelta(days=31)
                else honap_mulva(fiok.eves_bazis, ciklus) if fiok.eves_bazis and not beallitas.fix_dijas(sub.data) else None
            ),
            # A számlán közölt következő leolvasás / diktálás időszaka (DAKÖV), ha még nem múlt el.
            "kovetkezo_leolvasas": (lambda x: [x[0].isoformat(), x[1].isoformat()]
                                    if x and x[1] >= most.date() and not (fiok.eves_bazis and x[0] <= fiok.eves_bazis <= x[1]) else None)(
                kovetkezo_idopont(tarolt, "kovetkezo_leolvasas")
            ),
            "utolso_eves_leolvasas": fiok.eves_bazis.isoformat() if fiok.eves_bazis and not beallitas.fix_dijas(sub.data) else None,
            # Távleolvasásnál a szolgáltató maga olvassa le a mérőt: diktálással nincs dolgunk.
            "kovetkezo_diktalas": [diktalas[0].isoformat(), diktalas[1].isoformat()]
            if diktalas and diktalas[1] >= most.date() and not tavleolv else None,
            # Víz: a legutóbbi számla tetején álló elszámolt mennyiség (ivóvíz, csatorna) és időszaka.
            "elszamolt_viz": _utolso_elszamolt_viz(tarolt),
            "elszamolt_kwh": _utolso_elszamolt_kwh(tarolt),
            "elszamolt_gaz": _utolso_elszamolt_gaz(tarolt),
            "diktalasi_ablak": list(diktalasi_ablak(tarolt, sub.data)) if diktalasi_ablak(tarolt, sub.data) and not tavleolv else None,
            # Kezdőállás (birtokba vétel / új mérő) és az éves leolvasás óraállása – a fejléc magyarázó soraihoz.
            "kezdo": dict(tarolt["kezdo_origo"]) if tarolt.get("kezdo_origo") else None,
            # Az éves leolvasás óraállása regiszterenként (1.8.0; napelemnél a 2.8.0 betáplálás is).
            "eves_allas": next((lo["allas"] for m in tarolt.get("merok") or [] for lo in m.get("leolvasasok", [])
                                if lo.get("elszamolasi") and (lo.get("csatorna") or "vetelezes") == "vetelezes"
                                and fiok.eves_bazis and lo["datum"] == fiok.eves_bazis.isoformat()), None),
            "eves_allas_betaplalas": next((lo["allas"] for m in tarolt.get("merok") or [] for lo in m.get("leolvasasok", [])
                                           if lo.get("csatorna") == "betaplalas" and fiok.eves_bazis
                                           and lo["datum"] == fiok.eves_bazis.isoformat()), None),
            "van_szamla": bool(tarolt.get("szamlak")),
        }
        beszamitas = self._turfizetes_beszamitas(sid, uton, esedekes_e, szamlazasi_e)
        egyenleg, egyenleg_hiba = None, None
        if beallitas.reszszamlas(sub.data) and not diktalas_szerint:
            try:
                # Egy részszámla az ütem szerinti hónapok átalánya (pl. DAKÖV: két hónap).
                egyenleg = await self._egyenleg(
                    sub, tarolt, fiok, szamlalo, most, tovabbi, atalany_e["havi"] * (periodus or 1) if atalany_e else None,
                    szaldo_betap,
                )
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
                utolso_szamla=_utolso_szamla(tarolt),
                elszamolas=elszamolas,
                atalany=atalany_e,
                esedekes=esedekes_e,
                utem=utem,
                szamlazasi=szamlazasi_e,
                szamla_stat=_stat_esedekessel(
                    szamla_statisztika(
                        tarolt, most.date(), fix_dij=beallitas.fix_dijas(sub.data),
                        honap=int(sub.data[CONF_SZAMLAZAS_HONAP]) if beallitas.fix_dijas(sub.data) and sub.data.get(CONF_SZAMLAZAS_HONAP) else None,
                        idenyes=(self.tar.felold(_hozzarendeles(fiok, most.date()), most.date(), fiok.szolgaltato, fiok.feluliras)
                                 .szabalyok.get("alapdij") or {}).get("honapok") if beallitas.fix_dijas(sub.data) else None,
                        szamla_dij=self._fix_szamla_dij(fiok, sub, tarolt) if beallitas.fix_dijas(sub.data) else None,
                    ), esedekes_e
                ),
                napelem_hiba=napelem_hiba,
                keret_ev=keret_ev,
                uton_szamlak=uton,
                beszamitas=beszamitas,
                diktalt_szamla=diktalt_e,
                diktalas_szerint=diktalas_szerint,
                megszunt=tarolt.get("megszunt") if veg else None,
                szunetel=szunetel_e,
                szamla_allasok=szamla_allasok,
                d_osszevetes=(
                    (self._d_osszevetes(fiok, tarolt, ny, most) or {}) | {"szaldo_napelem": sub.data.get(CONF_NAPELEM) == "szaldo"}
                    | self._d_12ho_mezok(sid, sub, most)
                    if sub.data.get(CONF_DIJSZABAS) == "villany/a1" and (fiok.d_napok or fiok.d_ar_napok) else None
                ),
            ),
            lezart_valt,
        )


    async def _leolvasasos_lezartak(
        self, sid: str, fiok: Fiok, tarolt: dict[str, Any], hatarok_l: list[date], nyitott_tol: date, most: datetime,
        extra: set[date],
    ) -> bool:
        """Diktálásnál a lezárt időszakok = egymást követő leolvasások párjai a nyitott időszakig. A hiányzót kiszámolja,
        az ezekkel átfedő, de nem egyező régi bejegyzést (más mód, becsült havi lezárás) eltávolítja."""
        parok = [(a, b) for a, b in zip(hatarok_l, hatarok_l[1:]) if b <= nyitott_tol]
        if not parok:
            if tarolt.get("nyitott_tol") != nyitott_tol.isoformat():
                tarolt["nyitott_tol"] = nyitott_tol.isoformat()
                return True
            return False
        elso = parok[0][0].isoformat()
        kell = {(a.isoformat(), b.isoformat()) for a, b in parok}
        regi = tarolt.get("lezart", [])
        marad = [x for x in regi if (x["tol"], x["ig"]) in kell or x["ig"] <= elso]
        megvan = {(x["tol"], x["ig"]) for x in marad}
        hianyzo = [(a, b) for a, b in parok if (a.isoformat(), b.isoformat()) not in megvan]
        if hianyzo:
            t0 = datetime.combine(hianyzo[0][0], datetime.min.time())
            szamlalok = [await self.szamlalo(sid, fiok, t0, most, i) for i in range(len(fiok.csatornak))]
            for a, b in hianyzo:
                try:
                    e = szamol(fiok, self.tar, a, b, szamlalok, extra_hatarok=extra)
                    marad.append(eredmeny_tarolhato(e) | {"rogzitve": most.isoformat(), "forras": "leolvasások között"})
                except (NincsAdat, DijszabasHiba) as err:
                    _LOGGER.warning("%s – %s időszak nem zárható le: %s", a, b, err)
        valt = len(marad) != len(regi) or bool(hianyzo) or tarolt.get("nyitott_tol") != nyitott_tol.isoformat()
        tarolt["lezart"] = sorted(marad, key=lambda x: x["tol"])
        tarolt["nyitott_tol"] = nyitott_tol.isoformat()
        return valt

    async def _ellenorzes(self, sid: str, tarolt: dict[str, Any]) -> None:
        """Számla-ellenőrzés (ellenorzes.py) az utolsó ~14 hónap elszámoló számláira – naponta, ill. ha a számlák vagy
        a leolvasások változnak; a „rendezve” jelölés a tárolóban (ellenorzes_dontes)."""
        szamlak_ = tarolt.get("szamlak") or {}
        ma = helyi_most().date()
        hatar = (ma - timedelta(days=430)).isoformat()
        cel = {k for k, x in szamlak_.items() if x.get("tipus") in ellenorzes.ELLENORZOTT_TIPUSOK and (x.get("kelte") or "") >= hatar}
        sub = self.fiokok()[sid]
        viz = sub.data.get(CONF_KOZMU) == "viz" and any((x.get("elszamolt_viz") or {}).get("csatorna") is not None for x in szamlak_.values())
        if not cel and not viz:
            self.ellenorzesek.pop(sid, None)
            return
        kulcs = (ma, json.dumps({k: szamlak_[k] for k in sorted(cel)}, sort_keys=True, default=str),
                 json.dumps([m.get("leolvasasok") for m in tarolt.get("merok") or []], sort_keys=True, default=str),
                 json.dumps({k: x.get("elszamolt_viz") for k, x in szamlak_.items()} if viz else None, sort_keys=True, default=str))
        if self._ellenorzes_kulcs.get(sid) != kulcs:
            nyers: list[dict[str, Any]] = []
            if cel:
                osz = await self.szamla_osszevetes(sid, honap=15, tarolt=tarolt, csak=cel)
                napelemes = sub.data.get(CONF_NAPELEM, "nincs") != "nincs"
                nyers = ellenorzes.ellenoriz(osz.get("sorok") or [], szamlak_, elteres=not napelemes,
                                             tavho=sub.data.get(CONF_KOZMU) == "tavho")
            if viz:
                fiok = self._otthon_bazissal(sub, fiok_motorba(dict(sub.data), tarolt))

                def csatorna_ar(nap: date) -> Decimal | None:
                    try:
                        e = self.tar.felold(_hozzarendeles(fiok, nap), nap, fiok.szolgaltato, fiok.feluliras)
                    except DijszabasHiba:
                        return None
                    ar = e.dijak.get("csatorna_m3")
                    return None if not ar else Decimal(ar) * (1 + Decimal(e.dijak.get("afa") or 0) / 100)

                marad = {t["sorszam"] for t in nyers}  # számlánként egy hiba: a meglévő erősebb
                nyers += [t for t in ellenorzes.viz_ellenoriz(szamlak_, csatorna_ar, hatar, self._haztartas_melegviz())
                          if t["sorszam"] not in marad]
            self._ellenorzes_nyers[sid] = nyers
            self._ellenorzes_kulcs[sid] = kulcs
        dontes = tarolt.get("ellenorzes_dontes") or {}
        self.ellenorzesek[sid] = [t | {"kulcs": ellenorzes.kulcs(t), "rendezve": dontes.get(ellenorzes.kulcs(t)) == "rendezve"}
                                  for t in self._ellenorzes_nyers.get(sid, [])]

    def _melegviz_havi(self) -> Any:
        """A háztartás távhős melegvize egy hónapra (m³; „ÉÉÉÉ-HH” → Decimal): a távhőszámlán számlázott mennyiség, számla
        híján a fiók átalánya (alapból 1 m³/hó) – legalább 1 m³ (a havi minimum). Távhő fiók nélkül None."""
        tavho = [(sid, sub) for sid, sub in self.fiokok().items() if sub.data.get(CONF_KOZMU) == "tavho"]
        if not tavho:
            return None
        havi: dict[str, Decimal] = {}
        atalany = Decimal(0)
        for sid, sub in tavho:
            atalany += Decimal(str(sub.data.get(CONF_ATALANY_MENNYISEG) or 1))
            for x in (self.tarolo.fiok(sid).get("szamlak") or {}).values():
                et, ido = x.get("elszamolt_tavho") or {}, x.get("idoszak")
                if et.get("melegviz") is not None and ido and ido[0][:7] == ido[1][:7]:
                    havi[ido[0][:7]] = havi.get(ido[0][:7], Decimal(0)) + Decimal(str(et["melegviz"]))
        return lambda ho: max(havi.get(ho, atalany), Decimal(1))

    def _haztartas_melegviz(self) -> Any:
        """A háztartás távhős melegvize (m³) egy időszakra, egész hónapokban (a számlaellenőrzéshez). Távhő nélkül None."""
        havi = self._melegviz_havi()
        if havi is None:
            return None

        def melegviz(tol: date, ig: date) -> Decimal:
            ossz, ho = Decimal(0), date(tol.year, tol.month, 1)
            while ho <= ig:
                ossz += havi(ho.strftime("%Y-%m"))
                ho = date(ho.year + (ho.month == 12), ho.month % 12 + 1, 1)
            return ossz

        return melegviz

    def _meleg_szennyviz(self, fiok: Fiok, tol: date, ig: date) -> tuple[Decimal, Decimal, dict[str, Any]] | None:
        """Víz fióknál a háztartás távhős melegvizének szennyvize („meleg szennyvíz”), amelyet a vízmű a csatornadíjjal
        számláz (pl. ALFÖLDVÍZ 2026-05-től): (m³, bruttó Ft, tételsor) a [tol, ig) időszakra, hónaponként napra arányosítva.
        None, ha nincs távhő a háztartásban, vagy a vízfiókon nincs csatornadíj."""
        havi = self._melegviz_havi()
        if havi is None or ig <= tol or not fiok.csatornak or not fiok.csatornak[0].csatornadij_aktiv:
            return None
        nap = ig - timedelta(days=1)
        try:
            e = self.tar.felold(_hozzarendeles(fiok, nap), nap, fiok.szolgaltato, fiok.feluliras)
        except (DijszabasHiba, KeyError):
            return None
        # Csak ahol a vízmű a meleg szennyvizet külön számlázza (díjszabás „meleg_szennyviz”) – ahol a vízfiók a
        # melegvízórát is méri (pl. budapesti társasház), ott a melegvíz eleve a vízfiókban van.
        if not e.szabalyok.get("meleg_szennyviz") or not e.szabalyok.get("csatornadij") or not e.dijak.get("csatorna_m3"):
            return None
        m3, ho = Decimal(0), date(tol.year, tol.month, 1)
        while ho < ig:
            kov = date(ho.year + (ho.month == 12), ho.month % 12 + 1, 1)
            atfed = (min(kov, ig) - max(ho, tol)).days
            m3 += havi(ho.strftime("%Y-%m")) * atfed / (kov - ho).days
            ho = kov
        afa = e.dijak.get("afa")
        netto = Decimal(str(e.dijak["csatorna_m3"]))
        ft = m3 * netto * (1 + Decimal(str(afa)) / 100 if afa is not None else 1)
        tetel = {"nev": "Meleg szennyvíz", "mennyiseg": float(round(m3, 3)), "egyseg": "m³", "ar": float(netto),
                 "netto": float(round(m3 * netto, 2)), "afa": afa}
        return m3, ft, tetel

    def _viz_potlek(self, sub: ConfigSubentry, fiok: Fiok, ny: NyitottIdoszak, tol: date, ig: date, most: datetime) -> NyitottIdoszak:
        """Víz fiók folyó időszaka: (1) az „eddig” legalább a várható időarányos része – egész m³-es számlázásnál a
        0,3 m³ még 0 m³ lenne, holott a számlánkénti minimum (1 m³) arányos része már jár; (2) a háztartás távhős
        melegvizének szennyvize (meleg szennyvíz) – a várhatóban az egész időszakra, az eddigben a mai napig."""
        if sub.data.get(CONF_KOZMU) != "viz" or ny is None:
            return ny
        uj_e, uj_v = list(ny.eddig.szeletek), list(ny.varhato.szeletek)
        if not uj_e or not uj_v:
            return ny
        minta = uj_v[-1]

        def szelet(t: date, i: date, ft: Decimal, csat: str, tetel: dict[str, Any]) -> Any:
            return dataclasses.replace(
                minta, tol=t, ig=i, mennyiseg=Decimal(0), kedvezmenyes=Decimal(0), piaci=Decimal(0), keret=None, energia_ft=ft,
                alapdij_ft=Decimal(0), csatorna=csat, elszamolt=Decimal(0), csatorna_ft=ft if csat == "meleg_szennyviz" else Decimal(0),
                savkorrekcio=Decimal(0), keret_evi=None, keret_eves=False, volgy=None, volgy_ft=Decimal(0), tetelek=[tetel])

        ma = min(max(most.date() + timedelta(days=1), tol), ig)
        napok = Decimal((ig - tol).days) or Decimal(1)
        eltelt = Decimal((ma - tol).days)
        alap_e, alap_v = ny.eddig.osszesen_ft, ny.varhato.osszesen_ft
        aranyos = (alap_v * eltelt / napok).quantize(Decimal(1))
        if ny.varhato is not ny.eddig and ma < ig and aranyos > alap_e:
            uj_e.append(szelet(tol, ma, aranyos - alap_e, "aranyos_minimum",
                               {"nev": "Időarányos rész (egész m³, számlánkénti minimum)", "mennyiseg": None, "egyseg": "", "ar": None,
                                "netto": None, "afa": None}))
        msz_v, msz_e = self._meleg_szennyviz(fiok, tol, ig), self._meleg_szennyviz(fiok, tol, ma)
        if msz_v:
            uj_v.append(szelet(tol, ig, msz_v[1], "meleg_szennyviz", msz_v[2]))
        if msz_e and ny.varhato is not ny.eddig:
            uj_e.append(szelet(tol, ma, msz_e[1], "meleg_szennyviz", msz_e[2]))
        if ny.varhato is ny.eddig:
            v = dataclasses.replace(ny.varhato, szeletek=uj_v)
            return dataclasses.replace(ny, eddig=v, varhato=v)
        return dataclasses.replace(ny, eddig=dataclasses.replace(ny.eddig, szeletek=uj_e),
                                   varhato=dataclasses.replace(ny.varhato, szeletek=uj_v))

    async def fizetes_rogzit(self, sid: str, sorszam: str, fizetve: bool | None, datum: date | None = None) -> None:
        """Egy számla pénzügyi teljesítése kézzel: fizetve (dátummal) / nincs fizetve; None: a kézi bejegyzés törlése
        (újra a Díjnet szerint)."""
        tarolt = self.tarolo.fiok(sid)
        if sorszam not in (tarolt.get("szamlak") or {}):
            raise ValueError("Nincs ilyen számla.")
        f = tarolt.setdefault("fizetesek", {})
        if fizetve is None:
            f.pop(sorszam, None)
        else:
            f[sorszam] = {"fizetve": fizetve, "datum": (datum or date.today()).isoformat() if fizetve else None}
        await self.tarolo.ment()
        # A fizetés a folyószámla egyenlegét, így a túlfizetés beszámítását is változtatja: újraszámolás – a háttérben,
        # hogy a panel ne várjon rá (a folyószámla és a fizetés-állapot a tárolóból azonnal friss).
        self._hatter_frissites()

    @property
    def _kozos_ip(self) -> dict[str, tuple[date, date]]:
        """A diktálás szerint számlázó fiókok következő számlájának időszaka (tol, ig) – a közös folyószámla
        társfiókjainak. Körök között megmarad (a fiókok sorrendje így nem számít)."""
        if not hasattr(self, "_kozos_ip_"):
            self._kozos_ip_: dict[str, tuple[date, date]] = {}
        return self._kozos_ip_

    def _kozos_szamlazasi_idoszak(self, sid: str, tarolt: dict[str, Any]) -> tuple[date, date] | None:
        """A közös folyószámla diktálás szerint számlázó társfiókjának következő számla-időszaka, ha a fiók saját
        legutóbbi számlája előtte zárult."""
        if not self._kozos_ip:
            return None
        haztartas = {s: (sub.title, self.tarolo.fiok(s).get("szamlak") or {}) for s, sub in self.fiokok().items()}
        vegek = [i[1] for x in (tarolt.get("szamlak") or {}).values() if (i := _szamlazott_idoszak(x))]
        for s in folyoszamla_.kozos_csoport(sid, haztartas):
            if s != sid and (ip := self._kozos_ip.get(s)) and (not vegek or max(vegek) < ip[0]) and ip[1] >= helyi_most().date():
                return ip
        return None

    def _kozos_utolso_kelte(self, sid: str) -> date | None:
        """A közös folyószámla társfiókjainak legutóbbi (nem stornó, érvényes) számlája – kelte."""
        haztartas = {s: (sub.title, self.tarolo.fiok(s).get("szamlak") or {}) for s, sub in self.fiokok().items()}
        keltek = [d(x["kelte"]) for s in folyoszamla_.kozos_csoport(sid, haztartas) if s != sid
                  for k, x in haztartas[s][1].items()
                  if x.get("kelte") and x.get("tipus") != "storno" and k not in _ervenytelenek(haztartas[s][1])]
        return max(keltek) if keltek else None

    def _hatter_frissites(self) -> None:
        """Teljes újraszámolás a háttérben (a hívó nem vár rá; több gyors módosítás egy számolásba fut össze)."""
        self.hass.async_create_background_task(self.async_request_refresh(), f"{DOMAIN} újraszámolás")

    def javitott_szamlak(self, sid: str) -> dict[str, dict[str, Any]]:
        """A fiók számlái a kézi javításokkal (szamla_javitas: határidő, megjegyzés) – a számla saját adatai (a fájlból)
        érintetlenek, így az újraolvasás nem írja felül a javítást."""
        tarolt = self.tarolo.fiok(sid)
        szamlak, jav = tarolt.get("szamlak") or {}, tarolt.get("szamla_javitas") or {}
        if not jav:
            return szamlak
        return {k: ({**x, **({"hatarido": j["hatarido"]} if j.get("hatarido") else {}),
                     **({"javitas_megjegyzes": j["megjegyzes"]} if j.get("megjegyzes") else {})} if (j := jav.get(k)) else x)
                for k, x in szamlak.items()}

    async def szamla_javitas(self, sid: str, sorszam: str, *, fizetes: dict[str, Any] | None = None,
                             hatarido: date | None = None, megjegyzes: str = "") -> None:
        """Egy számla kézi javítása: csak a fájlban nem szereplő adatok – fizetés (fizetve/nincs + nap; None: vissza a
        Díjnet szerintire), fizetési határidő, megjegyzés. Az összeg, az időszak, a mérőállás a számlából jön."""
        tarolt = self.tarolo.fiok(sid)
        if sorszam not in (tarolt.get("szamlak") or {}):
            raise ValueError("Nincs ilyen számla.")
        if fizetes is not None:
            f = tarolt.setdefault("fizetesek", {})
            if fizetes.get("fizetve") is None:
                f.pop(sorszam, None)
            else:
                f[sorszam] = {"fizetve": bool(fizetes["fizetve"]),
                              "datum": (fizetes.get("datum") or date.today()).isoformat() if fizetes["fizetve"] else None}
        jav = tarolt.setdefault("szamla_javitas", {})
        uj = {k: v for k, v in {"hatarido": hatarido.isoformat() if hatarido else None,
                                "megjegyzes": (megjegyzes or "").strip()[:500] or None}.items() if v}
        if uj:
            jav[sorszam] = uj | {"modositva": helyi_most().isoformat(timespec="minutes")}
        else:
            jav.pop(sorszam, None)
        await self.tarolo.ment()
        self._hatter_frissites()

    async def hatarido_rogzit(self, sid: str, sorszam: str, hatarido: date | None) -> None:
        """Egy számla fizetési határideje kézzel (kézi számlánál nincs honnan kiolvasni); None: törlés."""
        tarolt = self.tarolo.fiok(sid)
        if sorszam not in (tarolt.get("szamlak") or {}):
            raise ValueError("Nincs ilyen számla.")
        if hatarido is None and tarolt["szamlak"][sorszam].get("kezi"):
            tarolt["szamlak"][sorszam].pop("hatarido", None)  # régebben a kézi számlába írtuk
        j = (tarolt.get("szamla_javitas") or {}).get(sorszam) or {}
        await self.szamla_javitas(sid, sorszam, hatarido=hatarido, megjegyzes=j.get("megjegyzes") or "")

    async def szamla_lemondas(self, sid: str, kovetkezo_datum: str, tol: str | None = None, ig: str | None = None,
                              osszeg: float | None = None) -> None:
        """A késő várt számla lemondása („nem jön számla”): csak a becslés tűnik el – a tárolt számlák, befizetések,
        egyenlegek nem változnak. Csak az éppen későként várt számla mondható le; a következő valódi számla után a
        lemondás hatástalan (a várt számla onnan újraszámolódik)."""
        a = (self.data or {}).get(sid)
        es = (getattr(a, "esedekes", None) or {}) if a is not None else {}
        varva = es.get("kovetkezo_datum")
        varva = varva.isoformat() if hasattr(varva, "isoformat") else str(varva or "")[:10]
        if not es.get("elmaradt") or varva != kovetkezo_datum[:10]:
            raise ValueError("Ez a számla már nem késik (közben megjött, vagy újraszámolódott) – frissítsd az oldalt.")
        tarolt = self.tarolo.fiok(sid)
        if any(x.get("kovetkezo_datum") == varva for x in tarolt.get("lemondott_szamlak") or []):
            return  # már lemondva (pl. két gyors kérés a háttér-újraszámolás előtt) – ne tolja el kétszer
        tarolt.setdefault("lemondott_szamlak", []).append({  # tol, ig, osszeg: csak napló (a panelen látott becslés)
            "kovetkezo_datum": varva, "tol": tol, "ig": ig, "osszeg": osszeg if osszeg is not None else es.get("kovetkezo_osszeg"),
            "rogzitve": dt_util.now().isoformat(timespec="seconds"),
        })
        _LOGGER.info("%s: a %s körül várt számla lemondva (nem jön)", self.fiokok()[sid].title, varva)
        await self.tarolo.ment()
        self._hatter_frissites()

    async def dij_elteres_dontes(self, sid: str, sorszam: str, dontes: str) -> None:
        """Fix díjas fiók: a legutóbbi számla eltér a beállított díjtól. „uj_dij”: a számla összege az új havidíj
        (felülírás dijak.alapdij_ho a számla időszakának kezdetétől, ÁFA nélkül, × hónapok helyett havira);
        „egyszeri”: egyszeri tétel – ennél a számlánál nem jelez tovább."""
        tarolt = self.tarolo.fiok(sid)
        x = (tarolt.get("szamlak") or {}).get(sorszam)
        if x is None:
            raise ValueError(f"Nincs ilyen számla: {sorszam}")
        if dontes == "egyszeri":
            lista = tarolt.setdefault("dijelteres_nyugtazva", [])
            if sorszam not in lista:
                lista.append(sorszam)
        elif dontes == "uj_dij":
            self._havidij_szamlabol(sid, self.fiokok()[sid], tarolt, x)
        else:
            raise ValueError(f"Ismeretlen döntés: {dontes}")
        await self.tarolo.ment()
        self._hatter_frissites()

    def _havidij_szamlabol(self, sid: str, sub: ConfigSubentry, tarolt: dict[str, Any], x: dict[str, Any]) -> tuple[date, Decimal]:
        """A számla összege az új havidíj: felülírás dijak.alapdij_ho a számla időszakának kezdetétől (a hónap 1-jétől),
        ÁFA nélkül, a számlázott hónapokra elosztva. Visszaad: (érvényes ettől, havidíj ÁFA nélkül)."""
        fiok = self.motor_fiok(sid)
        tol = date.fromisoformat((x.get("idoszak") or [x["kelte"]])[0][:10]).replace(day=1)
        e = self.tar.felold(_hozzarendeles(fiok, tol), tol, fiok.szolgaltato, fiok.feluliras)
        honap = int(sub.data.get(CONF_SZAMLAZAS_HONAP) or 1)
        afa = Decimal(str(e.dijak.get("afa") or 0))
        havi = (Decimal(str(sajat_ertek(x))) / honap / (1 + afa / 100)).quantize(Decimal("0.01"))
        tarolt["feluliras"] = [f for f in tarolt.get("feluliras") or []
                               if not (f["kulcs"] == "dijak.alapdij_ho" and f["ervenyes_tol"] == tol.isoformat())]
        tarolt["feluliras"].append({"kulcs": "dijak.alapdij_ho", "ertek": str(havi), "ervenyes_tol": tol.isoformat()})
        return tol, havi

    # ---- saját díjak (2.2.0b6): a településenként / edényenként eltérő díjak a panelről, felülírásként ----
    SAJAT_DIJ_MEZOK = {
        "viz": [("viz_m3", "Ivóvíz", "Ft/m³"), ("csatorna_m3", "Csatorna", "Ft/m³"), ("alapdij_ho", "Alapdíj", "Ft/hó")],
        "_fix": [("alapdij_ho", "Havidíj", "Ft/hó")],
    }

    def _sajat_dij_mezok(self, sub: ConfigSubentry) -> list[tuple[str, str, str]]:
        if beallitas.fix_dijas(sub.data) and sub.data.get(CONF_KOZMU) not in FIX_DIJAS:
            return []  # mérő nélküli gáz: országos egységár × átalány-MJ, nincs saját havidíj
        if beallitas.fix_dijas(sub.data):
            return self.SAJAT_DIJ_MEZOK["_fix"]
        return self.SAJAT_DIJ_MEZOK.get(sub.data.get(CONF_KOZMU), [])

    def sajat_dijak(self, sid: str, nap: date | None = None) -> dict[str, Any]:
        """A fiók díjai (bruttó Ft) a „Saját díjak” űrlaphoz: a mostani érték (díjszabás + felülírás)."""
        sub = self.fiokok()[sid]
        mezok = self._sajat_dij_mezok(sub)
        if not mezok:
            raise ValueError("Ennél a fióknál nincs saját díj (a díjszabás a szolgáltatóé).")
        nap = nap or helyi_most().date()
        fiok = self.motor_fiok(sid)
        e = self.tar.felold(_hozzarendeles(fiok, nap), nap, fiok.szolgaltato, fiok.feluliras)
        afa = Decimal(str(e.dijak.get("afa") or 0))
        kezi = {f["kulcs"] for f in self.tarolo.fiok(sid).get("feluliras") or []}
        return {"afa": float(afa), "mezok": [
            {"kulcs": k, "nev": n, "egyseg": u, "kezi": f"dijak.{k}" in kezi,
             "ertek": float((Decimal(str(e.dijak.get(k) or 0)) * (1 + afa / 100)).quantize(Decimal("0.01")))}
            for k, n, u in mezok]}

    async def sajat_dijak_ment(self, sid: str, ertekek: dict[str, float], tol: date) -> None:
        """A megadott bruttó díjak felülírásként (ÁFA nélkül tárolva) a `tol` naptól."""
        sub = self.fiokok()[sid]
        engedett = {k for k, _n, _u in self._sajat_dij_mezok(sub)}
        if not engedett or not set(ertekek) <= engedett:
            raise ValueError("Ismeretlen díj.")
        fiok = self.motor_fiok(sid)
        e = self.tar.felold(_hozzarendeles(fiok, tol), tol, fiok.szolgaltato, fiok.feluliras)
        afa = Decimal(str(e.dijak.get("afa") or 0))
        tarolt = self.tarolo.fiok(sid)
        lista = tarolt.setdefault("feluliras", [])
        for k, v in ertekek.items():
            netto = (Decimal(str(v)) / (1 + afa / 100)).quantize(Decimal("0.0001"))
            lista[:] = [f for f in lista if not (f["kulcs"] == f"dijak.{k}" and f["ervenyes_tol"] == tol.isoformat())]
            lista.append({"kulcs": f"dijak.{k}", "ertek": str(netto), "ervenyes_tol": tol.isoformat()})
        lista.sort(key=lambda f: (f["kulcs"], f["ervenyes_tol"]))
        tarolt["fix_dij_tanulva"] = tarolt.get("fix_dij_tanulva") or {"kezi": True}   # kézi díj után nem tanul
        await self.tarolo.ment()
        self._hatter_frissites()

    def _fix_dij_tanul(self, sid: str, sub: ConfigSubentry, tarolt: dict[str, Any]) -> bool:
        """Fix díjas fiók (MOHU, közös költség): a díj a helyi szolgáltatótól függ (edény, ürítés, település), a beépített
        díjszabás csak kiindulás. Ha a havidíjat kézzel nem adták meg, és a legutóbbi két teljes időszakos számla
        ugyanannyi, de eltér a díjszabás díjától, a számlák díja lesz a havidíj – egyszer, értesítéssel (2.2.0b6)."""
        if beallitas.fix_dijas(sub.data) and sub.data.get(CONF_KOZMU) not in FIX_DIJAS:
            # Mérő nélküli gáz: a díj egységár (Ft/MJ) × a havi átalány-MJ, nem havidíj – nem tanulunk. A 2.2.0 tévesen
            # ide is tanult (a havidíjat Ft/MJ-ként szorozta a havi MJ-val: milliós várható díj); a saját tanult
            # felülírását visszavonjuk (a kézzel megadottat nem).
            t = tarolt.get("fix_dij_tanulva") or {}
            if not t.get("havi"):
                return False
            tarolt["feluliras"] = [f for f in tarolt.get("feluliras") or []
                                   if not (f.get("kulcs") == "dijak.alapdij_ho" and f.get("ervenyes_tol") == t.get("tol")
                                           and str(f.get("ertek")) == str(t["havi"]))]
            tarolt.pop("fix_dij_tanulva", None)
            persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_fixdij_{sid}")
            _LOGGER.warning("%s: a tévesen a számlákból tanult havidíj (%s) visszavonva – mérő nélküli gáz", sub.title, t["havi"])
            return True
        if not beallitas.fix_dijas(sub.data) or not sub.data.get(CONF_SZAMLAZAS_HONAP) or tarolt.get("fix_dij_tanulva"):
            return False
        if any(f.get("kulcs") == "dijak.alapdij_ho" for f in tarolt.get("feluliras") or []):
            return False                                    # kézzel (vagy a panel gombjával) már megadták
        honap = int(sub.data[CONF_SZAMLAZAS_HONAP])
        kihagy = _ervenytelenek(tarolt.get("szamlak") or {})

        def teljes(x: dict[str, Any]) -> bool:
            i = x.get("idoszak") or []
            try:
                return len(i) >= 2 and abs((date.fromisoformat(i[1][:10]) - date.fromisoformat(i[0][:10])).days - honap * 30.4) <= 6
            except (TypeError, ValueError):
                return False

        lista = sorted((x["kelte"], k, x) for k, x in (tarolt.get("szamlak") or {}).items()
                       if x.get("kelte") and k not in kihagy and sajat_ertek(x) and teljes(x))
        if len(lista) < 2:
            return False
        (_, k1, x1), (_, _k2, x2) = lista[-2], lista[-1]
        v1, v2 = Decimal(str(sajat_ertek(x1))), Decimal(str(sajat_ertek(x2)))
        if abs(v1 - v2) > 1:
            return False                                    # változó összeg: nincs egyértelmű díj
        for _kelte, k_, x_ in reversed(lista[:-2]):         # az azonos összegű számlák sorozatának eleje
            if abs(Decimal(str(sajat_ertek(x_))) - v2) > 1:
                break
            k1, x1 = k_, x_
        fiok = self.motor_fiok(sid)
        nap = date.fromisoformat((x2.get("idoszak") or [x2["kelte"]])[0][:10])
        e = self.tar.felold(_hozzarendeles(fiok, nap), nap, fiok.szolgaltato, fiok.feluliras)
        if (e.szabalyok.get("alapdij") or {}).get("honapok"):
            return False                                    # idényes díj (pl. üdülő): a negyedévek eltérnek
        afa = Decimal(str(e.dijak.get("afa") or 0))
        varhato = Decimal(str(e.dijak.get("alapdij_ho") or 0)) * (1 + afa / 100) * honap
        if abs(v2 - varhato) <= 1:
            return False                                    # a díjszabás díja egyezik a számlákkal
        tol, havi = self._havidij_szamlabol(sid, sub, tarolt, x1)
        brutto = (havi * (1 + afa / 100)).quantize(Decimal("1"))
        tarolt["fix_dij_tanulva"] = {"sorszam": k1, "havi": str(havi), "tol": tol.isoformat()}
        persistent_notification.async_create(
            self.hass,
            f"A(z) {sub.title} díját a számláidból vettem át: {int(v2)} Ft / {honap} hónap = kb. {int(brutto)} Ft/hó "
            f"({tol.isoformat()}-tól). A beépített díj ({int(varhato)} Ft / {honap} hónap) egy másik településé / "
            "edényméreté volt. Ha nem ez a díjad, a panelen a fiók kártyáján a „Saját díjak” alatt módosíthatod.",
            title=f"Rezsikövető – {sub.title}: díj a számlákból", notification_id=f"{DOMAIN}_fixdij_{sid}",
        )
        _LOGGER.info("%s: fix díj a számlákból: %s Ft/hó (ÁFA nélkül) %s-tól", sub.title, havi, tol)
        return True

    def _fix_szamla_dij(self, fiok: Fiok, sub: ConfigSubentry, tarolt: dict[str, Any]) -> Decimal | None:
        """Fix díjas fiók egy számlájának várható összege a legutóbbi számla napján érvényes díjjal: havi díj (bruttó, ÁFA-val)
        × a számlázott hónapok – a díjváltozás / egyszeri tétel jelzéséhez. Idényes díjnál nincs (a negyedévek eltérnek)."""
        kihagy = _ervenytelenek(tarolt.get("szamlak") or {})
        szamlak = sorted((x["kelte"], x) for k, x in (tarolt.get("szamlak") or {}).items() if x.get("kelte") and k not in kihagy)
        if not szamlak or not sub.data.get(CONF_SZAMLAZAS_HONAP) or sub.data.get(CONF_KOZMU) not in FIX_DIJAS:
            return None  # a mérő nélküli gázátalány díja nem havi alapdíj
        x = szamlak[-1][1]
        nap = date.fromisoformat((x.get("idoszak") or [x["kelte"]])[0])
        e = self.tar.felold(_hozzarendeles(fiok, nap), nap, fiok.szolgaltato, fiok.feluliras)
        if (e.szabalyok.get("alapdij") or {}).get("honapok") or not e.dijak.get("alapdij_ho"):
            return None
        havi = Decimal(str(e.dijak["alapdij_ho"])) * (1 + Decimal(str(e.dijak.get("afa") or 0)) / 100)
        return (havi * int(sub.data[CONF_SZAMLAZAS_HONAP])).quantize(Decimal(1))

    def _turfizetes_beszamitas(
        self, sid: str, uton: list[dict[str, Any]] | None, esedekes_e: dict[str, Any] | None, szamlazasi_e: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Amíg a folyószámlán túlfizetés van, a várható (még nem érkezett) számlák fizetendője a túlfizetéssel csökken;
        ha mínuszba fordulna, nincs fizetendő (0). Időrendben: előbb a még nem érkezett, lezárt időszakok számlái, aztán
        a következő számla. Közös (MVM) folyószámlánál a csoport fiókjai közösen fogyasztják a túlfizetést."""
        try:
            k = self.folyoszamla(sid, egyutt=True)  # a beszámítás a közös (MVM) folyószámla egyenlegéből
        except Exception:  # noqa: BLE001 – a beszámítás nem állíthatja meg a számolást
            return None
        if k["zaro"] > -0.5:
            return None
        # Csak a szolgáltató által igazolt túlfizetés: az elmúlt fél év legutóbbi mínuszos fizetendőjű számlája (pl.
        # hődíj-korrekció, elszámoló jóváírás) – legfeljebb ennyi. A kivonat egyenlege önmagában lehet pontatlan
        # (a számlán nem részletezett beszámítások, feltételezett befizetések).
        hatar = (date.today() - timedelta(days=183)).isoformat()
        negativ = sorted(
            ((x.get("kelte") or "", Decimal(str(x["osszeg"]))) for s in k["fiokok"] for x in (self.tarolo.fiok(s).get("szamlak") or {}).values()
             if x.get("osszeg") not in (None, "") and Decimal(str(x["osszeg"])) < 0 and x.get("tipus") != "storno" and (x.get("kelte") or "") >= hatar),
        )
        if not negativ:
            return None
        kulcs = tuple(sorted(k["fiokok"]))
        eredeti = min(Decimal(str(-k["zaro"])), -negativ[-1][1]).quantize(Decimal(1))
        if not hasattr(self, "_kredit_maradek"):
            self._kredit_maradek = {}
        marad = self._kredit_maradek.setdefault(kulcs, eredeti)
        levonva = Decimal(0)

        szamlak_: list[dict[str, Any]] = []  # érintett számlánként: díj, beszámított túlfizetés, a számlán várható végösszeg, fizetendő

        def von(x: Any, **hol: Any) -> Decimal:
            nonlocal marad, levonva
            v = Decimal(str(x or 0))
            lev = min(v, marad) if v > 0 else Decimal(0)
            if lev:
                szamlak_.append({**hol, "dij": int(v), "beszamitas": int(marad), "szamlan": int(v - marad), "fizetendo": int(v - lev)})
            marad -= lev
            levonva += lev
            return lev

        for x in uton or []:
            if lev := von(x.get("osszeg"), idoszak=[_iso_d(x.get("tol")), _iso_d(x.get("ig"))]):
                x["osszeg_brutto"], x["levonva"] = x["osszeg"], int(lev)
                x["osszeg"] = int(Decimal(str(x["osszeg"])) - lev)
        uton_brutto = sum(Decimal(str(x.get("osszeg_brutto", x["osszeg"]))) for x in uton or [])
        if esedekes_e:
            kov = Decimal(str(esedekes_e.get("kovetkezo_osszeg") or 0))
            if esedekes_e.get("uton") or (uton and abs(kov - uton_brutto) < 1):
                # A következő számla maga a még nem érkezett számla: ugyanaz, nem vonjuk le kétszer.
                if uton and any(x.get("levonva") for x in uton):
                    esedekes_e["kovetkezo_osszeg_brutto"] = esedekes_e.get("kovetkezo_osszeg")
                esedekes_e["kovetkezo_osszeg"] = sum(x["osszeg"] for x in uton or [])
            elif lev := von(esedekes_e.get("kovetkezo_osszeg"), datum=_iso_d(esedekes_e.get("kovetkezo_datum"))):
                esedekes_e["kovetkezo_osszeg_brutto"] = esedekes_e["kovetkezo_osszeg"]
                esedekes_e["kovetkezo_osszeg"] = int(Decimal(str(esedekes_e["kovetkezo_osszeg"])) - lev)
                if esedekes_e.get("e_havi_varhato"):
                    ev = min(Decimal(str(esedekes_e["e_havi_varhato"])), lev)
                    esedekes_e["e_havi_varhato"] = int(Decimal(str(esedekes_e["e_havi_varhato"])) - ev)
                    esedekes_e["e_havi_osszesen"] = int(Decimal(str(esedekes_e.get("e_havi_osszesen") or 0)) - ev)
                if szamlazasi_e and not szamlazasi_e.get("kiallitott") and szamlazasi_e.get("fizetendo"):
                    szamlazasi_e["fizetendo_brutto"] = szamlazasi_e["fizetendo"]
                    szamlazasi_e["fizetendo"] = max(0, int(Decimal(str(szamlazasi_e["fizetendo"])) - lev))
        self._kredit_maradek[kulcs] = marad
        if uton and szamlak_ and esedekes_e and esedekes_e.get("kovetkezo_datum") and not szamlak_[0].get("datum"):
            szamlak_[0]["datum"] = _iso_d(esedekes_e.get("kovetkezo_datum"))
        return {"turfizetes": int(marad + levonva), "levonva": int(levonva), "marad": int(marad), "kozos": k.get("kozos", False),
                "szamlak": szamlak_}

    def folyoszamla(self, sid: str, egyutt: bool = False) -> dict[str, Any]:
        """A fiók (MVM közös folyószámlánál a csoport) folyószámla-kivonata – folyoszamla.kivonat."""
        haztartas = {s: (sub.title, self.javitott_szamlak(s)) for s, sub in self.fiokok().items()}
        kozos = folyoszamla_.kozos_csoport(sid, haztartas)
        csoport = kozos if egyutt else [sid]
        fizetesek: dict[str, dict[str, Any]] = {}
        for s in kozos:  # tarifánkénti kivonatnál is: a közös folyószámla átvezetéseihez a másik fiók befizetései kellenek
            fizetesek |= self.fizetes_allapotok(s)
        kezi = [t for s in csoport for t in self.tarolo.fiok(s).get("folyoszamla_tetelek") or []]
        # A számla saját óraállásai; ahol nincsenek (kézi számla), a számlához rögzített mérőállásokból.
        for s in csoport:
            sz_ = haztartas[s][1]
            hianyzo = [k for k, x in sz_.items() if "allasok" not in x]
            if not hianyzo:
                continue
            masolat = dict(sz_)
            for k in hianyzo:
                lo = sorted((lo["datum"], lo["allas"], m.get("gyari_szam", "")) for m in self.tarolo.fiok(s).get("merok") or []
                            for lo in m.get("leolvasasok", []) if (lo.get("megjegyzes") or "").startswith(f"számla {k} (")
                            and lo.get("csatorna", "vetelezes") == "vetelezes")
                if lo:
                    masolat[k] = {**sz_[k], "allasok": [{"mero": lo[-1][2], "indulo": None, "zaro": [lo[-1][0], str(lo[-1][1])], "lm": "Dikt"}]}
            haztartas[s] = (haztartas[s][0], masolat)
        egysegek = {s: EGYSEG.get(self.fiokok()[s].data.get(CONF_KOZMU), "") for s in csoport}
        k = folyoszamla_.kivonat(sid, haztartas, fizetesek, self.tarolo.fiok(sid).get("folyoszamla_nyito"), date.today(), kezi,
                                 egysegek, egyutt)
        # A még nem érkezett / következő számla (becslés) a túlfizetés beszámításával – a teljesítés-nézet végére.
        varhato = []
        for s in csoport:
            a = (self.data or {}).get(s)
            if a is None or getattr(a, "hiba", None):
                continue
            nev = self.fiokok()[s].title
            for x in a.uton_szamlak or []:
                varhato.append({"fiok": nev, "datum": None, "idoszak": [_iso_d(x.get("tol")), _iso_d(x.get("ig"))],
                                "osszeg": x.get("osszeg_brutto", x.get("osszeg")), "fizetendo": x.get("osszeg"), "levonva": x.get("levonva")})
            e = a.esedekes or {}
            if e.get("kovetkezo_osszeg") is not None and not e.get("uton") and not e.get("nincs_tobb") and not (a.uton_szamlak and e.get("kovetkezo_osszeg_brutto") is None and abs(float(e["kovetkezo_osszeg"]) - sum(float(x["osszeg"]) for x in a.uton_szamlak)) < 1):
                varhato.append({"fiok": nev, "datum": _iso_d(e.get("kovetkezo_datum")), "idoszak": None,
                                "osszeg": e.get("kovetkezo_osszeg_brutto", e.get("kovetkezo_osszeg")), "fizetendo": e.get("kovetkezo_osszeg"),
                                "levonva": (int(e["kovetkezo_osszeg_brutto"]) - int(e["kovetkezo_osszeg"])) if e.get("kovetkezo_osszeg_brutto") is not None else None})
        k["teljesites"]["varhato"] = varhato
        k["teljesites"]["beszamitas"] = next((getattr((self.data or {}).get(s), "beszamitas", None) for s in csoport
                                               if getattr((self.data or {}).get(s), "beszamitas", None)), None)
        return k

    async def folyoszamla_tetel(self, sid: str, datum: str, megnevezes: str, kovetel: float, tartozik: float) -> None:
        """Kézi könyvelési tétel a folyószámlán (pl. egyeztetés a szolgáltató folyószámla-egyenlegével)."""
        import uuid  # noqa: PLC0415

        self.tarolo.fiok(sid).setdefault("folyoszamla_tetelek", []).append({
            "id": uuid.uuid4().hex[:10], "datum": datum, "megnevezes": megnevezes.strip() or "Kézi tétel",
            "kovetel": round(float(kovetel or 0), 2), "tartozik": round(float(tartozik or 0), 2),
        })
        await self.tarolo.ment()

    async def folyoszamla_tetel_torles(self, sid: str, tetel_id: str) -> None:
        """Kézi könyvelési tétel törlése (közös folyószámlánál bármelyik fiókjáról)."""
        haztartas = {s: (sub.title, self.tarolo.fiok(s).get("szamlak") or {}) for s, sub in self.fiokok().items()}
        for s in folyoszamla_.kozos_csoport(sid, haztartas):
            t = self.tarolo.fiok(s)
            t["folyoszamla_tetelek"] = [x for x in t.get("folyoszamla_tetelek") or [] if x.get("id") != tetel_id]
        await self.tarolo.ment()

    async def folyoszamla_nyito(self, sid: str, datum: str | None, osszeg: float | None) -> None:
        """A folyószámla kézzel megadott nyitó egyenlege (pozitív: hátralék, negatív: túlfizetés); None: törlés –
        ilyenkor az első számlán áthozott egyenleg, ennek híján 0. Közös folyószámlánál a csoport minden fiókjára."""
        haztartas = {s: (sub.title, self.tarolo.fiok(s).get("szamlak") or {}) for s, sub in self.fiokok().items()}
        for s in folyoszamla_.kozos_csoport(sid, haztartas):
            t = self.tarolo.fiok(s)
            if osszeg is None:
                t.pop("folyoszamla_nyito", None)
            else:
                t["folyoszamla_nyito"] = {"datum": datum, "osszeg": osszeg}
        await self.tarolo.ment()

    def fizetes_allapotok(self, sid: str) -> dict[str, dict[str, Any]]:
        """A fiók minden számlájának pénzügyi teljesítése (fizetes.allapot)."""
        tarolt = self.tarolo.fiok(sid)
        kezi, ma = tarolt.get("fizetesek") or {}, date.today()
        sub = self.fiokok().get(sid)
        nap = (sub.data.get(CONF_UTALAS_NAP) if sub else None) or None
        szl = self.javitott_szamlak(sid)
        torolt = szamlak.sztornozott_kulcsok(szl)
        return {k: fizetes.allapot(k, x, kezi.get(k), self.dijnet_fizetett, ma, nap, k in torolt) for k, x in szl.items()}

    async def ellenorzes_dontes(self, sid: str, kulcs: str, dontes: str) -> None:
        """Egy talált számlahiba „rendezve” (reklamáltam / megjött a helyesbítés) vagy újra „nyitott”."""
        tarolt = self.tarolo.fiok(sid)
        d_ = tarolt.setdefault("ellenorzes_dontes", {})
        if dontes == "rendezve":
            d_[kulcs] = "rendezve"
        else:
            d_.pop(kulcs, None)
        await self.tarolo.ment()
        await self._ellenorzes(sid, tarolt)
        self.async_update_listeners()

    async def szamla_osszevetes(
        self, sid: str, honap: int = 24, tarolt: dict[str, Any] | None = None, csak: set[str] | None = None
    ) -> dict[str, Any]:
        """Valódi számlák összevetése a Rezsikövető számításával, számlánként az elszámolt időszakra (forintra).

        Összevethető: a nem storno, időszakkal bíró számla. „mert”: az időszak mindkét végén van valódi mérőállás
        (± 1 nap) – különben a fogyasztás a mérőállások között arányosított, az eltérés ebből is jöhet. A részszámla
        (átalány) és a korábbi befizetéseket levonó elszámoló számla összege nem a fogyasztás díja – ezeknél az
        „osszevetheto” hamis, a sor csak tájékoztató."""
        sub = self.fiokok()[sid]
        tarolt = tarolt if tarolt is not None else self.tarolo.fiok(sid)
        fiok = self._otthon_bazissal(sub, fiok_motorba(dict(sub.data), tarolt))
        most = helyi_most()
        hatar = most.date() - timedelta(days=31 * honap)
        allas_napok = {d(lo["datum"]) for m in tarolt.get("merok") or [] for lo in m.get("leolvasasok", [])
                       if (lo.get("csatorna") or "vetelezes") == "vetelezes"}
        allas_napok |= {d(m["beepitve"]) for m in tarolt.get("merok") or []}
        sorok = []
        kihagy = _ervenytelenek(tarolt.get("szamlak") or {})
        jeloltek = sorted(
            ((i, k, x) for k, x in (tarolt.get("szamlak") or {}).items()
             if (i := _szamlazott_idoszak(x)) and k not in kihagy and i[1] >= hatar and (csak is None or k in csak)),
            key=lambda y: y[0],
        )
        if not jeloltek:
            return {"fiok": sub.title, "sorok": []}
        t0 = datetime.combine(jeloltek[0][0][0] - timedelta(days=2), datetime.min.time())
        fiok = await self._zona_fiok(sub, fiok, t0)
        fiok = await self._d_fiok(sid, sub, fiok, most)
        fix = beallitas.fix_dijas(sub.data)
        if fix:
            # Fix díj (hulladék, gázmérő nélküli átalány): a díj nem függ a méréstől – állandó számlálóval számolunk.
            szamlalok = [Szamlalo([Pont(t0, Decimal(0), True), Pont(most, Decimal(0), True)]) for _ in fiok.csatornak]
        else:
            szamlalok = [await self.szamlalo(sid, fiok, t0, most, i) for i in range(len(fiok.csatornak))]
        for (tol0, ig_utolso), sorszam, x in jeloltek:
            # A számla záró állása az időszak utolsó napjára kerül, így az előző számla záróállása az időszak előtti
            # napon áll: az ablak a tényleges leolvasási napokhoz igazodik (ha ott van állás).
            tol = tol0 - timedelta(days=1) if (tol0 - timedelta(days=1)) in allas_napok and tol0 not in allas_napok else tol0
            ig = ig_utolso if ig_utolso in allas_napok and (ig_utolso + timedelta(days=1)) not in allas_napok else ig_utolso + timedelta(days=1)
            kozel = lambda n: any(abs((n - a).days) <= 1 for a in allas_napok)  # noqa: E731
            dij, dij_forras = _szamla_teljes_dija(x, tarolt.get("szamlak") or {})
            sor: dict[str, Any] = {
                "sorszam": sorszam, "kelte": x.get("kelte"), "tipus": x.get("tipus"), "tol": tol0.isoformat(),
                "ig": ig_utolso.isoformat(), "fizetendo_ft": int(Decimal(str(x["osszeg"]))) if x.get("osszeg") is not None else None,
                "szamla_ft": dij, "szamla_ft_forras": dij_forras,
                "mert": fix or (kozel(tol) and kozel(ig)), "kezi": bool(x.get("kezi")),
            }
            q = x.get("elszamolt_kwh") or (x.get("elszamolt_gaz") or {}).get("m3") or (x.get("elszamolt_viz") or {}).get("ivoviz")
            sor["szamla_mennyiseg"] = float(q) if q is not None else None
            try:
                e = szamol(fiok, self.tar, tol, ig, szamlalok, extra_hatarok=elszamolasi_napok(tarolt))
                sor["szamolt_ft"] = int(e.osszesen_ft)
                sor["szamolt_mennyiseg"] = round(float(e.mennyiseg), 2)
                idenyek: dict[str, float] = {}
                for sz_ in e.szeletek:
                    if sz_.csatorna in ("h_teli", "h_nyari"):
                        idenyek[sz_.csatorna[2:]] = round(idenyek.get(sz_.csatorna[2:], 0.0) + float(sz_.mennyiseg), 2)
                if idenyek:
                    sor["szamolt_idenyek"] = idenyek
            except (NincsAdat, DijszabasHiba, ValueError) as err:
                sor["hiba"] = str(err)
            atalany = x.get("tipus") == "resz" or ((x.get("elszamolt_viz") or {}).get("atalany"))
            sor["osszevetheto"] = bool(sor.get("szamolt_ft") is not None and sor["szamla_ft"] is not None and not atalany
                                       and sor["szamla_ft"] > 0 and dij_forras != "fizetendo")
            if sor["osszevetheto"]:
                sor["elteres_ft"] = sor["szamolt_ft"] - sor["szamla_ft"]
            sorok.append(sor)
        ossz = [s for s in sorok if s["osszevetheto"] and s["mert"]]
        return {
            "fiok": sub.title,
            "dijszabas": sub.data.get(CONF_DIJSZABAS),
            "sorok": sorok,
            "mert_osszevetheto": len(ossz),
            "forintra_egyezik": sum(1 for s in ossz if abs(s["elteres_ft"]) <= 1),
            "max_elteres_ft": max((abs(s["elteres_ft"]) for s in ossz), default=None),
        }

    async def _fuggo_elonezet(
        self, sid: str, sub: ConfigSubentry, tarolt: dict[str, Any], most: datetime, egyseg: str, elotte: FiokAllapot
    ) -> None:
        """A függő számlák hatása: a fiók egy másolatán rögzítjük őket, és újraszámoljuk – előtte/utána a fő
        számok, az átvett mérőállások, és a számla díja a saját mérésünkhöz képest (gyanús, ha nagyon eltér)."""
        fuggo = tarolt["fuggo"]
        kulcs = (tuple(x["sorszam"] for x in fuggo), most.date(), len(tarolt.get("szamlak") or {}),
                 sum(len(m.get("leolvasasok", [])) for m in tarolt.get("merok") or []))
        if self._elonezet_kulcs.get(sid) == kulcs:
            return
        mappa = Path(self.hass.config.config_dir) / sub.data[CONF_SZAMLA_MAPPA]
        uj = await self.hass.async_add_executor_job(lambda: self._fuggo_szamlak(mappa, fuggo, tarolt))
        masolat = copy.deepcopy(tarolt)
        masolat["fuggo"] = []
        szamlak.meresi_pontok_kapcsolasa(uj, masolat.setdefault("meresi_pontok", {}))
        szuro = {x.strip() for x in str(sub.data.get(CONF_SZAMLA_MEROK) or "").split(",") if x.strip()}
        j = rogzit(masolat, uj, szuro, ARSZABAS.get(sub.data.get(CONF_DIJSZABAS)))
        try:
            utana, _ = await self._fiok(sid, sub, masolat, most, egyseg)
        except (NincsAdat, DijszabasHiba, KeyError, ValueError) as err:
            utana = FiokAllapot(egyseg=egyseg, hiba=str(err))

        def fo(a: FiokAllapot) -> dict[str, Any]:
            ny = a.nyitott
            return {
                "eddig": int(ny.eddig.osszesen_ft) if ny else None,
                "varhato": int(ny.varhato.osszesen_ft) if ny else None,
                "esedekes": (a.esedekes or {}).get("e_havi_osszesen"),
                "kovetkezo": (a.esedekes or {}).get("kovetkezo_osszeg"),
                "ha_ma": int(a.elszamolas.egyenleg) if a.elszamolas else None,
                "eves_egyenleg": int(a.egyenleg.varhato_egyenleg) if a.egyenleg else None,
                "keret_hatra": round(float(ny.hatralevo_keret), 1) if ny and ny.hatralevo_keret is not None else None,
                "idoszak": [a.tol.isoformat(), a.ig.isoformat()] if a.tol and a.ig else None,
            }

        regi = {(lo["datum"], lo.get("csatorna", "vetelezes")) for m in tarolt.get("merok") or [] for lo in m.get("leolvasasok", [])}
        uj_allasok = sorted(
            ({"datum": lo["datum"], "allas": float(Decimal(str(lo["allas"]))), "csatorna": lo.get("csatorna", "vetelezes")}
             for m in masolat.get("merok") or [] for lo in m.get("leolvasasok", [])
             if (lo["datum"], lo.get("csatorna", "vetelezes")) not in regi),
            key=lambda x: (x["datum"], x["csatorna"]),
        )
        try:
            ov = await self.szamla_osszevetes(sid, 36, tarolt=masolat, csak={x["sorszam"] for x in fuggo})
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("függő számla összevetése nem sikerült: %s", err)
            ov = {"sorok": []}
        szamlak_ki = []
        for x in fuggo:
            sor = next((r for r in ov.get("sorok", []) if r["sorszam"] == x["sorszam"]), {})
            figy = []
            if sor.get("osszevetheto") and sor.get("szamla_ft"):
                e = sor["elteres_ft"]
                if abs(e) > max(1000, 0.15 * abs(sor["szamla_ft"])):
                    figy.append(f"a számla díja ({sor['szamla_ft']} Ft) {abs(e)} Ft-tal {'kevesebb' if e > 0 else 'több'}, "
                                f"mint a saját mérésünk szerinti díj ({sor['szamolt_ft']} Ft)")
            if sor.get("szamla_mennyiseg") is not None and sor.get("szamolt_mennyiseg"):
                q, m = sor["szamla_mennyiseg"], sor["szamolt_mennyiseg"]
                if abs(q - m) > max(5, 0.15 * m):
                    figy.append(f"a számlán {q:g}, a saját mérés szerint {m:g} az elszámolt mennyiség")
            szamlak_ki.append({**x, "szamla_ft": sor.get("szamla_ft"), "szamolt_ft": sor.get("szamolt_ft"),
                               "szamla_mennyiseg": sor.get("szamla_mennyiseg"), "szamolt_mennyiseg": sor.get("szamolt_mennyiseg"),
                               "mert": sor.get("mert"), "figyelmeztetes": figy})
        if j.kihagyott_ellentmondas:
            szamlak_ki[0]["figyelmeztetes"].append(
                f"{j.kihagyott_ellentmondas} mérőállás ellentmond a meglévőknek (visszafelé menne) – ezt nem venné át")
        self.elonezet[sid] = {
            "szamlak": szamlak_ki, "elotte": fo(elotte), "utana": fo(utana), "uj_allasok": uj_allasok,
            "hiba": utana.hiba, "szamolva": most.isoformat(),
        }
        self._elonezet_kulcs[sid] = kulcs

    async def fuggo_dontes(self, sid: str, dontes: str, sorszamok: list[str] | None = None) -> dict[str, Any]:
        """Függő számla jóváhagyása (rögzítés, újraszámolás) vagy elvetése (nem kerül be; a fájl a mappában marad,
        a Részletekből vagy a hu_rezsi.szamlak_ujraolvasasa szolgáltatással később újra beolvasható)."""
        async with self._zar:
            sub = self.fiokok()[sid]
            tarolt = self.tarolo.fiok(sid)
            fuggo = tarolt.get("fuggo") or []
            valasztott = [x for x in fuggo if sorszamok is None or x["sorszam"] in sorszamok]
            if not valasztott:
                raise ValueError("Nincs ilyen jóváhagyásra váró számla.")
            eredmeny: dict[str, Any] = {"szamlak": [x["sorszam"] for x in valasztott], "dontes": dontes}
            if dontes == "jovahagy":
                mappa = Path(self.hass.config.config_dir) / sub.data[CONF_SZAMLA_MAPPA]
                uj = await self.hass.async_add_executor_job(lambda: self._fuggo_szamlak(mappa, valasztott, tarolt))
                szamlak.meresi_pontok_kapcsolasa(uj, tarolt.setdefault("meresi_pontok", {}))
                szuro = {x.strip() for x in str(sub.data.get(CONF_SZAMLA_MEROK) or "").split(",") if x.strip()}
                j = rogzit(tarolt, uj, szuro, ARSZABAS.get(sub.data.get(CONF_DIJSZABAS)))
                eredmeny |= {"rogzitve": j.szamlak, "meroallas": j.leolvasasok, "kihagyott": j.kihagyott_ellentmondas}
            else:
                tarolt.setdefault("elvetett_szamlak", []).extend(
                    {"sorszam": x["sorszam"], "fajl": x["fajl"], "datum": helyi_most().date().isoformat()} for x in valasztott)
            nevek = {x["fajl"] for x in valasztott}
            tarolt["feldolgozott_fajlok"] = sorted(set(tarolt.get("feldolgozott_fajlok", [])) | nevek)
            tarolt["fuggo"] = [x for x in fuggo if x["fajl"] not in nevek]
            # Az AI-val kiolvasott (eddig fel nem ismert) fájl a döntés után már nem „ismeretlen”.
            ai_nevek = {x["fajl"] for x in valasztott if x.get("ai")}
            if ai_nevek:
                tarolt["ismeretlen_fajlok"] = [n for n in tarolt.get("ismeretlen_fajlok", []) if n not in ai_nevek]
                if isinstance(tarolt.get("nem_olvasott_fajlok"), dict):
                    for n in ai_nevek:
                        tarolt["nem_olvasott_fajlok"].pop(n, None)
            if not tarolt["fuggo"]:
                persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_fuggo_{sid}")
            self._elonezet_kulcs.pop(sid, None)
            await self.tarolo.ment()
        await self.async_refresh()
        return eredmeny

    def _fuggo_szamlak(self, mappa: Path, lista: list[dict[str, Any]], tarolt: dict[str, Any]) -> list[Any]:
        """A függő számlák Számlaként (végrehajtó szálon): a mappából beolvasva, az AI-val kiolvasottak a jóváhagyott
        adatukból."""
        ki = []
        for x in lista:
            if not (mappa / x["fajl"]).exists():
                continue
            if x.get("ai"):
                try:
                    ki.append(ai_beolvaso.szamlava(x["ai"], x["fajl"], tarolt))
                except (ValueError, ArithmeticError) as err:
                    _LOGGER.warning("AI-val kiolvasott számla nem alakítható (%s): %s", x["fajl"], err)
            elif sz := self._beolvas(mappa / x["fajl"]):
                ki.append(sz)
        return ki

    # --- AI-számlabeolvasó (2.3.0b1) ---------------------------------------------------------------------------

    def _ai_fiok(self, sid: str) -> ConfigSubentry:
        sub = self.fiokok().get(sid)
        if sub is None:
            raise ValueError("Nincs ilyen fiók ebben az otthonban.")
        return sub

    def _ai_fajl(self, sub: ConfigSubentry, fajl: str) -> Path:
        if not sub.data.get(CONF_SZAMLA_MAPPA):
            raise ValueError("Ennek a fióknak nincs számlamappája – a számlát az Új számla gombbal töltsd fel vagy rögzítsd.")
        mappa = Path(self.hass.config.config_dir) / sub.data[CONF_SZAMLA_MAPPA]
        if not fajl or "/" in fajl or "\\" in fajl or fajl.startswith("."):
            raise ValueError("Érvénytelen fájlnév.")
        p = mappa / fajl
        if not p.is_file():
            raise ValueError(f"A fájl ({fajl}) nincs a fiók számlamappájában.")
        if p.suffix.lower() != ".pdf":
            raise ValueError("AI-val egyelőre csak PDF-számla olvasható ki.")
        return p

    def _ai_szovegek(self, p: Path) -> tuple[str, str]:
        sima, tabla = szamlak.pdf_szoveg(p, "plain"), szamlak.pdf_szoveg(p)
        if len(re.sub(r"\s+", "", sima + tabla)) < ai_beolvaso.MIN_SZOVEG:
            raise ValueError("A PDF-ben nincs kinyerhető szöveg (szkennelt, képes számla) – ezt egy későbbi változat "
                             "tudja majd kiolvasni. Addig rögzítsd az Új számla gombbal.")
        return sima, tabla

    def _ai_segito(self, sub: ConfigSubentry, tarolt: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
        """A fiók segítő adatai az AI-nak, és a kitakarandók: ismert személyes adatok, a fiók mérőszámai."""
        kozmu = sub.data.get(CONF_KOZMU)
        merok = [m.get("gyari_szam") for m in (tarolt.get("merok") or []) + (tarolt.get("almero_merok") or []) if m.get("gyari_szam")]
        merok += [x.strip() for x in str(sub.data.get(CONF_SZAMLA_MEROK) or "").split(",") if x.strip()]
        merok = list(dict.fromkeys(merok))
        leol = sorted(((lo["datum"], lo["allas"]) for m in tarolt.get("merok") or [] for lo in m.get("leolvasasok", [])
                       if lo.get("csatorna", "vetelezes") == "vetelezes"), key=lambda x: x[0])
        # Ismert személyes adatok: minden otthon minden fiókjának számláiról (név, cím, azonosító, mérési pont) – egy
        # új fióknál / új szolgáltatónál is –, és a HA személyeinek (person) neve.
        ismert: list[str] = []
        tarolok = [k.tarolo for e in self.hass.config_entries.async_entries(DOMAIN)
                   if isinstance(k := getattr(e, "runtime_data", None), RezsiKoordinator)] or [self.tarolo]
        for tar in tarolok:
            for t2 in list((tar.adat.get("fiokok") or {}).values()):
                for x in (t2.get("szamlak") or {}).values():
                    ismert += [v for k, v in (x.get("ugyfel") or {}).items() if k != "mero" and isinstance(v, str)]
                    if x.get("meresi_pont"):
                        ismert.append(str(x["meresi_pont"]))
                ismert += [str(v) for v in (t2.get("meresi_pontok") or {})]
        ismert += [s.attributes.get("friendly_name") or "" for s in self.hass.states.async_all("person")]
        segito = {"kozmu": kozmu, "egyseg": EGYSEG.get(kozmu, ""), "merok": [f"MERO_{i}" for i in range(1, len(merok) + 1)],
                  **({"utolso_allas": {"datum": leol[-1][0], "allas": str(leol[-1][1])}} if leol else {})}
        return segito, ismert, merok

    async def ai_kiolvasas(self, sid: str, fajl: str, entitas: str, context: Any = None) -> dict[str, Any]:
        """Egy fel nem ismert PDF-számla kiolvasása AI-val (kitakarva): a kiolvasott adat, a mezőnkénti ellenőrzés
        és a számla szövege (a panel jóváhagyó ablakához). Semmit nem rögzít, semmit nem tárol."""
        sub = self._ai_fiok(sid)
        tarolt = self.tarolo.fiok(sid)
        p = self._ai_fajl(sub, fajl)
        sima, tabla = await self.hass.async_add_executor_job(self._ai_szovegek, p)
        segito, ismert, merok = self._ai_segito(sub, tarolt)
        kt = ai_beolvaso.Kitakaro(ismert, merok)
        k_sima = kt.kitakar(sima)
        elso, kt.kategoriak = kt.kategoriak, {}
        k_tabla = kt.kitakar(tabla)
        kt.kategoriak = {k: max(elso.get(k, 0), kt.kategoriak.get(k, 0)) for k in elso.keys() | kt.kategoriak.keys()}
        try:
            valasz = await asyncio.wait_for(self.hass.services.async_call(
                "ai_task", "generate_data",
                {"task_name": "rezsi_szamla_kivonat", "entity_id": entitas, "structure": ai_beolvaso.STRUKTURA,
                 "instructions": ai_beolvaso.utasitas(segito, k_sima, k_tabla)},
                blocking=True, return_response=True, context=context,
            ), timeout=90)
        except TimeoutError as err:
            raise ValueError("Az AI 90 másodpercen belül nem válaszolt – próbáld újra később.") from err
        d = (valasz or {}).get("data")
        if not isinstance(d, dict):
            raise ValueError("Az AI nem adott értékelhető választ.")
        adat = ai_beolvaso.normalizal(kt.visszair(d))
        szuro = {x.strip() for x in str(sub.data.get(CONF_SZAMLA_MEROK) or "").split(",") if x.strip()}
        return {
            "fajl": fajl, "adat": adat, "entitas": entitas, "szoveg": tabla,
            "jelolesek": szamla_ellenorzo.ellenoriz(adat, sima + "\n" + tabla, tarolt, sub.data.get(CONF_KOZMU), szuro),
            "kitakarva": kt.kategoriak,
        }

    async def ai_atvetel(self, sid: str, fajl: str, adat: dict[str, Any], megerosit: bool = False,
                         sablon_mentes: bool = False) -> dict[str, Any]:
        """A jóváhagyott (esetleg javított) adat a függő számlák közé: a panel előnézete mutatja a hatását, és ott
        hagyható jóvá vagy vethető el (mint a mappába érkezett számla)."""
        async with self._zar:
            sub = self._ai_fiok(sid)
            tarolt = self.tarolo.fiok(sid)
            p = self._ai_fajl(sub, fajl)
            sima, tabla = await self.hass.async_add_executor_job(self._ai_szovegek, p)
            adat = ai_beolvaso.normalizal(adat)
            szuro = {x.strip() for x in str(sub.data.get(CONF_SZAMLA_MEROK) or "").split(",") if x.strip()}
            jel = szamla_ellenorzo.ellenoriz(adat, sima + "\n" + tabla, tarolt, sub.data.get(CONF_KOZMU), szuro)
            if jel["_osszes"]["ellentmondas"] and not megerosit:
                return {"ok": False, "jelolesek": jel}
            sz = ai_beolvaso.szamlava(adat, fajl, tarolt)  # ValueError: hiányzó kelte/sorszám
            fuggo = tarolt.setdefault("fuggo", [])
            if sz.sorszam in (tarolt.get("szamlak") or {}) or any(x["sorszam"] == sz.sorszam for x in fuggo if x["fajl"] != fajl):
                raise ValueError(f"A(z) {sz.sorszam} számla már szerepel.")
            meta = szamla_meta(sz)
            tarolt["fuggo"] = [x for x in fuggo if x["fajl"] != fajl] + [{
                "fajl": fajl, "sorszam": sz.sorszam, "erkezett": helyi_most().isoformat(), "ai": adat,
                **({"ai_megerositve": True} if jel["_osszes"]["ellentmondas"] else {}),
                **{k: meta.get(k) for k in ("kelte", "tipus", "idoszak", "osszeg", "szamlaertek", "elszamolt_kwh")}}]
            self._elonezet_kulcs.pop(sid, None)
            await self.tarolo.ment()
            sab = None
            if sablon_mentes:
                if jel["_osszes"]["ellentmondas"]:
                    sab = {"mentve": False, "uzenet": "Ellentmondásos számlából nem készül beolvasó."}
                else:
                    _seg, ismert, merok = self._ai_segito(sub, tarolt)
                    sab = await self.hass.async_add_executor_job(self._sablon_keszit, adat, sima, tabla, ismert + merok)
        if sab and sab.get("mentve"):
            await self._sablon_utan(sab)
        else:
            await self.async_refresh()
        return {"ok": True, "sorszam": sz.sorszam, **({"sablon": sab} if sab else {})}

    def _sablon_keszit(self, adat: dict[str, Any], sima: str, tabla: str, tiltott: list[str]) -> dict[str, Any]:
        """Sablon a jóváhagyott adatból (végrehajtó szálon): önpróba és személyesadat-szűrő után mentve."""
        s = sablon.keszit(adat, sima, tabla)
        if elteres := sablon.onproba(s, adat, sima, tabla):
            return {"mentve": False, "uzenet": "A beolvasó nem készült el: a számlán nem ugyanazt olvasná ki ("
                    + ", ".join(elteres) + "). A következő számlát újra AI-val olvashatod ki."}
        if szem := sablon.szemelyes(s, tiltott):
            _LOGGER.warning("Számlasablon (%s): személyes adat maradt benne, nem mentve (%s db)", s["azonosito"], len(szem))
            return {"mentve": False, "uzenet": "A beolvasó nem készült el: személyes adat maradt volna benne."}
        cel = sablon.ment(Path(self.hass.config.config_dir) / sablon.MAPPA_NEV, s)
        return {"mentve": True, "azonosito": s["azonosito"], "nev": s["nev"], "verzio": s["verzio"], "fajl": f"{sablon.MAPPA_NEV}/{cel.name}",
                "uzenet": f"Beolvasó mentve ({s['nev']}): a szolgáltató következő számláit AI nélkül olvasom be."}

    async def _sablon_utan(self, sab: dict[str, Any]) -> None:
        """Új sablon: betöltés, és minden otthon fel nem ismert fájljainak újraolvasása (ugyanattól a szolgáltatótól
        a már a mappában lévő számlák is jóváhagyásra várók lesznek)."""
        szamlak.SABLONOK[:] = await self.hass.async_add_executor_job(sablon.osszes_betolt, self.hass.config.config_dir)
        for e in self.hass.config_entries.async_entries(DOMAIN):
            k = getattr(e, "runtime_data", None)
            if not isinstance(k, RezsiKoordinator):
                continue
            k._fajl_cache.clear()
            for s_id in k.fiokok():
                t = k.tarolo.fiok(s_id)
                if t.get("nem_olvasott_fajlok"):
                    t["nem_olvasott_fajlok"] = {}
            await k.tarolo.ment()
            await k.async_refresh()
        persistent_notification.async_create(
            self.hass, f"{sab['uzenet']} Fájl: {sab['fajl']} (megosztható – személyes adatot nem tartalmaz).",
            title="Rezsikövető – új számlabeolvasó", notification_id=f"{DOMAIN}_sablon_{sab['azonosito']}")

    async def eves_kimutatas(self, sid: str, ev_tol: date | None = None) -> dict[str, Any]:
        """Éves elszámolási kimutatás (MVM villany, A1 és H): a két éves leolvasás közötti év a mérőállások és a díjszabás
        szerint, számlánként szembeállítva az elszámoló számlákkal (kimutatas.kimutatas). ev_tol: a választott év
        kezdő leolvasása (alapból a legutóbbi teljes év)."""
        sub = self.fiokok()[sid]
        tarolt = self.tarolo.fiok(sid)
        dsz = sub.data.get(CONF_DIJSZABAS)
        if dsz not in ("villany/a1", "villany/h"):
            raise ValueError("Éves kimutatás csak A1 és H díjszabású villanyfióknál készül.")
        fiok = self._otthon_bazissal(sub, fiok_motorba(dict(sub.data), tarolt))
        # Évhatárok: a fiók éves (elszámoló) leolvasásai – a szerződésváltás miatti kényszerített évkezdet nélkül –, a
        # mérő kezdőállása és az otthon közös éves leolvasása.
        napok = {d(lo["datum"]) for m in tarolt.get("merok", []) for lo in m.get("leolvasasok", [])
                 if lo.get("elszamolasi") and not lo.get("evkezdet")}
        if origo := tarolt.get("kezdo_origo"):
            napok.add(d(origo["datum"]))
        if kozos := self._otthon_eves_leolvasas("villany"):
            napok.add(kozos)
        jeloltek = kimutatas.ev_jeloltek(sorted(napok))
        if not jeloltek:
            raise ValueError("Ehhez két éves leolvasás (vagy kezdőállás és éves leolvasás) kell.")
        # Alapból a legutóbbi legalább ~5 hónapos év (a H-idényváltás is jelölt elszámoló leolvasás lehet).
        alap = next((x for x in jeloltek if (x[1] - x[0]).days >= 150), jeloltek[0])
        tol, ig = next((x for x in jeloltek if ev_tol and x[0] == ev_tol), alap)
        csatorna_alias = {"vetelezes": ("vetelezes", "fo")}

        def allas(csat: str, nap: date) -> tuple[Decimal, bool] | None:
            pontok = sorted(
                [(d(lo["datum"]), Decimal(str(lo["allas"])))
                 for m in tarolt.get("merok", []) for lo in m.get("leolvasasok", [])
                 if (lo.get("csatorna") or "vetelezes") in csatorna_alias.get(csat, (csat,)) and lo.get("tipus") != "automatikus"]
                # a mérő kezdőállása (beépítés) is mérőállás – nincs mindig leolvasásként rögzítve
                + [(d(m["beepitve"]), Decimal(str(k)))
                   for m in tarolt.get("merok", []) if m.get("beepitve")
                   and (k := m.get("kezdo_allas" if csat == "vetelezes" else f"kezdo_{csat}")) not in (None, "")]
            )
            pontos = [a for n, a in pontok if n == nap]
            if pontos:
                return pontos[-1], True
            elotte = [(n, a) for n, a in pontok if n < nap]
            utana = [(n, a) for n, a in pontok if n > nap]
            if not elotte or not utana:
                return None
            (n1, a1), (n2, a2) = elotte[-1], utana[0]
            return a1 + (a2 - a1) * Decimal((nap - n1).days) / Decimal((n2 - n1).days), False  # arányosan (becsült)

        def arak(azon: str, nap: date) -> dict[str, Any]:
            return self.tar.felold(azon, nap, sub.data[CONF_SZOLGALTATO], fiok.feluliras).dijak

        a1 = self.tar.felold("villany/a1", ig, sub.data[CONF_SZOLGALTATO], fiok.feluliras)
        keret = (a1.szabalyok.get("keret") or {})
        eredmeny = kimutatas.kimutatas(
            dsz, tol, ig, allas, tarolt.get("szamlak") or {}, arak,
            keret_ev=Decimal(str(keret.get("ev_mennyiseg", 2523))), tetel_hatar=keret.get("tetel_hatar"),
            kezdo=bool(origo) and d(origo["datum"]) == tol,
        )
        ugyfel = max(((x.get("kelte") or "", x["ugyfel"]) for x in (tarolt.get("szamlak") or {}).values() if x.get("ugyfel")), default=None)
        dij_a1 = arak("villany/a1", ig)
        # Pénzügyi teljesítés: az elszámoló sorok fizetése, és az év összes (nem sztornó) számlája – amelynek időszaka az
        # évbe esik – fizetendővel, határidővel, fizetéssel.
        fiz = self.fizetes_allapotok(sid)
        for s_ in eredmeny["sorok"]:
            if s_.get("sorszam"):
                s_["fizetes"] = fiz.get(s_["sorszam"])
        bef = []
        kihagy = _ervenytelenek(tarolt.get("szamlak") or {})
        for k, x in (tarolt.get("szamlak") or {}).items():
            i = x.get("idoszak")
            if k in kihagy or not i or d(i[1]) <= tol or d(i[0]) > ig:
                continue
            bef.append({"sorszam": k, "kelte": x.get("kelte"), "tipus": x.get("tipus"), "idoszak": i, "fizetes": fiz.get(k)})
        bef.sort(key=lambda y: y["kelte"] or "")
        fizetendo = [b_["fizetes"] for b_ in bef if b_["fizetes"] and not b_["fizetes"]["nincs_fizetendo"] and b_["fizetes"]["osszeg"]]
        eredmeny["befizetesek"] = {
            "szamlak": bef,
            "fizetendo_ft": sum(a_["osszeg"] for a_ in fizetendo),
            "fizetve_ft": sum(a_["osszeg"] for a_ in fizetendo if a_["fizetve"]),
            "nyitott_ft": sum(a_["osszeg"] for a_ in fizetendo if not a_["fizetve"]),
            "nyitott_db": sum(1 for a_ in fizetendo if not a_["fizetve"]),
            "jovairas_ft": sum(b_["fizetes"]["osszeg"] for b_ in bef if b_["fizetes"] and (b_["fizetes"]["osszeg"] or 0) < 0),
        }
        return eredmeny | {
            "fiok": sub.title, "jeloltek": [[a.isoformat(), b.isoformat()] for a, b in jeloltek],
            "ugyfel": ugyfel[1] if ugyfel else {}, "mero": (tarolt.get("merok") or [{}])[-1].get("gyari_szam"),
            "szolgaltato": (self.tar.szolgaltatok.get(sub.data.get(CONF_SZOLGALTATO)) or {}).get("nev"),
            "dijak": {"a1": {k: float(v) for k, v in dij_a1.items() if isinstance(v, (int, float, Decimal))},
                      **({"h": {k: float(v) for k, v in arak("villany/h", ig).items() if isinstance(v, (int, float, Decimal))}} if dsz == "villany/h" else {})},
            "keret_ev": float(keret.get("ev_mennyiseg", 2523)),
            "allasok": {
                c: {x: (float(v[0]) if (v := allas(c, date.fromisoformat(x))) else None)
                    for x in sorted({tol.isoformat(), ig.isoformat(), *(s["ig"] for s in eredmeny["sorok"])})}
                for c in (("h_teli", "h_nyari") if dsz == "villany/h" else ("vetelezes",))
            },
        }

    async def tetelek(self, sid: str, tol: date, ig: date) -> dict[str, Any]:
        """Tájékoztató, számlaszerű tételes bontás egy (még nem számlázott) időszakra [tol, ig] (ig is benne van): a
        motor tételsorai összevonva (azonos tétel és egységár egymás után egy sor), nettó, ÁFA, bruttó. Ha az
        időszak a jövőbe nyúlik, a fogyasztás a mai napig mért, utána napi átlaggal kivetített (becslés)."""
        sub = self.fiokok()[sid]
        tarolt = self.tarolo.fiok(sid)
        fiok = self._otthon_bazissal(sub, fiok_motorba(dict(sub.data), tarolt))
        most = helyi_most()
        t0 = datetime.combine(tol - timedelta(days=2), datetime.min.time())
        fiok = await self._zona_fiok(sub, fiok, t0)
        fiok = await self._d_fiok(sid, sub, fiok, most)
        if beallitas.fix_dijas(sub.data):
            szamlalok = [Szamlalo([Pont(t0, Decimal(0), True), Pont(most, Decimal(0), True)]) for _ in fiok.csatornak]
        else:
            szamlalok = [await self.szamlalo(sid, fiok, t0, most, i) for i in range(len(fiok.csatornak))]
        vege = ig + timedelta(days=1)
        extra = elszamolasi_napok(tarolt)
        if vege > most.date():
            e = nyitott(fiok, self.tar, tol, vege, szamlalok, most, extra_hatarok=extra).varhato
            kivetitve = True
        else:
            e = szamol(fiok, self.tar, tol, vege, szamlalok, extra_hatarok=extra)
            kivetitve = False
        sorok: list[dict[str, Any]] = []
        for sz in e.szeletek:
            for t in sz.tetelek:
                elozo = sorok[-1] if sorok else None
                if elozo and (elozo["nev"], elozo["ar"], elozo["afa"]) == (t["nev"], t["ar"], t["afa"]) and elozo["_ig"] == sz.tol:
                    elozo["mennyiseg"] += t["mennyiseg"]
                    elozo["netto"] += t["netto"]
                    elozo["_ig"] = sz.ig
                    continue
                # Azonos tétel más időszakban (pl. a keret más szeletben): ha az ár is azonos, összevonjuk.
                azonos = next((x for x in sorok if (x["nev"], x["ar"], x["afa"]) == (t["nev"], t["ar"], t["afa"])), None)
                if azonos:
                    azonos["mennyiseg"] += t["mennyiseg"]
                    azonos["netto"] += t["netto"]
                    azonos["_ig"] = max(azonos["_ig"], sz.ig)
                    continue
                sorok.append({**t, "_tol": sz.tol, "_ig": sz.ig})
        # A 0 Ft-os tételt (pl. a keret alatt maradt fogyasztás „piaci” sora) nem mutatjuk; az alapdíj a teljes időszaké.
        sorok = [x for x in sorok if round(x["netto"]) != 0]
        for x in sorok:
            if x["nev"] == "Alapdíj":
                x["_tol"], x["_ig"] = tol, vege
        afa: dict[str, Decimal] = {}
        for x in sorok:
            if x["afa"] is not None:
                afa[str(x["afa"])] = afa.get(str(x["afa"]), Decimal(0)) + x["netto"]
        netto = sum((x["netto"] for x in sorok), Decimal(0))
        afa_ft = {k: (v * Decimal(k) / 100).quantize(Decimal(1)) for k, v in afa.items()}
        brutto = int(e.osszesen_ft)
        return {
            "tol": tol.isoformat(), "ig": ig.isoformat(), "kivetitve": kivetitve, "becsult": bool(e.becsult),
            "mennyiseg": round(float(e.mennyiseg), 2), "egyseg": EGYSEG.get(sub.data[CONF_KOZMU], ""),
            "sorok": [{
                "nev": x["nev"], "tol": x["_tol"].isoformat(), "ig": (x["_ig"] - timedelta(days=1)).isoformat(),
                "mennyiseg": round(float(x["mennyiseg"]), 3), "egyseg": x["egyseg"], "ar": round(float(x["ar"]), 4),
                "netto": round(float(x["netto"]), 2), "afa": float(x["afa"]) if x["afa"] is not None else None,
            } for x in sorok],
            "netto": round(float(netto)), "afa": {k: int(v) for k, v in afa_ft.items()},
            "brutto": brutto, "kerekites": brutto - int(round(float(netto))) - sum(int(v) for v in afa_ft.values()) if afa_ft else 0,
        }

    async def lezartak_ujraszamolasa(self, sid: str, tol: date | None = None) -> dict[str, Any]:
        """A lezárt időszakok újraszámolása a fiók MOSTANI módja szerint (pl. diktálási időszakokra), a díjszabás
        kezdetétől (vagy tol-tól) a nyitott időszakig. A korábbi lezárások ettől kezdve lecserélődnek."""
        sub = self.fiokok()[sid]
        tarolt = self.tarolo.fiok(sid)
        fiok = self._otthon_bazissal(sub, fiok_motorba(dict(sub.data), tarolt))
        mod, nap = beallitas.idoszak_mod(sub.data)
        dhatarok = diktalasi_hatarok(tarolt, mod == "leolvasas") if mod in DIKT_MODOK else None
        dablak = diktalasi_ablak(tarolt, sub.data) if mod in DIKT_MODOK else None
        most = helyi_most()
        nyitott_tol, _ = idoszak(most.date(), mod, nap, dhatarok, dablak)
        legkorabbi = max(
            d(sub.data.get(CONF_DIJSZABAS_TOL)) or date(2000, 1, 1),
            min((d(m["beepitve"]) for m in tarolt["merok"]), default=date(2000, 1, 1)),
        )
        kezdet = max(tol or legkorabbi, legkorabbi)
        # Diktálásnál az első időszak egy határon kezdődjön (a kezdet utáni első diktálás); naptári (és egyedi napos)
        # időszaknál a mérő kezdetétől induló töredék első időszak is számít (pl. 07.15-én felvett fiók júliusa).
        if mod in DIKT_MODOK and idoszak(kezdet, mod, nap, dhatarok, dablak)[0] < kezdet:
            kezdet = idoszak(kezdet, mod, nap, dhatarok, dablak)[1]
        # Egy régi (pl. más módban vagy a v1-ből átvett) időszak, amely a kezdeten átnyúlik, átfedne az újakkal:
        # az újraszámolás az ő elejétől induljon, így se átfedés, se hézag nem marad.
        atnyulo = [d(x["tol"]) for x in tarolt["lezart"] if x["tol"] < kezdet.isoformat() < x["ig"]]
        if atnyulo:
            kezdet = max(min(atnyulo), legkorabbi)
        hatarok = elszamolasi_napok(tarolt)
        t0 = datetime.combine(kezdet, datetime.min.time())
        fiok = await self._zona_fiok(sub, fiok, t0)
        fiok = await self._d_fiok(sid, sub, fiok, most)
        szamlalok = [await self.szamlalo(sid, fiok, t0, most, i) for i in range(len(fiok.csatornak))]
        uj, hibak = [], []
        p = kezdet
        while p < nyitott_tol:
            _, q = idoszak(p, mod, nap, dhatarok, dablak)
            q = min(q, nyitott_tol)
            try:
                e = szamol(fiok, self.tar, p, q, szamlalok, extra_hatarok=hatarok)
                uj.append(eredmeny_tarolhato(e) | {"rogzitve": most.isoformat(), "forras": f"ujraszamolt ({mod})"})
            except (NincsAdat, DijszabasHiba) as err:
                hibak.append(f"{p.isoformat()}: {err}")
            p = q
        regi = [x for x in tarolt["lezart"] if x["tol"] < kezdet.isoformat()]
        torolt = len(tarolt["lezart"]) - len(regi)
        tarolt["lezart"] = regi + uj
        tarolt["nyitott_tol"] = nyitott_tol.isoformat()
        await self.tarolo.ment()
        await self.async_request_refresh()
        return {
            "mod": mod,
            "kezdet": kezdet.isoformat(),
            "nyitott_tol": nyitott_tol.isoformat(),
            "torolt": torolt,
            "uj": [{"tol": x["tol"], "ig": x["ig"], "mennyiseg": x["mennyiseg"], "osszesen_ft": x["osszesen_ft"]} for x in uj],
            "hibak": hibak,
        }

    def _diktalt_szamla(self, fiok: Fiok, tarolt: dict[str, Any], szamlalok: list[Szamlalo]) -> dict[str, Any] | None:
        """Átalánynál: a legutóbbi számla elszámolt időszaka utáni legutolsó diktált (saját) állás szerinti számla –
        a számlázott időszak vége utáni naptól a diktálás napjáig mért fogyasztás díja (alapdíjjal)."""
        idoszakok = [i for x in (tarolt.get("szamlak") or {}).values() if (i := _szamlazott_idoszak(x))]
        if not idoszakok:
            return None
        tol = max([i[1] for i in idoszakok] + _rendezett_vegek(tarolt)) + timedelta(days=1)
        diktalt = sorted(
            (d(lo["datum"]), lo) for m in tarolt.get("merok") or [] for lo in m.get("leolvasasok", [])
            if lo.get("diktalt") and (lo.get("csatorna") or "vetelezes") == "vetelezes" and d(lo["datum"]) > tol
        )
        if not diktalt:
            return None
        ig, lo = diktalt[-1]
        try:
            e = szamol(fiok, self.tar, tol, ig, szamlalok, extra_hatarok=elszamolasi_napok(tarolt))
        except (NincsAdat, DijszabasHiba, ValueError) as err:
            _LOGGER.debug("diktált számla nem számolható: %s", err)
            return None
        return {
            "datum": ig.isoformat(), "allas": float(Decimal(str(lo["allas"]))), "tol": tol.isoformat(),
            "mennyiseg": round(float(e.mennyiseg), 1), "osszeg": int(e.osszesen_ft),
        }

    def _becsult_diktalt_szamla(
        self, fiok: Fiok, tarolt: dict[str, Any], szamlalok: list[Szamlalo], most: datetime, periodus: int | None = None
    ) -> tuple[dict[str, Any] | None, NyitottIdoszak | None]:
        """Átalányos, de diktálás szerint számlázott fiók (az utolsó két számla elszámoló, vagy az utóbbi 120 napban
        diktáltál – motor.kovetkezo_szamla): a következő számla a legutóbbi számla utolsó napja utántól a várható
        diktálás napjáig tart; díja a saját mérésből, napi átlaggal kivetítve. Becslés („becsult”), amíg nem diktálsz."""
        szamlak = sorted(
            (x for x in (tarolt.get("szamlak") or {}).values() if x.get("tipus") != "storno" and _szamlazott_idoszak(x)),
            key=lambda x: (_szamlazott_idoszak(x)[1], x.get("kelte") or ""),
        )
        if not szamlak:
            return None, None
        ma = most.date()
        diktalasok = [d(lo["datum"]) for m in tarolt.get("merok") or [] for lo in m.get("leolvasasok", []) if lo.get("diktalt")]
        if not diktalas_szerint_szamlaz([x.get("tipus") for x in szamlak], diktalasok, ma):
            return None, None
        utolso_vege = max([_szamlazott_idoszak(szamlak[-1])[1]] + _rendezett_vegek(tarolt))
        evhatar = fiok.eves_bazis if fiok.eves_bazis and fiok.eves_bazis > utolso_vege else None
        idoszak_ = kovetkezo_szamla_idoszak(utolso_vege, ma, diktalasi_ablak(tarolt), periodus or 1, evhatar)
        if idoszak_ is None:
            return None, None
        tol, ig = idoszak_
        if evhatar and ig == evhatar and evhatar < ma:
            # Az éves leolvasás már megvolt: a számla addig lezárt időszak (valódi állással) – a hívó „még nem érkezett
            # számlaként” veszi, és a folyó időszakot a leolvasás utántól a következő diktálásig számolja.
            allas = next((lo["allas"] for m in tarolt.get("merok") or [] for lo in m.get("leolvasasok", [])
                          if lo.get("elszamolasi") and lo["datum"] == evhatar.isoformat()
                          and (lo.get("csatorna") or "vetelezes") in ("vetelezes", "fo")), None)
            try:
                # A mérőállás a nap elején áll a számlálóban: a fogyasztás a legutóbbi számla záró állásától (utolsó
                # napja) az éves leolvasásig – a számlán „utolsó nap másnapja – leolvasás napja”.
                e = szamol(fiok, self.tar, utolso_vege, ig, szamlalok, extra_hatarok=elszamolasi_napok(tarolt))
            except (NincsAdat, DijszabasHiba, ValueError) as err:
                _LOGGER.debug("éves leolvasásig tartó számla nem számolható: %s", err)
                return None, None
            return {
                "datum": ig.isoformat(), "allas": float(Decimal(str(allas))) if allas is not None else None,
                "tol": tol.isoformat(), "eves": True,
                "mennyiseg": round(float(e.mennyiseg), 1), "osszeg": int(e.osszesen_ft),
            }, None
        try:
            ny = nyitott(fiok, self.tar, tol, ig + timedelta(days=1), szamlalok, most, extra_hatarok=elszamolasi_napok(tarolt))
        except (NincsAdat, DijszabasHiba, ValueError) as err:
            _LOGGER.debug("becsült diktált számla nem számolható: %s", err)
            return None, None
        return {
            "datum": ig.isoformat(), "allas": None, "tol": tol.isoformat(), "becsult": True,
            "mennyiseg": round(float(ny.varhato.mennyiseg), 1), "osszeg": int(ny.varhato.osszesen_ft),
        }, ny

    @staticmethod
    def _szamla_alapu_allasok(tarolt: dict[str, Any], most: datetime) -> list[dict[str, Any]]:
        """Átalányszámlánként a szolgáltató által feltételezett mérőállás az elszámolt időszak végén: a mérő utolsó
        valódi állása (leolvasás, diktálás, ill. a mérő kezdőállása) + az azóta számlázott átalány-mennyiségek.
        Egy valódi (pl. diktált) állás után a lánc onnan indul újra. Tájékoztató („számla alapján”): a fogyasztás
        számítását nem befolyásolja."""
        merok = tarolt.get("merok") or []
        hatar = most.date() - timedelta(days=400)
        out: list[dict[str, Any]] = []
        elozo: tuple[date, Decimal] | None = None
        szamlak = sorted(
            ((i, k, x) for k, x in (tarolt.get("szamlak") or {}).items()
             if (i := _szamlazott_idoszak(x)) and _atalany_mennyiseg_szamlan(x) is not None),
            key=lambda y: y[0],
        )
        for (tol, ig), sorszam, x in szamlak:
            # Az időszak elején aktív mérő valódi állásai (a kezdőállással együtt).
            aktiv = [m for m in merok if d(m["beepitve"]) <= tol and (not m.get("kiszerelve") or d(m["kiszerelve"]) > tol)]
            if not aktiv:
                elozo = None
                continue
            m = aktiv[-1]
            pontok = [(d(m["beepitve"]), Decimal(str(m.get("kezdo_allas") or 0)))] + [
                (d(lo["datum"]), Decimal(str(lo["allas"]))) for lo in m.get("leolvasasok", [])
                if (lo.get("csatorna") or "vetelezes") == "vetelezes" and d(lo["datum"]) <= tol
            ]
            r_nap, r_allas = max(pontok, key=lambda p: (p[0], p[1]))
            alap = elozo[1] if elozo and elozo[0] >= r_nap else r_allas
            allas = alap + _atalany_mennyiseg_szamlan(x)
            elozo = (ig, allas)
            if ig >= hatar:
                out.append({"datum": ig.isoformat(), "allas": round(float(allas), 3), "sorszam": sorszam,
                            "mennyiseg": float(_atalany_mennyiseg_szamlan(x))})
        return out

    async def _szamlazasi(
        self, sid: str, fiok: Fiok, ny: NyitottIdoszak | None, atalany_e: dict[str, Any] | None,
        esedekes_e: dict[str, Any] | None, periodus: int | None, most: datetime, fix: bool,
    ) -> dict[str, Any] | None:
        """Többhavi utólagos számlázás ablaka, a mért fogyasztással (lezárt ablaknál a teljes, különben eddig+várható)."""
        napi = Decimal(str(atalany_e["napi"])) if atalany_e else None
        ablak = szamlazasi_ablak(most.date(), int(periodus or 0), esedekes_e or {}, napi, szamlazasi_eltolas(self.tarolo.fiok(sid)),
                                 minimum=1 if fix else 2)
        if ablak is None or fix:
            return ablak
        tol = datetime.combine(ablak["tol"], datetime.min.time())
        ig = datetime.combine(ablak["ig"], datetime.min.time())
        try:
            szl = await self.szamlalo(sid, fiok, tol, most, 0)
            eddig, becsult = szl.fogyasztas(tol, min(ig, most))
        except NincsAdat:
            return ablak
        napi_atlag = ny.napi_atlag[0] if ny and ny.napi_atlag else Decimal(0)
        hatra = Decimal(max((ig - most).total_seconds(), 0) / 86400)
        ablak["mennyiseg_eddig"] = round(float(eddig), 2)
        ablak["mennyiseg_varhato"] = round(float(eddig + (0 if ablak["lezart"] else napi_atlag * hatra)), 1)
        ablak["mennyiseg_becsult"] = becsult
        if atalany_e and atalany_e.get("mennyiseg_napi") is not None:
            ablak["atalany_mennyiseg"] = round(float(atalany_e["mennyiseg_napi"]) * ablak["napok"], 1)
        ablak["bontas"] = await self._ablak_bontas(sid, fiok, ablak, tol, most)
        return ablak

    async def _ablak_bontas(self, sid: str, fiok: Fiok, ablak: dict[str, Any], tol: datetime, most: datetime) -> dict[str, Any] | None:
        """A számlázási ablak tételes díja (víz: vízdíj a főmérő, csatornadíj a főmérő − almérő után, alapdíj).
        Lezárt ablaknál a teljes időszak, folyó ablaknál a mai napig."""
        vege = ablak["ig"] if ablak["lezart"] else most.date()
        if vege <= ablak["tol"]:
            return None
        try:
            szamlalok = [await self.szamlalo(sid, fiok, tol, most, i) for i in range(len(fiok.csatornak))]
            e = szamol(fiok, self.tar, ablak["tol"], vege, szamlalok)
        except (NincsAdat, DijszabasHiba, KeyError, ValueError) as err:
            _LOGGER.debug("számlázási ablak díja nem számolható: %s", err)
            return None
        fo = [s for s in e.szeletek if s.csatorna != "almero"]
        al = [s for s in e.szeletek if s.csatorna == "almero"]
        # Számlázott mennyiség: egész m³-re kerekített óraállásokból (a díj is ebből), mellette a mért.
        def szamlazott(sz: list) -> Decimal:
            return sum(((s.elszamolt if s.elszamolt is not None else s.mennyiseg) for s in sz), Decimal(0))

        fo_q, al_q = szamlazott(fo), szamlazott(al)
        fo_mert = sum((s.mennyiseg for s in fo), Decimal(0))
        al_mert = sum((s.mennyiseg for s in al), Decimal(0))
        csat_ft = sum((s.csatorna_ft for s in e.szeletek), Decimal(0))
        viz_ft = sum((s.energia_ft - s.csatorna_ft for s in fo), Decimal(0))
        alap_ft = sum((s.alapdij_ft for s in e.szeletek), Decimal(0))
        # A háztartás távhős melegvizének szennyvize (meleg szennyvíz) – a vízmű a csatornadíjjal számlázza.
        msz = self._meleg_szennyviz(fiok, ablak["tol"], vege)
        msz_m3, msz_ft = (msz[0], msz[1]) if msz else (Decimal(0), Decimal(0))
        return {
            "meleg_szennyviz_m3": round(float(msz_m3), 2) if msz else None,
            "meleg_szennyviz_ft": int(round(msz_ft)) if msz else None,
            "vege": vege.isoformat(),
            "fo_m3": round(float(fo_q), 2),
            "almero_m3": round(float(al_q), 2) if al else None,
            "csatorna_m3": round(float(fo_q - al_q), 2),
            "fo_m3_mert": round(float(fo_mert), 2),
            "almero_m3_mert": round(float(al_mert), 2) if al else None,
            "viz_ft": int(round(viz_ft)),
            "csatorna_ft": int(round(csat_ft)),
            "alapdij_ft": int(round(alap_ft)),
            "osszesen_ft": int(round(viz_ft + csat_ft + alap_ft + msz_ft)),
            "becsult": e.becsult,
        }

    def _beolvas(self, fajl: Path) -> Any:
        """szamlak.beolvas_fajl gyorsítótárral (végrehajtó szálon fut). Másolatot ad: a hívó módosítja."""
        st = fajl.stat()
        kulcs = (str(fajl), st.st_mtime, st.st_size)
        if kulcs not in self._fajl_cache:
            self._fajl_cache[kulcs] = szamlak.beolvas_fajl(fajl)
        return copy.deepcopy(self._fajl_cache[kulcs])

    async def _szamlak_feldolgozasa(self, sid: str, sub: ConfigSubentry, tarolt: dict[str, Any]) -> bool:
        """Új számlák a fiók mappájából: befizetés, valódi mérőállások, fűtőértékek."""
        mappa = Path(self.hass.config.config_dir) / sub.data[CONF_SZAMLA_MAPPA]
        valtozott = False
        # Ha a mappa, a számla-mérők, a díjszabás vagy a mérő kezdő adatai megváltoztak, a mappát újraolvassuk
        # (pl. a szűrőt a számlák után adták meg, vagy a kezdőnapot korábbira tették) – a kézi számlák maradnak.
        beall = {
            "mappa": sub.data.get(CONF_SZAMLA_MAPPA), "merok": str(sub.data.get(CONF_SZAMLA_MEROK) or ""),
            "dijszabas": sub.data.get(CONF_DIJSZABAS), "beepitve": str(sub.data.get(CONF_BEEPITVE)),
            "kezdo_allas": str(sub.data.get(CONF_KEZDO_ALLAS)), "gyari_szam": str(sub.data.get(CONF_GYARI_SZAM) or ""),
        }
        elozo = tarolt.get("szamla_beallitas")
        if elozo is not None and elozo != beall and tarolt.get("feldolgozott_fajlok"):
            mappas_adatok_torlese(tarolt)
            _LOGGER.info("%s: a számla-beállítás megváltozott, a számlamappa újraolvasása", sub.title)
        if elozo != beall:
            tarolt["szamla_beallitas"] = beall
            valtozott = True
        if tarolt.get("szamlak") and tarolt.get("szamla_import_verzio", 1) < IMPORT_VERZIO:
            # Régi import-verzió: a mappa összes számláját újraolvassuk, és a belőlük jött állásokat rendbe tesszük.
            minden = await self.hass.async_add_executor_job(
                lambda: [x for x in (self._beolvas(f) for f in szamlak.uj_fajlok(mappa, set())) if x]
            )
            szamlak.meresi_pontok_kapcsolasa(minden, tarolt.setdefault("meresi_pontok", {}))
            db = ujraertekel(tarolt, minden)
            _LOGGER.info("%s: számlából jött állások újraértékelve (%s módosítás)", sub.title, db)
            valtozott = True
        if tarolt.get("pdf_olvaso_verzio", 1) < szamlak.PDF_OLVASO_VERZIO:
            # Új PDF-olvasó: csak a korábban FEL NEM ISMERT fájlokat próbáljuk újra (a szándékosan törölt, de
            # felismert számlák így nem jönnek vissza). Az 1-es verzióról (még ismeretlen-lista nélkül) az XML-pár
            # nélküli, számlát nem adott PDF-ek is.
            ujra = set(tarolt.get("ismeretlen_fajlok", []))
            if tarolt.get("pdf_olvaso_verzio", 1) < 2:
                ismert_fajl = {x.get("fajl") for x in (tarolt.get("szamlak") or {}).values()}
                ujra |= {
                    f for f in tarolt.get("feldolgozott_fajlok", [])
                    if f.lower().endswith(".pdf") and f not in ismert_fajl and not (mappa / f).with_suffix(".xml").exists()
                }
            tarolt["feldolgozott_fajlok"] = [f for f in tarolt.get("feldolgozott_fajlok", []) if f not in ujra]
            tarolt.pop("nem_olvasott_fajlok", None)
            tarolt["pdf_olvaso_verzio"] = szamlak.PDF_OLVASO_VERZIO
            valtozott = True
        # A mappából azóta törölt, fel nem ismert fájlokról ne szóljunk tovább; a már rögzített számla
        # átnevezett másolata (pl. kézzel bemásolt „<sorszám>.pdf”) sem ismeretlen.
        ism = tarolt.get("ismeretlen_fajlok") or []
        megvan = await self.hass.async_add_executor_job(
            lambda: [n for n in ism if (mappa / n).exists() and not _ismert_masolat(n, tarolt)]
        )
        if megvan != ism:
            tarolt["ismeretlen_fajlok"] = megvan
            valtozott = True
        if tarolt.get("meta_potlas", 0) < 3 and tarolt.get("szamlak"):
            # A tárolt számlák új mezője (következő leolvasás) – csak ez pótlódik, a számla maga nem íródik újra
            # (a kézzel javított/törölt számlák így nem jönnek vissza). Csak a legutóbbi ~13 hónap számlái.
            hatar = (date.today() - timedelta(days=400)).isoformat()
            hianyos = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items()
                       if x.get("fajl") and ("kovetkezo_leolvasas" not in x or ("elszamolt_kwh" not in x and "elszamolt_gaz" not in x))
                       and x.get("kelte", "") >= hatar]

            def potol() -> dict[str, dict[str, Any]]:
                out: dict[str, dict[str, Any]] = {}
                for k, nev in hianyos:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if not sz:
                        continue
                    uj: dict[str, Any] = {}
                    if sz.kovetkezo_leolvasas:
                        uj["kovetkezo_leolvasas"] = [x.isoformat() for x in sz.kovetkezo_leolvasas]
                    if sz.elszamolt_kwh is not None:
                        uj["elszamolt_kwh"] = str(sz.elszamolt_kwh)
                    if sz.elszamolt_gaz:
                        uj["elszamolt_gaz"] = {kk: str(vv) for kk, vv in sz.elszamolt_gaz.items()}
                    if sz.kovetkezo_resz_m3 is not None:
                        uj["kovetkezo_resz_m3"] = str(sz.kovetkezo_resz_m3)
                    out[k] = uj
                return out

            for k, v in (await self.hass.async_add_executor_job(potol)).items():
                tarolt["szamlak"][k].update(v)
            tarolt["meta_potlas"] = max(3, tarolt.get("meta_potlas", 0))
            valtozott = True
        if tarolt.get("storno_potlas", 0) < 1 and tarolt.get("szamlak"):
            # Régi, párosítatlan stornó (az MVM-XML-ben nincs hivatkozás): a sztornózott számla a PDF-párból
            # („Stornózott számla száma”), ennek híján a javított párosítással (a stornónál korábbi számla). Csak a
            # hivatkozás pótlódik: befizetés, mérőállás, számla nem íródik át.
            hianyos_st = [(k, x.get("fajl")) for k, x in tarolt["szamlak"].items() if x.get("tipus") == "storno" and not x.get("sztornozott")]

            def potol_storno() -> dict[str, str]:
                out: dict[str, str] = {}
                for k, nev in hianyos_st:
                    pdf = (mappa / nev).with_suffix(".pdf") if nev else None
                    if pdf and pdf.exists():
                        try:
                            if ref := szamlak.storno_hivatkozas(szamlak.pdf_szoveg(pdf, "plain")):
                                out[k] = ref
                        except Exception:  # noqa: BLE001 – olvashatatlan PDF: marad a párosítás
                            pass
                return out

            for k, ref in (await self.hass.async_add_executor_job(potol_storno)).items():
                tarolt["szamlak"][k]["sztornozott"] = ref
            storno_parositas(tarolt["szamlak"])
            for k, _ in hianyos_st:
                if ref := tarolt["szamlak"][k].get("sztornozott"):
                    _LOGGER.info("%s: a %s stornó a(z) %s számlát érvényteleníti (utólag párosítva)", sub.title, k, ref)
            tarolt["storno_potlas"] = 1
            valtozott = True
        if tarolt.get("mohu_hatarido_potlas", 0) < 1 and tarolt.get("szamlak"):
            # A MOHU-XML fizetési határideje és módja (korábban nem olvastuk ki – határidő nélkül a számla kimaradt a
            # kifizetetlenek közül). Csak ez a két mező pótlódik, ahol hiányzik.
            hianyos = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items()
                       if x.get("fajl") and x.get("forras") == "mohu" and not x.get("hatarido")]

            def potol_hatarido() -> dict[str, dict[str, Any]]:
                out: dict[str, dict[str, Any]] = {}
                for k, nev in hianyos:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.hatarido:
                        meta = szamla_meta(sz)
                        out[k] = {kk: meta[kk] for kk in ("hatarido", "fizetesi_mod") if meta.get(kk)}
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_hatarido)).items():
                tarolt["szamlak"][k].update(v)
            tarolt["mohu_hatarido_potlas"] = 1
            valtozott = True
        if tarolt.get("szamlaertek_potlas", 0) < 2 and tarolt.get("szamlak"):
            # A számla saját bruttó értéke és a levont részszámlák (a számla↔számítás összevetéshez) – csak ez
            # pótlódik, a számla maga nem íródik újra. Az utolsó ~3 év számlái.
            hatar = (date.today() - timedelta(days=1100)).isoformat()
            hianyos = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items()
                       if x.get("fajl") and "szamlaertek" not in x and x.get("kelte", "") >= hatar]

            def potol4() -> dict[str, dict[str, Any]]:
                out: dict[str, dict[str, Any]] = {}
                for k, nev in hianyos:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.szamlaertek is not None:
                        out[k] = {"szamlaertek": str(sz.szamlaertek)}
                        if sz.levont_szamlak:
                            out[k]["levont_szamlak"] = [[s, None if o is None else str(o)] for s, o in sz.levont_szamlak]
                return out

            for k, v in (await self.hass.async_add_executor_job(potol4)).items():
                tarolt["szamlak"][k].update(v)
            # 2: az MVM gáz-PDF régebbi nyomata (a számlaérték a „Bruttó számlaérték összesen” sorból) – újra.
            tarolt["szamlaertek_potlas"] = 2
            valtozott = True
        if tarolt.get("folyoszamla_potlas", 0) < 3 and tarolt.get("szamlak"):
            # MVM áram: a folyószámla-tételek (túlfizetés, átvezetés), az egyenleg és a kiszámlázott mennyiség – a
            # számla-ellenőrzéshez és a folyószámla-sorhoz; csak ezek pótlódnak. Az utolsó ~2 év számlái.
            hatar = (date.today() - timedelta(days=800)).isoformat()
            # A fájlnév nélkül rögzített (pl. feltöltött) számlánál a mappában a „<sorszám>.pdf”.
            jeloltek = [(k, x.get("fajl") or f"{k}.pdf") for k, x in tarolt["szamlak"].items()
                        if (x.get("fajl") or (mappa / f"{k}.pdf").exists()) and x.get("forras", "mvm_aram") == "mvm_aram"
                        and x.get("tipus") != "storno" and x.get("kelte", "") >= hatar and not str(k).startswith("kezi")]

            def potol6() -> dict[str, dict[str, Any]]:
                out: dict[str, dict[str, Any]] = {}
                for k, nev in jeloltek:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.sorszam == k and (meta := folyoszamla_meta(sz)):
                        out[k] = {**meta, "fajl": nev, **({"szamlaertek": str(sz.szamlaertek)} if sz.szamlaertek is not None else {})}
                return out

            for k, v in (await self.hass.async_add_executor_job(potol6)).items():
                tarolt["szamlak"][k].update(v)
            # A befizetés MVM villanynál a számla saját értéke (a fizetendő a közös folyószámla tételeit is tartalmazza).
            for r in tarolt.get("reszszamlak", []):
                x_ = tarolt["szamlak"].get(r.get("sorszam") or "")
                if x_ and x_.get("forras") == "mvm_aram" and x_.get("tipus") != "storno" and x_.get("szamlaertek") is not None:
                    r["osszeg"] = x_["szamlaertek"]
            # 2: minden tétel a számlaérték és a fizetendő között (pl. több sorba tördelt kötbér), a befizetés pedig MVM
            # villanynál mindig a számlaérték. 3: a késedelmi kamat sorában a „számla(k): …” sorszámok nem összegek; a
            # fájlnév nélkül rögzített számlák is (<sorszám>.pdf) – a pénzügyi teljesítéshez.
            tarolt["folyoszamla_potlas"] = 3
            valtozott = True
        if tarolt.get("gaz_egyeb_potlas", 0) < 1 and tarolt.get("szamlak"):
            # MVM gáz-részszámla: a „Támogatás, túlfizetés” beszámítás (egy korábbi elszámoló jóváírása) és a számla
            # saját bruttó értéke – különben a folyószámla a jóváírást kétszer veszi figyelembe. Minden ilyen számla.
            jeloltek_g = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items()
                          if x.get("forras") == "mvm_gaz" and x.get("tipus") == "resz" and str(x.get("fajl", "")).endswith(".xml")]

            def potol_g() -> dict[str, dict[str, Any]]:
                out: dict[str, dict[str, Any]] = {}
                for k, nev in jeloltek_g:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.sorszam == k and sz.egyeb_tetelek and sz.szamlaertek is not None:
                        out[k] = {"szamlaertek": str(sz.szamlaertek), "egyeb_tetelek": [[n, str(o)] for n, o in sz.egyeb_tetelek]}
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_g)).items():
                tarolt["szamlak"][k].update(v)
                for r in tarolt.get("reszszamlak", []):
                    if r.get("sorszam") == k:
                        r["osszeg"] = v["szamlaertek"]
            tarolt["gaz_egyeb_potlas"] = 1
            valtozott = True
        if tarolt.get("gaz_folyoszamla_potlas", 0) < 1 and tarolt.get("szamlak"):
            # MVM gáz: a PDF-párból a számlán közölt folyószámla-egyenleg (a kivonat összevetéséhez) – minden számlára.
            jeloltek_gf = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items()
                           if x.get("forras") == "mvm_gaz" and x.get("fajl") and x.get("folyoszamla") is None]

            def potol_gf() -> dict[str, str]:
                out: dict[str, str] = {}
                for k, nev in jeloltek_gf:
                    pdf = (mappa / nev).with_suffix(".pdf")
                    if pdf.exists():
                        v = szamlak.mvm_folyoszamla(szamlak.pdf_szoveg(pdf, "plain"))[0]
                        if v is not None:
                            out[k] = str(v)
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_gf)).items():
                tarolt["szamlak"][k]["folyoszamla"] = v
            tarolt["gaz_folyoszamla_potlas"] = 1
            valtozott = True
        if tarolt.get("dakov_potlas", 0) < 1 and tarolt.get("szamlak"):
            # DAKÖV: a fizetési határidő és a számlán közölt folyószámla-egyenleg (a befizetések visszafejtéséhez) –
            # minden DAKÖV-számlára.
            jeloltek_d = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items() if x.get("forras") == "dakov" and x.get("fajl")]

            def potol_d() -> dict[str, dict[str, Any]]:
                out: dict[str, dict[str, Any]] = {}
                for k, nev in jeloltek_d:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.sorszam == k:
                        v = {**({"hatarido": sz.hatarido.isoformat()} if sz.hatarido else {}),
                             **({"folyoszamla": str(sz.folyoszamla)} if sz.folyoszamla is not None else {})}
                        if v:
                            out[k] = v
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_d)).items():
                tarolt["szamlak"][k].update(v)
            tarolt["dakov_potlas"] = 1
            valtozott = True
        if tarolt.get("hvsz_potlas", 0) < 1 and tarolt.get("szamlak"):
            # HVSZ: a PDF-párból a számlán közölt folyószámla-egyenleg és az elszámoló (hődíj-korrekció) teljes időszaka.
            jeloltek_h = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items() if x.get("forras") == "hvsz" and x.get("fajl")]

            def potol_h() -> dict[str, dict[str, Any]]:
                out: dict[str, dict[str, Any]] = {}
                for k, nev in jeloltek_h:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.sorszam == k:
                        out[k] = {**({"folyoszamla": str(sz.folyoszamla)} if sz.folyoszamla is not None else {}),
                                  **({"idoszak": [sz.idoszak[0].isoformat(), sz.idoszak[1].isoformat()]} if sz.idoszak else {})}
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_h)).items():
                tarolt["szamlak"][k].update(v)
            tarolt["hvsz_potlas"] = 1
            valtozott = True
        if tarolt.get("hatarido_potlas", 0) < 1 and tarolt.get("szamlak"):
            # A fizetési határidő (pénzügyi teljesítés) a meglévő számlákra – az utolsó ~2 év fájljaiból.
            hatar = (date.today() - timedelta(days=800)).isoformat()
            jeloltek = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items()
                        if x.get("fajl") and x.get("tipus") != "storno" and x.get("kelte", "") >= hatar and not x.get("hatarido")]

            def potol_hatarido() -> dict[str, str]:
                out: dict[str, str] = {}
                for k, nev in jeloltek:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.hatarido:
                        out[k] = sz.hatarido.isoformat()
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_hatarido)).items():
                tarolt["szamlak"][k]["hatarido"] = v
            tarolt["hatarido_potlas"] = 1
            valtozott = True
        if tarolt.get("fizmod_potlas", 0) < 1 and tarolt.get("szamlak"):
            # A fizetési mód (pl. csoportos beszedés → a határidőn fizetett) a meglévő számlákra – az utolsó ~2 év fájljaiból.
            hatar = (date.today() - timedelta(days=800)).isoformat()
            jeloltek = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items()
                        if x.get("fajl") and x.get("tipus") != "storno" and x.get("kelte", "") >= hatar and not x.get("fizetesi_mod")]

            def potol_fizmod() -> dict[str, str]:
                out: dict[str, str] = {}
                for k, nev in jeloltek:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.fizetesi_mod:
                        out[k] = sz.fizetesi_mod
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_fizmod)).items():
                tarolt["szamlak"][k]["fizetesi_mod"] = v
            tarolt["fizmod_potlas"] = 1
            valtozott = True
        if tarolt.get("allas_potlas", 0) < 1 and tarolt.get("szamlak"):
            # A számlán szereplő induló és záró óraállás (becsült is) a meglévő számlákra – a folyószámla kivonathoz.
            jeloltek = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items()
                        if x.get("fajl") and x.get("tipus") != "storno" and "allasok" not in x]

            def potol_allas() -> dict[str, list]:
                out: dict[str, list] = {}
                for k, nev in jeloltek:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.meroallasok:
                        out[k] = szamla_allasok(sz)
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_allas)).items():
                tarolt["szamlak"][k]["allasok"] = v
            tarolt["allas_potlas"] = 1
            valtozott = True
        if tarolt.get("tetel_potlas", 0) < 1 and tarolt.get("szamlak"):
            # MVM áram: a számlarészletező tételei (az éves kimutatáshoz) és a levont részszámlák (az XML-ben nincsenek
            # benne – a PDF-párból) – az utolsó ~2 év számláira.
            hatar = (date.today() - timedelta(days=800)).isoformat()
            jeloltek = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items()
                        if x.get("fajl") and x.get("forras") == "mvm_aram" and x.get("tipus") != "storno" and x.get("kelte", "") >= hatar]

            def potol_tetel() -> dict[str, dict[str, Any]]:
                out: dict[str, dict[str, Any]] = {}
                for k, nev in jeloltek:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if sz and sz.tetelek:
                        out[k] = {"tetelek": sz.tetelek, **({"levont_szamlak": [[s, None if o is None else str(o)] for s, o in sz.levont_szamlak]}
                                                           if sz.levont_szamlak else {})}
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_tetel)).items():
                tarolt["szamlak"][k].update(v)
            tarolt["tetel_potlas"] = 1
            valtozott = True
        if tarolt.get("meta_potlas", 0) < 5 and tarolt.get("szamlak"):
            # Gáz: az elszámoló számlák végleges fűtőértéke és korrekciós tényezője (pl. 1,018) a lefedett hónapokra –
            # csak ez pótlódik, kiállítás szerinti sorrendben (a későbbi elszámoló az erősebb).
            elszamolok = sorted((x["kelte"], x["fajl"]) for x in tarolt["szamlak"].values()
                                if x.get("forras") == "mvm_gaz" and x.get("tipus") == "elszamolo" and x.get("fajl"))

            def potol5() -> list[Any]:
                return [sz for _, nev in elszamolok if (mappa / nev).exists() and (sz := self._beolvas(mappa / nev))]

            for sz in await self.hass.async_add_executor_job(potol5):
                fe = tarolt.setdefault("futoertekek", {})
                for honap, ertek in sz.futoertekek.items():
                    fe[honap] = str(ertek.normalize())
                if sz.korrekciok:
                    tarolt.setdefault("korrekciok", {}).update({h: str(v.normalize()) for h, v in sz.korrekciok.items()})
            tarolt["meta_potlas"] = 5
            valtozott = True
        if tarolt.get("mennyiseg_potlas", 0) < 1 and tarolt.get("szamlak"):
            # Az elszámolt mennyiség (kWh, gáz m³/MJ, víz m³) a teljes múltra – a fenti pótlás csak ~13 hónapra ment
            # vissza, a számlakimutatás viszont a régi elszámolóknál is kiírja, mekkora fogyasztás díja a számlaérték.
            hianyos = [(k, x["fajl"]) for k, x in tarolt["szamlak"].items() if x.get("fajl") and x.get("tipus") != "storno"
                       and not any(kk in x for kk in ("elszamolt_kwh", "elszamolt_gaz", "elszamolt_viz"))]

            def potol_menny() -> dict[str, dict[str, Any]]:
                out: dict[str, dict[str, Any]] = {}
                for k, nev in hianyos:
                    f = mappa / nev
                    sz = self._beolvas(f) if f.exists() else None
                    if not sz:
                        continue
                    uj: dict[str, Any] = {}
                    if sz.elszamolt_kwh is not None:
                        uj["elszamolt_kwh"] = str(sz.elszamolt_kwh)
                    if sz.elszamolt_gaz:
                        uj["elszamolt_gaz"] = {kk: str(vv) for kk, vv in sz.elszamolt_gaz.items()}
                    if sz.elszamolt_viz:
                        uj["elszamolt_viz"] = {kk: (str(vv) if isinstance(vv, Decimal) else vv) for kk, vv in sz.elszamolt_viz.items()}
                    if uj:
                        out[k] = uj
                return out

            for k, v in (await self.hass.async_add_executor_job(potol_menny)).items():
                tarolt["szamlak"][k].update(v)
            tarolt["mennyiseg_potlas"] = 1
            valtozott = True
        if sub.data.get(CONF_DIJSZABAS) == "villany/h" and tarolt.get("h_regiszter_potlas", 0) < 1 and tarolt.get("szamlak"):
            # H-tarifa: a már rögzített számlák regiszterállásai (első sor 1.82 nyári, második 1.81 téli) – korábban
            # csak az összegük került a fő csatornára.
            nevek = [x["fajl"] for x in sorted(tarolt["szamlak"].values(), key=lambda y: y.get("kelte") or "")
                     if x.get("fajl") and x.get("tipus") != "storno"]
            regi = await self.hass.async_add_executor_job(
                lambda: [sz for n in nevek if (mappa / n).exists() and (sz := self._beolvas(mappa / n))]
            )
            szuro_h = {x.strip() for x in str(sub.data.get(CONF_SZAMLA_MEROK) or "").split(",") if x.strip()}
            db = sum(regiszter_rogzit(tarolt, sz, szuro_h) for sz in regi)
            _LOGGER.info("%s: %s H-regiszter állás a számlákból", sub.title, db)
            tarolt["h_regiszter_potlas"] = 1
            valtozott = True
        latott = set(tarolt.get("feldolgozott_fajlok", []))
        fuggo = tarolt.setdefault("fuggo", [])

        def biztos_beolvas(f: Path) -> Any:
            try:
                return self._beolvas(f)
            except Exception as err:  # noqa: BLE001 – egy hibás fájl ne állítsa meg a többit
                _LOGGER.warning("%s: számla nem olvasható (%s): %s", sub.title, f.name, err)
                return None

        # A fel nem ismert fájl (méret, módosítás) szerint számít látottnak: ha kicserélik, vagy a letöltése csak
        # most fejeződött be, újra beolvassuk.
        nem_olv = tarolt.get("nem_olvasott_fajlok") or {}
        fajlok = await self.hass.async_add_executor_job(szamlak.uj_fajlok, mappa, latott | {x["fajl"] for x in fuggo}, nem_olv)
        if not fajlok:
            # a korábban rögzített számlákból is (pl. frissítés után, új fájl nélkül)
            return self._fix_dij_tanul(sid, sub, tarolt) or valtozott
        beolvasott = await self.hass.async_add_executor_job(lambda: [biztos_beolvas(f) for f in fajlok])
        # A részszámlán nincs mérőszám: a mérési pontja köti a mérőhöz (a tárolt térkép a korábbi számlákból).
        szamlak.meresi_pontok_kapcsolasa([x for x in beolvasott if x], tarolt.setdefault("meresi_pontok", {}))
        szuro = {x.strip() for x in str(sub.data.get(CONF_SZAMLA_MEROK) or "").split(",") if x.strip()}
        arsz = ARSZABAS.get(sub.data.get(CONF_DIJSZABAS))
        # Jóváhagyás: a mappába érkezett, ehhez a fiókhoz tartozó új számla előbb „függő” – a panelen előnézettel
        # (mi változna) jóváhagyható vagy elvethető. A panelről feltöltött fájl azonnal rögzül.
        szuro_n = {szamlak.mero_azonosito(x) for x in szuro}
        ismert, fuggo_sorsz = tarolt.get("szamlak") or {}, {x["sorszam"] for x in fuggo}
        varo = []
        for i, (f, x) in enumerate(zip(fajlok, beolvasott, strict=True)):
            try:
                if not (x and x.sorszam and f.name not in self.azonnali_fajlok and x.sorszam not in ismert
                        and x.sorszam not in fuggo_sorsz and hozzatartozik(x, szuro_n, arsz)):
                    continue
                meta = szamla_meta(x)
            except Exception as err:  # noqa: BLE001 – egy hibás számla ne állítsa meg a többit
                _LOGGER.warning("%s: számla nem rögzíthető (%s): %s", sub.title, f.name, err)
                beolvasott[i] = None
                continue
            varo.append(f.name)
            fuggo_sorsz.add(x.sorszam)
            fuggo.append({"fajl": f.name, "sorszam": x.sorszam, "erkezett": helyi_most().isoformat(),
                          **{k: meta.get(k) for k in ("kelte", "tipus", "idoszak", "osszeg", "szamlaertek", "elszamolt_kwh", "forras")}})
        self.azonnali_fajlok -= {f.name for f in fajlok}
        j = rogzit(tarolt, [x for f, x in zip(fajlok, beolvasott, strict=True) if x and f.name not in varo], szuro, arsz)
        self._fix_dij_tanul(sid, sub, tarolt)
        tarolt["szamla_import_verzio"] = IMPORT_VERZIO
        tarolt["feldolgozott_fajlok"] = sorted(latott | ({f.name for f, x in zip(fajlok, beolvasott, strict=True) if x} - set(varo)))
        tarolt["nem_olvasott_fajlok"] = await self.hass.async_add_executor_job(
            szamlak.nem_olvasott_frissites, mappa, nem_olv, [f for f, x in zip(fajlok, beolvasott, strict=True) if x is None])
        if varo:
            persistent_notification.async_create(
                self.hass,
                f"{len(varo)} új számla érkezett, jóváhagyásra vár. A Rezsikövető panelen látod, mi változna vele "
                "(fogyasztás, várható költség, egyenleg), és ott hagyhatod jóvá vagy vetheted el.",
                title=f"Rezsikövető – {sub.title}: új számla", notification_id=f"{DOMAIN}_fuggo_{sid}",
            )
        # Fel nem ismert fájlok (nem számla, ismeretlen szolgáltató, szkennelt PDF): ne vesszenek el csendben.
        # Az XML-párral rendelkező PDF szándékosan kimarad (az XML-t olvassuk), az nem „ismeretlen”.
        ujak_ismeretlen = {
            f.name for f, x in zip(fajlok, beolvasott, strict=True)
            if x is None and not (f.suffix.lower() == ".pdf" and f.with_suffix(".xml").exists())
            and not _ismert_masolat(f.name, tarolt)
        }
        felismert = {f.name for f, x in zip(fajlok, beolvasott, strict=True) if x is not None}
        tarolt["ismeretlen_fajlok"] = sorted((set(tarolt.get("ismeretlen_fajlok", [])) - felismert) | ujak_ismeretlen)
        if ujak_ismeretlen:
            nevek = sorted(ujak_ismeretlen)
            persistent_notification.async_create(
                self.hass,
                f"{len(nevek)} fájlt nem ismertem fel a(z) {sub.data[CONF_SZAMLA_MAPPA]} mappában:\n"
                + "\n".join(f"- {n}" for n in nevek[:10])
                + (f"\n- … és még {len(nevek) - 10}" if len(nevek) > 10 else "")
                + "\n\nHa számla, rögzítsd a Rezsikövető panelen az **Új számla** gombbal, vagy küldj róla kitakart mintát, "
                "hogy beolvasó készülhessen hozzá (GitHub: „Új szolgáltató kérése”).",
                title=f"Rezsikövető – {sub.title}: fel nem ismert fájl",
                notification_id=f"{DOMAIN}_ismeretlen_{sid}",
            )
        if j.szamlak or j.figyelmeztetesek:
            uzenet = (
                f"{len(j.szamlak)} új számla ({sub.data[CONF_SZAMLA_MAPPA]}): {j.leolvasasok} mérőállás, "
                f"{j.futoertekek} fűtőérték rögzítve"
                + (f", {j.kihagyott_ellentmondas} ellentmondó állás kihagyva" if j.kihagyott_ellentmondas else "")
                + "."
                + ("\n\n" + "\n".join(j.figyelmeztetesek) if j.figyelmeztetesek else "")
            )
            persistent_notification.async_create(
                self.hass, uzenet, title=f"Rezsikövető – {sub.title}", notification_id=f"{DOMAIN}_szamla_{sid}"
            )
        return True

    async def _befizetesek(self, sub: ConfigSubentry, tarolt: dict[str, Any]) -> dict[str, tuple[date, Decimal]]:
        """Számlaszám szerint egyesítve: a számlamappa és a Díjnet ugyanazt a számlát ne számolja kétszer."""
        dn = await self.hass.async_add_executor_job(
            dijnet.szamlak, Path(self.hass.config.config_dir), DIJNET_MINTA, sub.data[CONF_DIJNET]
        ) if sub.data.get(CONF_DIJNET) else []
        return befizetesek_egyesitese(tarolt, dn)

    async def _varhato_elszamolas(
        self, sub: ConfigSubentry, tarolt: dict[str, Any], fiok: Fiok, szamlalo: Szamlalo, most: datetime, tovabbi: list[Szamlalo],
        betaplalas: Szamlalo | None = None,
    ) -> VarhatoElszamolas | None:
        """Kiindulás: az utolsó valódi elszámoló számla időszakának vége; ha nincs, az első számla kezdete,
        végső esetben az éves bázis. Befizetés: az azóta kiállított számlák (a kiinduló elszámoló nélkül)."""
        szamlak_meta = tarolt.get("szamlak") or {}
        torolt = szamlak.sztornozott_kulcsok(szamlak_meta)
        elszamolok = [
            (d(x["idoszak"][1]) if x.get("idoszak") else d(x["utolso_valodi_allas"]), s)
            for s, x in szamlak_meta.items()
            if x.get("tipus") == "elszamolo" and s not in torolt and (x.get("idoszak") or x.get("utolso_valodi_allas"))
        ]
        kizart: set[str] = set()
        if elszamolok:
            tol, sorszam = max(elszamolok)
            meta = szamlak_meta[sorszam]
            # A kiinduló elszámoló számla nem befizetés az új időszakra (sorszám vagy kelte+összeg szerint is).
            kizart = {sorszam.lstrip("0")}  # a _befizetesek kulcsa nullák nélkül
            if meta.get("osszeg") not in (None, ""):  # összeg nélküli számlának nincs nap+összeg kulcsa
                kizart.add(_bef_kulcs(meta["kelte"], meta["osszeg"]))
        elif szamlak_meta:
            kezdetek = [d(x["idoszak"][0]) for x in szamlak_meta.values() if x.get("idoszak")]
            tol = min(kezdetek) if kezdetek else min(d(x["kelte"]) for x in szamlak_meta.values())
        elif fiok.eves_bazis and (beallitas.reszszamlas(sub.data) or tarolt.get("megszunt")):
            # Lezárt fióknál számla nélkül is: a végelszámolás az éves bázistól (a kezdő óraállástól) a lezárásig.
            tol = fiok.eves_bazis
        else:
            return None
        # Nem kezdődhet a mérők előtt (pl. az első számla időszaka a mérő felszerelése előtt indul), és az éves
        # leolvasás előtti (lezárt évhez tartozó) számlák sem számítanak: tiszta lap az új elszámolási évtől.
        elso_mero = min((m.beepitve for m in fiok.csatornak[0].merok), default=tol)
        tol = max(tol, elso_mero, fiok.eves_bazis or tol)
        reszek = await self._befizetesek(sub, tarolt)
        befizetesek = [v for k, v in reszek.items() if k not in kizart]
        return varhato_elszamolas(fiok, self.tar, szamlalo, most, tol, befizetesek, tovabbi, betaplalas)

    def _mennyisegi_atalany(
        self, sub: ConfigSubentry, fiok: Fiok, tol: date, ig: date, most: datetime, szamlalok: list[Szamlalo] | None = None,
        tarolt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        havi_q, honnan = atalany_mennyiseg(sub.data, tarolt or {})
        arany = Decimal(0)
        szerepek = [c.szerep for c in fiok.csatornak]
        if "almero" in szerepek and szamlalok:
            # A locsolási almérő aránya az elmúlt egy évben (a csatornadíj levonásához).
            try:
                t1 = most - timedelta(days=365)
                fo = szamlalok[0].fogyasztas(t1, most)[0]
                al = szamlalok[szerepek.index("almero")].fogyasztas(t1, most)[0]
                arany = max(min(al / fo, Decimal(1)), Decimal(0)) if fo > 0 else Decimal(0)
            except NincsAdat:
                arany = Decimal(0)
        napi_q, idoszak_q, havi_ft = atalany_havi(fiok, self.tar, tol, ig, havi_q, arany)
        # Víz: a háztartás távhős melegvizének szennyvizét (meleg szennyvíz) a vízmű az átalányszámlán is számlázza.
        msz = self._meleg_szennyviz(fiok, tol, ig) if sub.data[CONF_KOZMU] == "viz" else None
        if msz:
            havi_ft = havi_ft + msz[1]
        napok = (ig - tol).days
        eltelt = min(max((most.date() - tol).days + 1, 0), napok)
        egyseg = EGYSEG.get(sub.data[CONF_KOZMU], "")
        # Teljes hónapokból álló időszakban a havi = az időszak / hónapok száma (a 30 és a 31 napos hónap átalánya
        # ugyanannyi); egyébként a napi átalány egy átlagos hónapra – az időszak lehet hosszabb is (pl. az éves leolvasás
        # után 46 nap), a havi részszámla akkor is ennyi (az éves egyenleg hátralévő részszámlái is ebből).
        hatarok = teljes_honapok(tol, ig)
        havi = float(havi_ft) / (len(hatarok) - 1) if hatarok else float(havi_ft) / napok * 365 / 12
        return {
            "napi": round(havi * 12 / 365, 2),
            "havi": int(round(havi)),
            "idoszak_ft": int(havi_ft),
            "eddig": int(round(float(havi_ft) * eltelt / napok)),
            "napok": napok,
            "eltelt_nap": eltelt,
            "mennyiseg_havi": float(havi_q),
            "mennyiseg_napi": round(float(napi_q), 3),
            "mennyiseg_idoszak": round(float(idoszak_q), 1),
            "almero_arany": round(float(arany), 3),
            "meleg_szennyviz_m3": round(float(msz[0]), 1) if msz else None,
            "forras": (
                f"{honnan}: átalány {float(havi_q):g} {egyseg}/hó → napi {float(napi_q):.2f} {egyseg}, "
                f"az időszakra ({napok} nap) {float(idoszak_q):.1f} {egyseg}"
                + (f"; + meleg szennyvíz {float(msz[0]):.1f} m³ (a távhős melegvíz csatornadíja)" if msz else "")
            ).replace(".", ","),
        }

    def _gaz_eves_keret(self, sub: ConfigSubentry, fiok: Fiok, szamlalo: Szamlalo, most: datetime) -> dict[str, Any] | None:
        """Gáz: az éves kedvezményes keret (63 645 MJ × a fiók szorzója) és az év elejétől ténylegesen felhasznált
        mennyiség (a mérőállás-szenzorból, ennek híján a rögzített leolvasásokból). Az év eleje: átalánynál az éves
        elszámoló leolvasás, diktálásnál a kedvezményes év kezdete (augusztus 1.)."""
        if sub.data.get(CONF_KOZMU) != "gaz" or beallitas.fix_dijas(sub.data) or not sub.data.get(CONF_KERET_AKTIV, True):
            return None
        ma = most.date()
        try:
            e = self.tar.felold(_hozzarendeles(fiok, ma), ma, fiok.szolgaltato, fiok.feluliras)
        except DijszabasHiba:
            return None
        keret = _modhoz(fiok, e.szabalyok.get("keret")) or {}
        if not keret.get("ev_mennyiseg"):
            return None
        if beallitas.reszszamlas(sub.data) and fiok.eves_bazis:
            tol = eves_keret_kezdete(fiok.eves_bazis, ma)  # az évfordulón megújul, új éves leolvasás nélkül is
        else:
            tol = date(ma.year if (ma.month, ma.day) >= (8, 1) else ma.year - 1, 8, 1)
        try:
            felh = elszamolt_mennyiseg(szamlalo, tol, ma + timedelta(days=1), e.szabalyok.get("atvaltas"), fiok)
        except NincsAdat:
            return None
        ossz = Decimal(str(keret["ev_mennyiseg"]))
        return {"tol": tol.isoformat(), "osszes": float(ossz), "felhasznalt": float(felh), "hatralevo": float(max(ossz - felh, 0))}

    def _otthon_eves_leolvasas(self, kozmu: str) -> date | None:
        """Egy otthonban az azonos közmű (villany) mérőit egyszerre olvassák le évente: ha bármelyik fiók utolsó
        számláján közölt „következő leolvasás” időszakában van (múltbeli) mérőállás, az az otthon éves leolvasása."""
        legjobb: date | None = None
        ma = date.today()
        for sid, sub in self.fiokok().items():
            if sub.data.get(CONF_KOZMU) != kozmu:
                continue
            tarolt = self.tarolo.fiok(sid)
            ablak = kovetkezo_idopont(tarolt, "kovetkezo_leolvasas")
            if not ablak:
                continue
            for m in tarolt.get("merok", []):
                for lo in m.get("leolvasasok", []):
                    nap = d(lo["datum"])
                    if ablak[0] <= nap <= min(ablak[1], ma) and (legjobb is None or nap > legjobb):
                        legjobb = nap
        return legjobb

    def _otthon_bazissal(self, sub: ConfigSubentry, fiok: Fiok) -> Fiok:
        """Villanynál az otthon közös éves leolvasása a fiók elszámolási évkezdete (ha későbbi a sajátjánál)."""
        if sub.data.get(CONF_KOZMU) != "villany":
            return fiok
        nap = self._otthon_eves_leolvasas("villany")
        if nap is None or (fiok.eves_bazis and fiok.eves_bazis >= nap):
            return fiok
        return dataclasses.replace(fiok, eves_bazis=nap, elszamolasi_napok=tuple(sorted(set(fiok.elszamolasi_napok) | {nap})))

    def _ciklus(self, sub: ConfigSubentry, tarolt: dict[str, Any], fiok: Fiok) -> tuple[int, date | None]:
        """(elszámolási ciklus hónapokban, a következő elszámoló leolvasás várható kezdete). Ha a legutóbbi számla közli
        a következő leolvasást, az dönt: a legutóbbi elszámoló leolvasástól ~1 év → éves, ~fél év → féléves;
        ha a közölt leolvasás már megvolt (az évkezdet az időszakába esik), a következő egy ciklussal később."""
        beallitott = int(sub.data.get(CONF_ELSZAMOLAS_HONAP) or 12)
        leolv = kovetkezo_idopont(tarolt, "kovetkezo_leolvasas")
        kov = d(sub.data.get(CONF_KOV_EVES))
        if kov and fiok.eves_bazis and (kov - honap_mulva(fiok.eves_bazis, 12)).days > 31:
            # Az elszámolási év legfeljebb 12 hónap (+ tűrés): ennél távolabbi megadott leolvasás nem lehet ennek az évnek
            # a vége – figyelmen kívül marad.
            _LOGGER.warning("%s: a megadott következő éves leolvasás (%s) több mint 12 hónapra van az évkezdettől (%s)",
                            sub.title, kov, fiok.eves_bazis)
            kov = None
        if kov and fiok.eves_bazis and abs((kov - fiok.eves_bazis).days) <= 31 and fiok.eves_bazis in elszamolasi_napok(tarolt):
            # A megadott leolvasás már megtörtént (rögzített éves leolvasás a környékén): a következő egy ciklussal később.
            kov = None
        if not leolv and kov and fiok.eves_bazis and kov > fiok.eves_bazis:
            # Tört év: a fiókban megadott következő éves leolvasás (a szolgáltató ciklusa) – a számla közölt időpontja
            # híján. Ha már elmúlt, de még nincs rögzítve, a következő ciklusra lép (legfeljebb egy hónap türelemmel).
            while kov < date.today() - timedelta(days=31):
                kov = honap_mulva(kov, beallitott)
            return beallitott, kov
        if leolv and fiok.eves_bazis and leolv[0] <= fiok.eves_bazis <= leolv[1]:
            return beallitott, honap_mulva(fiok.eves_bazis, beallitott)
        if leolv and fiok.eves_bazis and leolv[1] > fiok.eves_bazis:
            honap = round((leolv[0] - fiok.eves_bazis).days / 30.44)
            return (12 if honap >= 9 else 6 if honap >= 4 else beallitott), leolv[0]
        return beallitott, None

    async def _egyenleg(self, sub: ConfigSubentry, tarolt: dict[str, Any], fiok: Fiok, szamlalo: Szamlalo, most: datetime, tovabbi: list[Szamlalo] | None = None, atalany_havi_ft: int | None = None, betaplalas: Szamlalo | None = None) -> EvesEgyenleg:
        """Részszámlás fiók: kézzel rögzített + Díjnet-számlák, éves egyenleg."""
        lista = list((await self._befizetesek(sub, tarolt)).values())
        ciklus, kov = self._ciklus(sub, tarolt, fiok)
        # Tört év (a következő éves leolvasás nem egy ciklusnyira van a bázistól): az egyenleg időszaka addig tart, és
        # a részszámlák száma is ehhez igazodik.
        ev_ig = None
        if kov and fiok.eves_bazis and abs((kov - honap_mulva(fiok.eves_bazis, ciklus)).days) > 45:
            ev_ig = kov
        honapok = round((ev_ig - fiok.eves_bazis).days / 30.44) if ev_ig else ciklus
        return eves_egyenleg(
            fiok, self.tar, szamlalo, most, lista,
            ev_ig=ev_ig,
            reszszamla_db_ev=(
                max(honapok // int(sub.data[CONF_SZAMLAZAS_HONAP]) - 1, 0)
                if sub.data.get(CONF_SZAMLAZAS_HONAP)
                else (max(honapok - 1, 0) if ev_ig else int(sub.data.get(CONF_RESZSZAMLA_DB) or 11))
            ),
            elozo_bazis=elozo_bazis(tarolt, ciklus),
            ciklus_honap=ciklus,
            tovabbi=tovabbi,
            reszszamla_osszeg=(
                Decimal(str(sub.data[CONF_RESZSZAMLA_OSSZEG])) if sub.data.get(CONF_RESZSZAMLA_OSSZEG)
                else Decimal(atalany_havi_ft) if atalany_havi_ft else None
            ),
            elozo_ev_mennyiseg=Decimal(str(sub.data[CONF_ELOZO_EV])) if sub.data.get(CONF_ELOZO_EV) else None,
            betaplalas=betaplalas,
            profil="nyaralo" if sub.data.get(CONF_HASZNALAT) == "nyaralo" else None,
        )

    def _mero_allasok(self, sid: str, sub: ConfigSubentry, fiok: Fiok, szamlalok: list[Szamlalo],
                      betap: Szamlalo | None, betap_csatorna: Csatorna, most: datetime) -> list[dict[str, Any]]:
        """Az indítókártya „Mérőállások” sora: csak a szenzoros csatornák (H-tarifánál téli/nyári regiszter, ha mindkettőnek
        van szenzora, különben az 1.8.0; A2-nél csúcs/völgy; almérő; napelemnél a 2.8.0) mostani, korrigált állása. A kártya
        élőben lépteti: állás + szorzó × (a szenzor mostani értéke − alap)."""
        forrasok = {"vetelezes": CONF_FORRAS, "h_teli": CONF_H_TELI, "h_nyari": CONF_H_NYARI, "zona_csucs": CONF_A2_CSUCS,
                    "zona_volgy": CONF_A2_VOLGY, "almero": CONF_ALMERO_FORRAS, "betaplalas": CONF_BETAPLALAS}
        parok = list(zip(szamlalok, fiok.csatornak, strict=False))
        if betap is not None:
            parok.append((betap, betap_csatorna))
        ki = []
        for sz, csatorna in parok:
            szerep = csatorna.szerep
            eid = sub.data.get(forrasok.get(szerep, ""))
            if not eid:
                continue
            try:
                allas, becsult = sz.ertek(most)
                allas = kijelzett_allas(csatorna, allas)
            except (NincsAdat, ValueError):
                continue
            allapot = self.hass.states.get(eid)
            try:
                alap = float(allapot.state) if allapot else None
            except ValueError:
                alap = None
            szorzo = Decimal(str(sub.data.get(CONF_SZORZO) or 1))
            if (kal := self.kalibraciok.get(sid, {}).get(szerep)) and kal.szorzo:
                szorzo *= kal.szorzo
            ki.append({"szerep": szerep, "allas": round(float(allas), 3), "becsult": becsult, "entity_id": eid,
                       "alap": alap, "szorzo": float(szorzo)})
        return ki

    async def _betap_szamlalo(self, sub: ConfigSubentry, tarolt: dict[str, Any], fiok: Fiok, tol: date, most: datetime) -> Szamlalo:
        """Napelemes fiók (kísérleti): betáplálási számláló a 2.8.0-s leolvasásokból és a betáplálás-szenzorból."""
        csat = betaplalas_csatorna(tarolt)
        sorozat = None
        if sub.data.get(CONF_BETAPLALAS):
            kezdet = min([tol, fiok.eves_bazis or tol, *(m.beepitve for m in csat.merok)])
            sorozat = await self._sorozat(sub.data[CONF_BETAPLALAS], datetime.combine(kezdet, datetime.min.time()) - timedelta(days=1), most)
        tol_nap = d(sub.data.get(CONF_FORRAS_TOL))
        return Szamlalo.csatornabol(
            csat, sorozat, Decimal(str(sub.data.get(CONF_SZORZO) or 1)),
            meroallas=sub.data.get(CONF_FORRAS_TIPUS, "meroallas") == "meroallas",
            sorozat_tol=datetime.combine(tol_nap, datetime.min.time()) if tol_nap else None,
        )

    def _napelem(
        self, fiok: Fiok, vetel: Szamlalo, betap: Szamlalo, tol: date, ig: date, most: datetime, mod: str
    ) -> napelem.NapelemEredmeny:
        """Bruttónál a folyó (havi) időszak, szaldónál az elszámolási év eddigi része („ha ma lenne”)."""
        if mod == "brutto":
            return napelem.brutto(fiok, self.tar, tol, ig, vetel, betap, meres_vege=most)
        bazis = fiok.eves_bazis or tol
        return napelem.szaldo(fiok, self.tar, bazis, egy_ev_mulva(bazis), vetel, betap, meres_vege=most)

    def _szaldo_keret(self, fiok: Fiok, n: napelem.NapelemEredmeny, most: datetime) -> dict[str, Any] | None:
        """Szaldó: az éves kedvezményes keret (2 523 kWh) a nettó vételezésre vonatkozik, az elszámolási év elejétől."""
        ma = most.date()
        try:
            e = self.tar.felold(_hozzarendeles(fiok, ma), ma, fiok.szolgaltato, fiok.feluliras)
        except DijszabasHiba:
            return None
        keret = _modhoz(fiok, e.szabalyok.get("keret")) or {}
        if not keret.get("ev_mennyiseg"):
            return None
        ossz, felh = Decimal(str(keret["ev_mennyiseg"])), max(n.vetelezes - n.betaplalas, Decimal(0))
        return {"tol": n.tol.isoformat(), "osszes": float(ossz), "felhasznalt": float(felh), "hatralevo": float(max(ossz - felh, 0)),
                "szaldo": True}

    def _aktualis_ar(self, fiok: Fiok, ny: NyitottIdoszak, most: datetime) -> Decimal | None:
        """A következő elfogyasztott egység ára a mért egységben (gáznál Ft/m³), a HA Energia irányítópulthoz."""
        for s in ny.eddig.szeletek:
            if s.csatorna.startswith("h_") and s.keret == 0 and s.keret is not None:
                continue  # H-regiszter a saját idényén kívül: nem ez a „következő kWh” ára
            if s.csatorna == "h_teli" and s.keret is None:
                idx = (idenyszak(most.date(), self.tar.felold(_hozzarendeles(fiok, most.date()), most.date(), fiok.szolgaltato, fiok.feluliras).szabalyok.get("idenyszak") or []) or {}).get("nev")
                if idx != "teli":
                    continue
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


def _utolso_szamla(tarolt: dict[str, Any]) -> dict[str, Any] | None:
    sz = tarolt.get("szamlak") or {}
    if not sz:
        return None
    sorszam, x = max(sz.items(), key=lambda kv: kv[1]["kelte"])
    return {"sorszam": sorszam, **x, "szamlak_szama": len(sz)}


def _bef_kulcs(datum: Any, osszeg: Any) -> str:
    """Befizetés azonosítója sorszám híján: nap + összeg egységes formában (11202 = 11202.0)."""
    return f"{str(datum)[:10]}|{Decimal(str(osszeg)).quantize(Decimal('0.01'))}"

