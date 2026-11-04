"""Kiolvasott számlaadat ellenőrzése a számla szövegéhez és a fiók adataihoz (2.3.0b1).

Az AI-kivonatra (és a 2.3.0b2-től a sablonra) fut. Mezőnként jelöl:
- „ok”: a szabálynak megfelel (pl. az érték szó szerint szerepel a számlán),
- „figy”: figyelmeztetés – ellenőrizd (pl. a tételek összege nem adja ki a számlaértéket),
- „ellentmondas”: biztosan hibás vagy nem a számláról való (pl. az érték nincs a szövegben, a mérő visszafelé
  menne) – rögzíteni csak javítás vagy kifejezett megerősítés után lehet.
A „nem ellenőrizhető” mezőnek nincs jelölése (pl. üres).

HA nélkül is futtatható (tesztek).
"""

from __future__ import annotations

import copy
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

try:
    from .ai_beolvaso import datum, szam
    from .szamla_import import _aktiv, _cel_mero, _illeszkedik
    from .szamlak import Meroallas, mero_azonosito
except ImportError:  # tesztek
    from ai_beolvaso import datum, szam
    from szamla_import import _aktiv, _cel_mero, _illeszkedik
    from szamlak import Meroallas, mero_azonosito

OK, FIGY, ELL = "ok", "figy", "ellentmondas"
# Havi fogyasztás szokásos felső határa közművenként (mért egységben) – fölötte figyelmeztetés.
HAVI_MAX = {"villany": 3000, "gaz": 1500, "viz": 60, "tavho": 30}

_SZAM_TOKEN = re.compile(r"(?<![\d,.])-?\d{1,3}(?:[  .]\d{3})+(?:,\d+)?(?![\d])|(?<![\d])-?\d+(?:[,.]\d+)?(?![\d])")


def szamok(szoveg: str) -> set[Decimal]:
    """A szöveg összes száma (mindkét olvasattal, ha a pont ezres tagolás is lehet: 20.061 → 20061 és 20,061)."""
    ki: set[Decimal] = set()
    for t in _SZAM_TOKEN.findall(szoveg or ""):
        nyers = t.replace(" ", " ")
        if re.fullmatch(r"-?\d{1,3}(?:[ .]\d{3})+(?:,\d+)?", nyers):
            ki.add(Decimal(re.sub(r"[ .]", "", nyers).replace(",", ".")))
        if re.fullmatch(r"-?\d+[,.]\d+", nyers):
            ki.add(Decimal(nyers.replace(",", ".")))
        if re.fullmatch(r"-?\d+", nyers):
            ki.add(Decimal(nyers))
    return ki | {abs(x) for x in ki}


def _tomor(s: str) -> str:
    return re.sub(r"[\s ]+", "", s or "").lower()


def datum_formak(n: date) -> list[str]:
    return [f"{n.year}.{n.month:02d}.{n.day:02d}", f"{n.year}-{n.month:02d}-{n.day:02d}", f"{n.year}/{n.month:02d}/{n.day:02d}", f"{n.day:02d}.{n.month:02d}.{n.year}"]


def _van_datum(n: date, tomor: str) -> bool:
    if any(_tomor(f) in tomor for f in datum_formak(n)):
        return True
    # „2026. október 5.” / „2026. okt. 5.”
    honapok = ["január", "február", "március", "április", "május", "június", "július", "augusztus", "szeptember",
               "október", "november", "december"]
    nev = honapok[n.month - 1]
    return bool(re.search(rf"{n.year}\.?({nev}|{nev[:3]}\.?){n.day}\.?", tomor))


def _jel(ki: dict[str, Any], mezo: str, jel: str, uzenet: str) -> None:
    """Mezőnként a legsúlyosabb jelölés marad (ellentmondás > figyelmeztetés > ok), az üzenetek gyűlnek."""
    rang = {OK: 0, FIGY: 1, ELL: 2}
    regi = ki.setdefault(mezo, {"jel": OK, "uzenet": "", "_gondok": []})
    if rang[jel] > rang[regi["jel"]]:
        regi["jel"] = jel
    if jel != OK and uzenet not in regi["_gondok"]:
        regi["_gondok"].append(uzenet)
    regi["uzenet"] = "; ".join(regi["_gondok"]) or uzenet


