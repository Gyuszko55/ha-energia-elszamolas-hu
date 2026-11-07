"""Éves elszámolási kimutatás (MVM villany, A1 és H): a két éves leolvasás közötti év a mérőállások és a díjszabás
szerint, számlánként szembeállítva a szolgáltató elszámoló számláival – a reklamációhoz.

A „helyes” oldal szabályai (valódi MVM-számlákkal ellenőrizve, Kertes ház A1 2025/26: 4 számla 0 Ft eltéréssel):
- a fogyasztás a számla időszakának két végén lévő mérőállás különbsége (az időszak „előző leolvasás másnapja –
  leolvasás napja”);
- kedvezményes keret: 2523 kWh/év napra arányosan, számlánként (aug. 1-jén tételenként) egész kWh-ra kerekítve, a
  kedvezményes éven belül (aug. 1. – júl. 31., 4/2011. NFM rendelet 6. § (3)) halmozva (sávkorrekció) – a július 31-én
  fel nem használt keret nem megy át a következő évre; H-tarifán csak a nyári (1.82) regiszterre, a nyári napokra,
  éven átnyúló halmozással (6. § (1): a H kerete a fűtési idényen kívüli időszakra szól);
- elosztói alapdíj: a számla napjai közé eső hónap-1-jék szerint (H: télen a H, nyáron az A1 alapdíja);
- díjak tételenként: nettó forintra, bruttó = nettó × (1 + ÁFA), forintra.

Az MVM oldal a számlák tételeiből (szamlak.mvm_tetelek): kiszámlázott mennyiség, kedvezményes/piaci/téli kWh,
energiadíj és rendszerhasználati díj bruttó (a levont részszámlák előtt); az alapdíj hónaponként, az év összes
számlájából egyszer (részszámlán is lehet egy hónap alapdíja, amelyet az elszámoló nem von le)."""

from __future__ import annotations

from calendar import isleap
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
    out, a = [], tol
    for ev in range(tol.year, ig.year + 1):  # a számla az év második felében is indulhat, a határ ilyenkor a következő évben van
        h = date(ev, int(hatar[:2]), int(hatar[3:]))
        if a < h <= ig:
            out.append((a, h - timedelta(days=1)))
            a = h
    return [*out, (a, ig)]


def _ev_napok(n: date, hatar: str | None) -> int:
    """A keret napi arányához az év napjai: 365, szökőévet tartalmazó kedvezményes évben (hatar nélkül naptári évben) 366."""
    if not hatar:
        return 366 if isleap(n.year) else 365
    e = _kedv_ev(n, hatar)
    return (date(e + 1, int(hatar[:2]), int(hatar[3:])) - date(e, int(hatar[:2]), int(hatar[3:]))).days


def _kedv_ev(n: date, hatar: str | None) -> int | None:
    """A kedvezményes év kezdő éve (aug. 1. – júl. 31. esetén 2026-07-31 → 2025); hatar nélkül nincs évváltás."""
    if not hatar:
        return None
    return n.year if n >= date(n.year, int(hatar[:2]), int(hatar[3:])) else n.year - 1


