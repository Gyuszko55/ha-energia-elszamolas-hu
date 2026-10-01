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

from .const import DOMAIN, PENZNEM
from .koordinator import FiokAllapot, RezsiKoordinator
from .modell import szelet_dict

MAX_NAPLO = 24


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
        egyseg=lambda a: a.egyseg,
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
            [FiokSzenzor(koord, entry, sid, sub.title, leiras) for leiras in FIOK_LEIRASOK],
            config_subentry_id=sid,
        )


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
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def _allapot(self) -> FiokAllapot | None:
        return (self.coordinator.data or {}).get(self._sid)

    @property
    def available(self) -> bool:
        a = self._allapot
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
