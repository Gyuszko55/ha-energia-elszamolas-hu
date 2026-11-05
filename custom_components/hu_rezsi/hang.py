"""Hangutasítások (Assist): a Rezsikövető szándékai (intent) – 2.4.0b1, bővítve 2.4.0b2.

- HuRezsiBefizetendo   „Van befizetendő számlám?”          a még be nem fizetett számlák, határidővel
- HuRezsiKovetkezoSzamla „Mennyi lesz a következő gázszámla?” a várható következő számla összege és ideje
- HuRezsiKoltseg       „Mennyi a villany eddig?”           a folyó időszak költsége eddig és várhatóan
- HuRezsiKeret         „Hol tartok a keretben?”            a kedvezményes (rezsicsökkentett) keretből hátralévő
- HuRezsiUtolsoSzamla  „Mennyi volt az utolsó vízszámla?”  a legutóbbi számla összege és kelte

Mindegyiknek elhagyható `kozmu` része van (villany, gáz, víz, távhő, szemét, internet, közös költség), és csak a
beállításban kiválasztott otthonokra válaszol (Panel beállításai → Otthonok). Amíg a HA indulása után az első
számolás nem futott le (pl. a Díjnet-fizetések még nincsenek betöltve), nem ad (téves) választ.
Az LLM-es Assist-ügynök (pl. Gemini) mindegyiket eszközként kapja (llm.py); a helyi Assist a
custom_sentences/hu/hu_rezsi.yaml mondataival.
"""

from __future__ import annotations

import unicodedata
from datetime import date, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, intent
from homeassistant.util import dt as dt_util

from . import panel_beallitas as pb
from .const import CONF_KOZMU, DOMAIN

BETOLT_SZOVEG = "A számlák adatai még töltődnek, próbáld újra pár perc múlva."
HONAP_NEV = ("január", "február", "március", "április", "május", "június", "július", "augusztus", "szeptember",
             "október", "november", "december")
EGYSEG_HANG = {"kWh": "kilowattóra", "m3": "köbméter", "m³": "köbméter", "MJ": "megajoule", "GJ": "gigajoule"}

# A kimondott közmű → a fiók közmű-kódja (Kozmu). Ékezet nélkül is (az LLM-ek gyakran úgy adják).
KOZMU_SZAVAK: dict[str, tuple[str, ...]] = {
    "villany": ("villany", "aram", "villamos", "elektromos"),
    "gaz": ("gaz", "foldgaz"),
    "viz": ("viz", "csatorna", "vizdij"),
    "tavho": ("tavho", "futes", "melegviz", "hodij"),
    "hulladek": ("szemet", "hulladek", "kuka"),
    "tavkozles": ("internet", "tv", "teve", "televizio", "telefon", "mobil"),
    "kozos": ("kozos", "kozos koltseg", "tarsashaz"),
}
KOZMU_NEV = {"villany": "villany", "gaz": "gáz", "viz": "víz", "tavho": "távhő", "hulladek": "szemétszállítás",
             "tavkozles": "internet, TV, telefon", "kozos": "közös költség"}