def tarolt_pontok(tarolt: dict[str, Any], csat: str, folytonos: bool = False) -> list[tuple[date, Decimal]]:
    """A csatorna rögzített mérőállásai időrendben (az automatikus nélkül), a mérő kezdőállásával együtt.
    folytonos: mérőcsere után az új mérő állásai a régi záróállásától folytatva (mint a motor számlálója), így a
    különbségek a fogyasztást adják; egy mérőnél nincs eltérés. Különben a nyers állások."""
    nevek = ("vetelezes", "fo") if csat == "vetelezes" else (csat,)
    kezdo_kulcs, zaro_kulcs = ("kezdo_allas", "zaro_allas") if csat == "vetelezes" else (f"kezdo_{csat}", f"zaro_{csat}")
    out: list[tuple[date, Decimal]] = []
    eltolas, elozo_vege = D0, None
    for m in sorted(tarolt.get("merok", []), key=lambda m: str(m.get("beepitve") or "")):
        sajat = [(_d(lo["datum"]), Decimal(str(lo["allas"]))) for lo in m.get("leolvasasok", [])
                 if (lo.get("csatorna") or "vetelezes") in nevek and lo.get("tipus") != "automatikus"]
        kezdo = m.get(kezdo_kulcs)
        kezdo = None if kezdo in (None, "") else Decimal(str(kezdo))
        if m.get("beepitve") and kezdo is not None:
            sajat.append((_d(m["beepitve"]), kezdo))
        sajat.sort()
        if not sajat:
            continue
        if folytonos and elozo_vege is not None:
            eltolas = elozo_vege - (kezdo if kezdo is not None else sajat[0][1])
        out += [(n, a + eltolas) for n, a in sajat]
        zaro = m.get(zaro_kulcs)
        vege = Decimal(str(zaro)) if zaro not in (None, "") else sajat[-1][1]
        elozo_vege = vege + eltolas
        if folytonos and m.get("kiszerelve") and zaro not in (None, ""):
            out.append((_d(m["kiszerelve"]), elozo_vege))
    return sorted(out)


def evhatar_allasok(dijszabas: str, szamlak: dict[str, dict[str, Any]], pontok: Callable[[str], list[tuple[date, Decimal]]]) -> list[dict[str, Any]]:
    """Az elszámolási határok mérőállása a számlák bontásából: az év (A1: júl. 31.) és a H-idény (ápr. 15., júl. 31.) határa.
    Ha a határra van rögzített állás (pl. a számla mérősora bontott), az a „mero”; különben a számla induló állása + a
    határig tartó tételek („tetelek”). Csak ha a számla tételei kiadják a két mérőállás különbségét: így egy hibás,
    felcserélt regiszterű számlából nem lesz mérőállás. Egy nap egy csatornájára a későbbi számla az érvényes."""
    h = dijszabas == "villany/h"
    regiszterek = {"h_teli": (("teli_tetelek",), ("04-15",)), "h_nyari": (("kedv_tetelek", "piaci_tetelek"), ("04-15", "07-31"))} if h \
        else {"vetelezes": (("kedv_tetelek", "piaci_tetelek"), ("07-31",))}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for x in elszamolok(szamlak, date(2000, 1, 1), date(2100, 1, 1)):
        i0, i1 = _d(x["idoszak"][0]), _d(x["idoszak"][1])
        t = x.get("tetelek") or {}
        jo = True
        talalt = []
        for csat, (fajtak, naptar) in regiszterek.items():
            p = dict(pontok(csat))
            a0 = p.get(i0 - timedelta(days=1), p.get(i0))
            a1 = p.get(i1)
            tetelek = [(_d(b), Decimal(str(q))) for f in fajtak for _a, b, q in t.get(f) or []]
            if a0 is None or a1 is None or abs(a1 - a0 - sum((q for _b, q in tetelek), D0)) >= 1:
                jo = False  # a tételek nem adják ki a mérőállásokat: a bontás nem használható
            for md in naptar:
                for ev in range(i0.year, i1.year + 1):
                    nap = _md_nap(ev, md)
                    if not i0 <= nap <= i1:
                        continue
                    if nap in p:
                        out[(csat, nap.isoformat())] = {"datum": nap.isoformat(), "csatorna": csat, "allas": float(p[nap]), "sorszam": x["sorszam"], "mod": "mero"}
                    elif a0 is not None and a1 is not None:
                        v = a0 + sum((q for b, q in tetelek if b <= nap), D0)
                        if min(a0, a1) <= v <= max(a0, a1):
                            talalt.append({"datum": nap.isoformat(), "csatorna": csat, "allas": float(v), "sorszam": x["sorszam"], "mod": "tetelek"})
        if jo:
            out.update({(u["csatorna"], u["datum"]): u for u in talalt})
    return sorted(out.values(), key=lambda u: (u["datum"], u["csatorna"]))


