"""Rezsikövető – magyar lakossági rezsi-elszámolás Home Assistanthoz (tájékoztató jellegű)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import config_validation as cv
from datetime import timedelta

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .d_arak import DArak
from .koordinator import RezsiKoordinator
from . import mentes_ha
from .panel import regisztral_panel
from .szolgaltatasok import regisztral
from .tar import dijszabas_tar
from .tarolo import Tarolo

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type RezsiConfigEntry = ConfigEntry[RezsiKoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    regisztral(hass)
    # D árszabás: az MVM negyedórás rugalmas árlistája (közös minden otthonnak) és a még közzé nem tett napok
    # HUPX-ból számolt ára. Indulás után, majd 3 óránként ellenőrzi (az MVM-lista letöltése naponta legfeljebb egyszer,
    # a másnapi HUPX-ár délután jelenik meg); új árnál minden otthon újraszámol.
    d_arak = DArak(hass)
    await d_arak.betolt()
    hass.data.setdefault(DOMAIN, {})["d_arak"] = d_arak

    async def _d_frissit(*_: object) -> None:
        uj = await d_arak.frissit()
        if await d_arak.hupx_frissit() or uj:
            for entry in hass.config_entries.async_entries(DOMAIN):
                if koord := getattr(entry, "runtime_data", None):
                    await koord.async_request_refresh()

    async def _indulaskor(_hass: HomeAssistant) -> None:
        hass.async_create_background_task(_d_frissit(), "hu_rezsi D-árlista")

    async_at_started(hass, _indulaskor)
    mentes_ha.utemezo_indit(hass)  # a Rezsikövető ütemezett mentése (beállítás: panel → Mentés és visszaállítás)
    async_track_time_interval(hass, _d_frissit, timedelta(hours=3))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RezsiConfigEntry) -> bool:
    # Visszaállított otthon első indulása: a mentés adatai a koordinátor előtt kerülnek a tárolóba.
    await mentes_ha.befejezes(hass, entry)
    tar = await dijszabas_tar(hass)
    tarolo = Tarolo(hass, entry.entry_id)
    await tarolo.betolt()
    koord = RezsiKoordinator(hass, entry, tar, tarolo)
    if hass.state is CoreState.running:
        await koord.async_config_entry_first_refresh()
    else:
        # Induláskor az első számolás a háttérben fut: a recorder ilyenkor még terhelt, és a statisztika-lekérdezések
        # percekig feltartanák a HA indulását. Addig az entitások elérhetetlenek, a panel „még nincs adat”.
        entry.async_create_background_task(hass, koord.async_refresh(), "hu_rezsi első számolás")
    # A számlamappák feldolgozása a HA elindulása után (futó HA-n azonnal) – ez nem tartja fel az indulást.
    async def _mappak(_hass: HomeAssistant) -> None:
        await koord.async_request_refresh()

    entry.async_on_unload(async_at_started(hass, _mappak))
    entry.runtime_data = koord
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await regisztral_panel(hass)  # „Rezsikövető” oldalsáv-menüpont (egyszer)
    lenyomat = _lenyomat(entry)

    async def _ujratolt(hass: HomeAssistant, entry: RezsiConfigEntry) -> None:
        # Csak az otthon beállításai (options: fűtés, hőmérséklet az indítókártyához) változtak: nem kell újraszámolni,
        # a kártya a következő lekéréskor már az újat kapja.
        if _lenyomat(entry) != lenyomat:
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_ujratolt))
    return True


def _lenyomat(entry: RezsiConfigEntry) -> tuple:
    """Ami a számolást érinti: név, adatok, alárendelt bejegyzések (fiókok, szigetüzem) – az options nem."""
    return (entry.title, dict(entry.data),
            {sid: (s.subentry_type, s.title, dict(s.data)) for sid, s in entry.subentries.items()})


async def async_unload_entry(hass: HomeAssistant, entry: RezsiConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: RezsiConfigEntry) -> None:
    await Tarolo(hass, entry.entry_id).torol()