def _sima(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").strip()


def kozmu_kod(szo: str | None) -> str | None:
    """A kimondott közmű kódja (None: nincs megadva / nem ismert → minden fiók)."""
    if not szo:
        return None
    s = _sima(szo)
    for kod, szavak in KOZMU_SZAVAK.items():
        if s == kod or any(s == w or s.startswith(w) for w in szavak):
            return kod
    return None


def ft_hang(n: Any) -> str:
    return f"{int(round(float(n))):,}".replace(",", " ") + " forint"


def datum_hang(d: Any) -> str:
    x = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    return f"{HONAP_NEV[x.month - 1]} {x.day}."


# A nap ragja („-án/-én”): 1-jén, 2-án, 3-án, 4-én … (a számnév kiejtése szerint)
_NAP_RAG = {1: "-jén", 2: "-án", 3: "-án", 6: "-án", 8: "-án", 13: "-án", 16: "-án", 18: "-án", 20: "-án", 23: "-án",
            26: "-án", 28: "-án", 30: "-án"}


def datumon_hang(d: Any) -> str:
    """„december 12-én”, „november 3-án” – mikor?"""
    x = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    return f"{HONAP_NEV[x.month - 1]} {x.day}{_NAP_RAG.get(x.day, '-én')}"


def mennyiseg_hang(n: Any, egyseg: str | None) -> str:
    v = float(n)
    szam = f"{v:,.0f}".replace(",", " ") if abs(v) >= 10 else f"{v:.1f}".replace(".", ",")
    return f"{szam} {EGYSEG_HANG.get(egyseg or '', egyseg or '')}".strip()


# ---------------------------------------------------------------------------------------- adatok


def otthonok(hass: HomeAssistant) -> list[Any]:
    """A beállításban kiválasztott (üres: minden) otthon config entry-jei, amelyek be vannak töltve."""
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if getattr(e, "runtime_data", None) is not None]
    if valasztott := set(pb.aktualis(hass).get(pb.ERT_OTTHONOK) or []):
        entries = [e for e in entries if e.entry_id in valasztott]
    return entries


def kesz(hass: HomeAssistant) -> bool:
    """Lefutott-e minden (kiválasztott) otthon első számolása – addig a Díjnet-fizetések, várható összegek hiányoznak."""
    return all(getattr(e.runtime_data, "data", None) is not None for e in otthonok(hass))


def fiokok(hass: HomeAssistant, kozmu: str | None = None) -> list[dict[str, Any]]:
    """{otthon, nev, kozmu, a (FiokAllapot), sid, koord} a kiválasztott otthonok aktív fiókjairól, közmű szerint szűrve."""
    ki = []
    entries = otthonok(hass)
    for e in entries:
        koord = e.runtime_data
        for sid, sub in koord.fiokok().items():
            kod = sub.data.get(CONF_KOZMU)
            if kozmu and kod != kozmu:
                continue
            a = (koord.data or {}).get(sid)
            if a is None or getattr(a, "megszunt", None):
                continue
            ki.append({"otthon": e.title, "nev": sub.title, "kozmu": kod, "a": a, "sid": sid, "koord": koord,
                       "tobb": len(entries) > 1})
    return ki


def _nev(f: dict[str, Any]) -> str:
    return f"{f['otthon']} · {f['nev']}" if f.get("tobb") else f["nev"]


def _pont(s: str) -> str:
    return s if s.endswith(".") else s + "."


def _kozmu_resz(kozmu: str | None) -> str:
    return f" ({KOZMU_NEV[kozmu]})" if kozmu else ""


# ---------------------------------------------------------------------------------------- válaszok


def kovetkezo_valasz(ff: list[dict[str, Any]], kozmu: str | None, ma: date) -> str:
    sorok = []
    for f in ff:
        a = f["a"]
        src = a.esedekes or a.szamla_stat or {}
        datum, osszeg = src.get("kovetkezo_datum"), src.get("kovetkezo_osszeg")
        if not datum:
            continue
        try:
            d = datum if isinstance(datum, date) else date.fromisoformat(str(datum)[:10])
        except ValueError:
            continue
        mikor = "ma" if d == ma else ("holnap" if d == ma + timedelta(days=1) else f"{datum_hang(d)} körül")
        if d < ma:
            mikor = f"{datum_hang(d)} óta várható, még nem érkezett meg"
        sorok.append((d, f"{_nev(f)}: {'kb. ' + ft_hang(osszeg) + ', ' if osszeg else ''}{mikor}"))
    if not sorok:
        return f"Nem tudom, mikor jön a következő számla{_kozmu_resz(kozmu)}."
    sorok.sort(key=lambda x: x[0])
    eleje = "A következő számla" if len(sorok) == 1 else "A következő számlák"
    return _pont(f"{eleje}{_kozmu_resz(kozmu)}: " + "; ".join(s for _, s in sorok))