def kesobbi_szamla_kell(eredmeny: dict[str, Any], ig: date) -> bool:
    """A kifogáshoz kell-e az időszak utáni számla: csak ha rajta pótlás vagy annak következménye (téves sávkorrekció) van."""
    return any(m["tipus"] in ("potolt_fogyasztas", "nem_kiszamlazott", "savkorrekcio") and _d(m["tol"]) > ig for m in eredmeny["megallapitasok"])


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

    def napi(n: date) -> Decimal:
        return keret_ev / Decimal(_ev_napok(n, tetel_hatar))

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

    cum: dict[str, Any] = {"keret": 0, "fogy": D0, "kedv": D0, "ev": None}
    evek: dict[int, dict[str, Any]] = {}
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
                kr += kerek(napi(a) * n) if n else 0
            q_keretes = qn
        else:
            q, valodi = fogy("vetelezes", tol, ig)
            if q is None:
                hianyos = True
                continue
            qt = D0
            kr = sum(kerek(napi(a) * ((b - a).days + 1)) for a, b in _tetel_reszek(tol, ig, tetel_hatar))
            q_keretes = q
        # Halmozott keret (sávkorrekció) a kedvezményes éven belül; aug. 1-jén új év kezdődik.
        if h:
            reszek = [(None, kr, q_keretes, tol, ig)]
        else:
            tr = _tetel_reszek(tol, ig, tetel_hatar)
            qr = [fogy("vetelezes", a, b)[0] for a, b in tr]
            if any(v is None for v in qr):  # nincs állás a határnapra: a napok arányában
                nap_ossz = Decimal((ig - tol).days + 1)
                qr = [q * Decimal((b - a).days + 1) / nap_ossz for a, b in tr]
            reszek = [(_kedv_ev(a, tetel_hatar), kerek(napi(a) * ((b - a).days + 1)), qv, a, b) for (a, b), qv in zip(tr, qr)]
        kedv = D0
        s["reszek"] = [{"tol": a.isoformat(), "ig": b.isoformat(), "keret": kr_r, "mert": float(q_r)} for _, kr_r, q_r, a, b in reszek]
        for ev, kr_r, q_r, a, b in reszek:
            if ev != cum["ev"]:
                cum.update(keret=0, fogy=D0, kedv=D0, ev=ev)
            cum["keret"] += kr_r
            cum["fogy"] += q_r
            d_kedv = min(cum["fogy"], Decimal(cum["keret"])) - cum["kedv"]
            cum["kedv"] += d_kedv
            kedv += d_kedv
            if x and ev is not None:
                e_ = evek.setdefault(ev, {"tol": a, "ig": b, "keret": 0, "fogy": D0, "kedv": D0})
                e_["ig"] = b
                e_["keret"] += kr_r
                e_["fogy"] += q_r
                e_["kedv"] += d_kedv
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
            # A számla korábban indul, mint az első mérőállás: a mért rész nem a számla teljes időszaka.
            s["szamla_tol"] = x["idoszak"][0]
            s["csonka"] = (tol - _d(x["idoszak"][0])).days > 1
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
    kedv_evek = _kedv_evek(evek, szl, tetel_hatar)
    if not h:
        for e_ in kedv_evek:
            e_["teljes"] = _teljes_kedv_ev(int(e_["ev"][:4]), szamlak, allas, keret_ev, tetel_hatar, ev_ig)
    return {
        "dijszabas": dijszabas, "ev_tol": ev_tol.isoformat(), "ev_ig": ev_ig.isoformat(), "hianyos": hianyos,
        "sorok": sorok, "osszesen": ossz, "fuggo": fuggo,
        "ev_helyes": ossz["helyes"] + (fuggo["helyes"] if fuggo else 0),
        "kedv_evek": kedv_evek,
        "megallapitasok": megallapitasok(h, sorok, szamlak, szl) + _sav_hianyok(kedv_evek, sorok, arak),
    }