def ellenoriz(adat: dict[str, Any], szoveg: str, tarolt: dict[str, Any] | None = None, kozmu: str | None = None,
              szuro: set[str] | None = None) -> dict[str, Any]:
    """{mezo: {jel, uzenet}} – a mezők nevei: „sorszam”, „kelte”, …, „merok.0.ig_allas”, „tetelek.2.brutto”.
    A „_osszes” kulcs: {ellentmondas: db, figy: db}."""
    ki: dict[str, Any] = {}
    tomor, szamhalmaz = _tomor(szoveg), szamok(szoveg)
    tarolt = tarolt or {}

    def szo_szerint_szam(mezo: str, v: Any) -> None:
        n = szam(v)
        if n is None:
            return
        if n in szamhalmaz or abs(n) in szamhalmaz or (n == n.to_integral_value() and int(n) in szamhalmaz):
            _jel(ki, mezo, OK, "szerepel a számlán")
        else:
            _jel(ki, mezo, ELL, "ez a szám nem szerepel a számla szövegében")

    def szo_szerint_datum(mezo: str, v: Any) -> None:
        n = datum(v)
        if n is None:
            if v:
                _jel(ki, mezo, ELL, "nem értelmezhető dátum")
            return
        _jel(ki, mezo, OK if _van_datum(n, tomor) else ELL,
             "szerepel a számlán" if _van_datum(n, tomor) else "ez a dátum nem szerepel a számla szövegében")

    def szo_szerint_szoveg(mezo: str, v: Any) -> None:
        if v and not re.fullmatch(r"(?:KITAKART|MERO)_\d+", str(v)):
            t = _tomor(str(v))
            _jel(ki, mezo, OK if t in tomor else ELL, "szerepel a számlán" if t in tomor else "nem szerepel a számla szövegében")

    # Kötelező mezők
    for m, nev in (("sorszam", "sorszám"), ("kelte", "kelte"), ("fizetendo", "fizetendő összeg")):
        if adat.get(m) in (None, ""):
            _jel(ki, m, ELL, f"hiányzik a(z) {nev}")
    # Szó szerinti egyezés
    szo_szerint_szoveg("sorszam", adat.get("sorszam"))
    szo_szerint_szoveg("szolgaltato_nev", adat.get("szolgaltato_nev"))
    for m in ("kelte", "fizetesi_hatarido", "idoszak_tol", "idoszak_ig"):
        szo_szerint_datum(m, adat.get(m))
    for m in ("fizetendo", "szamlaertek"):
        szo_szerint_szam(m, adat.get(m))
    for i, s in enumerate(adat.get("merok") or []):
        szo_szerint_szoveg(f"merok.{i}.gyari_szam", s.get("gyari_szam"))
        for m in ("tol_datum", "ig_datum"):
            szo_szerint_datum(f"merok.{i}.{m}", s.get(m))
        for m in ("tol_allas", "ig_allas"):
            szo_szerint_szam(f"merok.{i}.{m}", s.get(m))
    for lista, mezok in (("mennyisegek", ("mennyiseg",)), ("tetelek", ("mennyiseg", "egysegar", "brutto"))):
        for i, s in enumerate(adat.get(lista) or []):
            for m in mezok:
                szo_szerint_szam(f"{lista}.{i}.{m}", s.get(m))

    # Egyediség
    if adat.get("sorszam") and adat["sorszam"] in (tarolt.get("szamlak") or {}):
        _jel(ki, "sorszam", ELL, "ez a számla már szerepel a fiókban")

    # Tételek ⇒ számlaérték, egységár × mennyiség
    tetelek = [t for t in adat.get("tetelek") or [] if szam(t.get("brutto")) is not None]
    ertek = szam(adat.get("szamlaertek")) if adat.get("szamlaertek") is not None else szam(adat.get("fizetendo"))
    if len(tetelek) >= 2 and ertek is not None:
        ossz = sum(szam(t["brutto"]) for t in tetelek)
        if abs(ossz - ertek) > len(tetelek) + 1:
            _jel(ki, "szamlaertek" if adat.get("szamlaertek") is not None else "fizetendo", FIGY,
                 f"a tételek bruttó összege {ossz:f} Ft, ez nem egyezik a számla értékével")
    for i, t in enumerate(adat.get("tetelek") or []):
        q, e, b = szam(t.get("mennyiseg")), szam(t.get("egysegar")), szam(t.get("brutto"))
        if q is not None and e is not None and b is not None and b != 0:
            szorzat = q * e
            if not any(abs(szorzat * k - b) <= max(Decimal(2), abs(b) * Decimal("0.005")) for k in (1, Decimal("1.27"), Decimal("1.18"), Decimal("1.05"))):
                _jel(ki, f"tetelek.{i}.brutto", FIGY, "az egységár × mennyiség nem adja ki a tétel értékét")
    f, sz = szam(adat.get("fizetendo")), szam(adat.get("szamlaertek"))
    if f is not None and sz is not None and f != sz and adat.get("tipus") not in ("elszamolo", "storno"):
        _jel(ki, "fizetendo", FIGY, "a fizetendő eltér a számla értékétől (levont tétel vagy túlfizetés?)")

    # Dátumok
    kelte = datum(adat.get("kelte"))
    tol, ig = datum(adat.get("idoszak_tol")), datum(adat.get("idoszak_ig"))
    hat = datum(adat.get("fizetesi_hatarido"))
    if tol and ig:
        if tol > ig:
            _jel(ki, "idoszak_ig", ELL, "az időszak vége a kezdete előtt van")
        elif (ig - tol).days > 400:
            _jel(ki, "idoszak_ig", FIGY, "szokatlanul hosszú időszak (több mint egy év)")
        if kelte and ig > kelte + timedelta(days=62):
            _jel(ki, "idoszak_ig", FIGY, "az időszak jóval a számla kelte után ér véget")
    if kelte and hat and hat < kelte:
        _jel(ki, "fizetesi_hatarido", FIGY, "a határidő a kelte előtt van")
    if kelte and (kelte > date.today() + timedelta(days=31) or kelte.year < 2000):
        _jel(ki, "kelte", ELL, "valószínűtlen kelte")

    # Mérőállások: záró ≥ induló, nem megy visszafelé a fiók korábbi leolvasásaihoz képest, a fiók mérője-e
    szuro_n = {mero_azonosito(x) for x in szuro or set() if x}
    proba = copy.deepcopy(tarolt)
    proba.setdefault("merok", [])
    ismert_merok = {mero_azonosito(m.get("gyari_szam", "")) for m in proba["merok"] + (proba.get("almero_merok") or [])} - {""}
    for i, s in enumerate(adat.get("merok") or []):
        a, b = szam(s.get("tol_allas")), szam(s.get("ig_allas"))
        da, db = datum(s.get("tol_datum")), datum(s.get("ig_datum"))
        if a is not None and b is not None and b < a:
            _jel(ki, f"merok.{i}.ig_allas", ELL, "a záró állás kisebb az indulónál")
        if da and db and db < da:
            _jel(ki, f"merok.{i}.ig_datum", ELL, "a záró dátum az induló előtt van")
        gy = mero_azonosito(s.get("gyari_szam") or "")
        if gy and ismert_merok and gy not in ismert_merok and gy not in szuro_n:
            _jel(ki, f"merok.{i}.gyari_szam", FIGY, "nem a fiók ismert mérője (mérőcsere vagy más fiók számlája?)")
        if s.get("regiszter") and not re.fullmatch(r"1\.8\.0|összes(en)?", s["regiszter"].lower()):
            continue
        for nap, allas, mezo in ((da, a, "tol_allas"), (db, b, "ig_allas")):
            if nap is None or allas is None or not proba["merok"]:
                continue
            mero = _cel_mero(proba, Meroallas(gy, nap, allas, "Dikt"), szuro_n) if gy else _aktiv(proba["merok"], nap)
            if mero is not None and mero.get("beepitve") and not _illeszkedik(mero, nap, allas):
                _jel(ki, f"merok.{i}.{mezo}", ELL, "ellentmond a fiók meglévő mérőállásainak (visszafelé menne)")
        # Nagyságrend: havi fogyasztás
        if a is not None and b is not None and da and db and (db - da).days >= 20 and kozmu in HAVI_MAX:
            havi = (b - a) / Decimal((db - da).days) * Decimal("30.4")
            if havi > HAVI_MAX[kozmu]:
                _jel(ki, f"merok.{i}.ig_allas", FIGY, f"szokatlanul nagy fogyasztás (kb. {int(havi)} / hó)")
    if adat.get("kozmu") and kozmu and adat["kozmu"] != kozmu:
        _jel(ki, "kozmu", FIGY, f"a számla szerint {adat['kozmu']}, a fiók {kozmu}")

    for v in ki.values():
        v.pop("_gondok", None)
    ki["_osszes"] = {"ellentmondas": sum(1 for v in ki.values() if v["jel"] == ELL),
                     "figy": sum(1 for v in ki.values() if v["jel"] == FIGY)}
    return ki
