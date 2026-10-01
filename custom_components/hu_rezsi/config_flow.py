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

from pathlib import Path

from . import dijnet, szamlak
from .const import (
    CONF_BEEPITVE,
    CONF_ALMERO,
    CONF_ALMERO_BEEPITVE,
    CONF_ALMERO_FORRAS,
    CONF_ALMERO_KEZDO,
    CONF_BETAPLALAS,
    CONF_CSATORNADIJ,
    CONF_NAPELEM,
    CONF_DIJNET,
    CONF_FIZETESI_MOD,
    CONF_ATALANY_MENNYISEG,
    CONF_ELOZO_EV,
    CONF_RESZSZAMLA_DB,
    CONF_RESZSZAMLA_OSSZEG,
    CONF_SZAMLA_MAPPA,
    CONF_SZAMLA_MEROK,
    DIJNET_MINTA,
    FIX_DIJAS,
    CONF_DIJSZABAS,
    CONF_DIJSZABAS_TOL,
    CONF_FORRAS,
    CONF_FORRAS_TIPUS,
    CONF_H_NYARI,
    CONF_H_TELI,
    CONF_FORRAS_TOL,
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

KOZMUVEK = ["villany", "gaz", "viz", "hulladek"]


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
        super().__init__()
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

    async def _energia_betaplalas(self) -> str | None:
        """Ha a HA Energia irányítópulton van beállított hálózati betáplálás, azt ajánljuk fel."""
        try:
            from homeassistant.components.energy.data import async_get_manager  # noqa: PLC0415

            adat = (await async_get_manager(self.hass)).data or {}
            for forras in adat.get("energy_sources", []):
                if forras.get("type") == "grid" and forras.get("stat_energy_to"):
                    return forras["stat_energy_to"]
                for f in forras.get("flow_to", []) if forras.get("type") == "grid" else []:  # régebbi formátum
                    if f.get("stat_energy_to"):
                        return f["stat_energy_to"]
        except Exception:  # noqa: BLE001 – az ajánlás nem kötelező
            return None
        return None

    async def _fix_sema(self, kozmu: str, eddigi: dict[str, Any], uj: bool) -> vol.Schema:
        """Fix díjas fiók (pl. hulladékszállítás): szolgáltató, díjszabás, kezdőnap, számlamappa."""
        tar = await dijszabas_tar(self.hass)
        szolg = [SelectOptionDict(value=k, label=v["nev"]) for k, v in tar.szolgaltatok.items() if kozmu in v.get("kozmu", [])]
        dijsz = [SelectOptionDict(value=k, label=d.nev) for k, d in sorted(tar.dijszabasok.items()) if d.kozmu == kozmu]
        mappak = await self.hass.async_add_executor_job(szamlak.jelolt_mappak, Path(self.hass.config.config_dir))
        mezok: dict[Any, Any] = {
            vol.Required(CONF_SZOLGALTATO, default=eddigi.get(CONF_SZOLGALTATO, szolg[0]["value"])): SelectSelector(SelectSelectorConfig(options=szolg)),
            vol.Required(CONF_DIJSZABAS, default=eddigi.get(CONF_DIJSZABAS, dijsz[0]["value"])): SelectSelector(SelectSelectorConfig(options=dijsz)),
            vol.Required(CONF_DIJSZABAS_TOL, default=eddigi.get(CONF_DIJSZABAS_TOL, "2024-01-01")): DateSelector(),
            vol.Optional(CONF_SZAMLA_MAPPA, **({"description": {"suggested_value": eddigi[CONF_SZAMLA_MAPPA]}} if eddigi.get(CONF_SZAMLA_MAPPA) else {})): SelectSelector(
                SelectSelectorConfig(options=mappak, custom_value=True)
            ),
        }
        if uj:
            mezok[vol.Required(CONF_BEEPITVE, default=date.today().isoformat())] = DateSelector()
        return vol.Schema(mezok)

    async def _sema(self, kozmu: str, eddigi: dict[str, Any], uj: bool) -> vol.Schema:
        if kozmu in FIX_DIJAS:
            return await self._fix_sema(kozmu, eddigi, uj)
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
                SelectSelectorConfig(options=["naptari_honap", "egyedi_nap", "negyedev"], translation_key="idoszak_mod")
            ),
            vol.Required(CONF_IDOSZAK_NAP, default=alap(CONF_IDOSZAK_NAP, 1)): NumberSelector(
                NumberSelectorConfig(min=1, max=28, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_FORRAS, **({"description": {"suggested_value": eddigi[CONF_FORRAS]}} if eddigi.get(CONF_FORRAS) else {})): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_FORRAS_TIPUS, default=alap(CONF_FORRAS_TIPUS, "meroallas")): SelectSelector(
                SelectSelectorConfig(options=["meroallas", "szamlalo"], translation_key="forras_tipus")
            ),
            vol.Optional(CONF_FORRAS_TOL, **({"description": {"suggested_value": eddigi[CONF_FORRAS_TOL]}} if eddigi.get(CONF_FORRAS_TOL) else {})): DateSelector(),
            vol.Required(CONF_SZORZO, default=alap(CONF_SZORZO, 1)): NumberSelector(
                NumberSelectorConfig(min=0.5, max=2, step="any", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_KERET_AKTIV, default=alap(CONF_KERET_AKTIV, kozmu != "viz")): BooleanSelector(),
            vol.Required(CONF_FIZETESI_MOD, default=alap(CONF_FIZETESI_MOD, "fogyasztas_szerint")): SelectSelector(
                SelectSelectorConfig(options=["fogyasztas_szerint", "reszszamla"], translation_key="fizetesi_mod")
            ),
            vol.Required(CONF_RESZSZAMLA_DB, default=alap(CONF_RESZSZAMLA_DB, 11)): NumberSelector(
                NumberSelectorConfig(min=1, max=12, step=1, mode=NumberSelectorMode.BOX)
            ),
        }
        for kulcs in (CONF_ATALANY_MENNYISEG, CONF_RESZSZAMLA_OSSZEG, CONF_ELOZO_EV):
            mezok[vol.Optional(kulcs, **({"description": {"suggested_value": eddigi[kulcs]}} if eddigi.get(kulcs) else {}))] = NumberSelector(
                NumberSelectorConfig(min=0, max=10000000, step="any", mode=NumberSelectorMode.BOX)
            )
        mappak = await self.hass.async_add_executor_job(szamlak.jelolt_mappak, Path(self.hass.config.config_dir))
        mezok[vol.Optional(CONF_SZAMLA_MAPPA, **({"description": {"suggested_value": eddigi[CONF_SZAMLA_MAPPA]}} if eddigi.get(CONF_SZAMLA_MAPPA) else {}))] = SelectSelector(
            SelectSelectorConfig(options=mappak, custom_value=True)
        )
        mezok[vol.Optional(CONF_SZAMLA_MEROK, **({"description": {"suggested_value": eddigi[CONF_SZAMLA_MEROK]}} if eddigi.get(CONF_SZAMLA_MEROK) else {}))] = TextSelector()
        dn = await self.hass.async_add_executor_job(dijnet.szolgaltatok, Path(self.hass.config.config_dir), DIJNET_MINTA)
        if dn:
            mezok[vol.Optional(CONF_DIJNET, **({"description": {"suggested_value": eddigi[CONF_DIJNET]}} if eddigi.get(CONF_DIJNET) else {}))] = SelectSelector(
                SelectSelectorConfig(options=dn, custom_value=True)
            )
        if kozmu == "villany":
            for kulcs in (CONF_H_TELI, CONF_H_NYARI):
                mezok[vol.Optional(kulcs, **({"description": {"suggested_value": eddigi[kulcs]}} if eddigi.get(kulcs) else {}))] = EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                )
            ajanlott = eddigi.get(CONF_BETAPLALAS) or await self._energia_betaplalas()
            mezok[vol.Required(CONF_NAPELEM, default=alap(CONF_NAPELEM, "nincs"))] = SelectSelector(
                SelectSelectorConfig(options=["nincs", "brutto", "szaldo"], translation_key="napelem_mod")
            )
            mezok[vol.Optional(CONF_BETAPLALAS, **({"description": {"suggested_value": ajanlott}} if ajanlott else {}))] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )
        if kozmu == "viz":
            mezok[vol.Required(CONF_CSATORNADIJ, default=alap(CONF_CSATORNADIJ, True))] = BooleanSelector()
            mezok[vol.Required(CONF_ALMERO, default=alap(CONF_ALMERO, False))] = BooleanSelector()
            mezok[vol.Optional(CONF_ALMERO_FORRAS, **({"description": {"suggested_value": eddigi[CONF_ALMERO_FORRAS]}} if eddigi.get(CONF_ALMERO_FORRAS) else {}))] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )
            if uj:
                mezok[vol.Optional(CONF_ALMERO_BEEPITVE)] = DateSelector()
                mezok[vol.Optional(CONF_ALMERO_KEZDO, default=0)] = NumberSelector(
                    NumberSelectorConfig(min=0, max=99999999, step=0.001, mode=NumberSelectorMode.BOX)
                )
        if uj:
            mezok |= {
                vol.Optional(CONF_GYARI_SZAM, default=""): TextSelector(),
                vol.Required(CONF_BEEPITVE, default=ma): DateSelector(),
                vol.Required(CONF_KEZDO_ALLAS, default=0): NumberSelector(
                    NumberSelectorConfig(min=0, max=99999999, step=0.001, mode=NumberSelectorMode.BOX)
                ),
            }
        return vol.Schema(mezok)
