"""Várható (még nem érkezett) számlák egy fiókra – a számlakimutatáshoz.

A fiók panel-adataiból (panel._fiok_adat) és a tárolt számlákból: azok a fogyasztások, amelyekről még nem jött
számla, a várható fizetendővel és a számla várható keltével. Forrás:
- „meres”: lezárt vagy folyó időszak a saját mérésből (Rezsikövető-számítás),
- „diktalas”: átalánynál a legutóbbi diktált állás szerinti számla,
- „atalany”: a következő részszámla az átalány szerint,
- „fix”: fix díjas fiók (szemétszállítás, mérő nélküli gáz) következő számlája,
- „elszamolas”: a közelgő éves (féléves) elszámoló számla várható fizetendője (mínusz: visszajár).
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any

try:
    from .szamlak import sztornozott_kulcsok
except ImportError:  # tesztek: a csomag HA nélkül, közvetlenül
    from szamlak import sztornozott_kulcsok

HORIZONT_NAP = 62  # ennyi napon belül várható számlák (a későbbiek még nem „ki nem számlázott fogyasztás”)
ALAP_KESES = 10  # nap: a számla kelte az elszámolt időszak vége után, ha a fiók számláiból nem derül ki


def _d(x: str | date | None) -> date | None:
    if x is None or isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def szamla_keses(szamlak: dict[str, dict[str, Any]]) -> int:
    """Hány nappal az elszámolt időszak vége után szokott kelni a számla (a fiók legutóbbi számlái szerint)."""
    k = [
        (_d(x["kelte"]) - _d(x["idoszak"][1])).days
        for x in sorted(szamlak.values(), key=lambda y: y.get("kelte") or "")[-8:]
        if x.get("idoszak") and x.get("kelte") and x.get("tipus") != "storno"
    ]
    k = [x for x in k if 0 <= x <= 60]
    return int(median(k)) if k else ALAP_KESES


def varhato_szamlak(f: dict[str, Any], szamlak: dict[str, dict[str, Any]], ma: date,
                    horizont: int = HORIZONT_NAP) -> list[dict[str, Any]]:
    """A fiók még nem érkezett számlái: [{kelte, honap, tol, ig, osszeg, forras}] (dátumok ISO-szövegként)."""
    if not f.get("idoszak") and not f.get("esedekes") and not f.get("uton_szamlak"):
        return []
    keses = timedelta(days=szamla_keses(szamlak))
    torolt = sztornozott_kulcsok(szamlak)  # a sztornózott számla időszaka még nincs (érvényesen) kiszámlázva
    szamlazott = [(_d(x["idoszak"][0]), _d(x["idoszak"][1])) for k, x in szamlak.items()
                  if x.get("idoszak") and x.get("tipus") != "storno" and k not in torolt]
    out: list[dict[str, Any]] = []

    def tesz(kelte: date | None, tol: Any, ig: Any, osszeg: Any, forras: str, kezdet: Any = None) -> None:
        if kelte is None or osszeg is None:
            return
        kelte = max(kelte, ma)  # elmaradt számla: még várjuk, a mostani hónapban
        if kelte > ma + timedelta(days=horizont):
            return
        out.append({"kelte": kelte.isoformat(), "honap": kelte.isoformat()[:7], "tol": _d(tol).isoformat() if tol else None,
                    "ig": _d(ig).isoformat() if ig else None, "osszeg": int(osszeg), "forras": forras, **({"kezdet": kezdet} if kezdet else {})})

    # Lezárt időszak, amelyre még nem jött számla (mért fiók).
    for x in f.get("uton_szamlak") or []:
        tesz(_d(x["ig"]) + keses, x["tol"], x["ig"], x["osszeg"], "meres", x.get("kezdet"))

    es = f.get("esedekes") or {}
    sz = f.get("szamlazasi") or {}
    sz_nyitott = bool(sz) and not sz.get("kiallitott")
    if f.get("fix_dij"):
        if es and not es.get("nincs_tobb"):
            v = es.get("vegszamla")
            tesz(_d(v["datum"]) if v else _d(es["kovetkezo_datum"]), sz.get("tol") if sz_nyitott else None,
                 (_d(sz["ig"]) - timedelta(days=1)) if sz_nyitott else None, v["osszeg"] if v else es.get("kovetkezo_osszeg"), "fix")
    elif f.get("reszszamlas"):
        if es and not es.get("nincs_tobb"):
            dik = f.get("diktalt_szamla")
            if sz_nyitott:
                tesz(_d(es["kovetkezo_datum"]), sz["tol"], _d(sz["ig"]) - timedelta(days=1), sz.get("fizetendo"),
                     "diktalas" if sz.get("diktalt") else "atalany")
            else:
                tesz(_d(es["kovetkezo_datum"]), dik["tol"] if dik else None, dik["datum"] if dik else None,
                     dik["osszeg"] if dik else es.get("kovetkezo_osszeg"), "diktalas" if dik else "atalany")
        # A közelgő éves elszámoló: a várható éves egyenleg ellentettje (mínusz: visszajár).
        egy, ut = f.get("egyenleg") or {}, f.get("utem") or {}
        if egy.get("egyenleg") is not None and ut.get("kovetkezo_elszamolas"):
            tesz(_d(ut["kovetkezo_elszamolas"]) + keses, egy.get("ev_tol"), ut["kovetkezo_elszamolas"], -egy["egyenleg"], "elszamolas")
    elif not f.get("megszunt"):
        # Mért fiók: a folyó (még nem számlázott) időszak a saját mérés szerint, a végéig előrevetítve.
        if sz_nyitott:
            tol, ig, osszeg = _d(sz["tol"]), _d(sz["ig"]), sz.get("fizetendo")
        else:
            i = f.get("idoszak") or {}
            tol, ig, osszeg = _d(i.get("tol")), _d(i.get("ig")), (f.get("varhato") or {}).get("osszeg")
        if tol and ig and not any(a < ig - timedelta(days=1) and b > tol for a, b in szamlazott):
            # A várható kelte a számlázási ütem szerint (mint a „következő számla”), ha az az időszak vége utánra esik.
            k = _d(es.get("kovetkezo_datum")) if es else None
            tesz(k if k and k >= ig - timedelta(days=1) else ig - timedelta(days=1) + keses, tol, ig - timedelta(days=1), osszeg, "meres")
    return sorted(out, key=lambda x: x["kelte"])
