"""AI-számlabeolvasó (2.3.0b1): a fel nem ismert számla kiolvasása egy AI Task entitással – jóváhagyással.

Ez a modul HA nélkül is futtatható (tesztek): kitakarás, az AI-nak adott utasítás és adatszerkezet, a válasz
egységesítése és Számlává alakítása. Az AI-hívás maga a koordinátorban van (koordinator.ai_kiolvasas).

Adatvédelem: elküldés előtt a felismerhető személyes adatok helyőrzőt kapnak (KITAKART_1, MERO_1 …), a válaszban
a Rezsikövető visszaírja őket. A szolgáltató neve és adószáma marad (a sablonhoz kell, nem személyes adat).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    from .szamla_import import _aktiv
    from .szamlak import Meroallas, Szamla, mero_azonosito
except ImportError:  # tesztek: a csomag HA nélkül, közvetlenül
    from szamla_import import _aktiv
    from szamlak import Meroallas, Szamla, mero_azonosito

KOZMUVEK = ["villany", "gaz", "viz", "hulladek", "tavho", "kozos", "tavkozles"]
TIPUSOK = ["resz", "elszamolo", "egyeb", "storno"]
MODOK = {"leolvasott": "Leol", "diktalt": "Dikt", "becsult": "Becs"}
MIN_SZOVEG = 80  # ennél rövidebb kinyert szöveg: szkennelt (képes) PDF

# --- Kitakarás -------------------------------------------------------------------------------------------------

_MINTAK = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("iban", re.compile(r"\bHU\d{2}(?:[ ]?\d{4}){6}\b", re.I)),
    ("bankszamla", re.compile(r"\b\d{8}-\d{8}(?:-\d{8})?\b")),
    ("telefon", re.compile(r"(?<!\d)(?:\+36|06)[ /-]?(?:1|\d{2})[ /-]?\d{3}[ -]?\d{3,4}(?!\d)")),
    ("adoazonosito", re.compile(r"(?<![\d-])8\d{9}(?![\d-])")),
]
# A felirat utáni érték (név, cím, azonosító) kitakarva; a felirat marad, hogy az AI lássa, mi volt ott. A felirat a sor
# elején vagy egy oszlop elején (2+ szóköz után) állhat; az érték az oszlop végéig tart (3+ szóköz vagy sorvég), ha
# pedig a felirat után a sorban nincs érték, a következő nem üres sor az érték.
_FELIRAT_SZOK = (r"Felhasználási hely(?: címe)?|Felhasználó(?: neve| címe)?|Vevő(?: neve| címe)?|Fizető(?: neve| címe)?|"
                 r"Számlafizető|Ügyfél(?: neve| címe)?|Értesítési cím|Postázási cím|Levelezési cím|Számlázási cím|"
                 r"Szerződő(?: neve)?|Tulajdonos|Név|Cím|Lakcím|Születési (?:név|hely|idő)|Anyja neve")
_FELIRAT_ELEJE = rf"(?:^|(?<=[ \t]{{2}}))[ \t]*(?:{_FELIRAT_SZOK})\b[^:\n]{{0,30}}:"
# 1. az érték ugyanabban a sorban (az oszlop végéig); 2. a felirat után üres a sor: a következő sor eleje az érték
_FELIRATOK = re.compile(rf"(?im)(?P<f>{_FELIRAT_ELEJE}[ \t]*)(?P<e>[^ \t\n][^\n]*?)(?=[ \t]{{3,}}|[ \t]*$)")
_FELIRAT_KOV = re.compile(rf"(?im)(?P<f>{_FELIRAT_ELEJE}[ \t]*\n[ \t]*)(?P<e>[^ \t\n][^\n]*?)(?=[ \t]{{3,}}|[ \t]*$)")
# Cím felirat nélkül (pl. a borítékablak): irányítószám + település + közterület + házszám.
_CIM = re.compile(r"(?<!\d)\d{4}[ \t]+[A-ZÁÉÍÓÖŐÚÜŰ][\wáéíóöőúüű.-]+,?[ \t]+[^\n]{0,40}?\b(?:utca|út|útja|tér|tere|köz|körút|krt\.?|"
                  r"sor|sétány|fasor|lakótelep|ltp\.|dűlő|u\.)[ \t]*\d+[^\n]{0,20}?(?=[ \t]{3,}|[ \t]*$)", re.M)


class Kitakaro:
    """Visszafejthető kitakarás: ugyanaz az érték mindenütt ugyanazt a helyőrzőt kapja."""

    def __init__(self, ismert: list[str] | None = None, merok: list[str] | None = None) -> None:
        self.terkep: dict[str, str] = {}  # helyőrző → eredeti
        self._vissza: dict[str, str] = {}  # eredeti → helyőrző
        self.merok = [m for m in dict.fromkeys(x.strip() for x in merok or []) if m]
        self.ismert = sorted({x.strip() for x in ismert or [] if x and len(x.strip()) >= 4}, key=len, reverse=True)
        # A mérőszám csak elég hosszú (≥ 5 jelentős karakter) azonosítóként takarható ki – egy rövid szám (pl. 12345)
        # az összegeket is elrontaná.
        self.merok = [m for m in self.merok if len(re.sub(r"\W", "", m.lstrip("0"))) >= 5]
        self.kategoriak: dict[str, int] = {}
        for i, m in enumerate(self.merok, 1):
            self.terkep[f"MERO_{i}"], self._vissza[m] = m, f"MERO_{i}"

    def _hely(self, ertek: str, elotag: str = "KITAKART") -> str:
        if ertek in self._vissza:
            return self._vissza[ertek]
        n = sum(1 for k in self.terkep if k.startswith(elotag + "_")) + 1
        h = f"{elotag}_{n}"
        self.terkep[h], self._vissza[ertek] = ertek, h
        return h

    def kitakar(self, szoveg: str) -> str:
        t = szoveg or ""
        # Mérőszám: a fiók mérői MERO_n-t kapnak (a válaszban visszakerül, így a mérő párosítható).
        for i, m in enumerate(self.merok, 1):
            h = f"MERO_{i}"
            # Pontosan a mérőszám (vezető nullákkal vagy nélkülük) – tagolt számot (pl. „12 345 Ft”) nem érint.
            t, db = re.subn(rf"(?<![\w.,])0*{re.escape(m.lstrip('0'))}(?![\w])", h, t)
            if db:
                self.kategoriak["mérőszám"] = self.kategoriak.get("mérőszám", 0) + db
        for s in self.ismert:
            minta = re.compile(r"(?<!\w)" + r"\s+".join(re.escape(r) for r in s.split()) + r"(?!\w)", re.I)
            t, db = minta.subn(lambda m, s=s: self._hely(s), t)
            if db:
                self.kategoriak["ismert adat"] = self.kategoriak.get("ismert adat", 0) + db
        for nev, minta in _MINTAK:
            t, db = minta.subn(lambda m: self._hely(m.group(0)), t)
            if db:
                self.kategoriak[nev] = self.kategoriak.get(nev, 0) + db

        def felirat(m: re.Match) -> str:
            e = m.group("e").strip()
            if not e or re.fullmatch(r"(?:KITAKART|MERO)_\d+", e) or re.match(rf"(?i)(?:{_FELIRAT_SZOK})\b[^:\n]{{0,30}}:", e):
                return m.group(0)
            self.kategoriak["név/cím sor"] = self.kategoriak.get("név/cím sor", 0) + 1
            return m.group("f") + self._hely(e)

        t = _FELIRATOK.sub(felirat, t)
        t = _FELIRAT_KOV.sub(felirat, t)
        t, db = _CIM.subn(lambda m: self._hely(m.group(0).strip()), t)
        if db:
            self.kategoriak["cím"] = self.kategoriak.get("cím", 0) + db
        return t

    def visszair(self, x: Any) -> Any:
        if isinstance(x, str):
            return re.sub(r"\b(?:KITAKART|MERO)_\d+\b", lambda m: self.terkep.get(m.group(0), m.group(0)), x)
        if isinstance(x, list):
            return [self.visszair(v) for v in x]
        if isinstance(x, dict):
            return {k: self.visszair(v) for k, v in x.items()}
        return x


# --- Az AI-nak adott utasítás és adatszerkezet ---------------------------------------------------------------

UTASITAS = """Egy magyar közüzemi (rezsi-) számla szövegéből kérem az adatokat a megadott szerkezetben.
Szigorú szabályok:
- CSAK a számla szövegében szó szerint szereplő értéket add vissza. Ne számolj, ne becsülj, ne találj ki semmit;
  ami nincs a szövegben, azt hagyd üresen (vagy a listát üresen).
