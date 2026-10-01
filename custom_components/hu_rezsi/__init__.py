"""Rezsikövető – magyar lakossági rezsi-elszámolás Home Assistanthoz (tájékoztató jellegű)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .koordinator import RezsiKoordinator
from .panel import regisztral_panel
from .szolgaltatasok import regisztral
from .tar import dijszabas_tar
from .tarolo import Tarolo

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type RezsiConfigEntry = ConfigEntry[RezsiKoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    regisztral(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RezsiConfigEntry) -> bool:
    tar = await dijszabas_tar(hass)
    tarolo = Tarolo(hass, entry.entry_id)
    await tarolo.betolt()
    koord = RezsiKoordinator(hass, entry, tar, tarolo)
    await koord.async_config_entry_first_refresh()
    entry.runtime_data = koord
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await regisztral_panel(hass)  # „Rezsi” oldalsáv-menüpont (egyszer)
    entry.async_on_unload(entry.add_update_listener(_ujratolt))
    return True


async def _ujratolt(hass: HomeAssistant, entry: RezsiConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: RezsiConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: RezsiConfigEntry) -> None:
    await Tarolo(hass, entry.entry_id).torol()
