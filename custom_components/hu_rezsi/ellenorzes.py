"""Számla-ellenőrzés („könyvvizsgálói” réteg): a szolgáltató elszámoló számláinak belső ellentmondásai és eltérései
a saját méréstől – forint-hatással, hogy reklamálható-e, vagy pótszámla várható.

Talált hibák (tipus):
- „nem_szamlazott”: a számla saját mérősorai szerint több fogyott, mint amennyit kiszámláztak („Fogyasztás összesen”)
  – az MVM saját dokumentuma szerint ellentmondás; a hiányzó rész pótszámlája várható.
- „regisztercsere”: H-tarifa – a kiszámlázott téli és nyári mennyiség épp a mért fordítottja (a két regiszter
  felcserélve: a drágább nyári árat a téli fogyasztásra számolták, vagy fordítva).
- „elteres”: más ok nélkül a számla díja és a saját számítás közti nagy eltérés – ellenőrizendő (tájékoztató).
- „csatorna_tobblet”: víz – a számla több szennyvizet (csatornadíjat) számláz, mint a mért ivóvíz (pl. kétszer
  szereplő szennyvízdíj-sor). Bármely számlatípusnál: a számla belső ellentmondása, a saját méréstől független.

A hatás (Ft): a helyes díj (saját számítás) − a kiszámlázott díj. Pozitív: a szolgáltató kevesebbet számlázott
(pótszámla várható), negatív: többet (reklamálható).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

try:
    from .szamlak import sztornozott_kulcsok
except ImportError:  # tesztek: a csomag HA nélkül, közvetlenül
    from szamlak import sztornozott_kulcsok

ELLENORZOTT_TIPUSOK = ("elszamolo", "vegszamla")
ELTERES_MIN_FT = 1000
ELTERES_ARANY = Decimal("0.05")


def _dec(x: Any) -> Decimal | None:
    return None if x is None else Decimal(str(x))


def _sz(x: Decimal) -> str:
    """Mennyiség szövegben: egész, ha az; különben tizedesvesszővel."""
    return f"{x:.0f}" if x == x.to_integral_value() else f"{x:.1f}".replace(".", ",")


def _kozel(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(Decimal(3), abs(b) * Decimal("0.02"))


def ellenoriz(sorok: list[dict[str, Any]], szamlak: dict[str, dict[str, Any]], elteres: bool = True, tavho: bool = False) -> list[dict[str, Any]]:
    """sorok: a számla↔számítás összevetés sorai (koordinator.szamla_osszevetes), szamlak: a tárolt számlák.
    elteres=False: az ok nélküli eltérést nem jelezzük (pl. napelemes fióknál a szaldó miatt a saját számítás nem
    összevethető). Kimenet: a talált hibák (számlánként legfeljebb egy – a legerősebb ok)."""
    out: list[dict[str, Any]] = []
    torolt = sztornozott_kulcsok(szamlak)  # a sztornózott számla helyett a helyesbítőt vizsgáljuk
    for sor in sorok:
        x = szamlak.get(sor["sorszam"]) or {}
        if sor["sorszam"] in torolt or x.get("tipus") not in ELLENORZOTT_TIPUSOK or sor.get("szamolt_ft") is None or sor.get("szamla_ft") is None:
            continue
        if (x.get("elszamolt_tavho") or {}).get("korrekcio_ft") is not None or (tavho and x.get("tipus") == "elszamolo"):
            continue  # távhő: a fűtési idény utáni hődíj-korrekció a költségmegosztás szerint – nem a mi mérésünkből
        hatas = int(sor["szamolt_ft"]) - int(sor["szamla_ft"])
        alap = {
            "sorszam": sor["sorszam"], "kelte": sor.get("kelte"), "tol": sor.get("tol"), "ig": sor.get("ig"),
            "szamla_ft": int(sor["szamla_ft"]), "szamolt_ft": int(sor["szamolt_ft"]), "hatas_ft": hatas,
        }
        mert_q, szamlazott_q = _dec(x.get("elszamolt_kwh")), _dec(x.get("szamlazott_kwh"))
        if mert_q is not None and szamlazott_q is not None and mert_q - szamlazott_q >= max(Decimal(5), mert_q * Decimal("0.02")):
            out.append(alap | {
                "tipus": "nem_szamlazott", "sulyos": True,
                "mennyiseg_mert": float(mert_q), "mennyiseg_szamlazott": float(szamlazott_q),
                "leiras": (f"A számla mérősorai szerint {_sz(mert_q)} kWh fogyott, de csak {_sz(szamlazott_q)} kWh-t számláztak ki "
                           f"({_sz(mert_q - szamlazott_q)} kWh nincs kiszámlázva)."),
            })
            continue
        mvm = {k: _dec(v) for k, v in (x.get("szamlazott_idenyek") or {}).items()}
        sajat = {k: _dec(v) for k, v in (sor.get("szamolt_idenyek") or {}).items()}
        mt, mn, st, sn = mvm.get("teli"), mvm.get("nyari"), sajat.get("teli"), sajat.get("nyari")
        if None not in (mt, mn, st, sn) and abs(st - sn) > 5 and _kozel(mt, sn) and _kozel(mn, st) and not (_kozel(mt, st) and _kozel(mn, sn)):
            out.append(alap | {
                "tipus": "regisztercsere", "sulyos": True,
                "mvm_teli": float(mt), "mvm_nyari": float(mn), "mert_teli": float(st), "mert_nyari": float(sn),
                "leiras": (f"A téli (1.81) és a nyári (1.82) regiszter felcserélve: a számla télre {_sz(mt)}, nyárra {_sz(mn)} kWh-t "
                           f"számlázott, a mérés szerint télen {_sz(st)}, nyáron {_sz(sn)} kWh fogyott."),
            })
            continue
        if elteres and sor.get("mert") and abs(hatas) >= max(ELTERES_MIN_FT, int(abs(Decimal(sor["szamla_ft"])) * ELTERES_ARANY)):
            out.append(alap | {
                "tipus": "elteres", "sulyos": False,
                "leiras": f"A számla díja {abs(hatas)} Ft-tal {'kevesebb' if hatas > 0 else 'több'}, mint a saját számítás ugyanarra a mennyiségre.",
            })
    return out


def viz_ellenoriz(
    szamlak: dict[str, dict[str, Any]], csatorna_ar: Callable[[date], Decimal | None], hatar: str = "",
    melegviz: Callable[[date, date], Decimal] | None = None,
) -> list[dict[str, Any]]:
    """Víz: a számlán elszámolt szennyvíz több, mint az ivóvíz (a locsolási almérő csak csökkentheti) – a többlet
    csatornadíja (bruttó, a díjszabás szerinti egységárral, a vízterhelési díjjal együtt) reklamálható.
    csatorna_ar: a bruttó csatornadíj Ft/m³ egy napra (None: nincs díjszabás); hatar: a vizsgált legkorábbi kelte;
    melegviz: a háztartás távhős melegvize az időszakban (m³) – annak a szennyvizét is a vízmű számlázhatja (pl.
    ALFÖLDVÍZ 2026 májusától), így az nem többlet."""
    out: list[dict[str, Any]] = []
    torolt = sztornozott_kulcsok(szamlak)
    for sorszam, x in szamlak.items():
        if sorszam in torolt:
            continue
        ev = x.get("elszamolt_viz") or {}
        iv, cs = _dec(ev.get("ivoviz")), _dec(ev.get("csatorna"))
        if iv is None or cs is None or cs - iv < 1 or (x.get("kelte") or "") < hatar:
            continue
        if x.get("tipus") != "resz":
            continue  # elszámolón a mennyiségek a részszámlák levonása utáni különbözetek – a csatorna lehet több
        idoszak = ev.get("idoszak") or x.get("idoszak") or [x.get("kelte"), x.get("kelte")]
        if melegviz is not None and idoszak[0] and idoszak[1]:
            iv += melegviz(date.fromisoformat(idoszak[0]), date.fromisoformat(idoszak[1]))
            if cs - iv < 1:
                continue
        ar = csatorna_ar(date.fromisoformat(idoszak[1]))
        szamla_ft = x.get("szamlaertek") or x.get("osszeg")
        if ar is None or szamla_ft is None:
            continue
        hatas = -int(((cs - iv) * ar).quantize(Decimal(1)))
        out.append({
            "sorszam": sorszam, "kelte": x.get("kelte"), "tol": idoszak[0], "ig": idoszak[1],
            "szamla_ft": int(Decimal(str(szamla_ft))), "szamolt_ft": int(Decimal(str(szamla_ft))) + hatas, "hatas_ft": hatas,
            "tipus": "csatorna_tobblet", "sulyos": True, "ivoviz": float(iv), "csatorna": float(cs), "csatorna_ar": float(ar),
            "leiras": (f"A számla {_sz(cs)} m³ szennyvizet számláz {_sz(iv)} m³ ivóvízre – az elvezetett szennyvíz nem lehet több "
                       f"a mért ivóvíznél ({_sz(cs - iv)} m³ többlet, pl. kétszer szereplő szennyvízdíj-sor)."),
        })
    return out


def kulcs(t: dict[str, Any]) -> str:
    return f"{t['sorszam']}:{t['tipus']}"