def _vannak_datumozott_tetelek(x: dict[str, Any]) -> bool:
    """Használhatók-e a számla dátumozott tételei. A régi formájú számlán nincs kiszámlázott mennyiség, és a tételek
    dátuma nem a fogyasztás időszaka: ilyenkor abból, hogy egy évre nem esik tétel, nem következik, hogy a számla nem
    adott kedvezményes mennyiséget."""
    t = x.get("tetelek") or {}
    return bool(t.get("kiszamlazott_kwh") and (t.get("kedv_tetelek") or t.get("piaci_tetelek") or t.get("teli_tetelek")))


def _kedv_evek(evek: dict[int, dict[str, Any]], szl: list[dict[str, Any]], hatar: str | None) -> list[dict[str, Any]]:
    """A kedvezményes évek szerinti bontás a számlázott időszakra: mennyi keret járt, és a számlák kedvezményes tételei
    (a sávkorrekcióval együtt, a tétel saját időszaka szerint) mennyit adtak. mvm_kedvezmenyes: None, ha valamelyik
    számlán nincs tételes adat (régebben beolvasott számla)."""
    mvm: dict[int, Decimal] = {}
    teljes = True
    for x in szl:
        tetelek = (x.get("tetelek") or {}).get("kedv_tetelek")
        if not _vannak_datumozott_tetelek(x):
            teljes = False
            continue
        for _tol, ig, kwh in tetelek:
            ev = _kedv_ev(_d(ig), hatar)
            mvm[ev] = mvm.get(ev, D0) + Decimal(str(kwh))
    out = []
    for ev, e in sorted(evek.items()):
        m = mvm.get(ev, D0) if teljes else None
        out.append({
            "ev": f"{ev}/{ev + 1}", "tol": e["tol"].isoformat(), "ig": e["ig"].isoformat(), "nap": (e["ig"] - e["tol"]).days + 1,
            "keret": e["keret"], "fogyasztas": float(e["fogy"]), "kedvezmenyes": float(e["kedv"]),
            "mvm_kedvezmenyes": float(m) if m is not None else None, "hiany": float(e["kedv"] - m) if m is not None else None,
        })
    return out


def _teljes_kedv_ev(ev: int, szamlak: dict[str, dict[str, Any]], allas: Callable[[str, date], tuple[Decimal, bool] | None],
                    keret_ev: Decimal, hatar: str | None, ev_ig: date) -> dict[str, Any] | None:
    """A teljes kedvezményes év (aug. 1. – júl. 31.) az elszámolási évtől függetlenül, az összes elszámoló számlából:
    a járó keret (1/365, szökőévben 1/366 × napok), a fogyasztás a mérőállásokból és a számlák kedvezményes tételei.
    Az év vége a kimutatás záró napjánál nem későbbi. None: ha valamelyik számláról nincs tétel, vagy az időszakok nem
    fedik le az évet, vagy nincs mérőállás."""
    if not hatar:
        return None
    ho, nap_ = int(hatar[:2]), int(hatar[3:])
    tol, kov = date(ev, ho, nap_), date(ev + 1, ho, nap_)
    ig = min(kov - timedelta(days=1), ev_ig)
    szl = elszamolok(szamlak, tol - timedelta(days=1), ig)
    if not szl or _d(szl[0]["idoszak"][0]) > tol or _d(szl[-1]["idoszak"][1]) < ig:
        return None
    for a, b in zip(szl, szl[1:]):
        if _d(b["idoszak"][0]) != _d(a["idoszak"][1]) + timedelta(days=1):
            return None
    kedv = D0
    for x in szl:
        tetelek = (x.get("tetelek") or {}).get("kedv_tetelek")
        if tetelek is None or not _vannak_datumozott_tetelek(x):
            return None
        kedv += sum((Decimal(str(kwh)) for _t, i_, kwh in tetelek if tol <= _d(i_) <= ig), D0)
    a, b = allas("vetelezes", tol - timedelta(days=1)), allas("vetelezes", ig)
    if a is None or b is None:
        return None
    napok = (ig - tol).days + 1
    keret = kerek(keret_ev * napok / Decimal((kov - tol).days))
    fogy = b[0] - a[0]
    jar = min(Decimal(keret), fogy)
    return {"tol": tol.isoformat(), "ig": ig.isoformat(), "nap": napok, "keret": keret, "fogyasztas": float(fogy), "kedvezmenyes": float(jar),
            "mvm_kedvezmenyes": float(kedv), "hiany": float(jar - kedv), "valodi": a[1] and b[1]}


