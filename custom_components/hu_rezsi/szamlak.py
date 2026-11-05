"""Számlák automatikus beolvasása egy mappából (pl. a Díjnet-integráció letöltési mappája).

Támogatott források (HA nélkül tesztelhető):
- MVM Next áram és földgáz: a Díjnet által letöltött `*_szamla.xml` (strukturált: mérőállások, leolvasási mód,
  havi fűtőérték, fizetendő összeg);
- DAKÖV víz: PDF (szöveg a pypdf layout-módjával), mérősoronként „<mérő> számú vízmérőn <tól>-<ig> <induló>-<záró>”;
- MVM Next áram: PDF is (ha nincs mellette XML): a számla bruttó értéke, időszak, mérési pont, diktált/leolvasott
  állások; a stornó számla összeg nélkül kerül be, állás nélkül;
- MOHU hulladékszállítás: XML (összeg, kelt, időszak).

Becsült („Becs”) mérőállást nem veszünk át: csak diktáltat („Dikt”) és leolvasottat („Leol”).
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

_LOGGER = logging.getLogger(__name__)
VALODI_LM = ("Dikt", "Leol")
PDF_OLVASO_VERZIO = 6  # 2: MVM áram-PDF; 3: MVM végszámla; 4: Telekom PDF, üres oldal; 5: kelte nélküli, ISO-dátumos, MVM gáz-stornó; 6: beépített beolvasók (Mezőföldvíz) (a fel nem ismert fájlokat újrapróbálja)


@dataclass
class Meroallas:
    mero: str  # gyári szám (vezető nullák nélkül)
    datum: date
    allas: Decimal
    lm: str  # Dikt | Leol | Becs | ...
    csatorna: str = "vetelezes"  # H-tarifa regiszter: h_teli (1.81), h_nyari (1.82)

    @property
    def valodi(self) -> bool:
        return self.lm.startswith(VALODI_LM)

    @property
    def leolvasott(self) -> bool:
        return self.lm.startswith("Leol")


@dataclass
class Szamla:
    forras: str  # mvm_aram | mvm_gaz | dakov | alfoldviz | mohu | hvsz
    sorszam: str
    kelte: date
    osszeg: Decimal | None  # fizetendő, bruttó (negatív: visszatérítés)
    tipus: str  # resz | elszamolo | egyeb
    idoszak: tuple[date, date] | None = None
    meroallasok: list[Meroallas] = field(default_factory=list)
    # H-tarifa: a két regiszter (1.82 nyári, 1.81 téli) induló és záró állása – a fő csatorna (összes) mellett.
    regiszter_allasok: list[Meroallas] = field(default_factory=list)
    futoertekek: dict[str, Decimal] = field(default_factory=dict)  # gáz: {"ÉÉÉÉ-HH": MJ/m³}
    korrekciok: dict[str, Decimal] = field(default_factory=dict)  # gáz: {"ÉÉÉÉ-HH": korrekciós tényező}
    fajl: str = ""
    meresi_pont: str = ""  # MVM PDF: „HU000…” – a mérőszám nélküli részszámla ezzel köthető a mérőhöz
    kapcsolt_merok: set[str] = field(default_factory=set)
    atalany_mennyiseg: Decimal | None = None  # MVM: „A következő részszámla becsült mennyisége” (kWh/hó)
    diktalasi_ablak: tuple[int, int] | None = None  # MVM: „Következő diktálási időszak: Minden hónap 08-14 között”
    arszabas: str | None = None  # MVM villany: „A1” / „H” (a fiók díjszabásával egyeztetve válogat)
    # MVM villany: az időszakon BELÜLI valódi leolvasás, ahol a mérősor kettéválik (pl. „04.11–07.31” + „07.31–08.08”):
    # itt fordul az elszámolási év (a keret is itt bomlik) – elszámoló leolvasásként rögzítjük.
    evhatarok: set[date] = field(default_factory=set)
    # DAKÖV: „Következő leolvasás várható időpontja” (az éves elszámolás) és „Következő diktálás / mérőállás
    # bejelentés” – (kezdete, vége); a számla tetején az „Elszámolt mennyiség” (ivóvíz, csatorna m³) és időszaka.
    kovetkezo_leolvasas: tuple[date, date] | None = None
    kovetkezo_diktalas: tuple[date, date] | None = None
    elszamolt_viz: dict[str, Any] | None = None
    elszamolt_kwh: Decimal | None = None  # MVM áram: részszámlán az „Elszámolt mennyiség”, elszámolón a mérőállásokból
    elszamolt_gaz: dict[str, Decimal] | None = None  # MVM gáz: „Elszámolt mennyiség: 3 564 MJ (103,00 m3)”
    kovetkezo_resz_m3: Decimal | None = None  # MVM gáz: „A következő részszámla becsült mennyisége: 103 m3”
    # A számla saját bruttó értéke és az elszámolóban levont korábbi részszámlák (sorszám, összeg – ha a számlán
    # olvasható): az időszak teljes díja = számlaérték + levont részszámlák (a fizetendő ettől eltérhet).
    szamlaertek: Decimal | None = None
    levont_szamlak: list = field(default_factory=list)
    # MVM közös folyószámla: a bruttó számlaérték és a fizetendő közötti tételek (pl. „Túlfizetés”, „Egyéb fizetendőt
    # csökkentő tétel” – egy másik fiók jóváírásának átvezetése), és a folyószámla egyenlege a számla kibocsátásakor.
    egyeb_tetelek: list = field(default_factory=list)
    folyoszamla: Decimal | None = None
    # MVM áram: a számlán ténylegesen kiszámlázott mennyiség („Fogyasztás összesen”) – a mérősorok összegétől eltérhet.
    szamlazott_kwh: Decimal | None = None
    # H-tarifa: a számla energiadíj-tételei szerint kiszámlázott téli és nyári mennyiség ({"teli": kWh, "nyari": kWh}).
    szamlazott_idenyek: dict[str, Decimal] | None = None
    # A felhasználó adatai a számláról (a reklamáció-tervezethez): azonosító, név, felhasználási hely, mérési pont.
    ugyfel: dict[str, str] = field(default_factory=dict)
    # MVM áram: a számlarészletező tételei összesítve (az éves kimutatáshoz) – mvm_tetelek.
    tetelek: dict[str, Any] | None = None
    # Fizetési határidő (MVM: XML „fizhatarido”, PDF „Fizetési határidő:”) – a pénzügyi teljesítéshez.
    hatarido: date | None = None
    # Távhő (HVSZ): a számlázott melegvíz (m³), a hődíj (GJ – átalány vagy korrekció) és a fűtési alapdíj hónapjai.
    elszamolt_tavho: dict[str, Any] | None = None
    # A számlán megadott fizetési mód (pl. „Beszed.megbízás”, „Kompenzálás”) – beszedésnél a határidőn fizetettnek vesszük.
    fizetesi_mod: str = ""
    # Stornó: az érvénytelenített (eredeti) számla sorszáma (MVM PDF: „Sztornózott számla sorszáma:”).
    sztornozott: str = ""

    @property
    def merok(self) -> set[str]:
        return {m.mero for m in self.meroallasok} | self.kapcsolt_merok


def mero_azonosito(x: str) -> str:
    """Gyári szám egységesítve: szóközök és vezető nullák nélkül (az MVM néha 00-val kezdi)."""
    return re.sub(r"\s+", "", x or "").lstrip("0")


def _d(s: str | None) -> date | None:
    """„ÉÉÉÉ.HH.NN” (a pont után szóközzel is) vagy ISO „ÉÉÉÉ-HH-NN” (pl. Telekom InvDate); érvénytelen dátum: None."""
    m = re.search(r"(\d{4})([.-])\s*(\d{2})\2\s*(\d{2})", s or "")
    try:
        return date(int(m.group(1)), int(m.group(3)), int(m.group(4))) if m else None
    except ValueError:
        return None


def sztornozottak(szamlak: Any) -> set[str]:
    """A stornó számlákkal érvénytelenített számlák sorszámai (a stornón: sztornozott)."""
    return {x["sztornozott"] for x in szamlak if x.get("tipus") == "storno" and x.get("sztornozott")}


def sztornozott_kulcsok(szamlak: dict[str, dict[str, Any]]) -> set[str]:
    """A tárolt számlák (sorszám → adatok) közül a stornóval érvénytelenítettek sorszámai (vezető nullák nélkül egyeztetve)."""
    s = {str(x).lstrip("0") for x in sztornozottak(szamlak.values())}
    return {k for k in szamlak if str(k).lstrip("0") in s} if s else set()


def ervenytelenek(szamlak: dict[str, dict[str, Any]]) -> set[str]:
    """A nem számítandó számlák sorszámai: a stornók és az általuk érvénytelenített (sztornózott) eredetiek – az
    összegekből, befizetésekből, lejárt-jelzésből, teljes díjból és az éves kimutatásból is kimaradnak."""
    return sztornozott_kulcsok(szamlak) | {k for k, x in szamlak.items() if x.get("tipus") == "storno"}


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
    if "stornó" in n or "storno" in n or "sztornó" in n:
        return "storno"
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
    osszeg = szamlaertek = None
    levont: list = []
    egyeb: list = []  # a bruttó számlaérték és a fizetendő közötti tételek (pl. „Támogatás, túlfizetés: -8835”)
    for o in gyoker.iter("osszesites"):
        eredeti = (o.findtext("sor_megnevezes_szoveg") or "").strip()
        nev = eredeti.lower()
        if nev.startswith("fizetendő összeg"):
            osszeg = _szam(o.findtext("brutto_osszeg"))
        elif nev.startswith("bruttó számlaérték"):
            szamlaertek = _szam(o.findtext("brutto_osszeg"))
        elif o.findtext("reszszamla_szama"):
            levont.append((o.findtext("reszszamla_szama").strip(), _szam(o.findtext("reszszamla_osszege"))))
        elif szamlaertek is not None and osszeg is None and re.match(r"[^\W\d]", eredeti) and not nev.startswith(("kerekítés", "összesen")):
            if (v := _szam(o.findtext("brutto_osszeg"))):
                egyeb.append((eredeti.rstrip(": "), v))
    kelte = _d(info.findtext("szlakelte"))
    if kelte is None:
        return None  # kelte nélkül nem rögzíthető (fel nem ismert fájlként jelezzük)
    sz = Szamla(
        forras=forras,
        sorszam=(info.findtext("szlaszam") or gyoker.get("szlaszam") or "").strip(),
        kelte=kelte,
        osszeg=osszeg,
        tipus=_tipus(info.findtext("szlanev") or ""),
        idoszak=(_d(info.findtext("elsz_kezdete")), _d(info.findtext("elsz_vege"))) if info.findtext("elsz_kezdete") else None,
        fajl=fajl,
        szamlaertek=szamlaertek,
        levont_szamlak=levont,
        hatarido=_d(info.findtext("fizhatarido")) if info.findtext("fizhatarido") else None,
        fizetesi_mod=(info.findtext("fizmod") or "").strip(),
    )
    if sz.tipus == "storno":
        sz.sztornozott = _xml_sztornozott(gyoker)
    if forras == "mvm_gaz" and sz.tipus == "resz" and egyeb:
        # Gáz-részszámlán az MVM a korábbi elszámoló jóváírását „Támogatás, túlfizetés” sorban számítja be: a számla
        # saját értéke a bruttó számlaérték, a beszámítás áthozott egyenleg. (Elszámolón a fizetendő a követelés.)
        sz.egyeb_tetelek = egyeb
    if forras == "mvm_aram":
        for t in gyoker.iter("tetel_megnevezese_szoveg"):
            m = re.search(r'ESZ\s+Lakoss\w*\s+"?(A1|H|B)\b', t.text or "")
            if m:
                sz.arszabas = m.group(1)
                break
    h_sorok = []
    for t in gyoker.iter("tetel"):
        mero = t.findtext("mero_gyartasi_szama")
        zaro = _szam(t.findtext("zaro_meroallas"))
        if sz.arszabas == "H" and mero and zaro is not None and _szam(t.findtext("indulo_meroallas")) is not None \
                and t.findtext("elszamolasi_idoszak_kezdete") and t.findtext("elszamolasi_idoszak_vege"):
            h_sorok.append((mero_azonosito(mero), _d(t.findtext("elszamolasi_idoszak_kezdete")), _d(t.findtext("elszamolasi_idoszak_vege")),
                            _szam(t.findtext("indulo_meroallas")), zaro, (t.findtext("lm_megnevezes") or t.findtext("lm_kod") or "").strip()))
        vege = _d(t.findtext("elszamolasi_idoszak_vege"))
        lm = (t.findtext("lm_megnevezes") or t.findtext("lm_kod") or "").strip()
        if mero and sz.tipus == "storno":
            sz.kapcsolt_merok.add(mero_azonosito(mero))  # a stornó állásai nem leolvasások, csak a mérőhöz köt
        elif mero and zaro is not None and vege:
            sz.meroallasok.append(Meroallas(mero_azonosito(mero), vege, zaro, lm))
            indulo = _szam(t.findtext("indulo_meroallas"))
            kezd = _d(t.findtext("elszamolasi_idoszak_kezdete"))
            if indulo is not None and kezd and lm:
                sz.meroallasok.append(Meroallas(mero_azonosito(mero), kezd, indulo, lm))
        fe = _szam(t.findtext("futoertek"))
        korr = _szam(t.findtext("korrekcios_tenyezo"))
        kezd = _d(t.findtext("elszamolasi_idoszak_kezdete"))
        vege = _d(t.findtext("elszamolasi_idoszak_vege")) or kezd
        if fe and kezd:
            # A tétel időszakának minden hónapjára (az éves elszámoló egy tétele több hónapot is lefed).
            for ho in _honapok(kezd, vege):
                sz.futoertekek[ho] = fe
                if korr:
                    sz.korrekciok[ho] = korr
    if h_sorok and sz.tipus != "storno":
        sz.regiszter_allasok = h_regiszterek(h_sorok)
    return sz


def storno_hivatkozas(szoveg: str) -> str:
    """Stornó szövegéből a sztornózott számla sorszáma (MVM: „Stornózott számla száma: …”), vagy üres."""
    m = re.search(r"S(?:z)?tornózott számla (?:sor)?száma:?\s*(\d+)", szoveg or "")
    return m.group(1) if m else ""


def _xml_sztornozott(gyoker: ET.Element) -> str:
    """MVM stornó XML: az érvénytelenített számla sorszáma, ha szerepel benne – egy „sztorn”/„storno”/„eredeti”/
    „hivatkoz”/„helyesb” nevű, számlaszámot tartalmazó mező, vagy a szövegben „Sztornózott számla sorszáma: …”.
    Ha nincs, üres: a rögzítés az azonos fiókú, azonos időszakú, ellentétes összegű korábbi számlához párosítja."""
    for e in gyoker.iter():
        tag = e.tag.split("}")[-1].lower()
        if re.search(r"sztorn|storno|eredeti|hivatkoz|helyesb", tag) and re.search(r"sz(?:a|á)m|szla|sorsz", tag):
            if (v := (e.text or "").strip()) and re.fullmatch(r"[\w/-]+", v) and re.search(r"\d", v):
                return v
        if e.text and (m := re.search(r"S(?:z)?tornózott számla (?:sor)?száma:?\s*(\d+)", e.text)):
            return m.group(1)
    return ""


def _honapok(tol: date, ig: date) -> list[str]:
    """A [tol, ig] napjait érintő hónapok „ÉÉÉÉ-HH” kulcsai."""
    out, d = [], tol.replace(day=1)
    while d <= ig:
        out.append(f"{d.year:04d}-{d.month:02d}")
        d = (d + timedelta(days=32)).replace(day=1)
    return out


# --- MOHU – XML ---------------------------------------------------------------------------------------


def mohu_xml(adat: bytes, fajl: str = "") -> Szamla | None:
    gyoker = ET.fromstring(adat)
    fej = gyoker.find(".//fejlec")
    if fej is None or gyoker.find(".//szlasorszam") is None or _d(gyoker.findtext(".//szladatum")) is None:
        return None
    return Szamla(
        forras="mohu",
        sorszam=(gyoker.findtext(".//szlasorszam") or "").strip(),
        kelte=_d(gyoker.findtext(".//szladatum")),
        osszeg=_szam(gyoker.findtext(".//szla_fizetendo")),
        tipus="egyeb",
        idoszak=(_d(gyoker.findtext(".//elszam_ido_tol")), _d(gyoker.findtext(".//elszam_ido_ig"))),
        fajl=fajl,
        szamlaertek=_szam(gyoker.findtext(".//szla_fizetendo")),
        # Fizetési határidő és mód (csoportos beszedésnél a határidő napján fizetettnek vesszük) – nélküle a számla
        # kimaradna a kifizetetlenek közül.
        hatarido=_d(gyoker.findtext(".//fiz_hatarido")),
        fizetesi_mod=(gyoker.findtext(".//fiz_mod") or "").strip(),
    )


# --- Magyar Telekom – AMDOCS-XML (Díjnet: „otthoni telekom összevont”) -------------------------------------


def telekom_xml(adat: bytes, fajl: str = "") -> Szamla | None:
    """Telekom összevont számla (<Invoice><DocType>AMDOCSBILL): sorszám InvNb, kelte InvDate, fizetendő InvAmVAT
    (a számla összege, egyszeri tételekkel – kiszállás, munkadíj), határidő PaymDue, időszak a Period hónapja."""
    gyoker = ET.fromstring(adat)
    if gyoker.tag.split("}")[-1] != "Invoice" or (gyoker.findtext(".//DocType") or "").strip() != "AMDOCSBILL":
        return None
    if _d(gyoker.findtext(".//InvDate")) is None:
        return None
    per = (gyoker.findtext(".//Period") or "").strip()
    idoszak = None
    if re.fullmatch(r"\d{6}", per):
        tol = date(int(per[:4]), int(per[4:]), 1)
        idoszak = (tol, date(tol.year + (tol.month == 12), tol.month % 12 + 1, 1) - timedelta(days=1))
    osszeg = _szam(gyoker.findtext(".//InvAmVAT"))
    return Szamla(
        forras="telekom",
        sorszam=(gyoker.findtext(".//InvNb") or "").strip(),
        kelte=_d(gyoker.findtext(".//InvDate")),
        osszeg=osszeg,
        tipus="egyeb",
        idoszak=idoszak,
        fajl=fajl,
        szamlaertek=osszeg,
        hatarido=_d(gyoker.findtext(".//PaymDue")) if gyoker.findtext(".//PaymDue") else None,
        fizetesi_mod=(gyoker.findtext(".//PayModeName") or "").strip(),
    )


def telekom_pdf(szoveg: str, fajl: str = "") -> Szamla | None:
    """Telekom összevont számla PDF-ből (pdftotext -layout), ha a Díjnet-XML-pár hiányzik. Ugyanazok a mezők, mint
    az XML-ből: sorszám, kelte, a számla bruttó összege („Jelenlegi számla összesen … Bruttó összeg”), határidő
    („Beérkezési határidő”), elszámolási időszak, fizetési mód. A pdftotext az ő/ű betűt õ/û-nek is adhatja."""
    if "Magyar Telekom Nyrt." not in szoveg or not (m_sz := re.search(r"Számla sorszám\s+(\d{10,})", szoveg)):
        return None
    ft = lambda x: Decimal(x.replace(".", "").replace(",", "."))  # noqa: E731 – „18.439,00” → 18439.00
    m_k = re.search(r"Számla kelte\s+(\d{4}\.\d{2}\.\d{2})", szoveg)
    m_o = (re.search(r"Jelenlegi számla összesen.*?Bruttó összeg\s+(-?[\d.]+,\d{2})\s*Ft", szoveg)
           or re.search(r"A szolgáltatások fizetend[őõ] összege\*?\s+(-?[\d.]+(?:,\d{2})?)\s*Ft", szoveg))
    if not m_k or not m_o:
        return None
    m_i = re.search(r"Elszámolási id[őõ]szak\s+(\d{4}\.\d{2}\.\d{2})\.?\s*-\s*(\d{4}\.\d{2}\.\d{2})", szoveg)
    m_h = re.search(r"Beérkezési határid[őõ]\s+(\d{4}\.\d{2}\.\d{2})", szoveg)
    m_f = re.search(r"Fizetés módja\s+(\S.*?)\s*$", szoveg, re.M)
    osszeg = ft(m_o.group(1))
    return Szamla(
        forras="telekom",
        sorszam=m_sz.group(1),
        kelte=_d(m_k.group(1)),
        osszeg=osszeg,
        tipus="egyeb",
        idoszak=(_d(m_i.group(1)), _d(m_i.group(2))) if m_i else None,
        fajl=fajl,
        szamlaertek=osszeg,
        hatarido=_d(m_h.group(1)) if m_h else None,
        fizetesi_mod=m_f.group(1).replace("õ", "ő").replace("û", "ű") if m_f else "",
    )


# --- One Magyarország (volt DIGI) – EcoSoftWare PDF-számla ---------------------------------------------------


def one_pdf(szoveg: str, fajl: str = "") -> Szamla | None:
    """One Magyarország Zrt. (a DIGI jogutódja) internet/TV/telefon számlája PDF-ből (EcoSoftWare). A fejléc értéksora
    „Szerződésszám [Teljesítés] Számla kelte  Fizetési határidő  Fizetési mód  Számla száma (ÉÉÉÉ/nnnnnnnn)” – a pypdf
    a teljesítés dátumát külön sorba teszi, ezért az utolsó két dátum a kelte és a határidő; a fizetendő a
    „Fizetendő:” sorban, az időszak a tételsorokban („2026/08/01 - 2026/08/31”)."""
    if "One Magyarország Zrt." not in szoveg:
        return None
    datum = r"\d{4}\. ?\d{2}\. ?\d{2}"
    m = re.search(rf"^\s*\d{{6,}}((?:\s+{datum}){{2,3}})\s+(\S.*?)\s+(\d{{4}}/\d{{6,}})\s*$", szoveg, re.M)
    m_o = re.search(r"Fizetendő:\s+(-?\d{1,3}(?: \d{3})*,\d{2})", szoveg)
    if not m or not m_o:
        return None
    kelte, hatarido = (_d(x) for x in re.findall(datum, m.group(1))[-2:])
    if kelte is None:
        return None
    idok = re.findall(r"(\d{4})/(\d{2})/(\d{2})\s*-\s*(\d{4})/(\d{2})/(\d{2})", szoveg)
    idoszak = None
    if idok:
        idoszak = (min(date(int(a), int(b), int(c)) for a, b, c, *_ in idok),
                   max(date(int(d), int(e), int(f)) for *_, d, e, f in idok))
    osszeg = Decimal(m_o.group(1).replace(" ", "").replace(",", "."))
    return Szamla(
        forras="one",
        sorszam=m.group(3),
        kelte=kelte,
        osszeg=osszeg,
        tipus="egyeb",
        idoszak=idoszak,
        fajl=fajl,
        szamlaertek=osszeg,
        hatarido=hatarido,
        fizetesi_mod=m.group(2).strip().capitalize(),
    )


# --- Távhő: HVSZ Zrt. – APEH-XML (http://www.apeh.hu/2005/szamla) ----------------------------------------

_APEH = "{http://www.apeh.hu/2005/szamla}"
_IDOSZAK = re.compile(r"(\d{4}\.\d{2}\.\d{2})-(\d{4}\.\d{2}\.\d{2})")


def hvsz_xml(adat: bytes, fajl: str = "") -> Szamla | None:
    """HVSZ távhőszámla: tételek L_FUT_AL (fűtési alapdíj, lm³), L_FUT_MO (hődíj, GJ), L_HMV_AL (melegvíz-alapdíj),
    L_HMV_MO (melegvíz, m³), L_CSA_MO (csatornahasználat), „hődíj korrekció” (a fűtési idény utáni elszámolás)."""
    gyoker = ET.fromstring(adat)
    if gyoker.tag != f"{_APEH}szamla":
        return None
    elado = gyoker.findtext(f"{_APEH}fejlec/{_APEH}elado/{_APEH}nev") or ""
    if "Vagyonkezel" not in elado or "vásárhely" not in elado:
        return None
    info = gyoker.find(f"{_APEH}fejlec/{_APEH}szamlainfo")
    if info is None:
        return None
    iso = lambda x: date.fromisoformat(x.strip()) if x and x.strip() else None  # noqa: E731
    tetelek = [{k: (t.findtext(f"{_APEH}{k}") or "").strip() for k in ("termeknev", "menny", "mennyegys", "nettoegysegar", "bruttoar")}
               for t in gyoker.iter(f"{_APEH}tetel")]
    hmv = sum((Decimal(t["menny"]) for t in tetelek if "(L_HMV_MO)" in t["termeknev"]), Decimal(0))
    gj = sum((Decimal(t["menny"]) for t in tetelek if "(L_FUT_MO)" in t["termeknev"]), Decimal(0))
    korr = [t for t in tetelek if "korrekci" in t["termeknev"].lower()]
    napok = [(_d(m.group(1)), _d(m.group(2))) for t in tetelek for m in [_IDOSZAK.search(t["termeknev"])] if m]
    brutto = _szam(gyoker.findtext(f"{_APEH}osszesites/{_APEH}vegosszeg/{_APEH}bruttoarossz"))
    if brutto is not None:
        brutto = brutto.quantize(Decimal(1))
    vevo = gyoker.find(f"{_APEH}fejlec/{_APEH}vevo")
    if iso(info.findtext(f"{_APEH}kialldatum")) is None:
        return None
    sz = Szamla(
        forras="hvsz", sorszam=(info.findtext(f"{_APEH}sorszam") or "").strip(), kelte=iso(info.findtext(f"{_APEH}kialldatum")),
        osszeg=brutto, tipus="elszamolo" if korr else "resz", fajl=fajl, szamlaertek=brutto,
        idoszak=(min(a for a, _ in napok), max(b for _, b in napok)) if napok else None,
        hatarido=iso(info.findtext(f"{_APEH}fizhatarido")), fizetesi_mod=(info.findtext(f"{_APEH}fizmod") or "").strip(),
    )
    sz.elszamolt_tavho = {
        "melegviz": hmv, "gj": gj,
        "alapdij": any("(L_FUT_AL)" in t["termeknev"] for t in tetelek),
        **({"korrekcio_gj": sum((Decimal(t["menny"]) for t in korr), Decimal(0)),
            "korrekcio_ft": sum((Decimal(t["bruttoar"]) for t in korr), Decimal(0))} if korr else {}),
    }
    if vevo is not None:
        cim = vevo.find(f"{_APEH}cim")
        hely = " ".join(x for x in ((cim.findtext(f"{_APEH}irszam") or ""), (cim.findtext(f"{_APEH}telepules") or ""),
                                    (cim.findtext(f"{_APEH}kozternev") or "")) if x.strip()) if cim is not None else ""
        javit = lambda x: x.replace("û", "ű").replace("õ", "ő").replace("Û", "Ű").replace("Õ", "Ő").strip()  # noqa: E731 – Latin-2 maradvány
        sz.ugyfel = {k: v for k, v in {"nev": javit(vevo.findtext(f"{_APEH}nev") or ""), "hely": javit(hely)}.items() if v}
    return sz


def hvsz_pdf(sz: Szamla, szoveg: str) -> None:
    """HVSZ: a PDF-párból a folyószámla egyenlege a számla kibocsátásakor, a melegvízóra állásai és az elszámoló
    (hődíj-korrekció) teljes időszaka – az XML-ben a korrekciós sorok dátum nélküliek, ott csak a havi melegvíz időszaka látszik."""
    folyo = re.search(r"folyószámla-egyenlege a számla kibocsátásakor\s+(" + _SZAM + r")\s*Ft", szoveg)
    if folyo:
        sz.folyoszamla = _ezres(folyo.group(1))
    # „79407642 mérőóra fogyasztása 2026.08.01 - 2026.08.31 között: Nyitó óra állás:26; Záró óra állás:27” – a melegvízóra
    # havi állásai (a HVSZ havonta diktáltatja / olvassa; elszámoló leolvasásnak nem számít).
    for m in re.finditer(r"(\d+) mérőóra fogyasztása (\d{4})\.(\d{2})\.(\d{2}) - (\d{4})\.(\d{2})\.(\d{2}) között: "
                         r"Nyitó óra állás:\s*(\d+(?:[.,]\d+)?); Záró óra állás:\s*(\d+(?:[.,]\d+)?)", szoveg):
        mero = mero_azonosito(m.group(1))
        sz.meroallasok += [Meroallas(mero, date(*map(int, m.group(2, 3, 4))), Decimal(m.group(8).replace(",", ".")), "Dikt"),
                           Meroallas(mero, date(*map(int, m.group(5, 6, 7))), Decimal(m.group(9).replace(",", ".")), "Dikt")]
    elsz = re.search(r"Elszámolt időszak:\s*(\d{4})\.(\d{2})\.(\d{2})\s*-\s*(\d{4})\.(\d{2})\.(\d{2})", szoveg)
    if elsz and sz.tipus == "elszamolo":
        tol = date(*map(int, elsz.group(1, 2, 3)))
        ig = date(*map(int, elsz.group(4, 5, 6)))
        sz.idoszak = (min(tol, sz.idoszak[0]), max(ig, sz.idoszak[1])) if sz.idoszak else (tol, ig)


# --- DAKÖV – PDF szöveg (layout) ------------------------------------------------------------------------

_DAKOV_MERO = re.compile(
    r"(\S+) számú vízmérőn (\d{4})\.(\d{2})\.(\d{2})-(\d{4})\.(\d{2})\.(\d{2}) (\d+)-(\d+) "
)


_DAKOV_IDOPONT = re.compile(
    r"Következő (leolvasás várható időpontja|diktálás várható időpontja|mérőállás bejelentés időpontja):\s*"
    r"(\d{4}\.\d{2}\.\d{2})\s*-\s*(\d{4}\.\d{2}\.\d{2})"
)


def dakov_idopontok(t: str) -> dict[str, tuple[date, date]]:
    """A számla aljáról (layout-szöveg) a következő leolvasás (éves elszámolás) és diktálás időszaka."""
    out: dict[str, tuple[date, date]] = {}
    for m in _DAKOV_IDOPONT.finditer(t):
        out["leolvasas" if m.group(1).startswith("leolvasás") else "diktalas"] = (_d(m.group(2)), _d(m.group(3)))
    return out


def dakov_levont(t: str) -> list:
    """DAKÖV elszámoló: a „Részszámlákban elszámolt …” (negatív) tételsorok bruttó díjának összege, egy tételben."""
    ossz = Decimal(0)
    for sor in t.splitlines():
        if "Részszámlákban" in sor and (m := re.findall(r"-?\d[\d ]*,\d{2}", sor)):
            ossz += abs(Decimal(m[-1].replace(" ", "").replace(",", ".")))
    return [("részszámlákban elszámolt tételek", ossz)] if ossz else []


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
    idoszak = re.search(r"Elszámolt időszak: (\d{4}\.\d{2}\.\d{2})-(\d{4}\.\d{2}\.\d{2})", t)
    lm_s = lm.group(1) if lm else ("Becs" if "becsült fogyasztás" in t else "")
    sz = Szamla(
        forras="dakov",
        sorszam=sorszam.group(1),
        kelte=_d(kelte.group(1)),
        osszeg=_szam(osszeg.group(1)) if osszeg else None,
        tipus="elszamolo" if "elszámoló számla" in t else "resz",
        idoszak=(_d(idoszak.group(1)), _d(idoszak.group(2))) if idoszak else None,
        fajl=fajl,
        szamlaertek=_szam(ertek.group(1)) if (ertek := re.search(r"Bruttó számlaérték\s*(-?[\d ]+?)\s*$", t, re.M)) else None,
        levont_szamlak=dakov_levont(t),
        hatarido=fizetesi_hatarido(t),
    )
    # „A nyilvántartás szerint a folyószámla egyenlege a számla kibocsátásakor 11 521 Ft.” – ebből a befizetések
    # visszafejthetők (a DAKÖV a jóváírást a következő befizetésnél számítja be, a számlán nem).
    if folyo := re.search(r"egyenlege a számla kibocsátásakor (-?[\d ]+?) Ft", t):
        sz.folyoszamla = _szam(folyo.group(1))
    for m in _DAKOV_MERO.finditer(t):
        mero = mero_azonosito(m.group(1))
        kezd = date(int(m.group(2)), int(m.group(3)), int(m.group(4)))
        vege = date(int(m.group(5)), int(m.group(6)), int(m.group(7)))
        sz.meroallasok.append(Meroallas(mero, kezd, Decimal(m.group(8)), lm_s))
        sz.meroallasok.append(Meroallas(mero, vege, Decimal(m.group(9)), lm_s))
    ido = dakov_idopontok(t)
    sz.kovetkezo_leolvasas, sz.kovetkezo_diktalas = ido.get("leolvasas"), ido.get("diktalas")
    menny = re.search(r"Elszámolt mennyiség: Ivóvíz (-?\d+) m3.*?Elszámolt mennyiség: Csatorna (-?\d+) m3", t, re.S)
    if menny:
        ido = re.search(r"Elszámol(?:t|ási) időszak: (\d{4}\.\d{2}\.\d{2})-(\d{4}\.\d{2}\.\d{2})", t)
        sz.elszamolt_viz = {
            "ivoviz": Decimal(menny.group(1)), "csatorna": Decimal(menny.group(2)), "atalany": "átalánydíj" in t,
            "idoszak": [_d(ido.group(1)).isoformat(), _d(ido.group(2)).isoformat()] if ido else None,
        }
    return sz


# --- ALFÖLDVÍZ Zrt. (víz, csatorna) – PDF szöveg ---------------------------------------------------------

_DATUM = r"(\d{4}[.-]\d{2}[.-]\d{2})"
_ALFOLDVIZ_MERO = re.compile(
    r"(\S+) számú vízmérőn mért ivóvíz\s+" + _DATUM + r"-\s+(\d+)-(\d+)\s+[^\n]*\n\s*fogyasztással arányos díj\s+" + _DATUM
)
# „Fogyasztás megállapításának módja” (részszámla) → a DAKÖV-féle LM-kód.
_ALFOLDVIZ_MOD = {"kalkulált": "Becs", "becsült": "Becs", "diktált": "Dikt", "bejelentett": "Dikt", "leolvasott": "Leol"}


def _iso(s: str) -> date:
    return date.fromisoformat(s.replace(".", "-"))


def alfoldviz_levont(t: str) -> list:
    """Elszámoló: „Az elszámoló számlában elszámolt részszámlák sorszáma és a számla végösszege” – (sorszám, összeg)."""
    i = t.find("elszámolt részszámlák sorszáma")
    if i < 0:
        return []
    out = []
    for sor in t[i:].splitlines()[1:]:
        if m := re.match(r"^\s*(\d+LV\d{2})\s+(-?\d[\d ]*)\s*$", sor):
            out.append((m.group(1), Decimal(m.group(2).replace(" ", ""))))
        elif out and sor.strip():
            break
    return out


def alfoldviz_szoveg(szoveg: str, fajl: str = "") -> Szamla | None:
    """ALFÖLDVÍZ Zrt. számla (layout-szöveg). Részszámla: havi / összevont, „kalkulált” (átalány, 1 m³/hó) vagy
    diktált mennyiséggel; elszámoló: az éves leolvasás (LM: Leol), a részszámlák levonásával."""
    if "ALFÖLDVÍZ" not in szoveg:
        return None
    t = re.sub(r"[ \t]+", " ", szoveg)
    sorszam = re.search(r"Számla sorszáma: (\S+)", t)
    kelte = re.search(r"Számla kelte: " + _DATUM, t)
    if not sorszam or not kelte:
        return None
    elszamolo = "elszámoló számla" in t
    osszeg = re.search(r"Fizetendő összeg: (-?[\d ]+?) Ft", t)
    ertek = re.search(r"Bruttó számlaérték összesen\*?: (-?[\d ]+?)\s*$", t, re.M)
    hatarido = re.search(r"Fizetési határidő: " + _DATUM, t)
    lm = re.search(r"Leolvasás módja \(LM\) jelen számlában: (\w+)", t)
    mod = re.search(r"Fogyasztás megállapításának módja: (\w+)", t)
    lm_s = lm.group(1) if lm else _ALFOLDVIZ_MOD.get(mod.group(1).lower(), "Becs") if mod else ("Leol" if elszamolo else "Becs")
    sz = Szamla(
        forras="alfoldviz", sorszam=sorszam.group(1), kelte=_iso(kelte.group(1)),
        osszeg=_szam(osszeg.group(1)) if osszeg else None, tipus="elszamolo" if elszamolo else "resz", fajl=fajl,
        szamlaertek=_szam(ertek.group(1)) if ertek else None, levont_szamlak=alfoldviz_levont(szoveg),
        hatarido=_iso(hatarido.group(1)) if hatarido else None,
    )
    # A számlaérték és a fizetendő közti tétel (pl. a korábbi túlfizetés beszámítása az elszámolón).
    if m := re.search(r"Figyelembe vett hátralék/túlfizetés (-?[\d ]+?)\s*$", t, re.M):
        sz.egyeb_tetelek = [("figyelembe vett hátralék/túlfizetés", _szam(m.group(1)))]
    if idoszak := re.search(r"Elszámolt időszak: " + _DATUM + "-" + _DATUM, t):
        sz.idoszak = (_iso(idoszak.group(1)), _iso(idoszak.group(2)))
    for m in _ALFOLDVIZ_MERO.finditer(t):
        mero, kezd, vege = mero_azonosito(m.group(1)), _iso(m.group(2)), _iso(m.group(5))
        sz.meroallasok += [Meroallas(mero, kezd, Decimal(m.group(3)), lm_s), Meroallas(mero, vege, Decimal(m.group(4)), lm_s)]
        if sz.idoszak is None:  # elszámoló: az időszak a mérősorból
            sz.idoszak = (kezd, vege)
    ido = dakov_idopontok(t)
    sz.kovetkezo_leolvasas, sz.kovetkezo_diktalas = ido.get("leolvasas"), ido.get("diktalas")
    if re.search(r"bejelentésre minden hónap 10-e és 15-e között", t):
        sz.diktalasi_ablak = (10, 15)
    if menny := re.search(r"Elszámolt mennyiség: ?Ivóvíz (-?\d+) m3, Szennyvíz (-?\d+) m3", t):
        sz.elszamolt_viz = {
            "ivoviz": Decimal(menny.group(1)), "csatorna": Decimal(menny.group(2)), "atalany": lm_s == "Becs",
            "idoszak": [sz.idoszak[0].isoformat(), sz.idoszak[1].isoformat()] if sz.idoszak else None,
        }
    ugyfel = {
        "nev": (m.group(1).strip() if (m := re.search(r"Felhasználó neve:\s+(.+?)(?:\s{2,}|$)", szoveg, re.M)) else ""),
        "azonosito": (m.group(1) if (m := re.search(r"Vevő \(fizető\) azonosító száma: (\d+)", t)) else ""),
        "hely": (m.group(1).strip() if (m := re.search(r"Felhasználási hely címe: (.+?)\s*$", t, re.M)) else ""),
        "mero": next(iter(sz.merok), ""),
    }
    sz.ugyfel = {k: v for k, v in ugyfel.items() if v}
    return sz


# --- MVM Next áram – PDF szöveg ------------------------------------------------------------------------

# Szám: „20.061” (MVM-nyomtató), „2 930” (végszámla) vagy tagolás nélkül.
_SZAM = r"-?(?:0|[1-9]\d{0,2}(?:[. ]\d{3})+|[1-9]\d*)"
# A gyári szám általában 16 jegyű (a végszámlán vezető nullákkal 18), de rövidebb is előfordul (pl. 15 jegyű H-mérő): 8–18.
_MVM_SOR = re.compile(r"^\s*(\d{8,18})\s*(\d{4}\.\d{2}\.\d{2})\s*-\s*(\d{4}\.\d{2}\.\d{2})\s*([\d.\s]+?)\s*(Dikt|Leol|Becs|Ell)\.?\s*(.*)$", re.M)


def _ezres(x: str) -> Decimal:
    return Decimal(x.replace(".", "").replace(" ", ""))


def _teli_nap(n: date) -> bool:
    """H-tarifa téli időszaka: okt. 15. – ápr. 15."""
    return (n.month, n.day) >= (10, 15) or (n.month, n.day) <= (4, 15)


def h_regiszterek(sorok: list[tuple[str, date, date, Decimal, Decimal, str]]) -> list[Meroallas]:
    """H-tarifás mérő sorai (mérő, kezdet, vég, induló, záró, LM) → regiszterállások. Az MVM-számlán egy mérőnek
    ugyanarra az időszakra két sora van: az első (külön jelölés nélkül) a nyári 1.82, a második a téli 1.81.
    Ellenőrzés a fogyasztással: ha egy tisztán téli időszakban csak az első sor nő (nyáriban csak a második),
    a sorrend fordított."""
    csoport: dict[tuple[str, date, date], list] = {}
    for mero, kezd, vege, indulo, zaro, lm in sorok:
        csoport.setdefault((mero, kezd, vege), []).append((indulo, zaro, lm))
    out: list[Meroallas] = []
    for (mero, kezd, vege), r in csoport.items():
        if len(r) != 2:
            continue
        f0, f1 = r[0][1] - r[0][0], r[1][1] - r[1][0]
        napok = [kezd + timedelta(days=i) for i in range((vege - kezd).days + 1)]
        teli, nyari = all(map(_teli_nap, napok)), not any(map(_teli_nap, napok))
        nev = ["h_nyari", "h_teli"]
        if (teli and f0 > 0 and f1 == 0) or (nyari and f1 > 0 and f0 == 0):
            nev.reverse()
        for (indulo, zaro, lm), c in zip(r, nev, strict=True):
            out.append(Meroallas(mero, vege, zaro, lm, c))
            out.append(Meroallas(mero, kezd, indulo, lm, c))
    return out


def _mvm_allasok(eleje: str, vege: str) -> tuple[Decimal, Decimal] | None:
    """A PDF-ben a mérősor számai összefolynak („18.82720.028Dikt1.20111.201”): induló, záró, fogyasztás,
    szorzó (1), mennyiség. A bontást a fogyasztás egyezése dönti el: záró − induló = fogyasztás."""
    eleje, vege = eleje.replace(" ", ""), re.sub(r"\s+", "", vege)
    fogy = None
    for i in range(1, len(vege) // 2 + 1):  # vége = F + "1" + F
        f = vege[:i]
        if vege == f + "1" + f and re.fullmatch(_SZAM, f):
            fogy = _ezres(f)
            break
    if fogy is None:
        return None
    for i in range(1, len(eleje)):
        a, b = eleje[:i], eleje[i:]
        if re.fullmatch(_SZAM, a) and re.fullmatch(_SZAM, b) and _ezres(b) - _ezres(a) == fogy:
            return _ezres(a), _ezres(b)
    return None


def mvm_atalany(szoveg: str) -> Decimal | None:
    """„A következő részszámla becsült mennyisége: 24 órás 293 kWh” → 293 (több tarifánál az összeg)."""
    sor = re.search(r"következő részszámla becsült mennyisége:\s*(.+)$", szoveg, re.M | re.I)
    if not sor:
        return None
    szamok = re.findall(r"(\d[\d.]*(?: \d{3})*)\s*kwh", sor.group(1), re.I)
    return sum((_ezres(x) for x in szamok), Decimal(0)) if szamok else None


def mvm_elszamolt_kwh(szoveg: str, sz: Szamla) -> Decimal | None:
    """Részszámla: „Elszámolt mennyiség: "H" 23 kWh” (több sor összege); elszámoló: a számla mérőállásaiból
    (mérőnként záró − induló)."""
    sorok = re.findall(r"Elszámolt mennyiség:\s*(?:\"[^\"]*\"\s*)?(\d[\d .]*(?:,\d+)?)\s*kWh", szoveg, re.I)
    if sorok:
        return sum((Decimal(x.replace(" ", "").replace(".", "").replace(",", ".")) for x in sorok), Decimal(0))
    merok: dict[str, list[Decimal]] = {}
    for m in sz.meroallasok:
        merok.setdefault(m.mero, []).append(m.allas)
    return sum((max(v) - min(v) for v in merok.values()), Decimal(0)) if merok else None


def mvm_gaz_mennyisegek(szoveg: str) -> tuple[dict[str, Decimal] | None, Decimal | None]:
    """MVM gázszámla (PDF): az elszámolt mennyiség (MJ és m³) és a következő részszámla becsült mennyisége (m³)."""
    def szam(x: str) -> Decimal:
        return Decimal(x.replace(" ", "").replace(".", "").replace(",", "."))
    e = re.search(r"Elszámolt mennyiség:\s*([\d ]+)\s*MJ\s*\(([\d ]+(?:,\d+)?)\s*m3\)", szoveg)
    k = re.search(r"következő részszámla becsült mennyisége:\s*([\d ]+(?:,\d+)?)\s*m3", szoveg, re.I)
    return ({"mj": szam(e.group(1)), "m3": szam(e.group(2))} if e else None), (szam(k.group(1)) if k else None)


def mvm_gaz_szoveg(szoveg: str, fajl: str = "") -> Szamla | None:
    """MVM gázszámla PDF-ből, XML nélkül (pl. mérő nélküli átalány: „Árszabás: Mérő nélküli”, negyedéves számla).
    A fizetendő a fejlécből, a számla saját értéke az ÁFA-összesítő „Számla összesen” sorának bruttó értékéből."""
    t = szoveg
    # A stornó fejléce (mint a villanyé) csak „Sztornó számla” lehet, a „Földgáz …” cím nélkül.
    storno = "Földgáz" in t and re.search(r"^\s*(Sztornó számla)\s*$", t, re.M)
    if "MVM Next" not in t or not (storno or re.search(r"Földgáz\s+(?:elszámoló\s+számla|\d+\.\s*részszámla|részszámla|végszámla|stornó)", t)):
        return None
    nev = storno or re.search(r"Földgáz\s+(elszámoló számla|\d+\.\s*részszámla|részszámla|végszámla|stornó[^\n]*)", t)
    sorszam = re.search(r"Számla sorszáma:\s*(\d+)", t)
    kelte = re.search(r"Számla kelte:\s*(\d{4}\.\d{2}\.\d{2})", t)
    if not nev or not sorszam or not kelte:
        return None
    tipus = _tipus(nev.group(0))
    fizetendo = re.search(r"^Fizetendő összeg:\s*(-?[\d ]+)\s*Ft", t, re.M)
    osszesen = re.search(r"^Számla összesen:\s*(-?[\d ]+?)\s+(-?[\d ]+?)\s+(-?\d{1,3}(?: \d{3})*)\s*$", t, re.M)
    idoszak = re.search(r"(?:Elszámolási|Elszámolt) időszak:\s*(\d{4}\.\d{2}\.\d{2})\.?\s*-\s*(\d{4}\.\d{2}\.\d{2})", t)
    pont = re.search(r"Mérési pont azonosító:\s*(\S+)", t)
    elsz, kov = mvm_gaz_mennyisegek(t)
    ertek = _szam(osszesen.group(3)) if osszesen else None
    if ertek is None and fizetendo:
        # Régebbi nyomat „Számla összesen” sor nélkül: a „Bruttó számlaérték összesen** 27 3 475” sorban az ÁFA-kulcs
        # összefolyik az összeggel – ha a sor a fizetendővel végződik, az a számlaérték.
        b = re.search(r"Bruttó számlaérték összesen\**\s*([-\d ]+?)\s*$", t, re.M)
        fiz = fizetendo.group(1).replace(" ", "")
        if b and b.group(1).replace(" ", "").endswith(fiz.lstrip("-")):
            ertek = _szam(fiz)
    return Szamla(
        sztornozott=(m.group(1) if tipus == "storno" and (m := re.search(r"Sztornózott számla sorszáma:\s*(\d+)", t)) else ""),
        forras="mvm_gaz",
        sorszam=sorszam.group(1),
        kelte=_d(kelte.group(1)),
        osszeg=Decimal(0) if tipus == "storno" else (_szam(fizetendo.group(1)) if fizetendo else ertek),
        tipus=tipus,
        idoszak=(_d(idoszak.group(1)), _d(idoszak.group(2))) if idoszak else None,
        fajl=fajl,
        meresi_pont=pont.group(1) if pont else "",
        elszamolt_gaz=elsz,
        kovetkezo_resz_m3=kov,
        szamlaertek=ertek,
        hatarido=fizetesi_hatarido(t),
        folyoszamla=mvm_folyoszamla(t)[0],
    )


def mvm_kovetkezo_leolvasas(szoveg: str) -> tuple[date, date] | None:
    """„Következő leolvasás várható időpontja: 2026.09.22 - 2026.10.09 között” → az éves (elosztói) leolvasás ablaka."""
    m = re.search(r"Következő leolvasás várható időpontja:\s*(\d{4}\.\d{2}\.\d{2})\.?\s*-\s*(\d{4}\.\d{2}\.\d{2})", szoveg)
    return (_d(m.group(1)), _d(m.group(2))) if m else None


def mvm_diktalasi_ablak(szoveg: str) -> tuple[int, int] | None:
    """„Következő diktálási időszak: Minden hónap 08-14 között” → (8, 14)."""
    m = re.search(r"diktálási időszak:\s*Minden hónap\s*(\d{1,2})\s*-\s*(\d{1,2})", szoveg)
    return (int(m.group(1)), int(m.group(2))) if m else None


def mvm_levont_szamlak(t: str) -> list:
    """MVM elszámoló PDF: „Az elszámoló számlában elszámolt részszámlák sorszáma és a számla végösszege” lista –
    (sorszám, összeg vagy None, ha a nyomaton nem olvasható)."""
    i = t.find("elszámolt részszámlák sorszáma")
    if i < 0:
        return []
    out = []
    for sor in t[i:].splitlines()[2:]:
        m = re.match(r"^\s*(\d{9,})\s*(-?\d[\d. ]*?)?\s*(?:Ft)?\s*$", sor)  # új: „846… 1.172”, régi: „011… 12 062 Ft”
        if not m:
            break
        out.append((m.group(1), _ezres(m.group(2)) if m.group(2) else None))
    return out


def mvm_folyoszamla(t: str) -> tuple[Decimal | None, list]:
    """MVM: a folyószámla egyenlege a számla kibocsátásakor, és a bruttó számlaérték és a fizetendő összesen közötti
    tételek (név, összeg) – pl. „Túlfizetés -17.652”, „Egyéb fizetendőt csökkentő tétel -30.477”, kötbér."""
    folyo = re.search(r"folyószámla-egyenlege a számla kibocsátásakor:\s*(" + _SZAM + r")\s*Ft", t)
    egyeb = []
    bent = False
    elotag = ""  # több sorba tördelt tételnév („Kötbér garantált szolgáltatás / elmaradása miatt -5.000”)
    for sor in t.splitlines():
        if re.match(r"\s*Bruttó számlaérték összesen", sor):
            bent = True
            continue
        if not bent:
            continue
        if re.match(r"\s*Fizetendő összeg", sor):
            break
        if re.search(r"számla\(k\)", sor):  # „Késedelmi kamatszámításban érintett számla(k): 846…, 846…” – a sorszámok nem összegek
            elotag = f"{elotag} {sor.strip()}".strip()
            continue
        if elotag and (csak := re.match(r"\s*(" + _SZAM + r")\s*$", sor)):  # a tördelt tétel összege külön sorban („15”)
            if not elotag.lower().startswith("kerekítés"):
                egyeb.append((re.sub(r"\s*Késedelmi kamatszámításban.*$", "", elotag) or elotag, _ezres(csak.group(1))))
            elotag = ""
            continue
        m = re.match(r"\s*(\D.*?)\s+(" + _SZAM + r")\s*$", sor)
        if not m:
            elotag = f"{elotag} {sor.strip()}".strip() if sor.strip() else elotag
            continue
        nev = f"{elotag} {m.group(1).strip()}".strip()
        elotag = ""
        if not nev.lower().startswith("kerekítés"):
            egyeb.append((nev, _ezres(m.group(2))))
    return (_ezres(folyo.group(1)) if folyo else None), egyeb


def mvm_ugyfel(t: str) -> dict[str, str]:
    """A felhasználó adatai a számla fejlécéből (a reklamáció-tervezethez)."""
    out = {}
    for kulcs, minta in (("azonosito", r"Felhasználó azonosító száma:\s*(\d+)"), ("nev", r"Felhasználó neve:\s*(.+)"),
                         ("hely", r"Felhasználási hely címe:\s*(.+)"), ("meresi_pont", r"Mérési pont azonosító:\s*(\S+)")):
        if m := re.search(minta, t):
            out[kulcs] = re.sub(r"\s+", " ", m.group(1)).strip()
    return out


def _netto_brutto(szoveg: str) -> tuple[Decimal, Decimal] | None:
    """Egy „nettó bruttó” számpár a részletezőből – a két formátum („6 028 7 655”, „10.86213.795”, „-4.419-5.612”)
    egységesen: a bruttó a nettó × 1,27 (ÁFA), ez választja szét a két számot."""
    c = re.sub(r"[ .]", "", szoveg)
    for i in range(1, len(c)):
        a, b = c[:i], c[i:]
        if not re.fullmatch(r"-?\d+", a) or not re.fullmatch(r"-?\d+", b):
            continue
        na, nb = int(a), int(b)
        if (na == 0) == (nb == 0) and abs(nb - na * 1.27) <= 2 + abs(na) * 0.0005:
            return Decimal(na), Decimal(nb)
    return None


def _honap_ev(ho: int, tol: date, kelte: date) -> str:
    """A régi formátum „Elosztói alapdíj* N” hónapjához az év: a számla időszaka elejétől a kelte napjáig."""
    for ev in (kelte.year, kelte.year - 1):
        if tol.replace(day=1) <= date(ev, ho, 1) <= kelte:
            return f"{ev}-{ho:02d}"
    return f"{kelte.year}-{ho:02d}"


def mvm_tetelek(szoveg: str, idoszak: tuple[date, date] | None, kelte: date) -> dict[str, Any] | None:
    """MVM áram: a számlarészletező tételei – kiszámlázott mennyiség, energiadíj-mennyiségek fajtánként (kedvezményes,
    lakossági piaci, téli H-ár; a sávkorrekció előjelesen benne), az energiadíj és a rendszerhasználati díjak bruttó
    összesen (a levont részszámlák ELŐTT), és az elosztói alapdíj hónaponként (hónap → bruttó Ft)."""
    if "SZÁMLARÉSZLETEZ" not in szoveg:
        return None
    t = szoveg[szoveg.index("SZÁMLARÉSZLETEZ"):]
    if "ÁFA összesít" in t:
        t = t[:t.index("ÁFA összesít")]
    sor = " ".join(t.split())
    datum = r"(\d{4}\.\d\d\.\d\d)\s*-\s*(\d{4}\.\d\d\.\d\d)"
    menny = {"kedvezmenyes": Decimal(0), "piaci": Decimal(0), "teli": Decimal(0)}
    van = False
    for m in re.finditer(datum + r"\s*(-?\d[\d.]*(?:,\d+)?)\s*kWh\s*(\d+,\d+)\s*Ft/kWh", sor):
        elotte = sor[max(0, m.start() - 70):m.start()]
        cimke = elotte[elotte.rfind("ESZ"):] if "ESZ" in elotte else elotte
        if "díj" in cimke or "ESZ" not in elotte:
            continue  # rendszerhasználati / forgalmi díj
        q, ar = Decimal(m.group(3).replace(".", "").replace(",", ".")), Decimal(m.group(4).replace(",", "."))
        fajta = "piaci" if "piaci" in cimke else "teli" if ar < 4 else "kedvezmenyes"
        menny[fajta] += q
        van = True
    e = re.search(r"Energiadíj összesen\s*(?:" + datum + r")?\s*(-?[\d .-]+)", sor)
    r_ = re.search(r"Rendszerhasználati díjak összesen\s*(-?[\d .-]+)", sor)
    energia, rhd = (_netto_brutto(e.group(3)) if e else None), (_netto_brutto(r_.group(1)) if r_ else None)
    if not van or energia is None or rhd is None:
        return None
    alap: dict[str, Decimal] = {}
    for m in re.finditer(r"Elosztói alapdíj\s*(?:\"\w+\")?\s*\*?\s*(?:(\d{1,2})\s*1,00\s*db|" + datum + r"\s*(\d+)\s*hó)\s*(\d+,\d+)\s*Ft/(?:db|hó)", sor):
        ar = Decimal(m.group(5).replace(",", "."))
        # A tétel bruttója úgy, ahogy a számla számolja: nettó = hónapok × díj forintra, + ÁFA forintra; hónaponként
        # a tétel egy hónapra eső része (pl. 4 hó × 120,50 = 482 → 612 Ft: 153 Ft/hó).
        db = 1 if m.group(1) else int(m.group(4))
        br = ((ar * db).quantize(Decimal(1), rounding="ROUND_HALF_UP") * Decimal("1.27")).quantize(Decimal(1), rounding="ROUND_HALF_UP")
        if m.group(1) and idoszak:
            alap[_honap_ev(int(m.group(1)), idoszak[0], kelte)] = br
        elif m.group(2):
            a, b = _d(m.group(2)), _d(m.group(3))
            honapok = [f"{x.year}-{x.month:02d}" for x in (a + timedelta(days=i) for i in range((b - a).days + 1)) if x.day == 1]
            for h in honapok:
                alap[h] = (br / len(honapok)).quantize(Decimal("0.0001")) if honapok else br
    fo = re.search(r"(?:Fogyasztás összesen|Elszámolt mennyiség):\s*(?:\"\w+\"\s*)?(\d[\d.]*)\s*kWh", sor)
    return {
        "kiszamlazott_kwh": str(_ezres(fo.group(1))) if fo else None,
        **{k: str(v) for k, v in menny.items()},
        "energia_brutto": str(energia[1]), "rhd_brutto": str(rhd[1]),
        "alapdij": {k: str(v) for k, v in sorted(alap.items())},
    }


def fizetesi_hatarido(szoveg: str) -> date | None:
    """„Fizetési határidő: 2026.08.25” (MVM PDF; a régi nyomaton ponttal a végén)."""
    m = re.search(r"Fizetési határid\w*:\s*(\d{4}\.\d{2}\.\d{2})", szoveg)
    return _d(m.group(1)) if m else None


def mvm_aram_szoveg(szoveg: str, fajl: str = "") -> Szamla | None:
    t = szoveg
    if "MVM Next" not in t or "Villamos energia" not in t:
        return None
    # A stornó fejléce csak „Sztornó számla” (a „Villamos energia … számla” cím nélkül).
    nev = (re.search(r"Villamos energia[^\n]*?számla", t) or re.search(r"^\s*(végszámla)\b", t, re.M | re.I)
           or re.search(r"^\s*(Sztornó számla)\s*$", t, re.M))
    sorszam = re.search(r"Számla sorszáma:\s*(\d+)", t)
    kelte = re.search(r"Számla kelte:\s*(\d{4}\.\d{2}\.\d{2})", t)
    if not nev or not sorszam or not kelte:
        return None
    tipus = _tipus(nev.group(0))
    brutto = re.search(r"Bruttó számlaérték összesen\**\s*(" + _SZAM + r")\s*$", t, re.M)
    # A ténylegesen fizetendő (a fejlécben): elszámolónál a részszámlák, az MVM közös ügyfélszámláján a korábbi
    # túlfizetés levonása után – lehet negatív (visszajár). Ez a befizetés; a bruttó számlaérték csak tartalék.
    fizetendo = re.search(r"^Fizetendő összeg:\s*(" + _SZAM + r")\s*Ft", t, re.M)
    idoszak = re.search(r"(?:Elszámolási|Elszámolt) időszak:\s*(\d{4}\.\d{2}\.\d{2})\s*-\s*(\d{4}\.\d{2}\.\d{2})", t)
    pont = re.search(r"Mérési pont azonosító:\s*(\S+)", t)
    atalany = mvm_atalany(t)
    ablak = mvm_diktalasi_ablak(t)
    arsz = re.search(r'Árszabás:\s*ESZ\s*"?(A1|H|B)\b', t) or re.search(r'ESZ\s+Lakoss\w*\s+"?(A1|H|B)\b', t)
    sz = Szamla(
        forras="mvm_aram",
        sorszam=sorszam.group(1),
        kelte=_d(kelte.group(1)),
        # Részszámlánál a számla saját értéke (bruttó számlaérték) a befizetés: a fizetendő itt a folyószámla teljes
        # egyenlegét is tartalmazhatja (pl. korábbi túlfizetés: 991 Ft-os részszámla, „fizetendő” −47 138 Ft).
        osszeg=Decimal(0) if tipus == "storno" else (
            _ezres(brutto.group(1)) if tipus == "resz" and brutto
            else _ezres(fizetendo.group(1)) if fizetendo else _ezres(brutto.group(1)) if brutto else None
        ),
        tipus=tipus,
        idoszak=(_d(idoszak.group(1)), _d(idoszak.group(2))) if idoszak else None,
        fajl=fajl,
        meresi_pont=pont.group(1) if pont else "",
        atalany_mennyiseg=atalany,
        diktalasi_ablak=ablak,
        kovetkezo_leolvasas=mvm_kovetkezo_leolvasas(t),
        arszabas=arsz.group(1) if arsz else None,
        szamlaertek=_ezres(brutto.group(1)) if brutto else None,
        levont_szamlak=mvm_levont_szamlak(t),
    )
    sorok = []
    for m in _MVM_SOR.finditer(t):
        allas = _mvm_allasok(m.group(4), m.group(6))
        if allas:
            sorok.append((mero_azonosito(m.group(1)), _d(m.group(2)), _d(m.group(3)), allas, m.group(5)))
    # Több regiszteres mérő (H: téli+nyári, két sor ugyanarra az időszakra): a regiszterek sorrendje nem
    # egyértelmű, ezért az összegüket vesszük át – a fiók fő csatornája is a regiszterek összege.
    osszevont: dict[tuple[str, date, date], list] = {}
    for mero, kezd, vege, (indulo, zaro), lm in sorok:
        x = osszevont.setdefault((mero, kezd, vege), [Decimal(0), Decimal(0), lm])
        x[0] += indulo
        x[1] += zaro
        if x[2] != lm:
            x[2] = "Becs"  # vegyes leolvasási mód: nem tekintjük valódinak
    kezdetek = {(mero, kezd) for mero, kezd, _ in osszevont}
    for (mero, kezd, vege), (indulo, zaro, lm) in osszevont.items():
        if tipus == "storno":
            continue
        if (mero, vege) in kezdetek and lm.startswith(("Dikt", "Leol", "Ell")):
            sz.evhatarok.add(vege)
        sz.meroallasok.append(Meroallas(mero, vege, zaro, lm))
        sz.meroallasok.append(Meroallas(mero, kezd, indulo, lm))
    if not sz.meroallasok:  # a mérőszám így is jó a hozzárendeléshez
        sz.kapcsolt_merok = {x[0] for x in sorok}
    if sz.arszabas == "H" and tipus != "storno":
        sz.regiszter_allasok = h_regiszterek([(mero, kezd, vege, a[0], a[1], lm) for mero, kezd, vege, a, lm in sorok])
    sz.elszamolt_kwh = mvm_elszamolt_kwh(t, sz)
    sz.folyoszamla, sz.egyeb_tetelek = mvm_folyoszamla(t)
    sz.ugyfel = mvm_ugyfel(t)
    if sz.arszabas == "H":
        idenyek: dict[str, Decimal] = {}
        for m in re.finditer(r'ESZ\s+"H"\s+árszabás ára\s*(\d{4}\.\d{2}\.\d{2})\s*-\s*(\d{4}\.\d{2}\.\d{2})\s*(' + _SZAM + r")\s*kWh", t):
            nev = "teli" if _teli_nap(_d(m.group(1))) else "nyari"
            idenyek[nev] = idenyek.get(nev, Decimal(0)) + _ezres(m.group(3))
        sz.szamlazott_idenyek = idenyek or None
    if m := re.search(r'Fogyasztás összesen:\s*(?:"\w+"\s*)?(' + _SZAM + r")\s*kWh", t, re.I):
        sz.szamlazott_kwh = _ezres(m.group(1))
    if tipus != "storno":
        sz.tetelek = mvm_tetelek(t, sz.idoszak, sz.kelte)
    sz.hatarido = fizetesi_hatarido(t)
    if tipus == "storno" and (m := re.search(r"S(?:z)?tornózott számla (?:sor)?száma:?\s*(\d+)", t)):
        sz.sztornozott = m.group(1)
    return sz


def meresi_pontok_kapcsolasa(lista: list[Szamla], terkep: dict[str, list[str]] | None = None) -> None:
    """A mérőszám nélküli számlát (pl. részszámla) a mérési pontja alapján a többi számla mérőjéhez köti.

    terkep: tartós {mérési pont: [mérők]} – a hívó tárolja, így a későbbi részszámlák is köthetők.
    """
    terkep = {} if terkep is None else terkep
    for x in lista:
        if x.meresi_pont and x.merok:
            terkep[x.meresi_pont] = sorted(set(terkep.get(x.meresi_pont, [])) | x.merok)
    for x in lista:
        if x.meresi_pont and not x.merok:
            x.kapcsolt_merok = set(terkep.get(x.meresi_pont, ()))


def _par(c: str) -> str:
    """Egy hibásan összevont bájtpár („ㄠ” = „1 ”) visszabontása; minden más karakter marad."""
    o = ord(c)
    hi, lo = o >> 8, o & 0xFF
    if 0x2000 <= o < 0x8000 and all(b == 0 or 0x20 <= b < 0x7F for b in (hi, lo)):
        return (chr(hi) + chr(lo)).replace("\x00", "")
    return c


def _utf16_javit(sor: str) -> str:
    """Néhány MVM PDF szövegrétege UTF-16 bájtpárokként jön ki („\\x00S\\x00z…”), máshol két ASCII
    karakter egy „CJK” jellé olvad össze („Dikt459 ㄠ459”)."""
    if "\x00" in sor:
        try:
            sor = sor.encode("latin-1").decode("utf-16-be")
        except (UnicodeError, ValueError):
            sor = sor.replace("\x00", "")
    # Az „ő” és „ű” egyes nyomatokban vezérlőkarakter + betű („Fizetend\x01Q”).
    return "".join(_par(c) for c in sor).replace("\x01Q", "ő").replace("\x01q", "ű")


def pdf_szoveg(fajl: Path, mod: str = "layout") -> str:
    """PDF szövege. „layout”: a DAKÖV-höz (oszlopok megtartva); „plain”: az MVM-hez (a layout-mód nála
    összekeveri a UTF-16 bájtpárokat a szóközökkel)."""
    from pypdf import PdfReader  # noqa: PLC0415 – csak PDF-nél kell

    # Tartalom nélküli (üres) oldal: a layout-mód KeyError-ral elhasalna rajta (Telekom-számla 4. oldala).
    szoveg = "\n".join(p.extract_text(extraction_mode=mod) for p in PdfReader(str(fajl)).pages if "/Contents" in p)
    return szoveg if mod == "layout" else "\n".join(_utf16_javit(s) for s in szoveg.splitlines())


# --- Mappa ---------------------------------------------------------------------------------------------


def _mvm_pdf(fajl: Path) -> bool:
    """Az MVM számlanyomtatója (PrintSoft M-PReS) – a metaadatból, a szöveg kibontása nélkül."""
    from pypdf import PdfReader  # noqa: PLC0415

    try:
        meta = PdfReader(str(fajl)).metadata or {}
    except Exception:  # noqa: BLE001
        return False
    return "M-PReS" in str(meta.get("/Producer") or meta.get("/Creator") or "")


_FIZMOD = re.compile(r"Fizetési mód:[ \t]*(.+?)[ \t]*(?:A szolgáltatás megnevezése|\s{3,}|$)", re.M)


def fizetesi_mod(szoveg: str) -> str:
    """A számla szövegéből a fizetési mód (pl. „Csoportos beszedés”, „Egyedi utalás (Saját E-számla)”)."""
    m = _FIZMOD.search(szoveg or "")
    return m.group(1).strip() if m else ""


# Számlasablonok (2.3.0b2): az integráció tölti be (config/hu_rezsi_sablonok); a beépített beolvasók után próbálja.
SABLONOK: list[dict[str, Any]] = []


def sablonnal(sima: str, tabla: str, fajl: str) -> Szamla | None:
    """A mentett sablonok közül az első, amelyik felismeri a számlát és minden kötelező mezőt kiolvas."""
    if not SABLONOK:
        return None
    try:
        from . import ai_beolvaso, sablon  # noqa: PLC0415 – körkörös import elkerülése
    except ImportError:
        import ai_beolvaso  # noqa: PLC0415
        import sablon  # noqa: PLC0415
    for s in SABLONOK:
        try:
            adat = sablon.alkalmaz(s, sima, tabla)
        except Exception as err:  # noqa: BLE001 – egy hibás (pl. kézzel szerkesztett) sablon ne állítsa meg a többit
            _LOGGER.warning("Hibás számlasablon (%s): %s", s.get("azonosito"), err)
            continue
        if adat is None:
            continue
        if hiany := sablon.hianyzo(adat):
            _LOGGER.warning("%s: a(z) %s sablon felismerte, de hiányzik: %s – a beolvasó elavult lehet (AI-val újra kiolvasható)",
                            fajl, s.get("azonosito"), ", ".join(hiany))
            continue
        try:
            return ai_beolvaso.szamlava(adat, fajl, None, forras=f"sablon:{s['azonosito']}")
        except ValueError as err:
            _LOGGER.warning("%s: a(z) %s sablon adata nem alakítható: %s", fajl, s.get("azonosito"), err)
    return None


def beolvas_fajl(fajl: Path) -> Szamla | None:
    """Egy fájl → Számla (vagy None, ha nem ismert formátum). A PDF-ből a fizetési mód is (beszedésnél a határidőn
    fizetettnek vesszük)."""
    sz = _beolvas_fajl(fajl)
    if sz is not None and not isinstance(sz.kelte, date):
        _LOGGER.warning("Számla kelte nélkül (%s): fel nem ismertként kezelve", fajl)
        return None
    if sz is not None and not sz.fizetesi_mod and fajl.suffix.lower() == ".pdf":
        try:
            sz.fizetesi_mod = fizetesi_mod(pdf_szoveg(fajl)) or fizetesi_mod(pdf_szoveg(fajl, "plain"))
        except Exception:  # noqa: BLE001 – a fizetési mód nem kötelező
            pass
    return sz


def _xml_szamla(fajl: Path) -> Szamla | None:
    adat = fajl.read_bytes()
    return mvm_xml(adat, fajl.name) or mohu_xml(adat, fajl.name) or hvsz_xml(adat, fajl.name) or telekom_xml(adat, fajl.name)


def _xml_par_olvashato(xml: Path) -> bool:
    """A PDF XML-párja felismert, kelte szerinti számla-e (különben a PDF-et olvassuk, hogy a számla ne vesszen el)."""
    try:
        sz = _xml_szamla(xml)
    except Exception:  # noqa: BLE001 – hibás XML: a PDF-et olvassuk
        return False
    return sz is not None and isinstance(sz.kelte, date)


def _beolvas_fajl(fajl: Path) -> Szamla | None:
    """Egy fájl → Számla (vagy None, ha nem ismert formátum)."""
    try:
        if fajl.suffix.lower() == ".xml":
            sz = _xml_szamla(fajl)
            # Az MVM áram-XML-ben nincs benne az átalány mennyisége, a PDF-párban igen: friss számlánál onnan.
            pdf = fajl.with_suffix(".pdf")
            if sz and sz.tipus == "storno" and not sz.sztornozott and sz.forras in ("mvm_aram", "mvm_gaz") and pdf.exists():
                # Az MVM-stornó XML-jében nincs a sztornózott számla sorszáma, a PDF-párban igen („Stornózott számla száma”).
                sz.sztornozott = storno_hivatkozas(pdf_szoveg(pdf, "plain"))
            if sz and sz.forras == "mvm_gaz" and pdf.exists() and sz.folyoszamla is None:
                # A gáz-XML-ben nincs, a PDF-ben igen: „A nyilvántartás szerinti folyószámla-egyenlege a számla kibocsátásakor”.
                sz.folyoszamla = mvm_folyoszamla(pdf_szoveg(pdf, "plain"))[0]
            if sz and sz.forras == "mvm_gaz" and pdf.exists() and (date.today() - sz.kelte).days <= 400:
                szoveg = pdf_szoveg(pdf, "plain")
                sz.kovetkezo_leolvasas = mvm_kovetkezo_leolvasas(szoveg)
                sz.elszamolt_gaz, sz.kovetkezo_resz_m3 = mvm_gaz_mennyisegek(szoveg)
            if sz and sz.forras == "mvm_aram" and pdf.exists() and (date.today() - sz.kelte).days <= 400:
                szoveg = pdf_szoveg(pdf, "plain")
                sz.atalany_mennyiseg = mvm_atalany(szoveg)
                sz.diktalasi_ablak = mvm_diktalasi_ablak(szoveg)
                sz.kovetkezo_leolvasas = mvm_kovetkezo_leolvasas(szoveg)
                sz.elszamolt_kwh = mvm_elszamolt_kwh(szoveg, sz)
            if sz and sz.forras == "hvsz" and pdf.exists():
                hvsz_pdf(sz, pdf_szoveg(pdf))
            # A számlarészletező tételei (az éves kimutatáshoz) – az utolsó két év számláinál, a PDF-párból.
            if sz and sz.forras == "mvm_aram" and sz.tipus != "storno" and pdf.exists() and (date.today() - sz.kelte).days <= 800:
                szoveg = pdf_szoveg(pdf, "plain")
                sz.tetelek = mvm_tetelek(szoveg, sz.idoszak, sz.kelte)
                if not sz.levont_szamlak:  # az XML-ben nincs benne, mely részszámlákat vonta le az elszámoló
                    sz.levont_szamlak = mvm_levont_szamlak(szoveg)
            return sz
        if fajl.suffix.lower() == ".pdf":
            if fajl.with_suffix(".xml").exists() and _xml_par_olvashato(fajl.with_suffix(".xml")):
                return None  # az XML-t olvassuk helyette (ha az nem ismerhető fel, a PDF-et)
            if _mvm_pdf(fajl):  # a fölösleges DAKÖV-próba egy MVM-PDF-en annyi, mint maga a beolvasás
                sima = pdf_szoveg(fajl, "plain")
                return mvm_aram_szoveg(sima, fajl.name) or mvm_gaz_szoveg(sima, fajl.name)
            sima = pdf_szoveg(fajl, "plain")
            layout = pdf_szoveg(fajl)
            return (alfoldviz_szoveg(layout, fajl.name) or dakov_szoveg(layout, fajl.name) or mvm_aram_szoveg(sima, fajl.name)
                    or mvm_gaz_szoveg(sima, fajl.name) or telekom_pdf(layout, fajl.name) or one_pdf(sima, fajl.name)
                    or sablonnal(sima, layout, fajl.name))
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


def fajl_alairas(f: Path) -> str | None:
    """A fájl „méret:módosítás” azonosítója (a fel nem ismert fájl cseréjének / befejezett letöltésének észleléséhez)."""
    try:
        st = f.stat()
    except OSError:
        return None
    return f"{st.st_size}:{st.st_mtime_ns}"


def uj_fajlok(mappa: Path, ismert: set[str], nem_olvasott: dict[str, str] | None = None) -> list[Path]:
    """A mappa még nem látott számlafájljai. nem_olvasott: a korábban fel nem ismert fájlok (név → fajl_alairas) –
    ezek csak akkor újak, ha azóta megváltoztak (kicserélték, befejeződött a letöltésük)."""
    if not mappa.is_dir():
        return []
    nem_olvasott = nem_olvasott or {}
    return sorted(f for f in mappa.iterdir() if f.suffix.lower() in (".xml", ".pdf") and f.name not in ismert
                  and (f.name not in nem_olvasott or nem_olvasott[f.name] != fajl_alairas(f)))


def nem_olvasott_frissites(mappa: Path, nem_olvasott: dict[str, str], ujak: list[Path]) -> dict[str, str]:
    """A fel nem ismert fájlok nyilvántartása: a mappából eltűntek kimaradnak, az újonnan fel nem ismertek bekerülnek."""
    out = {n: a for n, a in (nem_olvasott or {}).items() if (mappa / n).exists()}
    for f in ujak:
        if (a := fajl_alairas(f)) is not None:
            out[f.name] = a
    return out


def szamlazott_idoszak(x: dict[str, Any]) -> tuple[date, date] | None:
    """Egy számla elszámolt időszaka (víznél az elszámolt mennyiség mellől, ha a számlán nincs külön)."""
    i = x.get("idoszak") or (x.get("elszamolt_viz") or {}).get("idoszak")
    return (date.fromisoformat(i[0]), date.fromisoformat(i[1])) if i else None


def szamla_teljes_dija(x: dict[str, Any], szamlak: dict[str, dict[str, Any]]) -> tuple[int | None, str]:
    """Az elszámolt időszak teljes bruttó díja: a számla saját értéke + a benne levont korábbi részszámlák (ahol az
    összeg nem olvasható a számlán, a tárolt részszámlából). (díj, forrás): „szamlaertek”, „szamlaertek+levont”, ill.
    „fizetendo” (csak a fizetendő ismert – levonás esetén nem a teljes díj), „fizetendo+reszszamlak” (kézi elszámoló:
    a fizetendő + az időszakába eső részszámlák, amelyeket a szolgáltató levont)."""
    i = szamlazott_idoszak(x)
    torolt = sztornozott_kulcsok(szamlak)  # a sztornózott részszámla nem része a díjnak (az újra kiállított igen)
    reszek = [r for k, r in szamlak.items() if x.get("tipus") in ("elszamolo", "vegszamla") and i and r.get("tipus") == "resz"
              and k not in torolt and (ri := szamlazott_idoszak(r)) and i[0] <= ri[0] and ri[1] <= i[1]]
    if x.get("szamlaertek") is None:
        if x.get("osszeg") is None:
            return None, "fizetendo"
        if x.get("kezi") and reszek:
            # Kézzel rögzített éves elszámoló részszámlás fióknál: a számlán a részszámlák levonása utáni fizetendő
            # áll, a teljes díj ehhez adva az időszak részszámláit.
            return int(Decimal(str(x["osszeg"])) + sum((Decimal(str(r.get("szamlaertek") or r.get("osszeg") or 0)) for r in reszek), Decimal(0))), "fizetendo+reszszamlak"
        return int(Decimal(str(x["osszeg"]))), "fizetendo"
    ossz = Decimal(str(x["szamlaertek"]))
    if not x.get("levont_szamlak"):
        # Régebbi elszámoló, amelyről a levont részszámlák listája nem olvasható: az időszakába eső tárolt részszámlák.
        if reszek:
            return int(ossz + sum((Decimal(str(r.get("szamlaertek") or r.get("osszeg") or 0)) for r in reszek), Decimal(0))), "szamlaertek+levont"
        return int(ossz), "szamlaertek"
    norm = {k.lstrip("0"): v for k, v in szamlak.items()}
    for sorszam, osszeg in x["levont_szamlak"]:
        if osszeg is None:
            r = norm.get(str(sorszam).lstrip("0"))
            if r is None:
                return None, "hianyzo_reszszamla"
            osszeg = r.get("szamlaertek") or r.get("osszeg")
        ossz += Decimal(str(osszeg))
    return int(ossz), "szamlaertek+levont"
