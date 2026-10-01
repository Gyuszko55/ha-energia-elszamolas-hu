"""Beállítás felületről: háztartás (bejegyzés) → fiókok (alárendelt bejegyzések)."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_BEEPITVE,
    CONF_DIJSZABAS,
    CONF_DIJSZABAS_TOL,
    CONF_FORRAS,
    CONF_GYARI_SZAM,
    CONF_IDOSZAK_MOD,
    CONF_IDOSZAK_NAP,
    CONF_KERET_AKTIV,
    CONF_KEZDO_ALLAS,
    CONF_KOZMU,
    CONF_SZOLGALTATO,
    CONF_SZORZO,
    DOMAIN,
    FIOK,
)
from .tar import dijszabas_tar

KOZMUVEK = ["villany", "gaz"]  # a víz a 2. lépcsőben jön


class RezsiConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=user_input["nev"], data={})
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required("nev", default="Otthon"): TextSelector()})
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {FIOK: FiokFlow}


class FiokFlow(ConfigSubentryFlow):
    """Szolgáltatói fiók felvétele és szerkesztése."""

    def __init__(self) -> None:
        self._alap: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._alap = user_input
            return await self.async_step_reszletek()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("nev"): TextSelector(),
                    vol.Required(CONF_KOZMU, default="villany"): SelectSelector(
                        SelectSelectorConfig(options=KOZMUVEK, translation_key="kozmu", mode=SelectSelectorMode.LIST)
                    ),
                }
            ),
        )

    async def async_step_reszletek(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        kozmu = self._alap[CONF_KOZMU]
        if user_input is not None:
            adat = {CONF_KOZMU: kozmu, **user_input}
            return self.async_create_entry(title=self._alap["nev"], data=adat)
        return self.async_show_form(
            step_id="reszletek",
            data_schema=await self._sema(kozmu, {}, uj=True),
            description_placeholders={"kozmu": kozmu},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        kozmu = sub.data[CONF_KOZMU]
        if user_input is not None:
            nev = user_input.pop("nev")
            return self.async_update_and_abort(
                self._get_entry(), sub, title=nev, data={**sub.data, **user_input}
            )
        sema = await self._sema(kozmu, dict(sub.data), uj=False)
        sema = vol.Schema({vol.Required("nev", default=sub.title): TextSelector()}).extend(sema.schema)
        return self.async_show_form(step_id="reconfigure", data_schema=sema)

    async def _sema(self, kozmu: str, eddigi: dict[str, Any], uj: bool) -> vol.Schema:
        tar = await dijszabas_tar(self.hass)
        szolg = [
            SelectOptionDict(value=k, label=v["nev"]) for k, v in tar.szolgaltatok.items() if kozmu in v.get("kozmu", [])
        ]
        dijsz = [
            SelectOptionDict(value=k, label=d.nev) for k, d in sorted(tar.dijszabasok.items()) if d.kozmu == kozmu
        ]
        ma = date.today().isoformat()

        def alap(kulcs: str, x: Any) -> Any:
            return eddigi.get(kulcs, x)

        mezok: dict[Any, Any] = {
            vol.Required(CONF_SZOLGALTATO, default=alap(CONF_SZOLGALTATO, szolg[0]["value"])): SelectSelector(
                SelectSelectorConfig(options=szolg)
            ),
            vol.Required(CONF_DIJSZABAS, default=alap(CONF_DIJSZABAS, dijsz[0]["value"])): SelectSelector(
                SelectSelectorConfig(options=dijsz)
            ),
            vol.Required(CONF_DIJSZABAS_TOL, default=alap(CONF_DIJSZABAS_TOL, "2024-01-01")): DateSelector(),
            vol.Required(CONF_IDOSZAK_MOD, default=alap(CONF_IDOSZAK_MOD, "naptari_honap")): SelectSelector(
                SelectSelectorConfig(options=["naptari_honap", "egyedi_nap"], translation_key="idoszak_mod")
            ),
            vol.Required(CONF_IDOSZAK_NAP, default=alap(CONF_IDOSZAK_NAP, 1)): NumberSelector(
                NumberSelectorConfig(min=1, max=28, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_FORRAS, **({"description": {"suggested_value": eddigi[CONF_FORRAS]}} if eddigi.get(CONF_FORRAS) else {})): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_SZORZO, default=alap(CONF_SZORZO, 1)): NumberSelector(
                NumberSelectorConfig(min=0.5, max=2, step=0.0001, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_KERET_AKTIV, default=alap(CONF_KERET_AKTIV, True)): BooleanSelector(),
        }
        if uj:
            mezok |= {
                vol.Optional(CONF_GYARI_SZAM, default=""): TextSelector(),
                vol.Required(CONF_BEEPITVE, default=ma): DateSelector(),
                vol.Required(CONF_KEZDO_ALLAS, default=0): NumberSelector(
                    NumberSelectorConfig(min=0, max=99999999, step=0.001, mode=NumberSelectorMode.BOX)
                ),
            }
        return vol.Schema(mezok)
