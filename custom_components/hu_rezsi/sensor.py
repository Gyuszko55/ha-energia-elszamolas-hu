"""Rezsikövető entitások: fiókonként költség, várható költség, keret, ár; háztartásonként összesítés."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_FIZETESI_MOD, CONF_KOZMU, CONF_NAPELEM, CONF_SZAMLA_MAPPA, DOMAIN, FIX_DIJAS, PENZNEM
from .koordinator import FiokAllapot, RezsiKoordinator
from .modell import szelet_dict

MAX_NAPLO = 24
EGYENLEG_KULCSOK = {"befizetve", "varhato_eves_koltseg", "varhato_egyenleg"}
NAPELEM_KULCSOK = {"betaplalas", "betaplalas_jovairas", "napelem_egyenleg"}
SZAMLA_KULCSOK = {"utolso_szamla", "eves_szamlaosszeg", "kovetkezo_szamla"}
# Fix díjas (mérő nélküli) fióknál csak ezek értelmesek:
FIX_KULCSOK = {
    "koltseg_eddig", "koltseg_varhato", "utolso_szamla", "eves_szamlaosszeg", "kovetkezo_szamla", "utolso_lezart",
    "szolgaltato", "szamlazasi_utem",
}
UTEM_NEV = {1: "havonta", 2: "kéthavonta", 3: "negyedévente", 6: "félévente", 12: "évente"}


def _utem_nev(honap: int | None) -> str | None:
    return None if not honap else UTEM_NEV.get(int(honap), f"{honap} havonta")


def _napelem_attr(a: FiokAllapot) -> dict[str, Any]:
    n = a.napelem
    return {
        "mod": {"brutto": "bruttó (havi)", "szaldo": "szaldó (éves)"}[n.mod],
        "idoszak_kezdete": n.tol.isoformat(),
        "idoszak_vege": n.ig.isoformat(),
        "vetelezes_kwh": _f(n.vetelezes, 3),
        "betaplalas_kwh": _f(n.betaplalas, 3),
        "elszamolt_vetelezes_kwh": _f(n.elszamolt_vetelezes, 3),
        "betaplalasi_tobblet_kwh": _f(n.tobblet, 3),
        "energia_ft": float(n.energia_ft),
        "alapdij_ft": float(n.alapdij_ft),
        "jovairas_ft": float(n.jovairas_ft),
        "becsult": n.becsult,
        "kiserleti": True,
        "megjegyzes": "Kísérleti: a szabályokat még nem ellenőriztük valódi napelemes számlán (docs/terv/05_NAPELEM.md).",
    }
EGYSEG_MEGJELENES = {"m3": "m³"}


def _keret_egyseg(a: FiokAllapot) -> str | None:
    sz = a.nyitott.eddig.szeletek if a.nyitott else []
    return EGYSEG_MEGJELENES.get(sz[0].egyseg, sz[0].egyseg) if sz and sz[0].egyseg else a.egyseg


def _egyenleg_attr(a: FiokAllapot) -> dict[str, Any]:
    e = a.egyenleg
    return {
        "ev_kezdete": e.ev_tol.isoformat(),
        "ev_vege": e.ev_ig.isoformat(),
        "befizetve": int(e.befizetve),
        "befizetett_reszszamlak": e.befizetett_db,
        "hatralevo_reszszamlak": e.hatralevo_db,
        "hatralevo_reszszamla_ft": int(e.hatralevo_reszszamla),
        "teny_eddig": int(e.teny_eddig),
        "varhato_eves": int(e.varhato_eves),
        "varhato_fogyasztas": _f(e.varhato_fogyasztas, 1),
        "elozo_ev_fogyasztas": _f(e.elozo_ev_fogyasztas, 1),
        "modszer": e.modszer,
        "megbizhatosag": "rendben" if e.megbizhato else "alacsony – nincs előző évi fogyasztás vagy részszámla-összeg",
        "elozo_ev_visszameres": None
        if not e.elozo_ev
        else {
            "idoszak": f"{e.elozo_ev['tol'].isoformat()} – {e.elozo_ev['ig'].isoformat()}",
            "fizetve": int(e.elozo_ev["fizetve"]),
            "szamitott": int(e.elozo_ev["szamitott"]),
            "elteres_szazalek": round(float((e.elozo_ev["szamitott"] - e.elozo_ev["fizetve"]) / e.elozo_ev["fizetve"] * 100), 1)
            if e.elozo_ev["fizetve"]
            else None,
        },
        "jelentes": "pozitív: várható visszatérítés, negatív: várható ráfizetés",
        "tajekoztato": "Tájékoztató jellegű becslés, a hivatalos elszámolást nem helyettesíti.",
    }


def _f(x: Decimal | None, jegy: int = 2) -> float | None:
    return None if x is None else round(float(x), jegy)


@dataclass(frozen=True, kw_only=True)
class FiokLeiras(SensorEntityDescription):
    ertek: Callable[[FiokAllapot], Any]
    attr: Callable[[FiokAllapot], dict[str, Any]] = lambda a: {}
    egyseg: Callable[[FiokAllapot], str | None] = lambda a: None
    elerheto: Callable[[FiokAllapot], bool] = lambda a: a.nyitott is not None


def honapok(a: FiokAllapot) -> int:
    """Hány hónapos az elszámolási időszak (negyedévnél 3)."""
    return max(1, (a.ig.year - a.tol.year) * 12 + a.ig.month - a.tol.month)


def idenyszakok(e: Any) -> dict[str, Any] | None:
    """Idényszakonkénti bontás (H-tarifa: téli 1.81 / nyári 1.82), ha van."""
    out: dict[str, dict[str, float]] = {}
    for s in e.szeletek:
        nev = s.idenyszak or ({"h_teli": "teli", "h_nyari": "nyari"}.get(s.csatorna))
        if not nev:
            continue
        x = out.setdefault(nev, {"mennyiseg": 0.0, "energia_ft": 0.0})
        x["mennyiseg"] += float(s.mennyiseg)
        x["energia_ft"] += float(s.energia_ft)
    return {k: {"mennyiseg": round(v["mennyiseg"], 2), "energia_ft": round(v["energia_ft"])} for k, v in out.items()} or None


def _eddig_attr(a: FiokAllapot) -> dict[str, Any]:
    e = a.nyitott.eddig
    return {
        **({"idenyszakok": idenyszakok(e)} if idenyszakok(e) else {}),
        **({"atalany_havi": a.atalany["havi"], "atalany_eddig": a.atalany["eddig"]} if a.atalany else {}),
        **({"havi_resz": int(round(e.osszesen_ft / honapok(a))), "idoszak_honap": honapok(a)} if honapok(a) > 1 else {}),
        "idoszak_kezdete": a.tol.isoformat(),
        "idoszak_vege": a.ig.isoformat(),
        "eltelt_nap": _f(a.nyitott.eltelt_nap),
        "mennyiseg": _f(e.mennyiseg, 3),
        "energia_ft": int(e.energia_ft),
        "alapdij_ft": int(e.alapdij_ft),
        "becsult": e.becsult,
        "szeletek": [szelet_dict(s) for s in e.szeletek],
        "tajekoztato": "Tájékoztató jellegű számítás, a hivatalos számlát nem helyettesíti.",
    }


def _varhato_attr(a: FiokAllapot) -> dict[str, Any]:
    v = a.nyitott.varhato
    return {
        **({"havi_resz": int(round(v.osszesen_ft / honapok(a)))} if honapok(a) > 1 else {}),
        "mennyiseg": _f(v.mennyiseg, 1),
        "energia_ft": int(v.energia_ft),
        "alapdij_ft": int(v.alapdij_ft),
        "hatralevo_nap": _f(a.nyitott.hatralevo_nap),
        "napi_atlag": _f(a.nyitott.napi_atlag[0], 3),
        "modszer": "az utolsó 7 nap napi átlaga",
    }


FIOK_LEIRASOK: tuple[FiokLeiras, ...] = (
    FiokLeiras(
        key="koltseg_eddig",
        translation_key="koltseg_eddig",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: int(a.nyitott.eddig.osszesen_ft),
        attr=_eddig_attr,
    ),
    FiokLeiras(
        key="koltseg_varhato",
        translation_key="koltseg_varhato",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: int(a.nyitott.varhato.osszesen_ft),
        attr=_varhato_attr,
    ),
    FiokLeiras(
        key="fogyasztas_idoszak",
        translation_key="fogyasztas_idoszak",
        suggested_display_precision=1,
        ertek=lambda a: _f(a.nyitott.eddig.mennyiseg, 3),
        egyseg=lambda a: a.egyseg,
    ),
    FiokLeiras(
        key="hatralevo_keret",
        translation_key="hatralevo_keret",
        suggested_display_precision=1,
        ertek=lambda a: _f(a.nyitott.hatralevo_keret, 3),
        egyseg=_keret_egyseg,
        attr=lambda a: {
            "varhato_keretatlepes": a.nyitott.varhato_keretatlepes.isoformat()
            if a.nyitott.varhato_keretatlepes
            else None
        },
        elerheto=lambda a: a.nyitott is not None and a.nyitott.hatralevo_keret is not None,
    ),
    FiokLeiras(
        key="aktualis_ar",
        translation_key="aktualis_ar",
        suggested_display_precision=2,
        ertek=lambda a: _f(a.aktualis_ar, 3),
        egyseg=lambda a: f"{PENZNEM}/{a.egyseg}",
        elerheto=lambda a: a.aktualis_ar is not None,
    ),
    FiokLeiras(
        key="eves_fogyasztas",
        translation_key="eves_fogyasztas",
        suggested_display_precision=1,
        ertek=lambda a: _f(a.eves_fogyasztas, 3),
        egyseg=lambda a: a.egyseg,
        attr=lambda a: {"eves_bazis": a.eves_bazis.isoformat() if a.eves_bazis else None},
        elerheto=lambda a: a.eves_fogyasztas is not None,
    ),
    FiokLeiras(
        key="befizetve",
        translation_key="befizetve",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: int(a.egyenleg.befizetve),
        attr=_egyenleg_attr,
        elerheto=lambda a: a.egyenleg is not None,
    ),
    FiokLeiras(
        key="varhato_eves_koltseg",
        translation_key="varhato_eves_koltseg",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: int(a.egyenleg.varhato_eves),
        attr=_egyenleg_attr,
        elerheto=lambda a: a.egyenleg is not None,
    ),
    FiokLeiras(
        key="varhato_egyenleg",
        translation_key="varhato_egyenleg",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: int(a.egyenleg.varhato_egyenleg),
        attr=_egyenleg_attr,
        elerheto=lambda a: a.egyenleg is not None,
    ),
    FiokLeiras(
        key="betaplalas",
        translation_key="betaplalas",
        suggested_display_precision=1,
        ertek=lambda a: _f(a.napelem.betaplalas, 3),
        egyseg=lambda a: "kWh",
        attr=_napelem_attr,
        elerheto=lambda a: a.napelem is not None,
    ),
    FiokLeiras(
        key="betaplalas_jovairas",
        translation_key="betaplalas_jovairas",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: int(round(a.napelem.jovairas_ft)),
        attr=_napelem_attr,
        elerheto=lambda a: a.napelem is not None,
    ),
    FiokLeiras(
        key="napelem_egyenleg",
        translation_key="napelem_egyenleg",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: int(a.napelem.egyenleg_ft),
        attr=_napelem_attr,
        elerheto=lambda a: a.napelem is not None,
    ),
    FiokLeiras(
        key="varhato_elszamolas",
        translation_key="varhato_elszamolas",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: int(a.elszamolas.egyenleg),
        attr=lambda a: {
            "idoszak_kezdete": a.elszamolas.tol.isoformat(),
            "tenyleges_koltseg": int(a.elszamolas.tenyleges),
            "befizetve": int(a.elszamolas.befizetve),
            "szamlak_szama": a.elszamolas.szamlak_db,
            "fogyasztas": _f(a.elszamolas.mennyiseg, 1),
            "becsult": a.elszamolas.becsult,
            "jelentes": "pozitív: várható visszatérítés, negatív: várható ráfizetés – ha ma lenne az elszámolás",
            "tajekoztato": "Tájékoztató jellegű becslés, a hivatalos elszámolást nem helyettesíti.",
        },
        elerheto=lambda a: a.elszamolas is not None,
    ),
    FiokLeiras(
        key="atalany_havi",
        translation_key="atalany_havi",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: a.atalany["havi"],
        attr=lambda a: {**a.atalany, "jelentes": "átalányos fizetés: az átalány napra leosztva × a hónap napjai"},
        elerheto=lambda a: a.atalany is not None,
    ),
    FiokLeiras(
        key="utolso_szamla",
        translation_key="utolso_szamla",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: int(float(a.utolso_szamla["osszeg"])) if a.utolso_szamla.get("osszeg") is not None else None,
        attr=lambda a: a.utolso_szamla,
        elerheto=lambda a: a.utolso_szamla is not None,
    ),
    FiokLeiras(
        key="eves_szamlaosszeg",
        translation_key="eves_szamlaosszeg",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: a.szamla_stat["eves_osszeg"],
        attr=lambda a: {"szamlak_12_honap": a.szamla_stat["eves_db"], "idoszak": "az utolsó 365 nap számlái (kelte szerint)"},
        elerheto=lambda a: a.szamla_stat is not None,
    ),
    FiokLeiras(
        key="kovetkezo_szamla",
        translation_key="kovetkezo_szamla",
        device_class=SensorDeviceClass.DATE,
        ertek=lambda a: (a.esedekes or a.szamla_stat)["kovetkezo_datum"],
        attr=lambda a: {
            "varhato_osszeg": (a.esedekes or a.szamla_stat)["kovetkezo_osszeg"],
            "szamlazasi_utem_honap": (a.utem or {}).get("szamlazas_honap"),
            "e_havi_esedekes": (a.esedekes or {}).get("e_havi_osszesen"),
            "szokasos_idokoz_nap": a.szamla_stat["idokoz_nap"],
            "figyelmeztetes": a.szamla_stat["figyelmeztetes"],
        },
        elerheto=lambda a: a.szamla_stat is not None and a.szamla_stat["kovetkezo_datum"] is not None,
    ),
    FiokLeiras(
        key="utolso_lezart",
        translation_key="utolso_lezart",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        # Az integráció saját havi (negyedéves) lezárása; amíg az első időszak nem zárult le, „ismeretlen”, nem elérhetetlen.
        ertek=lambda a: a.utolso_lezart["osszesen_ft"] if a.utolso_lezart else None,
        attr=lambda a: {k: v for k, v in a.utolso_lezart.items() if k != "szeletek"}
        if a.utolso_lezart
        else {
            "allapot": "még nincs lezárt időszak",
            "elso_lezaras": a.ig.isoformat(),
            "magyarazat": "Az integráció az elszámolási időszak (hónap, negyedév) végén maga zárja le az időszakot a mért fogyasztásból.",
        },
        elerheto=lambda a: True,
    ),
    FiokLeiras(
        key="szolgaltato",
        translation_key="szolgaltato",
        ertek=lambda a: a.utem.get("szolgaltato"),
        attr=lambda a: {"szamlazasi_utem": _utem_nev(a.utem.get("szamlazas_honap"))},
        elerheto=lambda a: a.utem is not None,
    ),
    FiokLeiras(
        key="szamlazasi_utem",
        translation_key="szamlazasi_utem",
        ertek=lambda a: _utem_nev(a.utem.get("szamlazas_honap")),
        attr=lambda a: {"honap": a.utem.get("szamlazas_honap")},
        elerheto=lambda a: a.utem is not None and bool(a.utem.get("szamlazas_honap")),
    ),
    FiokLeiras(
        key="elszamolasi_ciklus",
        translation_key="elszamolasi_ciklus",
        ertek=lambda a: _utem_nev(a.utem.get("elszamolas_honap")),
        attr=lambda a: {
            "honap": a.utem.get("elszamolas_honap"),
            "kovetkezo_elszamolas": a.utem["kovetkezo_elszamolas"].isoformat() if a.utem.get("kovetkezo_elszamolas") else None,
        },
        elerheto=lambda a: a.utem is not None,
    ),
    FiokLeiras(
        key="kovetkezo_elszamolas",
        translation_key="kovetkezo_elszamolas",
        device_class=SensorDeviceClass.DATE,
        ertek=lambda a: a.utem["kovetkezo_elszamolas"],
        attr=lambda a: {"elszamolasi_ciklus": _utem_nev(a.utem.get("elszamolas_honap")), "becsles": "az utolsó elszámoló leolvasás + a ciklus"},
        elerheto=lambda a: a.utem is not None and a.utem.get("kovetkezo_elszamolas") is not None,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    koord: RezsiKoordinator = entry.runtime_data
    async_add_entities([HaztartasOsszesen(koord, entry, k) for k in ("eddig", "varhato", "esedekes")])
    for sid, sub in koord.fiokok().items():
        async_add_entities(
            [
                FiokSzenzor(koord, entry, sid, sub.title, leiras)
                for leiras in FIOK_LEIRASOK
                if (leiras.key not in EGYENLEG_KULCSOK | {"atalany_havi"} or sub.data.get(CONF_FIZETESI_MOD) == "reszszamla")
                and (leiras.key not in NAPELEM_KULCSOK or sub.data.get(CONF_NAPELEM, "nincs") != "nincs")
                and (leiras.key not in SZAMLA_KULCSOK or sub.data.get(CONF_SZAMLA_MAPPA))
                and (sub.data.get(CONF_KOZMU) not in FIX_DIJAS or leiras.key in FIX_KULCSOK)
            ],
            config_subentry_id=sid,
        )
    # Új fiók felvételekor az újratöltés versenyhelyzetbe kerülhet: ha egy fiók még nincs a számolt
    # adatok között, azonnal újraszámolunk (különben az entitásai a következő frissítésig elérhetetlenek).
    if set(koord.fiokok()) - set(koord.data or {}):
        await koord.async_request_refresh()


class FiokSzenzor(CoordinatorEntity[RezsiKoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: FiokLeiras

    def __init__(self, koord: RezsiKoordinator, entry: ConfigEntry, sid: str, nev: str, leiras: FiokLeiras) -> None:
        super().__init__(koord)
        self.entity_description = leiras
        self._sid = sid
        self._attr_unique_id = f"{sid}_{leiras.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sid)},
            name=nev,
            manufacturer="Rezsikövető",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _allapot(self) -> FiokAllapot | None:
        return (self.coordinator.data or {}).get(self._sid)

    @property
    def available(self) -> bool:
        a = self._allapot
        if a is None and super().available and not getattr(self.coordinator, "_ujraszamol_kert", False):
            self.coordinator._ujraszamol_kert = True  # egyszer kérünk újraszámolást a hiányzó fiókhoz
            self.hass.async_create_task(self.coordinator.async_request_refresh())
        return super().available and a is not None and a.hiba is None and self.entity_description.elerheto(a)

    @property
    def native_value(self) -> Any:
        return self.entity_description.ertek(self._allapot) if self.available else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.native_unit_of_measurement:
            return self.entity_description.native_unit_of_measurement
        a = self._allapot
        return self.entity_description.egyseg(a) if a else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        a = self._allapot
        if a is None:
            return None
        if a.hiba:
            return {"hiba": a.hiba}
        if not self.entity_description.elerheto(a):
            return None
        return self.entity_description.attr(a)


class HaztartasOsszesen(CoordinatorEntity[RezsiKoordinator], SensorEntity):
    """A háztartás összes fiókjának eddigi vagy várható költsége."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = PENZNEM
    _attr_suggested_display_precision = 0

    def __init__(self, koord: RezsiKoordinator, entry: ConfigEntry, fajta: str) -> None:
        super().__init__(koord)
        self._fajta = fajta  # eddig | varhato | esedekes
        self._attr_translation_key = f"osszesen_{fajta}"
        self._attr_unique_id = f"{entry.entry_id}_osszesen_{fajta}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Rezsikövető",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _reszek(self) -> dict[str, int]:
        koord = self.coordinator
        out: dict[str, int] = {}
        for sid, a in (koord.data or {}).items():
            if self._fajta == "esedekes":
                sub = koord.fiokok().get(sid)
                if a.esedekes:
                    out[sub.title if sub else sid] = a.esedekes["e_havi_osszesen"]
                continue
            if a.nyitott is None:
                continue
            e = a.nyitott.eddig if self._fajta == "eddig" else a.nyitott.varhato
            sub = koord.fiokok().get(sid)
            # Havi összesítő: átalánynál a fizetendő (napra leosztva), egyébként a költség; a több hónapos
            # (pl. negyedéves) időszakból a havi rész.
            if a.atalany:
                out[sub.title if sub else sid] = a.atalany["eddig" if self._fajta == "eddig" else "havi"]
            else:
                out[sub.title if sub else sid] = int(round(e.osszesen_ft / honapok(a)))
        return out

    @property
    def native_value(self) -> int | None:
        r = self._reszek()
        return sum(r.values()) if r else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"fiokok": self._reszek()}
