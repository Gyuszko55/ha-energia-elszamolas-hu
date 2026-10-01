"""Számlák automatikus beolvasása egy mappából (pl. a Díjnet-integráció letöltési mappája).

Támogatott források (HA nélkül tesztelhető):
- MVM Next áram és földgáz: a Díjnet által letöltött `*_szamla.xml` (strukturált: mérőállások, leolvasási mód,
  havi fűtőérték, fizetendő összeg);
- DAKÖV víz: PDF (szöveg a pypdf layout-módjával), mérősoronként „<mérő> számú vízmérőn <tól>-<ig> <induló>-<záró>”;
- MOHU hulladékszállítás: XML (összeg, kelt, időszak).

Becsült („Becs”) mérőállást nem veszünk át: csak diktáltat („Dikt”) és leolvasottat („Leol”).
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

_LOGGER = logging.getLogger(__name__)
VALODI_LM = ("Dikt", "Leol")


@dataclass
class Meroallas:
    mero: str  # gyári szám (vezető nullák nélkül)
    datum: date
    allas: Decimal
    lm: str  # Dikt | Leol | Becs | ...

    @property
    def valodi(self) -> bool:
        return self.lm.startswith(VALODI_LM)

    @property
    def leolvasott(self) -> bool:
        return self.lm.startswith("Leol")


@dataclass
class Szamla:
    forras: str  # mvm_aram | mvm_gaz | dakov | mohu
    sorszam: str
    kelte: date
    osszeg: Decimal | None  # fizetendő, bruttó (negatív: visszatérítés)
    tipus: str  # resz | elszamolo | egyeb
    idoszak: tuple[date, date] | None = None
    meroallasok: list[Meroallas] = field(default_factory=list)
    futoertekek: dict[str, Decimal] = field(default_factory=dict)  # gáz: {"ÉÉÉÉ-HH": MJ/m³}
    fajl: str = ""

    @property
    def merok(self) -> set[str]:
        return {m.mero for m in self.meroallasok}


def mero_azonosito(x: str) -> str:
    """Gyári szám egységesítve: szóközök és vezető nullák nélkül (az MVM néha 00-val kezdi)."""
    return re.sub(r"\s+", "", x or "").lstrip("0")


def _d(s: str | None) -> date | None:
    m = re.search(r"(\d{4})\.\s*(\d{2})\.\s*(\d{2})", s or "")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _szam(s: str | None) -> Decimal | None:
    if s is None:
        return None
    s = s.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _tipus(nev: str) -> str:
    n = nev.lower()
    if "elszámoló" in n or "végszámla" in n:
        return "elszamolo"
    if "részszámla" in n:
        return "resz"
    return "egyeb"


# --- MVM Next (áram, gáz) – XML ----------------------------------------------------------------------


def mvm_xml(adat: bytes, fajl: str = "") -> Szamla | None:
    gyoker = ET.fromstring(adat)
    if gyoker.tag != "szamla":
        return None
    info = gyoker.find("fejlec/szamlainfo")
    if info is None:
        return None
    szolg = (info.findtext("szolgaltatas") or "").lower()
    forras = "mvm_gaz" if "földgáz" in szolg else "mvm_aram" if "villamos" in szolg else None
    if forras is None:
        return None
    osszeg = None
    for o in gyoker.iter("osszesites"):
        if (o.findtext("sor_megnevezes_szoveg") or "").strip().lower().startswith("fizetendő összeg"):
            osszeg = _szam(o.findtext("brutto_osszeg"))
    sz = Szamla(
        forras=forras,
        sorszam=(info.findtext("szlaszam") or gyoker.get("szlaszam") or "").strip(),
        kelte=_d(info.findtext("szlakelte")),
        osszeg=osszeg,
        tipus=_tipus(info.findtext("szlanev") or ""),
        idoszak=(_d(info.findtext("elsz_kezdete")), _d(info.findtext("elsz_vege"))) if info.findtext("elsz_kezdete") else None,
        fajl=fajl,
    )
    for t in gyoker.iter("tetel"):
        mero = t.findtext("mero_gyartasi_szama")
        zaro = _szam(t.findtext("zaro_meroallas"))
        vege = _d(t.findtext("elszamolasi_idoszak_vege"))
        lm = (t.findtext("lm_megnevezes") or t.findtext("lm_kod") or "").strip()
        if mero and zaro is not None and vege:
            sz.meroallasok.append(Meroallas(mero_azonosito(mero), vege, zaro, lm))
            indulo = _szam(t.findtext("indulo_meroallas"))
            kezd = _d(t.findtext("elszamolasi_idoszak_kezdete"))
            if indulo is not None and kezd and lm:
                sz.meroallasok.append(Meroallas(mero_azonosito(mero), kezd, indulo, lm))
        fe = _szam(t.findtext("futoertek"))
        kezd = _d(t.findtext("elszamolasi_idoszak_kezdete"))
        if fe and kezd:
            sz.futoertekek[f"{kezd.year:04d}-{kezd.month:02d}"] = fe
    return sz


# --- MOHU – XML ---------------------------------------------------------------------------------------


def mohu_xml(adat: bytes, fajl: str = "") -> Szamla | None:
    gyoker = ET.fromstring(adat)
    fej = gyoker.find(".//fejlec")
    if fej is None or gyoker.find(".//szlasorszam") is None:
        return None
    return Szamla(
        forras="mohu",
        sorszam=(gyoker.findtext(".//szlasorszam") or "").strip(),
        kelte=_d(gyoker.findtext(".//szladatum")),
        osszeg=_szam(gyoker.findtext(".//szla_fizetendo")),
        tipus="egyeb",
        idoszak=(_d(gyoker.findtext(".//elszam_ido_tol")), _d(gyoker.findtext(".//elszam_ido_ig"))),
        fajl=fajl,
    )


# --- DAKÖV – PDF szöveg (layout) ------------------------------------------------------------------------

_DAKOV_MERO = re.compile(
    r"(\S+) számú vízmérőn (\d{4})\.(\d{2})\.(\d{2})-(\d{4})\.(\d{2})\.(\d{2}) (\d+)-(\d+) "
)


def dakov_szoveg(szoveg: str, fajl: str = "") -> Szamla | None:
    t = re.sub(r"[ \t]+", " ", szoveg)
    if "DAKÖV" not in t and "Víziközmű-szolgáltatás" not in t:
        return None
    sorszam = re.search(r"Számla sorszáma: (\S+)", t)
    kelte = re.search(r"Számla kelte: (\d{4}\.\d{2}\.\d{2})", t)
    if not sorszam or not kelte:
        return None
    osszeg = re.search(r"Fizetendő összeg: (-?[\d ]+?) Ft", t)
    lm = re.search(r"Leolvasás módja \(LM\) jelen számlában: (\w+)", t)
    lm_s = lm.group(1) if lm else ("Becs" if "becsült fogyasztás" in t else "")
    sz = Szamla(
        forras="dakov",
        sorszam=sorszam.group(1),
        kelte=_d(kelte.group(1)),
        osszeg=_szam(osszeg.group(1)) if osszeg else None,
        tipus="elszamolo" if "elszámoló számla" in t else "resz",
        fajl=fajl,
    )
    for m in _DAKOV_MERO.finditer(t):
        mero = mero_azonosito(m.group(1))
        kezd = date(int(m.group(2)), int(m.group(3)), int(m.group(4)))
        vege = date(int(m.group(5)), int(m.group(6)), int(m.group(7)))
        sz.meroallasok.append(Meroallas(mero, kezd, Decimal(m.group(8)), lm_s))
        sz.meroallasok.append(Meroallas(mero, vege, Decimal(m.group(9)), lm_s))
    return sz


def pdf_szoveg(fajl: Path) -> str:
    from pypdf import PdfReader  # noqa: PLC0415 – csak PDF-nél kell

    return "\n".join(p.extract_text(extraction_mode="layout") for p in PdfReader(str(fajl)).pages)


# --- Mappa ---------------------------------------------------------------------------------------------


def beolvas_fajl(fajl: Path) -> Szamla | None:
    """Egy fájl → Számla (vagy None, ha nem ismert formátum)."""
    try:
        if fajl.suffix.lower() == ".xml":
            adat = fajl.read_bytes()
            return mvm_xml(adat, fajl.name) or mohu_xml(adat, fajl.name)
        if fajl.suffix.lower() == ".pdf":
            if fajl.with_suffix(".xml").exists():
                return None  # az XML-t olvassuk helyette
            return dakov_szoveg(pdf_szoveg(fajl), fajl.name)
    except Exception as err:  # noqa: BLE001 – egy hibás fájl ne állítsa meg a többit
        _LOGGER.warning("Számla nem olvasható (%s): %s", fajl, err)
    return None


def jelolt_mappak(gyoker: Path, melyseg: int = 2) -> list[str]:
    """A config mappán belüli mappák, amelyekben számla (XML vagy PDF) van – a beállító felülethez."""
    talalat: list[str] = []

    def bejar(p: Path, szint: int) -> None:
        try:
            gyerekek = [x for x in p.iterdir() if x.is_dir() and not x.name.startswith((".", "__"))]
        except OSError:
            return
        for g in gyerekek:
            if g.name in ("custom_components", "deps", "tts", "www", "node_modules", "blueprints", "themes"):
                continue
            try:
                if any(f.suffix.lower() in (".xml", ".pdf") for f in g.iterdir() if f.is_file()):
                    talalat.append(str(g.relative_to(gyoker)))
            except OSError:
                continue
            if szint < melyseg:
                bejar(g, szint + 1)

    bejar(gyoker, 1)
    return sorted(talalat)


def uj_fajlok(mappa: Path, ismert: set[str]) -> list[Path]:
    if not mappa.is_dir():
        return []
    return sorted(f for f in mappa.iterdir() if f.suffix.lower() in (".xml", ".pdf") and f.name not in ismert)
