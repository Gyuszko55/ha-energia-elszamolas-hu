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
# Értesítés a fizetési határidő előtt (2.4.0b1): mobilra (notify.mobile_app_…), N nappal előtte és a lejárat után egyszer.
ERT_BE = "hatarido_ertesites"
ERT_NAPOK = "hatarido_napok"
ERT_CELOK = "hatarido_celok"  # notify-szolgáltatások: ["notify.mobile_app_telefon", …]
ERT_IDO = "hatarido_ido"  # "ÓÓ:PP"
ERT_OTTHONOK = "hatarido_otthonok"  # mely otthonokra (config entry id-k) – értesítés és hangutasítás; üres: mindegyik
ERT_NAPOK_ALAP, ERT_NAPOK_MAX, ERT_IDO_ALAP = 3, 14, "09:00"


def alap() -> dict[str, Any]:
    return {PANEL_AUTO_BEZARAS: PANEL_AUTO_BEZARAS_ALAP, AI_BEOLVASAS: False, AI_ENTITAS: None,
            ERT_BE: False, ERT_NAPOK: ERT_NAPOK_ALAP, ERT_CELOK: [], ERT_IDO: ERT_IDO_ALAP, ERT_OTTHONOK: []}


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
    if ERT_BE in uj:
        if not isinstance(uj[ERT_BE], bool):
            raise ValueError("Az értesítés kapcsolója igen/nem érték.")
        ki[ERT_BE] = uj[ERT_BE]
    if ERT_NAPOK in uj:
        try:
            n = int(uj[ERT_NAPOK])
        except (TypeError, ValueError) as err:
            raise ValueError("A napok száma egész szám.") from err
        if not 1 <= n <= ERT_NAPOK_MAX:
            raise ValueError(f"Az értesítés a határidő előtt 1–{ERT_NAPOK_MAX} nappal kérhető.")
        ki[ERT_NAPOK] = n
    if ERT_CELOK in uj:
        c = uj[ERT_CELOK] or []
        if not isinstance(c, list) or not all(isinstance(x, str) and x.startswith("notify.") and len(x) > 7 for x in c):
            raise ValueError("Csak értesítő szolgáltatás (notify.…) választható.")
        ki[ERT_CELOK] = sorted(set(c))
    if ERT_IDO in uj:
        t = str(uj[ERT_IDO] or "")[:5]
        try:
            o, p = (int(x) for x in t.split(":"))
        except ValueError as err:
            raise ValueError("Az időpont ÓÓ:PP alakú.") from err
        if not (0 <= o <= 23 and 0 <= p <= 59):
            raise ValueError("Az időpont ÓÓ:PP alakú.")
        ki[ERT_IDO] = f"{o:02d}:{p:02d}"
    if ERT_OTTHONOK in uj:
        o_ = uj[ERT_OTTHONOK] or []
        if not isinstance(o_, list) or not all(isinstance(x, str) and x for x in o_):
            raise ValueError("Az otthonok listája hibás.")
        ki[ERT_OTTHONOK] = sorted(set(o_))
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
    if b.get(ERT_BE) and not b.get(ERT_CELOK):
        raise ValueError("Az értesítéshez válassz legalább egy telefont (értesítő szolgáltatást).")
    await Store(hass, 1, KULCS).async_save(b)
    hass.data[DOMAIN]["panel_beallitas"] = b
    return b
