"""Beállítás felületről: háztartás (bejegyzés) → fiókok (alárendelt bejegyzések)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
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
from .beallitas import ELSZAMOLAS_MODOK, fix_dijas
from .gaz_atalany import SZOBASZAMOK, TUZHELYEK
from .const import (
    CONF_BELSO_HOMERSEKLET,
    CONF_FUTES,
    CONF_KULSO_HOMERSEKLET,
    OTTHON_BEALLITASOK,
    CONF_ELSZAMOLAS_MOD,
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
    CONF_ELSZAMOLAS_HONAP,
    CONF_KOV_EVES,
    CONF_SZUNETEL_IG,
    CONF_SZUNETEL_TOL,
    CONF_UTALAS_NAP,
    CONF_DIKT_ABLAK,
    CONF_SZAMLAZAS_HONAP,
    CONF_ELOZO_EV,
    CONF_HASZNALAT,
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
    CONF_A2_CSUCS,
    CONF_A2_VOLGY,
    CONF_FORRAS_KORREKCIO,
    CONF_FORRAS_TOL,
    CONF_PROFIL_FORRAS,
    CONF_FUTES_GJ_HO,
    CONF_GAZMERO_TELJESITMENY,
    CONF_LEGTERFOGAT,
    CONF_KOZOSSEG_TIPUS,
    CONF_LAKASSZAM,
    CONF_GYARI_SZAM,
    CONF_SZOBASZAM,
    CONF_TUZHELY,
    CONF_IDOSZAK_MOD,
    CONF_IDOSZAK_NAP,
    CONF_KERET_AKTIV,
    CONF_KEZDO_ALLAS,
    CONF_KOZMU,
    CONF_SZOLGALTATO,
    CONF_SZORZO,
    DOMAIN,
    FIOK,
    SZIGET,
)
from .tar import dijszabas_tar

KOZMUVEK = ["villany", "gaz", "viz", "tavho", "hulladek", "kozos", "tavkozles"]
# Területhez kötött díjszabások (MVM árlap): csak ezeknél a szolgáltatóknál (elosztói területen) érhetők el.
ALAP_DIJSZABAS = {"villany": "villany/a1", "gaz": "gaz/lakossagi", "viz": "viz/dakov", "hulladek": "hulladek/mohu", "tavho": "tavho/hvsz", "kozos": "kozos/tarsashaz", "tavkozles": "tavkozles/elofizetes"}
TERULETI = {"villany/b_komfort": {"mvm_demasz"}, "villany/b_geo": {"elmu", "elmu_emasz"}}
# A varázsló összes, díjszabástól/közműtől függő mezője: amit az utolsó bejárás nem kérdezett, az a mentéskor törlődik
# (pl. A1 → H váltáskor a napelem-beállítás). A Díjnet-mező kivétel: csak akkor látszik, ha van Díjnet-mappa.
FELTETELES = {
    CONF_ELSZAMOLAS_MOD, CONF_FIZETESI_MOD, CONF_IDOSZAK_MOD, CONF_IDOSZAK_NAP, CONF_KERET_AKTIV, CONF_SZOBASZAM,
    CONF_TUZHELY, CONF_GYARI_SZAM, CONF_BEEPITVE, CONF_KEZDO_ALLAS, CONF_FORRAS, CONF_FORRAS_TIPUS, CONF_SZORZO,
    CONF_FORRAS_KORREKCIO, CONF_FORRAS_TOL, CONF_PROFIL_FORRAS, CONF_H_TELI, CONF_H_NYARI, CONF_A2_CSUCS, CONF_A2_VOLGY,
    CONF_NAPELEM, CONF_BETAPLALAS, CONF_CSATORNADIJ, CONF_ALMERO, CONF_ALMERO_FORRAS, CONF_ALMERO_BEEPITVE,
    CONF_ALMERO_KEZDO, CONF_GAZMERO_TELJESITMENY, CONF_LEGTERFOGAT, CONF_FUTES_GJ_HO, CONF_KOZOSSEG_TIPUS, CONF_LAKASSZAM, CONF_SZAMLA_MAPPA,
    CONF_SZAMLA_MEROK, CONF_SZAMLAZAS_HONAP, CONF_ELSZAMOLAS_HONAP, CONF_KOV_EVES, CONF_ATALANY_MENNYISEG, CONF_RESZSZAMLA_OSSZEG,
    CONF_RESZSZAMLA_DB, CONF_ELOZO_EV,
}


def _van_keret(tar: Any, azonosito: str, latott: set[str]) -> bool:
    """Van-e kedvezményes keret a díjszabás bármely verziójában (az idényszakok hivatkozott díjszabásaival együtt)."""
    if azonosito in latott or azonosito not in tar.dijszabasok:
        return False
    latott.add(azonosito)
    for v in tar[azonosito].verziok:
        if ((v.szabalyok.get("keret") or {}).get("tipus") or "nincs") != "nincs":
            return True
        for sz in v.szabalyok.get("idenyszak") or []:
            if ((sz.get("keret") or {}).get("tipus") or "nincs") != "nincs":
                return True
            if sz.get("dijszabas") and _van_keret(tar, sz["dijszabas"], latott):
                return True
    return False


class RezsiConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=user_input["nev"], data={})
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required("nev", default="Otthon"): TextSelector()})
        )

    async def async_step_import(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Visszaállítás mentésből (mentes_ha.visszaallit): új otthon a mentés alárendelt bejegyzéseivel; a régi
        azonosító az adatokban marad, amíg az első indulás (mentes_ha.befejezes) át nem kulcsolja a tárolt adatokat."""
        from .mentes import REGI_ID  # noqa: PLC0415

        return self.async_create_entry(
            title=data["nev"],
            data={"visszaallitas": data["visszaallitas"]},
            options=data.get("beallitas") or {},
            subentries=[
                ConfigSubentryData(data={**a["data"], REGI_ID: a["subentry_id"]}, subentry_type=a["subentry_type"],
                                   title=a["title"], unique_id=None)
                for a in data["alarendeltek"]
            ],
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OtthonBeallitasFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {FIOK: FiokFlow, SZIGET: SzigetFlow}


class OtthonBeallitasFlow(OptionsFlow):
    """Az otthon beállításai (Konfigurálás): fűtés-termosztát, benti és kinti hőmérséklet – az indítókártyához.
    Üresen hagyva az otthon kártyáján nincs hőmérséklet és füst."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            egyeb = {k: v for k, v in self.config_entry.options.items() if k not in OTTHON_BEALLITASOK}
            return self.async_create_entry(data=egyeb | {k: v for k, v in user_input.items() if k in OTTHON_BEALLITASOK and v})
        sema = vol.Schema({
            vol.Optional(CONF_FUTES): EntitySelector(EntitySelectorConfig(domain=["climate", "switch", "binary_sensor", "input_boolean"])),
            vol.Optional(CONF_BELSO_HOMERSEKLET): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="temperature")),
            vol.Optional(CONF_KULSO_HOMERSEKLET): EntitySelector(EntitySelectorConfig(domain=["sensor", "weather"])),
        })
        return self.async_show_form(step_id="init", data_schema=self.add_suggested_values_to_schema(sema, dict(self.config_entry.options)))


class FiokFlow(ConfigSubentryFlow):
    """Szolgáltatói fiók felvétele és szerkesztése, lépésenként – mindig csak az adott fióknál érvényes mezőkkel.

    1. név és közmű → 2. szolgáltatás (szolgáltató, díjszabás) → 3. elszámolás (csak a díjszabáshoz tartozó kérdések:
    villanynál az elszámolás módja, gáznál/víznél a fizetés módja és az időszak, keret csak kerettel rendelkező
    díjszabásnál; gázmérő nélküli átalánynál csak a szobaszám és a tűzhely – utána kész) → 4. mérő (gyári szám,
    kezdőnap, kezdőállás, szenzor; H-regiszter csak H-nál, A2-regiszter csak A2-nél, napelem csak A1-nél, almérő csak
    víznél, mérő-teljesítmény csak gáz B1-nél) → 5. számlák és fizetés (átalány-mezők csak átalányos fióknál).
    Fix díjas fióknál (hulladék) a mérő lépés kimarad.
    """

    def __init__(self) -> None:
        super().__init__()
        self._adat: dict[str, Any] = {}
        self._szerkesztes = False
        self._mutatott: set[str] = set()

    # ------------------------------------------------------------------ belépési pontok

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._adat = dict(user_input)
            return await self.async_step_szolgaltatas()
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

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        self._adat = {**sub.data, "nev": sub.title}
        self._szerkesztes = True
        return await self.async_step_szolgaltatas()

    # ------------------------------------------------------------------ lépések

    def _atvesz(self, sema: vol.Schema, user_input: dict[str, Any]) -> None:
        """A lépés mezőit a beírtakkal cseréli (a kiürített opcionális mező így törlődik)."""
        kulcsok = {str(k) for k in sema.schema}
        self._mutatott |= kulcsok
        self._adat = {k: v for k, v in self._adat.items() if k not in kulcsok} | user_input

    async def async_step_szolgaltatas(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sema = await self._szolgaltatas_sema()
        hibak: dict[str, str] = {}
        if user_input is not None:
            teruleti = TERULETI.get(user_input.get(CONF_DIJSZABAS))
            if teruleti and user_input.get(CONF_SZOLGALTATO) not in teruleti:
                hibak[CONF_DIJSZABAS] = "teruleti_dijszabas"
            else:
                self._atvesz(sema, user_input)
                return await self.async_step_elszamolas()
        return self.async_show_form(
            step_id="szolgaltatas", data_schema=self.add_suggested_values_to_schema(sema, user_input) if user_input else sema,
            errors=hibak, description_placeholders={"nev": self._adat.get("nev", "")},
        )

    async def async_step_elszamolas(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sema = await self._elszamolas_sema()
        if user_input is not None or not sema.schema:
            self._atvesz(sema, user_input or {})
            if fix_dijas(self._adat):  # fix díj (hulladék, gázmérő nélküli átalány): nincs mérő, csak a számlák
                return await self.async_step_szamlak()
            return await self.async_step_mero()
        return self.async_show_form(step_id="elszamolas", data_schema=sema, description_placeholders={"nev": self._adat.get("nev", "")})

    async def async_step_mero(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sema = await self._mero_sema()
        if user_input is not None:
            self._atvesz(sema, user_input)
            return await self.async_step_szamlak()
        return self.async_show_form(step_id="mero", data_schema=sema, description_placeholders={"nev": self._adat.get("nev", "")})

    async def async_step_szamlak(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sema = await self._szamlak_sema()
        if user_input is not None:
            self._atvesz(sema, user_input)
            return self._kesz()
        return self.async_show_form(step_id="szamlak", data_schema=sema, description_placeholders={"nev": self._adat.get("nev", "")})

    def _kesz(self) -> SubentryFlowResult:
        # A most nem kérdezett, díjszabástól függő mezők régi értéke ne maradjon meg (pl. díjszabás-váltás után).
        adat = {k: v for k, v in self._adat.items() if k != "nev" and (k not in FELTETELES or k in self._mutatott)}
        if self._szerkesztes:
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), title=self._adat["nev"], data=adat
            )
        return self.async_create_entry(title=self._adat["nev"], data=adat)

    # ------------------------------------------------------------------ sémák

    def _alap(self, kulcs: str, x: Any = None) -> Any:
        return self._adat.get(kulcs, x)

    def _javasolt(self, kulcs: str, ertek: Any = None) -> dict[str, Any]:
        """Opcionális mező előtöltése (a kiüríthetőség megmarad)."""
        v = self._adat.get(kulcs, ertek)
        return {"description": {"suggested_value": v}} if v not in (None, "") else {}

    def _reszszamlas(self) -> bool:
        if self._adat.get(CONF_KOZMU) == "villany":
            return self._adat.get(CONF_ELSZAMOLAS_MOD) == "atalany"
        return self._adat.get(CONF_FIZETESI_MOD) == "reszszamla"

    async def _szolgaltatas_sema(self) -> vol.Schema:
        kozmu = self._adat[CONF_KOZMU]
        tar = await dijszabas_tar(self.hass)
        szolg = [SelectOptionDict(value=k, label=v["nev"]) for k, v in tar.szolgaltatok.items() if kozmu in v.get("kozmu", [])]
        dijsz = [SelectOptionDict(value=k, label=d.nev) for k, d in sorted(tar.dijszabasok.items()) if d.kozmu == kozmu and k != "villany/hmke"]
        mezok: dict[Any, Any] = {}
        if self._szerkesztes:
            mezok[vol.Required("nev", default=self._alap("nev", ""))] = TextSelector()
        mezok |= {
            vol.Required(CONF_SZOLGALTATO, default=self._alap(CONF_SZOLGALTATO, szolg[0]["value"])): SelectSelector(SelectSelectorConfig(options=szolg)),
            vol.Required(CONF_DIJSZABAS, default=self._alap(CONF_DIJSZABAS, ALAP_DIJSZABAS.get(kozmu, dijsz[0]["value"]))): SelectSelector(SelectSelectorConfig(options=dijsz)),
        }
        mezok[vol.Required(CONF_DIJSZABAS_TOL, default=self._alap(CONF_DIJSZABAS_TOL, "2024-01-01"))] = DateSelector()
        return vol.Schema(mezok)

    async def _elszamolas_sema(self) -> vol.Schema:
        """Csak az adott díjszabáshoz tartozó elszámolási kérdések."""
        kozmu = self._adat[CONF_KOZMU]
        ds = self._adat.get(CONF_DIJSZABAS)
        tar = await dijszabas_tar(self.hass)
        mezok: dict[Any, Any] = {}
        if ds == "gaz/mero_nelkuli":
            mezok[vol.Required(CONF_SZOBASZAM, default=str(self._alap(CONF_SZOBASZAM, "2")))] = SelectSelector(
                SelectSelectorConfig(options=list(SZOBASZAMOK), translation_key="szobaszam", mode=SelectSelectorMode.DROPDOWN)
            )
            mezok[vol.Required(CONF_TUZHELY, default=self._alap(CONF_TUZHELY, "3_4_langu"))] = SelectSelector(
                SelectSelectorConfig(options=list(TUZHELYEK), translation_key="tuzhely", mode=SelectSelectorMode.LIST)
            )
            return vol.Schema(mezok)
        if kozmu == "villany" and ds != "villany/d":  # D: mindig távleolvasás (havi idősoros)
            regi = "atalany" if self._adat.get(CONF_FIZETESI_MOD) == "reszszamla" else "diktalas"
            mezok[vol.Required(CONF_ELSZAMOLAS_MOD, default=self._alap(CONF_ELSZAMOLAS_MOD, regi))] = SelectSelector(
                SelectSelectorConfig(options=list(ELSZAMOLAS_MODOK), translation_key="elszamolas_mod", mode=SelectSelectorMode.LIST)
            )
        elif kozmu not in FIX_DIJAS:
            mezok[vol.Required(CONF_FIZETESI_MOD, default=self._alap(CONF_FIZETESI_MOD, "fogyasztas_szerint"))] = SelectSelector(
                SelectSelectorConfig(options=["fogyasztas_szerint", "reszszamla"], translation_key="fizetesi_mod", mode=SelectSelectorMode.LIST)
            )
            mezok[vol.Required(CONF_IDOSZAK_MOD, default=self._alap(CONF_IDOSZAK_MOD, "naptari_honap"))] = SelectSelector(
                SelectSelectorConfig(options=["naptari_honap", "egyedi_nap"], translation_key="idoszak_mod")
            )
            mezok[vol.Required(CONF_IDOSZAK_NAP, default=self._alap(CONF_IDOSZAK_NAP, 1))] = NumberSelector(
                NumberSelectorConfig(min=1, max=28, step=1, mode=NumberSelectorMode.BOX)
            )
        if kozmu == "tavho":  # a fűtés a lakásban nem mért: légköbméter-arányos alapdíj és havi hődíj-átalány
            mezok[vol.Required(CONF_LEGTERFOGAT, default=self._alap(CONF_LEGTERFOGAT, 100))] = NumberSelector(
                NumberSelectorConfig(min=1, max=10000, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement="lm³")
            )
            mezok[vol.Optional(CONF_FUTES_GJ_HO, **self._javasolt(CONF_FUTES_GJ_HO))] = NumberSelector(
                NumberSelectorConfig(min=0, max=100, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement="GJ/hó")
            )
        if ds and ds in tar.dijszabasok and _van_keret(tar, ds, set()):
            mezok[vol.Required(CONF_KERET_AKTIV, default=self._alap(CONF_KERET_AKTIV, True))] = BooleanSelector()
        return vol.Schema(mezok)

    async def _mero_sema(self) -> vol.Schema:
        kozmu = self._adat[CONF_KOZMU]
        h_tarifa = self._adat.get(CONF_DIJSZABAS) == "villany/h"
        mezok: dict[Any, Any] = {
            vol.Optional(CONF_GYARI_SZAM, **self._javasolt(CONF_GYARI_SZAM)): TextSelector(),
            # Üresen hagyva automatikus: a szenzor HA-statisztikájából, ill. mostani értékéből (lásd modell.kezdopont).
            vol.Optional(CONF_BEEPITVE, **self._javasolt(CONF_BEEPITVE)): DateSelector(),
            vol.Optional(CONF_KEZDO_ALLAS, **self._javasolt(CONF_KEZDO_ALLAS)): NumberSelector(
                NumberSelectorConfig(min=0, max=99999999, step="any", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_FORRAS, **self._javasolt(CONF_FORRAS)): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Required(CONF_FORRAS_TIPUS, default=self._alap(CONF_FORRAS_TIPUS, "meroallas")): SelectSelector(
                SelectSelectorConfig(options=["meroallas", "szamlalo"], translation_key="forras_tipus")
            ),
            vol.Required(CONF_SZORZO, default=self._alap(CONF_SZORZO, 1)): NumberSelector(
                NumberSelectorConfig(min=0.5, max=2, step="any", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_FORRAS_KORREKCIO, default=self._alap(CONF_FORRAS_KORREKCIO, True)): BooleanSelector(),
            vol.Optional(CONF_FORRAS_TOL, **self._javasolt(CONF_FORRAS_TOL)): DateSelector(),
        }
        if kozmu in ("gaz", "viz"):  # ritka (pl. éves) leolvasásnál a havi elosztás alakja
            mezok[vol.Optional(CONF_PROFIL_FORRAS, **self._javasolt(CONF_PROFIL_FORRAS))] = EntitySelector(EntitySelectorConfig(domain="sensor"))
        if kozmu == "villany" and h_tarifa:
            for kulcs in (CONF_H_TELI, CONF_H_NYARI):
                mezok[vol.Optional(kulcs, **self._javasolt(kulcs))] = EntitySelector(EntitySelectorConfig(domain="sensor"))
        if kozmu == "villany" and self._adat.get(CONF_DIJSZABAS) == "villany/a2":
            for kulcs in (CONF_A2_CSUCS, CONF_A2_VOLGY):
                mezok[vol.Optional(kulcs, **self._javasolt(kulcs))] = EntitySelector(EntitySelectorConfig(domain="sensor"))
        if kozmu == "villany" and self._adat.get(CONF_DIJSZABAS) == "villany/a1":  # napelem: csak A1 mellett
            ajanlott = self._adat.get(CONF_BETAPLALAS) or await self._energia_betaplalas()
            mezok[vol.Required(CONF_NAPELEM, default=self._alap(CONF_NAPELEM, "nincs"))] = SelectSelector(
                SelectSelectorConfig(options=["nincs", "brutto", "szaldo"], translation_key="napelem_mod")
            )
            mezok[vol.Optional(CONF_BETAPLALAS, **({"description": {"suggested_value": ajanlott}} if ajanlott else {}))] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )
        if self._adat.get(CONF_DIJSZABAS) == "gaz/lakossagi_b1":
            mezok[vol.Required(CONF_GAZMERO_TELJESITMENY, default=self._alap(CONF_GAZMERO_TELJESITMENY, 25))] = NumberSelector(
                NumberSelectorConfig(min=20, max=10000, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement="m³/h")
            )
        if self._adat.get(CONF_DIJSZABAS) == "gaz/fogyasztoi_kozosseg":
            mezok[vol.Required(CONF_KOZOSSEG_TIPUS, default=self._alap(CONF_KOZOSSEG_TIPUS, "tarsashaz"))] = SelectSelector(
                SelectSelectorConfig(options=["tarsashaz", "csaladi"], translation_key="kozosseg_tipus", mode=SelectSelectorMode.LIST)
            )
            mezok[vol.Required(CONF_LAKASSZAM, default=self._alap(CONF_LAKASSZAM, 2))] = NumberSelector(
                NumberSelectorConfig(min=1, max=1000, step=1, mode=NumberSelectorMode.BOX)
            )
        if kozmu == "viz":
            mezok[vol.Required(CONF_CSATORNADIJ, default=self._alap(CONF_CSATORNADIJ, True))] = BooleanSelector()
            mezok[vol.Required(CONF_ALMERO, default=self._alap(CONF_ALMERO, False))] = BooleanSelector()
            mezok[vol.Optional(CONF_ALMERO_FORRAS, **self._javasolt(CONF_ALMERO_FORRAS))] = EntitySelector(EntitySelectorConfig(domain="sensor"))
            mezok[vol.Optional(CONF_ALMERO_BEEPITVE, **self._javasolt(CONF_ALMERO_BEEPITVE))] = DateSelector()
            mezok[vol.Optional(CONF_ALMERO_KEZDO, **self._javasolt(CONF_ALMERO_KEZDO, 0))] = NumberSelector(
                NumberSelectorConfig(min=0, max=99999999, step="any", mode=NumberSelectorMode.BOX)
            )
        return vol.Schema(mezok)

    async def _szamlak_sema(self) -> vol.Schema:
        mappak = await self.hass.async_add_executor_job(szamlak.jelolt_mappak, Path(self.hass.config.config_dir))
        mezok: dict[Any, Any] = {
            vol.Optional(CONF_SZAMLA_MAPPA, **self._javasolt(CONF_SZAMLA_MAPPA)): SelectSelector(SelectSelectorConfig(options=mappak, custom_value=True)),
        }
        if not fix_dijas(self._adat) and self._adat.get(CONF_KOZMU) != "tavho":  # a távhőszámlán nincs mérőszám
            # A számla-mérők javasolt értéke a mérő gyári száma (közös mappánál ez választja szét az A1-et és a H-t).
            mezok[vol.Optional(CONF_SZAMLA_MEROK, **self._javasolt(CONF_SZAMLA_MEROK, self._adat.get(CONF_GYARI_SZAM)))] = TextSelector()
        dn = await self.hass.async_add_executor_job(dijnet.szolgaltatok, Path(self.hass.config.config_dir), DIJNET_MINTA)
        if dn:
            mezok[vol.Optional(CONF_DIJNET, **self._javasolt(CONF_DIJNET))] = SelectSelector(SelectSelectorConfig(options=dn, custom_value=True))
        mezok[vol.Optional(CONF_SZAMLAZAS_HONAP, **({"description": {"suggested_value": str(self._adat[CONF_SZAMLAZAS_HONAP])}} if self._adat.get(CONF_SZAMLAZAS_HONAP) else {}))] = SelectSelector(
            SelectSelectorConfig(options=["1", "2", "3", "4", "6", "12"], translation_key="szamlazas_honap")
        )
        if not fix_dijas(self._adat):
            mezok[vol.Optional(CONF_ELSZAMOLAS_HONAP, **({"description": {"suggested_value": str(self._adat[CONF_ELSZAMOLAS_HONAP])}} if self._adat.get(CONF_ELSZAMOLAS_HONAP) else {}))] = SelectSelector(
                SelectSelectorConfig(options=["6", "12"], translation_key="elszamolas_honap")
            )
            # Tört év (beköltözés, új szolgáltatás évközben): a szolgáltató éves ciklusa nem a kezdőnaptól indul.
            mezok[vol.Optional(CONF_KOV_EVES, **self._javasolt(CONF_KOV_EVES))] = DateSelector()
            # Diktálási ablak (pl. „8-14”): új fióknál még nincs számla, amely közölné.
            mezok[vol.Optional(CONF_DIKT_ABLAK, **self._javasolt(CONF_DIKT_ABLAK))] = TextSelector()
        # Állandó (ütemezett) banki átutalás a hónap e napján – a befizetés ebből, ha nincs más adat.
        mezok[vol.Optional(CONF_UTALAS_NAP, **self._javasolt(CONF_UTALAS_NAP))] = NumberSelector(
            NumberSelectorConfig(min=1, max=31, step=1, mode=NumberSelectorMode.BOX)
        )
        # Szüneteltetett számlázás (pl. lakatlan ingatlan): erre az időre semmi nem jár, számla sem várható.
        mezok[vol.Optional(CONF_SZUNETEL_TOL, **self._javasolt(CONF_SZUNETEL_TOL))] = DateSelector()
        mezok[vol.Optional(CONF_SZUNETEL_IG, **self._javasolt(CONF_SZUNETEL_IG))] = DateSelector()
        if self._reszszamlas():
            mezok[vol.Optional(CONF_ATALANY_MENNYISEG, **self._javasolt(CONF_ATALANY_MENNYISEG))] = NumberSelector(
                NumberSelectorConfig(min=0, max=10000000, step="any", mode=NumberSelectorMode.BOX)
            )
            mezok[vol.Optional(CONF_RESZSZAMLA_OSSZEG, **self._javasolt(CONF_RESZSZAMLA_OSSZEG))] = NumberSelector(
                NumberSelectorConfig(min=0, max=10000000, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement="Ft")
            )
            mezok[vol.Required(CONF_RESZSZAMLA_DB, default=self._alap(CONF_RESZSZAMLA_DB, 11))] = NumberSelector(
                NumberSelectorConfig(min=1, max=12, step=1, mode=NumberSelectorMode.BOX)
            )
            mezok[vol.Optional(CONF_ELOZO_EV, **self._javasolt(CONF_ELOZO_EV))] = NumberSelector(
                NumberSelectorConfig(min=0, max=10000000, step="any", mode=NumberSelectorMode.BOX)
            )
            mezok[vol.Required(CONF_HASZNALAT, default=self._alap(CONF_HASZNALAT, "allando"))] = SelectSelector(
                SelectSelectorConfig(options=["allando", "nyaralo"], translation_key="hasznalat", mode=SelectSelectorMode.LIST)
            )
        return vol.Schema(mezok)

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


class SzigetFlow(ConfigSubentryFlow):
    """Szigetüzemi energiarendszer (kísérleti): név és szerepkörök → szerepkörönként energia-szenzorok (akár több).

    Csak kWh-ban követ (docs/terv/06_SZIGETUZEM.md); szenzor nélkül a `hu_rezsi.sziget_leolvasas` kézi állásaiból."""

    def __init__(self) -> None:
        super().__init__()
        self._adat: dict[str, Any] = {}
        self._szerkesztes = False

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        from .motor import sziget as m  # noqa: PLC0415

        if user_input is not None:
            self._adat |= user_input
            return await self.async_step_forrasok()
        opciok = [s for s in m.SZEREPEK if s != m.FOGYASZTAS]
        mezok: dict[Any, Any] = {}
        mezok[vol.Required("nev", default=self._adat.get("nev", "Szigetüzem"))] = TextSelector()
        mezok[vol.Optional("szerepek", default=self._adat.get("szerepek", ["pv", "akku_toltes", "akku_kisutes"]))] = SelectSelector(
            SelectSelectorConfig(options=opciok, multiple=True, translation_key="sziget_szerep", mode=SelectSelectorMode.LIST)
        )
        return self.async_show_form(step_id="user", data_schema=vol.Schema(mezok))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        self._adat = {**sub.data, "nev": sub.title}
        self._szerkesztes = True
        return await self.async_step_user()

    async def async_step_forrasok(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        from .motor import sziget as m  # noqa: PLC0415

        szerepek = [m.FOGYASZTAS, *[s for s in m.SZEREPEK if s in (self._adat.get("szerepek") or [])]]
        if user_input is not None:
            adat = {"szerepek": list(self._adat.get("szerepek") or [])} | {
                f"forras_{s}": user_input.get(f"forras_{s}") or [] for s in szerepek
            }
            if self._szerkesztes:
                return self.async_update_and_abort(
                    self._get_entry(), self._get_reconfigure_subentry(), title=self._adat["nev"], data=adat
                )
            return self.async_create_entry(title=self._adat["nev"], data=adat)
        mezok: dict[Any, Any] = {}
        for sz in szerepek:
            regi = self._adat.get(f"forras_{sz}")
            mezok[vol.Optional(f"forras_{sz}", **({"description": {"suggested_value": regi}} if regi else {}))] = EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
            )
        return self.async_show_form(step_id="forrasok", data_schema=vol.Schema(mezok), description_placeholders={"nev": self._adat.get("nev", "")})
