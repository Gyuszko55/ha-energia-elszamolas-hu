"""Számlasablon (2.3.0b2): a jóváhagyott (AI-val kiolvasott) első számlából helyi beolvasó – a szolgáltató következő
számláit AI nélkül, helyben olvassa.

A sablon nem tartalmaz személyes adatot: csak a szolgáltató feliratait (név, adószám), a mezők melletti feliratokat
(„Számla kelte:”) és általános mintákat (dátum, összeg, sorszám-alak). Készítés: a jóváhagyott értékeket megkeresi
a számla szövegében, a soron balra álló felirat lesz a horgony; az értékből típus szerinti minta. Mentés csak akkor,
ha a forrásszámlán pontosan a jóváhagyott értékeket adja (önpróba), és a személyesadat-szűrőn átmegy.

HA nélkül is futtatható (tesztek). Tár: <config>/hu_rezsi_sablonok/<azonosito>.yaml.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .ai_beolvaso import Kitakaro, datum, normalizal, szam
except ImportError:  # tesztek
    from ai_beolvaso import Kitakaro, datum, normalizal, szam

_LOGGER = logging.getLogger(__name__)
VERZIO = 1
MAPPA_NEV = "hu_rezsi_sablonok"

# Közös minták (a sablonban rövidítve: {DATUM}, {SZAM})
DATUM = r"\d{4}[ \t]*[.\-/][ \t]*\d{1,2}[ \t]*[.\-/][ \t]*\d{1,2}\.?"
SZAM = r"-?\d{1,3}(?:[  .]\d{3})+(?:,\d+)?|-?\d+(?:[,.]\d+)?"
_DATUM_RE = re.compile(DATUM)
_SZAM_RE = re.compile(rf"(?<![\w,.])(?:{SZAM})(?![\d])")
_TAGOLT_RE = re.compile(r"(?:\d{1,3}(?:[  .]\d{3})+(?:,\d+)?)")
MEZOK_DATUM = ("kelte", "fizetesi_hatarido", "idoszak_tol", "idoszak_ig")
MEZOK_SZAM = ("fizetendo", "szamlaertek")


def _kibont(minta: str) -> str:
    """A sablonban tárolt minta ({DATUM}/{SZAM} rövidítésekkel) → reguláris kifejezés. A feliratok escape-elve
    kerülnek a mintába (a kapcsos zárójel is), így a rövidítés nem ütközhet egy felirattal."""
    # Atomi csoport: a már illesztett számba/dátumba nem lép vissza – a sok számoszlopos sornál ez akadályozza meg a
    # robbanásszerű visszalépést (catastrophic backtracking). Python 3.11+.
    return minta.replace("{DATUM}", f"(?>{DATUM})").replace("{SZAM}", f"(?>{SZAM})")


# --- Az értékek helye a szövegben -------------------------------------------------------------------------------


def _szam_formak(v: Any) -> list[str]:
    n = szam(v)
    if n is None:
        return []
    neg = "-" if n < 0 else ""
    n = abs(n)
    egesz = str(int(n))
    tort = None if n == int(n) else format(n, "f").split(".")[1].rstrip("0")
    tag = lambda sep: re.sub(r"\B(?=(\d{3})+(?!\d))", sep, egesz)  # noqa: E731
    ki = [neg + tag(sep) + ("," + tort if tort else "") for sep in (" ", "\u00a0", ".", "")]
    if tort:
        ki.append(neg + egesz + "." + tort)
        if len(tort) == 1:
            ki += [neg + tag(sep) + "," + tort + "0" for sep in (" ", "")]
    else:
        ki += [neg + tag(sep) + vege for sep in (" ", "") for vege in (",00", ",0", ".00")]
    return sorted(set(ki), key=len, reverse=True)


def _datum_formak(v: Any) -> list[str]:
    n = datum(v)
    if n is None:
        return []
    return [f"{n.year}.{n.month:02d}.{n.day:02d}.", f"{n.year}.{n.month:02d}.{n.day:02d}", f"{n.year}-{n.month:02d}-{n.day:02d}",
            f"{n.year}. {n.month:02d}. {n.day:02d}.", f"{n.year}/{n.month:02d}/{n.day:02d}"]


def _keres(szoveg: str, formak: list[str]) -> list[tuple[int, int]]:
    """Az érték előfordulásai (kezdet, vég) – nem egy hosszabb szám belsejében."""
    ki = []
    for f in formak:
        for m in re.finditer(re.escape(f), szoveg):
            a, b = m.start(), m.end()
            if (a and re.match(r"[\d,]", szoveg[a - 1])) or (b < len(szoveg) and re.match(r"\d|[,.]\d", szoveg[b:b + 2])):
                continue
            if not any(a < y and x < b for x, y in ki):
                ki.append((a, b))
    return sorted(ki)


# --- Felirat (horgony) ------------------------------------------------------------------------------------------


def _altalanosit(s: str) -> str:
    """A felirat szövege → minta: a benne álló dátum/szám általánosítva, a szóközök rugalmasan."""
    ki, poz = "", 0
    for m in re.finditer(rf"(?<![\w,.])(?:{DATUM}|{SZAM})(?![\w])", s):
        ki += _szavak(s[poz:m.start()]) + ("{DATUM}" if _DATUM_RE.fullmatch(m.group(0)) else "{SZAM}")
        poz = m.end()
    return ki + _szavak(s[poz:])


def _szavak(s: str) -> str:
    # soron belül marad: [ \t] (a \s a sortörést is elnyelné)
    if not s.strip():
        return r"[ \t]*" if s else ""
    ki = r"[ \t]+".join(re.escape(x) for x in s.split())
    return (r"[ \t]+" if s[0].isspace() else "") + ki + (r"[ \t]+" if s[-1].isspace() else "")


def _felirat(szoveg: str, a: int) -> str | None:
    """Az érték előtti felirat a soron: az utolsó nem üres oszlop (3+ szóköz választja el az oszlopokat)."""
    sor_eleje = szoveg.rfind("\n", 0, a) + 1
    bal = szoveg[sor_eleje:a]
    oszlopok = [x for x in re.split(r"\s{3,}", bal.rstrip()) if x.strip()]
    if not oszlopok:
        return None
    f = oszlopok[-1].strip()
    if not re.search(r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]", f) or len(f) < 3:
        return None
    return f


def _mezo_minta(szoveg: str, ertek_formak: list[str], tipus: str, foglalt: set[str] | None = None) -> str | None:
    """Egy mező mintája: felirat + rugalmas köz + (érték típusa). A legrövidebb egyértelmű feliratot választja."""
    jeloltek = []
    cap = {"datum": "({DATUM})", "osszeg": "({SZAM})"}.get(tipus, tipus)
    for i, (a, _b) in enumerate(_keres(szoveg, ertek_formak)):
        f = _felirat(szoveg, a)
        if not f:
            continue
        minta = _altalanosit(f)
        # A jó felirat kettősponttal végződik, és nincs benne változó rész (dátum, szám); azonos rangnál az első.
        rang = (0 if f.rstrip().endswith(":") else 1, minta.count("{"), i)
        if (teljes := minta + r"[ \t]*" + cap) not in (foglalt or set()):  # egy felirat csak egy mezőé (azonos dátumú mezők)
            jeloltek.append((rang, teljes))
    return min(jeloltek)[1] if jeloltek else None


def _sorszam_minta(ertek: str) -> str:
    """A sorszám alakja: a karakterosztályai, a hossza ±3 (a konkrét sorszám nem kerül a sablonba)."""
    osztaly = ""
    if re.search(r"[A-Za-z]", ertek):
        osztaly += "A-Za-z"
    if re.search(r"\d", ertek):
        osztaly += r"\d"
    for c in sorted(set(re.sub(r"[A-Za-z\d]", "", ertek))):
        osztaly += re.escape(c)
    n = len(ertek)
    return f"([{osztaly}]{{{max(3, n - 3)},{n + 3}}})"


# --- Táblázatsorok ----------------------------------------------------------------------------------------------


def _sor(szoveg: str, a: int) -> tuple[int, int]:
    e = szoveg.rfind("\n", 0, a) + 1
    v = szoveg.find("\n", a)
    return e, len(szoveg) if v < 0 else v


def _koz(s: str) -> str:
    """Két kiolvasott érték közti szöveg a sorban: a rövid jelölések (egység, kötőjel, pl. „m3”, „hó”, „-”) maradnak,
    a hosszabb szavak helyett bármi (soron belül) – így név, cím, egyéb szöveg nem kerül a sablonba."""
    if not s.strip():
        return r"[ \t]+" if s else r"[ \t]*"
    if all(len(x) <= 4 for x in s.split()):
        return r"[ \t]*" + _altalanosit(s.strip()) + r"[ \t]*"
    if re.search(r"\d", s):
        # Köztes számoszlopok (pl. „Ft/m3   1 194,30   27”): a helyük megmarad, különben a következő érték helyett egy
        # köztes számot (nettó díj, ÁFA %) olvasna. A szavak helyett bármi szám nélkül – szöveg nem kerül a sablonba.
        darabok: list[str] = []
        for x in re.findall(r"\d{1,3}(?:[  .]\d{3})+(?:,\d+)?(?=\s|$)|\S+", s.strip()):
            if re.fullmatch(SZAM, x):
                darabok.append("{SZAM}")
            elif re.search(r"\d", x):
                darabok.append(r"\S*\d\S*")
            elif not darabok or darabok[-1] != r"[^\d\s][^\d\n]*?":
                darabok.append(r"[^\d\s][^\d\n]*?")
        return (r"[ \t]+" if s[0].isspace() else "") + r"[ \t]+".join(darabok) + (r"[ \t]+" if s[-1].isspace() else "")
    return r"[ \t]+[^\n]*?[ \t]*"


def _sor_minta(sor: str, cimkek: list[tuple[int, int, str]]) -> str:
    """Egy táblázatsor mintája: az első kiolvasott értéktől az utolsóig, névvel ellátott csoportokkal; a sor eleje és
    vége kimarad (ott állhat név, cím, megjegyzés – a személyes adat nem kerülhet a sablonba)."""
    ki, poz = "", None
    for a, b, nev in sorted(cimkek):
        if poz is not None:
            ki += _koz(sor[poz:a])
        ki += nev
        poz = b
    return ki


def _gyari_osztaly(gy: str) -> str:
    """A mérő gyári számának alakja (pl. „21-114592” → [\\d\\-]{6,12}) – a konkrét szám nem kerül a sablonba."""
    o = r"\d" + ("A-Za-z" if re.search(r"[A-Za-z]", gy) else "") + "".join(re.escape(c) for c in sorted(set(re.sub(r"[A-Za-z\d]", "", gy))))
    n = len(gy)
    return f"[{o}]{{{max(4, n - 3)},{n + 3}}}"


def _mero_minta(szoveg: str, m: dict[str, Any]) -> tuple[str, dict[str, str]] | None:
    """Mérősor: a sor, amelyben a záró állás (és ha van, a gyári szám és a dátumok) szerepel."""
    for a, _b in _keres(szoveg, _szam_formak(m.get("ig_allas"))):
        e, v = _sor(szoveg, a)
        sor = szoveg[e:v]
        cimkek: list[tuple[int, int, str]] = []
        foglalt: list[tuple[int, int]] = []

        def tesz(formak: list[str], nev: str, minta: str) -> bool:
            for x, y in _keres(sor, formak):
                if not any(x < q and p < y for p, q in foglalt):
                    cimkek.append((x, y, f"(?P<{nev}>{minta})"))
                    foglalt.append((x, y))
                    return True
            return False

        if not tesz(_szam_formak(m.get("ig_allas")), "ig_allas", "{SZAM}"):
            continue
        # a záró a nagyobbik: az induló a sorban előtte álló, ugyanilyen alakú szám
        tesz(_szam_formak(m.get("tol_allas")), "tol_allas", "{SZAM}")
        tesz(_datum_formak(m.get("tol_datum")), "tol_datum", "{DATUM}")
        tesz(_datum_formak(m.get("ig_datum")), "ig_datum", "{DATUM}")
        if m.get("gyari_szam"):
            tesz([m["gyari_szam"]], "gyari_szam", _gyari_osztaly(m["gyari_szam"]))
        mod_szo = None
        for w in re.finditer(r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]{3,}\.?", sor):
            if not any(w.start() < q and p < w.end() for p, q in foglalt) and w.end() > max(q for _p, q in foglalt):
                mod_szo = w.group(0)
                cimkek.append((w.start(), w.end(), r"(?P<mod>[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]+\.?)"))
                break
        jelentes = {mod_szo: m.get("mod") or "becsult"} if mod_szo else {}
        return _sor_minta(sor, cimkek), jelentes
    return None


def _tetel_minta(szoveg: str, t: dict[str, Any]) -> str | None:
    """Tételsor: a megnevezés szó szerint (a díjtétel neve nem személyes adat), a számok névvel ellátott csoportban."""
    nev = (t.get("megnevezes") or "").strip()
    if not nev or szam(t.get("brutto")) is None:
        return None
    for m in re.finditer(re.escape(nev), szoveg):
        e, v = _sor(szoveg, m.start())
        sor = szoveg[e:v]
        x0 = m.start() - e
        bal = _keres(sor, _szam_formak(t.get("brutto")))
        bal = [p for p in bal if p[0] > x0]
        if not bal:
            continue
        cimkek = [(x0, x0 + len(nev), re.escape(nev))]
        foglalt = [(x0, x0 + len(nev)), bal[-1]]
        cimkek.append((bal[-1][0], bal[-1][1], "(?P<brutto>{SZAM})"))
        for k in ("mennyiseg", "egysegar"):
            for x, y in _keres(sor, _szam_formak(t.get(k))):
                if not any(x < q and p < y for p, q in foglalt):
                    cimkek.append((x, y, f"(?P<{k}>{{SZAM}})"))
                    foglalt.append((x, y))
                    break
        return _sor_minta(sor, cimkek)
    return None


def _mennyiseg_minta(szoveg: str, q: dict[str, Any]) -> str | None:
    nev, egys = (q.get("megnevezes") or "").strip(), (q.get("egyseg") or "").strip()
    if not nev:
        return None
    for f in _szam_formak(q.get("mennyiseg")):
        minta = re.escape(nev) + r"[ \t:]*" + re.escape(f) + (r"[ \t]*" + re.escape(egys) if egys else "")
        if re.search(minta, szoveg):
            return re.escape(nev) + r"[ \t:]*({SZAM})" + (r"[ \t]*" + re.escape(egys) if egys else "")
    return None


# --- Készítés, alkalmazás, önpróba ------------------------------------------------------------------------------


# A közmű jellemző szava a számlán: több közművet számlázó szolgáltatónál (azonos név, adószám) ez választja szét a
# sablonokat. Az első, a számlán szereplő szó kerül a felismerés szövegei közé.
KOZMU_SZAVAK = {
    "villany": ["villamos energia", "villamosenergia", "kWh"], "gaz": ["földgáz", "MJ"], "viz": ["ivóvíz", "víziközmű", "m3"],
    "hulladek": ["hulladék", "ürítés"], "tavho": ["távhő", "hődíj"], "kozos": ["közös költség"], "tavkozles": ["internet", "telefon"],
}


def _kozmu_szavak(kozmu: str | None, szoveg: str) -> list[str]:
    t = _tomor(szoveg)
    return next(([s] for s in KOZMU_SZAVAK.get(kozmu or "", []) if _tomor(s) in t), [])


def _tipus(szoveg: str, alap: str) -> str:
    """A számla típusa a szövegéből (a sablon az első számla típusát nem rögzíti: a következő lehet elszámoló)."""
    t = szoveg.lower()
    if re.search(r"sztornó|storno|érvénytelenít", t):
        return "storno"
    if re.search(r"elszámoló számla|végszámla|éves elszámolás|elszámoló\b", t):
        return "elszamolo"
    if re.search(r"részszámla|\d+\. ?sz\. részszámla", t):
        return "resz"
    return alap if alap in ("resz", "elszamolo", "egyeb") else "egyeb"


def azonosito(adat: dict[str, Any]) -> str:
    alap = unicodedata.normalize("NFKD", adat.get("szolgaltato_nev") or "szolgaltato").encode("ascii", "ignore").decode()
    alap = re.sub(r"[^a-z0-9]+", "_", alap.lower()).strip("_")[:40] or "szolgaltato"
    return f"{alap}_{adat.get('kozmu') or 'x'}"


def keszit(adat: dict[str, Any], sima: str, tabla: str, ma: date | None = None) -> dict[str, Any]:
    """Sablon a jóváhagyott adatból. Minden mezőnél előbb a táblázatos, aztán a folyó szövegben keres."""
    adat = normalizal(adat)
    felismeres = [s for s in (adat.get("szolgaltato_nev"), adat.get("szolgaltato_adoszam")) if s]
    sab: dict[str, Any] = {
        "azonosito": azonosito(adat), "nev": f"{adat.get('szolgaltato_nev') or 'Szolgáltató'} – {adat.get('kozmu') or ''}",
        "kozmu": adat.get("kozmu"), "verzio": 1, "formatum": VERZIO,
        "felismeres": {"szovegek": felismeres + _kozmu_szavak(adat.get("kozmu"), sima + "\n" + tabla)},
        "allando": {k: adat[k] for k in ("szolgaltato_nev", "szolgaltato_adoszam", "kozmu") if adat.get(k)},
        "alap_tipus": adat.get("tipus") or "egyeb",
        "mezok": {}, "merok": [], "tetelek": [], "mennyisegek": [],
        "ellenorzes": {"keszult": (ma or date.today()).isoformat(),
                       "mintaszamla_ujjlenyomat": hashlib.sha1(re.sub(r"\s+", " ", tabla).encode()).hexdigest()[:16]},
    }
    for szoveg_nev, szoveg in (("tabla", tabla), ("sima", sima)):
        for k in MEZOK_DATUM:
            if adat.get(k) and k not in sab["mezok"] and (m := _mezo_minta(szoveg, _datum_formak(adat[k]), "datum", {x["minta"] for x in sab["mezok"].values()})):
                sab["mezok"][k] = {"minta": m, "szoveg": szoveg_nev, "tipus": "datum"}
        for k in MEZOK_SZAM:
            if adat.get(k) is not None and k not in sab["mezok"] and (m := _mezo_minta(szoveg, _szam_formak(adat[k]), "osszeg", {x["minta"] for x in sab["mezok"].values()})):
                sab["mezok"][k] = {"minta": m, "szoveg": szoveg_nev, "tipus": "osszeg"}
        if adat.get("sorszam") and "sorszam" not in sab["mezok"] and (m := _mezo_minta(szoveg, [adat["sorszam"]], _sorszam_minta(adat["sorszam"]))):
            sab["mezok"]["sorszam"] = {"minta": m, "szoveg": szoveg_nev, "tipus": "szoveg"}
    for m in adat.get("merok") or []:
        if (r := _mero_minta(tabla, m)) and r[0] not in [x["sor"] for x in sab["merok"]]:
            sab["merok"].append({"sor": r[0], "mod_jelentes": r[1], **({"regiszter": m["regiszter"]} if m.get("regiszter") else {})})
    for t in adat.get("tetelek") or []:
        if (r := _tetel_minta(tabla, t)) and r not in [x["sor"] for x in sab["tetelek"]]:
            sab["tetelek"].append({"sor": r, "megnevezes": t["megnevezes"], **({"egyseg": t["egyseg"]} if t.get("egyseg") else {})})
    for q in adat.get("mennyisegek") or []:
        if r := _mennyiseg_minta(sima + "\n" + tabla, q):
            sab["mennyisegek"].append({"minta": r, "megnevezes": q["megnevezes"], "egyseg": q.get("egyseg") or ""})
    return sab


def _tomor(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def felismeri(sab: dict[str, Any], szoveg: str) -> bool:
    t = _tomor(szoveg)
    szovegek = (sab.get("felismeres") or {}).get("szovegek") or []
    return bool(szovegek) and all(_tomor(s) in t for s in szovegek)


def alkalmaz(sab: dict[str, Any], sima: str, tabla: str) -> dict[str, Any] | None:
    """A sablon a számlán: kiolvasott adat (mint az AI-é, normalizal-alakban), vagy None, ha nem ez a szolgáltató."""
    if not felismeri(sab, sima + "\n" + tabla):
        return None
    szovegek = {"tabla": tabla, "sima": sima}
    d: dict[str, Any] = dict(sab.get("allando") or {})
    d["tipus"] = _tipus(sima + "\n" + tabla, sab.get("alap_tipus") or (sab.get("allando") or {}).get("tipus") or "egyeb")
    for k, m in (sab.get("mezok") or {}).items():
        talalat = re.search(_kibont(m["minta"]), szovegek.get(m.get("szoveg"), tabla), re.M)
        if talalat:
            d[k] = talalat.group(1)
    d["merok"] = []
    for sor in sab.get("merok") or []:
        rx = re.compile(_kibont(sor["sor"]))
        for t in (x for s in _sorok(tabla) if (x := rx.search(s))):
            g = t.groupdict()
            mod = (sor.get("mod_jelentes") or {}).get(g.get("mod") or "", None) or _mod_szotol(g.get("mod") or "")
            d["merok"].append({"gyari_szam": g.get("gyari_szam") or "", "regiszter": sor.get("regiszter", ""),
                               "tol_datum": g.get("tol_datum"), "tol_allas": g.get("tol_allas"), "ig_datum": g.get("ig_datum"),
                               "ig_allas": g.get("ig_allas"), "mod": mod or "becsult"})
    d["tetelek"] = []
    for sor in sab.get("tetelek") or []:
        rx = re.compile(_kibont(sor["sor"]))
        if t := next((x for s in _sorok(tabla) if (x := rx.search(s))), None):
            g = t.groupdict()
            d["tetelek"].append({"megnevezes": sor["megnevezes"], "mennyiseg": g.get("mennyiseg"), "egyseg": sor.get("egyseg", ""),
                                 "egysegar": g.get("egysegar"), "brutto": g.get("brutto")})
    d["mennyisegek"] = []
    for q in sab.get("mennyisegek") or []:
        if t := re.search(_kibont(q["minta"]), sima + "\n" + tabla):
            d["mennyisegek"].append({"megnevezes": q["megnevezes"], "mennyiseg": t.group(1), "egyseg": q.get("egyseg", "")})
    return normalizal(d)


KOTELEZO = ("sorszam", "kelte", "fizetendo")
SOR_MAX = 400  # ennél hosszabb sorra a sormintákat nem próbáljuk (a futásidő korlátja)


def _sorok(szoveg: str) -> list[str]:
    return [s for s in szoveg.splitlines() if len(s) <= SOR_MAX]


def _mod_szotol(szo: str) -> str | None:
    s = szo.lower()
    if s.startswith(("leol", "távleol", "tavleol")):
        return "leolvasott"
    if s.startswith(("dikt", "bejel", "önleol", "onleol")):
        return "diktalt"
    if s.startswith(("becs", "kalk", "számít", "szamit")):
        return "becsult"
    return None


def hianyzo(adat: dict[str, Any] | None) -> list[str]:
    return list(KOTELEZO) if adat is None else [k for k in KOTELEZO if adat.get(k) in (None, "")]


def _ossze(a: dict[str, Any]) -> dict[str, Any]:
    """Az önpróbán összevetett adatok (az egyéb mezők, pl. megnevezés-írásmód, nem számítanak)."""
    return {
        **{k: a.get(k) for k in ("sorszam", "kelte", "fizetesi_hatarido", "fizetendo", "szamlaertek", "idoszak_tol", "idoszak_ig")},
        "merok": sorted((m.get("ig_datum"), m.get("ig_allas"), m.get("tol_datum"), m.get("tol_allas")) for m in a.get("merok") or []),
        "tetelek": sorted(str(t.get("brutto")) for t in a.get("tetelek") or []),
        "mennyisegek": sorted(str(q.get("mennyiseg")) for q in a.get("mennyisegek") or []),
    }


def onproba(sab: dict[str, Any], adat: dict[str, Any], sima: str, tabla: str) -> list[str]:
    """A sablon a forrásszámlán: az eltérő mezők listája (üres: a jóváhagyott értékeket adja)."""
    kapott = alkalmaz(sab, sima, tabla)
    if kapott is None:
        return ["a sablon nem ismeri fel a forrásszámlát"]
    v, k = _ossze(normalizal(adat)), _ossze(kapott)
    return [m for m in v if v[m] != k[m]]


def _lathato(minta: str) -> str:
    """Egy minta „szöveg” része (a reguláris elemek nélkül): ebben keressük a személyes adatot."""
    s = re.sub(r"\(\?P<\w+>[^()]*(?:\([^()]*\))*[^()]*\)|\{DATUM\}|\{SZAM\}|\[[^\]]*\](?:\{\d+,\d+\})?|\\[st][+*]?|\[ \\t\][+*]|[\^$*+?]|\(\?[:>]|[()]", " ", minta)
    s = re.sub(r"\\(.)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _szovegek(sab: dict[str, Any]) -> list[str]:
    """A sablon minden szövege (felismerés, állandók) és mintája – a személyesadat-szűrőnek."""
    ki = list((sab.get("felismeres") or {}).get("szovegek", [])) + [str(v) for v in (sab.get("allando") or {}).values()]
    ki += [_lathato(m["minta"]) for m in (sab.get("mezok") or {}).values()]
    ki += [_lathato(x["sor"]) for x in (sab.get("merok") or []) + (sab.get("tetelek") or [])]
    ki += [str(x.get("megnevezes") or "") for x in (sab.get("tetelek") or []) + (sab.get("mennyisegek") or [])]
    ki += [_lathato(x["minta"]) for x in sab.get("mennyisegek") or []]
    ki += [k for x in sab.get("merok") or [] for k in (x.get("mod_jelentes") or {})]
    return [s for s in ki if s]


def szemelyes(sab: dict[str, Any], tiltott: list[str]) -> list[str]:
    """A sablonban maradt személyes adat: a tiltott (ismert) értékek bármelyik mintában, és amit a kitakaró mintái
    (e-mail, telefon, bankszámla, felirat utáni név/cím, cím) felismernek."""
    szovegek = _szovegek(sab)
    egyben = _tomor(" ".join(szovegek))
    talalt = [t for t in tiltott if t and len(t.strip()) >= 4 and _tomor(t) in egyben]
    kt = Kitakaro()
    talalt += [s for s in szovegek if kt.kitakar(s) != s]
    return talalt


# --- Tár -------------------------------------------------------------------------------------------------------


def betolt(mappa: Path) -> list[dict[str, Any]]:
    import yaml  # noqa: PLC0415

    ki = []
    if not mappa.is_dir():
        return ki
    for f in sorted(mappa.glob("*.yaml")):
        try:
            s = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception as err:  # noqa: BLE001 – egy hibás sablon ne állítsa meg a többit
            _LOGGER.warning("Hibás számlasablon (%s): %s", f.name, err)
            continue
        if isinstance(s, dict) and s.get("azonosito") and s.get("felismeres"):
            s["_fajl"] = f.name
            ki.append(s)
    return ki


BEEPITETT = Path(__file__).parent / "sablonok"


def osszes_betolt(config_dir: Path | str) -> list[dict[str, Any]]:
    """A felhasználó saját beolvasói (`config/hu_rezsi_sablonok/`), utánuk a Rezsikövetővel érkező beépítettek
    (`sablonok/`). Azonos azonosítónál a saját az erősebb (pl. ha valaki a beépítettet már kézzel bemásolta)."""
    sajat = betolt(Path(config_dir) / MAPPA_NEV)
    van = {s["azonosito"] for s in sajat}
    beep = [dict(s, _beepitett=True) for s in betolt(BEEPITETT) if s["azonosito"] not in van]
    return sajat + beep


def ment(mappa: Path, sab: dict[str, Any]) -> Path:
    """Mentés. Ha ennek a szolgáltatónak már van sablonja, az új egy másik számlaformáé (a meglévő ezt a számlát nem
    tudta beolvasni – különben nem kellett volna AI): külön fájlba kerül (`<azonosító>_2.yaml` …), a régi is marad."""
    import yaml  # noqa: PLC0415

    mappa.mkdir(parents=True, exist_ok=True)
    alap, n = sab["azonosito"], 1
    cel = mappa / f"{alap}.yaml"
    while cel.exists():
        n += 1
        cel = mappa / f"{alap}_{n}.yaml"
    if n > 1:
        sab["azonosito"], sab["forma"] = f"{alap}_{n}", n
    fej = ("# Rezsikövető számlasablon – a jóváhagyott első számlából készült (személyes adat nélkül).\n"
           "# Megosztható; a minták: DATUM = dátum, SZAM = szám, (...) = a kiolvasott érték.\n")
    cel.write_text(fej + yaml.safe_dump({k: v for k, v in sab.items() if not k.startswith("_")}, allow_unicode=True,
                                        sort_keys=False, width=200), encoding="utf-8")
    return cel
