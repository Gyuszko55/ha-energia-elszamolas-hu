"""Szigetüzem (és hálózati tartalékos / generátoros) energiarendszer: a háztartás belső energiaáramlásai, kWh-ban.

Külön rendszertípus, nem a HMKE (napelem) bővítése: nincs elszámolás, nincs Ft – csak a mérhető energia
(docs/terv/06_SZIGETUZEM.md, Krissz55555 specifikációja alapján). Alapszabály: csak azt állítjuk tényként,
ami a rendelkezésre álló kWh-számlálókból ténylegesen levezethető.

Forrás: kumulatív (total_increasing) energiaszámlálók. W, A, V, SOC % nem elszámolási alap; W → kWh
integrálás nincs. A nyers szenzorsorozatból `szamlalo_sorozatbol` épít folytonos számlálót (nullázódás,
túlcsordulás, hibás visszaugrás, ismeretlen érték kezelése), `merleg` számolja egy időszak mérlegét.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from .szamlalo import NincsAdat, Pont, Szamlalo, nap_kezdete

# Szerepkörök (csatornák). Kötelező: FOGYASZTAS. Egy szerepkörhöz több forrás is tartozhat (több PV-mező,
# több akkumulátor) – ezek összege számít.
FOGYASZTAS = "fogyasztas"          # load: a rendszer által ellátott fogyasztók összes energiája
PV = "pv"                          # napelem-termelés (összesített vagy MPPT-nként / inverterenként)
AKKU_TOLTES = "akku_toltes"        # akkumulátorba töltött energia
AKKU_KISUTES = "akku_kisutes"      # akkumulátorból kivett energia
HALOZAT = "halozat"                # hálózati vételezés (backup, bypass is)
HALOZAT_AKKU = "halozat_akku"      # hálózatról akkuba (csak ha az inverter külön méri)
EXPORT = "export"                  # hálózatba visszatáplálás (ha a rendszer enged ilyet)
GENERATOR = "generator"            # generátor
EGYEB_TERMELES = "egyeb_termeles"  # pl. szél, víz

FORRASOK = (PV, HALOZAT, GENERATOR, EGYEB_TERMELES)
KULSO = (HALOZAT, GENERATOR)       # külső energia az önellátottsághoz (rögzített definíció)
SZEREPEK = (FOGYASZTAS, PV, AKKU_TOLTES, AKKU_KISUTES, HALOZAT, HALOZAT_AKKU, EXPORT, GENERATOR, EGYEB_TERMELES)

# Ennél kisebb visszaugrás mérési zaj (kerekítés, újraindulás körüli ingadozás), nem nullázódás.
ZAJ_KWH = Decimal("0.5")
ZAJ_ARANY = Decimal("0.001")
EGYSEG_SZORZO = {"Wh": Decimal("0.001"), "kWh": Decimal(1), "MWh": Decimal(1000)}


class Minoseg(StrEnum):
    COMPLETE = "COMPLETE"                  # minden beállított csatorna mért adattal lefedi az időszakot
    ESTIMATED = "ESTIMATED"                # van csatorna, amely hézagban interpolált (becsült)
    PARTIAL = "PARTIAL"                    # egy opcionális csatorna hiányzik, vagy nem minden csatorna fedi le az
                                           # időszakot (a közös mérési ablak később indul) – a többi mutató számolható
    INCONSISTENT = "INCONSISTENT"          # a mérések ellentmondanak egymásnak (pl. hálózat → akku > teljes hálózati vétel)
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # nincs fogyasztás-adat: semmi nem számolható


@dataclass
class Esemeny:
    ido: datetime
    tipus: str  # nullazodas | tulcsordulas | visszaugras | ismeretlen
    leiras: str


def kwh(ertek: Decimal | float | str, egyseg: str = "kWh") -> Decimal:
    """Wh / kWh / MWh → kWh."""
    if egyseg not in EGYSEG_SZORZO:
        raise ValueError(f"nem energia-mértékegység: {egyseg!r} (Wh, kWh vagy MWh kell)")
    d = Decimal(str(ertek))
    if not d.is_finite():  # „nan” / „inf”: ismeretlen érték (a Decimal-összehasonlítás különben hibát dobna)
        raise ValueError(f"nem véges szám: {ertek!r}")
    if d < 0:  # kumulatív számláló nem lehet negatív: hibás érték, nem mérés
        raise ValueError(f"negatív számlálóállás: {ertek!r}")
    return d * EGYSEG_SZORZO[egyseg]


def szamlalo_sorozatbol(
    sorozat: list[tuple[datetime, Decimal | float | str | None]],
    egyseg: str = "kWh",
    tulcsordulas: Decimal | None = None,
    kezdo: tuple[datetime, Decimal] | None = None,
) -> tuple[Szamlalo, list[Esemeny]]:
    """Nyers total_increasing szenzorsorozat → folytonos kWh-számláló (0-ról indul) és a naplózott események.

    - ismeretlen / unavailable (None, nem szám, nan/inf, negatív): kihagyva;
    - kis visszaugrás (≤ 0,5 kWh és ≤ 0,1%): zaj, az addigi legnagyobb értéktől folytatjuk (nem negatív fogyasztás);
    - nagy visszaugrás: nullázódás (inverter-reset, csere, entitáscsere) – az új érték új kiindulópont; ha a
      `tulcsordulas` (a számláló legnagyobb értéke) ismert és az előző érték a közelében volt, a kimaradt rész
      (max − előző) is beszámít;
    - kezdo: kézzel megadott kezdőállás (időpont, nyers érték) – innen indul a követés, előtte nincs adat.
    """
    pontok: list[Pont] = []
    esemenyek: list[Esemeny] = []
    ossz = Decimal(0)
    elozo: Decimal | None = None
    for t, v in sorted(((t, v) for t, v in sorozat), key=lambda x: x[0]):
        if kezdo and t < kezdo[0]:
            continue
        try:
            ertek = kwh(v, egyseg) if v is not None else None
        except (ValueError, ArithmeticError):
            ertek = None
        if ertek is None:
            esemenyek.append(Esemeny(t, "ismeretlen", f"nem szám: {v!r}"))
            continue
        if elozo is None:
            elozo = kwh(kezdo[1], egyseg) if kezdo else ertek
            if kezdo:
                pontok.append(Pont(kezdo[0], Decimal(0), True))
                if ertek < elozo:  # a kezdőállás után azonnal kisebb érték: nullázódás
                    esemenyek.append(Esemeny(t, "nullazodas", f"{elozo} → {ertek} kWh a kezdőállás után"))
                    elozo, ossz = ertek, ossz + ertek
                else:
                    ossz += ertek - elozo
                    elozo = ertek
            pontok.append(Pont(t, ossz, False))
            continue
        d = ertek - elozo
        if d >= 0:
            ossz += d
            elozo = ertek
        elif -d <= ZAJ_KWH and -d <= elozo * ZAJ_ARANY:
            esemenyek.append(Esemeny(t, "visszaugras", f"{elozo} → {ertek} kWh (zaj, kihagyva)"))
            continue  # elozo marad: a következő növekedést az eddigi legnagyobbhoz mérjük
        else:
            kozel = tulcsordulas is not None and elozo >= kwh(tulcsordulas, egyseg) * Decimal("0.9")
            if kozel:
                ossz += kwh(tulcsordulas, egyseg) - elozo + ertek
                esemenyek.append(Esemeny(t, "tulcsordulas", f"{elozo} → {ertek} kWh (a számláló körbefordult)"))
            else:
                ossz += ertek  # nullázódás után 0-ról számol; a mostani érték már a reset óta mért energia
                esemenyek.append(Esemeny(t, "nullazodas", f"{elozo} → {ertek} kWh (új kiindulópont)"))
            elozo = ertek
        pontok.append(Pont(t, ossz, False))
    if pontok:
        pontok[0] = Pont(pontok[0].ido, pontok[0].ertek, True)
    return Szamlalo(pontok), esemenyek


@dataclass
class Rendszer:
    """A beállított csatornák: szerepkörönként a források számlálói (üres lista = nincs ilyen forrás)."""

    csatornak: dict[str, list[Szamlalo]] = field(default_factory=dict)

    def van(self, szerep: str) -> bool:
        return bool(self.csatornak.get(szerep))


@dataclass
class SzigetEredmeny:
    tol: datetime
    ig: datetime
    kezdet: datetime | None  # ha a közös mérési ablak az időszakon belül indul: ettől (minden csatorna ettől számol)
    minoseg: Minoseg
    ertekek: dict[str, Decimal | None]  # szerepkörönként kWh; None = beállított, de nincs adat
    becsult: set[str]
    fogyasztas: Decimal | None
    kulso: Decimal | None
    sajat: Decimal | None  # fogyasztás − külső (a saját rendszerből)
    onellatottsag: Decimal | None  # 0–1
    halozati_reszarany: Decimal | None
    generator_reszarany: Decimal | None
    akku_netto: Decimal | None  # töltés − kisütés (nem hatásfok!)
    merleg_be: Decimal | None
    merleg_ki: Decimal | None
    merleg_elteres: Decimal | None  # be − ki: veszteség, mérési pontok különbsége, akku tárolt energiájának változása
    utvonalak: dict[str, Decimal]  # csak a mérésből levezethető útvonalak
    megjegyzesek: list[str]


def _elso_pont(szamlalok: list[Szamlalo], ig: datetime) -> datetime | None:
    """A szerepkör forrásai közül a legkésőbb induló első mért pontja; None, ha valamelyik forrás ig előtt nem mért."""
    if not szamlalok or any(not sz.pontok or sz.pontok[0].ido >= ig for sz in szamlalok):
        return None
    return max(sz.pontok[0].ido for sz in szamlalok)


def _szerep_ertek(szamlalok: list[Szamlalo], tol: datetime, ig: datetime) -> tuple[Decimal | None, bool]:
    """A források összege [tol, ig)-ra (tol: a közös mérési ablak kezdete, minden forrás mér már ekkor)."""
    ossz, becsult = Decimal(0), False
    for sz in szamlalok:
        try:
            q, b = sz.fogyasztas(tol, ig)
        except NincsAdat:
            return None, False
        ossz += max(q, Decimal(0))
        becsult = becsult or b
    return ossz, becsult


def _kwh_szoveg(x: Decimal) -> str:
    return f"{x:.1f} kWh".replace(".", ",")


def _arany(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None or b <= 0 else a / b


def merleg(rendszer: Rendszer, tol: datetime, ig: datetime) -> SzigetEredmeny:
    """Egy időszak energiamérlege. Hiányzó opcionális csatorna nem teszi számolhatatlanná a többit.

    Minden csatorna ugyanarra a közös mérési ablakra számol: a legkésőbb induló (adattal rendelkező) csatorna első
    pontjától ig-ig – különben pl. a később induló hálózati mérő pár napja a teljes havi fogyasztással szemben hamis
    önellátottságot adna."""
    ertekek: dict[str, Decimal | None] = {}
    becsult: set[str] = set()
    megj: list[str] = []
    kezdopontok: dict[str, datetime] = {}
    for szerep in SZEREPEK:
        if rendszer.van(szerep) and (k := _elso_pont(rendszer.csatornak[szerep], ig)) is not None:
            kezdopontok[szerep] = k
    kozos = max([tol, *kezdopontok.values()])
    kezdet = kozos if kozos > tol else None
    for szerep in SZEREPEK:
        if not rendszer.van(szerep):
            continue
        q, b = _szerep_ertek(rendszer.csatornak[szerep], kozos, ig) if szerep in kezdopontok else (None, False)
        ertekek[szerep] = q
        if b:
            becsult.add(szerep)

    def e(szerep: str) -> Decimal | None:
        """Beállítatlan forrás = 0 (nincs ilyen); beállított, de adat nélküli = None (ismeretlen)."""
        return ertekek.get(szerep) if rendszer.van(szerep) else Decimal(0)

    fogy = ertekek.get(FOGYASZTAS) if rendszer.van(FOGYASZTAS) else None
    hianyzo = [s for s, v in ertekek.items() if v is None]
    # Hálózat → akku nem lehet több a teljes hálózati vételezésnél: mérési vagy beállítási ellentmondás.
    # (Beállított hálózati forrás nélkül a vételezés 0: ilyenkor minden hálózat → akku energia ellentmondás.)
    ellentmondas = bool(rendszer.van(HALOZAT_AKKU) and e(HALOZAT_AKKU) is not None and e(HALOZAT) is not None
                        and e(HALOZAT_AKKU) > e(HALOZAT))
    if fogy is None:
        minoseg = Minoseg.INSUFFICIENT_DATA
    elif ellentmondas:
        minoseg = Minoseg.INCONSISTENT
    elif hianyzo or kezdet:
        minoseg = Minoseg.PARTIAL
    elif becsult:
        minoseg = Minoseg.ESTIMATED
    else:
        minoseg = Minoseg.COMPLETE
    if kezdet:
        megj.append(f"Az energiamérleg követése {kezdet:%Y-%m-%d %H:%M}-tól indul: minden csatorna ettől a közös "
                    "időponttól számol (előtte nem minden beállított csatornán van mérés).")
    if ellentmondas:
        megj.append(f"Ellentmondásos mérés: a hálózat → akku ({_kwh_szoveg(e(HALOZAT_AKKU))}) több a teljes hálózati "
                    f"vételezésnél ({_kwh_szoveg(e(HALOZAT))}). Ellenőrizd a szenzorok szerepkörét és mértékegységét – "
                    "a hálózati útvonalakat ezért nem bontjuk.")

    kulso_reszek = [e(s) for s in KULSO]
    kulso = None if any(x is None for x in kulso_reszek) else sum(kulso_reszek, Decimal(0))
    sajat = onell = h_arany = g_arany = None
    if fogy is not None and kulso is not None and fogy > 0:
        sajat = max(fogy - kulso, Decimal(0))
        onell = min(max(1 - kulso / fogy, Decimal(0)), Decimal(1))
        if kulso > fogy:
            megj.append("A külső energia több a fogyasztásnál (pl. hálózatról töltött akku): az önellátottság 0%.")
    if fogy is not None and fogy > 0:
        # Csak beállított forrásnál: tiszta szigetüzemnél a „hálózati részarány 0%” nem értelmezhető mutató.
        h_arany = _arany(e(HALOZAT), fogy) if rendszer.van(HALOZAT) else None
        g_arany = _arany(e(GENERATOR), fogy) if rendszer.van(GENERATOR) else None

    toltes, kisutes = e(AKKU_TOLTES), e(AKKU_KISUTES)
    van_akku = rendszer.van(AKKU_TOLTES) or rendszer.van(AKKU_KISUTES)
    akku_netto = toltes - kisutes if van_akku and toltes is not None and kisutes is not None else None

    # Energiamérleg: BE = források + akku kisütés, KI = fogyasztás + akku töltés + export. Csak ha minden beállított
    # csatornának van adata; a különbség nem automatikusan akkuveszteség (DC/AC mérési pont, inverter, kábel,
    # sajátfogyasztás, és a tárolt energia időszak eleji/végi különbsége is benne van).
    be = ki = elteres = None
    if fogy is not None and not hianyzo:
        be = sum((e(s) for s in (*FORRASOK, AKKU_KISUTES)), Decimal(0))
        ki = fogy + e(AKKU_TOLTES) + e(EXPORT)
        elteres = be - ki

    # Útvonalak: csak a mérési topológiából egyértelmű része.
    utv: dict[str, Decimal] = {}
    if rendszer.van(HALOZAT_AKKU) and e(HALOZAT_AKKU) is not None and e(HALOZAT) is not None and not ellentmondas:
        utv["halozat_akku"] = e(HALOZAT_AKKU)
        utv["halozat_fogyasztas"] = e(HALOZAT) - e(HALOZAT_AKKU)
    if rendszer.van(PV) and rendszer.van(EXPORT) and not van_akku and e(PV) is not None and e(EXPORT) is not None:
        # Akku nélkül: ami a PV-ből nem ment a hálózatba, az helyben használódott (veszteséggel együtt).
        utv["pv_helyben"] = max(e(PV) - e(EXPORT), Decimal(0))
    if van_akku and rendszer.van(PV):
        megj.append("PV → fogyasztás és PV → akku megosztása a mérésekből nem határozható meg – nem becsüljük.")

    return SzigetEredmeny(
        tol=tol, ig=ig, kezdet=kezdet, minoseg=minoseg, ertekek=ertekek, becsult=becsult, fogyasztas=fogy,
        kulso=kulso, sajat=sajat, onellatottsag=onell, halozati_reszarany=h_arany, generator_reszarany=g_arany,
        akku_netto=akku_netto, merleg_be=be, merleg_ki=ki, merleg_elteres=elteres, utvonalak=utv, megjegyzesek=megj,
    )


def idoszakok(most: datetime, elso: datetime | None = None) -> dict[str, tuple[datetime, datetime]]:
    """A szokásos nézetek [tol, ig) határai; a folyamatban lévők a mostani időpontig."""
    ma = nap_kezdete(most.date())
    ho = nap_kezdete(most.date().replace(day=1))
    elozo_ho = nap_kezdete((most.date().replace(day=1) - timedelta(days=1)).replace(day=1))
    ev = nap_kezdete(date(most.year, 1, 1))
    ki = {
        "ma": (ma, most),
        "tegnap": (ma - timedelta(days=1), ma),
        "honap": (ho, most),
        "elozo_honap": (elozo_ho, ho),
        "ev": (ev, most),
        "elozo_ev": (nap_kezdete(date(most.year - 1, 1, 1)), ev),
    }
    if elso is not None:
        ki["osszesen"] = (elso, most)
    return ki


def honapok(tol: date, ig: date) -> list[tuple[datetime, datetime]]:
    """Naptári hónapok [tol, ig) között (havi bontáshoz)."""
    ki, h = [], tol.replace(day=1)
    while h < ig:
        kov = h.replace(day=calendar.monthrange(h.year, h.month)[1]) + timedelta(days=1)
        ki.append((nap_kezdete(max(h, tol)), nap_kezdete(min(kov, ig))))
        h = kov
    return ki
