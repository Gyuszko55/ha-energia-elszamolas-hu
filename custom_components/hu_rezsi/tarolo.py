"""Leolvasások, mérők, felülírások és lezárt időszakok tárolása a HA saját tárhelyén."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

VERZIO = 1


def ures_fiok() -> dict[str, Any]:
    return {"merok": [], "feluliras": [], "lezart": []}


class Tarolo:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, VERZIO, f"{DOMAIN}.{entry_id}")
        self.adat: dict[str, Any] = {"fiokok": {}}

    async def betolt(self) -> None:
        self.adat = await self._store.async_load() or {"fiokok": {}}

    def fiok(self, subentry_id: str) -> dict[str, Any]:
        return self.adat["fiokok"].setdefault(subentry_id, ures_fiok())

    def torol_fiok(self, subentry_id: str) -> None:
        self.adat["fiokok"].pop(subentry_id, None)

    async def ment(self) -> None:
        await self._store.async_save(self.adat)

    async def torol(self) -> None:
        await self._store.async_remove()