- A dátumokat ÉÉÉÉ-HH-NN alakban add vissza (pl. „2026.10.05.” → 2026-10-05).
- Az összegek forintban, bruttó, előjellel (jóváírás/visszatérítés negatív), tagolás nélkül (pl. 12 345 → 12345).
- A KITAKART_n és MERO_n szavak kitakart személyes adatok, illetve a fiók mérői: a mérő gyári számaként a MERO_n
  szót add vissza változatlanul.
- „tipus”: resz = részszámla (átalány, becsült), elszamolo = elszámoló/éves/végszámla (leolvasás alapján),
  storno = sztornó/érvénytelenítő számla, egyeb = minden más (pl. fix díjas, havidíjas szolgáltatás).
- „fizetendo”: a számla végén fizetendő összeg; „szamlaertek”: a számla bruttó értéke (ha a fizetendőtől eltér,
  pl. levont részszámlák vagy túlfizetés miatt).
- „merok”: a mérőállás-sorok (gyári szám, induló és záró dátum és állás, a leolvasás módja). Több regiszter
  (pl. 1.8.1, 1.8.2) esetén regiszterenként egy sor, a „regiszter” mezőben a jelölésével.
- „mennyisegek”: az elszámolt mennyiségek (pl. „Elszámolt mennyiség: 12 m3”), „tetelek”: a díjtételek sorai
  (megnevezés, mennyiség, egység, bruttó egységár, bruttó érték – ami a sorban szerepel).
