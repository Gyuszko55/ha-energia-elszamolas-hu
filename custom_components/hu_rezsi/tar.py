"""A szállított díjszabás-fájlok egyszeri betöltése (megosztva a bejegyzések és a beállító felület között)."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .motor.dijszabas import DijszabasTar

MAPPA = Path(__file__).parent / "dijszabasok"


async def dijszabas_tar(hass: HomeAssistant) -> DijszabasTar:
    adat = hass.data.setdefault(DOMAIN, {})
    if "tar" not in adat:
        adat["tar"] = await hass.async_add_executor_job(DijszabasTar.mappabol, MAPPA)
    return adat["tar"]
