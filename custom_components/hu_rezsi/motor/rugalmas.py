"""D árszabás: a keret feletti fogyasztás rugalmas egységára egy szakaszra.

MVM: a szakasz (naptári hónap) negyedórás fogyasztásával súlyozott átlaga a negyedórás rugalmas egységáraknak
(HUPX × MNB-árfolyam + kereskedői díj, Ft/kWh nettó); a kedvezményes sávhatár feletti mennyiség ezen az áron fizet.
A Rezsikövető órás felbontással számol (órás fogyasztás × az óra négy negyedórás árának átlaga).
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import Any

from datetime import date, timedelta
from decimal import Decimal

from .tipusok import Fiok

_SOR = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) (\d{1,2}):(\d{2}) \d{1,2}:\d{2} (-?[\d ]+,\d+)")


def sorok_ora_arak(sorok: Any) -> dict[str, float]:
    """Az MVM árlista sorai („2025.09.01 0:00 0:15 48,56”) → órás átlagár (kulcs „ÉÉÉÉ-HH-NNTÓÓ”, helyi idő)."""
    gyujto: dict[str, list[float]] = {}
    for sor in sorok:
        m = _SOR.match(sor.strip())
        if not m:
            continue
        ev, ho, nap, ora, _, ar = m.groups()
        gyujto.setdefault(f"{ev}-{ho}-{nap}T{int(ora):02d}", []).append(float(ar.replace(" ", "").replace(",", ".")))
    return {k: round(sum(v) / len(v), 4) for k, v in gyujto.items()}


def sorok_negyed_arak(sorok: Any) -> dict[str, float]:
    """Az MVM árlista sorai → negyedórás ár (kulcs „ÉÉÉÉ-HH-NNTÓÓ:PP”, helyi idő, a negyedóra kezdete; Ft/kWh nettó)."""
    out: dict[str, float] = {}
    for sor in sorok:
        m = _SOR.match(sor.strip())
        if not m:
            continue
        ev, ho, nap, ora, perc, ar = m.groups()
        out[f"{ev}-{ho}-{nap}T{int(ora):02d}:{perc}"] = float(ar.replace(" ", "").replace(",", "."))
    return out


def negyed_ora_atlag(negyedek: dict[str, float]) -> dict[str, float]:
    """Negyedórás árak → órás átlagár (kulcs „ÉÉÉÉ-HH-NNTÓÓ”)."""
    gyujto: dict[str, list[float]] = {}
    for k, v in negyedek.items():
        gyujto.setdefault(k[:13], []).append(v)
    return {k: round(sum(v) / len(v), 4) for k, v in gyujto.items()}


EUR_HUF_MIN, EUR_HUF_MAX = 200.0, 1000.0  # ésszerű EUR/HUF sáv: ezen kívül hibás válasz, nem árfolyam


def mnb_arfolyamok(valasz: str) -> dict[str, float]:
    """Az MNB GetExchangeRates SOAP-válasza → napi EUR-középárfolyam („ÉÉÉÉ-HH-NN” → Ft/EUR).

    Szigorú: csak jól formált XML (a boríték és a benne szövegként küldött MNBExchangeRates is), értelmes dátum és
    véges, a sávba eső árfolyam fogadható el – bármilyen eltérésnél ValueError, a válasz egésze eldobandó."""
    try:
        boritek = ET.fromstring(valasz)
    except ET.ParseError as err:
        raise ValueError(f"nem jól formált XML: {err}") from err
    eredmeny = next((el for el in boritek.iter() if el.tag.rsplit("}", 1)[-1] == "GetExchangeRatesResult"), None)
    if eredmeny is None or not (eredmeny.text or "").strip():
        raise ValueError("a válaszban nincs GetExchangeRatesResult")
    try:
        arfolyamok = ET.fromstring(eredmeny.text)
    except ET.ParseError as err:
        raise ValueError(f"az árfolyamlista nem jól formált XML: {err}") from err
    if arfolyamok.tag != "MNBExchangeRates":
        raise ValueError(f"váratlan gyökérelem: {arfolyamok.tag!r}")
    ki: dict[str, float] = {}
    for nap in arfolyamok.findall("Day"):
        try:
            d = date.fromisoformat(nap.get("date") or "")
        except ValueError as err:
            raise ValueError(f"hibás dátum: {nap.get('date')!r}") from err
        for r in nap.findall("Rate"):
            if r.get("curr") != "EUR":
                continue
            try:
                egyseg = float(r.get("unit") or "1")
                ertek = float((r.text or "").strip().replace(",", ".")) / egyseg
            except (ValueError, ZeroDivisionError) as err:
                raise ValueError(f"{d}: hibás árfolyam: {r.text!r}") from err
            if not math.isfinite(ertek) or not EUR_HUF_MIN <= ertek <= EUR_HUF_MAX:
                raise ValueError(f"{d}: valószerűtlen EUR-árfolyam: {ertek}")
            ki[d.isoformat()] = ertek
    return ki


def arfolyam_napra(arfolyamok: dict[str, float], nap: str) -> float | None:
    """Az adott nap MNB EUR-árfolyama; munkaszüneti napon (nincs jegyzés) a legutóbbi korábbi jegyzés."""
    if nap in arfolyamok:
        return arfolyamok[nap]
    korabbi = [k for k in arfolyamok if k < nap]
    return arfolyamok[max(korabbi)] if korabbi else None


def hupx_negyed_arak(
    idopontok: list[str], eur_mwh: list[float | None], arfolyamok: dict[str, float], kereskedoi: float
) -> dict[str, float]:
    """A HUPX negyedórás másnapi ára (EUR/MWh) → rugalmas egységár (Ft/kWh nettó) az MVM képletével:
    HUPX × az adott napi (ennek híján a legutóbbi) MNB EUR-középárfolyam / 1000 + kereskedői díj, két tizedesre.
    Az MVM közzétett árlistájával 2026 augusztusában fillérre egyezik. idopontok: helyi „ÉÉÉÉ-HH-NNTÓÓ:PP”."""
    out: dict[str, float] = {}
    for k, ar in zip(idopontok, eur_mwh, strict=True):
        if ar is None:
            continue
        arf = arfolyam_napra(arfolyamok, k[:10])
        if arf is None:
            continue
        out[k] = round(ar * arf / 1000 + kereskedoi, 2)
    return out


def rugalmas_ar(fiok: Fiok, tol: date, ig: date) -> tuple[Decimal | None, bool]:
    """([tol, ig) fogyasztással súlyozott rugalmas egységára, becsült-e).

    fiok.d_napok: naponként (fogyasztás, fogyasztás × ár, becsült) – becsült, ha egy óra ára még nincs közzétéve, és a
    legutóbbi közzétett hónap súlyozott ára (fiok.d_tartalek) helyettesíti. Órás fogyasztás nélküli napra a nap
    átlagára (fiok.d_ar_napok), ennek híján a tartalék ár, a mért napok átlagos fogyasztásával súlyozva."""
    q = qp = Decimal(0)
    becsult = False
    hianyzo: list[date] = []
    d = tol
    while d < ig:
        x = fiok.d_napok.get(d)
        if x and x[0] > 0:
            q += x[0]
            qp += x[1]
            becsult |= x[2]
        else:
            hianyzo.append(d)
        d += timedelta(days=1)
    mert = (ig - tol).days - len(hianyzo)
    suly = q / mert if mert and q > 0 else Decimal(1)
    for h in hianyzo:
        ar = fiok.d_ar_napok.get(h)
        if ar is None:
            ar = fiok.d_tartalek
            becsult = True
        if ar is None:
            continue
        q += suly
        qp += suly * ar
        becsult = True
    if q <= 0:
        return fiok.d_tartalek, True
    return qp / q, becsult