def koltseg_valasz(ff: list[dict[str, Any]], kozmu: str | None) -> str:
    sorok, eddig_ossz, varhato_ossz = [], 0.0, 0.0
    for f in ff:
        ny = f["a"].nyitott
        if ny is None:
            continue
        eddig, varhato = float(ny.eddig.osszesen_ft), float(ny.varhato.osszesen_ft)
        eddig_ossz += eddig
        varhato_ossz += varhato
        sorok.append(f"{_nev(f)} eddig {ft_hang(eddig)}, várhatóan {ft_hang(varhato)}")
    if not sorok:
        return f"Ehhez{_kozmu_resz(kozmu)} nincs folyó elszámolási időszak."
    if len(sorok) == 1:
        return f"A folyó elszámolási időszakban: {sorok[0]}."
    return (f"A folyó elszámolási időszakokban{_kozmu_resz(kozmu)} eddig összesen {ft_hang(eddig_ossz)}, "
            f"az időszakok végére várhatóan {ft_hang(varhato_ossz)}: " + "; ".join(sorok) + ".")


def keret_valasz(ff: list[dict[str, Any]], kozmu: str | None) -> str:
    sorok = []
    for f in ff:
        a = f["a"]
        ny = a.nyitott
        if ny is None or ny.hatralevo_keret is None:
            continue
        sz = ny.eddig.szeletek
        egyseg = sz[0].egyseg if sz and sz[0].egyseg else a.egyseg
        h = float(ny.hatralevo_keret)
        if h <= 0:
            s = f"{_nev(f)}: a kedvezményes keretet már elérte, a többi piaci áron megy"
        else:
            s = f"{_nev(f)}: a kedvezményes keretből még {mennyiseg_hang(h, egyseg)} van hátra"
            s += (f", várhatóan {datumon_hang(ny.varhato_keretatlepes)} lépi túl" if ny.varhato_keretatlepes
                  else ", az időszakban várhatóan nem lépi túl")
        sorok.append(s)
    if not sorok:
        return f"Nincs kedvezményes keretes fiók{_kozmu_resz(kozmu)}."
    return _pont("; ".join(sorok))


def utolso_valasz(ff: list[dict[str, Any]], kozmu: str | None) -> str:
    sorok = []
    for f in ff:
        u = f["a"].utolso_szamla
        if not u or u.get("osszeg") is None:
            continue
        kelte = u.get("kelte")
        sorok.append((str(kelte or ""), f"{_nev(f)}: {ft_hang(u['osszeg'])}" + (f", kelte {datum_hang(kelte)}" if kelte else "")))
    if not sorok:
        return f"Nincs rögzített számla{_kozmu_resz(kozmu)}."
    sorok.sort(key=lambda x: x[0], reverse=True)
    eleje = "Az utolsó számla" if len(sorok) == 1 else "Az utolsó számlák"
    return _pont(f"{eleje}{_kozmu_resz(kozmu)}: " + "; ".join(s for _, s in sorok))


# ---------------------------------------------------------------------------------------- szándékok

_KOZMU_SLOT = {vol.Optional("kozmu"): cv.string}
_KOZMU_SUGO = (" Optional slot 'kozmu': the utility in Hungarian – villany (electricity), gáz, víz, távhő, szemét, "
                 "internet, közös költség; leave it out for all. Answer in Hungarian.")


class RezsiIntent(intent.IntentHandler):
    """Közös alap: otthon-szűrés, készenlét, közmű-slot."""

    slot_schema = _KOZMU_SLOT
    eszkoz_nev = ""
    eszkoz_cim = ""

    def valasz(self, hass: HomeAssistant, kozmu: str | None) -> str:  # pragma: no cover – alosztályok
        raise NotImplementedError

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots) if intent_obj.slots else {}
        kozmu = kozmu_kod((slots.get("kozmu") or {}).get("value"))
        r = intent_obj.create_response()
        r.async_set_speech(self.valasz(hass, kozmu) if kesz(hass) else BETOLT_SZOVEG)
        return r