def _sav_hianyok(kedv_evek: list[dict[str, Any]], sorok: list[dict[str, Any]], arak: Callable[[str, date], dict[str, Any]]) -> list[dict[str, Any]]:
    """Kedvezményes év, amelyben a számlák kevesebb kedvezményes mennyiséget adtak a járónál. A forint-hatás a szövegben
    van, a hatas_ft üres: ugyanez az eltérés a számlánkénti sorokban már benne van (különben kétszer számítana)."""
    out = []
    for e in kedv_evek:
        if e["hiany"] is None or e["hiany"] < 2:  # 1 kWh: számlánkénti kerekítés
            continue
        a1 = arak("villany/a1", _d(e["ig"]))
        ar = Decimal(str(a1["energia_piaci"])) - Decimal(str(a1["energia_kedvezmenyes"]))
        ft_ = kerek(Decimal(str(e["hiany"])) * ar * (1 + Decimal(str(a1.get("afa", 27))) / 100))
        potlo = next((s for s in sorok if s.get("mvm") and s["mvm"]["kiszamlazott"] is not None and s["mvm"]["kiszamlazott"] - s["mert"] >= 1), None)
        utolso = next((s for s in reversed(sorok) if s.get("mvm") and s["tol"] <= e["ig"]), None)
        out.append({"sorszam": (potlo or utolso or {}).get("sorszam"), "tol": e["tol"], "ig": e["ig"], "hatas_ft": None, "becsult_ft": ft_, "tipus": "sav_hiany",
                    "szoveg": f"a {e['ev']}. kedvezményes év elszámolt részében {e['keret']:.0f} kWh keret járt, a számlák {e['mvm_kedvezmenyes']:.0f} kWh-t adtak kedvezményes áron – "
                              f"{e['hiany']:.0f} kWh piaci áron szerepel, kb. {f"{ft_:,}".replace(",", " ")} Ft többlet"
                              + (f" (a teljes kedvezményes évre, {t_['nap']} napra {t_['keret']:.0f} kWh keret járt, a számlákon {t_['mvm_kedvezmenyes']:.0f} kWh szerepel: {t_['hiany']:.0f} kWh hiányzik)"
                                 if (t_ := e.get("teljes")) else "")})
    return out


# H-tarifa nyári idénye a számlák szerint (a téli ár ápr. 15-ével bezárólag jár): erre az időszakra jár a keret.
NYARI_TOL, NYARI_IG, TELI_TOL = "04-16", "10-14", "10-15"


def _md_nap(ev: int, md: str) -> date:
    return date(ev, int(md[:2]), int(md[3:]))


