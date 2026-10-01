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

from .const import CONF_FIZETESI_MOD, CONF_NAPELEM, CONF_SZAMLA_MAPPA, DOMAIN, PENZNEM
from .koordinator import FiokAllapot, RezsiKoordinator
from .modell import szelet_dict

MAX_NAPLO = 24
EGYENLEG_KULCSOK = {"befizetve", "varhato_eves_koltseg", "varhato_egyenleg"}
NAPELEM_KULCSOK = {"betaplalas", "betaplalas_jovairas", "napelem_egyenleg"}


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


def _eddig_attr(a: FiokAllapot) -> dict[str, Any]:
    e = a.nyitott.eddig
    return {
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
        key="utolso_lezart",
        translation_key="utolso_lezart",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PENZNEM,
        suggested_display_precision=0,
        ertek=lambda a: a.utolso_lezart["osszesen_ft"],
        attr=lambda a: {k: v for k, v in a.utolso_lezart.items() if k != "szeletek"},
        elerheto=lambda a: a.utolso_lezart is not None,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    koord: RezsiKoordinator = entry.runtime_data
    async_add_entities([HaztartasOsszesen(koord, entry, "eddig"), HaztartasOsszesen(koord, entry, "varhato")])
    for sid, sub in koord.fiokok().items():
        async_add_entities(
            [
                FiokSzenzor(koord, entry, sid, sub.title, leiras)
                for leiras in FIOK_LEIRASOK
                if (leiras.key not in EGYENLEG_KULCSOK or sub.data.get(CONF_FIZETESI_MOD) == "reszszamla")
                and (leiras.key not in NAPELEM_KULCSOK or sub.data.get(CONF_NAPELEM, "nincs") != "nincs")
                and (leiras.key != "utolso_szamla" or sub.data.get(CONF_SZAMLA_MAPPA))
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
        self._fajta = fajta
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
            if a.nyitott is None:
                continue
            e = a.nyitott.eddig if self._fajta == "eddig" else a.nyitott.varhato
            sub = koord.fiokok().get(sid)
            out[sub.title if sub else sid] = int(e.osszesen_ft)
        return out

    @property
    def native_value(self) -> int | None:
        r = self._reszek()
        return sum(r.values()) if r else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"fiokok": self._reszek()}
