"""Átvétel a v1 YAML-csomagból: leolvasási napló és lezárt havi elszámolások.

Forrás-entitások (a v1 csomag nevei):
  sensor.meroora_leolvasasi_naplo       – attribútum: bejegyzesek
  sensor.villany_havi_elszamolas_naplo  – attribútum: honapok

Alapból próbafuttatás: csak jelentést ad, nem ment. A v1 csomaghoz nem nyúl.
"""

from __future__ import annotations

from copy import deepcopy as _masolat
from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant

from .modell import d

LEOLVASAS_NAPLO = "sensor.meroora_leolvasasi_naplo"
HAVI_NAPLO = "sensor.villany_havi_elszamolas_naplo"


def _hatarok(h: dict[str, Any]) -> tuple[date, date]:
    if h.get("tol") and h.get("ig"):
        return d(h["tol"]), d(h["ig"]) + timedelta(days=1)  # a v1-ben az „ig” a nap maga
    y, m = int(h["honap"][:4]), int(h["honap"][5:7])
    return date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)


def v1_import(hass: HomeAssistant, celok: dict[str, tuple[Any, str]], probafuttatas: bool) -> dict[str, Any]:
    """celok: {'A'|'H'|'G': (koordinátor, fiók-azonosító)}."""
    jelentes: dict[str, list[str]] = {"leolvasasok": [], "merok": [], "idoszakok": [], "kihagyva": []}

    # Munkapéldányon dolgozunk; csak éles futásnál írjuk vissza.
    munka = {m: _masolat(k.tarolo.fiok(sid)) for m, (k, sid) in celok.items()}

    naplo = hass.states.get(LEOLVASAS_NAPLO)
    for b in sorted((naplo.attributes.get("bejegyzesek") or []) if naplo else [], key=lambda x: x["datum"]):
        mero = b.get("mero")
        if mero not in munka:
            continue
        t = munka[mero]
        nap = d(b["datum"])
        if b["tipus"] == "Éves leolvasás":
            elso = t["merok"][0]
            if nap < d(elso["beepitve"]):
                elso["beepitve"] = nap.isoformat()
                elso["kezdo_allas"] = str(b["allas"])
                jelentes["merok"].append(f"{mero}: az első mérő kezdete {nap}-ra, kezdőállás {b['allas']}")
            cel = next(
                m
                for m in reversed(t["merok"])
                if d(m["beepitve"]) <= nap and (m.get("kiszerelve") is None or nap <= d(m["kiszerelve"]))
            )
            cel["leolvasasok"] = [lo for lo in cel["leolvasasok"] if lo["datum"] != nap.isoformat()] + [
                {
                    "datum": nap.isoformat(),
                    "allas": str(b["allas"]),
                    "tipus": "szolgaltatoi",
                    "elszamolasi": True,
                    "megjegyzes": "v1 éves leolvasás",
                }
            ]
            cel["leolvasasok"].sort(key=lambda x: x["datum"])
            jelentes["leolvasasok"].append(f"{mero} {nap}: {b['allas']} (elszámoló)")
        elif b["tipus"] == "Mérőcsere":
            elso = t["merok"][0]
            if len(t["merok"]) == 1 and (nap <= d(elso["beepitve"]) or not elso["leolvasasok"]):
                elso["beepitve"] = nap.isoformat()
                elso["kezdo_allas"] = str(b.get("uj_kezdo") or 0)
                jelentes["merok"].append(f"{mero}: mérő felszerelése {nap}, kezdőállás {b.get('uj_kezdo') or 0}")
            else:
                aktiv = t["merok"][-1]
                aktiv["kiszerelve"] = nap.isoformat()
                aktiv["zaro_allas"] = str(b["allas"])
                t["merok"].append(
                    {
                        "gyari_szam": "",
                        "beepitve": nap.isoformat(),
                        "kezdo_allas": str(b.get("uj_kezdo") or 0),
                        "kiszerelve": None,
                        "zaro_allas": None,
                        "leolvasasok": [],
                    }
                )
                jelentes["merok"].append(f"{mero}: mérőcsere {nap}, régi záró {b['allas']}, új kezdő {b.get('uj_kezdo')}")
        else:
            jelentes["kihagyva"].append(f"{mero} {nap}: {b['tipus']} ({b.get('allas')}) – a korrekciót kézi leolvasásként rögzítsd")

    havi = hass.states.get(HAVI_NAPLO)
    for h in (havi.attributes.get("honapok") or []) if havi else []:
        tol, ig = _hatarok(h)
        # A v1 egy összegben tárolta az A1 és a H alapdíját (megosztott hónapnál már arányosítva),
        # ezért a szétosztás aránya a díjfájlokból jön: A1 : H = alapdíj_A1 : alapdíj_H.
        tar = next(iter(celok.values()))[0].tar
        a1_alap = float(tar.felold("villany/a1", tol, "mvm_demasz").dijak["alapdij_ho"])
        h_alap = float(tar.felold("villany/h", tol, "mvm_demasz").dijak["alapdij_ho"])
        h_jar = "H" in munka and ig > d(munka["H"]["merok"][0]["beepitve"])
        a_resz = a1_alap / (a1_alap + h_alap) if h_jar else 1.0
        for mero, kwh, energia in (
            ("A", h["a_kwh"], h["energia_ft"]),
            ("H", h["h_teli_kwh"] + h["h_nyari_kwh"], h["h_teli_ft"] + h["h_nyari_ft"]),
        ):
            if mero not in munka:
                continue
            nyitott_tol = d(munka[mero].get("nyitott_tol"))
            if nyitott_tol and tol >= nyitott_tol:
                jelentes["kihagyva"].append(f"{mero} {h['honap']}: a nyitott időszakba esik")
                continue
            a_alapdij = round(h["alapdij_ft"] * a_resz)
            alapdij = a_alapdij if mero == "A" else h["alapdij_ft"] - a_alapdij
            if mero == "H" and kwh == 0 and alapdij == 0:
                continue
            bejegyzes = {
                "tol": tol.isoformat(),
                "ig": ig.isoformat(),
                "mennyiseg": str(kwh),
                "energia_ft": int(energia),
                "alapdij_ft": alapdij,
                "osszesen_ft": int(energia) + alapdij,
                "becsult": bool(h.get("becsult")),
                "szeletek": [],
                "rogzitve": h.get("rogzitve"),
                "forras": "v1_import",
                "megjegyzes": h.get("megjegyzes", ""),
            }
            t = munka[mero]
            t["lezart"] = [x for x in t["lezart"] if x["tol"] != bejegyzes["tol"]] + [bejegyzes]
            jelentes["idoszakok"].append(f"{mero} {h['honap']}: {bejegyzes['osszesen_ft']} Ft")

    if not probafuttatas:
        for m, (k, sid) in celok.items():
            k.tarolo.adat["fiokok"][sid] = munka[m]
    return {"probafuttatas": probafuttatas, **jelentes}