"""


def _txt(leiras: str, kotelezo: bool = False) -> dict[str, Any]:
    return {"description": leiras, "required": kotelezo, "selector": {"text": {}}}


def _szam(leiras: str, kotelezo: bool = False) -> dict[str, Any]:
    return {"description": leiras, "required": kotelezo, "selector": {"number": {"mode": "box", "step": "any"}}}


def _lista(leiras: str, mezok: dict[str, Any]) -> dict[str, Any]:
    return {"description": leiras, "required": False,
            "selector": {"object": {"multiple": True, "fields": {k: {k2: v2 for k2, v2 in v.items() if k2 != "description"}
                                                                  | {"label": v["description"]} for k, v in mezok.items()}}}}


STRUKTURA: dict[str, Any] = {
    "szolgaltato_nev": _txt("A szolgáltató (számlakibocsátó) neve.", True),
    "szolgaltato_adoszam": _txt("A szolgáltató adószáma, ha szerepel."),
    "kozmu": {"description": "A szolgáltatás fajtája.", "required": True, "selector": {"select": {"options": KOZMUVEK}}},
    "sorszam": _txt("A számla sorszáma.", True),
    "kelte": _txt("A számla kelte (kiállítás dátuma), ÉÉÉÉ-HH-NN.", True),
    "fizetesi_hatarido": _txt("Fizetési határidő, ÉÉÉÉ-HH-NN."),
    "tipus": {"description": "resz / elszamolo / egyeb / storno", "required": True, "selector": {"select": {"options": TIPUSOK}}},
    "fizetendo": _szam("Fizetendő összeg, Ft (bruttó).", True),
    "szamlaertek": _szam("A számla bruttó értéke, Ft (ha a fizetendőtől eltér)."),
    "idoszak_tol": _txt("Az elszámolási (számlázási) időszak kezdete, ÉÉÉÉ-HH-NN."),
    "idoszak_ig": _txt("Az elszámolási időszak vége, ÉÉÉÉ-HH-NN."),
    "merok": _lista("Mérőállás-sorok.", {
        "gyari_szam": _txt("A mérő gyári száma (vagy MERO_n)."), "regiszter": _txt("Regiszter (pl. 1.8.1), ha van."),
        "tol_datum": _txt("Induló dátum, ÉÉÉÉ-HH-NN."), "tol_allas": _szam("Induló mérőállás."),
        "ig_datum": _txt("Záró dátum, ÉÉÉÉ-HH-NN."), "ig_allas": _szam("Záró mérőállás."),
        "mod": {"description": "leolvasott / diktalt / becsult", "selector": {"select": {"options": list(MODOK)}}},
    }),
    "mennyisegek": _lista("Elszámolt mennyiségek.", {
        "megnevezes": _txt("Megnevezés (pl. Ivóvíz, Csatorna, Villamos energia)."), "mennyiseg": _szam("Mennyiség."),
        "egyseg": _txt("Egység (kWh, m3, MJ, hó, db)."),
    }),
    "tetelek": _lista("Díjtételek.", {
        "megnevezes": _txt("Megnevezés."), "mennyiseg": _szam("Mennyiség."), "egyseg": _txt("Egység."),
        "egysegar": _szam("Bruttó egységár, Ft."), "brutto": _szam("Bruttó érték, Ft."),
    }),
}


def utasitas(segito: dict[str, Any], szoveg_sima: str, szoveg_tabla: str) -> str:
    """A teljes utasítás: szabályok + a fiók segítő adatai + a (kitakart) számlaszöveg kétféle kinyeréssel."""
    s = [f"- közmű: {segito.get('kozmu')}, mért egység: {segito.get('egyseg')}"]
    if segito.get("merok"):
        s.append("- a fiók mérői: " + ", ".join(segito["merok"]))
    if segito.get("utolso_allas"):
        u = segito["utolso_allas"]
        s.append(f"- utolsó ismert mérőállás: {u['allas']} ({u['datum']})")
    return (f"{UTASITAS}\nA fiók ismert adatai (segítség, nem a számla része):\n" + "\n".join(s)
            + "\n\nA számla szövege (táblázatos kinyerés):\n<<<\n" + szoveg_tabla.strip()
            + "\n>>>\n\nUgyanez folyó szövegként (a számokhoz megbízhatóbb):\n<<<\n" + szoveg_sima.strip() + "\n>>>")


# --- A válasz egységesítése ------------------------------------------------------------------------------------

_HONAPOK = {"jan": 1, "feb": 2, "már": 3, "mar": 3, "ápr": 4, "apr": 4, "máj": 5, "maj": 5, "jún": 6, "jun": 6,
            "júl": 7, "jul": 7, "aug": 8, "szep": 9, "okt": 10, "nov": 11, "dec": 12}


def datum(x: Any) -> date | None:
    """ÉÉÉÉ-HH-NN, ÉÉÉÉ.HH.NN(.), ÉÉÉÉ. HH. NN., ÉÉÉÉ. hónapnév NN. → dátum (más: None)."""
    if isinstance(x, date):
        return x
    s = str(x or "").strip()
    if m := re.fullmatch(r"(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\.?", s):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if m := re.fullmatch(r"(\d{4})\.?\s*([a-záéíóöőúüű]+)\.?\s*(\d{1,2})\.?", s, re.I):
        ho = _HONAPOK.get(m.group(2).lower()[:4].rstrip(".")) or _HONAPOK.get(m.group(2).lower()[:3])
        if ho:
            try:
                return date(int(m.group(1)), ho, int(m.group(3)))
            except ValueError:
                return None
    return None


def szam(x: Any) -> Decimal | None:
    """Szám (az AI néha szövegként adja, tagolva): 12 345 / 12.345 / 12345,6 / -1 200 Ft → Decimal."""
    if x is None or x == "" or isinstance(x, bool):
        return None
    if isinstance(x, (int, float, Decimal)):
        try:
            return _egesz(Decimal(str(x)))
        except (InvalidOperation, ValueError, OverflowError):
            return None
    s = re.sub(r"[\s ]|Ft|HUF", "", str(x), flags=re.I)
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return _egesz(Decimal(s))
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _egesz(n: Decimal) -> Decimal:
    """16851.0 → 16851 (a tárolt alak, mint a beépített beolvasóknál); a tört marad. Nem véges vagy valószínűtlenül
    nagy/kicsi szám (pl. „Infinity”, „1e999999”): hiba – egy számlán ilyen nincs."""
    if not n.is_finite() or abs(n.adjusted()) > 12:
        if n.is_finite() and n == 0:
            return Decimal(0)
        raise ValueError("valószínűtlen szám")
    return Decimal(int(n)) if n == n.to_integral_value() else n


def normalizal(d: dict[str, Any]) -> dict[str, Any]:
    """Az AI (vagy a panelen javított) adat egységes, JSON-képes alakban: dátum ISO, szám float/None, szöveg."""
    def iso(x: Any) -> str | None:
        n = datum(x)
        return n.isoformat() if n else None

    def f(x: Any) -> float | None:
        n = szam(x)
        return None if n is None else float(n)

    def s(x: Any) -> str:
        return re.sub(r"\s+", " ", str(x or "")).strip()

    ki: dict[str, Any] = {
        "szolgaltato_nev": s(d.get("szolgaltato_nev")), "szolgaltato_adoszam": s(d.get("szolgaltato_adoszam")),
        "kozmu": d.get("kozmu") if d.get("kozmu") in KOZMUVEK else None,
        "sorszam": s(d.get("sorszam")), "kelte": iso(d.get("kelte")), "fizetesi_hatarido": iso(d.get("fizetesi_hatarido")),
        "tipus": d.get("tipus") if d.get("tipus") in TIPUSOK else "egyeb",
        "fizetendo": f(d.get("fizetendo")), "szamlaertek": f(d.get("szamlaertek")),
        "idoszak_tol": iso(d.get("idoszak_tol")), "idoszak_ig": iso(d.get("idoszak_ig")),
        "merok": [], "mennyisegek": [], "tetelek": [],
    }
    for m in d.get("merok") or []:
        if not isinstance(m, dict):
            continue
        sor = {"gyari_szam": s(m.get("gyari_szam")), "regiszter": s(m.get("regiszter")),
               "tol_datum": iso(m.get("tol_datum")), "tol_allas": f(m.get("tol_allas")),
               "ig_datum": iso(m.get("ig_datum")), "ig_allas": f(m.get("ig_allas")),
               "mod": m.get("mod") if m.get("mod") in MODOK else "becsult"}
        if sor["ig_allas"] is not None or sor["tol_allas"] is not None:
            ki["merok"].append(sor)
    for m in d.get("mennyisegek") or []:
        if isinstance(m, dict) and f(m.get("mennyiseg")) is not None:
            ki["mennyisegek"].append({"megnevezes": s(m.get("megnevezes")), "mennyiseg": f(m.get("mennyiseg")), "egyseg": s(m.get("egyseg"))})
    for m in d.get("tetelek") or []:
        if isinstance(m, dict) and (s(m.get("megnevezes")) or f(m.get("brutto")) is not None):
            ki["tetelek"].append({"megnevezes": s(m.get("megnevezes")), "mennyiseg": f(m.get("mennyiseg")), "egyseg": s(m.get("egyseg")),
                                  "egysegar": f(m.get("egysegar")), "brutto": f(m.get("brutto"))})
    return ki


# --- Számla ----------------------------------------------------------------------------------------------------


def _egyseg(e: str) -> str:
    e = (e or "").lower().replace("³", "3").replace(" ", "")
    return {"kwh": "kwh", "m3": "m3", "mj": "mj", "gj": "gj"}.get(e, e)


def szamlava(adat: dict[str, Any], fajl: str, tarolt: dict[str, Any] | None = None, forras: str = "ai") -> Szamla:
    """A jóváhagyott adat → Számla (rogzit() dolgozza fel, ugyanúgy, mint a beépített beolvasókét).

    A mérőszám nélküli mérősor a fiók azon a napon aktív fő mérőjéhez kerül (mint a kézi számlánál)."""
    kelte = datum(adat.get("kelte"))
    if kelte is None:
        raise ValueError("A számla kelte hiányzik vagy hibás.")
    if not adat.get("sorszam"):
        raise ValueError("A számla sorszáma hiányzik.")
    tol, ig = datum(adat.get("idoszak_tol")), datum(adat.get("idoszak_ig"))
    tipus = adat.get("tipus") if adat.get("tipus") in TIPUSOK else "egyeb"
    osszeg, ertek = szam(adat.get("fizetendo")), szam(adat.get("szamlaertek"))
    sz = Szamla(forras=forras, sorszam=str(adat["sorszam"]).strip(), kelte=kelte, osszeg=osszeg, tipus=tipus,
                idoszak=(tol, ig) if tol and ig else None, fajl=fajl, hatarido=datum(adat.get("fizetesi_hatarido")),
                szamlaertek=ertek if ertek is not None else osszeg)
    if tipus == "storno":
        sz.szamlaertek = -abs(sz.szamlaertek or Decimal(0))
        sz.osszeg = Decimal(0) if osszeg is None else osszeg
    merok = (tarolt or {}).get("merok") or []
    for m in adat.get("merok") or []:
        if m.get("regiszter") and not re.fullmatch(r"1\.8\.0|összes(en)?|", m["regiszter"].lower()):
            continue  # b1: a regiszterenkénti (pl. H-tarifás) sorok nem fő mérőállások
        lm = MODOK.get(m.get("mod"), "Becs")
        for d_k, a_k in (("tol_datum", "tol_allas"), ("ig_datum", "ig_allas")):
            nap, allas = datum(m.get(d_k)), szam(m.get(a_k))
            if nap is None or allas is None:
                continue
            gy = mero_azonosito(m.get("gyari_szam") or "") or mero_azonosito((_aktiv(merok, nap) or {}).get("gyari_szam", ""))
            sz.meroallasok.append(Meroallas(gy, nap, allas, lm))
    menny: dict[str, Decimal] = {}
    for q in adat.get("mennyisegek") or []:
        e, n, v = _egyseg(q.get("egyseg")), (q.get("megnevezes") or "").lower(), szam(q.get("mennyiseg"))
        if v is None:
            continue
        if e == "kwh":
            menny["kwh"] = menny.get("kwh", Decimal(0)) + v
        elif e == "mj":
            menny["mj"] = v
        elif e == "m3" and ("csatorna" in n or "szenny" in n):
            menny["csatorna"] = v
        elif e == "m3":
            menny.setdefault("m3", v)
    k = adat.get("kozmu")
    if "kwh" in menny and k == "villany":
        sz.elszamolt_kwh = menny["kwh"]
    if k == "gaz" and ("mj" in menny or "m3" in menny):
        sz.elszamolt_gaz = {x: menny[x] for x in ("mj", "m3") if x in menny}
    if k == "viz" and "m3" in menny:
        sz.elszamolt_viz = {"ivoviz": menny["m3"], "csatorna": menny.get("csatorna", menny["m3"]), "atalany": tipus == "resz",
                            "idoszak": [tol.isoformat(), ig.isoformat()] if tol and ig else None}
    return sz