def jogi_lista(dijszabas: str, ma: date, elso: date, hatar: str = "08-01") -> list[dict[str, Any]]:
    """A jogszabály szerinti időszakok az első adattól a folyamatban lévőig, a legfrissebb elöl. A1: kedvezményes év
    (aug. 1. – júl. 31., 4/2011. NFM rendelet 6. § (3)). H: a nyári idény (ápr. 16. – okt. 14., a keret a fűtési idényen
    kívüli időszakra szól, 6. § (1)) és a téli idény (keret nélkül). Az éves leolvasásnak itt nincs szerepe."""
    out: list[dict[str, Any]] = []
    if dijszabas == "villany/h":
        for ev in range(elso.year - 1, ma.year + 1):
            nyar = (_md_nap(ev, NYARI_TOL), _md_nap(ev, NYARI_IG))
            tel = (_md_nap(ev, TELI_TOL), _md_nap(ev + 1, NYARI_TOL) - timedelta(days=1))
            out.append({"fajta": "nyari", "nev": str(ev), "tol": nyar[0], "ig": nyar[1]})
            out.append({"fajta": "teli", "nev": f"{ev}/{ev + 1}", "tol": tel[0], "ig": tel[1]})
    else:
        for ev in range(elso.year - 1, ma.year + 1):
            out.append({"fajta": "ev", "nev": f"{ev}/{ev + 1}", "tol": _md_nap(ev, hatar), "ig": _md_nap(ev + 1, hatar) - timedelta(days=1)})
    jo = [x | {"allapot": "lezart" if x["ig"] < ma else "folyamatban"} for x in out if x["tol"] <= ma and x["ig"] >= elso]
    return sorted(jo, key=lambda x: x["tol"], reverse=True)


def jogi_idoszakok(
    dijszabas: str, ma: date, pontok: Callable[[str], list[tuple[date, Decimal]]], allas: Callable[[str, date], tuple[Decimal, bool] | None],
    szamlak: dict[str, dict[str, Any]], arak: Callable[[str, date], dict[str, Any]], keret_ev: Decimal = Decimal(2523), hatar: str = "08-01",
    valasztott: date | None = None,
) -> list[dict[str, Any]]:
    """Az utolsó lezárt és a folyamatban lévő időszak (H: az utolsó lezárt nyári idény és ami most folyamatban van),
    és ha más, a kiválasztott is. A H kerete így a 2523 kWh időarányos része (182/365)."""
    h = dijszabas == "villany/h"
    csat = "h_nyari" if h else "vetelezes"
    kezd = [p[0][0] for c in ((csat, "h_teli") if h else (csat,)) if (p := pontok(c))]
    if not kezd:
        return []
    lista = jogi_lista(dijszabas, ma, min(kezd), hatar)
    lezart = next((x for x in lista if x["allapot"] == "lezart" and (not h or x["fajta"] == "nyari")), None)
    kell = [x for x in lista if x["allapot"] == "folyamatban"] + ([lezart] if lezart else [])
    kell += [x for x in lista if valasztott and x["tol"] == valasztott and x not in kell]
    out = []
    for x in sorted(kell, key=lambda y: y["tol"]):
        s = _jogi_sor(x["fajta"], x["nev"], x["tol"], x["ig"], x["allapot"], ma, pontok, allas, szamlak, arak, keret_ev)
        if s:
            out.append(s)
    return out


