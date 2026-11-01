"""A fiókkártya fejléce: következő számla · folyó időszak · folyószámla-egyenleg.

A fiók panel-adataiból (panel._fiok_adat) és a tárolt számlákból. A következő számla a számlázási mód szerint:
- lezárt, még nem számlázott időszak (a záró mérőállás megvan) – a Rezsikövető számítása,
- átalány / fix díj – a szerződött összeg (a mérőtől független),
- diktált állás – a diktált fogyasztás díja,
- mért (diktálásos, leolvasásos, távleolvasásos) fiók – a folyó időszak díja a mérésből, a végéig előrevetítve.
Az éves (féléves) zárószámla nem itt, csak a kártyán szerepel.

Megbízhatóság („cimke”):
- „pontos”: átalány, fix díj, vagy ismert a záró mérőállás (csak a számla nem jött még meg),
- „mert”: saját mérő (szenzor) szerint, a hátralévő napokra napi átlaggal előrevetítve,
- „becsult”: nincs friss mért adat – az utolsó mérőállás óta (szezonális) napi átlaggal.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

try:
    from .varhato_szamlak import varhato_szamlak
except ImportError:  # tesztben a csomag mappája közvetlenül a path-on van
    from varhato_szamlak import varhato_szamlak

HORIZONT_NAP = 400  # a következő számla akkor is kell, ha messze van (pl. negyedéves szemétszállítás)


def _honap_mulva(d: date, n: int) -> date:
    ho = d.month - 1 + n
    ev, ho = d.year + ho // 12, ho % 12 + 1
    for nap in (d.day, 30, 29, 28):
        try:
            return date(ev, ho, nap)
        except ValueError:
            continue
    raise ValueError(d)


def _cimke_meres(f: dict[str, Any]) -> tuple[str, str]:
    """A folyó időszak várható díjának megbízhatósága a mérés forrása szerint."""
    v = f.get("varhato") or {}
    hatra = round(v.get("hatralevo_nap") or 0)
    if f.get("szenzor") and not (f.get("eddig") or {}).get("becsult"):
        return "mert", (f"Saját mérő (szenzor) szerint; a hátralévő {hatra} napra napi átlaggal előrevetítve."
                        if hatra else "Saját mérő (szenzor) szerint.")
    return "becsult", ("Nincs friss mért adat (nincs szenzor, vagy kiesett): az utolsó mérőállás óta napi átlaggal becsülve. "
                       "Diktálás vagy a következő számla pontosítja.")


def kovetkezo_szamla(f: dict[str, Any], szamlak: dict[str, dict[str, Any]], ma: date) -> dict[str, Any] | None:
    """{tol, ig, dij, fizetendo, kelte, forras, cimke, magyarazat, folyo} – a következőként érkező számla.

    tol, ig: az elszámolt időszak (mindkettő benne van); folyo: igaz, ha ez maga a folyó időszak (a kártya ugyanúgy
    írja ki, mint a folyó időszakot). dij: a számla díja; fizetendo: a túlfizetés beszámítása után."""
    es = f.get("esedekes") or {}
    if f.get("megszunt") and es.get("nincs_tobb") or es.get("szunetel"):
        return None
    uton = f.get("uton_szamlak") or []
    if uton:
        dk = f.get("diktalt_szamla") or {}
        diktalt = bool(dk) and not dk.get("becsult") and any(x.get("ig") == dk.get("datum") for x in uton)
        return {
            "tol": min(x["tol"] for x in uton), "ig": max(x["ig"] for x in uton),
            "dij": sum(int(x.get("osszeg_brutto", x["osszeg"])) for x in uton), "fizetendo": sum(int(x["osszeg"]) for x in uton),
            "kelte": None, "forras": "diktalas" if diktalt else "meres", "cimke": "pontos", "folyo": False,
            "magyarazat": ("Lezárt időszak: a záró mérőállás megvan, a számla még nem érkezett meg. "
                           "A díj a Rezsikövető számítása a díjszabás szerint."),
        }
    lista = [x for x in varhato_szamlak(f, szamlak, ma, HORIZONT_NAP) if x["forras"] != "elszamolas"]
    if not lista:
        return None
    x = dict(lista[0])
    if not x["tol"] and x["forras"] in ("atalany", "fix"):
        # A már kiállított számla utáni (következő) részszámla időszaka: a legutóbbi számla végétől az ütem szerint.
        vegek = [y["idoszak"][1] for y in szamlak.values() if y.get("idoszak") and y["idoszak"][1] and y.get("tipus") != "storno"]
        if vegek:
            tol = date.fromisoformat(max(vegek)[:10]) + timedelta(days=1)
            ho = int((f.get("utem") or {}).get("szamlazas_honap") or 1)
            x["tol"], x["ig"] = tol.isoformat(), (_honap_mulva(tol, ho) - timedelta(days=1)).isoformat()
    dij = fiz = x["osszeg"]
    if es.get("kovetkezo_osszeg_brutto") is not None and es.get("kovetkezo_osszeg") == x["osszeg"]:
        dij = int(es["kovetkezo_osszeg_brutto"])
    ki = {"tol": x["tol"], "ig": x["ig"], "dij": dij, "fizetendo": fiz, "kelte": x["kelte"], "forras": x["forras"], "folyo": False,
          "kesik": bool(es.get("elmaradt"))}
    if x["forras"] == "atalany":
        return ki | {"cimke": "pontos", "magyarazat": "A szerződött átalány szerint – a mérőállástól független."}
    if x["forras"] == "fix":
        return ki | {"cimke": "pontos", "magyarazat": "Fix díj a díjszabás szerint."}
    dk = f.get("diktalt_szamla") or {}
    if x["forras"] == "diktalas" or (dk and f.get("diktalas_szerint")):
        if dk.get("becsult"):
            c, m = _cimke_meres(f)
            return ki | {"tol": dk["tol"], "ig": dk["datum"], "dij": int(dk["osszeg"]), "fizetendo": int(dk["osszeg"]), "cimke": c,
                         "magyarazat": f"A szolgáltató diktálás szerint számláz; a következő diktálásig ({dk['datum']}). {m}"}
        return ki | {"cimke": "pontos", "magyarazat": f"A diktált mérőállás ({dk.get('datum') or x['ig']}) szerint, a díjszabással számolva."}
    # Mért fiók: a folyó időszak a végéig előrevetítve.
    i = f.get("idoszak") or {}
    v = (f.get("varhato") or {}).get("osszeg")
    folyo = x["tol"] == i.get("tol") and v is not None and x["osszeg"] == v
    kovb = ((f.get("beszamitas") or {}).get("szamlak") or [None])[0]
    if folyo and kovb and not kovb.get("idoszak") and abs(kovb["dij"] - v) < 1:
        dij, fiz = int(kovb["dij"]), int(kovb["fizetendo"])
    c, m = _cimke_meres(f)
    return ki | {"dij": dij, "fizetendo": fiz, "cimke": c, "magyarazat": m, "folyo": folyo}


def folyo_idoszak(f: dict[str, Any], ma: date | None = None) -> dict[str, Any] | None:
    """{tol, ig, eddig, varhato, eltelt_nap, napok, napi_atlag, cimke, magyarazat, tajekoztato} – a folyó időszak.

    tol, ig: mint a panel idoszak mezője (a kártya a diktálásos formában írja ki). tajekoztato: átalánynál igaz – a
    számla az átalány, ez csak a mért fogyasztás díja."""
    ma = ma or date.today()
    i, e, v = f.get("idoszak"), f.get("eddig"), f.get("varhato")
    if not i or not e or not v or f.get("megszunt") or (f.get("szunetel") or {}).get("most"):
        return None
    eltelt, hatra = v.get("eltelt_nap") or 0, v.get("hatralevo_nap") or 0
    if f.get("fix_dij"):
        # Fix (havi) díj: a hónap az egység – a megkezdett hónap díja egészében jár, nem napra bontva.
        tol, ig = date.fromisoformat(i["tol"][:10]), date.fromisoformat(i["ig"][:10])
        honapok = max((ig.year - tol.year) * 12 + ig.month - tol.month, 1)
        megkezdett = min(max((ma.year - tol.year) * 12 + ma.month - tol.month + 1, 0), honapok)
        varhato = v.get("osszeg")
        return {
            "tol": i["tol"], "ig": i["ig"], "varhato": varhato,
            "eddig": round(varhato * megkezdett / honapok) if varhato is not None else None,
            "eltelt_honap": megkezdett, "honapok": honapok, "eltelt_nap": round(eltelt), "napok": round(eltelt + hatra),
            "napi_atlag": None, "cimke": "pontos", "tajekoztato": False,
            "magyarazat": ("Fix havidíj: a hónap az egység – a megkezdett hónap díja egészében jár. "
                           + (f"Az időszak {honapok} hónap, havonta {round(varhato / honapok)} Ft." if varhato is not None and honapok > 1 else "")).strip(),
        }
    else:
        c, m = _cimke_meres(f)
    atalany = bool(f.get("reszszamlas") and not f.get("diktalas_szerint"))
    if atalany:
        m += " Tájékoztató: a számla az átalány szerint jön; a különbség az elszámoláskor rendeződik."
    be = (f.get("atalany") or {}).get("betaplalas") if atalany else None
    if be and e.get("mennyiseg") is not None and v.get("mennyiseg") is not None:
        # Szaldós napelem: a forint a vételezést árazná a betáplálás nélkül – helyette a nettó mennyiség.
        return {
            "tol": i["tol"], "ig": i["ig"], "eddig": None, "varhato": None,
            "eddig_netto": round(max(e["mennyiseg"] - be["eddig"], 0), 1), "varhato_netto": round(max(v["mennyiseg"] - be["varhato"], 0), 1),
            "eltelt_nap": round(eltelt), "napok": round(eltelt + hatra), "napi_atlag": v.get("napi_atlag"), "cimke": c,
            "magyarazat": m + " Szaldós napelem: nettó fogyasztás (vételezés − betáplálás), ezt veti össze a szolgáltató az átalánnyal.",
            "tajekoztato": True,
        }
    return {
        "tol": i["tol"], "ig": i["ig"], "eddig": e.get("osszeg"), "varhato": v.get("osszeg"),
        "eltelt_nap": round(eltelt), "napok": round(eltelt + hatra), "napi_atlag": v.get("napi_atlag"),
        "cimke": c, "magyarazat": m, "tajekoztato": atalany,
    }


def fejlec(f: dict[str, Any], szamlak: dict[str, dict[str, Any]], ma: date,
           egyenleg: dict[str, Any] | None = None) -> dict[str, Any]:
    """A kártya fejléce: {kovetkezo, folyo, egyenleg}. egyenleg: {osszeg, kozos} a folyószámla-kivonatból (záró egyenleg;
    mínusz: túlfizetés)."""
    return {"kovetkezo": kovetkezo_szamla(f, szamlak, ma), "folyo": folyo_idoszak(f, ma), "egyenleg": egyenleg}
