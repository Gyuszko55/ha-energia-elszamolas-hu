"""A fiók beállításaiból levezetett, ténylegesen használt módok (villanynál az elszámolás módja dönt)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .const import CONF_ATALANY_MENNYISEG, CONF_DIJSZABAS, CONF_ELSZAMOLAS_MOD, CONF_FIZETESI_MOD, CONF_IDOSZAK_MOD, CONF_IDOSZAK_NAP, CONF_KOZMU, FIX_DIJAS, FIX_DIJSZABASOK

ELSZAMOLAS_MODOK = ("diktalas", "atalany", "tavleolvasas")


def fix_dijas(data: dict[str, Any]) -> bool:
    """Mérő nélküli, fix havi díjas fiók: hulladékszállítás, vagy gázmérő nélküli gázátalány."""
    return data.get(CONF_KOZMU) in FIX_DIJAS or data.get(CONF_DIJSZABAS) in FIX_DIJSZABASOK


def elszamolas_mod(data: dict[str, Any]) -> str | None:
    """Villany: diktálás (a diktálások között), átalány (a számlán megadott mennyiség), távleolvasás (naptári
    hónap). Más közműnél és a régi, mód nélküli villanyfióknál None (az időszak és a fizetés mezői döntenek)."""
    if data.get(CONF_KOZMU) != "villany":
        return None
    if data.get(CONF_DIJSZABAS) == "villany/d":  # D: távlehívható mérő, havi idősoros elszámolás
        return "tavleolvasas"
    mod = data.get(CONF_ELSZAMOLAS_MOD)
    return mod if mod in ELSZAMOLAS_MODOK else None


def idoszak_mod(data: dict[str, Any]) -> tuple[str, int]:
    """(időszakmód, kezdőnap)."""
    mod = elszamolas_mod(data)
    if mod == "diktalas":
        # Diktálásnál a lezárt időszak két egymást követő leolvasás (diktálás) között tart – a fogyasztás a két
        # állás különbsége; a számla időszaka ettől eltérhet.
        return "leolvasas", 1
    if mod == "atalany":
        # MVM: átalánynál a diktálási időszak zárja a számlát (diktálás nélkül az ablak végén).
        return "diktalas", 1
    if mod == "tavleolvasas":
        return "naptari_honap", 1
    if data.get(CONF_DIJSZABAS) in FIX_DIJSZABASOK:  # gázátalány: havonta, naptári hónapra
        return "naptari_honap", 1
    alap = "negyedev" if data.get(CONF_KOZMU) == "hulladek" else "naptari_honap"  # közös költség: havonta
    return data.get(CONF_IDOSZAK_MOD) or alap, int(data.get(CONF_IDOSZAK_NAP) or 1)


def reszszamlas(data: dict[str, Any]) -> bool:
    """Részszámlás (átalányos) fiók-e."""
    mod = elszamolas_mod(data)
    if mod is not None:
        return mod == "atalany"
    if data.get(CONF_DIJSZABAS) in FIX_DIJSZABASOK:
        return False
    return data.get(CONF_FIZETESI_MOD) == "reszszamla"


def atalany_mennyiseg(data: dict[str, Any], tarolt: dict[str, Any]) -> tuple[Decimal, str] | None:
    """Havi átalány-mennyiség és a forrása: a fiókban beírt érték, különben a legutóbbi számlán szereplő
    „következő részszámla becsült mennyisége” (MVM). Nincs: None."""
    if data.get(CONF_ATALANY_MENNYISEG) not in (None, ""):  # a 0 is érvényes (pl. napelemes: 0 kWh részszámla)
        return Decimal(str(data[CONF_ATALANY_MENNYISEG])), "beállított"
    szamlak = [
        (x["kelte"], k, x["atalany_mennyiseg"])
        for k, x in (tarolt.get("szamlak") or {}).items()
        if x.get("atalany_mennyiseg") not in (None, "", "0")
    ]
    if not szamlak:
        return None
    _, sorszam, q = max(szamlak)
    return Decimal(str(q)), f"{sorszam} számla"