def _jogi_sor(fajta: str, nev: str, tol: date, ig: date, allapot: str, ma: date, pontok: Callable[[str], list[tuple[date, Decimal]]],
              allas: Callable[[str, date], tuple[Decimal, bool] | None], szamlak: dict[str, dict[str, Any]],
              arak: Callable[[str, date], dict[str, Any]], keret_ev: Decimal) -> dict[str, Any] | None:
    csat = {"nyari": "h_nyari", "teli": "h_teli"}.get(fajta, "vetelezes")
    pts = pontok(csat)
    if not pts or pts[-1][0] < tol - timedelta(days=1) and pts[-1][0] < tol:
        return None
    # Idényes regiszter: az idényen kívül nem nő, ezért az idény széléhez a legközelebbi valódi állás tartozik (az
    # arányos becslés téves lenne); éven belül arányosan.
    idenyes = fajta != "ev"

    def ertek(n: date) -> Decimal | None:
        if idenyes and n < tol:
            r = [a for x, a in pts if x <= n]
            return r[-1] if r else None
        if idenyes and n >= ig:
            r = [a for x, a in pts if x >= ig]
            if r:
                return r[0]
        a = allas(csat, n)
        return a[0] if a else None

    kezdet = tol
    if pts[0][0] >= tol:  # a mérés az időszak közben indult: a keret az első adattól jár
        kezdet = pts[0][0] if idenyes or pts[0][0] > tol else tol
    utolso = pts[-1][0]
    eddig = ig if idenyes and utolso >= ig else min(ig, utolso, ma)
    ev_napok = 366 if (fajta == "ev" and (_md_nap(ig.year, "03-01") - timedelta(days=1)).day == 29) or (idenyes and (date(ig.year, 3, 1) - timedelta(days=1)).day == 29) else 365
    napi = keret_ev / Decimal(ev_napok)
    keretes = fajta != "teli"

    def keret_ig(n: date) -> int:
        return kerek(napi * ((n - kezdet).days + 1)) if keretes and n >= kezdet else 0

    a0 = ertek(kezdet - timedelta(days=1)) if kezdet > pts[0][0] else pts[0][1]
    b0 = ertek(eddig)
    mert = float(b0 - a0) if a0 is not None and b0 is not None else None
    # A számlák tételei, amelyek ebbe az időszakba esnek (a tétel saját dátuma szerint, a sávkorrekció is).
    szl = elszamolok(szamlak, tol - timedelta(days=1), min(ig, ma))
    if szl:
        szl = [x for x in szl if _d(x["idoszak"][1]) >= tol]
    reszek, teljes_tetel, lyuk, kov = [], True, False, None
    fo = "teli_tetelek" if fajta == "teli" else "kedv_tetelek"
    osszeg = {"fo": D0, "piaci": D0}
    for x in szl:
        i0, i1 = _d(x["idoszak"][0]), _d(x["idoszak"][1])
        p0, p1 = max(i0, tol), min(i1, ig)
        if kov and p0 != kov:
            lyuk = True
        kov = p1 + timedelta(days=1)
        t = x.get("tetelek") or {}
        if t.get(fo) is None or not _vannak_datumozott_tetelek(x):
            teljes_tetel = False
        a_, b_ = ertek(p0 - timedelta(days=1)), ertek(p1)
        kv = sum((Decimal(str(q)) for _a, b, q in t.get(fo) or [] if tol <= _d(b) <= ig), D0)
        pv = sum((Decimal(str(q)) for _a, b, q in t.get("piaci_tetelek") or [] if tol <= _d(b) <= ig), D0)
        osszeg["fo"] += kv
        osszeg["piaci"] += pv
        reszek.append({"sorszam": x["sorszam"], "tol": p0.isoformat(), "ig": p1.isoformat(), "mert": float(b_ - a_) if a_ is not None and b_ is not None else None,
                       "keret": kerek(napi * ((p1 - p0).days + 1)) if keretes else None, "szamla_fo": float(kv), "szamla_piaci": float(pv)})
    szamlazva = min(_d(szl[-1]["idoszak"][1]), ig) if szl else None
    m_sz = None
    if szamlazva:
        v = ertek(szamlazva)
        m_sz = float(v - a0) if v is not None and a0 is not None else None
    k_sz = keret_ig(szamlazva) if szamlazva else 0
    jar = min(Decimal(str(m_sz)), Decimal(k_sz)) if keretes and m_sz is not None else None
    hiany = float(jar - osszeg["fo"]) if jar is not None and teljes_tetel and szl else None
    ar = arak("villany/a1", min(ig, ma))
    hiany_ft = kerek(Decimal(str(hiany)) * (Decimal(str(ar["energia_piaci"])) - Decimal(str(ar["energia_kedvezmenyes"]))) * (1 + Decimal(str(ar.get("afa", 27))) / 100)) if hiany and hiany >= 2 else 0
    return {
        "fajta": fajta, "nev": nev, "allapot": allapot, "tol": tol.isoformat(), "ig": ig.isoformat(), "kezdet": kezdet.isoformat(), "eddig": eddig.isoformat(),
        "nap": (ig - tol).days + 1, "nap_eddig": (eddig - kezdet).days + 1, "keret_teljes": kerek(napi * ((ig - tol).days + 1)) if keretes else None, "keret_eddig": keret_ig(eddig) if keretes else None,
        "mert": mert, "kedvezmenyes": float(min(Decimal(str(mert)), Decimal(keret_ig(eddig)))) if keretes and mert is not None else None,
        "piaci": float(max(Decimal(str(mert)) - Decimal(keret_ig(eddig)), D0)) if keretes and mert is not None else None,
        "szamlazva_ig": szamlazva.isoformat() if szamlazva else None, "keret_szamlazva": k_sz if keretes else None, "mert_szamlazva": m_sz,
        "szamla_kedvezmenyes": float(osszeg["fo"]) if keretes and teljes_tetel and szl else None, "szamla_piaci": float(osszeg["piaci"]) if teljes_tetel and szl else None,
        "szamla_teli": float(osszeg["fo"]) if not keretes and teljes_tetel and szl else None,
        "hiany": hiany, "hiany_ft": hiany_ft, "lyuk": lyuk, "reszek": reszek,
    }