class BefizetendoIntent(RezsiIntent):
    intent_type = "HuRezsiBefizetendo"
    eszkoz_nev, eszkoz_cim = "befizetendo_szamlak", "Befizetendő számlák"
    description = ("Lists the household's unpaid utility bills (Rezsikövető) with the amount and how many days until "
                   "the payment deadline, or how many days overdue. Use it when the user asks whether there is a bill "
                   "to pay ('van befizetendő számlám?', 'milyen számlát kell befizetni?')." + _KOZMU_SUGO)

    def valasz(self, hass: HomeAssistant, kozmu: str | None) -> str:
        from . import hatarido_ertesites as he  # noqa: PLC0415 – körkörös import elkerülése

        tet = he.befizetendok(hass)
        if kozmu:
            sids = {f["sid"] for f in fiokok(hass, kozmu)}
            tet = [t for t in tet if t["sid"] in sids]
        return he.hang_valasz(tet)


class KovetkezoSzamlaIntent(RezsiIntent):
    intent_type = "HuRezsiKovetkezoSzamla"
    eszkoz_nev, eszkoz_cim = "kovetkezo_szamla", "Következő számla"
    description = ("Tells when the next utility bill is expected and its estimated amount (Rezsikövető), e.g. "
                   "'mikor jön a következő számla?', 'mennyi lesz a következő gázszámla?'." + _KOZMU_SUGO)

    def valasz(self, hass: HomeAssistant, kozmu: str | None) -> str:
        return kovetkezo_valasz(fiokok(hass, kozmu), kozmu, dt_util.now().date())


class KoltsegIntent(RezsiIntent):
    intent_type = "HuRezsiKoltseg"
    eszkoz_nev, eszkoz_cim = "koltseg_eddig", "Rezsi eddig és várhatóan"
    description = ("Tells the utility cost so far in the current billing period and the expected cost by its end "
                   "(Rezsikövető), e.g. 'mennyi a rezsi eddig?', 'mennyibe kerül a villany ebben az időszakban?'."
                   + _KOZMU_SUGO)

    def valasz(self, hass: HomeAssistant, kozmu: str | None) -> str:
        return koltseg_valasz(fiokok(hass, kozmu), kozmu)


class KeretIntent(RezsiIntent):
    intent_type = "HuRezsiKeret"
    eszkoz_nev, eszkoz_cim = "kedvezmenyes_keret", "Kedvezményes keret"
    description = ("Tells how much of the reduced-price allowance (rezsicsökkentett keret) is left for electricity or "
                   "gas and when it is expected to be exceeded (Rezsikövető), e.g. 'hol tartok a keretben?', "
                   "'mennyi van még a gázkeretből?'." + _KOZMU_SUGO)

    def valasz(self, hass: HomeAssistant, kozmu: str | None) -> str:
        return keret_valasz(fiokok(hass, kozmu), kozmu)


class UtolsoSzamlaIntent(RezsiIntent):
    intent_type = "HuRezsiUtolsoSzamla"
    eszkoz_nev, eszkoz_cim = "utolso_szamla", "Utolsó számla"
    description = ("Tells the amount and date of the latest utility bill (Rezsikövető), e.g. 'mennyi volt az utolsó "
                   "villanyszámla?'." + _KOZMU_SUGO)

    def valasz(self, hass: HomeAssistant, kozmu: str | None) -> str:
        return utolso_valasz(fiokok(hass, kozmu), kozmu)


SZANDEKOK = (BefizetendoIntent, KovetkezoSzamlaIntent, KoltsegIntent, KeretIntent, UtolsoSzamlaIntent)


def regisztral(hass: HomeAssistant) -> None:
    for k in SZANDEKOK:
        intent.async_register(hass, k())
