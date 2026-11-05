"""Számlák beolvasása e-mailből (IMAP) – a Home Assistanttól független rész.

Egy postafiók átnézése (végrehajtó szálon fut): bejelentkezés, a keresendő mappák (Gmailnél az „Összes levél” és a
Kuka – a nevük nyelvfüggő, ezért a LIST special-use jelzői alapján), a fiókok feladó-szűrőinek megfelelő, a
visszatekintési időn belüli levelek, a levél → fiók besorolás (feladó, tárgy, majd a PDF-ben / a levélben talált mérő
gyári száma vagy a felhasználási hely irányítószáma), a PDF/XML mellékletek mentése a fiók számlamappájába, és a
melléklet nélküli számlaértesítők (Telekom) adatai.

Csak OLVAS: a mappát csak olvasásra nyitja meg (EXAMINE), a levelet BODY.PEEK-kel tölti le – semmit nem töröl, nem
helyez át, és nem jelöl olvasottnak. A már ismert számlát (sorszám a tárban vagy a mappa egy fájlnevében, ill.
ugyanaz a fájl) kihagyja. A Home Assistant-oldal (email_ha) ütemez, tárol, rögzít és jelez.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import html
import imaplib
import logging
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Callable

try:
    from . import szamlak
except ImportError:  # a tesztek a csomag mappáját közvetlenül a path-ra teszik
    import szamlak  # type: ignore[no-redef]

_LOGGER = logging.getLogger(__name__)

ALAP_SZERVER = "imap.gmail.com"
ALAP_PORT = 993
ALAP_NAPOK = 45
IDOKORLAT = 40  # mp: kapcsolódás és egy-egy IMAP-parancs
MAX_LEVEL = 200  # egy átnézésben legfeljebb ennyi levelet töltünk le mappánként (a keresés így sem fut el)
SZAMLA_KITERJESZTESEK = {".pdf", ".xml"}
LATOTT_TARTAS_NAP = 7  # a visszatekintésen túl ennyi napig emlékszünk a feldolgozott levelekre
GMAIL_GAZDAK = ("gmail.com", "googlemail.com")
HONAPOK = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")  # IMAP-dátum (nem helyi)
FEJLEC_MEZOK = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID DATE)])"
# Számlának látszó melléklet-név (ha a beolvasó nem ismeri fel, akkor is mentjük – a mappa feldolgozása jelzi
# „fel nem ismert fájlként”, hogy beolvasó készülhessen hozzá).
SZAMLA_NEV = re.compile(r"(?i)sz[aá]mla|invoice|villany|f[oö]ldg[aá]z|g[aá]z|v[ií]z|\d{8,}")


class EmailHiba(Exception):
    """Postafiók-hiba (a postafiók állapotában és javítandó problémaként jelenik meg)."""

    tipus = "egyeb"


class HitelesitesiHiba(EmailHiba):
    tipus = "hitelesites"


class KapcsolatiHiba(EmailHiba):
    tipus = "kapcsolat"


class JelszoHianyzik(EmailHiba):
    tipus = "jelszo_hianyzik"


HITELESITES_SZOVEG = (
    "A bejelentkezés nem sikerült (hibás e-mail cím vagy jelszó). Gmailnél alkalmazásjelszó kell, nem a szokásos "
    "jelszavad: https://myaccount.google.com/apppasswords"
)
# Közérthető hibaszöveg levelezőnként (a panel állapotsorában és a javítandó problémában ez jelenik meg).
HITELESITES_SZOVEGEK = {
    "gmail": "A Google nem engedte be: ide alkalmazásjelszó kell, nem a szokásos jelszavad. Készíts egyet itt: "
             "https://myaccount.google.com/apppasswords (ehhez a kétlépcsős azonosításnak bekapcsolva kell lennie), és azt add meg.",
    "yahoo": "A Yahoo nem engedte be: ide alkalmazásjelszó kell, nem a szokásos jelszavad. Készíts egyet: "
             "https://login.yahoo.com/account/security → Alkalmazásjelszó létrehozása.",
    "icloud": "Az iCloud nem engedte be: ide alkalmazásspecifikus jelszó kell. Készíts egyet: https://account.apple.com → "
              "Bejelentkezés és biztonság → Alkalmazásspecifikus jelszavak.",
    "outlook": "A Microsoft (Outlook, Hotmail) jelszóval már nem enged be levelezőprogramot. Állíts be továbbítást a "
               "számlalevelekről egy Gmail- vagy Freemail-címre, és azt add meg itt.",
    "freemail": "A Freemail nem engedte be: ellenőrizd az e-mail címet és a jelszót, és hogy a Freemail beállításaiban "
                "engedélyezve van-e a levelezőprogramos (IMAP) hozzáférés.",
    "citromail": "A Citromail nem engedte be: ellenőrizd az e-mail címet és a jelszót, és hogy a Citromail beállításaiban "
                 "engedélyezve van-e a levelezőprogramos (IMAP) hozzáférés.",
}


# Az alkalmazásjelszó oldalai: a fordítások helykitöltői (gmail_url, yahoo_url, icloud_url).
JELSZO_URL = {"gmail_url": "https://myaccount.google.com/apppasswords", "yahoo_url": "https://login.yahoo.com/account/security",
              "icloud_url": "https://account.apple.com"}


def hitelesites_szoveg(szerver: str) -> str:
    return HITELESITES_SZOVEGEK.get(levelezo_szerverbol(szerver),
                                    "A bejelentkezés nem sikerült: hibás e-mail cím vagy jelszó (sok levelezőnél külön "
                                    "alkalmazásjelszó kell – lásd a levelező súgóját).")


# ------------------------------------------------------------------------------------------------ beállítások


def lista(ertek: Any) -> list[str]:
    """Vesszővel, pontosvesszővel, szóközzel vagy sortöréssel elválasztott lista (kisbetűsen, „@” előtag nélkül)."""
    if isinstance(ertek, (list, tuple)):
        ertek = ",".join(str(x) for x in ertek)
    return [x.strip().lower().lstrip("@") for x in re.split(r"[,;\s]+", str(ertek or "")) if x.strip().lstrip("@")]


def gmail(szerver: str) -> bool:
    s = (szerver or "").lower()
    return any(s == g or s.endswith("." + g) for g in GMAIL_GAZDAK)


# ------------------------------------------------------------------------------------------------ levelezők

# A cím domainje → a levelező beállításai. A szerverneveket kapcsolódással ellenőriztük (2026-11-01): a Citromail
# súgójában nincs IMAP-leírás, a „mail.citromail.hu” nem létezik, az imap.citromail.hu válaszol (a Freemaillel azonos
# szerverprogram) – a Citromail és a Freemail alkalmazásjelszó-igénye NINCS hivatalos súgóból ellenőrizve (a szokásos
# jelszóval próbálja; ha nem enged be, a levelező beállításaiban az IMAP-hozzáférést kell engedélyezni).
# Microsoft (Outlook.com, Hotmail, Live): az outlook.office365.com jelszavas bejelentkezést már nem fogad
# (LOGINDISABLED, csak OAuth2) – ezért „nem_tamogatott”: a felület elmondja, hogy továbbítással oldható meg.
LEVELEZOK: dict[str, dict[str, Any]] = {
    "gmail": {"nev": "Gmail", "domainek": ("gmail.com", "googlemail.com"), "szerver": "imap.gmail.com",
              "alkalmazasjelszo": True, "szokoz": True, "link": "https://myaccount.google.com/apppasswords"},
    "freemail": {"nev": "Freemail", "domainek": ("freemail.hu",), "szerver": "imap.freemail.hu",
                 "alkalmazasjelszo": False, "szokoz": False, "link": "https://freemail.hu"},
    "citromail": {"nev": "Citromail", "domainek": ("citromail.hu",), "szerver": "imap.citromail.hu",
                  "alkalmazasjelszo": False, "szokoz": False, "link": "https://citromail.hu"},
    "outlook": {"nev": "Outlook / Hotmail", "domainek": ("outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.hu", "hotmail.hu"),
                "szerver": "outlook.office365.com", "alkalmazasjelszo": True, "szokoz": True, "nem_tamogatott": True,
                "link": "https://account.live.com/proofs/AppPassword"},
    "yahoo": {"nev": "Yahoo Mail", "domainek": ("yahoo.com", "ymail.com"), "szerver": "imap.mail.yahoo.com",
              "alkalmazasjelszo": True, "szokoz": True, "link": "https://login.yahoo.com/account/security"},
    "icloud": {"nev": "iCloud Mail", "domainek": ("icloud.com", "me.com", "mac.com"), "szerver": "imap.mail.me.com",
               "alkalmazasjelszo": True, "szokoz": True, "link": "https://account.apple.com/account/manage"},
}
# Ezeknél a szervereknél az alkalmazásjelszót négyes csoportokban mutatják: a szóközök nem részei a jelszónak.
SZOKOZOS_SZERVEREK = {v["szerver"] for v in LEVELEZOK.values() if v["szokoz"]} | {"imap.googlemail.com"}
CIM_MINTA = re.compile(r"^[^@\s]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")


def cim_domain(cim: str) -> str:
    cim = (cim or "").strip().lower()
    return cim.rsplit("@", 1)[1] if "@" in cim else ""


def levelezo(cim: str) -> dict[str, Any]:
    """Az e-mail cím levelezője: kulcs, név, IMAP-szerver (port 993, SSL), alkalmazásjelszó kell-e, súgó-link.
    Ismeretlen domainnél „imap.<domain>” a tipp (ismert: False – a felület a Haladó mezőket is mutatja)."""
    domain = cim_domain(cim)
    for kulcs, v in LEVELEZOK.items():
        if domain in v["domainek"]:
            return {"kulcs": kulcs, "ismert": True, "port": ALAP_PORT, "ssl": True, **{k: x for k, x in v.items() if k != "domainek"}}
    return {"kulcs": "egyeb", "ismert": False, "nev": domain or "", "szerver": f"imap.{domain}" if domain else "", "port": ALAP_PORT,
            "ssl": True, "alkalmazasjelszo": False, "szokoz": False, "link": ""}


def levelezo_szerverbol(szerver: str) -> str:
    """A szerver levelezője (a hibaüzenethez): gmail, yahoo, … vagy „egyeb”."""
    s = (szerver or "").lower().strip()
    if gmail(s):
        return "gmail"
    return next((k for k, v in LEVELEZOK.items() if s == v["szerver"]), "egyeb")


def jelszo_tisztitas(jelszo: str, szerver: str) -> str:
    """Az alkalmazásjelszó szóközök nélkül azoknál a levelezőknél, amelyek csoportokban mutatják (Gmail, Yahoo,
    iCloud, Outlook); máshol a jelszó változatlan (a szóköz ott a jelszó része lehet)."""
    jelszo = str(jelszo or "")
    s = (szerver or "").lower().strip()
    return jelszo.replace(" ", "") if gmail(s) or s in SZOKOZOS_SZERVEREK else jelszo


LEPESEK = {
    "gmail": [
        "Nyisd meg ezt az oldalt: https://myaccount.google.com/apppasswords (ha nem nyílik meg, előbb kapcsold be a "
        "kétlépcsős azonosítást a Google-fiókodban: Biztonság → Kétlépcsős azonosítás).",
        "Adj nevet (pl. „Rezsikövető”), és kattints a Létrehozás gombra.",
        "A Google egy 16 betűs jelszót mutat (4 × 4 betű). Ezt másold a Jelszó mezőbe – a szóközök nem számítanak.",
    ],
    "freemail": [
        "Ide a Freemail-címed és a szokásos Freemail-jelszavad kell.",
        "Ha nem enged be: a freemail.hu-n a Beállításokban engedélyezd a levelezőprogramos (IMAP) hozzáférést.",
    ],
    "citromail": [
        "Ide a Citromail-címed és a szokásos jelszavad kell.",
        "Ha nem enged be: a citromail.hu-n a Beállításokban engedélyezd a levelezőprogramos (IMAP) hozzáférést.",
    ],
    "yahoo": [
        "Nyisd meg: https://login.yahoo.com/account/security → „Alkalmazásjelszó létrehozása”.",
        "Adj nevet (pl. „Rezsikövető”), és kattints a Létrehozás gombra.",
        "A kapott jelszót másold a Jelszó mezőbe.",
    ],
    "icloud": [
        "Nyisd meg: https://account.apple.com → Bejelentkezés és biztonság → Alkalmazásspecifikus jelszavak.",
        "Adj nevet (pl. „Rezsikövető”), és kattints a Létrehozás gombra.",
        "A kapott jelszót másold a Jelszó mezőbe.",
    ],
    "outlook": [
        "A Microsoft-fiókok (Outlook, Hotmail, Live) jelszóval már nem olvashatók levelezőprogramból.",
        "Megoldás: az Outlookban állíts be továbbítást a számlalevelekről egy Gmail- vagy Freemail-címre, és azt add meg itt.",
    ],
    "egyeb": [
        "Nézd meg a levelező súgójában, kell-e külön alkalmazásjelszó, és mi az IMAP-szerver neve.",
        "Ha a kapcsolódás nem sikerül, a Haladó részben írd be a szerver nevét (pl. imap.pelda.hu, port 993).",
    ],
    "alap": [
        "Írd be az e-mail címed, ahová a számláid érkeznek.",
        "Gmailnél a szokásos jelszó helyett alkalmazásjelszó kell: https://myaccount.google.com/apppasswords – "
        "Freemailnél és Citromailnél a szokásos jelszó.",
        "Kattints a Mehet gombra: a Rezsikövető bejelentkezik, és megkeresi az utolsó fél év számláit.",
    ],
}


def lepesek(kulcs: str) -> list[str]:
    """A levelező beállításának lépései (közérthetően) – a beállító felület leírásához és a panel varázslójához."""
    return LEPESEK.get(kulcs) or LEPESEK["egyeb"]


def lepesek_szoveg(kulcs: str) -> str:
    return "\n".join(f"{i}. {x}" for i, x in enumerate(lepesek(kulcs), 1))


def alap_nev(cim: str) -> str:
    """A postafiók alapértelmezett neve: a cím „@” előtti része."""
    return (cim or "").strip().split("@", 1)[0] or "E-mail"


@dataclass
class Postafiok:
    sid: str
    nev: str
    felhasznalo: str
    jelszo: str
    szerver: str = ALAP_SZERVER
    port: int = ALAP_PORT
    ssl: bool = True
    napok: int = ALAP_NAPOK
    kuka: bool = True

    @classmethod
    def adatbol(cls, sid: str, nev: str, data: dict[str, Any]) -> Postafiok:
        szerver = str(data.get("imap_szerver") or ALAP_SZERVER).strip()
        # A Google (Yahoo, iCloud, Outlook) az alkalmazásjelszót négyes csoportokban mutatja: szóközök nélkül.
        jelszo = jelszo_tisztitas(str(data.get("jelszo") or ""), szerver)
        return cls(
            sid=sid, nev=nev, felhasznalo=str(data.get("email_cim") or "").strip(), jelszo=jelszo, szerver=szerver,
            port=int(data.get("imap_port") or ALAP_PORT), ssl=bool(data.get("imap_ssl", True)),
            napok=max(1, int(data.get("email_napok") or ALAP_NAPOK)), kuka=bool(data.get("email_kuka", True)),
        )


@dataclass
class FiokSzuro:
    """Egy fiók e-mailes beállítása: melyik feladótól (cím vagy domain), milyen tárgyú levél, és – ha egy szolgáltató
    levelei több fiókot is lefednek – a mérő gyári száma vagy a felhasználási hely irányítószáma."""

    sid: str
    nev: str
    mappa: Path | None  # a számlamappa abszolút útja (None: nincs / a konfigurációs mappán kívül)
    feladok: list[str]
    targy: str = ""
    merok: list[str] = field(default_factory=list)
    irszok: list[str] = field(default_factory=list)

    @classmethod
    def adatbol(cls, sid: str, nev: str, data: dict[str, Any], config_dir: Path) -> FiokSzuro:
        return cls(
            sid=sid, nev=nev, mappa=szamla_mappa_ut(config_dir, data.get("szamla_mappa")),
            feladok=lista(data.get("email_feladok")), targy=str(data.get("email_targy") or "").strip(),
            merok=[m for m in (szamlak.mero_azonosito(x) for x in re.split(r"[,;]+", str(data.get("email_mero") or ""))) if m],
            irszok=re.findall(r"\b\d{4}\b", str(data.get("email_irsz") or "")),
        )

    @property
    def megkulonbozteto(self) -> bool:
        return bool(self.merok or self.irszok)

    def illeszkedik(self, feladok: list[str], targy: str) -> bool:
        if not self.feladok or not any(felado_illeszkedik(c, m) for c in feladok for m in self.feladok):
            return False
        return not self.targy or self.targy.lower() in (targy or "").lower()

    def tartalom_illeszkedik(self, szoveg: str) -> bool:
        tomor = re.sub(r"\s+", "", szoveg or "")
        if any(len(m) >= 5 and m in tomor for m in self.merok):
            return True
        return any(irsz_illeszkedik(szoveg, i) for i in self.irszok)


def szamla_mappa_ut(config_dir: Path, rel: Any) -> Path | None:
    """A számlamappa abszolút útja – csak a konfigurációs mappán belül (kilépő útvonalat nem írunk)."""
    if not rel:
        return None
    gyoker = Path(config_dir).resolve()
    ut = (gyoker / str(rel)).resolve()
    return ut if ut == gyoker or gyoker in ut.parents else None


# ------------------------------------------------------------------------------------------------ illesztés


def felado_cimek(fejlec: str | None) -> list[str]:
    return [c.lower() for _, c in getaddresses([fejlec or ""]) if "@" in c]


def felado_illeszkedik(cim: str, minta: str) -> bool:
    """Teljes cím („szamla@pelda.hu”) vagy domain („pelda.hu” – az aldomainjeivel együtt)."""
    cim, minta = cim.lower().strip(), minta.lower().strip().lstrip("@")
    if not minta or "@" not in cim:
        return False
    if "@" in minta:
        return cim == minta
    domain = cim.rsplit("@", 1)[1]
    return domain == minta or domain.endswith("." + minta)


FH_IRSZ = re.compile(r"Felhaszn\S*\s+hely\S*(?:\s+c[ií]m\S*)?\s*:?\s*(\d{4})\b", re.I)


def irsz_illeszkedik(szoveg: str, irsz: str) -> bool:
    """A felhasználási hely irányítószáma: ha a szövegben van „Felhasználási hely (címe): NNNN”, csak az számít (a
    számlán a levelezési cím is szerepelhet); különben egy sor elején vagy településnév előtt álló irányítószám."""
    talalt = FH_IRSZ.findall(szoveg or "")
    if talalt:
        return irsz in talalt
    return bool(re.search(rf"(?m)^\s*{irsz}\b|\b{irsz} [^\W\d]", szoveg or ""))


def fiok_valasztas(jeloltek: list[FiokSzuro], szoveg: str) -> list[FiokSzuro]:
    """A levél fiókja a szűrőnek megfelelő fiókok közül. Ha valamelyiknek van megkülönböztetője (mérő, irányítószám),
    az a fiók nyer, amelyiké a levélben / a PDF-ben szerepel; ha egyiké sem, a megkülönböztető nélküli fiók. Több
    jelölt csak akkor marad, ha ugyanaz a számlamappájuk (a mappa feldolgozása választja szét őket); különben nem
    egyértelmű: üres lista."""
    if not jeloltek:
        return []
    kulonbozo = [j for j in jeloltek if j.megkulonbozteto]
    if kulonbozo:
        eros = [j for j in kulonbozo if j.tartalom_illeszkedik(szoveg)]
        valasztott = eros or [j for j in jeloltek if not j.megkulonbozteto]
    else:
        valasztott = jeloltek
    if len(valasztott) == 1 or (valasztott and len({j.mappa for j in valasztott}) == 1):
        return valasztott
    return []


# ------------------------------------------------------------------------------------------------ levél


def biztonsagos_nev(nev: str) -> str:
    """Melléklet-név fájlnévként: útvonal nélkül, csak betű/szám/._- (szóköz helyett aláhúzás)."""
    nev = re.split(r"[\\/]", nev or "")[-1].strip()
    nev = re.sub(r"[^\w.\-]+", "_", nev, flags=re.UNICODE).strip("._") or "melleklet"
    return nev[:150]


def fajlnev_sorszam(nev: str) -> str | None:
    m = re.search(r"\d{8,}", nev or "")
    return m.group(0) if m else None


def mentendo_nev(nev: str, targy: str) -> str:
    """Továbbított MVM-levélben a melléklet neve gyakran csak „<sorszám>.PDF”: villanyszámla-tárgynál a szokásos
    „Villany_<sorszám>.pdf” névre mentjük (a kiterjesztés kisbetűs)."""
    p = Path(biztonsagos_nev(nev))
    if re.fullmatch(r"\d{8,}", p.stem) and "villany" in (targy or "").lower():
        return f"Villany_{p.stem}{p.suffix.lower()}"
    return p.stem + p.suffix.lower()


def mellekletek(uzenet: EmailMessage) -> list[tuple[str, bytes]]:
    """A PDF/XML mellékletek (a továbbított, csatolt levelekben lévők is): (eredeti név, tartalom)."""
    ki = []
    for resz in uzenet.walk():
        if resz.is_multipart():
            continue
        nev = resz.get_filename()
        if not nev or Path(nev).suffix.lower() not in SZAMLA_KITERJESZTESEK:
            continue
        adat = resz.get_payload(decode=True)
        if adat:
            ki.append((nev, adat))
    return ki


def torzs_szoveg(uzenet: EmailMessage) -> str:
    """A levél szövege (HTML-ből címkék nélkül), egy sorba tömörítve nem – a sorok megmaradnak."""
    darabok = []
    for resz in uzenet.walk():
        if resz.is_multipart() or resz.get_filename():
            continue
        tipus = resz.get_content_type()
        if tipus not in ("text/plain", "text/html"):
            continue
        try:
            t = resz.get_content()
        except (LookupError, ValueError):
            t = (resz.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if tipus == "text/html":
            t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
            t = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", t)
            t = html.unescape(re.sub(r"<[^>]+>", " ", t))
        darabok.append(t)
    return "\n".join(darabok)


def _nap(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return date(*map(int, s.strip(".").split("."))).isoformat()
    except (TypeError, ValueError):
        return None


def ertesito_szamla(szoveg: str) -> dict[str, Any] | None:
    """Melléklet nélküli számlaértesítő (Telekom): sorszám, összeg, kelte (kötelező), elszámolási időszak és
    határidő (ha van). Nem ilyen levél: None."""
    t = re.sub(r"\s+", " ", szoveg or "")

    def mezo(cimke: str, minta: str) -> str | None:
        m = re.search(cimke + r"\s*[:|]?\s*" + minta, t, re.I)
        return m.group(1) if m else None

    sorszam = mezo("Számla sorszáma", r"(\d{8,})")
    osszeg = mezo("Számlázott összeg", r"(-?\d[\d  .]*) ?Ft")
    kelte = _nap(mezo("Számla kelte", r"(\d{4}\.\d{2}\.\d{2})"))
    if not (sorszam and osszeg and kelte):
        return None
    idoszak = re.search(r"Elszámolási időszak\s*[:|]?\s*(\d{4}\.\d{2}\.\d{2})\.?\s*-\s*(\d{4}\.\d{2}\.\d{2})", t, re.I)
    return {
        "sorszam": sorszam,
        "osszeg": int(re.sub(r"[^\d-]", "", osszeg)),
        "kelte": kelte,
        "idoszak_tol": _nap(idoszak.group(1)) if idoszak else None,
        "idoszak_ig": _nap(idoszak.group(2)) if idoszak else None,
        "hatarido": _nap(mezo("Beérkezési határidő", r"(\d{4}\.\d{2}\.\d{2})") or mezo("Fizetési határidő", r"(\d{4}\.\d{2}\.\d{2})")),
    }


def level_kulcs(fejlec: EmailMessage) -> str:
    """A levél azonosítója a „látott” nyilvántartáshoz (a Message-ID kivonata – maga a cím nem kerül a tárba)."""
    alap = fejlec.get("Message-ID") or "|".join(str(fejlec.get(k) or "") for k in ("Date", "From", "Subject"))
    return hashlib.sha1(alap.strip().encode("utf-8", "replace")).hexdigest()[:20]


def _pdf_szoveg(fajl: Path) -> str:
    try:
        return szamlak.pdf_szoveg(fajl, "plain").replace("\x00", "")
    except Exception:  # noqa: BLE001 – szkennelt / sérült PDF: szöveg nélkül
        return ""


def _beolvas(fajl: Path) -> Any:
    try:
        return szamlak.beolvas_fajl(fajl)
    except Exception:  # noqa: BLE001 – a fel nem ismert melléklet nem hiba
        return None


# ------------------------------------------------------------------------------------------------ IMAP


def _idezett(nev: str) -> str:
    return '"' + nev.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _idezet_nelkul(nev: str) -> str:
    nev = nev.strip()
    if len(nev) >= 2 and nev[0] == nev[-1] == '"':
        return re.sub(r"\\(.)", r"\1", nev[1:-1])
    return nev


LIST_SOR = re.compile(r'^\((?P<jelzok>[^)]*)\)\s+(?P<elv>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<nev>.*)$', re.I)


def keresendo_mappak(list_valasz: list[Any], kuka: bool) -> list[str]:
    """A LIST-válaszból: az „Összes levél” (\\All – Gmail) vagy a Beérkezett (INBOX), és ha kérik, a Kuka (\\Trash).
    A nevek nyelvfüggők (pl. „[Gmail]/Kuka”), ezért a special-use jelzők döntenek."""
    osszes = kukanev = None
    for sor in list_valasz or []:
        if isinstance(sor, tuple):  # literálként küldött név: (b'(\\Trash) "/" {9}', b'[Gmail]/X')
            fej, nev_b = sor[0], sor[1]
            sor_s = (fej.decode("utf-8", "replace") if isinstance(fej, bytes) else str(fej))
            nev = nev_b.decode("utf-8", "replace") if isinstance(nev_b, bytes) else str(nev_b)
            m = LIST_SOR.match(re.sub(r"\{\d+\}$", "", sor_s).strip() + " X")
        else:
            if sor is None:
                continue
            sor_s = sor.decode("utf-8", "replace") if isinstance(sor, bytes) else str(sor)
            m = LIST_SOR.match(sor_s.strip())
            nev = _idezet_nelkul(m.group("nev")) if m else ""
        if not m:
            continue
        jelzok = {j.lower() for j in m.group("jelzok").split()}
        if "\\noselect" in jelzok:
            continue
        if "\\all" in jelzok and osszes is None:
            osszes = nev
        if "\\trash" in jelzok and kukanev is None:
            kukanev = nev
    ki = [osszes or "INBOX"]
    if kuka and kukanev and kukanev not in ki:
        ki.append(kukanev)
    return ki


def imap_datum(nap: date) -> str:
    return f"{nap.day:02d}-{HONAPOK[nap.month - 1]}-{nap.year}"


def kereses(feladok: list[str], napok: int, ma: date, gmail_kiterjesztes: bool) -> tuple[str, ...]:
    """A UID SEARCH argumentumai: a feladók bármelyikétől, a visszatekintési időn belül. Gmailnél a Gmail-kereső
    (X-GM-RAW), máshol szabványos SEARCH (a FROM a feladó-fejlécben részszövegre keres, a domain is jó)."""
    feladok = sorted({f.replace('"', "") for f in feladok if f})
    if gmail_kiterjesztes:
        return ("X-GM-RAW", _idezett(f"from:({' OR '.join(feladok)}) newer_than:{napok}d"))

    def vagy(x: list[str]) -> str:
        if len(x) == 1:
            return f"FROM {_idezett(x[0])}"
        return f"OR FROM {_idezett(x[0])} ({vagy(x[1:])})"

    return ("SINCE", imap_datum(ma - timedelta(days=napok)), vagy(feladok))


def _uzenet_bajtok(valasz: Any) -> bytes | None:
    for x in valasz or []:
        if isinstance(x, tuple) and len(x) > 1 and isinstance(x[1], (bytes, bytearray)):
            return bytes(x[1])
    return None


def kapcsolodik(pf: Postafiok, gyar: Callable[[Postafiok], Any] | None = None) -> Any:
    """Bejelentkezett IMAP-kapcsolat. Hibás jelszó: HitelesitesiHiba; nem elérhető szerver: KapcsolatiHiba."""
    if not pf.jelszo:
        raise JelszoHianyzik("Nincs megadva jelszó (visszaállítás után újra meg kell adni: E-mail fiók → Újrakonfigurálás).")
    try:
        if gyar is not None:
            imap = gyar(pf)
        elif pf.ssl:
            imap = imaplib.IMAP4_SSL(pf.szerver, pf.port, timeout=IDOKORLAT)
        else:
            imap = imaplib.IMAP4(pf.szerver, pf.port, timeout=IDOKORLAT)
            imap.starttls()
    except (OSError, imaplib.IMAP4.error) as err:
        raise KapcsolatiHiba(f"A szerver nem érhető el ({pf.szerver}:{pf.port}): {err}") from err
    try:
        imap.login(pf.felhasznalo, pf.jelszo)
    except imaplib.IMAP4.abort as err:
        _kilep(imap)
        raise KapcsolatiHiba(f"A kapcsolat megszakadt bejelentkezés közben: {err}") from err
    except imaplib.IMAP4.error as err:
        _kilep(imap)
        szoveg = err.args[0].decode("utf-8", "replace") if err.args and isinstance(err.args[0], bytes) else str(err)
        raise HitelesitesiHiba(f"{hitelesites_szoveg(pf.szerver)} (A szerver válasza: {szoveg[:200]})") from err
    except OSError as err:
        _kilep(imap)
        raise KapcsolatiHiba(f"A kapcsolat megszakadt bejelentkezés közben: {err}") from err
    return imap


def _kilep(imap: Any) -> None:
    try:
        imap.logout()
    except Exception:  # noqa: BLE001
        pass


def bejelentkezes_proba(pf: Postafiok, gyar: Callable[[Postafiok], Any] | None = None) -> None:
    """A beállító felület ellenőrzése: be tud-e lépni (utána kilép)."""
    _kilep(kapcsolodik(pf, gyar))


# ------------------------------------------------------------------------------------------------ átnézés


@dataclass
class Eredmeny:
    mentett: list[dict[str, Any]] = field(default_factory=list)  # {fiok, fiok_nev, fajl, sorszam, mappa}
    ertesitok: list[dict[str, Any]] = field(default_factory=list)  # {fiok, fiok_nev, adat}
    nem_besorolhato: list[dict[str, Any]] = field(default_factory=list)  # {datum, ok}
    kihagyva: int = 0  # már ismert számla
    levelek: int = 0  # a szűrőnek megfelelő, most feldolgozott levelek
    latott: dict[str, str] = field(default_factory=dict)  # levél-kulcs → a feldolgozás napja (a régiek nélkül)
    mappak: list[str] = field(default_factory=list)


def _ismert_a_mappaban(mappa: Path, sorszam: str | None, adat: bytes, nev: str) -> bool:
    if not mappa.is_dir():
        return False
    for f in mappa.iterdir():
        if not f.is_file():
            continue
        if sorszam and sorszam in f.name:
            return True
        if f.name == nev and f.stat().st_size == len(adat) and f.read_bytes() == adat:
            return True
    return False


def _szabad_nev(mappa: Path, nev: str) -> Path:
    cel = mappa / nev
    n = 2
    while cel.exists():
        cel = mappa / f"{Path(nev).stem}_{n}{Path(nev).suffix}"
        n += 1
    return cel


# ------------------------------------------------------------------------------------------------ tartalom szerinti besorolás

# A beolvasó forrása → közmű és a szolgáltató-kulcsok (dijszabasok/szolgaltatok.yaml), amelyek ilyen számlát küldenek.
# A lakossági villanyszámlát minden elosztói területen az MVM Next állítja ki.
MVM_VILLANY = frozenset({"mvm_demasz", "eon", "opus_titasz", "elmu", "elmu_emasz"})
FORRASOK: dict[str, tuple[str, frozenset[str], str]] = {
    "mvm_aram": ("villany", MVM_VILLANY, "MVM villanyszámla"),
    "mvm_gaz": ("gaz", frozenset({"mvm_next"}), "MVM gázszámla"),
    "dakov": ("viz", frozenset({"dakov"}), "DAKÖV vízszámla"),
    "alfoldviz": ("viz", frozenset({"alfoldviz"}), "ALFÖLDVÍZ vízszámla"),
    "mohu": ("hulladek", frozenset({"mohu"}), "MOHU hulladékszámla"),
    "hvsz": ("tavho", frozenset({"hvsz"}), "HVSZ távhőszámla"),
    "telekom": ("tavkozles", frozenset({"telekom"}), "Telekom-számla"),
    "one": ("tavkozles", frozenset({"one"}), "One-számla"),
}
# A közérthető üzenet alanya: „Az MVM villanyszámlái mostantól e-mailből jönnek a „Villany A1” fiókhoz.”
FORRAS_ALANY = {
    "mvm_aram": "Az MVM villanyszámlái", "mvm_gaz": "Az MVM gázszámlái", "dakov": "A DAKÖV vízszámlái",
    "alfoldviz": "Az ALFÖLDVÍZ vízszámlái", "mohu": "A MOHU számlái", "hvsz": "A HVSZ távhőszámlái",
    "telekom": "A Telekom számlái", "one": "A One számlái",
}
# Az ajánlat-kártya mondata: „Telekom-számlákat találtam, de nincs ilyen fiók.”
FORRAS_TARGY = {
    "mvm_aram": "MVM villanyszámlákat", "mvm_gaz": "MVM gázszámlákat", "dakov": "DAKÖV vízszámlákat",
    "alfoldviz": "ALFÖLDVÍZ vízszámlákat", "mohu": "MOHU-számlákat", "hvsz": "HVSZ távhőszámlákat",
    "telekom": "Telekom-számlákat", "one": "One-számlákat",
}
ARSZABASOK = {"villany/a1": "A1", "villany/h": "H", "villany/b": "B"}  # a fiók díjszabása → a számla árszabása


@dataclass
class AutoFiok:
    """Egy fiók a tartalom szerinti besoroláshoz: mit tudunk róla (közmű, szolgáltató, árszabás, mérők, mérési
    pontok, már ismert számla-sorszámok, a felhasználási hely irányítószáma)."""

    sid: str
    nev: str
    mappa: Path | None
    kozmu: str
    szolgaltato: str
    arszabas: str | None = None
    merok: set[str] = field(default_factory=set)
    meresi_pontok: set[str] = field(default_factory=set)
    sorszamok: set[str] = field(default_factory=set)
    irszok: list[str] = field(default_factory=list)
    feladok: list[str] = field(default_factory=list)  # a szolgáltatója ismert feladói (keresés, melléklet nélküli értesítő)

    @classmethod
    def adatbol(cls, sid: str, nev: str, data: dict[str, Any], tarolt: dict[str, Any] | None, config_dir: Path,
                feladok: list[str] | None = None) -> AutoFiok:
        tarolt = tarolt or {}
        merok = {szamlak.mero_azonosito(x) for x in re.split(r"[,;+]+", str(data.get("gyari_szam") or "")) if x.strip()}
        merok |= {szamlak.mero_azonosito(x) for x in re.split(r"[,;]+", str(data.get("szamla_merok") or "")) if x.strip()}
        merok |= {szamlak.mero_azonosito(m.get("gyari_szam") or "") for m in tarolt.get("merok") or []}
        pontok = dict(tarolt.get("meresi_pontok") or {})
        merok |= {szamlak.mero_azonosito(m) for v in pontok.values() for m in v or []}
        return cls(
            sid=sid, nev=nev, mappa=szamla_mappa_ut(config_dir, data.get("szamla_mappa")), kozmu=str(data.get("kozmu") or ""),
            szolgaltato=str(data.get("szolgaltato") or ""), arszabas=ARSZABASOK.get(str(data.get("dijszabas") or "")),
            merok={m for m in merok if m}, meresi_pontok=set(pontok), sorszamok=set(tarolt.get("szamlak") or {}),
            irszok=re.findall(r"\b\d{4}\b", str(data.get("email_irsz") or "")), feladok=list(feladok or []),
        )


@dataclass
class SzamlaJel:
    """Amit egy talált számláról tudunk (a besoroláshoz): forrás, közmű, szolgáltatók, sorszám, mérők, mérési pont,
    árszabás, a felhasználási hely, a kelte és az összeg."""

    forras: str
    kozmu: str
    szolgaltatok: frozenset[str]
    sorszam: str = ""
    merok: frozenset[str] = frozenset()
    meresi_pont: str = ""
    arszabas: str | None = None
    hely: str = ""
    kelte: str | None = None
    osszeg: int | None = None
    tipus: str = "melleklet"  # melleklet | ertesito

    @property
    def nev(self) -> str:
        return FORRASOK.get(self.forras, ("", frozenset(), self.forras))[2]

    @property
    def csoport(self) -> str:
        """A besorolási döntés kulcsa: ugyanaz a szolgáltató és ugyanaz a mérő (mérési pont) – egy kérdés elég."""
        azon = ",".join(sorted(self.merok)) or self.meresi_pont or "-"
        return f"{self.forras}|{azon}"


def szamla_jel(sz: Any) -> SzamlaJel | None:
    """A beolvasott számlából (szamlak.Szamla) a besorolás adatai; ismeretlen forrásnál None."""
    if sz is None or getattr(sz, "forras", None) not in FORRASOK:
        return None
    kozmu, szolg, _ = FORRASOK[sz.forras]
    ugyfel = getattr(sz, "ugyfel", None) or {}
    osszeg = getattr(sz, "osszeg", None)
    kelte = getattr(sz, "kelte", None)
    return SzamlaJel(
        forras=sz.forras, kozmu=kozmu, szolgaltatok=szolg, sorszam=str(getattr(sz, "sorszam", "") or ""),
        merok=frozenset(m for m in (getattr(sz, "merok", None) or set()) if m),
        meresi_pont=str(getattr(sz, "meresi_pont", "") or ugyfel.get("meresi_pont") or ""),
        arszabas=getattr(sz, "arszabas", None), hely=str(ugyfel.get("hely") or ""),
        kelte=kelte.isoformat() if hasattr(kelte, "isoformat") else None,
        osszeg=int(osszeg) if osszeg is not None else None,
    )


def ertesito_jel(adat: dict[str, Any], felado_szolg: set[str] | frozenset[str]) -> SzamlaJel | None:
    """Melléklet nélküli számlaértesítő (Telekom): a feladó domainje adja a szolgáltatót."""
    forras = next((f for f, (_, szolg, _) in FORRASOK.items() if f in ("telekom", "one") and szolg & set(felado_szolg)), None)
    if not forras:
        return None
    kozmu, szolg, _ = FORRASOK[forras]
    return SzamlaJel(forras=forras, kozmu=kozmu, szolgaltatok=szolg, sorszam=str(adat.get("sorszam") or ""),
                     kelte=adat.get("kelte"), osszeg=adat.get("osszeg"), tipus="ertesito")


def tartalom_valasztas(jel: SzamlaJel, fiokok: list[AutoFiok]) -> tuple[list[AutoFiok], str]:
    """A számla fiókja a tartalma szerint. Visszaad: (jelöltek, ok). ok:
    „ismert” – a sorszám már egy fiók számlája; „mero” – a mérő gyári száma / mérési pontja egyezik; „szolgaltato” –
    a fiók közműve és szolgáltatója egyezik (mérő nélkül, vagy a fióknak még nincs ismert mérője); „mas_mero” – van
    ilyen szolgáltatójú fiók, de másik mérővel (mérőcsere vagy másik ingatlan: kérdezni kell). Egy jelölt (és nem
    „mas_mero”): egyértelmű; több: kérdés; egy sem: nincs ilyen fiók."""
    if jel.sorszam:
        ismert = [f for f in fiokok if jel.sorszam in f.sorszamok]
        if len(ismert) == 1:
            return ismert, "ismert"

    def arszabas_szerint(lista: list[AutoFiok]) -> list[AutoFiok]:
        if not jel.arszabas:
            return lista
        return [f for f in lista if not f.arszabas or f.arszabas == jel.arszabas] or lista

    if jel.merok or jel.meresi_pont:
        mero = [f for f in fiokok if (jel.merok & f.merok) or (jel.meresi_pont and jel.meresi_pont in f.meresi_pontok)]
        if mero:
            return arszabas_szerint(mero), "mero"
    csalad = [f for f in fiokok if f.kozmu == jel.kozmu and f.szolgaltato in jel.szolgaltatok]
    if jel.arszabas:
        csalad = [f for f in csalad if not f.arszabas or f.arszabas == jel.arszabas]
    ok = "szolgaltato"
    if jel.merok or jel.meresi_pont:
        szabad = [f for f in csalad if not f.merok and not f.meresi_pontok]
        if szabad:
            csalad = szabad
        elif csalad:
            ok = "mas_mero"
    if len(csalad) > 1 and jel.hely:
        irsz = [f for f in csalad if f.irszok and any(irsz_illeszkedik(f"Felhasználási hely: {jel.hely}", i) for i in f.irszok)]
        if irsz:
            csalad = irsz
    return csalad, ok


def egyertelmu(jeloltek: list[AutoFiok], ok: str) -> AutoFiok | None:
    return jeloltek[0] if len(jeloltek) == 1 and ok != "mas_mero" else None


# ------------------------------------------------------------------------------------------------ keresés (tartalom)


MELLEKLET_SZERKEZET = re.compile(rb'(?i)"application"\s+"(pdf|xml|octet-stream)"|"text"\s+"xml"|\.(pdf|xml)"')


def _melleklete_van(imap: Any, uid: bytes) -> bool:
    """Szabványos IMAP-nál (nincs melléklet-keresés): a levél szerkezete (BODYSTRUCTURE – a levelet nem tölti le)
    alapján van-e PDF/XML melléklete."""
    typ, v = imap.uid("FETCH", uid, "(BODYSTRUCTURE)")
    if typ != "OK":
        return False
    nyers = b" ".join(x if isinstance(x, (bytes, bytearray)) else b" ".join(y for y in x if isinstance(y, (bytes, bytearray)))
                      for x in v or [] if x is not None)
    return bool(MELLEKLET_SZERKEZET.search(nyers))


def kereses_tartalom(feladok: list[str], napok: int, ma: date, gmail_kiterjesztes: bool) -> tuple[str, ...]:
    """Tartalom szerinti besorolásnál: a megadott feladóktól VAGY PDF/XML melléklettel (pl. továbbított számla).
    Gmailnél egy Gmail-keresés; máshol a visszatekintési idő minden levele (a mellékletet a szerkezet dönti el)."""
    feladok = sorted({f.replace('"', "") for f in feladok if f})
    if gmail_kiterjesztes:
        felado = f"from:({' OR '.join(feladok)}) " if feladok else ""
        return ("X-GM-RAW", _idezett(f"newer_than:{napok}d {{{felado}filename:pdf filename:xml}}"))
    return ("SINCE", imap_datum(ma - timedelta(days=napok)))


def felderites_mappak(list_valasz: list[Any]) -> list[str]:
    """Felderítéshez: Gmailnél az „Összes levél” és a Kuka; máshol minden megnyitható mappa az Elküldött és a
    Piszkozatok kivételével (a Kuka és a Levélszemét is)."""
    gm = keresendo_mappak(list_valasz, True)
    if gm[0] != "INBOX":
        return gm
    ki: list[str] = []
    for sor in list_valasz or []:
        if isinstance(sor, tuple):
            fej = sor[0].decode("utf-8", "replace") if isinstance(sor[0], bytes) else str(sor[0])
            nev = sor[1].decode("utf-8", "replace") if isinstance(sor[1], bytes) else str(sor[1])
            m = LIST_SOR.match(re.sub(r"\{\d+\}$", "", fej).strip() + " X")
        else:
            if sor is None:
                continue
            sor_s = sor.decode("utf-8", "replace") if isinstance(sor, bytes) else str(sor)
            m = LIST_SOR.match(sor_s.strip())
            nev = _idezet_nelkul(m.group("nev")) if m else ""
        if not m:
            continue
        jelzok = {j.lower() for j in m.group("jelzok").split()}
        if jelzok & {"\\noselect", "\\sent", "\\drafts", "\\nonexistent"}:
            continue
        if nev and nev not in ki:
            ki.append(nev)
    if "INBOX" not in [k.upper() for k in ki]:
        ki.insert(0, "INBOX")
    return ki


# ------------------------------------------------------------------------------------------------ átnézés


def atnez(
    pf: Postafiok,
    szurok: list[FiokSzuro],
    ismert: set[str],
    latott: dict[str, str],
    ma: date,
    gyar: Callable[[Postafiok], Any] | None = None,
    auto: list[AutoFiok] | None = None,
    felado_terkep: dict[str, set[str]] | None = None,
    napok: int | None = None,
) -> Eredmeny:
    """Egy postafiók átnézése (végrehajtó szálon). `ismert`: a háztartás már ismert számla-sorszámai (bővül a most
    mentettekkel). `latott`: a korábban már feldolgozott levelek (kulcs → nap). `auto`: a tartalom szerint besorolt
    fiókok (a melléklet beolvasása dönt; a kézi szűrők – `szurok` – tartaléknak maradnak). `felado_terkep`: ismert
    feladó-domain → szolgáltató-kulcsok. `napok`: a visszatekintés felülírása (felzárkózás). Hibánál EmailHiba."""
    szurok = [s for s in szurok if s.feladok]
    auto = list(auto or [])
    napok = max(1, int(napok or pf.napok))
    er = Eredmeny(latott={k: v for k, v in (latott or {}).items() if v >= (ma - timedelta(days=napok + LATOTT_TARTAS_NAP)).isoformat()})
    if not szurok and not auto:
        return er
    imap = kapcsolodik(pf, gyar)
    try:
        gm = "X-GM-EXT-1" in {str(c).upper() for c in (getattr(imap, "capabilities", None) or ())}
        typ, lista_v = imap.list()
        er.mappak = keresendo_mappak(lista_v if typ == "OK" else [], pf.kuka)
        kezi_feladok = [f for s in szurok for f in s.feladok]
        if auto:
            auto_feladok = sorted({f for a in auto for f in a.feladok} | set(kezi_feladok))
            feltetel = kereses_tartalom(auto_feladok, napok, ma, gm)
        else:
            auto_feladok = []
            feltetel = kereses(kezi_feladok, napok, ma, gm)
        ctx = _Kornyezet(pf=pf, szurok=szurok, ismert=ismert, er=er, ma=ma, auto=auto, felado_terkep=felado_terkep or {},
                         auto_feladok=auto_feladok, szerkezet_kell=bool(auto) and not gm)
        latott_most: set[str] = set()
        for mappa in er.mappak:
            typ, _ = imap.select(_idezett(mappa), readonly=True)
            if typ != "OK":
                _LOGGER.debug("%s: a(z) %s mappa nem nyitható meg", pf.nev, mappa)
                continue
            typ, ids = imap.uid("SEARCH", *feltetel)
            if typ != "OK":
                continue
            uidok = (ids[0] or b"").split() if ids else []
            for uid in uidok[-MAX_LEVEL:]:
                _level(imap, uid, ctx, latott_most)
    except EmailHiba:
        raise
    except (imaplib.IMAP4.abort, OSError) as err:
        raise KapcsolatiHiba(f"A kapcsolat megszakadt: {err}") from err
    except imaplib.IMAP4.error as err:
        raise EmailHiba(f"IMAP-hiba: {err}") from err
    finally:
        _kilep(imap)
    return er


@dataclass
class _Kornyezet:
    pf: Postafiok
    szurok: list[FiokSzuro]
    ismert: set[str]
    er: Eredmeny
    ma: date
    auto: list[AutoFiok]
    felado_terkep: dict[str, set[str]]
    auto_feladok: list[str]
    szerkezet_kell: bool


def felado_szolgaltatok(feladok: list[str], terkep: dict[str, set[str]]) -> set[str]:
    """A levél feladóiból a szolgáltató-kulcsok (ismert feladó-domain szerint)."""
    ki: set[str] = set()
    for c in feladok:
        for minta, szolg in (terkep or {}).items():
            if felado_illeszkedik(c, minta):
                ki |= set(szolg)
    return ki


def _elemek(mell: list[tuple[str, bytes]], targy: str) -> list[dict[str, Any]]:
    """A mellékletek beolvasva (ideiglenes mappában, hogy a PDF–XML pár együtt legyen): név, tartalom, számla,
    szöveg, sorszám, számlának látszik-e, és a besorolás adatai (jel)."""
    with tempfile.TemporaryDirectory(prefix="hu_rezsi_email_") as tmp:
        elemek = []
        fajlok = []
        for nev, adat in mell:
            mnev = mentendo_nev(nev, targy)
            f = Path(tmp) / mnev
            if f.exists():
                f = _szabad_nev(Path(tmp), mnev)
            f.write_bytes(adat)
            fajlok.append((f, adat))
        for f, adat in fajlok:
            sz = _beolvas(f)
            szoveg = _pdf_szoveg(f) if f.suffix == ".pdf" else adat.decode("utf-8", "replace")
            sorszam = (getattr(sz, "sorszam", None) or None) if sz is not None else None
            sorszam = sorszam or fajlnev_sorszam(f.name)
            elemek.append({"nev": f.name, "adat": adat, "sz": sz, "szoveg": szoveg, "sorszam": sorszam, "jel": szamla_jel(sz),
                           "szamla": sz is not None or bool(SZAMLA_NEV.search(f.name))})
    return elemek


def _level(imap: Any, uid: bytes, ctx: _Kornyezet, latott_most: set[str]) -> None:
    er, ma = ctx.er, ctx.ma
    typ, fej_v = imap.uid("FETCH", uid, FEJLEC_MEZOK)
    fej_b = _uzenet_bajtok(fej_v) if typ == "OK" else None
    if not fej_b:
        return
    fej = email.message_from_bytes(fej_b, policy=email.policy.default)
    kulcs = level_kulcs(fej)
    if kulcs in latott_most or kulcs in er.latott:  # másik mappában (Összes levél ↔ Kuka) vagy korábban már láttuk
        return
    latott_most.add(kulcs)
    targy = str(fej.get("Subject") or "")
    cimek = felado_cimek(str(fej.get("From") or ""))
    jeloltek = [s for s in ctx.szurok if s.illeszkedik(cimek, targy)]
    auto_jelolt = False
    if ctx.auto:
        if any(felado_illeszkedik(c, m) for c in cimek for m in ctx.auto_feladok):
            auto_jelolt = True
        else:
            auto_jelolt = _melleklete_van(imap, uid) if ctx.szerkezet_kell else True
    if not jeloltek and not auto_jelolt:
        if ctx.auto:
            er.latott[kulcs] = ma.isoformat()  # nem számla (nincs melléklete, ismeretlen feladó)
        return
    typ, adat_v = imap.uid("FETCH", uid, "(BODY.PEEK[])")
    nyers = _uzenet_bajtok(adat_v) if typ == "OK" else None
    if not nyers:
        return
    er.levelek += 1
    uzenet = email.message_from_bytes(nyers, policy=email.policy.default)
    mell = mellekletek(uzenet)
    torzs = torzs_szoveg(uzenet)
    datum = _levelnap(fej) or ma.isoformat()
    elemek = _elemek(mell, targy)
    szamla_elemek = [e for e in elemek if e["szamla"]]
    maradek = szamla_elemek
    ketes: list[str] = []
    # 1) Tartalom szerint (a melléklet beolvasása): a PDF és az XML-párja (azonos név) együtt megy.
    if ctx.auto and szamla_elemek:
        csoportok: dict[str, list[dict[str, Any]]] = {}
        for e in szamla_elemek:
            csoportok.setdefault(Path(e["nev"]).stem.lower(), []).append(e)
        maradek = []
        for csop in csoportok.values():
            jel = next((e["jel"] for e in csop if e["jel"]), None)
            if jel is None:
                maradek.extend(csop)
                continue
            jeloltek_t, ok = tartalom_valasztas(jel, ctx.auto)
            fiok = egyertelmu(jeloltek_t, ok)
            if fiok is None:
                if jeloltek_t:
                    ketes.extend(j.nev for j in jeloltek_t)
                maradek.extend(csop)
                continue
            _ment_elemek(fiok, csop, ctx, datum)
        if not maradek:
            er.latott[kulcs] = ma.isoformat()
            return
    if ctx.auto and not mell and (adat := ertesito_szamla(torzs)):
        jel = ertesito_jel(adat, felado_szolgaltatok(cimek, ctx.felado_terkep))
        if jel is not None:
            jeloltek_t, ok = tartalom_valasztas(jel, ctx.auto)
            fiok = egyertelmu(jeloltek_t, ok)
            if fiok is not None:
                _ertesito(fiok, adat, ctx, datum, kulcs)
                er.latott[kulcs] = ma.isoformat()
                return
            ketes.extend(j.nev for j in jeloltek_t)
    # 2) Kézi szűrők (feladó, tárgy, mérő / irányítószám) – a régi út, és tartalék a tartalom szerintihez.
    teljes_szoveg = "\n".join([torzs, *(e["szoveg"] for e in elemek)])
    valasztott = fiok_valasztas(jeloltek, teljes_szoveg)
    if not valasztott:
        if ketes:
            er.nem_besorolhato.append({"datum": datum, "ok": "több fiókhoz is illik" if len(set(ketes)) > 1 else "a mérő nem egyezik",
                                       "fiokok": sorted(set(ketes))})
        elif jeloltek and (maradek or ertesito_szamla(torzs)):
            ok = "több fiókhoz is illik" if len(jeloltek) > 1 else "a mérő / irányítószám nem egyezik"
            # Nem végleges (nem kerül a „látott” levelek közé): a beállítás javítása után újra próbáljuk.
            er.nem_besorolhato.append({"datum": datum, "ok": ok, "fiokok": [j.nev for j in jeloltek]})
        else:
            er.latott[kulcs] = ma.isoformat()
        return
    fiok = valasztott[0]
    if maradek:
        if _ment_elemek(fiok, maradek, ctx, datum):
            er.latott[kulcs] = ma.isoformat()
        return
    if not mell and (adat := ertesito_szamla(torzs)):
        _ertesito(fiok, adat, ctx, datum, kulcs)
    er.latott[kulcs] = ma.isoformat()


def _ertesito(fiok: Any, adat: dict[str, Any], ctx: _Kornyezet, datum: str, kulcs: str) -> None:
    if adat["sorszam"] in ctx.ismert:
        ctx.er.kihagyva += 1
        return
    ctx.ismert.add(adat["sorszam"])
    # A kulcs: ha a rögzítés nem sikerül, a HA-oldal kiveszi a „látott” levelek közül (újrapróba).
    ctx.er.ertesitok.append({"fiok": fiok.sid, "fiok_nev": fiok.nev, "adat": adat, "datum": datum, "kulcs": kulcs})


def _ment_elemek(fiok: Any, szamla_elemek: list[dict[str, Any]], ctx: _Kornyezet, datum: str) -> bool:
    """A levél (egy fiókhoz tartozó) számla-mellékleteinek mentése a fiók számlamappájába. A már ismert számla
    (sorszám a tárban vagy a mappában) kimarad. False: nincs érvényes számlamappa (nem besorolható)."""
    er, ismert = ctx.er, ctx.ismert
    if fiok.mappa is None:
        er.nem_besorolhato.append({"datum": datum, "ok": f"{fiok.nev}: nincs (érvényes) számlamappa", "fiokok": [fiok.nev]})
        return False
    # A levél számlái együtt döntenek (a PDF és az XML-párja ugyanazzal a sorszámmal jön).
    sorszamok = {e["sorszam"] for e in szamla_elemek if e["sorszam"]}
    if sorszamok and all(s in ismert or _ismert_a_mappaban(fiok.mappa, s, b"", "") for s in sorszamok):
        er.kihagyva += 1
        return True
    fiok.mappa.mkdir(parents=True, exist_ok=True)
    for e in szamla_elemek:
        if not e["sorszam"] and _ismert_a_mappaban(fiok.mappa, None, e["adat"], e["nev"]):
            continue
        cel = fiok.mappa / e["nev"]
        if cel.exists():
            if cel.read_bytes() == e["adat"]:
                continue
            cel = _szabad_nev(fiok.mappa, e["nev"])
        cel.write_bytes(e["adat"])
        er.mentett.append({"fiok": fiok.sid, "fiok_nev": fiok.nev, "fajl": cel.name, "sorszam": e["sorszam"], "datum": datum})
    ismert |= sorszamok
    return True


# ------------------------------------------------------------------------------------------------ felderítés


FELDERITES_NAPOK = 180
FELDERITES_MAX = 400  # mappánként legfeljebb ennyi (a legújabb) levél


def felderit(
    pf: Postafiok,
    ma: date,
    felado_terkep: dict[str, set[str]],
    napok: int = FELDERITES_NAPOK,
    gyar: Callable[[Postafiok], Any] | None = None,
) -> list[SzamlaJel]:
    """A postafiók számláinak felkutatása (végrehajtó szálon, csak olvas): az utolsó `napok` nap minden mappájában
    (Gmail: Összes levél + Kuka) az ismert szolgáltatói feladók levelei és a PDF/XML mellékletes levelek; a
    mellékleteket a számla-beolvasó olvassa be. Eredmény: a felismert számlák (és Telekom-értesítők) adatai –
    fájlt nem ment (azt a besorolás utáni felzárkózó átnézés teszi). Hibánál EmailHiba."""
    imap = kapcsolodik(pf, gyar)
    talalt: list[SzamlaJel] = []
    try:
        gm = "X-GM-EXT-1" in {str(c).upper() for c in (getattr(imap, "capabilities", None) or ())}
        typ, lista_v = imap.list()
        mappak = felderites_mappak(lista_v if typ == "OK" else [])
        feltetel = kereses_tartalom(sorted(felado_terkep), napok, ma, gm)
        latott: set[str] = set()
        for mappa in mappak:
            typ, _ = imap.select(_idezett(mappa), readonly=True)
            if typ != "OK":
                continue
            typ, ids = imap.uid("SEARCH", *feltetel)
            if typ != "OK":
                continue
            for uid in ((ids[0] or b"").split() if ids else [])[-FELDERITES_MAX:]:
                talalt.extend(_felderit_level(imap, uid, felado_terkep, latott, szerkezet_kell=not gm))
    except EmailHiba:
        raise
    except (imaplib.IMAP4.abort, OSError) as err:
        raise KapcsolatiHiba(f"A kapcsolat megszakadt: {err}") from err
    except imaplib.IMAP4.error as err:
        raise EmailHiba(f"IMAP-hiba: {err}") from err
    finally:
        _kilep(imap)
    return talalt


def _felderit_level(imap: Any, uid: bytes, terkep: dict[str, set[str]], latott: set[str], szerkezet_kell: bool) -> list[SzamlaJel]:
    typ, fej_v = imap.uid("FETCH", uid, FEJLEC_MEZOK)
    fej_b = _uzenet_bajtok(fej_v) if typ == "OK" else None
    if not fej_b:
        return []
    fej = email.message_from_bytes(fej_b, policy=email.policy.default)
    kulcs = level_kulcs(fej)
    if kulcs in latott:
        return []
    latott.add(kulcs)
    cimek = felado_cimek(str(fej.get("From") or ""))
    szolg = felado_szolgaltatok(cimek, terkep)
    if not szolg and szerkezet_kell and not _melleklete_van(imap, uid):
        return []
    typ, adat_v = imap.uid("FETCH", uid, "(BODY.PEEK[])")
    nyers = _uzenet_bajtok(adat_v) if typ == "OK" else None
    if not nyers:
        return []
    uzenet = email.message_from_bytes(nyers, policy=email.policy.default)
    mell = mellekletek(uzenet)
    ki: list[SzamlaJel] = []
    if mell:
        latott_jel: set[tuple[str, str]] = set()
        for e in _elemek(mell, str(fej.get("Subject") or "")):
            jel = e["jel"]
            if jel and (jel.sorszam, jel.forras) not in latott_jel:
                latott_jel.add((jel.sorszam, jel.forras))
                ki.append(jel)
    elif szolg and (adat := ertesito_szamla(torzs_szoveg(uzenet))):
        jel = ertesito_jel(adat, szolg)
        if jel:
            ki.append(jel)
    return ki


@dataclass
class Felderites:
    """A felderítés besorolva: összekötendő fiókok (egyértelmű), kérdések (több jelölt), ajánlatok (nincs fiók)."""

    osszekot: dict[str, dict[str, Any]] = field(default_factory=dict)  # sid → {nev, szamlak, szolgaltato}
    mar_bekotve: dict[str, dict[str, Any]] = field(default_factory=dict)  # kézi szűrővel már bekötött fiókok
    kerdesek: list[dict[str, Any]] = field(default_factory=list)
    ajanlatok: list[dict[str, Any]] = field(default_factory=list)
    talalt: int = 0


def _pelda(jelek: list[SzamlaJel]) -> dict[str, Any]:
    j = max(jelek, key=lambda x: x.kelte or "")
    return {"sorszam": j.sorszam, "kelte": j.kelte, "osszeg": j.osszeg, "db": len(jelek),
            "mero": ", ".join(sorted(j.merok)) or j.meresi_pont or None}


def osztalyoz(jelek: list[SzamlaJel], fiokok: list[AutoFiok], mellozott: set[str] | None = None,
              kezi: set[str] | None = None) -> Felderites:
    """A talált számlák csoportonként (szolgáltató + mérő) besorolva. `mellozott`: a korábban „Egyik sem / Nem
    kell” válaszú csoportok (kihagyjuk). `kezi`: a postafiókhoz már bekötött fiókok (kézi szűrővel vagy
    automatikusan) – nem írjuk át őket, csak jelezzük, hogy ide jönnek a számláik."""
    mellozott, kezi = set(mellozott or ()), set(kezi or ())
    f = Felderites(talalt=len(jelek))
    csoportok: dict[str, list[SzamlaJel]] = {}
    for j in jelek:
        csoportok.setdefault(j.csoport, []).append(j)
    for kulcs, cs in sorted(csoportok.items()):
        if kulcs in mellozott:
            continue
        jel = cs[0]
        jeloltek, ok = tartalom_valasztas(jel, fiokok)
        fiok = egyertelmu(jeloltek, ok)
        if fiok is not None:
            cel = f.mar_bekotve if fiok.sid in kezi else f.osszekot
            x = cel.setdefault(fiok.sid, {"nev": fiok.nev, "szamlak": 0, "tipusok": [], "forrasok": []})
            x["szamlak"] += len(cs)
            if jel.nev not in x["tipusok"]:
                x["tipusok"].append(jel.nev)
                x["forrasok"].append(jel.forras)
            continue
        if jeloltek:
            f.kerdesek.append({"id": kulcs, "nev": jel.nev, "kozmu": jel.kozmu, "ok": ok, **_pelda(cs),
                               "jeloltek": [{"sid": j.sid, "nev": j.nev} for j in jeloltek]})
        else:
            f.ajanlatok.append({"id": kulcs, "nev": jel.nev, "targy": FORRAS_TARGY.get(jel.forras, jel.nev), "kozmu": jel.kozmu, "forras": jel.forras,
                                "szolgaltatok": sorted(jel.szolgaltatok), **_pelda(cs)})
    return f


def _levelnap(fej: EmailMessage) -> str | None:
    try:
        d = fej["Date"].datetime if fej.get("Date") else None
    except (AttributeError, TypeError, ValueError):
        return None
    return d.date().isoformat() if d else None
