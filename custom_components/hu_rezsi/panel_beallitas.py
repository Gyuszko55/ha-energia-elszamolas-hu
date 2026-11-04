"""A Rezsikövető panel integráció szintű beállításai (otthontól függetlenek): pl. a csak megjelenítő ablakok
automatikus bezárása. Tár: `hu_rezsi_panel` (a HA saját tárhelyén); olvasni mindenki, írni csak rendszergazda tud
(websocket: hu_rezsi/panel_beallitas)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, PANEL_AUTO_BEZARAS, PANEL_AUTO_BEZARAS_ALAP

KULCS = f"{DOMAIN}_panel"
MAX_MP = 600


AI_BEOLVASAS = "ai_beolvasas"  # ismeretlen számla kiolvasása AI-val (2.3.0b1) – alapból ki, beleegyezéssel
AI_ENTITAS = "ai_entitas"  # a használt AI Task entitás (üres: az első elérhető)


def alap() -> dict[str, Any]:
    return {PANEL_AUTO_BEZARAS: PANEL_AUTO_BEZARAS_ALAP, AI_BEOLVASAS: False, AI_ENTITAS: None}


def ervenyes(uj: dict[str, Any]) -> dict[str, Any]:
    """A beállítás ellenőrizve: az automatikus bezárás egész másodperc 0 és 600 között (0: kikapcsolva)."""
    ki: dict[str, Any] = {}
    if PANEL_AUTO_BEZARAS in uj:
        try:
            mp = int(float(uj[PANEL_AUTO_BEZARAS]))
        except (TypeError, ValueError) as err:
            raise ValueError("Az automatikus bezárás másodpercben megadott egész szám.") from err
        if not 0 <= mp <= MAX_MP:
            raise ValueError(f"Az automatikus bezárás 0 és {MAX_MP} másodperc között lehet (0: soha).")
        ki[PANEL_AUTO_BEZARAS] = mp
    if AI_BEOLVASAS in uj:
        if not isinstance(uj[AI_BEOLVASAS], bool):
            raise ValueError("Az AI-beolvasás kapcsolója igen/nem érték.")
        ki[AI_BEOLVASAS] = uj[AI_BEOLVASAS]
    if AI_ENTITAS in uj:
        e = uj[AI_ENTITAS] or None
        if e is not None and (not isinstance(e, str) or not e.startswith("ai_task.")):
            raise ValueError("Csak AI Task entitás (ai_task.…) választható.")
        ki[AI_ENTITAS] = e
    return ki


async def betolt(hass: HomeAssistant) -> dict[str, Any]:
    d = hass.data.setdefault(DOMAIN, {})
    if "panel_beallitas" not in d:
        d["panel_beallitas"] = alap() | (await Store(hass, 1, KULCS).async_load() or {})
    return d["panel_beallitas"]


def aktualis(hass: HomeAssistant) -> dict[str, Any]:
    """A betöltött beállítás (szinkron – a panel adatlekérése ebből olvas); betöltés előtt az alapértelmezés."""
    return hass.data.get(DOMAIN, {}).get("panel_beallitas") or alap()


async def ment(hass: HomeAssistant, uj: dict[str, Any]) -> dict[str, Any]:
    b = dict(await betolt(hass)) | ervenyes(uj)
    await Store(hass, 1, KULCS).async_save(b)
    hass.data[DOMAIN]["panel_beallitas"] = b
    return b