def megallapitasok(h: bool, sorok: list[dict[str, Any]], szamlak: dict[str, dict[str, Any]], szl: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A talált hibák számlánként (forint-hatással), és a le nem vont részszámlák."""
    out: list[dict[str, Any]] = []
    for i, s in enumerate(sorok):
        m = s.get("mvm")
        if not m:
            continue
        if s.get("csonka"):
            out.append({"sorszam": s["sorszam"], "tol": s["tol"], "ig": s["ig"], "hatas_ft": None, "tipus": "csonka",
                        "szoveg": f"a számla {s['szamla_tol']} napjától szól, a mérőállások csak {s['tol']} napjától vannak meg: nem vethető össze"})
            continue
        e = s["elteres"]
        if abs(e) < max(100, s["helyes"] * 0.005):
            continue
        ok = []
        if m["kiszamlazott"] is not None and s["mert"] - m["kiszamlazott"] >= 1:
            ok.append(("nem_kiszamlazott", f"a mérőállások szerint {s['mert']:.0f} kWh fogyott, a számla {m['kiszamlazott']:.0f} kWh-t számláz ki – {s['mert'] - m['kiszamlazott']:.0f} kWh kimaradt"))
        if m["kiszamlazott"] is not None and m["kiszamlazott"] - s["mert"] >= 1:
            ered = next((o for o in sorok[:i] if o.get("mvm") and o["mvm"]["kiszamlazott"] is not None and o["mert"] - o["mvm"]["kiszamlazott"] >= 1), None)
            ok.append(("potolt_fogyasztas", f"a mérősor szerint {s['mert']:.0f} kWh fogyott, a számla {m['kiszamlazott']:.0f} kWh-t számláz: {m['kiszamlazott'] - s['mert']:.0f} kWh korábbi fogyasztást pótol"
                       + (f" (a {ered['sorszam']} sz. számlán kimaradt {ered['mert'] - ered['mvm']['kiszamlazott']:.0f} kWh), de ennek az időszaknak a keretével" if ered else "")))
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
    torolt = sztornozott_kulcsok(szamlak)  # a sztornózott részszámlát nem kell levonni
    utolso = max((_d(x["idoszak"][1]) for x in szl), default=None)
    for sorszam, x in szamlak.items():
        i = x.get("idoszak")
        if (x.get("tipus") == "resz" and sorszam not in torolt and i and utolso and _d(i[0]) <= utolso and not sorszam.startswith("kezi")
                and sorszam.lstrip("0") not in levont and _d(i[1]) >= _d(sorok[0]["tol"]) if sorok else False):
            out.append({"sorszam": sorszam, "tol": i[0], "ig": i[1], "hatas_ft": None, "tipus": "nem_levont",
                        "szoveg": f"a részszámlát ({int(Decimal(str(x.get('szamlaertek') or x.get('osszeg') or 0)))} Ft) egyik elszámoló sem vonta le – a következő elszámolónak le kell vonnia"})
    return out
