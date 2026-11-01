"""Éves elszámolási kimutatás (MVM villany, A1 és H): a két éves leolvasás közötti év a mérőállások és a díjszabás
szerint, számlánként szembeállítva a szolgáltató elszámoló számláival – a reklamációhoz.

A „helyes” oldal szabályai (valódi MVM-számlákkal ellenőrizve, Kertes ház A1 2025/26: 4 számla 0 Ft eltéréssel):
- a fogyasztás a számla időszakának két végén lévő mérőállás különbsége (az időszak „előző leolvasás másnapja –
  leolvasás napja”);
- kedvezményes keret: 2523 kWh/év napra arányosan, számlánként (aug. 1-jén tételenként) egész kWh-ra kerekítve, az
  elszámolási éven belül halmozva (sávkorrekció) – H-tarifán csak a nyári (1.82) regiszterre, a nyári napokra;
- elosztói alapdíj: a számla napjai közé eső hónap-1-jék szerint (H: télen a H, nyáron az A1 alapdíja);
- díjak tételenként: nettó forintra, bruttó = nettó × (1 + ÁFA), forintra.

Az MVM oldal a számlák tételeiből (szamlak.mvm_tetelek): kiszámlázott mennyiség, kedvezményes/piaci/téli kWh,
energiadíj és rendszerhasználati díj bruttó (a levont részszámlák előtt); az alapdíj hónaponként, az év összes
számlájából egyszer (részszámlán is lehet egy hónap alapdíja, amelyet az elszámoló nem von le)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

try:
    from .szamlak import sztornozott_kulcsok
except ImportError:  # tesztek: a csomag HA nélkül, közvetlenül
    from szamlak import sztornozott_kulcsok

D0 = Decimal(0)


def _d(x: str | date | None) -> date | None:
    if x is None or isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def kerek(x: Decimal) -> int:
    return int(Decimal(x).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _brutto(netto: Decimal, afa: Decimal) -> int:
    return kerek(Decimal(kerek(netto)) * (1 + afa / 100))


def _honap1(tol: date, ig: date) -> list[date]:
    """A [tol, ig] napjai közé eső hónap-1-jék."""
    out, x = [], tol.replace(day=1)
    if x < tol:
        x = (x + timedelta(days=32)).replace(day=1)
    while x <= ig:
        out.append(x)
        x = (x + timedelta(days=32)).replace(day=1)
    return out


def _teli_nap(n: date, tol: str = "10-15", ig: str = "04-15") -> bool:
    md = n.strftime("%m-%d")
    return md >= tol or md <= ig


def _tetel_reszek(tol: date, ig: date, hatar: str | None) -> list[tuple[date, date]]:
    """A számla tételei (az aug. 1-jei tételhatáron kettéválik): [(tol, ig)] – mindkét nap benne van."""
    if not hatar:
        return [(tol, ig)]
    h = date(tol.year, int(hatar[:2]), int(hatar[3:]))
    if tol < h <= ig:
        return [(tol, h - timedelta(days=1)), (h, ig)]
    return [(tol, ig)]


def ev_jeloltek(napok: list[date]) -> list[tuple[date, date]]:
    """A választható elszámolási évek: az egymást követő éves (elszámoló) leolvasások párjai, a legfrissebb elöl."""
    napok = sorted(set(napok))
    return list(reversed(list(zip(napok, napok[1:]))))


def elszamolok(szamlak: dict[str, dict[str, Any]], ev_tol: date, ev_ig: date) -> list[dict[str, Any]]:
    """Az év elszámoló számlái időrendben: sztornózott számla helyett az azonos időszakú újabb (egyszer)."""
    jo: dict[tuple[str, str], dict[str, Any]] = {}
    torolt = sztornozott_kulcsok(szamlak)  # a stornóval érvénytelenített számla soha nem számít
    for sorszam, x in szamlak.items():
        i = x.get("idoszak")
        if x.get("tipus") != "elszamolo" or not i or not x.get("tetelek") or sorszam in torolt:
            continue
        tol, ig = _d(i[0]), _d(i[1])
        if ig <= ev_tol or tol > ev_ig:
            continue
        kulcs = (i[0], i[1])
        if kulcs not in jo or (x.get("kelte") or "") > (jo[kulcs].get("kelte") or ""):
            jo[kulcs] = {**x, "sorszam": sorszam}
    return sorted(jo.values(), key=lambda x: x["idoszak"][0])


def _alapdij_honapok(szamlak: dict[str, dict[str, Any]]) -> dict[str, Decimal]:
    """Az MVM által kiszámlázott alapdíj hónaponként (bruttó; több hónapos tételnél a tétel egy hónapra eső része),
    az összes számlából egyszer."""
    out: dict[str, Decimal] = {}
    torolt = sztornozott_kulcsok(szamlak)
    for k, x in szamlak.items():
        if x.get("tipus") == "storno" or k in torolt:
            continue
        for ho, br in ((x.get("tetelek") or {}).get("alapdij") or {}).items():
            out[ho] = Decimal(str(br))
    return out


def kimutatas(
    dijszabas: str,
    ev_tol: date,
    ev_ig: date,
    allas: Callable[[str, date], tuple[Decimal, bool] | None],
    szamlak: dict[str, dict[str, Any]],
    arak: Callable[[str, date], dict[str, Any]],
    keret_ev: Decimal = Decimal(2523),
    tetel_hatar: str | None = "08-01",
    ma: date | None = None,
    kezdo: bool = False,
) -> dict[str, Any]:
    """Az év kimutatása. allas(csatorna, nap) → (mérőállás a nap elején, valódi-e) – csatorna: „vetelezes” (A1), H-nál
    „h_teli” és „h_nyari”; arak(díjszabás, nap) → a díjszabás nettó díjai (energia_kedvezmenyes, energia_piaci,
    rendszerhasznalati, alapdij_ho, afa; H: energia_teli, rendszerhasznalati, alapdij_ho). kezdo: az év eleje a mérő
    felszerelése (kezdőállás) – ilyenkor ez a nap is az első időszak része (nem egy előző időszak zárónapja)."""
    h = dijszabas == "villany/h"
    napi = keret_ev / Decimal(365)
    szl = elszamolok(szamlak, ev_tol, ev_ig)
    alap_mvm = _alapdij_honapok(szamlak)
    # Időszakok: a számlák (az év határaira vágva), és a végén az utolsó számla utáni, még nem számlázott rész.
    idoszakok: list[tuple[date, date, dict[str, Any] | None]] = []
    eleje = ev_tol if kezdo else ev_tol + timedelta(days=1)
    for x in szl:
        tol, ig = max(_d(x["idoszak"][0]), eleje), min(_d(x["idoszak"][1]), ev_ig)
        idoszakok.append((tol, ig, x))
        eleje = ig + timedelta(days=1)
    if eleje <= ev_ig:
        idoszakok.append((eleje, ev_ig, None))

    cum = {"keret": 0, "fogy": D0, "kedv": D0}
    sorok, hianyos = [], False

    def fogy(csat: str, tol: date, ig: date) -> tuple[Decimal | None, bool]:
        a, b = allas(csat, ev_tol if kezdo and tol == ev_tol else tol - timedelta(days=1)), allas(csat, ig)
        if a is None or b is None:
            return None, False
        return b[0] - a[0], a[1] and b[1]

    for tol, ig, x in idoszakok:
        a1 = arak("villany/a1", tol)
        afa = Decimal(str(a1.get("afa", 27)))
        s: dict[str, Any] = {"tol": tol.isoformat(), "ig": ig.isoformat(), "sorszam": x["sorszam"] if x else None,
                             "kelte": x.get("kelte") if x else None}
        if h:
            qt, vt = fogy("h_teli", tol, ig)
            qn, vn = fogy("h_nyari", tol, ig)
            if qt is None or qn is None:
                hianyos = True
                continue
            q, valodi = qt + qn, vt and vn
            nyari_napok = [(a, b) for a, b in _tetel_reszek(tol, ig, tetel_hatar)]
            kr = 0
            for a, b in nyari_napok:
                n = sum(1 for i in range((b - a).days + 1) if not _teli_nap(a + timedelta(days=i)))
                kr += kerek(napi * n) if n else 0
            q_keretes = qn
        else:
            q, valodi = fogy("vetelezes", tol, ig)
            if q is None:
                hianyos = True
                continue
            qt = D0
            kr = sum(kerek(napi * ((b - a).days + 1)) for a, b in _tetel_reszek(tol, ig, tetel_hatar))
            q_keretes = q
        # Halmozott keret (sávkorrekció) az elszámolási éven belül.
        cum["keret"] += kr
        cum["fogy"] += q_keretes
        kedv = min(cum["fogy"], Decimal(cum["keret"])) - cum["kedv"]
        cum["kedv"] += kedv
        piaci = q_keretes - kedv
        honapok = _honap1(tol, ig)
        net: dict[str, Decimal] = {
            "kedvezmenyes": kedv * Decimal(str(a1["energia_kedvezmenyes"])),
            "piaci": piaci * Decimal(str(a1["energia_piaci"])),
            "rhd": q_keretes * Decimal(str(a1["rendszerhasznalati"])),
        }
        # Alapdíj: a hónapok száma a hónap-1-jék szerint. Kerekítés úgy, ahogy a szolgáltató tételesíti: ha a hónapot
        # kiszámlázta, a számla egy hónapra eső része (havi tétel: 154, „4 hó” tétel: 612/4); különben egy tétel díjanként
        # (H: téli és nyári külön) – nettó a hónapok × havi díj, forintra, utána ÁFA.
        csoport: dict[Decimal, int] = {}
        alap_d = D0
        for ho in honapok:
            kulcs = f"{ho.year}-{ho.month:02d}"
            ar = Decimal(str((arak("villany/h", ho) if h and _teli_nap(ho) else arak("villany/a1", ho))["alapdij_ho"]))
            mvm_ho = alap_mvm.get(kulcs) if x else None
            if mvm_ho is not None and abs(mvm_ho - ar * (1 + afa / 100)) < 2:
                alap_d += mvm_ho
            else:
                csoport[ar] = csoport.get(ar, 0) + 1
        alap = kerek(alap_d) + sum(_brutto(ar * n, afa) for ar, n in csoport.items())
        if h and qt:
            ah = arak("villany/h", tol)
            net["teli"] = qt * Decimal(str(ah["energia_teli"]))
            net["teli_rhd"] = qt * Decimal(str(ah["rendszerhasznalati"]))
        dij = {k: _brutto(v, afa) for k, v in net.items()}
        dij["alapdij"] = alap
        s.update({
            "mert": float(q), "valodi": valodi, "keret": kr, "kedvezmenyes": float(kedv), "piaci": float(piaci),
            "teli": float(qt), "nyari": float(q_keretes) if h else None, "alapdij_ho": len(honapok),
            "dij": dij, "helyes": sum(dij.values()),
        })
        if x:
            t = x["tetelek"]
            sajat_alap = sum(Decimal(str(v)) for v in (t.get("alapdij") or {}).values())
            span = [f"{d.year}-{d.month:02d}" for d in honapok]
            mvm_alap = sum((alap_mvm.get(ho, D0) for ho in span), D0)
            s["mvm"] = {
                "kiszamlazott": float(Decimal(str(t["kiszamlazott_kwh"]))) if t.get("kiszamlazott_kwh") else None,
                "kedvezmenyes": float(Decimal(str(t.get("kedvezmenyes") or 0))), "piaci": float(Decimal(str(t.get("piaci") or 0))),
                "teli": float(Decimal(str(t.get("teli") or 0))), "alapdij_ho": sum(1 for ho in span if ho in alap_mvm),
                "dij": kerek(Decimal(str(t["energia_brutto"])) + Decimal(str(t["rhd_brutto"])) - sajat_alap + mvm_alap),
            }
            s["elteres"] = s["helyes"] - s["mvm"]["dij"]
        sorok.append(s)

    szamlazott = [s for s in sorok if s.get("mvm")]
    ossz = {
        "mert": sum(s["mert"] for s in szamlazott), "kiszamlazott": sum(s["mvm"]["kiszamlazott"] or 0 for s in szamlazott),
        "kedvezmenyes": sum(s["kedvezmenyes"] for s in szamlazott), "mvm_kedvezmenyes": sum(s["mvm"]["kedvezmenyes"] for s in szamlazott),
        "piaci": sum(s["piaci"] for s in szamlazott), "mvm_piaci": sum(s["mvm"]["piaci"] for s in szamlazott),
        "teli": sum(s["teli"] for s in szamlazott), "mvm_teli": sum(s["mvm"]["teli"] for s in szamlazott),
        "alapdij_ho": sum(s["alapdij_ho"] for s in szamlazott), "mvm_alapdij_ho": sum(s["mvm"]["alapdij_ho"] for s in szamlazott),
        "helyes": sum(s["helyes"] for s in szamlazott), "mvm": sum(s["mvm"]["dij"] for s in szamlazott),
        "dij": {k: sum(s["dij"].get(k, 0) for s in szamlazott) for k in ("kedvezmenyes", "piaci", "teli", "teli_rhd", "rhd", "alapdij")},
        "ig": szamlazott[-1]["ig"] if szamlazott else None,
    }
    ossz["elteres"] = ossz["helyes"] - ossz["mvm"]
    fuggo = next((s for s in sorok if not s.get("mvm")), None)
    return {
        "dijszabas": dijszabas, "ev_tol": ev_tol.isoformat(), "ev_ig": ev_ig.isoformat(), "hianyos": hianyos,
        "sorok": sorok, "osszesen": ossz, "fuggo": fuggo,
        "ev_helyes": ossz["helyes"] + (fuggo["helyes"] if fuggo else 0),
        "megallapitasok": megallapitasok(h, sorok, szamlak, szl),
    }


def megallapitasok(h: bool, sorok: list[dict[str, Any]], szamlak: dict[str, dict[str, Any]], szl: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A talált hibák számlánként (forint-hatással), és a le nem vont részszámlák."""
    out: list[dict[str, Any]] = []
    for i, s in enumerate(sorok):
        m = s.get("mvm")
        if not m:
            continue
        e = s["elteres"]
        if abs(e) < max(100, s["helyes"] * 0.005):
            continue
        ok = []
        if m["kiszamlazott"] is not None and s["mert"] - m["kiszamlazott"] >= 1:
            ok.append(("nem_kiszamlazott", f"a mérőállások szerint {s['mert']:.0f} kWh fogyott, a számla {m['kiszamlazott']:.0f} kWh-t számláz ki – {s['mert'] - m['kiszamlazott']:.0f} kWh kimaradt"))
        if h and abs(m["teli"] - s["nyari"]) < 1 and abs((m["kiszamlazott"] or 0) - m["teli"] - s["teli"]) < 1 and s["teli"] != s["nyari"]:
            ok.append(("regisztercsere", f"a két regiszter felcserélve: a számla a téli H-árra {m['teli']:.0f}, a nyári árra {(m['kiszamlazott'] or 0) - m['teli']:.0f} kWh-t számláz, a diktálás szerint téli {s['teli']:.0f}, nyári {s['nyari']:.0f}"))
        if not ok and i > 0 and any(o and o.get("mvm") and o["mvm"]["kiszamlazott"] is not None and o["mert"] - o["mvm"]["kiszamlazott"] >= 1 for o in sorok[:i]):
            ok.append(("savkorrekcio", "egy korábbi számla kiszámlázatlan fogyasztása miatt a sávkorrekció (kedvezményes jóváírás) téves"))
        if not ok and m["alapdij_ho"] != s["alapdij_ho"]:
            ok.append(("alapdij", f"alapdíj {m['alapdij_ho']} hónapra a helyes {s['alapdij_ho']} helyett"))
        if not ok:
            ok.append(("elteres", "a díj eltér a mérés és a díjszabás szerinti díjtól"))
        out.append({"sorszam": s["sorszam"], "tol": s["tol"], "ig": s["ig"], "hatas_ft": e, "tipus": ok[0][0], "szoveg": "; ".join(x[1] for x in ok)})
    # Részszámla, amelyet egyik elszámoló sem vont le, pedig az időszaka már elszámolt.
    levont = {str(sor).lstrip("0") for x in szl for sor, _ in (x.get("levont_szamlak") or [])}
    utolso = max((_d(x["idoszak"][1]) for x in szl), default=None)
    for sorszam, x in szamlak.items():
        i = x.get("idoszak")
        if (x.get("tipus") == "resz" and i and utolso and _d(i[0]) <= utolso and not sorszam.startswith("kezi")
                and sorszam.lstrip("0") not in levont and _d(i[1]) >= _d(sorok[0]["tol"]) if sorok else False):
            out.append({"sorszam": sorszam, "tol": i[0], "ig": i[1], "hatas_ft": None, "tipus": "nem_levont",
                        "szoveg": f"a részszámlát ({int(Decimal(str(x.get('szamlaertek') or x.get('osszeg') or 0)))} Ft) egyik elszámoló sem vonta le – a következő elszámolónak le kell vonnia"})
    return out
